import asyncio
import logging

import pytest
import requests
from fastapi import HTTPException
from starlette.requests import Request

from app import webhook
from core import observability
from services import ai_service
from services import market_service
from services.fundamental_service import FundamentalService


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
