"""Dashboard V3 visual tokens."""

BRAND = "#F59E0B"
SUCCESS = "#16A34A"
WARNING = "#F97316"
RISK = "#DC2626"
TEXT = "#111827"
MUTED = "#6B7280"
SURFACE = "#FFFFFF"
SUBTLE = "#F9FAFB"
BORDER = "#E5E7EB"


def card(contents: list[dict], *, background: str = SURFACE) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "spacing": "sm",
        "backgroundColor": background,
        "cornerRadius": "12px",
        "borderWidth": "1px",
        "borderColor": BORDER,
        "contents": contents,
    }
