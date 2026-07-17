from decimal import Decimal

import pytest

from core.models.alert_management import AlertListResult
from services.alert_management_service import AlertManagementService


class Repository:
    def __init__(self, rows=(), error=None):
        self.rows = list(rows)
        self.error = error
        self.calls = []

    def list_alerts(self, user_id):
        self.calls.append(user_id)
        if self.error:
            raise self.error
        return list(self.rows)


def _row(
    alert_id=1,
    stock_id="2330",
    condition="GT",
    target=Decimal("1150"),
    enabled=True,
):
    return {
        "id": alert_id,
        "stock_id": stock_id,
        "condition": condition,
        "target_price": target,
        "enabled": enabled,
    }


def _service(rows=(), names=None, error=None):
    names = names or {"2330": "台積電", "2454": "聯發科", "2882": "國泰金"}
    calls = []

    def resolve(stock_id):
        calls.append(stock_id)
        value = names.get(stock_id, "未知股票")
        if isinstance(value, Exception):
            raise value
        return value

    repository = Repository(rows, error)
    return AlertManagementService(repository, stock_name_resolver=resolve), repository, calls


def test_empty_alerts_returns_immutable_empty_result():
    service, repository, calls = _service()
    result = service.list_user_alerts(" user-1 ")
    assert result == AlertListResult.empty("user-1")
    assert result.items == ()
    assert repository.calls == ["user-1"]
    assert calls == []


@pytest.mark.parametrize(
    ("enabled", "expected_counts"),
    [(True, (1, 1, 0)), (False, (1, 0, 1))],
)
def test_single_enabled_and_disabled_alert(enabled, expected_counts):
    service, _, _ = _service([_row(enabled=enabled)])
    result = service.list_user_alerts("user-1")
    assert (result.total_count, result.enabled_count, result.disabled_count) == expected_counts
    assert result.items[0].enabled is enabled
    assert result.items[0].condition_label == "股價突破"


def test_stable_sorting_enabled_then_stock_then_id():
    service, _, _ = _service([
        _row(4, "2330", enabled=False),
        _row(3, "2454", enabled=True),
        _row(2, "2330", enabled=True),
        _row(1, "2330", enabled=True),
    ])
    result = service.list_user_alerts("user-1")
    assert [item.alert_id for item in result.items] == [1, 2, 3, 4]


def test_repository_receives_only_requested_user_id():
    service, repository, _ = _service([_row()])
    result = service.list_user_alerts("user-2")
    assert result.user_id == "user-2"
    assert repository.calls == ["user-2"]


def test_stock_name_success_and_duplicate_symbol_is_resolved_once():
    service, _, calls = _service([_row(1), _row(2, condition="LT")])
    result = service.list_user_alerts("user-1")
    assert [item.stock_name for item in result.items] == ["台積電", "台積電"]
    assert calls == ["2330"]


@pytest.mark.parametrize("name", [RuntimeError("offline"), "未知股票", None, "   "])
def test_stock_name_failure_isolated_with_empty_fallback(name):
    service, _, _ = _service([_row()], names={"2330": name})
    assert service.list_user_alerts("user-1").items[0].stock_name == ""


def test_unknown_condition_has_safe_label():
    service, _, _ = _service([_row(condition="UNKNOWN")])
    item = service.list_user_alerts("user-1").items[0]
    assert item.condition_type == "UNKNOWN"
    assert item.condition_label == "自訂提醒"


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (1150, "1150"),
        (55.5, "55.5"),
        (Decimal("100.2500"), "100.25"),
        (None, "—"),
    ],
)
def test_target_value_normalization(target, expected):
    service, _, _ = _service([_row(target=target)])
    assert service.list_user_alerts("user-1").items[0].target_value == expected


@pytest.mark.parametrize("user_id", [None, "", "   ", 123])
def test_invalid_user_id_is_rejected_before_repository(user_id):
    service, repository, _ = _service([_row()])
    with pytest.raises(ValueError, match="user_id"):
        service.list_user_alerts(user_id)
    assert repository.calls == []


def test_repository_error_preserves_existing_propagation_contract():
    service, _, _ = _service(error=RuntimeError("database unavailable"))
    with pytest.raises(RuntimeError, match="database unavailable"):
        service.list_user_alerts("user-1")
