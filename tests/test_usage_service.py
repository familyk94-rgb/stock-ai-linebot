import sqlite3
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core import observability
from services.cost_service import CostCalculator
from services.usage_service import (
    SUMMARY_FALLBACK,
    UsageRepository,
    build_usage_record,
    parse_usage_metadata,
)


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, (10, 5, 15)),
        ({"input_tokens": 8, "output_tokens": 2}, (8, 2, 10)),
        (SimpleNamespace(prompt_tokens=3, completion_tokens=4, total_tokens=7), (3, 4, 7)),
        (None, (0, 0, 0)),
        ("invalid", (0, 0, 0)),
    ],
)
def test_usage_metadata_variants(usage, expected):
    result = parse_usage_metadata(usage)
    assert (result["prompt_tokens"], result["completion_tokens"], result["total_tokens"]) == expected


@pytest.mark.parametrize(
    ("usage", "expected_total", "expected_status"),
    [
        ({"prompt_tokens": 10, "completion_tokens": 5}, 15, "available"),
        ({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 0}, 0, "available"),
        ({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": "15"}, 0, "invalid"),
        ({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 99}, 99, "available"),
        ({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, 0, "available"),
        ({}, 0, "missing"),
        ({"prompt_tokens": True}, 0, "invalid"),
        ({"prompt_tokens": "10"}, 0, "invalid"),
    ],
)
def test_total_tokens_and_usage_status_contract(usage, expected_total, expected_status):
    result = parse_usage_metadata(usage)
    assert result["total_tokens"] == expected_total
    assert result["usage_status"] == expected_status


def _record(timestamp, *, cache_hit=False, openai_call=True, prompt=10, completion=5, cost="0.01"):
    return {
        "id": f"{timestamp}-{cache_hit}-{prompt}", "timestamp": timestamp,
        "request_id": "request-1", "operation": "stock_analysis", "model": "test-model",
        "prompt_tokens": prompt, "completion_tokens": completion,
        "total_tokens": prompt + completion, "estimated_cost_usd": Decimal(cost),
        "result": "success", "cache_hit": cache_hit, "openai_call": openai_call,
        "usage_status": "available", "pricing_status": "available",
    }


def test_new_database_table_single_and_multiple_records_and_summaries(tmp_path):
    path = tmp_path / "nested" / "usage.db"
    repository = UsageRepository(path)
    assert repository.record_usage(_record("2026-07-13T10:00:00+08:00"))
    assert repository.record_usage(_record("2026-07-13T11:00:00+08:00", cache_hit=True, openai_call=False, prompt=0, completion=0, cost="0"))
    assert path.exists()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0] == 2
    daily = repository.get_daily_summary(date(2026, 7, 13))
    assert daily == {
        "request_count": 2, "openai_call_count": 1, "cache_hit_count": 1,
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
        "estimated_cost_usd": 0.01,
    }
    assert repository.get_monthly_summary(2026, 7) == daily
    assert repository.get_monthly_summary(2026, 8) == SUMMARY_FALLBACK


def test_record_timestamp_is_taipei_and_contains_no_sensitive_fields():
    token = observability.set_request_id("request-usage")
    try:
        record = build_usage_record(
            model="test-model", result="success", cache_hit=False, openai_call=True,
            usage={"prompt_tokens": 1, "completion_tokens": 2},
            calculator=CostCalculator({"test-model": {"input": 1, "output": 1}}),
        )
    finally:
        observability.clear_request_id(token)
    assert record["timestamp"].endswith("+08:00")
    assert record["request_id"] == "request-usage"
    assert set(record) == {
        "id", "timestamp", "request_id", "operation", "model",
        "prompt_tokens", "completion_tokens", "total_tokens",
        "estimated_cost_usd", "result", "cache_hit", "openai_call",
        "usage_status", "pricing_status",
    }
    assert record["usage_status"] == "available"
    assert record["pricing_status"] == "available"
    assert not ({"prompt", "response", "market_data", "user_id", "token", "secret"} & set(record))


def test_cache_hit_and_timeout_records_have_missing_usage_and_unknown_pricing():
    for result, cache_hit, openai_call in (
        ("success", True, False),
        ("timeout", False, True),
    ):
        record = build_usage_record(
            model="gpt-4.1-mini", result=result,
            cache_hit=cache_hit, openai_call=openai_call, usage=None,
        )
        assert record["prompt_tokens"] == 0
        assert record["completion_tokens"] == 0
        assert record["total_tokens"] == 0
        assert record["estimated_cost_usd"] == Decimal("0")
        assert record["usage_status"] == "missing"
        assert record["pricing_status"] == "pricing_unknown"


def test_database_write_and_query_failures_are_safe(monkeypatch, tmp_path):
    repository = UsageRepository(tmp_path / "usage.db")
    monkeypatch.setattr(repository, "_connect", lambda: (_ for _ in ()).throw(sqlite3.OperationalError()))
    assert repository.record_usage(_record("2026-07-13T10:00:00+08:00")) is False
    assert repository.get_daily_summary("2026-07-13") == SUMMARY_FALLBACK


def test_write_failure_explicitly_rolls_back_and_closes(monkeypatch, tmp_path):
    class BrokenConnection:
        rolled_back = False
        closed = False

        def execute(self, *args):
            raise sqlite3.OperationalError("write failed")

        def commit(self):
            pytest.fail("commit called")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = BrokenConnection()
    repository = UsageRepository(tmp_path / "usage.db")
    monkeypatch.setattr(repository, "_connect", lambda: connection)
    assert repository.record_usage(_record("2026-07-13T10:00:00+08:00")) is False
    assert connection.rolled_back is True
    assert connection.closed is True


def test_database_path_uses_environment_variable(monkeypatch, tmp_path):
    expected = tmp_path / "configured" / "usage.db"
    monkeypatch.setenv("USAGE_DB_PATH", str(expected))
    repository = UsageRepository()
    assert repository.db_path == expected
    assert repository.record_usage(_record("2026-07-13T10:00:00+08:00"))
    assert expected.exists()


def test_real_sqlite_write_lock_is_safe_and_preserves_existing_data(tmp_path):
    path = tmp_path / "usage.db"
    repository = UsageRepository(path, sqlite_timeout_seconds=0.01, busy_timeout_ms=10)
    assert repository.record_usage(_record("2026-01-01T00:00:00+08:00"))
    locker = sqlite3.connect(path, timeout=0.01)
    try:
        locker.execute("BEGIN IMMEDIATE")
        assert repository.record_usage(_record("2026-01-02T00:00:00+08:00")) is False
    finally:
        locker.rollback()
        locker.close()
    assert repository.get_daily_summary("2026-01-01")["request_count"] == 1
    assert repository.get_daily_summary("2026-01-02")["request_count"] == 0
    assert repository.record_usage(_record("2026-01-03T00:00:00+08:00")) is True


def test_daily_and_monthly_summaries_respect_taipei_month_boundaries(tmp_path):
    repository = UsageRepository(tmp_path / "usage.db")
    timestamps = (
        "2026-01-31T23:59:59+08:00",
        "2026-02-01T00:00:00+08:00",
        "2026-02-28T23:59:59+08:00",
        "2026-03-01T00:00:00+08:00",
    )
    for index, timestamp in enumerate(timestamps):
        record = _record(timestamp, prompt=index + 1)
        record["id"] = f"boundary-{index}"
        assert repository.record_usage(record)
    assert repository.get_daily_summary("2026-01-31")["request_count"] == 1
    assert repository.get_daily_summary("2026-02-01")["request_count"] == 1
    assert repository.get_monthly_summary(2026, 1)["request_count"] == 1
    assert repository.get_monthly_summary(2026, 2)["request_count"] == 2
    assert repository.get_monthly_summary(2026, 3)["request_count"] == 1


def test_old_schema_is_migrated_without_deleting_existing_rows(tmp_path):
    path = tmp_path / "usage.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE usage_records (
                id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, request_id TEXT,
                operation TEXT NOT NULL, model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL, estimated_cost_usd TEXT NOT NULL,
                result TEXT NOT NULL, cache_hit INTEGER NOT NULL,
                openai_call INTEGER NOT NULL, usage_missing INTEGER NOT NULL,
                pricing_unknown INTEGER NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO usage_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("old", "2026-01-01T00:00:00+08:00", None, "stock_analysis", "old-model", 1, 2, 3, "0", "success", 0, 1, 0, 1),
        )
    repository = UsageRepository(path)
    assert repository.record_usage(_record("2026-01-02T00:00:00+08:00"))
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(usage_records)")}
        assert {"usage_status", "pricing_status"} <= columns
        assert connection.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0] == 2
        assert connection.execute("SELECT usage_status, pricing_status FROM usage_records WHERE id='old'").fetchone() == ("available", "pricing_unknown")
    assert repository.get_monthly_summary(2026, 1)["request_count"] == 2
