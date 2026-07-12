from copy import deepcopy

import pytest

from core.market.composite_analysis_engine import (
    CompositeAnalysisEngine,
    composite_fallback,
)
from services import market_service


def module(score, available=True):
    return {"available": available, "score": score}


def analyze(technical=None, financial=None, institution=None, news=None):
    return CompositeAnalysisEngine().analyze(
        technical,
        financial,
        institution,
        news,
    )


def test_all_modules_use_fixed_weights():
    result = analyze(module(80), module(60), module(40), module(20))
    assert result["score"] == 55
    assert result["coverage"] == 100
    assert result["available_modules"] == 4
    assert result["contributions"]["technical"] == {
        "available": True,
        "score": 80,
        "base_weight": 35,
        "normalized_weight": 35.0,
        "contribution": 28.0,
    }


def test_one_module_normalizes_to_one_hundred_percent():
    result = analyze(financial=module(72))
    assert result["score"] == 72
    assert result["coverage"] == 25
    assert result["contributions"]["financial"]["normalized_weight"] == 100.0
    assert result["contributions"]["financial"]["contribution"] == 72.0


def test_two_modules_are_renormalized():
    result = analyze(technical=module(80), financial=module(40))
    assert result["score"] == 63
    assert result["coverage"] == 50
    assert result["contributions"]["technical"]["normalized_weight"] == 58.33
    assert result["contributions"]["financial"]["normalized_weight"] == 41.67


def test_three_modules_have_seventy_five_percent_coverage():
    result = analyze(module(90), module(70), module(50))
    assert result["coverage"] == 75
    assert result["available_modules"] == 3


def test_no_available_modules_returns_complete_fallback():
    assert analyze(None, {}, module(20, False), {"score": 50}) == composite_fallback()


@pytest.mark.parametrize(
    "invalid_module",
    [
        {},
        {"score": 50},
        module(50, False),
        {"available": True},
        module(None),
        module("50"),
        module(True),
        module(float("nan")),
        module(float("inf")),
    ],
)
def test_invalid_module_values_are_unavailable(invalid_module):
    result = analyze(technical=invalid_module)
    assert result == composite_fallback()


def test_scores_are_clamped_before_calculation():
    result = analyze(technical=module(-10), financial=module(120))
    assert result["contributions"]["technical"]["score"] == 0
    assert result["contributions"]["financial"]["score"] == 100
    assert result["score"] == 42


def test_inputs_are_not_modified():
    inputs = [
        {"available": True, "score": 80, "signals": ["x"]},
        {"available": True, "score": 60},
        {"available": False, "score": None},
        {"available": True, "score": 40},
    ]
    original = deepcopy(inputs)
    CompositeAnalysisEngine().analyze(*inputs)
    assert inputs == original


def test_signals_have_fixed_order_and_safe_content():
    result = analyze(
        module(80.6),
        {"available": False, "url": "https://example.com", "advice": "買進"},
        module(40),
        module(20),
    )
    assert result["signals"] == [
        "技術面：81 分",
        "基本面：資料不足",
        "籌碼面：40 分",
        "新聞面：20 分",
        "綜合分析資料覆蓋率：75%",
    ]
    text = " ".join(result["signals"])
    assert "http" not in text
    assert "買進" not in text
    assert "賣出" not in text


@pytest.mark.parametrize(
    ("score", "summary"),
    [
        (80, "整體市場訊號偏多"),
        (79, "整體市場訊號中性偏多"),
        (60, "整體市場訊號中性偏多"),
        (59, "整體市場訊號中性"),
        (40, "整體市場訊號中性"),
        (39, "整體市場訊號中性偏空"),
        (20, "整體市場訊號中性偏空"),
        (19, "整體市場訊號偏空"),
        (0, "整體市場訊號偏空"),
    ],
)
def test_summary_boundaries(score, summary):
    assert analyze(technical=module(score))["summary"] == summary


def test_weights_and_contributions_are_rounded_to_two_decimals():
    result = analyze(module(73.333), module(62.222), module(51.111))
    for contribution in result["contributions"].values():
        if contribution["available"]:
            assert contribution["normalized_weight"] == round(
                contribution["normalized_weight"], 2
            )
            assert contribution["contribution"] == round(
                contribution["contribution"], 2
            )


def _mock_market_dependencies(monkeypatch):
    calls = {"financial": 0, "institution": 0, "news": 0}
    monkeypatch.setattr(
        market_service.AssetService,
        "get_asset",
        lambda self, stock_id: {"type": "unknown", "source": None, "confidence": "low"},
    )
    monkeypatch.setattr(market_service, "get_stock_name", lambda stock_id: "台積電")
    monkeypatch.setattr(
        market_service,
        "get_stock_info",
        lambda stock_id: {
            "date": "2026-07-11",
            "close": 1000,
            "open": 990,
            "max": 1010,
            "min": 985,
            "change": 10,
            "change_percent": 1,
            "volume": 1000,
        },
    )
    monkeypatch.setattr(
        market_service,
        "get_technical_indicators",
        lambda stock_id: {"trend": "多頭"},
    )
    monkeypatch.setattr(
        market_service.GanzaiAI,
        "run",
        lambda self: {"score": 80, "confidence": 70, "data_completeness": 60},
    )

    def financial(self, stock_id):
        calls["financial"] += 1
        return {"available": True, "score": 60, "marker": "financial"}

    def institution(self, stock_id):
        calls["institution"] += 1
        return {"available": True, "score": 40, "marker": "institution"}

    def news(self, stock_id):
        calls["news"] += 1
        return {"available": True, "score": 20, "marker": "news"}

    monkeypatch.setattr(market_service.FundamentalEngine, "analyze", financial)
    monkeypatch.setattr(market_service.InstitutionEngine, "analyze", institution)
    monkeypatch.setattr(market_service.NewsEngine, "analyze", news)
    return calls


