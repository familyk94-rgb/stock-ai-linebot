"""Provider-neutral immutable market quote contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


QUOTE_STATUSES = frozenset(
    {"trading", "pre_open", "closed", "halted", "delayed", "unknown"}
)
DATA_QUALITIES = frozenset(
    {"realtime", "delayed", "stale", "incomplete", "invalid"}
)


@dataclass(frozen=True, slots=True)
class Quote:
    provider: str
    symbol: str
    market: str | None
    timestamp: datetime | None
    status: str
    price: float | None
    reference: float | None
    change: float | None
    change_percent: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: int | float | None
    is_realtime: bool
    data_quality: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize without mutating the immutable quote."""
        value = asdict(self)
        value["timestamp"] = self.timestamp.isoformat() if self.timestamp else None
        return value
