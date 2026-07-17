from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class AlertTrigger:
    alert_id: int
    line_user_id: str
    stock_id: str
    condition: str
    target_price: Decimal
    current_price: Decimal
    triggered_at: str
