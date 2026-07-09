def build_technical_card(stock):
    t = stock.get("technical") or {}

    return {
        "type": "box",
        "layout": "vertical",
        "margin": "lg",
        "spacing": "sm",
        "contents": [
            {
                "type": "text",
                "text": "📈 技術分析",
                "weight": "bold",
                "size": "lg"
            },
            {
                "type": "text",
                "text": f"MA5：{t.get('ma5')}",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"MA10：{t.get('ma10')}",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"MA20：{t.get('ma20')}",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"MA60：{t.get('ma60')}",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"RSI：{t.get('rsi')}",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"KD：K {t.get('k')} / D {t.get('d')}",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"MACD：{t.get('macd')}",
                "size": "sm"
            },
        ]
    }