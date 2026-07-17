from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from core.alert_engine import AlertEngine
from core.notification_dispatcher import NotificationDispatcher
from services.alert_runtime_service import AlertRuntimeService
from services.providers.fubon_neo_quote import AdapterResult
from services.providers.quote import Quote
from services.repositories.alert_repository import AlertRepository


class MutableQuoteProvider:
    def __init__(self, prices):
        self.prices = dict(prices)
        self.calls = []

    def get_quote(self, stock_id):
        self.calls.append(stock_id)
        return AdapterResult(
            True,
            Quote(
                provider="test", symbol=stock_id, market="TWSE", timestamp=None,
                status="closed", price=self.prices[stock_id], reference=None,
                change=None, change_percent=None, open=None, high=None, low=None,
                volume=None, is_realtime=False, data_quality="incomplete",
            ),
            "success",
        )


class RecordingSender:
    channel = "line"

    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)


def _add(repository, user, stock, condition, price):
    return repository.add_alert(
        line_user_id=user, stock_id=stock, condition=condition,
        target_price=Decimal(price), created_at="2026-07-17T10:00:00+08:00",
    )


def _runtime(tmp_path, prices):
    repository = AlertRepository(tmp_path / "alerts.db")
    provider = MutableQuoteProvider(prices)
    sender = RecordingSender()
    engine = AlertEngine(
        repository,
        clock=lambda: datetime(2026, 7, 17, 18, 24, tzinfo=ZoneInfo("Asia/Taipei")),
    )
    runtime = AlertRuntimeService(
        alert_repository=repository, quote_provider=provider,
        alert_engine=engine,
        notification_dispatcher=NotificationDispatcher([sender]),
    )
    return repository, provider, sender, runtime


def test_gt_runtime_dedup_reset_and_retrigger(tmp_path):
    repository, provider, sender, runtime = _runtime(tmp_path, {"2330": 101})
    _add(repository, "U1", "2330", "GT", "100")

    first = runtime.run_once()
    second = runtime.run_once()
    provider.prices["2330"] = 99
    reset = runtime.run_once()
    provider.prices["2330"] = 101
    retrigger = runtime.run_once()

    assert [first.triggers_created, second.triggers_created, reset.triggers_created, retrigger.triggers_created] == [1, 0, 0, 1]
    assert [event.recipient_id for event in sender.events] == ["U1", "U1"]
    assert provider.calls == ["2330", "2330", "2330", "2330"]
    assert all(report.stocks_requested == 1 for report in (first, second, reset, retrigger))


def test_lt_dedup_reset_retrigger_and_multiple_users_share_one_quote_per_run(tmp_path):
    repository, provider, sender, runtime = _runtime(tmp_path, {"2330": 89})
    _add(repository, "U1", "2330", "LT", "90")
    _add(repository, "U2", "2330", "LT", "95")

    first = runtime.run_once()
    second = runtime.run_once()
    provider.prices["2330"] = 96
    reset = runtime.run_once()
    provider.prices["2330"] = 89
    retrigger = runtime.run_once()

    assert [
        first.triggers_created,
        second.triggers_created,
        reset.triggers_created,
        retrigger.triggers_created,
    ] == [2, 0, 0, 2]
    assert first.notifications_succeeded == 2
    assert retrigger.notifications_succeeded == 2
    assert provider.calls == ["2330", "2330", "2330", "2330"]
    assert [event.recipient_id for event in sender.events] == ["U1", "U2", "U1", "U2"]
    assert all(event.current_price == Decimal("89") for event in sender.events)


def test_disabled_alert_is_not_queried_and_reports_do_not_accumulate(tmp_path):
    repository, provider, sender, runtime = _runtime(tmp_path, {"2317": 200, "2330": 101})
    disabled = _add(repository, "U0", "2317", "GT", "100")
    repository.disable_alert(disabled["id"], "U0")
    _add(repository, "U1", "2330", "GT", "100")

    first = runtime.run_once()
    second = runtime.run_once()

    assert provider.calls == ["2330", "2330"]
    assert first.triggers_created == 1
    assert second.triggers_created == 0
    assert first.dispatch_report is not None
    assert second.dispatch_report is None
    assert len(sender.events) == 1
