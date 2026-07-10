from core.market.fundamental_engine import FundamentalEngine
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
