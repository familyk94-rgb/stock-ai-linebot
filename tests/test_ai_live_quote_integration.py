import inspect
from datetime import datetime, timezone

from services import ai_service, market_service
from services.providers.quote import Quote


QUOTE_FIELDS = [
    "symbol",
    "price",
    "reference_price",
    "change",
    "change_percent",
    "volume",
    "timestamp",
    "market",
    "provider",
    "status",
    "is_realtime",
    "data_quality",
]


def _quote(provider):
    return Quote(
        provider=provider,
        symbol="2330",
        market="TWSE" if provider == "fubon_neo" else None,
        timestamp=datetime(2026, 7, 17, 6, 30, tzinfo=timezone.utc),
        status="trading" if provider == "fubon_neo" else "closed",
        price=100,
        reference=99,
        change=1,
        change_percent=1.01,
        open=99,
        high=101,
        low=98,
        volume=1000,
        is_realtime=provider == "fubon_neo",
        data_quality="realtime" if provider == "fubon_neo" else "incomplete",
    )


def test_neo_analysis_uses_exact_market_service_quote_contract():
    contract = market_service._quote_contract(_quote("fubon_neo"))
    assert list(contract) == QUOTE_FIELDS
    assert contract["provider"] == "fubon_neo"
    assert contract["reference_price"] == 99
    assert contract["is_realtime"] is True


def test_fallback_analysis_preserves_finmind_provider():
    contract = market_service._quote_contract(_quote("finmind"))
    analysis_input = ai_service._analysis_market_data(
        {"stock_id": "2330", "date": "2026-07-17", "quote": contract}
    )
    assert analysis_input["provider"] == "finmind"
    assert analysis_input["quote"] == contract


def test_ai_prompt_uses_only_provider_neutral_quote_contract():
    contract = market_service._quote_contract(_quote("fubon_neo"))
    stock = ai_service._analysis_market_data(
        {
            "stock_id": "2330",
            "stock_name": "TSMC",
            "date": "2026-07-17",
            "quote": {
                **contract,
                "lastUpdated": "forbidden",
                "total": "forbidden",
            },
        }
    )
    prompt = ai_service._build_prompt(
        stock,
        {"ai_summary": "summary", "explain": "explain"},
    )
    assert '"provider":"fubon_neo"' in prompt
    assert "lastUpdated" not in prompt
    assert '"total"' not in prompt
    assert list(stock["quote"]) == QUOTE_FIELDS


def test_ai_service_does_not_import_sdk_or_quote_providers():
    source = inspect.getsource(ai_service)
    assert "fubon_neo" not in source
    assert "NeoQuoteProvider" not in source
    assert "FinMindQuoteProvider" not in source
    assert "QuoteProviderFactory" not in source
    assert "fubon_neo.sdk" not in source


def test_analysis_input_does_not_mutate_market_data():
    market_data = {
        "stock_id": "2330",
        "date": "2026-07-17",
        "provider": "fubon_neo",
        "quote": {**market_service._quote_contract(_quote("fubon_neo"))},
    }
    before = {**market_data, "quote": dict(market_data["quote"])}
    ai_service._analysis_market_data(market_data)
    assert market_data == before
