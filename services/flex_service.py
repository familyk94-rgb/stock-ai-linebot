import json
from linebot.v3.messaging import FlexMessage, FlexContainer


def build_stock_flex(stock, ai_text):
    technical = stock.get("technical") or {}

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#111827",
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "股市柑仔店 AI Pro",
                    "color": "#FBBF24",
                    "size": "sm",
                    "weight": "bold"
                },
                {
                    "type": "text",
                    "text": f"{stock['stock_name']}（{stock['stock_id']}）",
                    "color": "#FFFFFF",
                    "size": "xl",
                    "weight": "bold",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": f"日期：{stock['date']}",
                    "color": "#D1D5DB",
                    "size": "xs",
                    "margin": "sm"
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
                    "type": "separator"
                },
                {
                    "type": "text",
                    "text": "📈 技術分析",
                    "weight": "bold",
                    "size": "md"
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
                        f"MACD：{technical.get('macd')}\n"
                        f"Signal：{technical.get('signal')}\n"
                        f"Hist：{technical.get('histogram')}"
                    ),
                    "size": "sm",
                    "wrap": True
                },
                {
                    "type": "separator"
                },
                {
                    "type": "text",
                    "text": ai_text,
                    "size": "sm",
                    "wrap": True
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "⚠️ 僅供研究參考，非投資建議。",
                    "size": "xs",
                    "color": "#6B7280",
                    "wrap": True
                }
            ]
        }
    }

    return FlexMessage(
        alt_text=f"{stock['stock_name']} 投資儀表板",
        contents=FlexContainer.from_json(json.dumps(bubble))
    )