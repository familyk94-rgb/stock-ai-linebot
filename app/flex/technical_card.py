def build_technical_card(
    trend: str | None = None,
    ma_signal: str | None = None,
    macd_signal: str | None = None,
    rsi_signal: str | None = None,
) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "技術分析",
                "weight": "bold",
                "size": "md",
                "color": "#111827",
            },
            _row("趨勢", trend or "未判定"),
            _row("均線", ma_signal or "未判定"),
            _row("MACD", macd_signal or "未判定"),
            _row("RSI", rsi_signal or "未判定"),
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