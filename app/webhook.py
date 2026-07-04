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

    return "OK"


def build_stock_dashboard(stock):
    technical = stock.get("technical") or {}

    ai_text = ai_stock_analysis(stock)

    return (
        f"📊 {stock['stock_name']}（{stock['stock_id']}）\n"
        f"📅 日期：{stock['date']}\n\n"
        f"💰 收盤價：{stock['price_text']} 元\n"
        f"📈 開盤價：{stock['open_text']} 元\n"
        f"🔺 最高價：{stock['high_text']} 元\n"
        f"🔻 最低價：{stock['low_text']} 元\n"
        f"📦 成交量：{stock['volume_text']}\n\n"
        f"📈 技術指標\n"
        f"MA5：{technical.get('ma5')}\n"
        f"MA10：{technical.get('ma10')}\n"
        f"MA20：{technical.get('ma20')}\n"
        f"MA60：{technical.get('ma60')}\n"
        f"RSI：{technical.get('rsi')}\n"
        f"KD：K {technical.get('k')} / D {technical.get('d')}\n"
        f"MACD：{technical.get('macd')}\n"
        f"Signal：{technical.get('signal')}\n"
        f"Histogram：{technical.get('histogram')}\n\n"
        f"{ai_text}"
    )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_text = event.message.text.strip()

    reply_text = f"收到訊息：{user_text}"

    if user_text.isdigit():
        stock = get_market_info(user_text)

        if stock:
            reply_text = build_stock_dashboard(stock)
        else:
            reply_text = f"❌ 查不到股票代號：{user_text}"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )