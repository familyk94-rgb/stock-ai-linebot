"""SQLite-backed, best-effort usage tracking for OpenAI analysis requests."""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from core.observability import get_request_id, log_event
from services.cost_service import CostCalculator


logger = logging.getLogger(__name__)
DEFAULT_USAGE_DB_PATH = "data/usage.db"
SQLITE_TIMEOUT_SECONDS = 1.0
SQLITE_BUSY_TIMEOUT_MS = 1000
SUMMARY_FALLBACK = {
    "request_count": 0,
    "openai_call_count": 0,
    "cache_hit_count": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "estimated_cost_usd": 0.0,
}


def _value(container, *names):
    for name in names:
        if isinstance(container, dict) and name in container:
            return True, container[name]
        if container is not None:
            try:
                return True, getattr(container, name)
            except AttributeError:
                pass
            except Exception:
                return True, None
    return False, None


def _safe_token_count(value) -> tuple[int, bool]:
    if isinstance(value, bool):
        return 0, False
    if not isinstance(value, (int, float)):
        return 0, False
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return 0, False
    if not number.is_finite() or number < 0:
        return 0, False
    return int(number), True


def parse_usage_metadata(usage) -> dict:
    prompt_found, prompt_raw = _value(usage, "prompt_tokens", "input_tokens")
    completion_found, completion_raw = _value(usage, "completion_tokens", "output_tokens")
    total_found, total_raw = _value(usage, "total_tokens")
    prompt, prompt_valid = _safe_token_count(prompt_raw) if prompt_found else (0, True)
    completion, completion_valid = _safe_token_count(completion_raw) if completion_found else (0, True)
    if total_found:
        total, total_valid = _safe_token_count(total_raw)
    else:
        total, total_valid = prompt + completion, True
    fields_found = prompt_found or completion_found or total_found
    if not fields_found:
        usage_status = "missing"
    elif prompt_valid and completion_valid and total_valid:
        usage_status = "available"
    else:
        usage_status = "invalid"
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "usage_status": usage_status,
    }


def build_usage_record(
    *,
    model: str,
    result: str,
    cache_hit: bool,
    openai_call: bool,
    usage=None,
    calculator: CostCalculator | None = None,
) -> dict:
    tokens = parse_usage_metadata(usage)
    cost = (calculator or CostCalculator()).calculate(
        model, tokens["prompt_tokens"], tokens["completion_tokens"]
    )
    return {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "request_id": get_request_id(),
        "operation": "stock_analysis",
        "model": model,
        "prompt_tokens": tokens["prompt_tokens"],
        "completion_tokens": tokens["completion_tokens"],
        "total_tokens": tokens["total_tokens"],
        "estimated_cost_usd": cost["estimated_cost_usd"],
        "result": result,
        "cache_hit": bool(cache_hit),
        "openai_call": bool(openai_call),
        "usage_status": tokens["usage_status"],
        "pricing_status": cost["pricing_status"],
    }


