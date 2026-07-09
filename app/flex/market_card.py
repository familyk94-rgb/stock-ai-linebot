def build_market_card(
    price: int | float | None = None,
    change: int | float | None = None,
    change_percent: int | float | None = None,
    volume: int | float | None = None,
) -> dict:
    price_text = "-" if price is None else str(price)
    change_text = "-" if change is None else str(change)
    percent_text = "-" if change_percent is None else f"{change_percent}%"
    volume_text = "-" if volume is None else str(volume)

    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "市場資料",
                "weight": "bold",
                "size": "md",
                "color": "#111827",
            },
            _row("股價", price_text),
            _row("漲跌", change_text),
            _row("漲跌幅", percent_text),
            _row("成交量", volume_text),
        ],
    }


def _row(label: str, value: str) -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {
                "type": "text",
                "text": label,
                "size": "sm",
                "color": "#6B7280",
                "flex": 1,
            },
            {
                "type": "text",
                "text": value,
                "size": "sm",
                "align": "end",
                "weight": "bold",
                "flex": 2,
            },
        ],
    }