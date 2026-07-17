"""Single-run coordinator for quote checks and alert notification dispatch."""

from __future__ import annotations

from core.models.alert_runtime_result import AlertRuntimeReport, StockCheckResult
from core.models.alert_trigger import AlertTrigger
from core.models.notification_event import NotificationEvent
from services.providers.fubon_neo_quote import AdapterResult


class AlertRuntimeService:
    def __init__(
        self,
        *,
        alert_repository,
        quote_provider,
        alert_engine,
        notification_dispatcher,
        notification_channel: str = "line",
    ) -> None:
        for name, dependency in (
            ("alert_repository", alert_repository),
            ("quote_provider", quote_provider),
            ("alert_engine", alert_engine),
            ("notification_dispatcher", notification_dispatcher),
        ):
            if dependency is None:
                raise TypeError(f"{name} is required")
        if not isinstance(notification_channel, str) or not notification_channel.strip():
            raise ValueError("notification_channel must be nonblank")
        self._alert_repository = alert_repository
        self._quote_provider = quote_provider
        self._alert_engine = alert_engine
        self._notification_dispatcher = notification_dispatcher
        self._notification_channel = notification_channel.strip()

    def run_once(self) -> AlertRuntimeReport:
        stock_ids = tuple(sorted(set(self._alert_repository.list_enabled_stock_ids())))
        stock_results = []
        events = []

        for stock_id in stock_ids:
            try:
                quote_result = self._quote_provider.get_quote(stock_id)
            except Exception as error:
                stock_results.append(_failed_stock(stock_id, False, "quote", error))
                continue

            if (
                not isinstance(quote_result, AdapterResult)
                or not quote_result.ok
                or quote_result.quote is None
            ):
                stock_results.append(
                    StockCheckResult(
                        stock_id=stock_id,
                        quote_fetched=False,
                        trigger_count=0,
                        error_type="QuoteUnavailableError",
                        error_message="quote fetch failed",
                    )
                )
                continue

            try:
                triggers = self._alert_engine.check_alerts(
                    stock_id, quote_result.quote
                )
                if not isinstance(triggers, list) or any(
                    not isinstance(trigger, AlertTrigger) for trigger in triggers
                ):
                    raise TypeError("invalid alert engine result")
                triggers = sorted(triggers, key=lambda trigger: trigger.alert_id)
                stock_events = [
                    NotificationEvent.from_alert_trigger(trigger)
                    for trigger in triggers
                ]
            except Exception as error:
                stock_results.append(_failed_stock(stock_id, True, "alert check", error))
                continue

            events.extend(stock_events)
            stock_results.append(
                StockCheckResult(
                    stock_id=stock_id,
                    quote_fetched=True,
                    trigger_count=len(stock_events),
                )
            )

        dispatch_report = None
        if events:
            dispatch_report = self._notification_dispatcher.dispatch(
                events,
                channel=self._notification_channel,
            )

        stocks_succeeded = sum(result.succeeded for result in stock_results)
        notifications_attempted = len(events)
        return AlertRuntimeReport(
            stocks_requested=len(stock_results),
            stocks_succeeded=stocks_succeeded,
            stocks_failed=len(stock_results) - stocks_succeeded,
            triggers_created=notifications_attempted,
            notifications_attempted=notifications_attempted,
            notifications_succeeded=(dispatch_report.succeeded if dispatch_report else 0),
            notifications_failed=(dispatch_report.failed if dispatch_report else 0),
            stock_results=tuple(stock_results),
            dispatch_report=dispatch_report,
        )


def _failed_stock(stock_id: str, quote_fetched: bool, stage: str, error: Exception):
    return StockCheckResult(
        stock_id=stock_id,
        quote_fetched=quote_fetched,
        trigger_count=0,
        error_type=type(error).__name__,
        error_message=f"{stage} failed: {type(error).__name__}",
    )
