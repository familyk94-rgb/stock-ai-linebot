from linebot.v3.messaging import FlexMessage, FlexContainer


def build_stock_flex(stock, ai_text):
    technical = stock.get("technical") or {}

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1F2937",
            "contents": [
                {
                    "type": "text",
                    "text": "📊 股市柑仔店 AI 投資儀表板",
                    "weight": "bold",
                    "size": "md",
                    "color": "#FFFFFF"
                },
                {
                    "type": "text",
                    "text": f"{stock['stock_name']}（{stock['stock_id']}）",
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FBBF24",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": f"日期：{stock['date']}",
                    "size": "sm",
                    "color": "#D1D5DB"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "💰 即時行情",
                    "weight": "bold",
                    "size": "md"
                },
                {
                    "type": "text",
                    "text": (
                        f"收盤：{stock['price_text']} 元\n"
                        f"開盤：{stock['open_text']} 元\n"
                        f"最高：{stock['high_text']} 元\n"
                        f"最低：{stock['low_text']} 元\n"
                        f"成交量：{stock['volume_text']}"
                    ),
                    "size": "sm",
                    "wrap": True
                },
                {
                    "type": "separator",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": "📈 技術指標",
                    "weight": "bold",
                    "size": "md",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": (
                        f"MA5：{technical.get('ma5')}\n"
                        f"MA10：{technical.get('ma10')}\n"
                        f"MA20：{technical.get('ma20')}\n"
                        f"MA60：{technical.get('ma60')}\n"
                        f"RSI：{technical.get('rsi')}\n"
                        f"KD：K {technical.get('k')} / D {technical.get('d')}\n"
                        f"MACD：{technical.get('macd')}"
                    ),
                    "size": "sm",
                    "wrap": True
                },
                {
                    "type": "separator",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": ai_text,
                    "size": "sm",
                    "wrap": True,
                    "margin": "md"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "⚠️ 本內容僅供研究參考，非投資建議。",
                    "size": "xs",
                    "color": "#6B7280",
                    "wrap": True
                }
            ]
        }
    }

    return FlexMessage(
        alt_text=f"{stock['stock_name']} 投資儀表板",
        contents=FlexContainer.from_dict(bubble)
    )