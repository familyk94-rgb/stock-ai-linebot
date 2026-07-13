from types import SimpleNamespace

import pytest

from services import ai_service


STOCK = {"stock_id": "2330", "date": "2026-07-13"}
FALLBACK = {"ai_summary": "summary", "explain": "explain"}


def _base(monkeypatch, cached=None):
    records = []
    monkeypatch.setattr(ai_service, "get_cache", lambda key: cached)
    monkeypatch.setattr(ai_service, "set_cache", lambda *args: None)
    monkeypatch.setattr(ai_service, "build_analysis_sections", lambda value: FALLBACK)
    monkeypatch.setattr(ai_service, "_limit_analysis_explain", lambda value, fallback=None: value)
    monkeypatch.setattr(ai_service, "record_analysis_usage", lambda **kwargs: records.append(kwargs) or True)
    return records


def test_cache_hit_records_zero_cost_call_contract(monkeypatch):
    records = _base(monkeypatch, FALLBACK)
    monkeypatch.setattr(ai_service, "_is_valid_cached_analysis", lambda value: True)
    monkeypatch.setattr(ai_service, "_create_client", lambda: pytest.fail("OpenAI called"))
    assert ai_service.ai_stock_analysis(STOCK) == FALLBACK
    assert records == [{"model": ai_service.OPENAI_MODEL, "result": "success", "cache_hit": True, "openai_call": False}]


def test_invalid_cache_records_once_and_never_calls_openai(monkeypatch):
    records = _base(monkeypatch, {"invalid": True})
    monkeypatch.setattr(ai_service, "_is_valid_cached_analysis", lambda value: False)
    monkeypatch.setattr(ai_service, "_create_client", lambda: pytest.fail("OpenAI called"))
    assert ai_service.ai_stock_analysis(STOCK) == FALLBACK
    assert records == [{"model": ai_service.OPENAI_MODEL, "result": "fallback", "cache_hit": False, "openai_call": False}]


def test_openai_success_and_invalid_response_record_official_usage(monkeypatch):
    records = _base(monkeypatch)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14)
    response = SimpleNamespace(model="response-model", usage=usage, choices=[SimpleNamespace(message=SimpleNamespace(content="json"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
    monkeypatch.setattr(ai_service, "_create_client", lambda: client)
    monkeypatch.setattr(ai_service, "_parse_analysis", lambda *args, **kwargs: {"ai_summary": "valid", "explain": "valid"})
    ai_service.ai_stock_analysis(STOCK)
    assert records[0]["usage"] is usage
    assert records[0]["openai_call"] is True
    assert records[0]["result"] == "success"

    records.clear()
    monkeypatch.setattr(ai_service, "_parse_analysis", lambda *args, **kwargs: FALLBACK)
    ai_service.ai_stock_analysis(STOCK)
    assert records[0]["result"] == "fallback"
    assert records[0]["usage"] is usage


@pytest.mark.parametrize(
    ("client_factory", "expected_result", "openai_call"),
    [
        (lambda: None, "fallback", False),
        (lambda: (_ for _ in ()).throw(RuntimeError()), "fallback", False),
    ],
)
def test_missing_key_and_client_failure_record_once(monkeypatch, client_factory, expected_result, openai_call):
    records = _base(monkeypatch)
    monkeypatch.setattr(ai_service, "_create_client", client_factory)
    assert ai_service.ai_stock_analysis(STOCK) == FALLBACK
    assert len(records) == 1
    assert records[0]["result"] == expected_result
    assert records[0]["openai_call"] is openai_call


def test_timeout_records_once_with_zero_known_usage(monkeypatch):
    records = _base(monkeypatch)
    completions = SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(ai_service, "_create_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    assert ai_service.ai_stock_analysis(STOCK) == FALLBACK
    assert len(records) == 1
    assert records[0] == {
        "model": ai_service.OPENAI_MODEL, "result": "timeout",
        "cache_hit": False, "openai_call": True, "usage": None,
    }


def test_usage_tracking_failure_never_changes_ai_result(monkeypatch):
    _base(monkeypatch, FALLBACK)
    monkeypatch.setattr(ai_service, "_is_valid_cached_analysis", lambda value: True)
    monkeypatch.setattr(ai_service, "record_analysis_usage", lambda **kwargs: (_ for _ in ()).throw(RuntimeError()))
    assert ai_service.ai_stock_analysis(STOCK) == FALLBACK
