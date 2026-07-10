from core.market.fundamental_engine import FundamentalEngine
from services.fundamental_service import FundamentalService
from services import market_service


EXPECTED_KEYS = {
    "eps",
    "pe",
    "pb",
    "roe",
    "revenue_growth",
    "dividend_yield",
    "score",
    "summary",
    "signals",
    "available",
}

EXPECTED_FALLBACK = {
    "eps": None,
    "pe": None,
    "pb": None,
    "roe": None,
    "revenue_growth": None,
    "dividend_yield": None,
    "score": 0,
    "summary": "尚未整合",
    "signals": [],
    "available": False,
}


def test_fundamental_engine_returns_fixed_keys():
    result = FundamentalEngine().analyze({})

    assert set(result) == EXPECTED_KEYS


def test_fundamental_engine_returns_unavailable_defaults_without_data():
    result = FundamentalEngine().analyze({})

    assert result["summary"] == "尚未整合"
    assert result["available"] is False
    assert result["score"] == 0
    assert result["signals"] == []


def test_fundamental_engine_returns_defaults_for_none():
    result = FundamentalEngine().analyze(None)

    assert set(result) == EXPECTED_KEYS
    assert result["score"] == 0
    assert result["summary"] == "尚未整合"
    assert result["signals"] == []
    assert result["available"] is False


def test_market_service_uses_financial_fallback_when_engine_fails(monkeypatch):
    calls = {"count": 0}

    def raise_fundamental_error(self, stock_data):
        calls["count"] += 1
        raise RuntimeError("simulated failure")

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
            "change_percent": 1.01,
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
        lambda self: {"score": 80},
    )
    monkeypatch.setattr(
        market_service.FundamentalEngine,
        "analyze",
        raise_fundamental_error,
    )

    result = market_service.get_market_info("2330")

    assert calls["count"] == 1
    assert result["price"] == 1000
    assert result["technical"] == {"trend": "多頭"}
    assert result["financial"] == {
        "eps": None,
        "pe": None,
        "pb": None,
        "roe": None,
        "revenue_growth": None,
        "dividend_yield": None,
        "score": 0,
        "summary": "尚未整合",
        "signals": [],
        "available": False,
    }


def test_engine_falls_back_when_service_raises(monkeypatch):
    calls = {"count": 0}

    def raise_error(self, stock_id):
        calls["count"] += 1
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(FundamentalService, "get_fundamental", raise_error)

    result = FundamentalEngine().analyze("2330")

    assert calls["count"] == 1
    assert result == EXPECTED_FALLBACK


def test_engine_falls_back_when_service_returns_none(monkeypatch):
    monkeypatch.setattr(
        FundamentalService,
        "get_fundamental",
        lambda self, stock_id: None,
    )

    assert FundamentalEngine().analyze("2330") == EXPECTED_FALLBACK


def test_engine_falls_back_when_service_returns_non_dict(monkeypatch):
    monkeypatch.setattr(
        FundamentalService,
        "get_fundamental",
        lambda self, stock_id: "invalid",
    )

    assert FundamentalEngine().analyze("2330") == EXPECTED_FALLBACK


def test_engine_falls_back_when_service_omits_required_key(monkeypatch):
    monkeypatch.setattr(
        FundamentalService,
        "get_fundamental",
        lambda self, stock_id: {"available": False},
    )

    assert FundamentalEngine().analyze("2330") == EXPECTED_FALLBACK


def test_engine_calls_service_once_per_analysis(monkeypatch):
    calls = {"count": 0}

    def get_fundamental(self, stock_id):
        calls["count"] += 1
        return {
            "eps": None,
            "pe": None,
            "pb": None,
            "roe": None,
            "revenue_growth": None,
            "dividend_yield": None,
            "available": False,
        }

    monkeypatch.setattr(FundamentalService, "get_fundamental", get_fundamental)

    result = FundamentalEngine().analyze("2330")

    assert calls["count"] == 1
    assert result["available"] is False


def test_engine_scores_partial_data_without_penalizing_missing_fields(monkeypatch):
    monkeypatch.setattr(
        FundamentalService,
        "get_fundamental",
        lambda self, stock_id: {
            "eps": 5.0,
            "pe": None,
            "pb": None,
            "roe": None,
            "revenue_growth": 12.0,
            "dividend_yield": None,
            "available": True,
        },
    )

    result = FundamentalEngine().analyze("2330")

    assert result["available"] is True
    assert result["score"] == 75
    assert result["summary"] == "基本面偏佳"
    assert result["roe"] is None
    assert 0 <= result["score"] <= 100


def test_engine_unavailable_service_result_uses_fixed_fallback(monkeypatch):
    monkeypatch.setattr(
        FundamentalService,
        "get_fundamental",
        lambda self, stock_id: {
            "eps": None,
            "pe": None,
            "pb": None,
            "roe": None,
            "revenue_growth": None,
            "dividend_yield": None,
            "available": False,
        },
    )

    assert FundamentalEngine().analyze("2330") == EXPECTED_FALLBACK


def _engine_result_with_fields(monkeypatch, **fields):
    data = {
        "eps": None,
        "pe": None,
        "pb": None,
        "roe": None,
        "revenue_growth": None,
        "dividend_yield": None,
        "available": True,
        **fields,
    }
    monkeypatch.setattr(
        FundamentalService,
        "get_fundamental",
        lambda self, stock_id: data,
    )
    return FundamentalEngine().analyze("2330")


def test_sparse_score_caps_are_applied(monkeypatch):
    one_field = _engine_result_with_fields(monkeypatch, eps=5)
    two_fields = _engine_result_with_fields(monkeypatch, eps=5, pe=10)
    three_fields = _engine_result_with_fields(monkeypatch, eps=5, pe=10, pb=1)
    four_fields = _engine_result_with_fields(
        monkeypatch,
        eps=5,
        pe=10,
        pb=1,
        revenue_growth=20,
    )

    assert one_field["score"] == 60
    assert two_fields["score"] == 75
    assert three_fields["score"] == 85
    assert four_fields["score"] == 100
    assert one_field["summary"] == "基本面中性"
    assert two_fields["summary"] == "基本面偏佳"
    assert all(result["roe"] is None for result in (one_field, two_fields, three_fields, four_fields))
    assert all(0 <= result["score"] <= 100 for result in (one_field, two_fields, three_fields, four_fields))
