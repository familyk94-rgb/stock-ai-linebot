import importlib
import json
import logging
from copy import deepcopy
from types import SimpleNamespace

import pytest

import services.ai_service as ai_service
from core import observability
from core.explain_engine import build_analysis_sections
from services.cache_service import CACHE


def _stock(date: str = "2026-07-10") -> dict:
    return {
        "stock_id": "2330",
        "stock_name": "台積電",
        "date": date,
        "price": 90,
        "technical": {"ma20": 100, "ma60": 80, "rsi": 55},
        "core": {
            "trend": "整理",
            "decision": "觀察",
            "confidence": 75,
            "risk_level": "中等風險",
        },
    }


def test_no_api_key_import_and_fallback(monkeypatch):
    CACHE.clear()
    module = importlib.reload(ai_service)
    monkeypatch.setattr(module, "OPENAI_API_KEY", "")

    result = module.ai_stock_analysis(_stock("no-key"))

    assert "趨勢總結：" in result["ai_summary"]
    assert "技術面：" in result["explain"]
    assert CACHE == {}


def test_timeout_uses_fallback(monkeypatch):
    CACHE.clear()
    observed = {}

    class FakeCompletions:
        def create(self, **kwargs):
            observed["timeout"] = kwargs.get("timeout")
            raise TimeoutError("simulated timeout")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(ai_service, "_create_client", lambda: fake_client)

    result = ai_service.ai_stock_analysis(_stock("timeout"))

    assert observed["timeout"] == 15
    assert result == build_analysis_sections(_stock("timeout"))


def test_duplicate_model_response_is_rejected():
    fallback = build_analysis_sections(_stock("duplicate"))
    repeated = "目前趨勢偏弱建議保守觀察"
    model_result = {
        "ai_summary": (
            f"摘要\n趨勢總結：{repeated}\n短線建議：避免追高\n"
            "中線建議：等待轉強\n長線建議：持續追蹤\nAI信心度：75%"
        ),
        "explain": (
            f"詳細原因\n技術面：{repeated}\n基本面：尚未整合\n"
            "籌碼面：尚未整合\n市場情緒：中性\n操作建議：觀察\n風險提醒：控制部位"
        ),
    }

    result = ai_service._parse_analysis(
        json.dumps(model_result, ensure_ascii=False),
        fallback,
        require_missing_fundamental=True,
        require_missing_chip=True,
    )

    assert result == fallback


def test_missing_fundamental_and_chip_are_preserved():
    fallback = build_analysis_sections(_stock("missing-data"))

    assert "基本面：尚未整合" in fallback["explain"]
    assert "籌碼面：尚未整合" in fallback["explain"]


def test_model_cannot_replace_missing_data_status():
    fallback = build_analysis_sections(_stock("invalid-missing-data"))
    model_result = {
        "ai_summary": (
            "摘要\n趨勢總結：整理\n短線建議：觀察\n中線建議：等待\n"
            "長線建議：追蹤\nAI信心度：75%"
        ),
        "explain": (
            "詳細原因\n技術面：中性\n基本面：未知\n籌碼面：資料不足\n"
            "市場情緒：中性\n操作建議：觀察\n風險提醒：控制部位"
        ),
    }

    result = ai_service._parse_analysis(
        json.dumps(model_result, ensure_ascii=False),
        fallback,
        require_missing_fundamental=True,
        require_missing_chip=True,
    )

    assert result == fallback


def test_stock_price_is_used_for_mid_term_advice():
    result = build_analysis_sections(_stock("stock-price"))

    assert "中線建議：尚未站回 MA20 前以保守觀察為主。" in result["ai_summary"]


def _stock_with_news_and_composite(date: str) -> dict:
    stock = _stock(date)
    stock["news"] = {
        "available": True,
        "summary": "新聞情緒中性",
        "score": 50,
        "signals": ["近 7 日中立新聞 2 則"],
    }
    stock["composite"] = {
        "available": True,
        "summary": "整體市場訊號中性",
        "score": 50,
        "coverage": 75,
        "signals": ["技術面：50 分"],
    }
    return stock


