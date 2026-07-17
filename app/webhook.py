import logging

import re
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
from app.flex.alert_list_card import build_alert_list_flex
from app.flex.alert_creation_card import build_alert_creation_confirmation_flex
from app.flex.builder import build_stock_dashboard_flex
from core.models.alert_creation import AlertCreationStep
from services.alert_creation_service import AlertCreationService, format_price
from services.alert_management_service import AlertManagementService
from services.ai_service import ai_stock_analysis
from services.market_service import get_market_info
from services.stock_name_service import get_stock_name
from services.watchlist_service import WatchlistService
from core.observability import clear_request_id, elapsed_ms, log_event, set_request_id


router = APIRouter()
logger = logging.getLogger(__name__)

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN or "")
handler = WebhookHandler(LINE_CHANNEL_SECRET or "")
watchlist_service = WatchlistService()
alert_management_service = AlertManagementService()
alert_creation_service = AlertCreationService()

_WATCHLIST_COMMANDS = {
    "加入自選": "add",
    "移除自選": "remove",
}
_STOCK_ID_PATTERN = re.compile(r"^[0-9]+$")


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

    if user_text in {"取消", "取消提醒", "結束"}:
        _handle_alert_creation_cancel(event)
        return

    user_id = _line_user_id(event)
    if user_id is not None:
        try:
            active_session = alert_creation_service.get_session(user_id)
            expired_session = alert_creation_service.consume_expired(user_id)
        except Exception as error:
            _alert_creation_error(event, error)
            return
        if active_session is not None:
            _handle_alert_creation_session(event, user_id, user_text)
            return
        if expired_session:
            safe_reply_text(event.reply_token, "提醒設定已逾時，請重新輸入『新增提醒』。")
            return

    if user_text == "新增提醒":
        _handle_alert_creation_start(event)
        return

    if user_text == "我的提醒":
        _handle_alert_management_command(event, user_text)
        return

    watchlist_command = _parse_watchlist_command(user_text)
    if watchlist_command is not None:
        _handle_watchlist_command(event, *watchlist_command)
        return

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
        quote_data = market_data.get("quote")
        if not isinstance(quote_data, dict):
            quote_data = {}

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
            "quote": quote_data,
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


def _parse_watchlist_command(text: str) -> tuple[str, str | None] | None:
    if text == "我的自選":
        return "list", None
    for prefix, action in _WATCHLIST_COMMANDS.items():
        if text.startswith(prefix):
            return action, text[len(prefix):].strip()
    return None


def _handle_watchlist_command(event: MessageEvent, action: str, stock_id: str | None) -> None:
    user_id = _line_user_id(event)
    if user_id is None:
        safe_reply_text(event.reply_token, "無法識別使用者，請稍後再試。")
        return

    try:
        if action == "list":
            safe_reply_text(
                event.reply_token,
                _format_watchlist(watchlist_service.list_stocks(user_id)),
            )
            return

        if not stock_id:
            safe_reply_text(event.reply_token, "請輸入股票代號")
            return
        if _STOCK_ID_PATTERN.fullmatch(stock_id) is None:
            safe_reply_text(event.reply_token, "股票代號格式錯誤")
            return

        if action == "add":
            stock_name = get_stock_name(stock_id)
            if (
                not isinstance(stock_name, str)
                or not stock_name.strip()
                or stock_name == "未知股票"
            ):
                safe_reply_text(event.reply_token, "查無此股票")
                return
            if watchlist_service.add_stock(user_id, stock_id, stock_name):
                safe_reply_text(
                    event.reply_token,
                    f"✅ 已加入自選股\n\n{stock_id} {stock_name.strip()}",
                )
            else:
                safe_reply_text(event.reply_token, f"⚠️ {stock_id} 已在自選股中")
            return

        stocks = watchlist_service.list_stocks(user_id)
        stock_name = next(
            (
                str(stock.get("stock_name", "")).strip()
                for stock in stocks
                if isinstance(stock, dict)
                and str(stock.get("stock_id", "")).strip() == stock_id
            ),
            "",
        )
        if not watchlist_service.remove_stock(user_id, stock_id):
            safe_reply_text(event.reply_token, f"⚠️ 自選股中沒有 {stock_id}")
            return
        safe_reply_text(
            event.reply_token,
            f"✅ 已移除自選股\n\n{stock_id} {stock_name}".rstrip(),
        )
    except Exception as error:
        log_event(
            logger,
            "watchlist_command_end",
            result="error",
            error_type=type(error).__name__,
        )
        safe_reply_text(event.reply_token, "自選股服務暫時無法使用，請稍後再試。")


