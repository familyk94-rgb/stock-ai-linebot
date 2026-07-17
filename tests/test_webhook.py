import json
from types import SimpleNamespace

import pytest
from linebot.v3.messaging import TextMessage

import app.config as app_config
from core.explain_engine import build_analysis_sections
from services import ai_service

_original_secret = app_config.LINE_CHANNEL_SECRET
_original_token = app_config.LINE_CHANNEL_ACCESS_TOKEN
app_config.LINE_CHANNEL_SECRET = "test-channel-secret"
app_config.LINE_CHANNEL_ACCESS_TOKEN = "test-access-token"

from app import webhook

app_config.LINE_CHANNEL_SECRET = _original_secret
app_config.LINE_CHANNEL_ACCESS_TOKEN = _original_token


def _event(text="2330"):
    return SimpleNamespace(
        message=SimpleNamespace(text=text),
        reply_token="reply-token",
    )


def _market_data(**overrides):
    data = {
        "stock_id": "2330",
        "stock_name": "台積電",
        "price": 1000,
        "change": 10,
        "change_percent": 1,
        "volume": 1000,
        "trend": "市場趨勢",
        "ma_signal": "市場 MA",
        "macd_signal": "市場 MACD",
        "rsi_signal": "市場 RSI",
        "financial": {"available": True},
        "institution": {"available": True},
        "news": {"available": True},
        "composite": {
            "available": True,
            "score": 72,
            "summary": "整體市場訊號中性偏多 🚀",
            "coverage": 100,
            "contributions": {"technical": {"score": 80}},
            "signals": ["不應傳入 Flex"],
        },
        "data_quality": {"status": "部分資料", "is_stale": True},
        "core": {
            "score": 80,
            "confidence": 85,
            "decision": "偏多",
            "risk_level": "中等風險",
            "shopkeeper_message": "店長訊息",
            "trend": "核心趨勢",
            "ma_signal": "核心 MA",
            "macd_signal": "核心 MACD",
            "rsi_signal": "核心 RSI",
        },
    }
    data.update(overrides)
    return data


def _setup_normal(monkeypatch, ai_result=None):
    calls = {"market": 0, "ai": 0, "builder": 0, "reply": []}
    market = _market_data()

    def get_market(stock_code):
        calls["market"] += 1
        return market

    def analyze(data):
        calls["ai"] += 1
        return ai_result if ai_result is not None else {
            "ai_summary": "摘要",
            "explain": "原因",
        }

    def build(data):
        calls["builder"] += 1
        calls["flex_data"] = data
        return "flex-message"

    def reply(token, message):
        calls["reply"].append((token, message))

    monkeypatch.setattr(webhook, "get_market_info", get_market)
    monkeypatch.setattr(webhook, "ai_stock_analysis", analyze)
    monkeypatch.setattr(webhook, "build_stock_dashboard_flex", build)
    monkeypatch.setattr(webhook, "reply_message", reply)
    return calls


def test_normal_flow_maps_flex_data_and_replies_once(monkeypatch):
    calls = _setup_normal(monkeypatch)
    webhook.handle_text_message(_event())
    assert calls["market"] == calls["ai"] == calls["builder"] == 1
    assert calls["reply"] == [("reply-token", "flex-message")]
    expected_keys = {
        "stock_code", "stock_name", "score", "confidence", "decision", "risk_level",
        "shopkeeper_message", "price", "change", "change_percent", "volume",
        "trend", "ma_signal", "macd_signal", "rsi_signal", "ai_summary", "explain",
        "composite_available", "composite_score", "composite_summary", "composite_coverage",
        "data_quality_status", "data_quality_is_stale",
    }
    assert set(calls["flex_data"]) == expected_keys
    assert not {"financial", "institution", "news", "composite"} & set(calls["flex_data"])
    assert not {"contributions", "signals"} & set(calls["flex_data"])
    assert calls["flex_data"]["trend"] == "核心趨勢"
    assert calls["flex_data"]["confidence"] == 85
    assert calls["flex_data"]["ai_summary"] == "摘要"
    assert calls["flex_data"]["explain"] == "原因"
    assert calls["flex_data"]["composite_available"] is True
    assert calls["flex_data"]["composite_score"] == 72
    assert calls["flex_data"]["composite_summary"] == "整體市場訊號中性偏多 🚀"
    assert calls["flex_data"]["composite_coverage"] == 100
    assert calls["flex_data"]["data_quality_status"] == "部分資料"
    assert calls["flex_data"]["data_quality_is_stale"] is True