class UsageRepository:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        sqlite_timeout_seconds: float = SQLITE_TIMEOUT_SECONDS,
        busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
    ):
        self.db_path = Path(db_path or os.getenv("USAGE_DB_PATH") or DEFAULT_USAGE_DB_PATH)
        self.sqlite_timeout_seconds = max(0.0, float(sqlite_timeout_seconds))
        self.busy_timeout_ms = max(0, int(busy_timeout_ms))

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=self.sqlite_timeout_seconds)
        try:
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            self._create_table(connection)
            self._migrate_schema(connection)
            connection.commit()
        except Exception:
            connection.close()
            raise
        return connection

    @staticmethod
    def _create_table(connection, table_name: str = "usage_records") -> None:
        if table_name not in {"usage_records", "usage_records_new"}:
            raise ValueError("unsupported table name")
        connection.execute(
            f"""CREATE TABLE IF NOT EXISTS {table_name} (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    request_id TEXT,
                    operation TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    estimated_cost_usd TEXT NOT NULL,
                    result TEXT NOT NULL,
                    cache_hit INTEGER NOT NULL,
                    openai_call INTEGER NOT NULL,
                    usage_status TEXT NOT NULL,
                    pricing_status TEXT NOT NULL
                )"""
        )

    @staticmethod
    def _migrate_schema(connection) -> None:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(usage_records)").fetchall()
        }
        if "usage_missing" in columns or "pricing_unknown" in columns:
            connection.execute("DROP TABLE IF EXISTS usage_records_new")
            UsageRepository._create_table(connection, "usage_records_new")
            usage_expression = (
                "CASE WHEN usage_missing = 0 THEN 'available' ELSE 'missing' END"
                if "usage_missing" in columns else "'missing'"
            )
            pricing_expression = (
                "CASE WHEN pricing_unknown = 0 THEN 'available' ELSE 'pricing_unknown' END"
                if "pricing_unknown" in columns else "'pricing_unknown'"
            )
            connection.execute(
                f"""INSERT INTO usage_records_new (
                    id, timestamp, request_id, operation, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    estimated_cost_usd, result, cache_hit, openai_call,
                    usage_status, pricing_status
                ) SELECT
                    id, timestamp, request_id, operation, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    estimated_cost_usd, result, cache_hit, openai_call,
                    {usage_expression}, {pricing_expression}
                FROM usage_records"""
            )
            connection.execute("DROP TABLE usage_records")
            connection.execute("ALTER TABLE usage_records_new RENAME TO usage_records")
            return
        if "usage_status" not in columns:
            connection.execute(
                "ALTER TABLE usage_records ADD COLUMN usage_status TEXT NOT NULL DEFAULT 'missing'"
            )
            if "usage_missing" in columns:
                connection.execute(
                    "UPDATE usage_records SET usage_status = CASE WHEN usage_missing = 0 THEN 'available' ELSE 'missing' END"
                )
        if "pricing_status" not in columns:
            connection.execute(
                "ALTER TABLE usage_records ADD COLUMN pricing_status TEXT NOT NULL DEFAULT 'pricing_unknown'"
            )
            if "pricing_unknown" in columns:
                connection.execute(
                    "UPDATE usage_records SET pricing_status = CASE WHEN pricing_unknown = 0 THEN 'available' ELSE 'pricing_unknown' END"
                )

    def record_usage(self, record: dict) -> bool:
        connection = None
        try:
            connection = self._connect()
            connection.execute(
                """INSERT INTO usage_records (
                    id, timestamp, request_id, operation, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    estimated_cost_usd, result, cache_hit, openai_call,
                    usage_status, pricing_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["id"], record["timestamp"], record.get("request_id"),
                    record["operation"], record["model"], record["prompt_tokens"],
                    record["completion_tokens"], record["total_tokens"],
                    str(record["estimated_cost_usd"]), record["result"],
                    int(record["cache_hit"]), int(record["openai_call"]),
                    record["usage_status"], record["pricing_status"],
                ),
            )
            connection.commit()
            log_event(logger, "usage_record_success", result="success", operation=record.get("operation"), model=record.get("model"))
            return True
        except Exception as error:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            log_event(logger, "usage_record_error", result="error", error_type=type(error).__name__, operation="stock_analysis")
            return False
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def get_daily_summary(self, target_date: date | str) -> dict:
        value = target_date.isoformat() if isinstance(target_date, date) else str(target_date)
        return self._summary("substr(timestamp, 1, 10) = ?", (value,))

    def get_monthly_summary(self, year: int, month: int) -> dict:
        try:
            value = f"{int(year):04d}-{int(month):02d}"
        except (TypeError, ValueError):
            return dict(SUMMARY_FALLBACK)
        return self._summary("substr(timestamp, 1, 7) = ?", (value,))

    def _summary(self, where_clause: str, parameters: tuple) -> dict:
        try:
            connection = self._connect()
            try:
                rows = connection.execute(
                    f"SELECT prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, cache_hit, openai_call FROM usage_records WHERE {where_clause}",
                    parameters,
                ).fetchall()
            finally:
                connection.close()
            summary = dict(SUMMARY_FALLBACK)
            summary["request_count"] = len(rows)
            cost = Decimal("0")
            for prompt, completion, total, estimated, cache_hit, openai_call in rows:
                summary["prompt_tokens"] += prompt
                summary["completion_tokens"] += completion
                summary["total_tokens"] += total
                summary["cache_hit_count"] += cache_hit
                summary["openai_call_count"] += openai_call
                cost += Decimal(estimated)
            summary["estimated_cost_usd"] = float(cost)
            log_event(logger, "usage_summary_query_success", result="success")
            return summary
        except Exception as error:
            log_event(logger, "usage_summary_query_error", result="error", error_type=type(error).__name__)
            return dict(SUMMARY_FALLBACK)


def record_analysis_usage(**kwargs) -> bool:
    try:
        record = build_usage_record(**kwargs)
        if record["usage_status"] != "available" and record["openai_call"]:
            log_event(logger, "usage_metadata_missing", result="fallback", operation="stock_analysis", model=record["model"])
        if record["pricing_status"] == "pricing_unknown" and record["openai_call"]:
            log_event(logger, "pricing_unknown", result="fallback", operation="stock_analysis", model=record["model"])
        return UsageRepository().record_usage(record)
    except Exception as error:
        log_event(logger, "usage_record_error", result="error", error_type=type(error).__name__, operation="stock_analysis")
        return False