def test_market_service_adds_composite_without_overwriting_modules(monkeypatch):
    calls = _mock_market_dependencies(monkeypatch)
    result = market_service.get_market_info("2330")

    assert result["composite"]["available"] is True
    assert result["composite"]["score"] == 55
    assert result["core"] == {
        "score": 80,
        "confidence": 70,
        "data_completeness": 60,
    }
    assert result["technical"] == {"trend": "多頭"}
    assert result["financial"]["marker"] == "financial"
    assert result["institution"]["marker"] == "institution"
    assert result["news"]["marker"] == "news"
    assert calls == {"financial": 1, "institution": 1, "news": 1}


def test_market_service_composite_exception_uses_fallback(monkeypatch):
    _mock_market_dependencies(monkeypatch)
    monkeypatch.setattr(
        market_service.CompositeAnalysisEngine,
        "analyze",
        lambda self, *args: (_ for _ in ()).throw(RuntimeError("simulated")),
    )
    result = market_service.get_market_info("2330")
    assert result["composite"] == composite_fallback()


def test_market_service_updates_shopkeeper_once_after_composite(monkeypatch):
    _mock_market_dependencies(monkeypatch)
    monkeypatch.setattr(
        market_service.GanzaiAI,
        "run",
        lambda self: {
            "score": 80,
            "decision": "偏多",
            "shopkeeper_message": "原訊息",
        },
    )
    calls = []

    def update(current_message, decision, composite):
        calls.append((current_message, decision, deepcopy(composite)))
        return "更新後訊息"

    monkeypatch.setattr(market_service, "get_composite_aware_advice", update)
    result = market_service.get_market_info("2330")

    assert len(calls) == 1
    assert calls[0][0] == "原訊息"
    assert calls[0][1] == "偏多"
    assert calls[0][2] == result["composite"]
    assert result["core"]["shopkeeper_message"] == "更新後訊息"
    assert result["core"]["score"] == 80
    assert result["core"]["decision"] == "偏多"
    assert result["composite"]["score"] == 55


def test_market_service_calculates_data_quality_once_after_modules(monkeypatch):
    _mock_market_dependencies(monkeypatch)
    calls = []

    def analyze(self, market_data):
        calls.append(deepcopy(market_data))
        return {"status": "正常", "marker": "quality"}

    monkeypatch.setattr(market_service.DataQualityEngine, "analyze", analyze)
    result = market_service.get_market_info("2330")

    assert len(calls) == 1
    assert all(key in calls[0] for key in ("financial", "institution", "news", "composite"))
    assert result["data_quality"] == {"status": "正常", "marker": "quality"}
    assert result["core"]["score"] == 80
    assert result["core"]["confidence"] == 70


def test_market_service_no_price_calculates_data_quality_once(monkeypatch):
    _mock_market_dependencies(monkeypatch)
    monkeypatch.setattr(market_service, "get_stock_info", lambda stock_id: None)
    calls = []

    def analyze(self, market_data):
        calls.append(deepcopy(market_data))
        return {"status": "資料不足", "marker": "no-price"}

    monkeypatch.setattr(market_service.DataQualityEngine, "analyze", analyze)
    result = market_service.get_market_info("2330")

    assert len(calls) == 1
    assert calls[0]["price"] is None
    assert all(key in calls[0] for key in ("financial", "institution", "news", "composite"))
    assert result["data_quality"] == {"status": "資料不足", "marker": "no-price"}
    assert result["price"] is None


@pytest.mark.parametrize("no_price", [False, True])
def test_market_service_data_quality_exception_uses_fixed_fallback(monkeypatch, no_price):
    _mock_market_dependencies(monkeypatch)
    if no_price:
        monkeypatch.setattr(market_service, "get_stock_info", lambda stock_id: None)

    def fail(self, market_data):
        raise RuntimeError("simulated")

    monkeypatch.setattr(market_service.DataQualityEngine, "analyze", fail)
    result = market_service.get_market_info("2330")

    assert result["data_quality"] == {
        "status": "資料不足",
        "as_of_date": None,
        "fetched_at": None,
        "is_stale": False,
        "available_sources": [],
        "missing_sources": ["price", "technical", "fundamental", "institution", "news"],
        "source_dates": {
            "price": None,
            "technical": None,
            "fundamental": None,
            "institution": None,
            "news": None,
        },
        "data_completeness": 0,
    }
    assert result["financial"]["marker"] == "financial"
    assert result["institution"]["marker"] == "institution"
    assert result["news"]["marker"] == "news"
    assert "composite" in result
    if not no_price:
        assert result["price"] == 1000
        assert result["technical"] == {"trend": "多頭"}
