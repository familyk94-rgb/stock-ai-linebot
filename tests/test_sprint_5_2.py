from core.data_quality import calculate_confidence, calculate_data_completeness
from core.explain_engine import build_analysis_sections
from core.ganzai_ai import GanzaiAI


def _complete_stock() -> dict:
    return {
        "price": 100,
        "open": 98,
        "high": 102,
        "low": 97,
        "volume": 1000,
        "change_percent": 2.04,
        "financial": {"eps": 5},
        "institution": {"foreign": 100},
        "news": [{"title": "測試新聞"}],
        "technical": {
            "ma5": 101,
            "ma10": 100,
            "ma20": 99,
            "ma60": 95,
            "rsi": 55,
            "k": 60,
            "d": 50,
            "macd": 1,
            "signal": 0.5,
            "histogram": 0.5,
        },
    }


def test_same_signal_from_macd_and_kd_is_preserved():
    stock = {
        "core": {
            "ma_signal": "站上 MA20",
            "macd_signal": "死亡交叉",
            "rsi_signal": "50.4（健康區間）",
            "kd_signal": "死亡交叉",
        }
    }

    result = build_analysis_sections(stock)
    technical_line = next(
        line for line in result["explain"].splitlines() if line.startswith("技術面：")
    )

    assert "均線：站上 MA20" in technical_line
    assert "MACD：死亡交叉" in technical_line
    assert "RSI：50.4（健康區間）" in technical_line
    assert "KD：死亡交叉" in technical_line
    assert technical_line.count("死亡交叉") == 2


def test_duplicate_signal_within_same_indicator_is_removed():
    stock = {
        "core": {
            "macd_signal": "死亡交叉、死亡交叉",
        }
    }

    result = build_analysis_sections(stock)
    technical_line = next(
        line for line in result["explain"].splitlines() if line.startswith("技術面：")
    )

    assert "MACD：死亡交叉" in technical_line
    assert technical_line.count("死亡交叉") == 1


def test_score_and_confidence_are_independent():
    stock = _complete_stock()
    bullish = GanzaiAI(stock).run()
    bearish = GanzaiAI(
        {
            **stock,
            "price": 80,
            "technical": {
                **stock["technical"],
                "ma5": 85,
                "ma10": 90,
                "ma20": 95,
                "ma60": 100,
                "rsi": 25,
                "k": 20,
                "d": 40,
                "macd": -1,
                "signal": 0,
                "histogram": -1,
            },
        }
    ).run()

    assert bullish["score"] != bearish["score"]
    assert bullish["score"] != bullish["confidence"]
    assert bullish["confidence"] != bullish["data_completeness"]


def test_same_completeness_with_different_consistency_changes_confidence():
    stock = _complete_stock()
    consistent_signals = {
        "trend": "多頭",
        "ma_signal": "多頭排列",
        "macd_signal": "黃金交叉",
        "rsi_signal": "55.0 健康區間",
        "kd_signal": "黃金交叉",
    }
    conflicting_signals = {
        **consistent_signals,
        "macd_signal": "死亡交叉",
        "kd_signal": "死亡交叉",
    }

    consistent = calculate_confidence(stock, 100, consistent_signals)
    conflicting = calculate_confidence(stock, 60, conflicting_signals)

    assert calculate_data_completeness(stock) == 100
    assert consistent > conflicting


def test_data_completeness_is_stored_in_core_output():
    stock = _complete_stock()
    result = GanzaiAI(stock).run()

    assert result["data_completeness"] == 100
    assert result["data_completeness"] == calculate_data_completeness(stock)


def test_missing_fields_reduce_completeness_and_confidence_equally():
    stock = {"price": 100, "technical": {"rsi": 55}}

    completeness = calculate_data_completeness(stock)
    confidence = calculate_confidence(
        stock,
        50,
        {"rsi_signal": "55.0 健康區間"},
    )

    assert completeness == 11
    assert confidence <= 60
    assert confidence != completeness


def test_no_market_data_has_zero_completeness():
    assert calculate_data_completeness({}) == 0