def test_openai_failure_fallback_keeps_news_composite_and_single_call(monkeypatch):
    CACHE.clear()
    calls = {"count": 0}

    class FakeCompletions:
        def create(self, **kwargs):
            calls["count"] += 1
            raise TimeoutError("simulated")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(ai_service, "_create_client", lambda: fake_client)

    result = ai_service.ai_stock_analysis(
        _stock_with_news_and_composite("news-composite-timeout")
    )

    assert calls["count"] == 1
    assert "新聞面：新聞情緒中性" in result["explain"]
    assert "綜合分析：整體市場訊號中性" in result["explain"]


def test_invalid_openai_format_returns_complete_news_composite_fallback():
    fallback = build_analysis_sections(
        _stock_with_news_and_composite("news-composite-invalid")
    )
    result = ai_service._parse_analysis("not-json", fallback)

    assert result == fallback
    assert "新聞面：新聞情緒中性" in result["explain"]
    assert "綜合分析：整體市場訊號中性" in result["explain"]


def _valid_model_result() -> dict:
    return {
        "ai_summary": (
            "摘要\n趨勢總結：盤勢整理\n短線建議：留意波動\n"
            "中線建議：追蹤趨勢\n長線建議：觀察基本面\nAI信心度：75%"
        ),
        "explain": (
            "詳細原因\n"
            "技術面：均線整理\n"
            "基本面：尚未整合\n"
            "籌碼面：尚未整合\n"
            "新聞面：情緒中性\n"
            "綜合分析：訊號中性\n"
            "市場情緒：觀望\n"
            "操作建議：控制部位\n"
            "風險提醒：留意波動"
        ),
    }


def test_complete_ordered_openai_contract_is_accepted():
    fallback = build_analysis_sections(_stock_with_news_and_composite("valid-contract"))
    model = _valid_model_result()
    result = ai_service._parse_analysis(
        json.dumps(model, ensure_ascii=False),
        fallback,
    )
    assert result == model


def test_openai_success_uses_complete_contract_and_calls_once(monkeypatch):
    CACHE.clear()
    calls = {"count": 0}
    model = _valid_model_result()

    class FakeCompletions:
        def create(self, **kwargs):
            calls["count"] += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(model, ensure_ascii=False)))]
            )

    monkeypatch.setattr(
        ai_service,
        "_create_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    result = ai_service.ai_stock_analysis(
        _stock_with_news_and_composite("valid-openai")
    )
    assert calls["count"] == 1
    assert result == model


