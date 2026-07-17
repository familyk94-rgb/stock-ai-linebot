"""AI score presentation for Dashboard V3."""

from app.flex.dashboard_card import _format_confidence, _safe_number
from app.flex.design_system import BRAND, MUTED, TEXT, card


def build_score_card(*, score=None, composite_score=None, confidence=None) -> dict:
    number = _clamped(score)
    score_text = "—" if number is None else str(round(number, 1))
    filled = 0 if number is None else int(number / 10 + 0.5)
    gauge = "█" * filled + "░" * (10 - filled)
    stars = 0 if number is None else int(number / 20 + 0.5)
    rating = "★" * stars + "☆" * (5 - stars)
    composite = _clamped(composite_score)
    composite_text = "—" if composite is None else str(round(composite, 1))

    return card([
        {"type": "text", "text": "AI 技術分", "size": "sm", "color": MUTED},
        {"type": "text", "text": score_text, "size": "3xl", "weight": "bold", "color": TEXT},
        {"type": "text", "text": gauge, "size": "md", "color": BRAND},
        {"type": "text", "text": rating, "size": "sm", "color": BRAND},
        {"type": "separator", "margin": "md"},
        {
            "type": "box", "layout": "horizontal", "margin": "md",
            "contents": [
                _metric("綜合評分", composite_text),
                _metric("AI 信心度", _format_confidence(confidence)),
            ],
        },
    ])


def _metric(label: str, value: str) -> dict:
    return {
        "type": "box", "layout": "vertical", "flex": 1, "spacing": "xs",
        "contents": [
            {"type": "text", "text": label, "size": "xs", "color": MUTED, "align": "center"},
            {"type": "text", "text": value, "size": "md", "weight": "bold", "color": TEXT, "align": "center"},
        ],
    }


def _clamped(value):
    number = _safe_number(value)
    return None if number is None else max(0.0, min(100.0, number))
