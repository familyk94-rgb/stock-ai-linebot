"""LINE Flex confirmation card for alert creation."""

from __future__ import annotations

from linebot.v3.messaging import FlexContainer, FlexMessage

from app.flex.design_system import BRAND, MUTED, SURFACE, TEXT
from core.models.alert_creation import AlertCreationResult, AlertCreationSession
from services.alert_creation_service import format_price


def build_alert_creation_confirmation_bubble(
    result: AlertCreationResult | None = None,
) -> dict:
    session = result.session if isinstance(result, AlertCreationResult) else None
    session = session if isinstance(session, AlertCreationSession) else None
    stock_id = _text(session.stock_id if session else None, "暫無資料")
    stock_name = _text(session.stock_name if session else None, "")
    condition = {"GT": "股價突破", "LT": "股價跌破"}.get(
        session.condition if session else None, "暫無資料"
    )
    target = format_price(session.target_price if session else None)
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": BRAND,
            "paddingAll": "18px",
            "contents": [{
                "type": "text", "text": "🔔 確認股價提醒", "size": "xl",
                "weight": "bold", "color": SURFACE,
            }],
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "paddingAll": "18px", "backgroundColor": SURFACE,
            "contents": [
                _row("股票", f"{stock_id} {stock_name}".strip()),
                _row("條件", condition),
                _row("目標價格", target),
                {"type": "text", "text": "確認後才會建立提醒。", "size": "xs", "color": MUTED, "wrap": True},
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "12px",
            "contents": [
                _button("確認建立", "確認建立", "primary"),
                {
                    "type": "box", "layout": "horizontal", "spacing": "sm",
                    "contents": [
                        _button("重新輸入", "重新輸入", "secondary"),
                        _button("取消", "取消", "secondary"),
                    ],
                },
            ],
        },
    }


def build_alert_creation_confirmation_flex(
    result: AlertCreationResult | None = None,
) -> FlexMessage:
    return FlexMessage(
        alt_text="確認股價提醒",
        contents=FlexContainer.from_dict(build_alert_creation_confirmation_bubble(result)),
    )


def _row(label: str, value: str) -> dict:
    return {
        "type": "box", "layout": "horizontal", "spacing": "md",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": MUTED, "flex": 2},
            {"type": "text", "text": value, "size": "sm", "weight": "bold", "color": TEXT, "flex": 4, "wrap": True},
        ],
    }


def _button(label: str, text: str, style: str) -> dict:
    return {
        "type": "button", "style": style, "height": "sm", "flex": 1,
        "color": BRAND,
        "action": {"type": "message", "label": label, "text": text},
    }


def _text(value: object, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback
