"""Immutable presentation contracts for alert management UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlertListItem:
    alert_id: int
    stock_id: str
    stock_name: str
    condition_type: str
    condition_label: str
    target_value: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class AlertListResult:
    user_id: str
    items: tuple[AlertListItem, ...]
    total_count: int
    enabled_count: int
    disabled_count: int

    @classmethod
    def empty(cls, user_id: str = "") -> "AlertListResult":
        return cls(
            user_id=user_id,
            items=(),
            total_count=0,
            enabled_count=0,
            disabled_count=0,
        )
