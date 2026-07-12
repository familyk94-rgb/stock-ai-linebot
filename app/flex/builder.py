from linebot.v3.messaging import FlexContainer, FlexMessage

from app.flex.header import build_header
from app.flex.dashboard_card import build_dashboard_card
from app.flex.shopkeeper_card import build_shopkeeper_card
from app.flex.market_card import build_market_card
from app.flex.technical_card import build_technical_card
from app.flex.composite_card import build_composite_card
from app.flex.analysis_card import build_analysis_card
from app.flex.explain_card import build_explain_card


def build_stock_dashboard_bubble(data: dict | None = None) -> dict:
    data = data or {}

    stock_code = str(data.get("stock_code", ""))
    stock_name = str(data.get("stock_name", ""))

    return {
        "type": "bubble",
        "size": "mega",
        "header": build_header(
            stock_code=stock_code,
            stock_name=stock_name,
        ),
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                build_dashboard_card(
                    score=data.get("score"),
                    confidence=data.get("confidence"),
                    decision=data.get("decision"),
                    risk_level=data.get("risk_level"),
                ),
                build_shopkeeper_card(
                    message=data.get("shopkeeper_message"),
                ),
                build_market_card(
                    price=data.get("price"),
                    change=data.get("change"),
                    change_percent=data.get("change_percent"),
                    volume=data.get("volume"),
                ),
                build_technical_card(
                    trend=data.get("trend"),
                    ma_signal=data.get("ma_signal"),
                    macd_signal=data.get("macd_signal"),
                    rsi_signal=data.get("rsi_signal"),
                ),
                build_composite_card(
                    available=data.get("composite_available", False),
                    score=data.get("composite_score"),
                    summary=data.get("composite_summary"),
                    coverage=data.get("composite_coverage"),
                    data_quality_status=data.get("data_quality_status"),
                    data_quality_is_stale=data.get("data_quality_is_stale", False),
                ),
                build_analysis_card(
                    summary=data.get("ai_summary"),
                ),
                build_explain_card(
                    explain=data.get("explain"),
                ),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "本內容僅供參考，非投資建議",
                    "size": "xs",
                    "color": "#9CA3AF",
                    "align": "center",
                    "wrap": True,
                }
            ],
        },
    }


def build_stock_dashboard_flex(data: dict | None = None) -> FlexMessage:
    bubble = build_stock_dashboard_bubble(data)

    return FlexMessage(
        alt_text="股市柑仔店 AI Pro 股票分析",
        contents=FlexContainer.from_dict(bubble),
    )