def _fake_openai_response(content, *, usage=None):
    return SimpleNamespace(
        model=ai_service.OPENAI_MODEL,
        usage=usage,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def _fake_openai_client(create):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


def test_only_valid_openai_success_is_cached_and_second_request_is_cache_hit(
    monkeypatch,
):
    CACHE.clear()
    stock = _stock_with_news_and_composite("valid-success-cache")
    model = _valid_model_result()
    calls = {"client": 0, "openai": 0, "store": 0}
    original_set_cache = ai_service.set_cache

    def create(**kwargs):
        calls["openai"] += 1
        return _fake_openai_response(json.dumps(model, ensure_ascii=False))

    def create_client():
        calls["client"] += 1
        return _fake_openai_client(create)

    def store(key, value):
        calls["store"] += 1
        original_set_cache(key, value)

    monkeypatch.setattr(ai_service, "_create_client", create_client)
    monkeypatch.setattr(ai_service, "set_cache", store)

    first = ai_service.ai_stock_analysis(stock)
    second = ai_service.ai_stock_analysis(stock)

    assert first == second == model
    assert calls == {"client": 1, "openai": 1, "store": 1}
    cache_key = f"ai_dashboard_v2_{stock['stock_id']}_{stock['date']}"
    assert CACHE[cache_key]["data"] == model


def test_successful_cache_store_does_not_emit_store_failure_event(
    monkeypatch, caplog
):
    CACHE.clear()
    stock = _stock_with_news_and_composite("cache-store-success-event")
    model = _valid_model_result()
    response = _fake_openai_response(json.dumps(model, ensure_ascii=False))
    monkeypatch.setattr(
        ai_service,
        "_create_client",
        lambda: _fake_openai_client(lambda **kwargs: response),
    )

    with caplog.at_level(logging.INFO, logger=ai_service.logger.name):
        assert ai_service.ai_stock_analysis(stock) == model

    assert "operation=cache_store" not in caplog.text


@pytest.mark.parametrize("store_error", [RuntimeError, OSError])
def test_cache_store_failure_is_best_effort_and_preserves_success_contract(
    monkeypatch, caplog, store_error
):
    CACHE.clear()
    stock = _stock_with_news_and_composite(
        f"cache-store-{store_error.__name__}"
    )
    model = _valid_model_result()
    usage = SimpleNamespace(
        prompt_tokens=21,
        completion_tokens=9,
        total_tokens=30,
    )
    response = _fake_openai_response(
        json.dumps(model, ensure_ascii=False), usage=usage
    )
    calls = {"openai": 0, "store": 0}
    usage_records = []

    def create(**kwargs):
        calls["openai"] += 1
        return response

    def fail_store(key, analysis):
        calls["store"] += 1
        raise store_error(
            "PRIVATE_CACHE_KEY_2330 PRIVATE_PROMPT PRIVATE_RESPONSE PRIVATE_SECRET"
        )

    monkeypatch.setattr(
        ai_service, "_create_client", lambda: _fake_openai_client(create)
    )
    monkeypatch.setattr(ai_service, "set_cache", fail_store)
    monkeypatch.setattr(
        ai_service,
        "record_analysis_usage",
        lambda **kwargs: usage_records.append(kwargs) or True,
    )
    token = observability.set_request_id("cache-store-request")
    try:
        with caplog.at_level(logging.INFO, logger=ai_service.logger.name):
            result = ai_service.ai_stock_analysis(stock)
    finally:
        observability.clear_request_id(token)

    assert result == model
    assert result != build_analysis_sections(stock)
    assert calls == {"openai": 1, "store": 1}
    assert len(usage_records) == 1
    assert usage_records[0]["result"] == "success"
    assert usage_records[0]["openai_call"] is True
    assert usage_records[0]["usage"] is usage
    store_events = [
        record.getMessage()
        for record in caplog.records
        if "operation=cache_store" in record.getMessage()
    ]
    assert len(store_events) == 1
    assert "event=service_fallback" in store_events[0]
    assert "result=fallback" in store_events[0]
    assert "request_id=cache-store-request" in store_events[0]
    assert "service=ai" in store_events[0]
    assert f"error_type={store_error.__name__}" in store_events[0]
    for sensitive in (
        "PRIVATE_CACHE_KEY",
        "2330",
        "PRIVATE_PROMPT",
        "PRIVATE_RESPONSE",
        "PRIVATE_SECRET",
        model["ai_summary"],
        model["explain"],
    ):
        assert sensitive not in store_events[0]


def test_cache_store_failure_does_not_retry_and_next_request_is_a_miss(
    monkeypatch,
):
    CACHE.clear()
    stock = _stock_with_news_and_composite("cache-store-next-miss")
    model = _valid_model_result()
    response = _fake_openai_response(json.dumps(model, ensure_ascii=False))
    calls = {"openai": 0, "store": 0}

    def create(**kwargs):
        calls["openai"] += 1
        return response

    def fail_store(key, analysis):
        calls["store"] += 1
        raise RuntimeError("store")

    monkeypatch.setattr(
        ai_service, "_create_client", lambda: _fake_openai_client(create)
    )
    monkeypatch.setattr(ai_service, "set_cache", fail_store)

    assert ai_service.ai_stock_analysis(stock) == model
    assert ai_service.ai_stock_analysis(stock) == model
    assert calls == {"openai": 2, "store": 2}
    assert CACHE == {}


def test_cache_lookup_and_store_failures_still_return_openai_success(
    monkeypatch, caplog
):
    stock = _stock_with_news_and_composite("lookup-and-store-failure")
    model = _valid_model_result()
    response = _fake_openai_response(json.dumps(model, ensure_ascii=False))
    calls = {"openai": 0, "store": 0}

    def create(**kwargs):
        calls["openai"] += 1
        return response

    def fail_store(key, analysis):
        calls["store"] += 1
        raise RuntimeError("store")

    monkeypatch.setattr(
        ai_service,
        "get_cache",
        lambda key: (_ for _ in ()).throw(RuntimeError("lookup")),
    )
    monkeypatch.setattr(
        ai_service, "_create_client", lambda: _fake_openai_client(create)
    )
    monkeypatch.setattr(ai_service, "set_cache", fail_store)

    with caplog.at_level(logging.INFO, logger=ai_service.logger.name):
        result = ai_service.ai_stock_analysis(stock)

    assert result == model
    assert calls == {"openai": 1, "store": 1}
    assert caplog.text.count("event=ai_cache_lookup_end") == 1
    assert "cache_status=error" in caplog.text
    assert caplog.text.count("operation=cache_store") == 1


def test_cache_store_event_logging_failure_does_not_change_analysis(
    monkeypatch,
):
    stock = _stock_with_news_and_composite("store-log-failure")
    model = _valid_model_result()
    response = _fake_openai_response(json.dumps(model, ensure_ascii=False))
    monkeypatch.setattr(ai_service, "get_cache", lambda key: None)
    monkeypatch.setattr(
        ai_service,
        "_create_client",
        lambda: _fake_openai_client(lambda **kwargs: response),
    )
    monkeypatch.setattr(
        ai_service,
        "set_cache",
        lambda *args: (_ for _ in ()).throw(RuntimeError("store")),
    )
    original_log_event = ai_service.log_event

    def fail_store_event(logger, event, **kwargs):
        if event == "service_fallback":
            raise RuntimeError("log")
        return original_log_event(logger, event, **kwargs)

    monkeypatch.setattr(ai_service, "log_event", fail_store_event)

    assert ai_service.ai_stock_analysis(stock) == model


@pytest.mark.parametrize(
    ("error_name", "expected_usage_result"),
    [
        ("APITimeoutError", "timeout"),
        ("Timeout", "timeout"),
        ("TimeoutError", "timeout"),
        ("APIConnectionError", "fallback"),
        ("APIStatusError", "fallback"),
        ("RateLimitError", "fallback"),
        ("UnexpectedOpenAIError", "fallback"),
    ],
)
def test_openai_request_exceptions_return_fallback_without_caching(
    monkeypatch, error_name, expected_usage_result
):
    CACHE.clear()
    stock = _stock_with_news_and_composite(f"no-cache-{error_name}")
    fallback = build_analysis_sections(stock)
    calls = {"openai": 0, "store": 0}
    usage_records = []
    error_type = type(error_name, (Exception,), {})

    def create(**kwargs):
        calls["openai"] += 1
        raise error_type("simulated")

    monkeypatch.setattr(ai_service, "_create_client", lambda: _fake_openai_client(create))
    monkeypatch.setattr(
        ai_service,
        "set_cache",
        lambda *args: calls.__setitem__("store", calls["store"] + 1),
    )
    monkeypatch.setattr(
        ai_service,
        "record_analysis_usage",
        lambda **kwargs: usage_records.append(kwargs) or True,
    )

    result = ai_service.ai_stock_analysis(stock)

    assert result == fallback
    assert calls == {"openai": 1, "store": 0}
    assert len(usage_records) == 1
    assert usage_records[0]["result"] == expected_usage_result
    assert usage_records[0]["openai_call"] is True


@pytest.mark.parametrize(
    "response",
    [
        _fake_openai_response(""),
        _fake_openai_response("not-json"),
        _fake_openai_response(json.dumps([])),
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=[SimpleNamespace()]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace())]),
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        ),
    ],
    ids=[
        "empty-content",
        "malformed-json",
        "json-not-dict",
        "missing-choices",
        "missing-message",
        "missing-content",
        "none-content",
    ],
)
def test_invalid_openai_response_structure_is_not_cached(monkeypatch, response):
    CACHE.clear()
    stock = _stock_with_news_and_composite("invalid-response-structure")
    fallback = build_analysis_sections(stock)
    stores = []
    openai_calls = []

    def create(**kwargs):
        openai_calls.append(kwargs)
        return response

    monkeypatch.setattr(ai_service, "_create_client", lambda: _fake_openai_client(create))
    monkeypatch.setattr(ai_service, "set_cache", lambda *args: stores.append(args))

    assert ai_service.ai_stock_analysis(stock) == fallback
    assert len(openai_calls) == 1
    assert stores == []


