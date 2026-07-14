import asyncio
import io
import logging
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import requests
from fastapi import HTTPException
from starlette.requests import Request

from app import webhook
from app import main as app_main
from core import observability
from services import ai_service
from services import asset_service, stock_name_service, stock_service, technical_service
from services import market_service
from services.fundamental_service import FundamentalService


def _capture_events(monkeypatch, module):
    events = []
    monkeypatch.setattr(
        module,
        "log_event",
        lambda logger, event, **fields: events.append((event, fields)),
    )
    return events


class _LoggerState:
    def __init__(self, logger):
        self.logger = logger
        self.level = logger.level
        self.handlers = list(logger.handlers)
        self.propagate = logger.propagate
        self.disabled = logger.disabled

    def restore(self):
        self.logger.handlers[:] = self.handlers
        self.logger.setLevel(self.level)
        self.logger.propagate = self.propagate
        self.logger.disabled = self.disabled


def test_application_startup_enables_root_info_logging():
    root = logging.getLogger()
    state = _LoggerState(root)
    try:
        root.setLevel(logging.WARNING)
        app_main._configure_logging()
        assert root.getEffectiveLevel() == logging.INFO
    finally:
        state.restore()


def test_application_info_event_reaches_existing_root_handler_once():
    root = logging.getLogger()
    state = _LoggerState(root)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    try:
        root.handlers[:] = [handler]
        root.setLevel(logging.WARNING)
        app_main._configure_logging()
        logger = logging.getLogger("services.production_logging_test")
        observability.log_event(
            logger,
            "technical_analysis_end",
            result="success",
            elapsed=12,
            stock_id="2330",
            token="secret",
        )
        handler.flush()
        output = stream.getvalue()
        assert output.count("event=technical_analysis_end") == 1
        assert "stock_id" not in output
        assert "2330" not in output
        assert "secret" not in output
    finally:
        state.restore()


def test_logging_initialization_does_not_duplicate_existing_root_handler():
    root = logging.getLogger()
    state = _LoggerState(root)
    handler = logging.StreamHandler(io.StringIO())
    try:
        root.handlers[:] = [handler]
        app_main._configure_logging()
        app_main._configure_logging()
        assert root.handlers == [handler]
    finally:
        state.restore()


def test_logging_initialization_adds_one_handler_when_root_has_none():
    root = logging.getLogger()
    state = _LoggerState(root)
    try:
        root.handlers[:] = []
        app_main._configure_logging()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.StreamHandler)
    finally:
        state.restore()


def test_logging_initialization_preserves_uvicorn_loggers():
    root = logging.getLogger()
    root_state = _LoggerState(root)
    access_state = _LoggerState(logging.getLogger("uvicorn.access"))
    error_state = _LoggerState(logging.getLogger("uvicorn.error"))
    before = {
        "access": (access_state.level, access_state.handlers, access_state.propagate, access_state.disabled),
        "error": (error_state.level, error_state.handlers, error_state.propagate, error_state.disabled),
    }
    try:
        app_main._configure_logging()
        access = logging.getLogger("uvicorn.access")
        error = logging.getLogger("uvicorn.error")
        assert (access.level, access.handlers, access.propagate, access.disabled) == before["access"]
        assert (error.level, error.handlers, error.propagate, error.disabled) == before["error"]
    finally:
        root_state.restore()
        access_state.restore()
        error_state.restore()


def test_request_id_is_generated_and_cleared():
    token = observability.set_request_id()
    value = observability.get_request_id()
    assert value
    assert len(value) == 36
    observability.clear_request_id(token)
    assert observability.get_request_id() is None


def test_valid_request_id_is_propagated():
    token = observability.set_request_id("request-123_OK")
    assert observability.get_request_id() == "request-123_OK"
    observability.clear_request_id(token)


def test_long_and_control_character_request_ids_are_rejected():
    for value in ("x" * 65, "safe\nforged", "safe\tforged"):
        token = observability.set_request_id(value)
        assert observability.get_request_id() != value
        assert "\n" not in observability.get_request_id()
        assert "\t" not in observability.get_request_id()
        observability.clear_request_id(token)


