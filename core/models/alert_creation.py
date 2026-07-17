"""Immutable contracts for the alert-creation conversation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping


class AlertCreationStep(str, Enum):
    AWAITING_STOCK_ID = "awaiting_stock_id"
    AWAITING_CONDITION = "awaiting_condition"
    AWAITING_TARGET = "awaiting_target"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


@dataclass(frozen=True, slots=True)
class AlertCreationSession:
    user_id: str
    step: AlertCreationStep
    stock_id: str | None = None
    stock_name: str | None = None
    condition: str | None = None
    target_price: Decimal | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AlertCreationResult:
    status: str
    message: str
    session: AlertCreationSession | None = None
    created_alert: Mapping[str, object] | None = None
    error_code: str | None = None