def _invalid_contract_models():
    missing_summary = _valid_model_result()
    missing_summary.pop("ai_summary")

    missing_explain = _valid_model_result()
    missing_explain.pop("explain")

    summary_missing_label = _valid_model_result()
    summary_label = ai_service.SUMMARY_LABELS[0]
    summary_missing_label["ai_summary"] = "\n".join(
        line
        for line in summary_missing_label["ai_summary"].splitlines()
        if not line.startswith(f"{summary_label}：")
    )

    explain_missing_section = _valid_model_result()
    explain_label = ai_service.EXPLAIN_LABELS[0]
    explain_missing_section["explain"] = "\n".join(
        line
        for line in explain_missing_section["explain"].splitlines()
        if not line.startswith(f"{explain_label}：")
    )

    wrong_order = _valid_model_result()
    lines = wrong_order["explain"].splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(f"{ai_service.EXPLAIN_LABELS[0]}："))
    second = next(i for i, line in enumerate(lines) if line.startswith(f"{ai_service.EXPLAIN_LABELS[1]}："))
    lines[first], lines[second] = lines[second], lines[first]
    wrong_order["explain"] = "\n".join(lines)

    forbidden = _valid_model_result()
    forbidden["explain"] += "\nhttps://example.com"

    missing_fundamental_contract = _valid_model_result()
    missing_fundamental_contract["explain"] = missing_fundamental_contract[
        "explain"
    ].replace("基本面：尚未整合", "基本面：資料不足", 1)

    missing_institution_contract = _valid_model_result()
    missing_institution_contract["explain"] = missing_institution_contract[
        "explain"
    ].replace("籌碼面：尚未整合", "籌碼面：資料不足", 1)

    overlap = _valid_model_result()
    shared = "相同分析內容測試文字"
    overlap["ai_summary"] = overlap["ai_summary"].replace(
        f"{ai_service.SUMMARY_LABELS[0]}：",
        f"{ai_service.SUMMARY_LABELS[0]}：{shared}",
        1,
    )
    overlap["explain"] = overlap["explain"].replace(
        f"{ai_service.EXPLAIN_LABELS[0]}：",
        f"{ai_service.EXPLAIN_LABELS[0]}：{shared}",
        1,
    )

    return [
        pytest.param(missing_summary, id="missing-summary"),
        pytest.param(missing_explain, id="missing-explain"),
        pytest.param(summary_missing_label, id="summary-validation"),
        pytest.param(explain_missing_section, id="explain-validation"),
        pytest.param(wrong_order, id="explain-order"),
        pytest.param(forbidden, id="forbidden-text"),
        pytest.param(
            missing_fundamental_contract,
            id="missing-fundamental-contract",
        ),
        pytest.param(
            missing_institution_contract,
            id="missing-institution-contract",
        ),
        pytest.param(overlap, id="summary-explain-overlap"),
    ]


