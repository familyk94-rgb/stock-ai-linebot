import json
from linebot.v3.messaging import FlexMessage, FlexContainer

from app.flex.header import build_header
from app.flex.dashboard_card import build_dashboard_card
from app.flex.shopkeeper_card import build_shopkeeper_card
from app.flex.market_card import build_market_card
from app.flex.technical_card import build_technical_card
from app.flex.analysis_card import build_analysis_card
from app.flex.explain_card import build_explain_card


def build_stock_dashboard_flex(stock, ai_text):
    body_contents = [
        build_dashboard_card(stock),

        {"type": "separator", "margin": "lg"},

        build_shopkeeper_card(stock),

        {"type": "separator", "margin": "lg"},

        build_market_card(stock),

        {"type": "separator", "margin": "lg"},

        build_technical_card(stock),

        {"type": "separator", "margin": "lg"},

        build_analysis_card(ai_text),

        {"type": "separator", "margin": "lg"},

        build_explain_card(stock),
    ]

    bubble = {
        "type": "bubble",
        "size": "giga",
        "header": build_header(stock),
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "⚠️ 本內容僅供研究參考，不構成任何投資建議。",
                    "size": "xs",
                    "wrap": True,
                    "color": "#9CA3AF",
                }
            ],
        },
    }

    return FlexMessage(
        alt_text=f"{stock['stock_name']} AI 投資儀表板",
        contents=FlexContainer.from_json(json.dumps(bubble, ensure_ascii=False)),
    )