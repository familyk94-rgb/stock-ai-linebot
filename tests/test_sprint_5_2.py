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


def _technical_lines(stock: dict) -> list[str]:
    result = build_analysis_sections(stock)
    lines = result["explain"].splitlines()
    start = lines.index("技術面：") + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("基本面：")),
        len(lines),
    )
    return [line for line in lines[start:end] if line]


def _assert_label_value(lines: list[str], label: str, value: str):
    label_index = lines.index(label)
    assert lines[label_index + 1] == value


def test_macd_and_kd_death_cross_are_combined():
    stock = {
        "core": {
            "ma_signal": "站上 MA20",
            "macd_signal": "死亡交叉",
            "rsi_signal": "50.4（健康區間）",
            "kd_signal": "死亡交叉",
        }
    }

    lines = _technical_lines(stock)

    _assert_label_value(lines, "動能：", "MACD、KD 死亡交叉")
    assert "MACD：" not in lines
    assert "KD：" not in lines


def test_macd_and_kd_golden_cross_are_combined():
    stock = {
        "core": {
            "macd_signal": "黃金交叉",
            "kd_signal": "黃金交叉",
        }
    }

    lines = _technical_lines(stock)

    _assert_label_value(lines, "動能：", "MACD、KD 黃金交叉")


def test_different_macd_and_kd_signals_are_not_combined():
    stock = {
        "core": {
            "macd_signal": "死亡交叉",
            "kd_signal": "黃金交叉",
        }
    }

    lines = _technical_lines(stock)

    _assert_label_value(lines, "MACD：", "死亡交叉")
    _assert_label_value(lines, "KD：", "黃金交叉")
    assert "動能：" not in lines


def test_ma_and_rsi_text_are_unchanged():
    stock = {
        "core": {
            "ma_signal": "站上 MA20",
            "macd_signal": "死亡交叉",
            "rsi_signal": "51.6（健康區間）",
            "kd_signal": "死亡交叉",
        }
    }

    lines = _technical_lines(stock)

    _assert_label_value(lines, "均線：", "站上 MA20")
    _assert_label_value(lines, "RSI：", "51.6（健康區間）")


def test_duplicate_signal_within_same_indicator_is_removed():
    stock = {
        "core": {
            "macd_signal": "死亡交叉、死亡交叉",
        }
    }

    lines = _technical_lines(stock)

    _assert_label_value(lines, "MACD：", "死亡交叉")
    assert sum(line.count("死亡交叉") for line in lines) == 1


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
