from core.market.fundamental_engine import FundamentalEngine
from services.fundamental_service import FundamentalService
from services import market_service


EXPECTED_KEYS = {
    "eps",
    "pe",
    "pb",
    "roe",
    "revenue_growth",
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
            "available": False,
        }

    monkeypatch.setattr(FundamentalService, "get_fundamental", get_fundamental)

    result = FundamentalEngine().analyze("2330")

    assert calls["count"] == 1
    assert result["available"] is False
