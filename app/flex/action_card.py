"""Dashboard V3 product actions."""

from app.flex.design_system import BRAND


def build_action_card(stock_code: str) -> dict:
    code = stock_code.strip() if isinstance(stock_code, str) else ""
    return {
        "type": "box", "layout": "vertical", "spacing": "sm",
        "contents": [
            _row(
                _button("📈 完整分析", code or "完整分析"),
                _button("⭐ 自選股", "我的自選"),
            ),
            _row(
                _button("🔔 設定提醒", f"設定提醒 {code}".strip()),
                _button("🔄 更新分析", code or "更新分析"),
            ),
        ],
    }


def _row(left: dict, right: dict) -> dict:
    return {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [left, right]}


def _button(label: str, text: str) -> dict:
    return {
        "type": "button", "style": "secondary", "height": "sm", "color": BRAND,
        "flex": 1, "action": {"type": "message", "label": label, "text": text},
    }