def test_parallel_contexts_are_isolated():
    async def worker(value):
        token = observability.set_request_id(value)
        await asyncio.sleep(0)
        result = observability.get_request_id()
        observability.clear_request_id(token)
        return result

    async def run_workers():
        return await asyncio.gather(worker("request-a"), worker("request-b"))

    assert asyncio.run(run_workers()) == [
        "request-a",
        "request-b",
    ]


def test_log_event_has_safe_fixed_context(caplog):
    logger = logging.getLogger("observability-test")
    token = observability.set_request_id("safe-id")
    with caplog.at_level(logging.INFO, logger="observability-test"):
        observability.log_event(
            logger,
            "finmind_request_end",
            result="timeout",
            elapsed=12,
            error_type="Timeout",
            service="fundamental",
        )
    observability.clear_request_id(token)
    text = caplog.text
    assert "event=finmind_request_end" in text
    assert "request_id=safe-id" in text
    assert "result=timeout" in text
    assert "elapsed_ms=12" in text
    assert "error_type=Timeout" in text


def test_logging_failure_is_safe():
    class BrokenLogger:
        def info(self, message):
            raise RuntimeError("simulated")

    observability.log_event(BrokenLogger(), "test", result="success", elapsed=0)


def _request(request_id="request-webhook"):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": b"{}", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/webhook",
            "headers": [
                (b"x-request-id", request_id.encode()),
                (b"x-line-signature", b"safe-signature"),
            ],
        },
        receive,
    )


def test_webhook_propagates_one_request_id_and_clears_context(monkeypatch, caplog):
    seen = []
    monkeypatch.setattr(webhook.handler, "handle", lambda body, signature: seen.append(observability.get_request_id()))
    with caplog.at_level(logging.INFO):
        result = asyncio.run(webhook.line_webhook(_request()))
    assert result == {"status": "ok"}
    assert seen == ["request-webhook"]
    assert "event=webhook_request_start request_id=request-webhook" in caplog.text
    assert "event=webhook_request_end request_id=request-webhook" in caplog.text
    assert observability.get_request_id() is None


def test_invalid_signature_event_is_safe(monkeypatch, caplog):
    from linebot.v3.exceptions import InvalidSignatureError

    monkeypatch.setattr(
        webhook.handler,
        "handle",
        lambda body, signature: (_ for _ in ()).throw(InvalidSignatureError("private-signature")),
    )
    with caplog.at_level(logging.INFO), pytest.raises(HTTPException):
        asyncio.run(webhook.line_webhook(_request("invalid-request")))
    assert "event=webhook_signature_invalid" in caplog.text
    assert "private-signature" not in caplog.text
    assert observability.get_request_id() is None


