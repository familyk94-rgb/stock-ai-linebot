"""Immutable contracts for one alert runtime execution."""

from __future__ import annotations

from dataclasses import dataclass

from core.models.dispatch_result import DispatchReport


@dataclass(frozen=True, slots=True)
class StockCheckResult:
    stock_id: str
    quote_fetched: bool
    trigger_count: int
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        _nonblank(self.stock_id, "stock_id")
        if not isinstance(self.quote_fetched, bool):
            raise TypeError("quote_fetched must be bool")
        _nonnegative_int(self.trigger_count, "trigger_count")
        has_type = self.error_type is not None
        has_message = self.error_message is not None
        if has_type != has_message:
            raise ValueError("error_type and error_message must appear together")
        if has_type:
            _nonblank(self.error_type, "error_type")
            _nonblank(self.error_message, "error_message")
            if self.trigger_count != 0:
                raise ValueError("failed stock result cannot contain triggers")
        elif not self.quote_fetched:
            raise ValueError("successful stock result requires a fetched quote")

    @property
    def succeeded(self) -> bool:
        return self.error_type is None


@dataclass(frozen=True, slots=True)
class AlertRuntimeReport:
    stocks_requested: int
    stocks_succeeded: int
    stocks_failed: int
    triggers_created: int
    notifications_attempted: int
    notifications_succeeded: int
    notifications_failed: int
    stock_results: tuple[StockCheckResult, ...]
    dispatch_report: DispatchReport | None

    def __post_init__(self) -> None:
        for field, value in (
            ("stocks_requested", self.stocks_requested),
            ("stocks_succeeded", self.stocks_succeeded),
            ("stocks_failed", self.stocks_failed),
            ("triggers_created", self.triggers_created),
            ("notifications_attempted", self.notifications_attempted),
            ("notifications_succeeded", self.notifications_succeeded),
            ("notifications_failed", self.notifications_failed),
        ):
            _nonnegative_int(value, field)
        if not isinstance(self.stock_results, tuple):
            raise TypeError("stock_results must be tuple")
        if any(not isinstance(item, StockCheckResult) for item in self.stock_results):
            raise TypeError("stock_results must contain StockCheckResult")
        if self.stocks_requested != self.stocks_succeeded + self.stocks_failed:
            raise ValueError("stocks_requested must equal succeeded plus failed")
        if self.stocks_requested != len(self.stock_results):
            raise ValueError("stocks_requested must equal stock result count")
        if self.stocks_succeeded != sum(item.succeeded for item in self.stock_results):
            raise ValueError("stocks_succeeded must match stock results")
        if self.notifications_attempted != (
            self.notifications_succeeded + self.notifications_failed
        ):
            raise ValueError("notifications_attempted must equal succeeded plus failed")
        if self.triggers_created != self.notifications_attempted:
            raise ValueError("each trigger must correspond to one notification attempt")
        if self.triggers_created != sum(item.trigger_count for item in self.stock_results):
            raise ValueError("triggers_created must match stock trigger counts")
        if self.dispatch_report is None:
            if self.notifications_attempted != 0:
                raise ValueError("dispatch_report is required when notifications are attempted")
        else:
            if not isinstance(self.dispatch_report, DispatchReport):
                raise TypeError("dispatch_report must be DispatchReport or None")
            if (
                self.dispatch_report.attempted != self.notifications_attempted
                or self.dispatch_report.succeeded != self.notifications_succeeded
                or self.dispatch_report.failed != self.notifications_failed
            ):
                raise ValueError("notification totals must match dispatch_report")


def _nonnegative_int(value, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")


def _nonblank(value, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