def test_ai_cache_store_failure_still_builds_and_replies_once(monkeypatch):
    market = _market_data(date="2026-07-17")
    model = build_analysis_sections(market)
    calls = {"openai": 0, "store": 0, "builder": 0, "reply": []}

    def create(**kwargs):
        calls["openai"] += 1
        return SimpleNamespace(
            model=ai_service.OPENAI_MODEL,
            usage=SimpleNamespace(
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
            ),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(model, ensure_ascii=False)
                    )
                )
            ],
        )

    def fail_store(key, analysis):
        calls["store"] += 1
        raise RuntimeError("cache store failed")

    def build(data):
        calls["builder"] += 1
        calls["flex_data"] = data
        return "flex-message"

    monkeypatch.setattr(webhook, "get_market_info", lambda stock_code: market)
    monkeypatch.setattr(webhook, "ai_stock_analysis", ai_service.ai_stock_analysis)
    monkeypatch.setattr(webhook, "build_stock_dashboard_flex", build)
    monkeypatch.setattr(
        webhook,
        "reply_message",
        lambda token, message: calls["reply"].append((token, message)),
    )
    monkeypatch.setattr(ai_service, "get_cache", lambda key: None)
    monkeypatch.setattr(
        ai_service,
        "_create_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        ),
    )
    monkeypatch.setattr(ai_service, "set_cache", fail_store)
    monkeypatch.setattr(ai_service, "record_analysis_usage", lambda **kwargs: True)

    webhook.handle_text_message(_event())

    assert calls["openai"] == 1
    assert calls["store"] == 1
    assert calls["builder"] == 1
    assert calls["reply"] == [("reply-token", "flex-message")]
    assert calls["flex_data"]["ai_summary"] == model["ai_summary"]
    assert calls["flex_data"]["explain"] == model["explain"]


@pytest.mark.parametrize("composite", [None, "invalid", [], 1])
def test_invalid_or_missing_composite_maps_unavailable(monkeypatch, composite):
    calls = _setup_normal(monkeypatch)
    market = _market_data(composite=composite)
    monkeypatch.setattr(webhook, "get_market_info", lambda code: market)
    webhook.handle_text_message(_event())
    assert calls["flex_data"]["composite_available"] is False
    assert calls["flex_data"]["composite_score"] is None
    assert calls["flex_data"]["composite_summary"] == ""
    assert calls["flex_data"]["composite_coverage"] is None


def test_missing_composite_maps_unavailable_without_mutating_market_data(monkeypatch):
    calls = _setup_normal(monkeypatch)
    market = _market_data()
    del market["composite"]
    original = dict(market)
    monkeypatch.setattr(webhook, "get_market_info", lambda code: market)
    webhook.handle_text_message(_event())
    assert calls["flex_data"]["composite_available"] is False
    assert market == original


@pytest.mark.parametrize(
    "composite",
    [
        {"available": False, "score": 50, "summary": "資料不足", "coverage": 0},
        {"available": True, "score": 0, "summary": "中性", "coverage": 0},
        {"available": True, "score": 100, "summary": "偏多 🚀", "coverage": 100},
    ],
)
def test_composite_mapping_preserves_explicit_values(monkeypatch, composite):
    calls = _setup_normal(monkeypatch)
    market = _market_data(composite=composite)
    monkeypatch.setattr(webhook, "get_market_info", lambda code: market)
    webhook.handle_text_message(_event())
    assert calls["flex_data"]["composite_available"] is composite["available"]
    assert calls["flex_data"]["composite_score"] == composite["score"]
    assert calls["flex_data"]["composite_summary"] == composite["summary"]
    assert calls["flex_data"]["composite_coverage"] == composite["coverage"]
    assert calls["market"] == 0
    assert calls["ai"] == calls["builder"] == 1
    assert len(calls["reply"]) == 1


def test_ai_dict_missing_text_fields_uses_existing_fallbacks(monkeypatch):
    calls = _setup_normal(monkeypatch, ai_result={})
    webhook.handle_text_message(_event())
    assert calls["flex_data"]["ai_summary"] == "目前資料不足，建議等待更多訊號。"
    assert calls["flex_data"]["explain"] == "尚未產生完整解釋。"


def test_confidence_is_not_parsed_from_ai_summary(monkeypatch):
    calls = _setup_normal(
        monkeypatch,
        ai_result={"ai_summary": "AI 信心度：99%", "explain": "原因"},
    )
    market = _market_data()
    market["core"] = dict(market["core"])
    market["core"].pop("confidence")
    monkeypatch.setattr(webhook, "get_market_info", lambda code: market)

    webhook.handle_text_message(_event())

    assert calls["flex_data"]["confidence"] is None


def test_string_ai_result_becomes_summary_with_reason_fallback(monkeypatch):
    calls = _setup_normal(monkeypatch, ai_result="字串摘要")
    webhook.handle_text_message(_event())
    assert calls["flex_data"]["ai_summary"] == "字串摘要"
    assert calls["flex_data"]["explain"] == "詳細原因\n目前無法取得完整分析原因。"