@pytest.mark.parametrize("model", _invalid_contract_models())
def test_validation_failures_are_not_cached(monkeypatch, model):
    CACHE.clear()
    stock = _stock_with_news_and_composite("invalid-contract-no-cache")
    fallback = build_analysis_sections(stock)
    stores = []
    response = _fake_openai_response(json.dumps(model, ensure_ascii=False))
    monkeypatch.setattr(
        ai_service,
        "_create_client",
        lambda: _fake_openai_client(lambda **kwargs: response),
    )
    monkeypatch.setattr(ai_service, "set_cache", lambda *args: stores.append(args))

    assert ai_service.ai_stock_analysis(stock) == fallback
    assert stores == []


@pytest.mark.parametrize("client_factory", [lambda: None, lambda: (_ for _ in ()).throw(RuntimeError("init"))])
def test_missing_key_and_client_initialization_failure_are_not_cached(
    monkeypatch, client_factory
):
    CACHE.clear()
    stock = _stock_with_news_and_composite("client-unavailable-no-cache")
    stores = []
    monkeypatch.setattr(ai_service, "_create_client", client_factory)
    monkeypatch.setattr(ai_service, "set_cache", lambda *args: stores.append(args))

    assert ai_service.ai_stock_analysis(stock) == build_analysis_sections(stock)
    assert stores == []


