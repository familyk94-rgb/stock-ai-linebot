from decimal import Decimal

import pytest

from services.cost_service import CostCalculator


PRICING = {"test-model": {"input": "2.5", "output": "10"}}


def test_known_model_input_output_and_total_cost():
    result = CostCalculator(PRICING).calculate("test-model", 1_000_000, 500_000)
    assert result == {"estimated_cost_usd": Decimal("7.5"), "pricing_status": "available"}


def test_zero_and_invalid_tokens_are_safe():
    calculator = CostCalculator(PRICING)
    for value in (0, -1, None, "bad", float("nan"), float("inf"), True):
        assert calculator.calculate("test-model", value, value)["estimated_cost_usd"] == Decimal("0")


def test_unknown_model_has_zero_cost_and_explicit_status():
    assert CostCalculator(PRICING).calculate("unknown", 100, 200) == {
        "estimated_cost_usd": Decimal("0"),
        "pricing_status": "pricing_unknown",
    }


def test_empty_pricing_mapping_keeps_gpt_4_1_mini_unknown():
    assert CostCalculator({}).calculate("gpt-4.1-mini", 1000, 500) == {
        "estimated_cost_usd": Decimal("0"),
        "pricing_status": "pricing_unknown",
    }


def test_numeric_string_tokens_are_not_accepted():
    assert CostCalculator(PRICING).calculate("test-model", "100", "200")["estimated_cost_usd"] == Decimal("0")


def test_finite_fractional_float_tokens_are_truncated_toward_zero():
    result = CostCalculator(PRICING).calculate("test-model", 10.9, 5.8)
    expected = (Decimal(10) / Decimal(1_000_000) * Decimal("2.5")) + (
        Decimal(5) / Decimal(1_000_000) * Decimal("10")
    )
    assert result["estimated_cost_usd"] == expected


def test_decimal_precision_is_not_rounded_early():
    result = CostCalculator(PRICING).calculate("test-model", 1, 1)
    assert result["estimated_cost_usd"] == Decimal("0.0000125")
