"""Adapter from the existing FinMind stock loader to the Quote contract."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from services.providers.fubon_neo_quote import AdapterResult
from services.providers.quote import Quote
from services.stock_service import get_stock_info


class FinMindQuoteProvider:
    def __init__(self, loader: Callable[[str], Any] | None = None) -> None:
        self._loader = loader or get_stock_info

    def get_quote(self, symbol: str) -> AdapterResult:
        try:
            stock = self._loader(symbol)
            if not isinstance(stock, Mapping):
                return AdapterResult(False, None, "empty_payload")
            price = _number(stock.get("close"))
            if price is None or price < 0:
                return AdapterResult(False, None, "missing_price")
            timestamp = _date_timestamp(stock.get("date"))
            quote = Quote(
                provider="finmind",
                symbol=str(symbol).strip(),
                market=None,
                timestamp=timestamp,
                status="closed",
                price=price,
                reference=None,
                change=_number(stock.get("change")),
                change_percent=_number(stock.get("change_percent")),
                open=_nonnegative(stock.get("open")),
                high=_nonnegative(stock.get("max")),
                low=_nonnegative(stock.get("min")),
                volume=_volume(stock.get("volume")),
                is_realtime=False,
                data_quality="incomplete",
            )
            if quote.high is not None and quote.low is not None and quote.high < quote.low:
                return AdapterResult(False, None, "invalid_ohlc")
            return AdapterResult(True, quote, "ok")
        except Exception:
            return AdapterResult(False, None, "quote_failed")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _nonnegative(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result >= 0 else None


def _volume(value: Any) -> int | float | None:
    result = _nonnegative(value)
    if result is None:
        return None
    return int(result) if result.is_integer() else result


def _date_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
        return parsed.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    except (ValueError, TypeError, OSError):
        return None
