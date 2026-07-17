from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.models.alert_creation import AlertCreationStep
from services.alert_creation_service import AlertCreationService, format_price
from services.alert_creation_state_store import AlertCreationStateStore


class Repo:
    def __init__(self):
        self.rows = []
        self.raise_create = False

    def exists_active_alert(self, user, stock, condition, target):
        return any(r["line_user_id"] == user and r["stock_id"] == stock and r["condition"] == condition and r["target_price"] == target and r["enabled"] for r in self.rows)

    def add_alert(self, **kwargs):
        if self.raise_create: raise RuntimeError("database path secret")
        row = {"id": len(self.rows) + 1, "enabled": True, "is_active": False, **kwargs}
        self.rows.append(row)
        return row


def _service(repo=None, resolver=lambda _: "台積電", clock=None):
    now = clock or (lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    store = AlertCreationStateStore(clock=now)
    return AlertCreationService(repo or Repo(), store, resolver, now), store


def _to_confirmation(service, user="u1", condition="股價突破", target="1150"):
    service.start(user)
    service.receive_stock_id(user, "2330")
    service.select_condition(user, condition)
    return service.receive_target(user, target)


def test_start_and_restart_reset_all_fields():
    service, _ = _service()
    assert service.start("u1").session.step is AlertCreationStep.AWAITING_STOCK_ID
    _to_confirmation(service)
    result = service.restart("u1")
    assert result.status == "started" and result.session.stock_id is None


@pytest.mark.parametrize("value", ["", "123", "1234567", "ABCD", "-2330", "23.30"])
def test_invalid_stock_format_stays_on_stock_step(value):
    service, _ = _service(); service.start("u1")
    result = service.receive_stock_id("u1", value)
    assert result.status == "invalid_input"
    assert result.session.step is AlertCreationStep.AWAITING_STOCK_ID


@pytest.mark.parametrize("resolver", [lambda _: "未知股票", lambda _: "2330", lambda _: "?unknown", lambda _: ""])
def test_unknown_stock_is_rejected(resolver):
    service, _ = _service(resolver=resolver); service.start("u1")
    assert service.receive_stock_id("u1", "2330").error_code == "stock_not_found"


def test_resolver_exception_is_safe_and_called_once():
    calls = []
    def resolver(stock): calls.append(stock); raise RuntimeError("network secret")
    service, _ = _service(resolver=resolver); service.start("u1")
    result = service.receive_stock_id("u1", "2330")
    assert result.error_code == "stock_lookup_failed" and calls == ["2330"]


@pytest.mark.parametrize(("text", "expected"), [("股價突破", "GT"), ("突破", "GT"), ("gt", "GT"), ("股價跌破", "LT"), ("跌破", "LT"), ("lt", "LT")])
def test_condition_mapping(text, expected):
    service, _ = _service(); service.start("u1"); service.receive_stock_id("u1", "2330")
    result = service.select_condition("u1", text)
    assert result.session.condition == expected


def test_unknown_condition_does_not_advance():
    service, _ = _service(); service.start("u1"); service.receive_stock_id("u1", "2330")
    result = service.select_condition("u1", "EQ")
    assert result.session.step is AlertCreationStep.AWAITING_CONDITION


@pytest.mark.parametrize(("value", "formatted"), [("1150", "1150"), ("55.50", "55.5"), ("0.01", "0.01")])
def test_valid_decimal_target(value, formatted):
    service, _ = _service(); service.start("u1"); service.receive_stock_id("u1", "2330"); service.select_condition("u1", "GT")
    result = service.receive_target("u1", value)
    assert result.status == "awaiting_confirmation" and format_price(result.session.target_price) == formatted


@pytest.mark.parametrize("value", ["", "0", "-1", "NaN", "Infinity", "1e3", "1,000", "中文", "10000000.01", True])
def test_invalid_target_does_not_advance(value):
    service, _ = _service(); service.start("u1"); service.receive_stock_id("u1", "2330"); service.select_condition("u1", "GT")
    result = service.receive_target("u1", value)
    assert result.session.step is AlertCreationStep.AWAITING_TARGET


def test_wrong_step_confirm_does_not_create():
    repo = Repo(); service, _ = _service(repo); service.start("u1")
    assert service.confirm("u1").error_code == "invalid_step" and repo.rows == []


def test_confirm_creates_once_enriches_name_and_clears_session():
    repo = Repo(); service, store = _service(repo); _to_confirmation(service)
    result = service.confirm("u1")
    assert result.status == "created" and result.created_alert["stock_name"] == "台積電"
    assert len(repo.rows) == 1 and not store.has("u1")


def test_duplicate_preserves_confirmation_session():
    repo = Repo(); service, store = _service(repo); _to_confirmation(service); repo.rows.append({"line_user_id":"u1", "stock_id":"2330", "condition":"GT", "target_price":Decimal("1150"), "enabled":True})
    result = service.confirm("u1")
    assert result.status == "duplicate" and store.has("u1") and len(repo.rows) == 1


def test_repository_failure_is_safe_and_preserves_session():
    repo = Repo(); repo.raise_create = True; service, store = _service(repo); _to_confirmation(service)
    result = service.confirm("u1")
    assert result.status == "failed" and "secret" not in result.message and store.has("u1")


def test_cancel_and_missing_cancel():
    service, store = _service(); service.start("u1")
    assert service.cancel("u1").message == "已取消提醒設定。" and not store.has("u1")
    assert service.cancel("u1").message == "目前沒有進行中的提醒設定。"


def test_users_are_isolated():
    service, _ = _service(); service.start("u1"); service.start("u2"); service.receive_stock_id("u1", "2330")
    assert service.get_session("u1").step is AlertCreationStep.AWAITING_CONDITION
    assert service.get_session("u2").step is AlertCreationStep.AWAITING_STOCK_ID


def test_expired_session_returns_expired():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc); current = [base]
    service, _ = _service(clock=lambda: current[0]); service.start("u1"); current[0] += timedelta(minutes=16)
    assert service.receive_stock_id("u1", "2330").status == "expired"
