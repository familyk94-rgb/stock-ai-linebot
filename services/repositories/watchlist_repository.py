"""SQLite persistence for per-user stock watchlists."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


DEFAULT_WATCHLIST_DB_PATH = "data/watchlist.db"
SQLITE_TIMEOUT_SECONDS = 1.0
SQLITE_BUSY_TIMEOUT_MS = 1000


class WatchlistRepository:
    """Store watchlist records without applying application business rules."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        sqlite_timeout_seconds: float = SQLITE_TIMEOUT_SECONDS,
        busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
    ) -> None:
        self.db_path = Path(
            db_path
            or os.getenv("WATCHLIST_DB_PATH")
            or DEFAULT_WATCHLIST_DB_PATH
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
                """CREATE TABLE IF NOT EXISTS watchlist_stocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_user_id TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(line_user_id, stock_id)
                )"""
            )
            connection.commit()
        except Exception:
            connection.close()
            raise
        return connection

    def insert(
        self,
        *,
        line_user_id: str,
        stock_id: str,
        stock_name: str,
        created_at: str,
    ) -> bool:
        connection = self._connect()
        try:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO watchlist_stocks (
                    line_user_id, stock_id, stock_name, created_at
                ) VALUES (?, ?, ?, ?)""",
                (line_user_id, stock_id, stock_name, created_at),
            )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def delete(self, *, line_user_id: str, stock_id: str) -> bool:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "DELETE FROM watchlist_stocks WHERE line_user_id = ? AND stock_id = ?",
                (line_user_id, stock_id),
            )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_by_user(self, *, line_user_id: str) -> list[dict]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """SELECT id, line_user_id, stock_id, stock_name, created_at
                FROM watchlist_stocks
                WHERE line_user_id = ?
                ORDER BY created_at ASC, id ASC""",
                (line_user_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def exists(self, *, line_user_id: str, stock_id: str) -> bool:
        connection = self._connect()
        try:
            row = connection.execute(
                """SELECT 1 FROM watchlist_stocks
                WHERE line_user_id = ? AND stock_id = ? LIMIT 1""",
                (line_user_id, stock_id),
            ).fetchone()
            return row is not None
        finally:
            connection.close()
