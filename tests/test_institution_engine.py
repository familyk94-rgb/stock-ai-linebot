import pytest

from core.market.institution_engine import InstitutionEngine
from services.institution_service import InstitutionService
from services import market_service


FALLBACK = {
    "foreign_buy_sell": None,
    "investment_buy_sell": None,
    "dealer_buy_sell": None,
    "three_major_buy_sell": None,
    "foreign_streak": None,
    "investment_streak": None,
    "dealer_streak": None,
    "score": 0,
    "summary": "尚未整合",
    "signals": [],
    "available": False,
}


def _service_result(**values):
    return {
        "foreign_buy_sell": None,
        "investment_buy_sell": None,
        "dealer_buy_sell": None,
        "three_major_buy_sell": None,
        "foreign_streak": None,
        "investment_streak": None,
        "dealer_streak": None,
        "available": True,
        **values,
    }


def _analyze(monkeypatch, **values):
    result = _service_result(**values)
    monkeypatch.setattr(
        InstitutionService,
        "get_institution",
        lambda self, stock_id: result,
    )
    return InstitutionEngine().analyze("2330")


@pytest.mark.parametrize(
    ("values", "expected_score", "expected_summary"),
    [
        ({"foreign_buy_sell": 1, "investment_buy_sell": 1, "dealer_buy_sell": 1, "three_major_buy_sell": 3}, 100, "籌碼偏多"),
        ({"foreign_buy_sell": -1, "investment_buy_sell": -1, "dealer_buy_sell": -1, "three_major_buy_sell": -3}, 0, "籌碼偏空"),
        ({"foreign_buy_sell": 0, "investment_buy_sell": 0, "dealer_buy_sell": 0, "three_major_buy_sell": 0}, 50, "籌碼中性"),
    ],
)
def test_all_buy_sell_and_flat_scores(monkeypatch, values, expected_score, expected_summary):
    result = _analyze(monkeypatch, **values)

    assert result["score"] == expected_score
    assert result["summary"] == expected_summary
    assert 0 <= result["score"] <= 100


def test_partial_missing_fields_do_not_reduce_average(monkeypatch):
    result = _analyze(monkeypatch, foreign_buy_sell=100, investment_buy_sell=None)

    assert result["score"] == 60
    assert result["signals"] == ["外資買超 100 張"]


def test_sparse_score_caps(monkeypatch):
    one = _analyze(monkeypatch, foreign_buy_sell=1)
    two = _analyze(monkeypatch, foreign_buy_sell=1, investment_buy_sell=1)
    three = _analyze(monkeypatch, foreign_buy_sell=1, investment_buy_sell=1, dealer_buy_sell=1)
    four = _analyze(
        monkeypatch,
        foreign_buy_sell=1,
        investment_buy_sell=1,
        dealer_buy_sell=1,
        three_major_buy_sell=3,
    )

    assert one["score"] == 60
    assert two["score"] == 75
    assert three["score"] == 85
    assert four["score"] == 100


@pytest.mark.parametrize(
    ("values", "expected_summary"),
    [
        ({"foreign_buy_sell": 1, "investment_buy_sell": 1, "dealer_buy_sell": 1}, "籌碼偏多"),
        ({"foreign_buy_sell": 1}, "籌碼中性偏多"),
        ({"foreign_buy_sell": 0}, "籌碼中性"),
        ({"foreign_buy_sell": -1, "investment_buy_sell": 0}, "籌碼中性偏空"),
        ({"foreign_buy_sell": -1}, "籌碼偏空"),
    ],
)
def test_summary_thresholds(monkeypatch, values, expected_summary):
    assert _analyze(monkeypatch, **values)["summary"] == expected_summary


def test_signal_formatting(monkeypatch):
    result = _analyze(
        monkeypatch,
        foreign_buy_sell=12345,
        investment_buy_sell=-8210,
        dealer_buy_sell=0,
        three_major_buy_sell=4135,
    )

    assert result["signals"] == [
        "外資買超 12,345 張",
        "投信賣超 8,210 張",
        "自營商持平",
        "三大法人合計買超 4,135 張",
    ]


def test_unavailable_service_result_uses_fallback(monkeypatch):
    monkeypatch.setattr(
        InstitutionService,
        "get_institution",
        lambda self, stock_id: {**_service_result(), "available": False},
    )
    assert InstitutionEngine().analyze("2330") == FALLBACK


@pytest.mark.parametrize("invalid_result", [None, "invalid", {"available": True}])
def test_invalid_service_results_use_fallback(monkeypatch, invalid_result):
    monkeypatch.setattr(
        InstitutionService,
        "get_institution",
        lambda self, stock_id: invalid_result,
    )
    assert InstitutionEngine().analyze("2330") == FALLBACK


def test_service_exception_uses_fallback(monkeypatch):
    def raise_error(self, stock_id):
        raise RuntimeError("simulated")

    monkeypatch.setattr(InstitutionService, "get_institution", raise_error)
    assert InstitutionEngine().analyze("2330") == FALLBACK


def test_service_is_called_once(monkeypatch):
    calls = {"count": 0}

    def get_institution(self, stock_id):
        calls["count"] += 1
        return _service_result(foreign_buy_sell=1)

    monkeypatch.setattr(InstitutionService, "get_institution", get_institution)
    InstitutionEngine().analyze("2330")
    assert calls["count"] == 1


def test_market_service_institution_failure_preserves_other_data(monkeypatch):
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
    monkeypatch.setattr(market_service, "get_technical_indicators", lambda stock_id: {"trend": "多頭"})
    monkeypatch.setattr(market_service.GanzaiAI, "run", lambda self: {"score": 80})
    monkeypatch.setattr(market_service.FundamentalEngine, "analyze", lambda self, stock_id: {"available": False})
    monkeypatch.setattr(
        market_service.InstitutionEngine,
        "analyze",
        lambda self, stock_id: (_ for _ in ()).throw(RuntimeError("simulated")),
    )
    monkeypatch.setattr(
        market_service.NewsEngine,
        "analyze",
        lambda self, stock_id: {"available": False},
    )

    result = market_service.get_market_info("2330")

    assert result["price"] == 1000
    assert result["technical"] == {"trend": "多頭"}
    assert result["financial"] == {"available": False}
    assert result["institution"] == FALLBACK
