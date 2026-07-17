"""Immutable, channel-neutral notification event contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.models.alert_trigger import AlertTrigger


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    alert_id: int
    recipient_id: str
    stock_id: str
    condition: str
    target_price: Decimal
    current_price: Decimal
    triggered_at: str

    def __post_init__(self) -> None:
        _validate_positive_int(self.alert_id, "alert_id")
        _validate_nonblank(self.recipient_id, "recipient_id")
        _validate_nonblank(self.stock_id, "stock_id")
        if self.condition not in {"GT", "LT"}:
            raise ValueError("condition must be GT or LT")
        _validate_price(self.target_price, "target_price")
        _validate_price(self.current_price, "current_price")
        _validate_aware_iso(self.triggered_at)

    @classmethod
    def from_alert_trigger(cls, trigger: AlertTrigger) -> "NotificationEvent":
        if not isinstance(trigger, AlertTrigger):
            raise TypeError("trigger must be AlertTrigger")
        return cls(
            alert_id=trigger.alert_id,
            recipient_id=trigger.line_user_id,
            stock_id=trigger.stock_id,
            condition=trigger.condition,
            target_price=trigger.target_price,
            current_price=trigger.current_price,
            triggered_at=trigger.triggered_at,
        )


def _validate_positive_int(value, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


def _validate_nonblank(value, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")


def _validate_price(value, field: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{field} must be positive and finite")


def _validate_aware_iso(value) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("triggered_at must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("triggered_at must be an ISO 8601 string") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("triggered_at must include timezone offset")
