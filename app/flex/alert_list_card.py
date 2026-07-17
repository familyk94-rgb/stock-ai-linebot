"""Standalone LINE Flex view for a user's price alerts."""

from __future__ import annotations

from linebot.v3.messaging import FlexContainer, FlexMessage

from app.flex.design_system import BRAND, MUTED, SUCCESS, SURFACE, TEXT
from core.models.alert_management import AlertListItem, AlertListResult


MAX_VISIBLE_ALERTS = 8


def build_alert_list_bubble(result: AlertListResult | None = None) -> dict:
    safe_result = result if isinstance(result, AlertListResult) else AlertListResult.empty()
    visible_items = safe_result.items[:MAX_VISIBLE_ALERTS]
    hidden_count = max(0, safe_result.total_count - len(visible_items))
    contents = [_summary(safe_result)]
    if visible_items:
        contents.extend(_alert_item(item) for item in visible_items)
        if hidden_count:
            contents.append(
                {
                    "type": "text",
                    "text": f"另有 {hidden_count} 筆提醒未顯示",
                    "size": "xs",
                    "color": MUTED,
                    "align": "center",
                    "wrap": True,
                }
            )
    else:
        contents.append(_empty_state())

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": BRAND,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "📌 我的股票提醒",
                    "size": "xl",
                    "weight": "bold",
                    "color": SURFACE,
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "16px",
            "backgroundColor": SURFACE,
            "contents": contents,
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "paddingAll": "12px",
            "contents": [
                _button("＋ 新增提醒", "新增提醒"),
                _button("🔄 重新整理", "我的提醒"),
            ],
        },
    }


def build_alert_list_flex(result: AlertListResult | None = None) -> FlexMessage:
    return FlexMessage(
        alt_text="我的股票提醒",
        contents=FlexContainer.from_dict(build_alert_list_bubble(result)),
    )


def _summary(result: AlertListResult) -> dict:
    return {
        "type": "text",
        "text": (
            f"共 {result.total_count} 筆　"
            f"啟用 {result.enabled_count} 筆　"
            f"停用 {result.disabled_count} 筆"
        ),
        "size": "sm",
        "weight": "bold",
        "color": TEXT,
        "wrap": True,
    }


def _alert_item(item: AlertListItem) -> dict:
    name = item.stock_name.strip() if isinstance(item.stock_name, str) else ""
    stock = f"{item.stock_id} {name}".strip()
    status = "🟢 啟用" if item.enabled else "⚪ 停用"
    status_color = SUCCESS if item.enabled else MUTED
    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "xs",
        "paddingAll": "12px",
        "cornerRadius": "10px",
        "backgroundColor": "#F9FAFB",
        "contents": [
            {
                "type": "text", "text": stock or "未知股票", "weight": "bold",
                "size": "md", "color": TEXT, "wrap": True, "maxLines": 2,
            },
            {
                "type": "text", "text": status, "size": "sm",
                "weight": "bold", "color": status_color,
            },
            {
                "type": "text",
                "text": f"{item.condition_label} {item.target_value}".strip(),
                "size": "sm", "color": TEXT, "wrap": True,
            },
        ],
    }


def _empty_state() -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "24px",
        "contents": [
            {
                "type": "text", "text": "目前沒有提醒", "align": "center",
                "size": "md", "color": MUTED,
            }
        ],
    }


def _button(label: str, text: str) -> dict:
    return {
        "type": "button",
        "style": "secondary",
        "height": "sm",
        "flex": 1,
        "color": BRAND,
        "action": {"type": "message", "label": label, "text": text},
    }
