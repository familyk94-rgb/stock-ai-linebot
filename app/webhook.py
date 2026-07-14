import logging

from time import perf_counter

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
from core.observability import clear_request_id, elapsed_ms, log_event, set_request_id


router = APIRouter()
logger = logging.getLogger(__name__)

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN or "")
handler = WebhookHandler(LINE_CHANNEL_SECRET or "")


@router.post("/webhook")
async def line_webhook(request: Request):
    request_token = set_request_id(request.headers.get("X-Request-ID"))
    started_at = perf_counter()
    request_result = "success"
    log_event(logger, "webhook_request_start", result="success")
    try:
        signature = request.headers.get("X-Line-Signature")
        body = await request.body()
        body_text = body.decode("utf-8")
        handler.handle(body_text, signature)
    except InvalidSignatureError:
        request_result = "error"
        log_event(logger, "webhook_signature_invalid", result="error")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as error:
        request_result = "error"
        log_event(logger, "webhook_handler_end", result="error", error_type=type(error).__name__)
        return {"status": "error"}

    finally:
        try:
            log_event(
                logger,
                "webhook_request_end",
                result=request_result,
                elapsed=elapsed_ms(started_at),
            )
        finally:
            clear_request_id(request_token)

    return {"status": "ok"}


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent):
    user_text = event.message.text.strip()

    if not user_text.isdigit():
        safe_reply_text(event.reply_token, "請輸入股票代號，例如：2330")
        return

    stock_code = user_text
    log_event(logger, "stock_query_received", result="success", stock_id=stock_code)

    try:
        market_started = perf_counter()
        log_event(logger, "market_analysis_start", result="success")
        try:
            market_data = get_market_info(stock_code)
            if not isinstance(market_data, dict):
                raise TypeError(
                    f"market_data 應該是 dict，但收到 {type(market_data).__name__}"
                )
            market_result = "success" if market_data.get("price") is not None else "fallback"
        except TimeoutError as error:
            log_event(logger, "market_analysis_end", result="timeout", elapsed=elapsed_ms(market_started), error_type=type(error).__name__)
            raise
        except Exception as error:
            log_event(logger, "market_analysis_end", result="error", elapsed=elapsed_ms(market_started), error_type=type(error).__name__)
            raise
        else:
            log_event(logger, "market_analysis_end", result=market_result, elapsed=elapsed_ms(market_started))

        log_event(logger, "market_data_loaded", result=market_result, stock_id=stock_code)

        if market_data.get("price") is None:
            safe_reply_text(
                event.reply_token,
                "目前暫時查不到這檔股票的市場資料，可能是資料來源逾時或代號有誤，請稍後再試。",
            )
            return

        try:
            ai_started = perf_counter()
            log_event(logger, "ai_analysis_start", result="success")
            ai_result = ai_stock_analysis(market_data)
            log_event(logger, "ai_analysis_end", result="success", elapsed=elapsed_ms(ai_started))
        except Exception as error:
            log_event(logger, "ai_analysis_end", result="fallback", elapsed=elapsed_ms(ai_started), error_type=type(error).__name__)
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

        flex_started = perf_counter()
        log_event(logger, "flex_build_start", result="success")
        try:
            flex_message = build_stock_dashboard_flex(flex_data)
        except Exception as error:
            log_event(logger, "flex_build_end", result="error", elapsed=elapsed_ms(flex_started), error_type=type(error).__name__)
            raise
        else:
            log_event(logger, "flex_build_end", result="success", elapsed=elapsed_ms(flex_started))

        reply_message(event.reply_token, flex_message)

    except Exception as error:
        log_event(logger, "line_message_end", result="error", error_type=type(error).__name__, stock_id=stock_code)

        safe_reply_text(
            event.reply_token,
            "系統暫時無法完成查詢，請稍後再試。",
        )


def reply_message(reply_token: str, message):
    started_at = perf_counter()
    log_event(logger, "line_reply_start", result="success")
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[message],
                )
            )
        log_event(logger, "line_reply_end", result="success", elapsed=elapsed_ms(started_at))
    except Exception as error:
        log_event(logger, "line_reply_end", result="error", elapsed=elapsed_ms(started_at), error_type=type(error).__name__)
        raise


def reply_text(reply_token: str, text: str):
    reply_message(
        reply_token,
        TextMessage(text=text),
    )


def safe_reply_text(reply_token: str, text: str):
    try:
        reply_text(reply_token, text)
    except Exception as error:
        log_event(logger, "line_fallback_reply_end", result="error", error_type=type(error).__name__)