def test_cache_lookup_exception_still_allows_success_to_be_cached(monkeypatch):
    stock = _stock_with_news_and_composite("lookup-error-success")
    model = _valid_model_result()
    stores = []
    calls = {"openai": 0}

    def create(**kwargs):
        calls["openai"] += 1
        return _fake_openai_response(json.dumps(model, ensure_ascii=False))

    monkeypatch.setattr(
        ai_service,
        "get_cache",
        lambda key: (_ for _ in ()).throw(RuntimeError("lookup")),
    )
    monkeypatch.setattr(ai_service, "_create_client", lambda: _fake_openai_client(create))
    monkeypatch.setattr(ai_service, "set_cache", lambda *args: stores.append(args))

    assert ai_service.ai_stock_analysis(stock) == model
    assert calls["openai"] == 1
    assert len(stores) == 1
    assert stores[0][1] == model


def test_invalid_existing_cache_does_not_call_openai_or_store(monkeypatch):
    stock = _stock_with_news_and_composite("invalid-existing-cache")
    monkeypatch.setattr(ai_service, "get_cache", lambda key: {"invalid": True})
    monkeypatch.setattr(
        ai_service,
        "_create_client",
        lambda: pytest.fail("OpenAI client must not be created"),
    )
    monkeypatch.setattr(
        ai_service,
        "set_cache",
        lambda *args: pytest.fail("invalid cache must not be replaced"),
    )

    assert ai_service.ai_stock_analysis(stock) == build_analysis_sections(stock)


def test_each_missing_explain_section_uses_fallback():
    fallback = build_analysis_sections(_stock_with_news_and_composite("missing-section"))
    for label in ai_service.EXPLAIN_LABELS:
        model = _valid_model_result()
        model["explain"] = "\n".join(
            line for line in model["explain"].splitlines()
            if not line.startswith(f"{label}：")
        )
        result = ai_service._parse_analysis(
            json.dumps(model, ensure_ascii=False), fallback
        )
        assert result == fallback, label


def test_news_after_composite_uses_fallback():
    fallback = build_analysis_sections(_stock_with_news_and_composite("wrong-order"))
    model = _valid_model_result()
    lines = model["explain"].splitlines()
    news_index = next(i for i, line in enumerate(lines) if line.startswith("新聞面："))
    composite_index = next(i for i, line in enumerate(lines) if line.startswith("綜合分析："))
    lines[news_index], lines[composite_index] = lines[composite_index], lines[news_index]
    model["explain"] = "\n".join(lines)
    assert ai_service._parse_analysis(
        json.dumps(model, ensure_ascii=False), fallback
    ) == fallback


def test_non_string_and_blank_explain_use_fallback():
    fallback = build_analysis_sections(_stock_with_news_and_composite("invalid-explain"))
    for explain in (None, 123, "", "   "):
        model = _valid_model_result()
        model["explain"] = explain
        assert ai_service._parse_analysis(
            json.dumps(model, ensure_ascii=False), fallback
        ) == fallback


@pytest.mark.parametrize(
    "forbidden",
    [
        "http://example.com",
        "HTTPS://example.com",
        "www.example.com",
        "明確買進",
        "明確賣出",
        "強烈買進",
        "強烈賣出",
        "保證獲利",
        "必定上漲",
        "必定下跌",
        "無風險",
        "投資建議",
        "建議投資",
    ],
)
def test_url_and_forbidden_advice_use_fallback(forbidden):
    fallback = build_analysis_sections(_stock_with_news_and_composite("forbidden"))
    model = _valid_model_result()
    model["explain"] += f"\n{forbidden}"
    assert ai_service._parse_analysis(
        json.dumps(model, ensure_ascii=False), fallback
    ) == fallback


def test_openai_api_exception_uses_complete_fallback(monkeypatch):
    CACHE.clear()
    calls = {"count": 0}

    class FakeCompletions:
        def create(self, **kwargs):
            calls["count"] += 1
            raise RuntimeError("simulated")

    monkeypatch.setattr(
        ai_service,
        "_create_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    result = ai_service.ai_stock_analysis(
        _stock_with_news_and_composite("api-exception")
    )
    assert calls["count"] == 1
    assert "新聞面：" in result["explain"]
    assert "綜合分析：" in result["explain"]


