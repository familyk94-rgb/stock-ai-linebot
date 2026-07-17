from decimal import Decimal

import pytest

from services.alert_service import AlertService
from services.repositories.alert_repository import AlertRepository


def _service(tmp_path):
    return AlertService(AlertRepository(tmp_path / "alerts.db"))


@pytest.mark.parametrize(("condition", "expected"), [("GT", "GT"), ("lt", "LT")])
def test_add_alert_normalizes_condition_and_decimal(tmp_path, condition, expected):
    alert = _service(tmp_path).add_alert(" user-1 ", " 2330 ", condition, "1000.25")
    assert alert["line_user_id"] == "user-1"
    assert alert["stock_id"] == "2330"
    assert alert["condition"] == expected
    assert alert["target_price"] == Decimal("1000.25")
    assert alert["created_at"].endswith("+08:00")


@pytest.mark.parametrize("condition", ["", "GE", "GT" + chr(0), None, 1])
def test_invalid_condition_is_rejected(tmp_path, condition):
    with pytest.raises(ValueError):
        _service(tmp_path).add_alert("user-1", "2330", condition, "1000")


@pytest.mark.parametrize(
    "price",
    [None, True, "", "invalid", "NaN", "Infinity", "-1", "0", [], {}],
)
def test_invalid_target_price_is_rejected(tmp_path, price):
    with pytest.raises(ValueError):
        _service(tmp_path).add_alert("user-1", "2330", "GT", price)


@pytest.mark.parametrize(
    ("user_id", "stock_id"),
    [(None, "2330"), ("", "2330"), ("user-1", None), ("user-1", " ")],
)
def test_missing_user_or_stock_is_rejected(tmp_path, user_id, stock_id):
    with pytest.raises(ValueError):
        _service(tmp_path).add_alert(user_id, stock_id, "GT", "1000")


@pytest.mark.parametrize("stock_id", ["ABCD", "23A0", "２３３０"])
def test_non_ascii_numeric_stock_id_is_rejected(tmp_path, stock_id):
    with pytest.raises(ValueError):
        _service(tmp_path).add_alert("user-1", stock_id, "GT", "1000")


def test_service_list_remove_enable_disable_are_user_scoped(tmp_path):
    service = _service(tmp_path)
    alert = service.add_alert("user-1", "2330", "GT", "1000")
    alert_id = alert["id"]
    assert service.list_alerts("user-1") == [alert]
    assert service.disable_alert("user-2", alert_id) is False
    assert service.disable_alert("user-1", alert_id) is True
    assert service.enable_alert("user-1", alert_id) is True
    assert service.remove_alert("user-2", alert_id) is False
    assert service.remove_alert("user-1", alert_id) is True


def test_service_does_not_expose_sql_connection(tmp_path):
    service = _service(tmp_path)
    assert not hasattr(service, "_connect")
    assert not hasattr(service, "execute")
