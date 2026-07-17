from types import SimpleNamespace

import pytest

from services import market_service
from services.providers.base import QuoteProvider
from services.providers.finmind_quote_provider import FinMindQuoteProvider
from services.providers.fubon_neo_quote import AdapterResult
from services.providers.neo_quote_provider import NeoQuoteProvider
from services.providers.quote import Quote
from services.providers.quote_provider_factory import QuoteProviderFactory


def _payload(**overrides):
    value = {
        "symbol": "2330",
        "market": "TWSE",
        "timestamp": "2026-07-17T10:30:00+08:00",
        "status": "trading",
        "price": 100,
        "reference": 99,
        "open": 99,
        "high": 101,
        "low": 98,
        "volume": 1000,
        "is_realtime": True,
    }
    value.update(overrides)
    return value


def _sdk(response):
    quote = lambda **kwargs: response
    intraday = SimpleNamespace(quote=quote)
    stock = SimpleNamespace(intraday=intraday)
    rest_client = SimpleNamespace(stock=stock)
    marketdata = SimpleNamespace(rest_client=rest_client)
    return SimpleNamespace(marketdata=marketdata)


class Manager:
    def __init__(self, client=None, reason="login_failed"):
        self.client = client
        self.reason = reason

    def get_client(self):
        return self.client

    def readiness(self):
        return {"reason": self.reason}


def _finmind_stock():
    return {
        "stock_id": "2330", "date": "2026-07-17", "close": 99,
        "open": 98, "max": 100, "min": 97, "volume": 1234,
    }


def test_quote_provider_protocol_accepts_implementations():
    provider: QuoteProvider = FinMindQuoteProvider(lambda symbol: _finmind_stock())
    assert provider.get_quote("2330").ok is True


def test_neo_provider_success_unwraps_success_error_data_contract():
    provider = NeoQuoteProvider(Manager(_sdk({"success": True, "error": None, "data": _payload()})))
    result = provider.get_quote("2330")
    assert result.ok is True
    assert result.quote.provider == "fubon_neo"
    assert result.quote.price == 100


@pytest.mark.parametrize(
    ("manager", "reason"),
    [
        (Manager(None, "login_failed"), "login_failed"),
        (Manager(None, "sdk_not_installed"), "sdk_not_installed"),
    ],
)
def test_neo_login_or_sdk_failure_is_safe(manager, reason):
    assert NeoQuoteProvider(manager).get_quote("2330") == AdapterResult(False, None, reason)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ({"symbol": "2330"}, "missing_price"),
        (_payload(price=100, lastPrice=101), "conflicting_fields"),
        (_payload(timestamp="invalid"), "invalid_timestamp"),
        ({"unexpected": "value"}, "unsupported_schema"),
    ],
)
def test_neo_adapter_failures_remain_safe(data, reason):
    provider = NeoQuoteProvider(Manager(_sdk({"success": True, "error": None, "data": data})))
    result = provider.get_quote("2330")
    assert result == AdapterResult(False, None, reason)


def test_neo_quote_failure_does_not_expose_error_or_payload():
    response = {"success": False, "error": "SECRET", "data": {"secret": "VALUE"}}
    result = NeoQuoteProvider(Manager(_sdk(response))).get_quote("2330")
    assert result == AdapterResult(False, None, "quote_failed")
    assert "SECRET" not in repr(result)
    assert "VALUE" not in repr(result)


def test_finmind_provider_returns_quote_contract():
    result = FinMindQuoteProvider(lambda symbol: _finmind_stock()).get_quote("2330")
    assert result.ok is True
    assert result.quote.provider == "finmind"
    assert result.quote.symbol == "2330"
    assert result.quote.price == 99
    assert result.quote.is_realtime is False
    assert result.quote.data_quality == "incomplete"


def test_finmind_failure_is_safe():
    provider = FinMindQuoteProvider(lambda symbol: (_ for _ in ()).throw(RuntimeError("SECRET")))
    result = provider.get_quote("2330")
    assert result == AdapterResult(False, None, "quote_failed")
    assert "SECRET" not in repr(result)


def test_factory_disabled_uses_finmind_without_manager():
    calls = []
    provider = QuoteProviderFactory(
        environ={"FUBON_NEO_ENABLED": "false"},
        manager=SimpleNamespace(get_client=lambda: calls.append("neo")),
        finmind_loader=lambda symbol: _finmind_stock(),
    ).create()
    result = provider.get_quote("2330")
    assert result.quote.provider == "finmind"
    assert calls == []


