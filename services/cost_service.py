"""Deterministic OpenAI cost calculation with explicitly supplied pricing."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


MILLION = Decimal("1000000")
DEFAULT_PRICING_USD_PER_1M: dict[str, dict[str, Decimal]] = {}


def _safe_tokens(value) -> int:
    if isinstance(value, bool):
        return 0
    if not isinstance(value, (int, float)):
        return 0
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return 0
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        return int(number) if number.is_finite() and number >= 0 else 0
    return int(number)


class CostCalculator:
    def __init__(self, pricing: dict | None = None):
        self.pricing = pricing if pricing is not None else DEFAULT_PRICING_USD_PER_1M

    def calculate(self, model, prompt_tokens, completion_tokens) -> dict:
        prompt = _safe_tokens(prompt_tokens)
        completion = _safe_tokens(completion_tokens)
        prices = self.pricing.get(model) if isinstance(model, str) else None
        if not isinstance(prices, dict):
            return {"estimated_cost_usd": Decimal("0"), "pricing_status": "pricing_unknown"}
        try:
            input_price = Decimal(str(prices["input"]))
            output_price = Decimal(str(prices["output"]))
            if not input_price.is_finite() or not output_price.is_finite():
                raise InvalidOperation
            cost = (Decimal(prompt) / MILLION * input_price) + (
                Decimal(completion) / MILLION * output_price
            )
        except (KeyError, InvalidOperation, TypeError, ValueError):
            return {"estimated_cost_usd": Decimal("0"), "pricing_status": "pricing_unknown"}
        return {"estimated_cost_usd": cost, "pricing_status": "available"}
