from copy import deepcopy

import pytest

from core.explain_engine import build_analysis_sections


def _explain(financial: dict) -> str:
    return build_analysis_sections({"financial": financial})["explain"]


def test_unavailable_fundamental_remains_unintegrated():
    explain = _explain({"available": False})

    assert "基本面：尚未整合" in explain
    assert "AI判定：" not in explain


def test_fundamental_with_only_eps():
    explain = _explain(
        {
            "available": True,
            "eps": 5.256,
            "summary": "基本面中性",
        }
    )

    assert "EPS：\n5.26" in explain
    assert "本益比(PER)：" not in explain
    assert "AI判定：\n基本面中性" in explain


def test_fundamental_with_only_per():
    explain = _explain(
        {
            "available": True,
            "pe": 18.26,
            "summary": "基本面中性",
        }
    )

    assert "本益比(PER)：\n18.3" in explain
    assert "EPS：" not in explain


def test_all_fundamental_values_are_formatted_in_order():
    explain = _explain(
        {
            "available": True,
            "eps": 5.256,
            "pe": 18.26,
            "pb": 2.54,
            "dividend_yield": 3.24,
            "revenue_growth": 12.56,
            "summary": "基本面偏佳",
        }
    )

    expected = (
        "基本面：\n\n"
        "EPS：\n5.26\n\n"
        "本益比(PER)：\n18.3\n\n"
        "股價淨值比(PBR)：\n2.5\n\n"
        "殖利率：\n3.2%\n\n"
        "月營收 YoY：\n12.6%\n\n"
        "AI判定：\n基本面偏佳"
    )
    assert expected in explain


def test_none_fundamental_values_are_omitted():
    explain = _explain(
        {
            "available": True,
            "eps": None,
            "pe": 20,
            "pb": None,
            "dividend_yield": 2,
            "revenue_growth": None,
            "summary": "基本面偏弱",
        }
    )

    assert "EPS：" not in explain
    assert "本益比(PER)：\n20.0" in explain
    assert "股價淨值比(PBR)：" not in explain
    assert "殖利率：\n2.0%" in explain
    assert "月營收YoY：" not in explain
    assert "AI判定：\n基本面偏弱" in explain


def _institution_explain(institution: dict) -> str:
    return build_analysis_sections({"institution": institution})["explain"]


def test_unavailable_institution_remains_unintegrated():
    explain = _institution_explain({"available": False})

    assert "籌碼面：尚未整合" in explain


def test_all_institutions_buy_and_summary_is_preserved():
    explain = _institution_explain(
        {
            "available": True,
            "foreign_buy_sell": 12345,
            "investment_buy_sell": 2100,
            "dealer_buy_sell": 500,
            "three_major_buy_sell": 14945,
            "summary": "籌碼偏多",
        }
    )

    assert "外資：\n買超 12,345 張" in explain
    assert "投信：\n買超 2,100 張" in explain
    assert "自營商：\n買超 500 張" in explain
    assert "三大法人：\n合計買超 14,945 張" in explain
    assert "AI判定：\n籌碼偏多" in explain


def test_all_institutions_sell():
    explain = _institution_explain(
        {
            "available": True,
            "foreign_buy_sell": -8200,
            "investment_buy_sell": -1000,
            "dealer_buy_sell": -300,
            "three_major_buy_sell": -9500,
            "summary": "籌碼偏空",
        }
    )

    assert "外資：\n賣超 8,200 張" in explain
    assert "投信：\n賣超 1,000 張" in explain
    assert "自營商：\n賣超 300 張" in explain
    assert "三大法人：\n合計賣超 9,500 張" in explain
    assert "AI判定：\n籌碼偏空" in explain


def test_missing_institution_values_are_omitted():
    explain = _institution_explain(
        {
            "available": True,
            "foreign_buy_sell": 100,
            "investment_buy_sell": None,
            "dealer_buy_sell": None,
            "three_major_buy_sell": 100,
            "summary": "籌碼中性偏多",
        }
    )

    assert "外資：\n買超 100 張" in explain
    assert "投信：" not in explain
    assert "自營商：" not in explain
    assert "三大法人：\n合計買超 100 張" in explain


def test_flat_institution_is_displayed():
    explain = _institution_explain(
        {
            "available": True,
            "foreign_buy_sell": 0,
            "summary": "籌碼中性",
        }
    )

    assert "外資：\n持平" in explain
    assert "AI判定：\n籌碼中性" in explain


def test_technical_layout_uses_label_value_blocks():
    explain = build_analysis_sections(
        {
            "core": {
                "ma_signal": "站上 MA20",
                "macd_signal": "死亡交叉",
                "kd_signal": "死亡交叉",
                "rsi_signal": "50.4（健康區間）",
            }
        }
    )["explain"]

    assert "技術面：\n\n均線：\n站上 MA20" in explain
    assert "動能：\nMACD、KD 死亡交叉" in explain
    assert "RSI：\n50.4（健康區間）" in explain