@pytest.mark.parametrize("failure", [RuntimeError("body failed"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")])
def test_webhook_body_or_decode_failure_clears_context(monkeypatch, failure):
    request = _request("failed-body")
    if isinstance(failure, RuntimeError):
        async def broken_body():
            raise failure
        monkeypatch.setattr(request, "body", broken_body)
    else:
        async def invalid_body():
            return b"\xff"
        monkeypatch.setattr(request, "body", invalid_body)
    assert asyncio.run(webhook.line_webhook(request)) == {"status": "error"}
    assert observability.get_request_id() is None


def test_webhook_logging_failure_does_not_prevent_context_clear(monkeypatch):
    monkeypatch.setattr(webhook.handler, "handle", lambda body, signature: None)
    calls = 0

    def broken_log(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("handler failure")

    monkeypatch.setattr(webhook, "log_event", broken_log)
    with pytest.raises(RuntimeError):
        asyncio.run(webhook.line_webhook(_request("logging-failure")))
    assert observability.get_request_id() is None


def test_market_and_flex_failures_always_emit_end(monkeypatch):
    events = []
    monkeypatch.setattr(webhook, "log_event", lambda logger, event, **fields: events.append((event, fields)))
    monkeypatch.setattr(webhook, "get_market_info", lambda code: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(webhook, "safe_reply_text", lambda *args: None)
    event = type("Event", (), {"message": type("Message", (), {"text": "2330"})(), "reply_token": "r"})()
    webhook.handle_text_message(event)
    assert [name for name, _ in events].count("market_analysis_end") == 1
    assert next(fields for name, fields in events if name == "market_analysis_end")["result"] == "error"

    events.clear()
    monkeypatch.setattr(webhook, "get_market_info", lambda code: {"price": 1, "core": {}})
    monkeypatch.setattr(webhook, "ai_stock_analysis", lambda data: {"ai_summary": "s", "explain": "e"})
    monkeypatch.setattr(webhook, "build_stock_dashboard_flex", lambda data: (_ for _ in ()).throw(RuntimeError()))
    webhook.handle_text_message(event)
    assert [name for name, _ in events].count("flex_build_end") == 1
    assert next(fields for name, fields in events if name == "flex_build_end")["result"] == "error"


def test_market_service_unexpected_exception_emits_one_end(monkeypatch):
    events = []
    monkeypatch.setattr(market_service, "log_event", lambda logger, event, **fields: events.append((event, fields)))
    monkeypatch.setattr(market_service, "_build_market_info", lambda stock_id: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        market_service.get_market_info("2330")
    ends = [fields for event, fields in events if event == "market_service_end"]
    assert len(ends) == 1
    assert ends[0]["result"] == "error"


def test_timeout_is_logged_with_safe_error_type(monkeypatch, caplog):
    monkeypatch.setattr(
        "services.fundamental_service.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout("secret-token")),
    )
    with caplog.at_level(logging.INFO):
        assert FundamentalService()._fetch_dataset("TaiwanStockPER", "2330", 10) == []
    assert "result=timeout" in caplog.text
    assert "error_type=Timeout" in caplog.text
    assert "secret-token" not in caplog.text


def test_request_exception_is_fallback_not_timeout(monkeypatch, caplog):
    monkeypatch.setattr(
        "services.fundamental_service.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("private")),
    )
    with caplog.at_level(logging.INFO):
        assert FundamentalService()._fetch_dataset("TaiwanStockPER", "2330", 10) == []
    assert "result=fallback" in caplog.text
    assert "error_type=RequestException" in caplog.text
    assert "result=timeout" not in caplog.text


def test_ai_cache_hit_and_miss_events(monkeypatch, caplog):
    stock = {"stock_id": "2330", "date": "2026-07-13"}
    cached = {"ai_summary": "summary", "explain": "explain"}
    monkeypatch.setattr(ai_service, "get_cache", lambda key: cached)
    monkeypatch.setattr(ai_service, "_is_valid_cached_analysis", lambda value: True)
    monkeypatch.setattr(ai_service, "_limit_analysis_explain", lambda value, fallback=None: value)
    monkeypatch.setattr(ai_service, "_create_client", lambda: pytest.fail("OpenAI called"))
    with caplog.at_level(logging.INFO):
        assert ai_service.ai_stock_analysis(stock) == cached
    assert caplog.text.count("event=ai_cache_hit") == 1
    assert caplog.text.count("event=ai_cache_lookup_end") == 1
    assert "result=cache_hit" in caplog.text
    assert "event=ai_analysis_end" in caplog.text
    assert "result=cache_hit" in caplog.text

    caplog.clear()
    monkeypatch.setattr(ai_service, "get_cache", lambda key: None)
    monkeypatch.setattr(ai_service, "build_analysis_sections", lambda value: cached)
    monkeypatch.setattr(ai_service, "_create_client", lambda: None)
    monkeypatch.setattr(ai_service, "set_cache", lambda key, value: None)
    with caplog.at_level(logging.INFO):
        assert ai_service.ai_stock_analysis(stock) == cached
    assert caplog.text.count("event=ai_cache_miss") == 1
    assert caplog.text.count("event=ai_cache_lookup_end") == 1
    assert "event=openai_analysis_end" in caplog.text
    assert "result=skipped" in caplog.text


def test_openai_failure_has_fallback_event_without_exception_message(monkeypatch, caplog):
    class Completions:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("PRIVATE_OPENAI_RESPONSE")

    class Client:
        class Chat:
            completions = Completions()

        chat = Chat()

    stock = {"stock_id": "2330", "date": "2026-07-13"}
    fallback = {"ai_summary": "summary", "explain": "explain"}
    monkeypatch.setattr(ai_service, "get_cache", lambda key: None)
    monkeypatch.setattr(ai_service, "build_analysis_sections", lambda value: fallback)
    monkeypatch.setattr(ai_service, "_create_client", lambda: Client())
    monkeypatch.setattr(ai_service, "set_cache", lambda key, value: None)
    with caplog.at_level(logging.INFO):
        assert ai_service.ai_stock_analysis(stock) == fallback
    assert "event=openai_analysis_end" in caplog.text
    assert "result=fallback" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "PRIVATE_OPENAI_RESPONSE" not in caplog.text


def test_invalid_cache_falls_back_without_creating_client(monkeypatch, caplog):
    stock = {"stock_id": "2330", "date": "2026-07-13"}
    fallback = {"ai_summary": "summary", "explain": "explain"}
    monkeypatch.setattr(ai_service, "get_cache", lambda key: {"bad": True})
    monkeypatch.setattr(ai_service, "build_analysis_sections", lambda value: fallback)
    monkeypatch.setattr(ai_service, "_create_client", lambda: pytest.fail("client created"))
    with caplog.at_level(logging.INFO):
        assert ai_service.ai_stock_analysis(stock) == fallback
    assert "result=fallback" in caplog.text
    assert "error_type=InvalidCacheEntry" in caplog.text
    assert caplog.text.count("event=ai_cache_lookup_end") == 1
    assert "cache_status=invalid" in caplog.text


def test_client_initialization_failure_falls_back(monkeypatch, caplog):
    stock = {"stock_id": "2330", "date": "2026-07-13"}
    fallback = {"ai_summary": "summary", "explain": "explain"}
    monkeypatch.setattr(ai_service, "get_cache", lambda key: None)
    monkeypatch.setattr(ai_service, "build_analysis_sections", lambda value: fallback)
    monkeypatch.setattr(ai_service, "_create_client", lambda: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(ai_service, "set_cache", lambda *args: None)
    with caplog.at_level(logging.INFO):
        assert ai_service.ai_stock_analysis(stock) == fallback
    assert "error_type=ClientInitializationError" in caplog.text


@pytest.mark.parametrize("value", [None, "bad", float("nan"), float("inf"), -10, True])
def test_invalid_elapsed_values_are_safe(value, caplog):
    logger = logging.getLogger("elapsed-test")
    with caplog.at_level(logging.INFO, logger="elapsed-test"):
        observability.log_event(logger, "safe_event", result="success", elapsed=value)
    if value is not None:
        assert "elapsed_ms=0" in caplog.text


def test_invalid_result_and_expanded_sensitive_fields_are_safe(caplog):
    logger = logging.getLogger("contract-test")
    with caplog.at_level(logging.INFO, logger="contract-test"):
        observability.log_event(
            logger, "safe_event", result="unexpected",
            finmind_token="SECRET_A", finmind_api_token="SECRET_B", openai_api_key="SECRET_C",
            line_channel_secret="SECRET_D", line_channel_access_token="SECRET_E",
            authorization="SECRET_F", headers="SECRET_G",
        )
    assert "result=error" in caplog.text
    assert all(f"SECRET_{letter}" not in caplog.text for letter in "ABCDEFG")


def test_profiling_events_filter_stock_identifiers(caplog):
    logger = logging.getLogger("profiling-privacy")
    with caplog.at_level(logging.INFO, logger="profiling-privacy"):
        observability.log_event(
            logger, "price_request_end", result="success", elapsed=1,
            stock_id="2330", stock_code="2330", service="price",
        )
    assert "2330" not in caplog.text
    assert "elapsed_ms=1" in caplog.text


@pytest.mark.parametrize(
    "value",
    [None, "bad", True, float("nan"), float("inf"), -1, [], {}, object()],
)
def test_elapsed_ms_invalid_inputs_are_safe(value):
    assert observability.elapsed_ms(value) == 0


@pytest.mark.parametrize("ending", [float("nan"), float("inf"), "bad", None, True])
def test_elapsed_ms_invalid_clock_values_are_safe(monkeypatch, ending):
    monkeypatch.setattr(observability, "perf_counter", lambda: ending)
    assert observability.elapsed_ms(1.0) == 0


def test_elapsed_ms_clock_failure_and_clock_rollback_are_safe(monkeypatch):
    monkeypatch.setattr(
        observability,
        "perf_counter",
        lambda: (_ for _ in ()).throw(RuntimeError("clock failed")),
    )
    assert observability.elapsed_ms(1.0) == 0
    monkeypatch.setattr(observability, "perf_counter", lambda: 1.0)
    assert observability.elapsed_ms(2.0) == 0


@pytest.mark.parametrize(
    ("cache_valid", "download_result", "expected"),
    [
        (True, None, "cache_hit"),
        (False, ({"2330": {"stock_name": "name"}}, "success"), "success"),
        (False, ({}, "timeout"), "timeout"),
    ],
)
def test_stock_name_lookup_profiling(monkeypatch, cache_valid, download_result, expected):
    events = _capture_events(monkeypatch, stock_name_service)
    monkeypatch.setattr(stock_name_service, "is_cache_valid", lambda: cache_valid)
    monkeypatch.setattr(stock_name_service, "load_stock_names", lambda: {"2330": {"stock_name": "name"}})
    if download_result is not None:
        monkeypatch.setattr(stock_name_service, "_download_stock_names_with_result", lambda: download_result)
    stock_name_service.get_stock_name("2330")
    matches = [fields for event, fields in events if event == "stock_name_lookup_end"]
    assert len(matches) == 1
    assert matches[0]["result"] == expected
    assert isinstance(matches[0]["elapsed"], int) and matches[0]["elapsed"] >= 0


@pytest.mark.parametrize(("mode", "expected"), [("hit", "cache_hit"), ("refresh", "success"), ("partial", "fallback")])
def test_asset_overall_profiling(monkeypatch, tmp_path, mode, expected):
    events = _capture_events(monkeypatch, asset_service)
    service = asset_service.AssetService(tmp_path / "asset.json")
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    asset = {"type": "stock", "source": "twse_company", "confidence": "high"}
    cache = {"assets": {"2330": asset}, "sources": {name: {"status": "ok"} for name in asset_service.SOURCE_NAMES}}
    monkeypatch.setattr(service, "_load_cache", lambda: cache)
    monkeypatch.setattr(service, "_safe_now", lambda: now)
    monkeypatch.setattr(service, "_cache_is_fresh", lambda value, current: mode == "hit")
    if mode != "hit":
        refreshed = dict(cache)
        refreshed["sources"] = {
            name: {"status": "failed" if mode == "partial" and name == "twse_etf" else "ok"}
            for name in asset_service.SOURCE_NAMES
        }
        monkeypatch.setattr(service, "_refresh", lambda old, current: refreshed)
    assert service.get_asset("2330")["type"] == "stock"
    matches = [fields for event, fields in events if event == "asset_analysis_end"]
    assert len(matches) == 1
    assert matches[0]["result"] == expected


class _Response:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return {"data": self._data}


def test_price_and_history_profiling(monkeypatch):
    events = _capture_events(monkeypatch, stock_service)
    row = {"date": "2026-07-14", "close": 1, "open": 1, "max": 1, "min": 1, "Trading_Volume": 1}
    monkeypatch.setattr(stock_service.requests, "get", lambda *args, **kwargs: _Response([row]))
    assert stock_service.get_stock_info("2330")["close"] == 1
    assert stock_service.get_stock_history("2330") == [row]
    assert [event for event, _ in events].count("price_request_end") == 1
    assert [event for event, _ in events].count("price_history_request_end") == 1
    assert all(fields["result"] == "success" for _, fields in events)


def test_price_timeout_and_history_fallback_profiling(monkeypatch):
    events = _capture_events(monkeypatch, stock_service)
    monkeypatch.setattr(stock_service.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout()))
    assert stock_service.get_stock_info("2330") is None
    assert next(fields for event, fields in events if event == "price_request_end")["result"] == "timeout"
    events.clear()
    monkeypatch.setattr(stock_service.requests, "get", lambda *args, **kwargs: _Response([]))
    assert stock_service.get_stock_history("2330") == []
    assert next(fields for event, fields in events if event == "price_history_request_end")["result"] == "fallback"


@pytest.mark.parametrize(("value", "expected"), [({"rsi": 50}, "success"), (None, "fallback")])
def test_technical_overall_profiling(monkeypatch, value, expected):
    events = _capture_events(monkeypatch, technical_service)
    monkeypatch.setattr(technical_service, "_calculate_technical_indicators", lambda stock_id: value)
    assert technical_service.get_technical_indicators("2330") == value
    matches = [fields for event, fields in events if event == "technical_analysis_end"]
    assert len(matches) == 1
    assert matches[0]["result"] == expected


def test_market_engine_stage_profiling(monkeypatch):
    events = _capture_events(monkeypatch, market_service)
    assert market_service._get_fundamental_analysis(
        SimpleNamespace(analyze=lambda *args, **kwargs: {"available": False, "applicability": "not_applicable"}),
        "0050", {"type": "etf"},
    )["applicability"] == "not_applicable"
    market_service._get_institution_analysis(SimpleNamespace(analyze=lambda value: {"available": True}), "2330")
    market_service._get_news_analysis(SimpleNamespace(analyze=lambda value: {"available": True}), "2330")
    market_service._get_composite_analysis(SimpleNamespace(analyze=lambda *args: {"available": True}), {}, {}, {}, {})
    market_service._get_data_quality(SimpleNamespace(analyze=lambda value: {"status": "正常"}), {})
    data = {"core": {"shopkeeper_message": "old", "decision": "觀察"}, "composite": {"available": False}}
    monkeypatch.setattr(market_service, "get_composite_aware_advice", lambda *args: "old")
    market_service._update_shopkeeper_message(data)
    expected = {
        "fundamental_analysis_end": "skipped",
        "institution_analysis_end": "success",
        "news_analysis_end": "success",
        "composite_analysis_end": "success",
        "data_quality_analysis_end": "success",
        "shopkeeper_analysis_end": "skipped",
    }
    for event, result in expected.items():
        matches = [fields for name, fields in events if name == event]
        assert len(matches) == 1
        assert matches[0]["result"] == result


@pytest.mark.parametrize(
    ("composite", "decision"),
    [
        (None, "unsupported"),
        ({"available": False}, "unsupported"),
        ({"available": True, "score": 70, "summary": "ok", "coverage": 80}, "unsupported"),
        ({"available": True, "score": float("nan"), "summary": "ok", "coverage": 80}, "偏多"),
        ({"available": True, "score": 70, "summary": "ok", "coverage": float("inf")}, "偏多"),
    ],
)
def test_shopkeeper_unchanged_paths_are_skipped_once(monkeypatch, composite, decision):
    events = _capture_events(monkeypatch, market_service)
    data = {"core": {"shopkeeper_message": "original", "decision": decision}, "composite": composite}
    market_service._update_shopkeeper_message(data)
    assert data["core"]["shopkeeper_message"] == "original"
    matches = [fields for event, fields in events if event == "shopkeeper_analysis_end"]
    assert len(matches) == 1
    assert matches[0]["result"] == "skipped"


def test_shopkeeper_update_is_success_once(monkeypatch):
    events = _capture_events(monkeypatch, market_service)
    data = {"core": {"shopkeeper_message": "original", "decision": "supported"}, "composite": {}}
    monkeypatch.setattr(market_service, "get_composite_aware_advice", lambda *args: "updated")
    market_service._update_shopkeeper_message(data)
    assert data["core"]["shopkeeper_message"] == "updated"
    matches = [fields for event, fields in events if event == "shopkeeper_analysis_end"]
    assert len(matches) == 1
    assert matches[0]["result"] == "success"
    assert not set(matches[0]) & {"stock_id", "user_id", "prompt", "response", "market_data"}


def test_shopkeeper_helper_failure_is_safe_fallback_once(monkeypatch):
    events = _capture_events(monkeypatch, market_service)
    data = {"core": {"shopkeeper_message": "original", "decision": "supported"}, "composite": {}}
    monkeypatch.setattr(
        market_service,
        "get_composite_aware_advice",
        lambda *args: (_ for _ in ()).throw(RuntimeError("helper failed")),
    )
    market_service._update_shopkeeper_message(data)
    assert data["core"]["shopkeeper_message"] == "original"
    matches = [fields for event, fields in events if event == "shopkeeper_analysis_end"]
    assert len(matches) == 1
    assert matches[0]["result"] == "fallback"
    assert matches[0]["error_type"] == "RuntimeError"


def test_shopkeeper_timing_and_logging_failures_do_not_affect_update(monkeypatch):
    data = {"core": {"shopkeeper_message": "original", "decision": "supported"}, "composite": {}}
    monkeypatch.setattr(market_service, "perf_counter", lambda: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(market_service, "elapsed_ms", lambda value: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(market_service, "log_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(market_service, "get_composite_aware_advice", lambda *args: "updated")
    market_service._update_shopkeeper_message(data)
    assert data["core"]["shopkeeper_message"] == "updated"


def test_market_service_timing_and_logging_failures_do_not_affect_result(monkeypatch):
    expected = {"price": 100, "core": {"score": 50}}
    monkeypatch.setattr(market_service, "_build_market_info", lambda stock_id: expected)
    monkeypatch.setattr(market_service, "perf_counter", lambda: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(market_service, "elapsed_ms", lambda value: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(market_service, "log_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()))
    assert market_service.get_market_info("2330") is expected


@pytest.mark.parametrize(("raises", "expected"), [(False, "success"), (True, "fallback")])
def test_ai_core_stage_profiling(monkeypatch, raises, expected):
    events = _capture_events(monkeypatch, market_service)
    if raises:
        monkeypatch.setattr(market_service.GanzaiAI, "run", lambda self: (_ for _ in ()).throw(RuntimeError()))
    else:
        monkeypatch.setattr(market_service.GanzaiAI, "run", lambda self: {"score": 50})
    result = market_service._get_ai_core_analysis({"price": 1})
    assert isinstance(result, dict)
    matches = [fields for event, fields in events if event == "ai_core_analysis_end"]
    assert len(matches) == 1
    assert matches[0]["result"] == expected


def test_ai_cache_lookup_profiling_and_request_id(monkeypatch):
    events = _capture_events(monkeypatch, ai_service)
    token = observability.set_request_id("profile-request")
    try:
        monkeypatch.setattr(ai_service, "get_cache", lambda key: None)
        monkeypatch.setattr(ai_service, "build_analysis_sections", lambda value: {"ai_summary": "s", "explain": "e"})
        monkeypatch.setattr(ai_service, "_create_client", lambda: None)
        monkeypatch.setattr(ai_service, "set_cache", lambda *args: None)
        monkeypatch.setattr(ai_service, "_track_usage", lambda **kwargs: None)
        ai_service.ai_stock_analysis({"stock_id": "2330", "date": "2026-07-14"})
    finally:
        observability.clear_request_id(token)
    matches = [fields for event, fields in events if event == "ai_cache_lookup_end"]
    assert len(matches) == 1
    assert matches[0]["result"] == "cache_miss"


def test_sensitive_fields_are_never_logged(caplog):
    logger = logging.getLogger("sensitive-log-test")
    with caplog.at_level(logging.INFO, logger="sensitive-log-test"):
        observability.log_event(
            logger,
            "safe_event",
            result="success",
            token="FINMIND_SECRET",
            api_key="OPENAI_SECRET",
            prompt="FULL_PROMPT",
            response="FULL_RESPONSE",
            market_data="FULL_MARKET_DATA",
            user_id="LINE_USER_ID",
        )
    assert all(
        secret not in caplog.text
        for secret in (
            "FINMIND_SECRET", "OPENAI_SECRET", "FULL_PROMPT",
            "FULL_RESPONSE", "FULL_MARKET_DATA", "LINE_USER_ID",
        )
    )
