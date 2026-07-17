"""Select Neo-first or FinMind-only quote routing."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from typing import Any

from core.observability import log_event
from services.providers.base import QuoteProvider
from services.providers.finmind_quote_provider import FinMindQuoteProvider
from services.providers.fubon_neo_client import FubonNeoClientManager
from services.providers.fubon_neo_quote import AdapterResult
from services.providers.neo_quote_provider import NeoQuoteProvider


logger = logging.getLogger(__name__)
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


class QuoteProviderFactory:
    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        manager: FubonNeoClientManager | None = None,
        finmind_loader: Callable[[str], Any] | None = None,
    ) -> None:
        self._environ = environ if environ is not None else os.environ
        self._manager = manager
        self._finmind_loader = finmind_loader

    def create(self) -> QuoteProvider:
        fallback = FinMindQuoteProvider(self._finmind_loader)
        enabled = _enabled(self._environ.get("FUBON_NEO_ENABLED"))
        primary = NeoQuoteProvider(self._manager) if enabled else None
        return RoutedQuoteProvider(primary=primary, fallback=fallback)


class RoutedQuoteProvider:
    def __init__(self, *, primary: QuoteProvider | None, fallback: QuoteProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    def get_quote(self, symbol: str) -> AdapterResult:
        fallback_reason = None
        if self._primary is not None:
            primary = _safe_get(self._primary, symbol)
            if primary.ok and primary.quote is not None:
                _safe_event("success", "neo", None)
                return primary
            fallback_reason = primary.reason

        result = _safe_get(self._fallback, symbol)
        event_result = "success" if result.ok and result.quote is not None else "fallback"
        _safe_event(event_result, "finmind", fallback_reason)
        return result


def _safe_get(provider: QuoteProvider, symbol: str) -> AdapterResult:
    try:
        result = provider.get_quote(symbol)
        return result if isinstance(result, AdapterResult) else AdapterResult(False, None, "quote_failed")
    except Exception:
        return AdapterResult(False, None, "quote_failed")


def _enabled(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() in _TRUE_VALUES


def _safe_event(result: str, provider_used: str, fallback_reason: str | None) -> None:
    try:
        log_event(
            logger,
            "quote_provider_end",
            result=result,
            service="quote_provider",
            provider_used=provider_used,
            fallback_reason=fallback_reason,
        )
    except Exception:
        pass