def test_explain_length_limit_over_and_exactly_three_thousand():
    model = _valid_model_result()
    model["explain"] = _long_valid_explain()
    over = ai_service._limit_analysis_explain(
        model
    )
    exact = ai_service._limit_analysis_explain(
        {
            "ai_summary": _valid_model_result()["ai_summary"],
            "explain": _valid_explain_of_length(3000),
        }
    )
    assert len(over["explain"]) == 3000
    assert over["explain"].endswith("…")
    _assert_eight_sections_in_order(over["explain"])
    assert exact["explain"] == _valid_explain_of_length(3000)
    _assert_eight_sections_in_order(exact["explain"])


def test_fallback_length_limit_and_market_data_immutability(monkeypatch):
    CACHE.clear()
    stock = _stock_with_news_and_composite("long-fallback")
    stock["news"]["signals"] = ["安全新聞訊號" * 600]
    original = deepcopy(stock)
    monkeypatch.setattr(ai_service, "_create_client", lambda: None)
    result = ai_service.ai_stock_analysis(stock)
    assert len(result["explain"]) == 3000
    assert "…" in result["explain"]
    _assert_eight_sections_in_order(result["explain"])
    assert stock == original


def _long_valid_explain() -> str:
    return "詳細原因\n" + "\n".join(
        f"{label}：{label}內容" * 100 for label in ai_service.EXPLAIN_LABELS
    )


def _valid_explain_of_length(length: int) -> str:
    explain = _valid_model_result()["explain"]
    padding = length - len(explain)
    if padding < 0:
        raise ValueError("target length is too short")
    return explain.replace("技術面：", f"技術面：{'x' * padding}", 1)


def _assert_eight_sections_in_order(explain: str):
    positions = [explain.index(f"{label}：") for label in ai_service.EXPLAIN_LABELS]
    assert positions == sorted(positions)


