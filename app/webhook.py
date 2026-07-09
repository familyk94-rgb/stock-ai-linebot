from fastapi import APIRouter, Request, HTTPException

from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.config import LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN

from services.market_service import get_market_info
from services.ai_service import ai_stock_analysis

from app.flex.builder import build_stock_dashboard_flex


router = APIRouter()

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


@router.post("/webhook")
async def line_webhook(request: Request):
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    body_text = body.decode("utf-8")

    try:
        handler.handle(body_text, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return {"status": "ok"}


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent):
    user_text = event.message.text.strip()

    # 只處理股票代號，例如：2330、0050
    if not user_text.isdigit():
        reply_text(event.reply_token, "請輸入股票代號，例如：2330")
        return

    stock_code = user_text

    try:
        market_data = get_market_info(stock_code)
        ai_result = ai_stock_analysis(stock_code, market_data)

        flex_data = {
            "stock_code": stock_code,
            "stock_name": market_data.get("stock_name", ""),
            "score": ai_result.get("score"),
            "decision": ai_result.get("decision"),
            "risk_level": ai_result.get("risk_level"),
            "shopkeeper_message": ai_result.get("shopkeeper_message"),
            "price": market_data.get("price"),
            "change": market_data.get("change"),
            "change_percent": market_data.get("change_percent"),
            "volume": market_data.get("volume"),
            "trend": ai_result.get("trend"),
            "ma_signal": ai_result.get("ma_signal"),
            "macd_signal": ai_result.get("macd_signal"),
            "rsi_signal": ai_result.get("rsi_signal"),
            "ai_summary": ai_result.get("ai_summary"),
            "explain": ai_result.get("explain"),
        }

        flex_message = build_stock_dashboard_flex(flex_data)

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[flex_message],
                )
            )

    except Exception as e:
        print(f"[Webhook Error] {e}")
        reply_text(event.reply_token, "系統分析時發生錯誤，請稍後再試。")


def reply_text(reply_token: str, text: str):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    TextMessage(text=text)
                ],
            )
        )