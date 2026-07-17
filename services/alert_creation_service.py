"""UI-neutral orchestration for creating price alerts."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable
from zoneinfo import ZoneInfo

from core.models.alert_creation import (
    AlertCreationResult,
    AlertCreationSession,
    AlertCreationStep,
)
from services.alert_creation_state_store import AlertCreationStateStore
from services.repositories.alert_repository import AlertRepository
from services.stock_name_service import get_stock_name


_TAIPEI = ZoneInfo("Asia/Taipei")
_STOCK_ID = re.compile(r"^[0-9]{4,6}$")
_PRICE = re.compile(r"^(?:[0-9]+)(?:\.[0-9]+)?$")
_MAX_PRICE = Decimal("10000000")
_CONDITIONS = {
    "股價突破": "GT", "突破": "GT", "GT": "GT",
    "股價跌破": "LT", "跌破": "LT", "LT": "LT",
}


class AlertCreationService:
    def __init__(
        self,
        repository: AlertRepository | None = None,
        state_store: AlertCreationStateStore | None = None,
        stock_name_resolver: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or AlertRepository()
        self.state_store = state_store or AlertCreationStateStore(clock=clock)
        self.stock_name_resolver = stock_name_resolver or get_stock_name
        self._clock = clock or (lambda: datetime.now(_TAIPEI))

    def start(self, user_id: str) -> AlertCreationResult:
        user = _required_user(user_id)
        now = self._clock()
        session = AlertCreationSession(
            user_id=user,
            step=AlertCreationStep.AWAITING_STOCK_ID,
            created_at=now,
            updated_at=now,
        )
        self.state_store.set(session)
        return _result("started", "請輸入股票代號，例如 2330。", session)

    def get_session(self, user_id: str) -> AlertCreationSession | None:
        return self.state_store.get(user_id)

    def consume_expired(self, user_id: str) -> bool:
        return self.state_store.consume_expired(user_id)

    def receive_stock_id(self, user_id: str, stock_id: object) -> AlertCreationResult:
        session = self._session_for(user_id, AlertCreationStep.AWAITING_STOCK_ID)
        if isinstance(session, AlertCreationResult):
            return session
        normalized = str(stock_id).strip() if stock_id is not None else ""
        if _STOCK_ID.fullmatch(normalized) is None:
            return _result("invalid_input", "股票代號格式錯誤，請輸入 4～6 位數字。", session, "invalid_stock_id")
        try:
            stock_name = self.stock_name_resolver(normalized)
        except Exception:
            return _result("invalid_input", "找不到這個股票代號，請重新輸入。", session, "stock_lookup_failed")
        if not _valid_stock_name(stock_name, normalized):
            return _result("invalid_input", "找不到這個股票代號，請重新輸入。", session, "stock_not_found")
        updated = replace(
            session,
            step=AlertCreationStep.AWAITING_CONDITION,
            stock_id=normalized,
            stock_name=stock_name.strip(),
            updated_at=self._clock(),
        )
        self.state_store.set(updated)
        return _result("awaiting_condition", "請選擇提醒條件。", updated)

    def select_condition(self, user_id: str, condition: object) -> AlertCreationResult:
        session = self._session_for(user_id, AlertCreationStep.AWAITING_CONDITION)
        if isinstance(session, AlertCreationResult):
            return session
        key = str(condition).strip().upper() if condition is not None else ""
        normalized = _CONDITIONS.get(key)
        if normalized is None:
            return _result("invalid_input", "請選擇股價突破或股價跌破。", session, "invalid_condition")
        updated = replace(
            session,
            step=AlertCreationStep.AWAITING_TARGET,
            condition=normalized,
            updated_at=self._clock(),
        )
        self.state_store.set(updated)
        return _result("awaiting_target", "請輸入目標價格，例如 1150。", updated)

    def receive_target(self, user_id: str, target: object) -> AlertCreationResult:
        session = self._session_for(user_id, AlertCreationStep.AWAITING_TARGET)
        if isinstance(session, AlertCreationResult):
            return session
        price = _target_price(target)
        if price is None:
            return _result("invalid_input", "目標價格格式錯誤，請輸入大於 0 的數字。", session, "invalid_target")
        updated = replace(
            session,
            step=AlertCreationStep.AWAITING_CONFIRMATION,
            target_price=price,
            updated_at=self._clock(),
        )
        self.state_store.set(updated)
        return _result("awaiting_confirmation", "請確認提醒內容。", updated)

    def confirm(self, user_id: str) -> AlertCreationResult:
        session = self._session_for(user_id, AlertCreationStep.AWAITING_CONFIRMATION)
        if isinstance(session, AlertCreationResult):
            return session
        if not _complete(session):
            return _result("failed", "提醒資料不完整，請重新輸入。", session, "incomplete_session")
        try:
            if self.repository.exists_active_alert(
                session.user_id, session.stock_id, session.condition, session.target_price
            ):
                return _result("duplicate", "這筆提醒已經存在。", session, "duplicate_alert")
            created = self.repository.add_alert(
                line_user_id=session.user_id,
                stock_id=session.stock_id,
                condition=session.condition,
                target_price=session.target_price,
                created_at=self._clock().isoformat(),
            )
        except Exception:
            return _result("failed", "提醒建立失敗，請稍後再試。", session, "repository_error")
        if not isinstance(created, dict):
            return _result("duplicate", "這筆提醒已經存在。", session, "duplicate_alert")
        created_view = dict(created)
        created_view["stock_name"] = session.stock_name
        self.state_store.delete(session.user_id)
        return AlertCreationResult("created", "提醒建立成功", None, created_view, None)

    def restart(self, user_id: str) -> AlertCreationResult:
        if self.state_store.get(user_id) is None:
            return _result("expired", "提醒設定已逾時，請重新輸入『新增提醒』。", None, "session_missing")
        return self.start(user_id)

    def cancel(self, user_id: str) -> AlertCreationResult:
        if self.state_store.get(user_id) is None:
            return _result("cancelled", "目前沒有進行中的提醒設定。")
        self.state_store.delete(user_id)
        return _result("cancelled", "已取消提醒設定。")

    def _session_for(self, user_id: str, step: AlertCreationStep):
        session = self.state_store.get(user_id)
        if session is None:
            return _result("expired", "提醒設定已逾時，請重新輸入『新增提醒』。", None, "session_missing")
        if session.step is not step:
            return _result("invalid_input", _step_message(session.step), session, "invalid_step")
        return session


def _result(status, message, session=None, error_code=None):
    return AlertCreationResult(status, message, session, None, error_code)


def _required_user(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("user_id is required")
    return value.strip()


def _valid_stock_name(value: object, stock_id: str) -> bool:
    if not isinstance(value, str):
        return False
    name = value.strip()
    return bool(name and name != stock_id and name != "未知股票" and not name.startswith("?"))


def _target_price(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    text = str(value).strip() if value is not None else ""
    if _PRICE.fullmatch(text) is None:
        return None
    try:
        price = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or price <= 0 or price > _MAX_PRICE:
        return None
    fixed = format(price, "f")
    if "." in fixed:
        fixed = fixed.rstrip("0").rstrip(".")
    return Decimal(fixed)


def format_price(value: Decimal | None) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        return "暫無資料"
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


def _complete(session: AlertCreationSession) -> bool:
    return (
        bool(session.stock_id and session.stock_name)
        and session.condition in {"GT", "LT"}
        and isinstance(session.target_price, Decimal)
        and session.target_price.is_finite()
        and session.target_price > 0
    )


def _step_message(step: AlertCreationStep) -> str:
    return {
        AlertCreationStep.AWAITING_STOCK_ID: "請先輸入股票代號。",
        AlertCreationStep.AWAITING_CONDITION: "請先選擇提醒條件。",
        AlertCreationStep.AWAITING_TARGET: "請先輸入目標價格。",
        AlertCreationStep.AWAITING_CONFIRMATION: "請確認建立、重新輸入或取消。",
    }[step]
