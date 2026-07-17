"""Short-, mid-, and long-term AI trend card."""

from app.flex.design_system import MUTED, TEXT, card


def build_trend_card(summary=None) -> dict:
    text = summary if isinstance(summary, str) else ""
    return card([
        {"type": "text", "text": "AI 趨勢", "size": "md", "weight": "bold", "color": TEXT},
        _row("短線", _extract(text, "短線建議")),
        _row("中線", _extract(text, "中線建議")),
        _row("長線", _extract(text, "長線建議")),
    ])


def _extract(text: str, label: str) -> str:
    for line in text.splitlines():
        normalized = line.strip()
        for separator in ("：", ":"):
            prefix = label + separator
            if normalized.startswith(prefix):
                value = normalized[len(prefix):].strip()
                return value or "資料不足"
    return "資料不足"


def _row(label: str, value: str) -> dict:
    return {
        "type": "box", "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": MUTED, "flex": 1},
            {"type": "text", "text": value, "size": "sm", "weight": "bold", "color": TEXT, "align": "end", "flex": 3, "wrap": True},
        ],
    }
