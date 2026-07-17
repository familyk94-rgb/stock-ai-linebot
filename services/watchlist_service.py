"""Application service for per-user stock watchlists."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.repositories.watchlist_repository import WatchlistRepository


_TAIPEI = ZoneInfo("Asia/Taipei")


class WatchlistService:
    def __init__(self, repository: WatchlistRepository | None = None) -> None:
        self.repository = repository or WatchlistRepository()

    def add_stock(self, line_user_id, stock_id, stock_name) -> bool:
        user_id = _required_text(line_user_id, "line_user_id")
        symbol = _required_text(stock_id, "stock_id")
        name = _required_text(stock_name, "stock_name")
        return self.repository.insert(
            line_user_id=user_id,
            stock_id=symbol,
            stock_name=name,
            created_at=datetime.now(_TAIPEI).isoformat(),
        )

    def remove_stock(self, line_user_id, stock_id) -> bool:
        return self.repository.delete(
            line_user_id=_required_text(line_user_id, "line_user_id"),
            stock_id=_required_text(stock_id, "stock_id"),
        )

    def list_stocks(self, line_user_id) -> list[dict]:
        return self.repository.list_by_user(
            line_user_id=_required_text(line_user_id, "line_user_id")
        )

    def exists(self, line_user_id, stock_id) -> bool:
        return self.repository.exists(
            line_user_id=_required_text(line_user_id, "line_user_id"),
            stock_id=_required_text(stock_id, "stock_id"),
        )


def _required_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()