@pytest.mark.parametrize("market", [None, _market_data(price=None)])
def test_missing_market_data_does_not_build_flex(monkeypatch, market):
    calls = {"market": 0, "ai": 0, "builder": 0, "replies": []}

    def get_market(stock_code):
        calls["market"] += 1
        return market

    monkeypatch.setattr(webhook, "get_market_info", get_market)
    monkeypatch.setattr(webhook, "ai_stock_analysis", lambda data: calls.__setitem__("ai", calls["ai"] + 1))
    monkeypatch.setattr(webhook, "build_stock_dashboard_flex", lambda data: calls.__setitem__("builder", calls["builder"] + 1))
    monkeypatch.setattr(webhook, "reply_message", lambda token, message: calls["replies"].append(message))
    webhook.handle_text_message(_event())
    assert calls["market"] == 1
    assert calls["ai"] == 0
    assert calls["builder"] == 0
    assert len(calls["replies"]) == 1
    assert isinstance(calls["replies"][0], TextMessage)


def test_market_exception_does_not_build_and_uses_text_fallback(monkeypatch):
    calls = {"market": 0, "ai": 0, "builder": 0, "replies": []}

    def get_market(code):
        calls["market"] += 1
        raise RuntimeError("simulated")

    monkeypatch.setattr(webhook, "get_market_info", get_market)
    monkeypatch.setattr(webhook, "ai_stock_analysis", lambda data: calls.__setitem__("ai", calls["ai"] + 1))
    monkeypatch.setattr(webhook, "build_stock_dashboard_flex", lambda data: calls.__setitem__("builder", calls["builder"] + 1))
    monkeypatch.setattr(webhook, "reply_message", lambda token, message: calls["replies"].append(message))
    webhook.handle_text_message(_event())
    assert calls["market"] == 1
    assert calls["ai"] == 0
    assert calls["builder"] == 0
    assert len(calls["replies"]) == 1


def test_ai_exception_does_not_build_and_uses_text_fallback(monkeypatch):
    calls = _setup_normal(monkeypatch)

    def analyze(data):
        calls["ai"] += 1
        raise RuntimeError("simulated")

    monkeypatch.setattr(webhook, "ai_stock_analysis", analyze)
    webhook.handle_text_message(_event())
    assert calls["market"] == 1
    assert calls["ai"] == 1
    assert calls["builder"] == 0
    assert len(calls["reply"]) == 1
    assert isinstance(calls["reply"][0][1], TextMessage)


def test_builder_exception_uses_text_fallback_without_rebuilding(monkeypatch):
    calls = _setup_normal(monkeypatch)

    def build(data):
        calls["builder"] += 1
        raise RuntimeError("simulated")

    monkeypatch.setattr(webhook, "build_stock_dashboard_flex", build)
    webhook.handle_text_message(_event())
    assert calls["market"] == 1
    assert calls["ai"] == 1
    assert calls["builder"] == 1
    assert len(calls["reply"]) == 1
    assert isinstance(calls["reply"][0][1], TextMessage)


def test_flex_reply_exception_attempts_one_text_fallback(monkeypatch):
    calls = _setup_normal(monkeypatch)

    def reply(token, message):
        calls["reply"].append(message)
        if message == "flex-message":
            raise RuntimeError("flex failed")

    monkeypatch.setattr(webhook, "reply_message", reply)
    webhook.handle_text_message(_event())
    assert calls["market"] == 1
    assert calls["ai"] == 1
    assert calls["builder"] == 1
    assert calls["reply"][0] == "flex-message"
    assert isinstance(calls["reply"][1], TextMessage)
    assert len(calls["reply"]) == 2


def test_fallback_reply_failure_is_contained(monkeypatch):
    calls = _setup_normal(monkeypatch)

    def reply(token, message):
        calls["reply"].append(message)
        if message == "flex-message":
            raise RuntimeError("flex failed")
        if isinstance(message, TextMessage):
            raise RuntimeError("fallback failed")

    monkeypatch.setattr(webhook, "reply_message", reply)
    webhook.handle_text_message(_event())
    assert calls["market"] == 1
    assert calls["ai"] == 1
    assert calls["builder"] == 1
    assert len(calls["reply"]) == 2
    assert calls["reply"][0] == "flex-message"
    assert isinstance(calls["reply"][1], TextMessage)


def test_non_numeric_input_skips_services_and_replies_once(monkeypatch):
    calls = {"market": 0, "reply": []}
    monkeypatch.setattr(webhook, "get_market_info", lambda code: calls.__setitem__("market", calls["market"] + 1))
    monkeypatch.setattr(webhook, "reply_message", lambda token, message: calls["reply"].append(message))
    webhook.handle_text_message(_event("abc"))
    assert calls["market"] == 0
    assert len(calls["reply"]) == 1
    assert isinstance(calls["reply"][0], TextMessage)