def test_market_sentiment_layout():
    explain = build_analysis_sections(
        {"core": {"consensus_score": 60, "trend": "多頭"}}
    )["explain"]

    assert "市場情緒：\n\n技術指標共識度：\n\n60%" in explain
    assert "目前偏向：\n\n偏多" in explain
    assert "新聞尚未整合" not in explain


def test_valid_news_displays_summary_score_and_safe_signals_in_order():
    explain = build_analysis_sections(
        {
            "news": {
                "available": True,
                "summary": "新聞情緒中性偏多",
                "score": 62.6,
                "signals": [
                    "近 7 日利多新聞 2 則",
                    "https://example.com/news",
                    "建議投資並買進",
                    "RuntimeError: simulated failure",
                    "最新新聞：營收成長",
                    "",
                    None,
                ],
            }
        }
    )["explain"]

    assert "新聞面：新聞情緒中性偏多" in explain
    assert "新聞情緒分數：63 分" in explain
    assert explain.index("近 7 日利多新聞 2 則") < explain.index("最新新聞：營收成長")
    assert "http" not in explain
    assert "建議投資" not in explain
    assert "RuntimeError" not in explain
    assert "新聞尚未整合" not in explain


@pytest.mark.parametrize(
    "news",
    [
        None,
        {},
        {"summary": "中性", "score": 50},
        {"available": False, "summary": "中性", "score": 50},
        {"available": True, "summary": "中性"},
        {"available": True, "summary": "中性", "score": None},
        {"available": True, "summary": "中性", "score": "50"},
        {"available": True, "summary": "中性", "score": True},
        {"available": True, "summary": "中性", "score": float("nan")},
        {"available": True, "summary": "中性", "score": float("inf")},
    ],
)
def test_invalid_news_displays_data_insufficient(news):
    explain = build_analysis_sections({"news": news})["explain"]
    assert "新聞面：資料不足" in explain


def test_news_score_is_clamped():
    low = build_analysis_sections(
        {"news": {"available": True, "summary": "偏空", "score": -1}}
    )["explain"]
    high = build_analysis_sections(
        {"news": {"available": True, "summary": "偏多", "score": 101}}
    )["explain"]
    assert "新聞情緒分數：0 分" in low
    assert "新聞情緒分數：100 分" in high


def test_valid_composite_displays_summary_score_coverage_and_unique_signals():
    explain = build_analysis_sections(
        {
            "composite": {
                "available": True,
                "summary": "整體市場訊號中性偏多",
                "score": 64.6,
                "coverage": 74.6,
                "signals": [
                    "技術面：80 分",
                    "技術面：80 分",
                    "基本面：60 分",
                    "www.example.com",
                    "強烈推薦加碼",
                    123,
                ],
            }
        }
    )["explain"]

    assert "綜合分析：整體市場訊號中性偏多" in explain
    assert "綜合分數：65 分" in explain
    assert "資料覆蓋率：75%" in explain
    assert explain.count("技術面：80 分") == 1
    assert explain.index("技術面：80 分") < explain.index("基本面：60 分")
    assert "www." not in explain
    assert "強烈推薦" not in explain


@pytest.mark.parametrize(
    "composite",
    [
        None,
        {},
        {"summary": "中性", "score": 50, "coverage": 50},
        {"available": False, "summary": "中性", "score": 50, "coverage": 50},
        {"available": True, "summary": "中性", "score": "50", "coverage": 50},
        {"available": True, "summary": "中性", "score": 50, "coverage": True},
        {"available": True, "summary": "中性", "score": float("nan"), "coverage": 50},
        {"available": True, "summary": "中性", "score": 50, "coverage": float("inf")},
    ],
)
def test_invalid_composite_displays_data_insufficient(composite):
    explain = build_analysis_sections({"composite": composite})["explain"]
    assert "綜合分析：資料不足" in explain


def test_composite_score_and_coverage_are_clamped():
    explain = build_analysis_sections(
        {
            "composite": {
                "available": True,
                "summary": "測試",
                "score": 200,
                "coverage": -10,
            }
        }
    )["explain"]
    assert "綜合分數：100 分" in explain
    assert "資料覆蓋率：0%" in explain


def test_news_precedes_composite_and_inputs_are_not_modified():
    stock = {
        "news": {
            "available": True,
            "summary": "新聞中性",
            "score": 50,
            "signals": ["新聞訊號"],
        },
        "composite": {
            "available": True,
            "summary": "綜合中性",
            "score": 50,
            "coverage": 100,
            "signals": ["綜合訊號"],
        },
    }
    original = deepcopy(stock)
    explain = build_analysis_sections(stock)["explain"]
    assert explain.index("新聞面：") < explain.index("綜合分析：")
    assert stock == original
