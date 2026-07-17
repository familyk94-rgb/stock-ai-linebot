from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from core.models.alert_runtime_result import AlertRuntimeReport, StockCheckResult
from core.models.alert_trigger import AlertTrigger
from core.models.dispatch_result import DispatchItemResult, DispatchReport
from core.notification_dispatcher import UnknownNotificationChannelError
from services.alert_runtime_service import AlertRuntimeService
from services.providers.fubon_neo_quote import AdapterResult
from services.providers.quote import Quote


def _quote(symbol):
    return Quote(
        provider="test", symbol=symbol, market="TWSE", timestamp=None,
        status="closed", price=100, reference=99, change=1,
        change_percent=1, open=99, high=101, low=98, volume=1000,
        is_realtime=False, data_quality="delayed",
    )


def _trigger(alert_id=1, stock_id="2330", user="U1"):
    return AlertTrigger(
        alert_id=alert_id, line_user_id=user, stock_id=stock_id,
        condition="GT", target_price=Decimal("99"),
        current_price=Decimal("100"),
        triggered_at="2026-07-17T18:24:00+08:00",
    )


class Repository:
    def __init__(self, stock_ids):
        self.stock_ids = stock_ids
        self.calls = 0

    def list_enabled_stock_ids(self):
        self.calls += 1
        return list(self.stock_ids)


class QuoteProvider:
    def __init__(self, results=None, failures=None):
        self.results = results or {}
        self.failures = failures or {}
        self.calls = []

    def get_quote(self, stock_id):
        self.calls.append(stock_id)
        if stock_id in self.failures:
            raise self.failures[stock_id]
        return self.results.get(
            stock_id, AdapterResult(True, _quote(stock_id), "success")
        )


class Engine:
    def __init__(self, triggers=None, failures=None):
        self.triggers = triggers or {}
        self.failures = failures or {}
        self.calls = []

    def check_alerts(self, stock_id, quote):
        self.calls.append((stock_id, quote))
        if stock_id in self.failures:
            raise self.failures[stock_id]
        return list(self.triggers.get(stock_id, []))


class Dispatcher:
    def __init__(self, failed_ids=(), error=None):
        self.failed_ids = set(failed_ids)
        self.error = error
        self.calls = []
        self.reports = []

    def dispatch(self, events, *, channel):
        events = tuple(events)
        self.calls.append((events, channel))
        if self.error:
            raise self.error
        results = tuple(
            DispatchItemResult(
                alert_id=event.alert_id, recipient_id=event.recipient_id,
                channel=channel, success=event.alert_id not in self.failed_ids,
                error_type=("SendError" if event.alert_id in self.failed_ids else None),
                error_message=("send failed" if event.alert_id in self.failed_ids else None),
            )
            for event in events
        )
        succeeded = sum(item.success for item in results)
        report = DispatchReport(
            channel, len(results), succeeded, len(results) - succeeded, results
        )
        self.reports.append(report)
        return report


def _service(stock_ids=(), *, provider=None, engine=None, dispatcher=None, channel="line"):
    return AlertRuntimeService(
        alert_repository=Repository(stock_ids),
        quote_provider=provider or QuoteProvider(),
        alert_engine=engine or Engine(),
        notification_dispatcher=dispatcher or Dispatcher(),
        notification_channel=channel,
    )


def test_result_dtos_are_frozen_slotted_and_validate_invariants():
    stock = StockCheckResult("2330", True, 0)
    report = AlertRuntimeReport(1, 1, 0, 0, 0, 0, 0, (stock,), None)
    assert report.stock_results == (stock,)
    assert not hasattr(stock, "__dict__")
    assert not hasattr(report, "__dict__")
    with pytest.raises(FrozenInstanceError):
        stock.stock_id = "2454"
    with pytest.raises(ValueError):
        StockCheckResult("2330", True, -1)
    with pytest.raises(ValueError):
        StockCheckResult("2330", False, 0, "Error", None)
    with pytest.raises(ValueError):
        StockCheckResult("2330", False, 0)
    with pytest.raises(ValueError):
        AlertRuntimeReport(1, 0, 0, 0, 0, 0, 0, (stock,), None)
    with pytest.raises(TypeError):
        AlertRuntimeReport(0, 0, 0, 0, 0, 0, 0, [], None)


def test_empty_flow_calls_only_repository_and_returns_fixed_empty_report():
    repository = Repository([])
    provider, engine, dispatcher = QuoteProvider(), Engine(), Dispatcher()
    service = AlertRuntimeService(
        alert_repository=repository, quote_provider=provider,
        alert_engine=engine, notification_dispatcher=dispatcher,
    )

    report = service.run_once()

    assert report == AlertRuntimeReport(0, 0, 0, 0, 0, 0, 0, (), None)
    assert repository.calls == 1
    assert provider.calls == []
    assert engine.calls == []
    assert dispatcher.calls == []


