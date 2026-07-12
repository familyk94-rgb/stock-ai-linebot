import logging

from fastapi import APIRouter, Request, HTTPException

from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    FlexMessage,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
from app.flex.builder import build_stock_dashboard_flex
from services.ai_service import ai_stock_analysis
from services.market_service import get_market_info


router = APIRouter()
logger = logging.getLogger(__name__)

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
    except Exception:
        logger.exception("LINE webhook handling failed")
        return {"status": "error"}

    return {"status": "ok"}


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent):
    user_text = event.message.text.strip()

    if not user_text.isdigit():
        safe_reply_text(event.reply_token, "請輸入股票代號，例如：2330")
        return

    stock_code = user_text

    try:
        market_data = get_market_info(stock_code)

        if not isinstance(market_data, dict):
            raise TypeError(
                f"market_data 應該是 dict，但收到 {type(market_data).__name__}"
            )

        logger.info(
            "Market data loaded",
            extra={
                "stock_code": stock_code,
                "has_price": market_data.get("price") is not None,
                "has_core": bool(market_data.get("core")),
            },
        )

        if market_data.get("price") is None:
            safe_reply_text(
                event.reply_token,
                "目前暫時查不到這檔股票的市場資料，可能是資料來源逾時或代號有誤，請稍後再試。",
            )
            return

        try:
            ai_result = ai_stock_analysis(market_data)
        except Exception:
            logger.exception("AI analysis failed", extra={"stock_code": stock_code})
            safe_reply_text(
                event.reply_token,
                "市場資料已取得，但 AI 分析服務暫時無法完成，請稍後再試。",
            )
            return

        if isinstance(ai_result, str):
            ai_result = {
                "ai_summary": ai_result,
                "explain": "詳細原因\n目前無法取得完整分析原因。",
            }

        if not isinstance(ai_result, dict):
            raise TypeError(
                f"ai_result 應該是 dict 或 str，但收到 {type(ai_result).__name__}"
            )

        core_data = market_data.get("core") or {}
        composite_data = market_data.get("composite")
        if not isinstance(composite_data, dict):
            composite_data = {}
        data_quality = market_data.get("data_quality")
        if not isinstance(data_quality, dict):
            data_quality = {}

        flex_data = {
            "stock_code": stock_code,
            "stock_name": market_data.get("stock_name", ""),
            "score": core_data.get("score"),
            "confidence": core_data.get("confidence"),
            "decision": core_data.get("decision", "觀察"),
            "risk_level": core_data.get("risk_level", "未評估"),
            "shopkeeper_message": core_data.get(
                "shopkeeper_message",
                "阿柑店長看法：目前先觀察，不急著追高。",
            ),
            "price": market_data.get("price"),
            "change": market_data.get("change"),
            "change_percent": market_data.get("change_percent"),
            "volume": market_data.get("volume"),
            "trend": core_data.get("trend") or market_data.get("trend"),
            "ma_signal": core_data.get("ma_signal") or market_data.get("ma_signal"),
            "macd_signal": core_data.get("macd_signal") or market_data.get("macd_signal"),
            "rsi_signal": core_data.get("rsi_signal") or market_data.get("rsi_signal"),
            "composite_available": composite_data.get("available", False),
            "composite_score": composite_data.get("score"),
            "composite_summary": composite_data.get("summary", ""),
            "composite_coverage": composite_data.get("coverage"),
            "data_quality_status": data_quality.get("status"),
            "data_quality_is_stale": data_quality.get("is_stale", False),
            "ai_summary": ai_result.get(
                "ai_summary",
                "目前資料不足，建議等待更多訊號。",
            ),
            "explain": ai_result.get(
                "explain",
                "尚未產生完整解釋。",
            ),
        }

        flex_message = build_stock_dashboard_flex(flex_data)

        reply_message(event.reply_token, flex_message)

    except Exception:
        logger.exception("LINE message handling failed", extra={"stock_code": stock_code})

        safe_reply_text(
            event.reply_token,
            "系統暫時無法完成查詢，請稍後再試。",
        )


def reply_message(reply_token: str, message):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[message],
            )
        )


def reply_text(reply_token: str, text: str):
    reply_message(
        reply_token,
        TextMessage(text=text),
    )


def safe_reply_text(reply_token: str, text: str):
    try:
        reply_text(reply_token, text)
    except Exception:
        logger.exception("LINE fallback text reply failed")