def test_factory_neo_success_does_not_call_finmind():
    calls = []
    manager = Manager(_sdk({"success": True, "error": None, "data": _payload()}))
    provider = QuoteProviderFactory(
        environ={"FUBON_NEO_ENABLED": "true"},
        manager=manager,
        finmind_loader=lambda symbol: calls.append(symbol),
    ).create()
    assert provider.get_quote("2330").quote.provider == "fubon_neo"
    assert calls == []


@pytest.mark.parametrize(
    "neo_result",
    [
        AdapterResult(False, None, "login_failed"),
        AdapterResult(False, None, "missing_price"),
        AdapterResult(False, None, "invalid_timestamp"),
        AdapterResult(False, None, "conflicting_fields"),
        AdapterResult(False, None, "unsupported_schema"),
    ],
)
def test_routing_falls_back_to_finmind(monkeypatch, neo_result):
    class Neo:
        def get_quote(self, symbol):
            return neo_result

    monkeypatch.setattr(
        "services.providers.quote_provider_factory.NeoQuoteProvider",
        lambda manager: Neo(),
    )
    provider = QuoteProviderFactory(
        environ={"FUBON_NEO_ENABLED": "true"},
        manager=object(),
        finmind_loader=lambda symbol: _finmind_stock(),
    ).create()
    result = provider.get_quote("2330")
    assert result.ok is True
    assert result.quote.provider == "finmind"


def test_provider_event_contains_provider_and_safe_fallback_reason(monkeypatch):
    events = []
    monkeypatch.setattr(
        "services.providers.quote_provider_factory.log_event",
        lambda logger, event, **fields: events.append((event, fields)),
    )
    provider = QuoteProviderFactory(
        environ={"FUBON_NEO_ENABLED": "false"},
        finmind_loader=lambda symbol: _finmind_stock(),
    ).create()
    provider.get_quote("2330")
    assert events == [("quote_provider_end", {
        "result": "success", "service": "quote_provider",
        "provider_used": "finmind", "fallback_reason": None,
    })]
    assert "2330" not in repr(events)


def test_market_service_uses_quote_provider_without_changing_output(monkeypatch):
    quote = Quote(
        "fubon_neo", "2330", "TWSE", None, "trading", 100, 99, 1,
        1.01, 99, 101, 98, 1000, True, "realtime",
    )

    class Provider:
        def get_quote(self, symbol):
            return AdapterResult(True, quote, "ok")

    class Factory:
        def __init__(self, **kwargs):
            pass

        def create(self):
            return Provider()

    monkeypatch.setattr(market_service, "QuoteProviderFactory", Factory)
    monkeypatch.setattr(market_service, "get_stock_name", lambda symbol: "TSMC")
    monkeypatch.setattr(market_service, "_run_parallel_sources", lambda *a: {
        "technical": {}, "fundamental": {}, "institution": {}, "news": {},
    })
    monkeypatch.setattr(market_service, "_get_ai_core_analysis", lambda data: {})
    monkeypatch.setattr(market_service, "_get_composite_analysis", lambda *a: {})
    monkeypatch.setattr(market_service, "_update_shopkeeper_message", lambda data: None)
    monkeypatch.setattr(market_service, "_get_data_quality", lambda *a: {})
    monkeypatch.setattr(market_service, "_get_asset", lambda *a: {})
    result = market_service.get_market_info("2330")
    assert result["price"] == 100
    assert result["change"] == 1
    assert result["change_percent"] == 1.01
    assert result["volume"] == 1000


def test_market_service_provider_failure_preserves_no_price_fallback(monkeypatch):
    class Provider:
        def get_quote(self, symbol):
            return AdapterResult(False, None, "quote_failed")

    monkeypatch.setattr(
        market_service,
        "QuoteProviderFactory",
        lambda **kwargs: SimpleNamespace(create=lambda: Provider()),
    )
    monkeypatch.setattr(market_service, "get_stock_name", lambda symbol: "")
    monkeypatch.setattr(market_service, "_get_asset", lambda *a: {})
    monkeypatch.setattr(market_service, "_get_fundamental_analysis", lambda *a: {})
    monkeypatch.setattr(market_service, "_get_institution_analysis", lambda *a: {})
    monkeypatch.setattr(market_service, "_get_news_analysis", lambda *a: {})
    monkeypatch.setattr(market_service, "_get_composite_analysis", lambda *a: {})
    monkeypatch.setattr(market_service, "_get_data_quality", lambda *a: {})
    result = market_service.get_market_info("2330")
    assert result["price"] is None
    assert result["technical"] == {}