def test_stable_deduplicated_stock_and_event_order_with_single_dispatch():
    provider = QuoteProvider()
    engine = Engine({
        "2330": [_trigger(2, "2330", "U2"), _trigger(1, "2330", "U1")],
        "2454": [_trigger(3, "2454", "U3")],
    })
    dispatcher = Dispatcher()
    service = _service(
        ["2454", "2330", "2330"],
        provider=provider,
        engine=engine,
        dispatcher=dispatcher,
    )

    report = service.run_once()

    assert provider.calls == ["2330", "2454"]
    assert [call[0] for call in engine.calls] == ["2330", "2454"]
    events, channel = dispatcher.calls[0]
    assert channel == "line"
    assert [event.alert_id for event in events] == [1, 2, 3]
    assert [event.recipient_id for event in events] == ["U1", "U2", "U3"]
    assert events[0].target_price == Decimal("99")
    assert events[0].triggered_at == "2026-07-17T18:24:00+08:00"
    assert (report.triggers_created, report.notifications_attempted) == (3, 3)


def test_no_trigger_does_not_call_dispatcher_and_custom_channel_is_forwarded():
    dispatcher = Dispatcher()
    empty = _service(["2330"], dispatcher=dispatcher).run_once()
    assert empty.stock_results == (StockCheckResult("2330", True, 0),)
    assert empty.dispatch_report is None
    assert dispatcher.calls == []

    dispatcher = Dispatcher()
    report = _service(
        ["2330"],
        engine=Engine({"2330": [_trigger()]}),
        dispatcher=dispatcher,
        channel="custom",
    ).run_once()
    assert dispatcher.calls[0][1] == "custom"
    assert report.dispatch_report.channel == "custom"


@pytest.mark.parametrize("failed_ids,expected", [([], (2, 0)), ([1], (1, 1)), ([1, 2], (0, 2))])
def test_notification_totals_follow_dispatch_report(failed_ids, expected):
    engine = Engine({"2330": [_trigger(1), _trigger(2, user="U2")]})
    dispatcher = Dispatcher(failed_ids)
    report = _service(["2330"], engine=engine, dispatcher=dispatcher).run_once()
    assert (report.notifications_succeeded, report.notifications_failed) == expected
    assert report.dispatch_report is not None
    assert report.dispatch_report.attempted == 2
    assert report.dispatch_report.succeeded == expected[0]
    assert report.dispatch_report.failed == expected[1]
    assert report.dispatch_report is dispatcher.reports[0]


def test_quote_and_engine_failures_are_isolated_and_sanitized():
    provider = QuoteProvider(failures={"2317": TimeoutError("token=secret payload")})
    engine = Engine(
        triggers={"2454": [_trigger(3, "2454")]},
        failures={"2330": RuntimeError("Authorization: Bearer secret")},
    )
    dispatcher = Dispatcher()
    report = _service(
        ["2317", "2330", "2454"], provider=provider,
        engine=engine, dispatcher=dispatcher,
    ).run_once()

    assert (report.stocks_requested, report.stocks_succeeded, report.stocks_failed) == (3, 1, 2)
    assert [result.error_type for result in report.stock_results] == [
        "TimeoutError", "RuntimeError", None
    ]
    messages = " ".join(result.error_message or "" for result in report.stock_results)
    assert "secret" not in messages
    assert "token" not in messages
    assert "Authorization" not in messages
    assert [call[0] for call in engine.calls] == ["2330", "2454"]
    assert dispatcher.calls[0][0][0].stock_id == "2454"


def test_safe_unavailable_quote_does_not_call_engine():
    provider = QuoteProvider({"2330": AdapterResult(False, None, "secret_reason")})
    engine = Engine()
    report = _service(["2330"], provider=provider, engine=engine).run_once()
    assert report.stock_results[0].error_type == "QuoteUnavailableError"
    assert report.stock_results[0].error_message == "quote fetch failed"
    assert engine.calls == []


def test_invalid_alert_engine_result_is_isolated():
    class InvalidEngine:
        def check_alerts(self, stock_id, quote):
            return (_trigger(),)

    report = _service(["2330"], engine=InvalidEngine()).run_once()
    result = report.stock_results[0]
    assert result.quote_fetched is True
    assert result.trigger_count == 0
    assert result.error_type == "TypeError"
    assert result.error_message == "alert check failed: TypeError"
    assert report.dispatch_report is None


def test_repository_failure_and_unknown_channel_propagate():
    class BrokenRepository:
        def list_enabled_stock_ids(self):
            raise RuntimeError("database failed")

    service = AlertRuntimeService(
        alert_repository=BrokenRepository(), quote_provider=QuoteProvider(),
        alert_engine=Engine(), notification_dispatcher=Dispatcher(),
    )
    with pytest.raises(RuntimeError, match="database failed"):
        service.run_once()

    unknown = UnknownNotificationChannelError("unknown")
    with pytest.raises(UnknownNotificationChannelError):
        _service(
            ["2330"], engine=Engine({"2330": [_trigger()]}),
            dispatcher=Dispatcher(error=unknown),
        ).run_once()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(), GeneratorExit()])
def test_base_exceptions_are_not_caught(error):
    provider = QuoteProvider(failures={"2330": error})
    with pytest.raises(type(error)):
        _service(["2330"], provider=provider).run_once()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(), GeneratorExit()])
def test_alert_engine_base_exceptions_are_not_caught(error):
    engine = Engine(failures={"2330": error})
    with pytest.raises(type(error)):
        _service(["2330"], engine=engine).run_once()
