"""Alert empty state reserved for future runtime composition."""

from app.flex.design_system import MUTED, TEXT, card


def build_alert_card() -> dict:
    return card([
        {"type": "text", "text": "🔔 我的提醒", "size": "md", "weight": "bold", "color": TEXT},
        {"type": "text", "text": "目前沒有提醒", "size": "sm", "color": MUTED},
        {"type": "text", "text": "＋新增提醒", "size": "sm", "weight": "bold", "color": "#F59E0B"},
    ])
