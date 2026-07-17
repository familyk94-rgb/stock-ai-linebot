from linebot.v3.messaging import FlexContainer, FlexMessage

from app.flex.action_card import build_action_card
from app.flex.alert_card import build_alert_card
from app.flex.analysis_grid import build_analysis_grid
from app.flex.decision_card import build_decision_card
from app.flex.full_analysis_card import build_full_analysis_card
from app.flex.header_card import build_header_card
from app.flex.score_card import build_score_card
from app.flex.shopkeeper_card import build_shopkeeper_card
from app.flex.trend_card import build_trend_card


def build_stock_dashboard_bubble(data: dict | None = None) -> dict:
    data = data or {}
    stock_code = str(data.get("stock_code", ""))
    stock_name = str(data.get("stock_name", ""))

    return {
        "type": "bubble",
        "size": "mega",
        "header": build_header_card(
            stock_code=stock_code,
            stock_name=stock_name,
            quote=data.get("quote"),
            price=data.get("price"),
            change=data.get("change"),
            change_percent=data.get("change_percent"),
        ),
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "12px",
            "backgroundColor": "#FFFFFF",
            "contents": [
                build_score_card(
                    score=data.get("score"),
                    composite_score=data.get("composite_score"),
                    confidence=data.get("confidence"),
                ),
                build_decision_card(
                    decision=data.get("decision"),
                    risk_level=data.get("risk_level"),
                ),
                build_analysis_grid(
                    technical_score=data.get("score"),
                    technical_summary=data.get("trend"),
                    financial_score=data.get("financial_score"),
                    financial_summary=data.get("financial_summary"),
                    institution_score=data.get("institution_score"),
                    institution_summary=data.get("institution_summary"),
                    news_score=data.get("news_score"),
                    news_summary=data.get("news_summary"),
                ),
                build_trend_card(summary=data.get("ai_summary")),
                build_shopkeeper_card(message=data.get("shopkeeper_message")),
                build_alert_card(),
                build_full_analysis_card(
                    summary=data.get("ai_summary"),
                    explain=data.get("explain"),
                ),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "backgroundColor": "#FFFFFF",
            "contents": [build_action_card(stock_code)],
        },
    }


def build_stock_dashboard_flex(data: dict | None = None) -> FlexMessage:
    bubble = build_stock_dashboard_bubble(data)
    return FlexMessage(
        alt_text="股市柑仔店 AI Pro 股票分析",
        contents=FlexContainer.from_dict(bubble),
    )
