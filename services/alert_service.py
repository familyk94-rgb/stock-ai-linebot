"""Validated application service for price alerts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from services.repositories.alert_repository import AlertRepository


_TAIPEI = ZoneInfo("Asia/Taipei")
_CONDITIONS = {"GT", "LT"}


class AlertService:
    def __init__(self, repository: AlertRepository | None = None) -> None:
        self.repository = repository or AlertRepository()

    def add_alert(self, line_user_id, stock_id, condition, target_price) -> dict | None:
        created_at = datetime.now(_TAIPEI).isoformat()
        return self.repository.add_alert(
            line_user_id=_required_text(line_user_id, "line_user_id"),
            stock_id=_stock_id(stock_id),
            condition=_condition(condition),
            target_price=_price(target_price),
            created_at=created_at,
        )

    def remove_alert(self, line_user_id, alert_id) -> bool:
        return self.repository.remove_alert(
            _alert_id(alert_id),
            _required_text(line_user_id, "line_user_id"),
        )

    def list_alerts(self, line_user_id) -> list[dict]:
        return self.repository.list_alerts(
            _required_text(line_user_id, "line_user_id")
        )

    def enable_alert(self, line_user_id, alert_id) -> bool:
        return self.repository.enable_alert(
            _alert_id(alert_id),
            _required_text(line_user_id, "line_user_id"),
        )

    def disable_alert(self, line_user_id, alert_id) -> bool:
        return self.repository.disable_alert(
            _alert_id(alert_id),
            _required_text(line_user_id, "line_user_id"),
        )


def _required_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _condition(value) -> str:
    normalized = _required_text(value, "condition").upper()
    if normalized not in _CONDITIONS:
        raise ValueError("condition must be GT or LT")
    return normalized


def _stock_id(value) -> str:
    normalized = _required_text(value, "stock_id")
    if not normalized.isascii() or not normalized.isdigit():
        raise ValueError("stock_id must contain ASCII digits only")
    return normalized


def _price(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("target_price must be a positive finite number")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("target_price must be a positive finite number") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("target_price must be a positive finite number")
    return number


def _alert_id(value) -> int:
    if isinstance(value, bool):
        raise ValueError("alert_id must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("alert_id must be a positive integer") from None
    if number <= 0 or str(value).strip() != str(number):
        raise ValueError("alert_id must be a positive integer")
    return number
