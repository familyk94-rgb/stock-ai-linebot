"""Small, dependency-free observability helpers for request-scoped logging."""

from __future__ import annotations

import logging
import math
import re
import uuid
from contextvars import ContextVar, Token
from time import perf_counter


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SAFE_VALUE = re.compile(r"[^A-Za-z0-9._:/-]+")
_SENSITIVE_KEYS = {
    "token", "api_key", "secret", "prompt", "response", "market_data",
    "user_id", "user_message", "news_content", "headers", "authorization",
    "finmind_token", "finmind_api_token", "openai_api_key",
    "line_channel_secret", "line_channel_access_token",
    "stock_id", "stock_code",
}
VALID_RESULTS = frozenset(
    {"success", "fallback", "timeout", "error", "skipped", "cache_hit", "cache_miss"}
)
EVENTS = frozenset(
    {
        "webhook_request_start", "webhook_request_end", "webhook_signature_invalid",
        "webhook_handler_end", "stock_query_received", "market_analysis_start",
        "market_analysis_end", "market_service_start", "market_service_end",
        "market_data_loaded", "ai_analysis_start", "ai_analysis_end",
        "ai_cache_hit", "ai_cache_miss", "openai_analysis_end", "ai_core_end",
        "flex_build_start", "flex_build_end", "line_reply_start", "line_reply_end",
        "line_message_end", "line_fallback_reply_end", "finmind_request_end",
        "asset_request_end", "asset_cache_hit", "asset_cache_miss",
        "asset_cache_write_end", "service_fallback",
        "usage_record_success", "usage_record_error",
        "usage_summary_query_success", "usage_summary_query_error",
        "pricing_unknown", "usage_metadata_missing",
        "stock_name_lookup_end", "asset_analysis_end",
        "price_request_end", "price_history_request_end",
        "technical_analysis_end", "ai_core_analysis_end",
        "fundamental_analysis_end", "institution_analysis_end",
        "news_analysis_end", "composite_analysis_end",
        "shopkeeper_analysis_end", "data_quality_analysis_end",
        "ai_cache_lookup_end",
    }
)


def result_for_error(error: BaseException) -> str:
    return "timeout" if type(error).__name__ in {
        "Timeout", "TimeoutError", "APITimeoutError", "ConnectTimeout", "ReadTimeout"
    } else "error"


def generate_request_id() -> str:
    return str(uuid.uuid4())


def sanitize_request_id(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if _SAFE_REQUEST_ID.fullmatch(value) else None


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value=None) -> Token:
    return _request_id.set(sanitize_request_id(value) or generate_request_id())


def clear_request_id(token: Token | None = None) -> None:
    if token is None:
        _request_id.set(None)
    else:
        _request_id.reset(token)


def elapsed_ms(started_at: float) -> int:
    try:
        if isinstance(started_at, bool):
            return 0
        started = float(started_at)
        if not math.isfinite(started) or started < 0:
            return 0
        ended_at = perf_counter()
        if isinstance(ended_at, bool):
            return 0
        ended = float(ended_at)
        if not math.isfinite(ended) or ended < started:
            return 0
        value = (ended - started) * 1000
        if not math.isfinite(value):
            return 0
        return max(0, int(round(value)))
    except Exception:
        return 0


def _safe_elapsed(value) -> int:
    try:
        if isinstance(value, bool):
            return 0
        number = float(value)
        if not math.isfinite(number) or number < 0:
            return 0
        return round(number)
    except (TypeError, ValueError, OverflowError):
        return 0


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    result: str,
    elapsed: int | None = None,
    error_type: str | None = None,
    **fields,
) -> None:
    """Emit stable key/value logs; logging failures never affect the caller."""
    try:
        values = {
            "event": event,
            "request_id": get_request_id() or "none",
            "result": result if result in VALID_RESULTS else "error",
        }
        if elapsed is not None:
            values["elapsed_ms"] = _safe_elapsed(elapsed)
        if error_type:
            values["error_type"] = type(error_type).__name__ if not isinstance(error_type, str) else error_type
        for key, value in fields.items():
            if key.casefold() in _SENSITIVE_KEYS:
                continue
            if value is None or isinstance(value, (dict, list, tuple, set)):
                continue
            safe = _SAFE_VALUE.sub("_", str(value))[:128]
            values[key] = safe
        message = " ".join(f"{key}={value}" for key, value in values.items())
        logger.info(message)
    except Exception:
        return
