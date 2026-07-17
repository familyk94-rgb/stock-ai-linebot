"""Provider-neutral quote provider interface."""

from __future__ import annotations

from typing import Protocol

from services.providers.fubon_neo_quote import AdapterResult


class QuoteProvider(Protocol):
    def get_quote(self, symbol: str) -> AdapterResult:
        """Return a provider-neutral quote result."""
        ...
