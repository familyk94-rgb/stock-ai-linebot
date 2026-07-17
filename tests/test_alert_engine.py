from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from core.alert_engine import AlertEngine
from core.models.alert_trigger import AlertTrigger
from services.alert_service import AlertService
from services.repositories.alert_repository import AlertRepository


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))


def _setup(tmp_path):
    repository = AlertRepository(tmp_path / "alerts.db")
    service = AlertService(repository)
    engine = AlertEngine(repository, clock=lambda: NOW)
    return repository, service, engine


def test_gt_dedup_reset_and_retrigger(tmp_path):
    repository, service, engine = _setup(tmp_path)
    alert = service.add_alert("user-1", "2330", "GT", "1000")

    assert engine.check_alerts("2330", {"price": "995"}) == []
    first = engine.check_alerts("2330", {"price": "1001"})
    assert len(first) == 1
    assert first[0].condition == "GT"
    assert first[0].target_price == Decimal("1000")
    assert first[0].current_price == Decimal("1001")
    assert engine.check_alerts("2330", {"price": "1003"}) == []
    assert engine.check_alerts("2330", {"price": "999"}) == []
    assert repository.get_alert(alert["id"])["is_active"] is False
    assert len(engine.check_alerts("2330", {"price": "1002"})) == 1


def test_lt_dedup_reset_and_retrigger(tmp_path):
    repository, service, engine = _setup(tmp_path)
    alert = service.add_alert("user-1", "2330", "LT", "1000")

    assert engine.check_alerts("2330", {"price": "1005"}) == []
    assert len(engine.check_alerts("2330", {"price": "999"})) == 1
    assert engine.check_alerts("2330", {"price": "995"}) == []
    assert engine.check_alerts("2330", {"price": "1001"}) == []
    assert repository.get_alert(alert["id"])["is_active"] is False
    assert len(engine.check_alerts("2330", {"price": "998"})) == 1


def test_equal_price_does_not_trigger(tmp_path):
    _, service, engine = _setup(tmp_path)
    service.add_alert("user-1", "2330", "GT", "1000")
    service.add_alert("user-2", "2330", "LT", "1000")
    assert engine.check_alerts("2330", {"price": "1000"}) == []


def test_disabled_alert_does_not_trigger(tmp_path):
    _, service, engine = _setup(tmp_path)
    alert = service.add_alert("user-1", "2330", "GT", "1000")
    assert service.disable_alert("user-1", alert["id"])
    assert engine.check_alerts("2330", {"price": "1001"}) == []


def test_multiple_users_and_alerts_trigger_independently(tmp_path):
    _, service, engine = _setup(tmp_path)
    service.add_alert("user-1", "2330", "GT", "900")
    service.add_alert("user-1", "2330", "GT", "950")
    service.add_alert("user-2", "2330", "GT", "990")
    triggers = engine.check_alerts("2330", {"price": "1000"})
    assert len(triggers) == 3
    assert {item.line_user_id for item in triggers} == {"user-1", "user-2"}


def test_other_stock_is_not_evaluated(tmp_path):
    repository, service, engine = _setup(tmp_path)
    alert = service.add_alert("user-1", "2454", "GT", "100")
    assert engine.check_alerts("2330", {"price": "200"}) == []
    assert repository.get_alert(alert["id"])["is_active"] is False


@pytest.mark.parametrize(
    "quote",
    [None, {}, {"price": None}, {"price": True}, {"price": "NaN"}, {"price": "Infinity"}, {"price": "bad"}, {"price": 0}, {"price": -1}],
)
def test_missing_or_invalid_quote_price_returns_empty(tmp_path, quote):
    _, service, engine = _setup(tmp_path)
    service.add_alert("user-1", "2330", "GT", "1000")
    assert engine.check_alerts("2330", quote) == []


@pytest.mark.parametrize("stock_id", [None, "", "ABCD", "２３３０"])
def test_invalid_stock_id_returns_empty_without_repository_lookup(stock_id):
    class NoLookupRepository:
        def get_enabled_alerts(self, symbol):
            pytest.fail("repository should not be queried")

    assert AlertEngine(NoLookupRepository()).check_alerts(
        stock_id, {"price": "1001"}
    ) == []


def test_numeric_float_is_converted_to_decimal_before_comparison(tmp_path):
    _, service, engine = _setup(tmp_path)
    service.add_alert("user-1", "2330", "GT", Decimal("0.2"))
    trigger = engine.check_alerts("2330", {"price": 0.3})[0]
    assert trigger.current_price == Decimal("0.3")
    assert isinstance(trigger.current_price, Decimal)
    assert isinstance(trigger.target_price, Decimal)


def test_alert_trigger_is_frozen_slotted_and_timezone_aware(tmp_path):
    _, service, engine = _setup(tmp_path)
    service.add_alert("user-1", "2330", "GT", "1000")
    trigger = engine.check_alerts("2330", {"price": "1001"})[0]
    assert isinstance(trigger, AlertTrigger)
    assert not hasattr(trigger, "__dict__")
    with pytest.raises(FrozenInstanceError):
        trigger.current_price = Decimal("2")
    parsed = datetime.fromisoformat(trigger.triggered_at)
    assert parsed.utcoffset() is not None


def test_engine_does_not_modify_quote(tmp_path):
    _, service, engine = _setup(tmp_path)
    service.add_alert("user-1", "2330", "GT", "1000")
    quote = {"price": "1001", "provider": "fubon_neo", "nested": {"x": 1}}
    original = deepcopy(quote)
    engine.check_alerts("2330", quote)
    assert quote == original


def test_repository_error_propagates_instead_of_returning_empty():
    class BrokenRepository:
        def get_enabled_alerts(self, stock_id):
            raise RuntimeError("database unavailable")

    engine = AlertEngine(BrokenRepository(), clock=lambda: NOW)
    with pytest.raises(RuntimeError, match="database unavailable"):
        engine.check_alerts("2330", {"price": "1001"})


def test_trigger_contains_only_fixed_safe_fields(tmp_path):
    _, service, engine = _setup(tmp_path)
    service.add_alert("user-1", "2330", "GT", "1000")
    trigger = engine.check_alerts("2330", {"price": "1001"})[0]
    assert trigger.__slots__ == (
        "alert_id", "line_user_id", "stock_id", "condition",
        "target_price", "current_price", "triggered_at",
    )
