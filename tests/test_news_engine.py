import pytest

from core.market.news_engine import NewsEngine
from services.news_service import NewsService
from services import market_service


FALLBACK = {
    "items": [],
    "count": 0,
    "positive_count": 0,
    "negative_count": 0,
    "neutral_count": 0,
    "score": 0,
    "summary": "尚未整合",
    "signals": [],
    "available": False,
}


def _item(title, url=""):
    return {"date": "2026-07-11", "title": title, "source": "測試", "url": url}


def _service_result(titles, available=True):
    items = [_item(title) for title in titles]
    return {"items": items, "count": len(items), "available": available}


def _analyze(monkeypatch, titles):
    result = _service_result(titles)
    monkeypatch.setattr(NewsService, "get_news", lambda self, stock_id: result)
    return NewsEngine().analyze("2330")


@pytest.mark.parametrize(
    ("titles", "counts", "score", "summary"),
    [
        (["營收創新高", "獲利成長", "需求強勁", "接單增加"], (4, 0, 0), 100, "新聞情緒偏多"),
        (["需求疲弱", "營運下滑", "公司裁員", "轉虧警示"], (0, 4, 0), 0, "新聞情緒偏空"),
        (["公司召開股東會"] * 4, (0, 0, 4), 50, "新聞情緒中性"),
        (["獲利成長", "需求疲弱", "公司召開股東會", "配息"], (2, 1, 1), 63, "新聞情緒中性偏多"),
    ],
)
def test_sentiment_groups(monkeypatch, titles, counts, score, summary):
    result = _analyze(monkeypatch, titles)
    assert (result["positive_count"], result["negative_count"], result["neutral_count"]) == counts
    assert result["score"] == score
    assert result["summary"] == summary


def test_conflicting_keywords_are_neutral(monkeypatch):
    result = _analyze(monkeypatch, ["營收成長但需求疲弱"])
    assert result["neutral_count"] == 1
    assert result["positive_count"] == result["negative_count"] == 0


def test_ai_keyword_is_case_insensitive(monkeypatch):
    for title in ("AI 新產品", "ai 新產品", "Ai 新產品"):
        assert _analyze(monkeypatch, [title])["positive_count"] == 1


@pytest.mark.parametrize(
    "invalid_result",
    [
        None,
        "invalid",
        {"available": True},
        {"items": {}, "count": 0, "available": True},
        {"items": [], "count": 0, "available": True},
        {"items": [], "count": 0, "available": False},
        {"items": [None, {"title": ""}], "count": 2, "available": True},
    ],
)
def test_invalid_service_results_use_fallback(monkeypatch, invalid_result):
    monkeypatch.setattr(NewsService, "get_news", lambda self, stock_id: invalid_result)
    assert NewsEngine().analyze("2330") == FALLBACK


@pytest.mark.parametrize("stock_id", [None, "", "   "])
def test_invalid_stock_id_falls_back_without_service(monkeypatch, stock_id):
    monkeypatch.setattr(
        NewsService,
        "get_news",
        lambda self, value: (_ for _ in ()).throw(AssertionError("must not call")),
    )
    assert NewsEngine().analyze(stock_id) == FALLBACK


def test_service_exception_uses_fallback(monkeypatch):
    monkeypatch.setattr(
        NewsService,
        "get_news",
        lambda self, stock_id: (_ for _ in ()).throw(RuntimeError("simulated")),
    )
    assert NewsEngine().analyze("2330") == FALLBACK


def test_sparse_score_caps_and_negative_not_raised(monkeypatch):
    assert _analyze(monkeypatch, ["創新高"])["score"] == 60
    assert _analyze(monkeypatch, ["創新高"] * 2)["score"] == 75
    assert _analyze(monkeypatch, ["創新高"] * 3)["score"] == 85
    assert _analyze(monkeypatch, ["創新高"] * 4)["score"] == 100
    assert _analyze(monkeypatch, ["虧損"])["score"] == 0


@pytest.mark.parametrize(
    ("titles", "expected_summary"),
    [
        (["創新高"] * 3, "新聞情緒偏多"),
        (["創新高"], "新聞情緒中性偏多"),
        (["一般新聞"], "新聞情緒中性"),
        (["虧損", "一般新聞"], "新聞情緒中性偏空"),
        (["虧損"], "新聞情緒偏空"),
    ],
)
def test_summary_thresholds_use_final_score(monkeypatch, titles, expected_summary):
    result = _analyze(monkeypatch, titles)
    assert result["summary"] == expected_summary
    assert 0 <= result["score"] <= 100


def test_count_signals_latest_title_and_no_url(monkeypatch):
    items = [
        _item("營收創新高", "https://secret.example/one"),
        _item("需求疲弱", "https://secret.example/two"),
        _item("股東會", "https://secret.example/three"),
    ]
    monkeypatch.setattr(
        NewsService,
        "get_news",
        lambda self, stock_id: {"items": items, "count": 3, "available": True},
    )
    result = NewsEngine().analyze("2330")
    assert result["count"] == len(result["items"]) == 3
    assert result["signals"] == [
        "近 7 日利多新聞 1 則",
        "近 7 日利空新聞 1 則",
        "近 7 日中立新聞 1 則",
        "最新新聞：營收創新高",
        "新聞情緒分數 50",
    ]
    assert all("http" not in signal for signal in result["signals"])


def test_long_latest_title_is_truncated_to_forty_characters(monkeypatch):
    title = "成長" * 25
    signal = _analyze(monkeypatch, [title])["signals"][3]
    assert signal == f"最新新聞：{title[:40]}…"


def test_service_is_called_once(monkeypatch):
    calls = {"count": 0}

    def get_news(self, stock_id):
        calls["count"] += 1
        return _service_result(["創新高"])

    monkeypatch.setattr(NewsService, "get_news", get_news)
    NewsEngine().analyze("2330")
    assert calls["count"] == 1


def test_market_service_news_failure_preserves_other_data(monkeypatch):
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
    monkeypatch.setattr(market_service.InstitutionEngine, "analyze", lambda self, stock_id: {"available": False})
    monkeypatch.setattr(
        market_service.NewsEngine,
        "analyze",
        lambda self, stock_id: (_ for _ in ()).throw(RuntimeError("simulated")),
    )

    result = market_service.get_market_info("2330")

    assert result["price"] == 1000
    assert result["technical"] == {"trend": "多頭"}
    assert result["financial"] == {"available": False}
    assert result["institution"] == {"available": False}
    assert result["news"] == FALLBACK
