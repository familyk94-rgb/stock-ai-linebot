"""SQLite persistence for price alerts."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_ALERT_DB_PATH = "data/alerts.db"
SQLITE_TIMEOUT_SECONDS = 1.0
SQLITE_BUSY_TIMEOUT_MS = 1000
_TAIPEI = ZoneInfo("Asia/Taipei")


class AlertRepository:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        sqlite_timeout_seconds: float = SQLITE_TIMEOUT_SECONDS,
        busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
    ) -> None:
        self.db_path = Path(
            db_path or os.getenv("ALERT_DB_PATH") or DEFAULT_ALERT_DB_PATH
        )
        self.sqlite_timeout_seconds = max(0.0, float(sqlite_timeout_seconds))
        self.busy_timeout_ms = max(0, int(busy_timeout_ms))

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.db_path,
            timeout=self.sqlite_timeout_seconds,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_user_id TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    condition TEXT NOT NULL CHECK(condition IN ('GT', 'LT')),
                    target_price TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    is_active INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0, 1)),
                    last_triggered_at TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(line_user_id, stock_id, condition, target_price)
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_stock_enabled ON alerts(stock_id, enabled)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_line_user ON alerts(line_user_id)"
            )
            connection.commit()
        except Exception:
            connection.close()
            raise
        return connection

    def add_alert(
        self,
        *,
        line_user_id: str,
        stock_id: str,
        condition: str,
        target_price: Decimal,
        created_at: str,
    ) -> dict | None:
        if not isinstance(target_price, Decimal):
            raise TypeError("target_price must be Decimal")
        connection = self._connect()
        try:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO alerts (
                    line_user_id, stock_id, condition, target_price,
                    enabled, is_active, last_triggered_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, 0, NULL, ?, ?)""",
                (
                    line_user_id,
                    stock_id,
                    condition,
                    str(target_price),
                    created_at,
                    created_at,
                ),
            )
            connection.commit()
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM alerts WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return _row_to_alert(row)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def exists_active_alert(
        self,
        line_user_id: str,
        stock_id: str,
        condition: str,
        target_price: Decimal,
    ) -> bool:
        if not isinstance(target_price, Decimal):
            raise TypeError("target_price must be Decimal")
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT 1 FROM alerts
                WHERE line_user_id = ? AND stock_id = ? AND condition = ?
                AND target_price = ? AND enabled = 1 LIMIT 1""",
                (line_user_id, stock_id, condition, str(target_price)),
            ).fetchone()
            return row is not None
        finally:
            connection.close()

    def remove_alert(self, alert_id: int, line_user_id: str | None = None) -> bool:
        connection = self._connect()
        try:
            if line_user_id is None:
                cursor = connection.execute(
                    "DELETE FROM alerts WHERE id = ?",
                    (alert_id,),
                )
            else:
                cursor = connection.execute(
                    "DELETE FROM alerts WHERE id = ? AND line_user_id = ?",
                    (alert_id, line_user_id),
                )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_alerts(self, line_user_id: str) -> list[dict]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT * FROM alerts WHERE line_user_id = ?
                ORDER BY enabled DESC, stock_id ASC, created_at ASC, id ASC""",
                (line_user_id,),
            ).fetchall()
            return [_row_to_alert(row) for row in rows]
        finally:
            connection.close()

    def get_enabled_alerts(self, stock_id: str) -> list[dict]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT * FROM alerts
                WHERE stock_id = ? AND enabled = 1 ORDER BY id""",
                (stock_id,),
            ).fetchall()
            return [_row_to_alert(row) for row in rows]
        finally:
            connection.close()

    def list_enabled_stock_ids(self) -> list[str]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT DISTINCT stock_id FROM alerts "
                "WHERE enabled = 1 ORDER BY stock_id"
            ).fetchall()
            return [row["stock_id"] for row in rows]
        finally:
            connection.close()

    def enable_alert(self, alert_id: int, line_user_id: str | None = None) -> bool:
        return self._set_enabled(alert_id, True, line_user_id)

    def disable_alert(self, alert_id: int, line_user_id: str | None = None) -> bool:
        return self._set_enabled(alert_id, False, line_user_id)

    def _set_enabled(
        self,
        alert_id: int,
        enabled: bool,
        line_user_id: str | None,
    ) -> bool:
        connection = self._connect()
        try:
            parameters = [int(enabled), _now_iso(), alert_id]
            sql = "UPDATE alerts SET enabled = ?, updated_at = ? WHERE id = ?"
            if line_user_id is not None:
                sql += " AND line_user_id = ?"
                parameters.append(line_user_id)
            cursor = connection.execute(sql, tuple(parameters))
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def set_active_state(
        self,
        alert_id: int,
        is_active: bool,
        triggered_at: str | None = None,
    ) -> bool:
        connection = self._connect()
        try:
            updated_at = triggered_at or _now_iso()
            if is_active:
                cursor = connection.execute(
                    """UPDATE alerts SET is_active = 1,
                    last_triggered_at = ?, updated_at = ?
                    WHERE id = ? AND is_active = 0""",
                    (triggered_at, updated_at, alert_id),
                )
            else:
                cursor = connection.execute(
                    """UPDATE alerts SET is_active = 0, updated_at = ?
                    WHERE id = ? AND is_active = 1""",
                    (updated_at, alert_id),
                )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_alert(self, alert_id: int) -> dict | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM alerts WHERE id = ?",
                (alert_id,),
            ).fetchone()
            return _row_to_alert(row) if row is not None else None
        finally:
            connection.close()


def _row_to_alert(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["target_price"] = Decimal(result["target_price"])
    result["enabled"] = bool(result["enabled"])
    result["is_active"] = bool(result["is_active"])
    return result


def _now_iso() -> str:
    return datetime.now(_TAIPEI).isoformat()
