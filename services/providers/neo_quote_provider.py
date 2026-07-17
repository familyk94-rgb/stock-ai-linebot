"""Fubon Neo SDK quote provider isolated from application services."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.providers.fubon_neo_client import (
    FubonNeoClientManager,
    get_fubon_neo_client_manager,
)
from services.providers.fubon_neo_quote import AdapterResult, adapt_quote


class NeoQuoteProvider:
    def __init__(self, manager: FubonNeoClientManager | None = None) -> None:
        self._manager = manager or get_fubon_neo_client_manager()

    def get_quote(self, symbol: str) -> AdapterResult:
        try:
            client = self._manager.get_client()
            if client is None:
                readiness = self._manager.readiness()
                return _failure(readiness.get("reason") or "login_failed")
            response = _request_quote(client, symbol)
            payload = _quote_payload(response)
            if payload is None:
                return _failure("api_error")
            return adapt_quote(payload, expected_symbol=symbol)
        except TimeoutError:
            return _failure("timeout")
        except Exception:
            return _failure("quote_failed")


def _request_quote(client: Any, symbol: str) -> Any:
    return client.marketdata.rest_client.stock.intraday.quote(symbol=symbol)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _quote_payload(response: Any) -> Any | None:
    if isinstance(response, Mapping):
        nested = response.get("data")
        if isinstance(nested, Mapping):
            return nested if response.get("success") is True else None
        return response
    nested = _field(response, "data")
    return nested if _field(response, "success") is True and nested is not None else None


def _failure(reason: Any) -> AdapterResult:
    safe_reasons = {
        "disabled",
        "missing_configuration",
        "sdk_not_installed",
        "login_failed",
        "no_stock_account",
        "quote_failed",
        "api_error",
        "timeout",
        "empty_payload",
        "missing_price",
        "invalid_timestamp",
        "conflicting_fields",
        "unsupported_schema",
        "invalid_numeric_value",
        "invalid_ohlc",
        "invalid_symbol",
        "symbol_mismatch",
    }
    return AdapterResult(
        ok=False,
        quote=None,
        reason=reason if isinstance(reason, str) and reason in safe_reasons else "quote_failed",
    )
