"""Deterministic Decimal-based price alert evaluation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from core.models.alert_trigger import AlertTrigger
from services.repositories.alert_repository import AlertRepository


_TAIPEI = ZoneInfo("Asia/Taipei")


class AlertEngine:
    def __init__(self, repository: AlertRepository | None = None, *, clock=None) -> None:
        self.repository = repository or AlertRepository()
        self.clock = clock or (lambda: datetime.now(_TAIPEI))

    def check_alerts(self, stock_id, quote) -> list[AlertTrigger]:
        symbol = _stock_id(stock_id)
        current_price = _quote_price(quote)
        if symbol is None or current_price is None:
            return []

        alerts = self.repository.get_enabled_alerts(symbol)
        triggers = []
        triggered_at = None
        for alert in alerts:
            condition = alert.get("condition")
            target_price = _decimal_price(alert.get("target_price"))
            if condition not in {"GT", "LT"} or target_price is None:
                continue
            matches = (
                current_price > target_price
                if condition == "GT"
                else current_price < target_price
            )
            is_active = alert.get("is_active") is True
            if matches and not is_active:
                if triggered_at is None:
                    triggered_at = _aware_iso(self.clock())
                if self.repository.set_active_state(
                    alert["id"], True, triggered_at
                ):
                    triggers.append(
                        AlertTrigger(
                            alert_id=alert["id"],
                            line_user_id=alert["line_user_id"],
                            stock_id=alert["stock_id"],
                            condition=condition,
                            target_price=target_price,
                            current_price=current_price,
                            triggered_at=triggered_at,
                        )
                    )
            elif not matches and is_active:
                self.repository.set_active_state(alert["id"], False)
        return triggers


_default_engine = AlertEngine()


def check_alerts(stock_id, quote) -> list[AlertTrigger]:
    return _default_engine.check_alerts(stock_id, quote)


def _stock_id(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if not normalized.isascii() or not normalized.isdigit():
        return None
    return normalized


def _quote_price(quote) -> Decimal | None:
    if isinstance(quote, dict):
        price = _decimal_price(quote.get("price"))
        return price if price is not None and price > 0 else None
    try:
        price = _decimal_price(getattr(quote, "price"))
        return price if price is not None and price > 0 else None
    except (AttributeError, TypeError):
        return None


def _decimal_price(value) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    return number


def _aware_iso(value) -> str:
    if not isinstance(value, datetime):
        raise TypeError("clock must return datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=_TAIPEI)
    return value.isoformat()