def _handle_alert_management_command(event: MessageEvent, command: str) -> None:
    user_id = _line_user_id(event)
    if user_id is None:
        safe_reply_text(event.reply_token, "無法識別使用者，請稍後再試。")
        return

    try:
        result = alert_management_service.list_user_alerts(user_id)
        reply_message(event.reply_token, build_alert_list_flex(result))
    except Exception as error:
        log_event(
            logger,
            "line_message_end",
            result="error",
            error_type=type(error).__name__,
        )
        safe_reply_text(event.reply_token, "提醒服務暫時無法使用，請稍後再試。")


def _handle_alert_creation_start(event: MessageEvent) -> None:
    user_id = _line_user_id(event)
    if user_id is None:
        safe_reply_text(event.reply_token, "無法識別使用者，請稍後再試。")
        return
    try:
        result = alert_creation_service.start(user_id)
        safe_reply_text(event.reply_token, result.message + "\n\n輸入「取消」可結束設定。")
    except Exception as error:
        _alert_creation_error(event, error)


def _handle_alert_creation_cancel(event: MessageEvent) -> None:
    user_id = _line_user_id(event)
    if user_id is None:
        safe_reply_text(event.reply_token, "無法識別使用者，請稍後再試。")
        return
    try:
        result = alert_creation_service.cancel(user_id)
        safe_reply_text(event.reply_token, result.message)
    except Exception as error:
        _alert_creation_error(event, error)


def _handle_alert_creation_session(event: MessageEvent, user_id: str, text: str) -> None:
    try:
        session = alert_creation_service.get_session(user_id)
        if session is None:
            safe_reply_text(event.reply_token, "提醒設定已逾時，請重新輸入『新增提醒』。")
            return
        if text in {"重新輸入", "重新開始"}:
            result = alert_creation_service.restart(user_id)
        elif text in {"確認建立", "確認"}:
            result = alert_creation_service.confirm(user_id)
        elif session.step is AlertCreationStep.AWAITING_STOCK_ID:
            result = alert_creation_service.receive_stock_id(user_id, text)
        elif session.step is AlertCreationStep.AWAITING_CONDITION:
            result = alert_creation_service.select_condition(user_id, text)
        elif session.step is AlertCreationStep.AWAITING_TARGET:
            result = alert_creation_service.receive_target(user_id, text)
        else:
            result = alert_creation_service.confirm(user_id)
        _reply_alert_creation_result(event, result)
    except Exception as error:
        _alert_creation_error(event, error)


def _reply_alert_creation_result(event: MessageEvent, result) -> None:
    if result.status == "awaiting_condition":
        safe_reply_text(event.reply_token, "請選擇提醒條件：\n股價突破\n股價跌破\n取消")
    elif result.status == "awaiting_target":
        safe_reply_text(event.reply_token, result.message + "\n\n可輸入「重新開始」或「取消」。")
    elif result.status == "awaiting_confirmation":
        reply_message(event.reply_token, build_alert_creation_confirmation_flex(result))
    elif result.status == "created":
        alert = result.created_alert or {}
        condition = "股價突破" if alert.get("condition") == "GT" else "股價跌破"
        stock_id = str(alert.get("stock_id", "")).strip()
        stock_name = str(alert.get("stock_name", "")).strip()
        target = alert.get("target_price")
        safe_reply_text(
            event.reply_token,
            "提醒建立成功\n\n"
            f"{stock_id} {stock_name}".rstrip()
            + f"\n{condition} {format_price(target)}\n\n可輸入「我的提醒」查看。",
        )
    else:
        safe_reply_text(event.reply_token, result.message)


def _alert_creation_error(event: MessageEvent, error: Exception) -> None:
    log_event(
        logger,
        "line_message_end",
        result="error",
        error_type=type(error).__name__,
    )
    safe_reply_text(event.reply_token, "提醒設定暫時無法使用，請稍後再試。")


def _line_user_id(event: MessageEvent) -> str | None:
    source = getattr(event, "source", None)
    user_id = getattr(source, "user_id", None)
    if not isinstance(user_id, str) or not user_id.strip():
        return None
    return user_id.strip()


def _format_watchlist(stocks) -> str:
    if not isinstance(stocks, list) or not stocks:
        return "目前沒有自選股"
    lines = []
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        stock_id = str(stock.get("stock_id", "")).strip()
        stock_name = str(stock.get("stock_name", "")).strip()
        if stock_id:
            lines.append(f"{len(lines) + 1}. {stock_id} {stock_name}".rstrip())
    if not lines:
        return "目前沒有自選股"
    return "⭐ 我的自選股\n\n" + "\n".join(lines)


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
