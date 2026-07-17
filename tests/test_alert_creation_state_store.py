from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from threading import Thread

import pytest

from core.models.alert_creation import AlertCreationSession, AlertCreationStep
from services.alert_creation_state_store import AlertCreationStateStore


def _session(user="u1", now=None):
    now = now or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return AlertCreationSession(user, AlertCreationStep.AWAITING_STOCK_ID, created_at=now, updated_at=now)


def test_store_set_get_has_delete_and_user_isolation():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = AlertCreationStateStore(clock=lambda: now)
    assert store.get("u1") is None and not store.has("u1")
    first, second = _session("u1", now), _session("u2", now)
    store.set(first); store.set(second)
    assert store.get("u1") == first and store.get("u2") == second
    store.delete("u1")
    assert store.get("u1") is None and store.get("u2") == second


def test_session_is_frozen_and_external_code_cannot_mutate_store_value():
    session = _session()
    with pytest.raises(FrozenInstanceError):
        session.stock_id = "2330"


def test_ttl_boundary_and_expired_auto_delete():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    current = [base + timedelta(minutes=15)]
    store = AlertCreationStateStore(clock=lambda: current[0])
    store.set(_session(now=base))
    assert store.has("u1")
    current[0] += timedelta(microseconds=1)
    assert store.get("u1") is None and not store.has("u1")
    assert store.consume_expired("u1") is True
    assert store.consume_expired("u1") is False


def test_empty_user_is_safe_and_invalid_session_rejected():
    store = AlertCreationStateStore()
    assert store.get("") is None
    store.delete("")
    with pytest.raises(ValueError):
        store.set(_session(user=""))


def test_basic_thread_safety_keeps_users_isolated():
    now = datetime.now(timezone.utc)
    store = AlertCreationStateStore(clock=lambda: now)
    threads = [Thread(target=store.set, args=(_session(f"u{i}", now),)) for i in range(20)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert all(store.get(f"u{i}").user_id == f"u{i}" for i in range(20))
