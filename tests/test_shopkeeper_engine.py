from copy import deepcopy

import pytest

from core.shopkeeper_engine import get_composite_aware_advice


ORIGINAL = "阿柑店長看法：先依技術面觀察。"


def composite(score=60, coverage=100, available=True):
    return {
        "available": available,
        "score": score,
        "coverage": coverage,
        "summary": "整體市場訊號",
    }


def test_unavailable_composite_preserves_original_message():
    assert get_composite_aware_advice(ORIGINAL, "偏多", composite(available=False)) == ORIGINAL


@pytest.mark.parametrize(
    ("decision", "score", "expected"),
    [
        ("偏多", 60, "目前技術與整體訊號偏多，可分批觀察，仍需留意風險。"),
        ("偏多", 39, "技術面偏多，但整體訊號仍偏弱，先觀察，不宜追高。"),
        ("偏空", 60, "基本面或籌碼面可能較佳，但技術面仍弱，等待止跌訊號。"),
        ("偏空", 39, "技術與整體訊號皆偏弱，先保守觀望。"),
    ],
)
def test_direction_combinations(decision, score, expected):
    data = composite(score)
    original = deepcopy(data)
    assert get_composite_aware_advice(ORIGINAL, decision, data) == expected
    assert data == original


def test_neutral_composite_preserves_tone_and_adds_neutral_sentence():
    result = get_composite_aware_advice(ORIGINAL, "偏多", composite(50))
    assert result.startswith(ORIGINAL)
    assert result.endswith("整體訊號偏中性，等待方向明確。")


def test_low_coverage_adds_conservative_notice():
    result = get_composite_aware_advice(ORIGINAL, "偏多", composite(70, coverage=25))
    assert result.endswith("目前分析面向不足，判斷需保守。")


@pytest.mark.parametrize("score", [None, float("nan"), float("inf"), "60", True])
def test_invalid_score_preserves_original_message(score):
    assert get_composite_aware_advice(ORIGINAL, "偏多", composite(score)) == ORIGINAL


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"available": True},
        {"available": True, "score": 60},
        {"available": True, "score": 60, "coverage": 100},
    ],
)
def test_missing_or_malformed_composite_preserves_original_message(value):
    assert get_composite_aware_advice(ORIGINAL, "偏多", value) == ORIGINAL


def test_unsupported_decision_preserves_original_message():
    assert get_composite_aware_advice(ORIGINAL, "觀察", composite(70)) == ORIGINAL


def test_advice_is_concise_and_does_not_repeat_analysis_sections():
    result = get_composite_aware_advice(ORIGINAL, "偏多", composite(70, coverage=25))
    assert len(result) < 80
    assert "AI Summary" not in result
    assert "分析原因" not in result
