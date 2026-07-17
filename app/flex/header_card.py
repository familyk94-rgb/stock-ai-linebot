"""Product header for Dashboard V3."""

from app.flex.dashboard_card import (
    _format_number,
    _format_provider,
    _format_quality,
    _format_timestamp,
    _safe_number,
)
from app.flex.design_system import BRAND, MUTED, SUCCESS, RISK, SURFACE, TEXT


def build_header_card(
    *,
    stock_code: str,
    stock_name: str,
    quote=None,
    price=None,
    change=None,
    change_percent=None,
) -> dict:
    quote_data = quote if isinstance(quote, dict) else {}
    current_price = quote_data.get("price", price)
    current_change = quote_data.get("change", change)
    current_percent = quote_data.get("change_percent", change_percent)
    change_text, change_color = _change_line(current_change, current_percent)
    timestamp = _short_time(quote_data.get("timestamp"))
    provider = _format_provider(quote_data.get("provider"))
    quality = _format_quality(quote_data.get("data_quality"))
    volume = _format_number(quote_data.get("volume"), grouping=True)
    title = f"{stock_code} {stock_name}".strip() or "股票分析"
    price_text = _format_number(current_price, grouping=True)
    if price_text != "暫無資料":
        price_text += " 元"

    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "20px",
        "backgroundColor": SURFACE,
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "🍊 股市柑仔店 AI Pro",
                "size": "sm",
                "color": BRAND,
                "weight": "bold",
            },
            {
                "type": "text",
                "text": title,
                "size": "xl",
                "color": TEXT,
                "weight": "bold",
                "margin": "sm",
            },
            {
                "type": "text",
                "text": price_text,
                "size": "xxl",
                "color": TEXT,
                "weight": "bold",
                "margin": "md",
            },
            {
                "type": "text",
                "text": change_text,
                "size": "md",
                "color": change_color,
                "weight": "bold",
            },
            {
                "type": "text",
                "text": f"{timestamp} 更新" if timestamp else "更新時間暫無資料",
                "size": "xs",
                "color": MUTED,
            },
            {
                "type": "text",
                "text": f"成交量 {volume}｜{provider}｜{quality}",
                "size": "xs",
                "color": MUTED,
                "wrap": True,
            },
        ],
    }


def _change_line(change, percent) -> tuple[str, str]:
    value = _safe_number(change)
    rate = _safe_number(percent)
    if value is None:
        return "暫無漲跌資料", MUTED
    if value == 0:
        marker, color = "—", MUTED
    elif value > 0:
        marker, color = "▲", SUCCESS
    else:
        marker, color = "▼", RISK
    change_text = _format_number(abs(value), grouping=True)
    if value > 0:
        change_text = "+" + change_text
    elif value < 0:
        change_text = "-" + change_text
    rate_text = "暫無資料" if rate is None else f"{rate:+g}%"
    return f"{marker} {change_text} ({rate_text})", color


def _short_time(value) -> str | None:
    formatted = _format_timestamp(value)
    if formatted == "暫無資料":
        return None
    return formatted.rsplit(" ", 1)[-1][:5]
