"""Pure Fubon Neo quote payload adapter.

The aliases below describe sanitized contract fixtures only.  They are not a
claim that the production SDK schema has been verified.  A sanitized real SDK
sample must confirm them before this adapter is connected to live data.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from services.providers.quote import Quote


PROVIDER = "fubon_neo"
SAFE_REASONS = frozenset(
    {
        "ok",
        "empty_payload",
        "invalid_symbol",
        "symbol_mismatch",
        "missing_price",
        "invalid_numeric_value",
        "invalid_ohlc",
        "invalid_timestamp",
        "conflicting_fields",
        "unsupported_schema",
    }
)

# Centralized aliases used by sanitized tests.  Do not expand this list from
# guesses; new aliases require a verified, secret-free SDK fixture.
FIELD_ALIASES = {
    "symbol": ("symbol", "stock_no", "stockNo", "code"),
    "market": ("market", "exchange", "marketType"),
    "timestamp": ("timestamp", "time", "datetime"),
    "status": ("status", "market_status", "marketStatus"),
    "price": ("price", "last_price", "lastPrice", "close_price", "closePrice"),
    "reference": ("reference", "reference_price", "referencePrice", "ref_price"),
    "change": ("change", "price_change", "priceChange"),
    "change_percent": ("change_percent", "changePercent", "change_rate"),
    "open": ("open", "open_price", "openPrice"),
    "high": ("high", "high_price", "highPrice"),
    "low": ("low", "low_price", "lowPrice"),
    "volume": ("volume", "total_volume", "totalVolume"),
    "is_realtime": ("is_realtime", "isRealtime", "realtime"),
}

_STATUS_VALUES = {
    "trading": "trading",
    "open": "trading",
    "pre_open": "pre_open",
    "preopen": "pre_open",
    "closed": "closed",
    "close": "closed",
    "halted": "halted",
    "halt": "halted",
    "delayed": "delayed",
}
_MARKET_VALUES = {
    "twse": "TWSE",
    "tse": "TWSE",
    "listed": "TWSE",
    "tpex": "TPEx",
    "otc": "TPEx",
}
_MISSING = object()
_EARLIEST_TIMESTAMP = datetime(2000, 1, 1, tzinfo=timezone.utc)
_LATEST_TIMESTAMP = datetime(2100, 1, 1, tzinfo=timezone.utc)


class _AliasConflict(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AdapterResult:
    ok: bool
    quote: Quote | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "quote": self.quote.to_dict() if self.quote else None,
            "reason": self.reason,
        }


def adapt_quote(payload: Any, expected_symbol: Any = None) -> AdapterResult:
    """Convert a sanitized dict/attribute payload into a safe Quote."""
    try:
        return _adapt_quote(payload, expected_symbol)
    except _AliasConflict:
        return _failure("conflicting_fields")
    except Exception:
        return _failure("unsupported_schema")


def _adapt_quote(payload: Any, expected_symbol: Any) -> AdapterResult:
    if payload is None or payload == {}:
        return _failure("empty_payload")
    if not _has_supported_field(payload):
        return _failure("unsupported_schema")

    expected = _symbol(expected_symbol, allow_missing=True)
    if expected_symbol is not None and expected is None:
        return _failure("invalid_symbol")
    symbol = _symbol(_value(payload, "symbol"))
    if symbol is None:
        return _failure("invalid_symbol")
    if expected is not None and symbol != expected:
        return _failure("symbol_mismatch")

    numeric = {}
    for name in (
        "price", "reference", "change", "change_percent", "open", "high", "low"
    ):
        raw = _value(payload, name)
        if raw is _MISSING or _is_blank(raw):
            numeric[name] = None
            continue
        number = _finite_number(raw)
        if number is None:
            return _failure("invalid_numeric_value")
        if name not in {"change", "change_percent"} and number < 0:
            return _failure("invalid_numeric_value")
        numeric[name] = number

    if numeric["price"] is None:
        return _failure("missing_price")

    raw_volume = _value(payload, "volume")
    volume = None
    if raw_volume is not _MISSING and not _is_blank(raw_volume):
        volume = _finite_volume(raw_volume)
        if volume is None or volume < 0:
            return _failure("invalid_numeric_value")

    if (
        numeric["high"] is not None
        and numeric["low"] is not None
        and numeric["high"] < numeric["low"]
    ):
        return _failure("invalid_ohlc")

    raw_timestamp = _value(payload, "timestamp")
    timestamp = None
    if raw_timestamp is not _MISSING and not _is_blank(raw_timestamp):
        timestamp = _timestamp(raw_timestamp)
        if timestamp is None:
            return _failure("invalid_timestamp")

    if numeric["change"] is None and numeric["reference"] is not None:
        numeric["change"] = numeric["price"] - numeric["reference"]
    if (
        numeric["change_percent"] is None
        and numeric["reference"] not in {None, 0}
        and numeric["change"] is not None
    ):
        numeric["change_percent"] = (
            numeric["change"] / numeric["reference"] * 100
        )

    status = _status(_value(payload, "status"))
    market = _market(_value(payload, "market"))
    explicit_realtime = _value(payload, "is_realtime") is True
    realtime_candidate = bool(
        explicit_realtime and timestamp is not None and status == "trading"
    )
    incomplete = any(
        value is None
        for value in (
            timestamp,
            numeric["reference"],
            numeric["open"],
            numeric["high"],
            numeric["low"],
            numeric["change"],
            numeric["change_percent"],
            volume,
        )
    )
    if incomplete:
        quality = "incomplete"
    elif realtime_candidate:
        quality = "realtime"
    else:
        quality = "delayed"
    is_realtime = quality == "realtime"

    quote = Quote(
        provider=PROVIDER,
        symbol=symbol,
        market=market,
        timestamp=timestamp,
        status=status,
        price=numeric["price"],
        reference=numeric["reference"],
        change=numeric["change"],
        change_percent=numeric["change_percent"],
        open=numeric["open"],
        high=numeric["high"],
        low=numeric["low"],
        volume=volume,
        is_realtime=is_realtime,
        data_quality=quality,
    )
    return AdapterResult(ok=True, quote=quote, reason="ok")


def _failure(reason: str) -> AdapterResult:
    return AdapterResult(
        ok=False,
        quote=None,
        reason=reason if reason in SAFE_REASONS else "unsupported_schema",
    )


def _has_supported_field(payload: Any) -> bool:
    return any(_value(payload, name) is not _MISSING for name in FIELD_ALIASES)


def _value(payload: Any, field: str) -> Any:
    values = []
    for alias in FIELD_ALIASES[field]:
        if isinstance(payload, Mapping):
            if alias in payload:
                values.append(payload[alias])
        else:
            try:
                values.append(getattr(payload, alias))
            except AttributeError:
                continue
            except Exception:
                continue
    if not values:
        return _MISSING
    normalized = [_alias_comparison_value(field, value) for value in values]
    if any(value != normalized[0] for value in normalized[1:]):
        raise _AliasConflict
    return values[0]


def _alias_comparison_value(field: str, value: Any) -> Any:
    if _is_blank(value):
        return ("blank", None)
    if field == "symbol":
        normalized = _symbol(value)
        return ("symbol", normalized) if normalized is not None else _invalid_value(value)
    if field in {
        "price", "reference", "change", "change_percent", "open", "high", "low", "volume"
    }:
        normalized = _finite_number(value)
        return ("number", normalized) if normalized is not None else _invalid_value(value)
    if field == "timestamp":
        normalized = _timestamp(value)
        return ("timestamp", normalized) if normalized is not None else _invalid_value(value)
    if field == "status":
        return ("status", _status(value))
    if field == "market":
        return ("market", _market(value))
    if field == "is_realtime":
        return ("realtime", value) if isinstance(value, bool) else _invalid_value(value)
    return _invalid_value(value)


def _invalid_value(value: Any) -> tuple[str, Any]:
    if isinstance(value, str):
        return ("invalid_string", value.strip())
    return ("invalid_type", type(value).__name__)


def _symbol(value: Any, *, allow_missing: bool = False) -> str | None:
    if value is _MISSING and allow_missing:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value else None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() in {"", "--"})


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or isinstance(value, (list, tuple, dict, set)):
        return None
    if not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _finite_volume(value: Any) -> int | float | None:
    number = _finite_number(value)
    if number is None:
        return None
    return int(number) if number.is_integer() else number


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        result = value if value.tzinfo is not None and value.utcoffset() is not None else None
        return result if _timestamp_in_range(result) else None
    if isinstance(value, (int, float, Decimal)):
        number = _finite_number(value)
        if number is None:
            return None
        if number > 1_000_000_000_000:
            number /= 1000
        try:
            result = datetime.fromtimestamp(number, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
        return result if _timestamp_in_range(result) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            return None
        if result.tzinfo is None or result.utcoffset() is None:
            return None
        return result if _timestamp_in_range(result) else None
    return None


def _timestamp_in_range(value: datetime | None) -> bool:
    if value is None:
        return False
    try:
        utc_value = value.astimezone(timezone.utc)
        return _EARLIEST_TIMESTAMP <= utc_value <= _LATEST_TIMESTAMP
    except Exception:
        return False


def _status(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    return _STATUS_VALUES.get(value.strip().casefold(), "unknown")


def _market(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _MARKET_VALUES.get(value.strip().casefold())
