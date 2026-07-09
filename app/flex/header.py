def build_header(stock_code: str, stock_name: str = "") -> dict:
    title = f"{stock_code} {stock_name}".strip()

    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "backgroundColor": "#1F2937",
        "contents": [
            {
                "type": "text",
                "text": "股市柑仔店 AI Pro",
                "size": "sm",
                "color": "#FBBF24",
                "weight": "bold",
            },
            {
                "type": "text",
                "text": title or "股票分析",
                "size": "xl",
                "color": "#FFFFFF",
                "weight": "bold",
                "margin": "sm",
            },
        ],
    }