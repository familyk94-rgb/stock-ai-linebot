import traceback

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

    if not user_text.isdigit():
        reply_text(event.reply_token, "請輸入股票代號，例如：2330")
        return

    stock_code = user_text

    try:
        market_data = get_market_info(stock_code)

        print("=" * 80)
        print("stock_code =", stock_code)
        print("market_data =", market_data)
        print("market_data type =", type(market_data))
        print("=" * 80)

        if not isinstance(market_data, dict):
            raise TypeError(
                f"market_data 應該是 dict，但收到 {type(market_data).__name__}"
            )

        ai_result = ai_stock_analysis(stock_code, market_data)

        if isinstance(ai_result, str):
            ai_result = {
                "score": None,
                "decision": "觀察",
                "risk_level": "未評估",
                "shopkeeper_message": "阿柑店長看法：目前先觀察，不急著追高。",
                "trend": market_data.get("trend"),
                "ma_signal": market_data.get("ma_signal"),
                "macd_signal": market_data.get("macd_signal"),
                "rsi_signal": market_data.get("rsi_signal"),
                "ai_summary": ai_result,
                "explain": ai_result,
            }

        if not isinstance(ai_result, dict):
            raise TypeError(
                f"ai_result 應該是 dict 或 str，但收到 {type(ai_result).__name__}"
            )

        flex_data = {
            "stock_code": stock_code,
            "stock_name": market_data.get("stock_name", ""),
            "score": ai_result.get("score"),
            "decision": ai_result.get("decision", "觀察"),
            "risk_level": ai_result.get("risk_level", "未評估"),
            "shopkeeper_message": ai_result.get(
                "shopkeeper_message",
                "阿柑店長看法：目前先觀察，不急著追高。"
            ),
            "price": market_data.get("price"),
            "change": market_data.get("change"),
            "change_percent": market_data.get("change_percent"),
            "volume": market_data.get("volume"),
            "trend": ai_result.get("trend") or market_data.get("trend"),
            "ma_signal": ai_result.get("ma_signal") or market_data.get("ma_signal"),
            "macd_signal": ai_result.get("macd_signal") or market_data.get("macd_signal"),
            "rsi_signal": ai_result.get("rsi_signal") or market_data.get("rsi_signal"),
            "ai_summary": ai_result.get(
                "ai_summary",
                "目前資料不足，建議等待更多訊號。"
            ),
            "explain": ai_result.get(
                "explain",
                "尚未產生完整解釋。"
            ),
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
        print("=" * 80)
        traceback.print_exc()
        print("=" * 80)

        reply_text(
            event.reply_token,
            f"錯誤：{type(e).__name__}\n{str(e)}"
        )


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