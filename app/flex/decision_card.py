"""Decision and risk presentation for Dashboard V3."""

from app.flex.design_system import MUTED, RISK, SUCCESS, WARNING, TEXT, card


def build_decision_card(*, decision=None, risk_level=None) -> dict:
    decision_text = _text(decision, "觀察")
    risk_text = _text(risk_level, "未評估")
    if "多" in decision_text:
        icon, suggestion, color = "📈", "分批布局", SUCCESS
    elif "空" in decision_text:
        icon, suggestion, color = "📉", "保守觀望", RISK
    else:
        icon, suggestion, color = "🔎", "耐心觀察", WARNING
    risk_color = RISK if "高" in risk_text else WARNING

    return card([
        {
            "type": "box", "layout": "horizontal", "alignItems": "center",
            "contents": [
                {
                    "type": "box", "layout": "vertical", "flex": 2, "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": f"{icon} {decision_text}", "size": "xl", "weight": "bold", "color": color},
                        {"type": "text", "text": "建議", "size": "xs", "color": MUTED},
                        {"type": "text", "text": suggestion, "size": "md", "weight": "bold", "color": TEXT},
                    ],
                },
                {
                    "type": "box", "layout": "vertical", "flex": 1, "alignItems": "center", "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": "⚠️", "size": "xl", "align": "center"},
                        {"type": "text", "text": risk_text, "size": "sm", "weight": "bold", "color": risk_color, "align": "center", "wrap": True},
                    ],
                },
            ],
        }
    ])


def _text(value, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback
