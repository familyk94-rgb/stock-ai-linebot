"""Immutable notification dispatch result contracts."""

from dataclasses import dataclass


MAX_DISPATCH_ERROR_MESSAGE_LENGTH = 160


@dataclass(frozen=True, slots=True)
class DispatchItemResult:
    alert_id: int
    recipient_id: str
    channel: str
    success: bool
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        _positive_int(self.alert_id, "alert_id")
        _nonblank(self.recipient_id, "recipient_id")
        _nonblank(self.channel, "channel")
        if not isinstance(self.success, bool):
            raise TypeError("success must be bool")
        if self.success:
            if self.error_type is not None or self.error_message is not None:
                raise ValueError("successful result cannot contain error details")
        else:
            _nonblank(self.error_type, "error_type")
            _nonblank(self.error_message, "error_message")
            if len(self.error_message) > MAX_DISPATCH_ERROR_MESSAGE_LENGTH:
                raise ValueError("error_message is too long")


@dataclass(frozen=True, slots=True)
class DispatchReport:
    channel: str
    attempted: int
    succeeded: int
    failed: int
    results: tuple[DispatchItemResult, ...]

    def __post_init__(self) -> None:
        _nonblank(self.channel, "channel")
        for field, value in (
            ("attempted", self.attempted),
            ("succeeded", self.succeeded),
            ("failed", self.failed),
        ):
            _nonnegative_int(value, field)
        if not isinstance(self.results, tuple):
            raise TypeError("results must be tuple")
        if self.attempted != self.succeeded + self.failed:
            raise ValueError("attempted must equal succeeded plus failed")
        if self.attempted != len(self.results):
            raise ValueError("attempted must equal result count")
        for result in self.results:
            if not isinstance(result, DispatchItemResult):
                raise TypeError("results must contain DispatchItemResult")
            if result.channel != self.channel:
                raise ValueError("result channel must match report channel")
        actual_succeeded = sum(result.success for result in self.results)
        if self.succeeded != actual_succeeded:
            raise ValueError("succeeded must match successful result count")
        if self.failed != self.attempted - actual_succeeded:
            raise ValueError("failed must match failed result count")


def _positive_int(value, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


def _nonnegative_int(value, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")


def _nonblank(value, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
