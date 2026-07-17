"""Read-only alert management application service."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from core.models.alert_management import AlertListItem, AlertListResult
from services.repositories.alert_repository import AlertRepository
from services.stock_name_service import get_stock_name


CONDITION_LABELS = {
    "GT": "股價突破",
    "LT": "股價跌破",
}
UNKNOWN_CONDITION_LABEL = "自訂提醒"


class AlertManagementService:
    def __init__(self, repository=None, *, stock_name_resolver=None) -> None:
        self.repository = repository or AlertRepository()
        self.stock_name_resolver = stock_name_resolver or get_stock_name

    def list_user_alerts(self, user_id) -> AlertListResult:
        normalized_user_id = _required_user_id(user_id)
        rows = self.repository.list_alerts(normalized_user_id)
        if not rows:
            return AlertListResult.empty(normalized_user_id)

        names: dict[str, str] = {}
        items = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            stock_id = _text(row.get("stock_id"))
            if not stock_id:
                continue
            if stock_id not in names:
                names[stock_id] = self._stock_name(stock_id)
            condition = _text(row.get("condition")).upper()
            items.append(
                AlertListItem(
                    alert_id=_safe_alert_id(row.get("id")),
                    stock_id=stock_id,
                    stock_name=names[stock_id],
                    condition_type=condition,
                    condition_label=CONDITION_LABELS.get(
                        condition, UNKNOWN_CONDITION_LABEL
                    ),
                    target_value=_format_target(row.get("target_price")),
                    enabled=row.get("enabled") is True,
                )
            )

        items.sort(key=lambda item: (not item.enabled, item.stock_id, item.alert_id))
        enabled_count = sum(item.enabled for item in items)
        return AlertListResult(
            user_id=normalized_user_id,
            items=tuple(items),
            total_count=len(items),
            enabled_count=enabled_count,
            disabled_count=len(items) - enabled_count,
        )

    def _stock_name(self, stock_id: str) -> str:
        try:
            name = self.stock_name_resolver(stock_id)
        except Exception:
            return ""
        if not isinstance(name, str):
            return ""
        normalized = name.strip()
        return "" if normalized == "未知股票" else normalized


def _required_user_id(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("user_id is required")
    return value.strip()


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_alert_id(value) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def _format_target(value) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    if not number.is_finite():
        return "—"
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized
