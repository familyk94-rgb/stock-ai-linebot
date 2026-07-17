import sqlite3
from decimal import Decimal

import pytest

from services.repositories.alert_repository import AlertRepository


CREATED_AT = "2026-07-17T10:00:00+08:00"


def _add(repository, *, user="user-1", stock="2330", condition="GT", price="1000"):
    return repository.add_alert(
        line_user_id=user,
        stock_id=stock,
        condition=condition,
        target_price=Decimal(price),
        created_at=CREATED_AT,
    )


def test_add_and_get_alert_preserves_decimal_as_text(tmp_path):
    path = tmp_path / "nested" / "alerts.db"
    repository = AlertRepository(path)
    created = _add(repository, price="1000.25")

    assert created["id"] == 1
    assert created["target_price"] == Decimal("1000.25")
    assert created["enabled"] is True
    assert created["is_active"] is False
    assert repository.get_alert(1) == created

    with sqlite3.connect(path) as connection:
        stored = connection.execute(
            "SELECT target_price, typeof(target_price) FROM alerts WHERE id = 1"
        ).fetchone()
    assert stored == ("1000.25", "text")


def test_list_alerts_isolated_by_user_and_stock(tmp_path):
    repository = AlertRepository(tmp_path / "alerts.db")
    assert _add(repository, user="user-1", stock="2330")
    assert _add(repository, user="user-1", stock="2454", condition="LT")
    assert _add(repository, user="user-2", stock="2330", condition="LT")

    assert [item["stock_id"] for item in repository.list_alerts("user-1")] == [
        "2330",
        "2454",
    ]
    enabled_2330 = repository.get_enabled_alerts("2330")
    assert {item["line_user_id"] for item in enabled_2330} == {"user-1", "user-2"}


def test_duplicate_add_returns_none(tmp_path):
    repository = AlertRepository(tmp_path / "alerts.db")
    assert _add(repository) is not None
    assert _add(repository) is None
    assert len(repository.list_alerts("user-1")) == 1


def test_repository_rejects_float_target_price(tmp_path):
    repository = AlertRepository(tmp_path / "alerts.db")
    with pytest.raises(TypeError, match="Decimal"):
        repository.add_alert(
            line_user_id="user-1",
            stock_id="2330",
            condition="GT",
            target_price=1000.5,
            created_at=CREATED_AT,
        )


def test_remove_alert_enforces_optional_user_scope(tmp_path):
    repository = AlertRepository(tmp_path / "alerts.db")
    alert_id = _add(repository)["id"]
    assert repository.remove_alert(alert_id, "user-2") is False
    assert repository.remove_alert(alert_id, "user-1") is True
    assert repository.get_alert(alert_id) is None


def test_enable_disable_and_enabled_stock_query(tmp_path):
    repository = AlertRepository(tmp_path / "alerts.db")
    alert_id = _add(repository)["id"]
    assert repository.disable_alert(alert_id, "user-1") is True
    assert repository.get_enabled_alerts("2330") == []
    assert repository.enable_alert(alert_id, "user-1") is True
    assert [item["id"] for item in repository.get_enabled_alerts("2330")] == [alert_id]


def test_set_active_state_preserves_last_trigger_when_reset(tmp_path):
    repository = AlertRepository(tmp_path / "alerts.db")
    alert_id = _add(repository)["id"]
    triggered = "2026-07-17T11:00:00+08:00"
    assert repository.set_active_state(alert_id, True, triggered)
    assert repository.get_alert(alert_id)["last_triggered_at"] == triggered
    assert repository.set_active_state(alert_id, False)
    alert = repository.get_alert(alert_id)
    assert alert["is_active"] is False
    assert alert["last_triggered_at"] == triggered


def test_active_state_transition_is_conditional_for_dedup(tmp_path):
    repository = AlertRepository(tmp_path / "alerts.db")
    alert_id = _add(repository)["id"]
    triggered = "2026-07-17T11:00:00+08:00"
    assert repository.set_active_state(alert_id, True, triggered) is True
    assert repository.set_active_state(alert_id, True, triggered) is False
    assert repository.set_active_state(alert_id, False) is True
    assert repository.set_active_state(alert_id, False) is False


def test_schema_and_indexes_are_created(tmp_path):
    path = tmp_path / "alerts.db"
    repository = AlertRepository(path)
    repository.list_alerts("user-1")
    with sqlite3.connect(path) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(alerts)")]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(alerts)")}
    assert columns == [
        "id", "line_user_id", "stock_id", "condition", "target_price",
        "enabled", "is_active", "last_triggered_at", "created_at", "updated_at",
    ]
    assert {"idx_alerts_stock_enabled", "idx_alerts_line_user"} <= indexes


def test_write_error_rolls_back_closes_and_propagates(monkeypatch, tmp_path):
    class BrokenConnection:
        rolled_back = False
        closed = False

        def execute(self, *args):
            raise sqlite3.OperationalError("write failed")

        def commit(self):
            pytest.fail("commit should not be called")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = BrokenConnection()
    repository = AlertRepository(tmp_path / "alerts.db")
    monkeypatch.setattr(repository, "_connect", lambda: connection)

    with pytest.raises(sqlite3.OperationalError):
        _add(repository)
    assert connection.rolled_back is True
    assert connection.closed is True


def test_repository_uses_environment_database_path(monkeypatch, tmp_path):
    path = tmp_path / "configured" / "alerts.db"
    monkeypatch.setenv("ALERT_DB_PATH", str(path))
    repository = AlertRepository()
    assert repository.db_path == path
    assert _add(repository)