def test_long_valid_openai_explain_preserves_sections_and_calls_once(monkeypatch):
    CACHE.clear()
    calls = {"count": 0}
    model = _valid_model_result()
    model["explain"] = _long_valid_explain()

    class FakeCompletions:
        def create(self, **kwargs):
            calls["count"] += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(model, ensure_ascii=False)))]
            )

    monkeypatch.setattr(
        ai_service,
        "_create_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    stock = _stock_with_news_and_composite("long-valid-openai")
    stock["financial"] = {"available": True}
    stock["institution"] = {"available": True}
    result = ai_service.ai_stock_analysis(stock)
    assert calls["count"] == 1
    assert len(result["explain"]) <= 3000
    assert "…" in result["explain"]
    _assert_eight_sections_in_order(result["explain"])
    cache_key = f"ai_dashboard_v2_{stock['stock_id']}_{stock['date']}"
    assert CACHE[cache_key]["data"] == result


def test_below_limit_explain_is_unchanged():
    model = _valid_model_result()
    assert ai_service._limit_analysis_explain(model) == model


def test_prompt_requires_eight_sections_and_keeps_summary_contract():
    fallback = build_analysis_sections(_stock_with_news_and_composite("prompt"))
    prompt = ai_service._build_prompt(
        _stock_with_news_and_composite("prompt"), fallback
    )
    for label in ai_service.EXPLAIN_LABELS:
        assert label in prompt
    assert prompt.index("新聞面") < prompt.index("綜合分析")
    for label in ("趨勢總結：", "短線建議：", "中線建議：", "長線建議：", "AI信心度："):
        assert label in prompt


def _set_cached(stock: dict, cached: dict):
    ai_service.set_cache(
        f"ai_dashboard_v2_{stock['stock_id']}_{stock['date']}",
        cached,
    )


def _forbid_openai(monkeypatch):
    monkeypatch.setattr(
        ai_service,
        "_create_client",
        lambda: (_ for _ in ()).throw(AssertionError("OpenAI must not be called")),
    )


def test_legacy_six_section_cache_uses_eight_section_fallback_without_openai(monkeypatch):
    CACHE.clear()
    stock = _stock_with_news_and_composite("legacy-cache")
    cached = _valid_model_result()
    cached["explain"] = "\n".join(
        line for line in cached["explain"].splitlines()
        if not line.startswith(("新聞面：", "綜合分析："))
    )
    _set_cached(stock, cached)
    _forbid_openai(monkeypatch)

    result = ai_service.ai_stock_analysis(stock)

    _assert_eight_sections_in_order(result["explain"])
    assert "新聞面：新聞情緒中性" in result["explain"]
    assert "綜合分析：整體市場訊號中性" in result["explain"]


@pytest.mark.parametrize("missing_label", ai_service.EXPLAIN_LABELS)
def test_cache_missing_each_explain_section_uses_fallback_without_openai(
    monkeypatch, missing_label
):
    CACHE.clear()
    stock = _stock_with_news_and_composite(f"cache-missing-{missing_label}")
    cached = _valid_model_result()
    cached["explain"] = "\n".join(
        line for line in cached["explain"].splitlines()
        if not line.startswith(f"{missing_label}：")
    )
    _set_cached(stock, cached)
    _forbid_openai(monkeypatch)
    result = ai_service.ai_stock_analysis(stock)
    _assert_eight_sections_in_order(result["explain"])
    assert result != cached


def test_cache_wrong_section_order_uses_fallback_without_openai(monkeypatch):
    CACHE.clear()
    stock = _stock_with_news_and_composite("cache-wrong-order")
    cached = _valid_model_result()
    lines = cached["explain"].splitlines()
    news = next(i for i, line in enumerate(lines) if line.startswith("新聞面："))
    composite = next(i for i, line in enumerate(lines) if line.startswith("綜合分析："))
    lines[news], lines[composite] = lines[composite], lines[news]
    cached["explain"] = "\n".join(lines)
    _set_cached(stock, cached)
    _forbid_openai(monkeypatch)
    result = ai_service.ai_stock_analysis(stock)
    _assert_eight_sections_in_order(result["explain"])
    assert result != cached


@pytest.mark.parametrize("forbidden", ai_service.FORBIDDEN_EXPLAIN_TERMS)
@pytest.mark.parametrize("field", ["ai_summary", "explain"])
def test_cache_forbidden_text_uses_fallback_without_openai(
    monkeypatch, forbidden, field
):
    CACHE.clear()
    stock = _stock_with_news_and_composite(f"cache-forbidden-{field}-{forbidden}")
    cached = _valid_model_result()
    cached[field] += f"\n{forbidden}"
    _set_cached(stock, cached)
    _forbid_openai(monkeypatch)
    result = ai_service.ai_stock_analysis(stock)
    assert forbidden not in result[field]
    _assert_eight_sections_in_order(result["explain"])


@pytest.mark.parametrize("missing_label", ai_service.SUMMARY_LABELS)
def test_cache_missing_each_summary_section_uses_fallback_without_openai(
    monkeypatch, missing_label
):
    CACHE.clear()
    stock = _stock_with_news_and_composite(f"cache-summary-{missing_label}")
    cached = _valid_model_result()
    cached["ai_summary"] = "\n".join(
        line for line in cached["ai_summary"].splitlines()
        if not line.startswith(f"{missing_label}：")
    )
    _set_cached(stock, cached)
    _forbid_openai(monkeypatch)
    result = ai_service.ai_stock_analysis(stock)
    assert result != cached
    for label in ai_service.SUMMARY_LABELS:
        assert f"{label}：" in result["ai_summary"]


def test_valid_cache_is_returned_unchanged_without_openai_or_input_mutation(monkeypatch):
    CACHE.clear()
    stock = _stock_with_news_and_composite("valid-cache")
    original_stock = deepcopy(stock)
    cached = _valid_model_result()
    original_cached = deepcopy(cached)
    _set_cached(stock, cached)
    _forbid_openai(monkeypatch)
    result = ai_service.ai_stock_analysis(stock)
    assert result == cached
    assert cached == original_cached
    assert stock == original_stock


def test_long_valid_cache_preserves_sections_without_openai(monkeypatch):
    CACHE.clear()
    stock = _stock_with_news_and_composite("long-valid-cache")
    cached = _valid_model_result()
    cached["explain"] = _valid_explain_of_length(4000)
    original_cached = deepcopy(cached)
    _set_cached(stock, cached)
    _forbid_openai(monkeypatch)
    result = ai_service.ai_stock_analysis(stock)
    assert len(result["explain"]) <= 3000
    assert "…" in result["explain"]
    _assert_eight_sections_in_order(result["explain"])
    assert cached == original_cached
