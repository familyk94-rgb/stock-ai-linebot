import json
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.providers.fubon_neo_quote import AdapterResult, adapt_quote
from services.providers.quote import DATA_QUALITIES, QUOTE_STATUSES, Quote


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "fubon_neo" / "quote_contract_cases.json"
PRODUCTION_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "fubon_neo" / "production_quote_sample.json"
)
QUOTE_FIELDS = [
    "provider", "symbol", "market", "timestamp", "status", "price",
    "reference", "change", "change_percent", "open", "high", "low",
    "volume", "is_realtime", "data_quality",
]


@pytest.fixture(scope="module")
def cases():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _valid(**overrides):
    value = {
        "symbol": "2330",
        "market": "TWSE",
        "timestamp": "2026-07-17T10:30:00+08:00",
        "status": "trading",
        "price": 100,
        "reference": 98,
        "open": 99,
        "high": 101,
        "low": 97,
        "volume": 1000,
        "is_realtime": True,
    }
    value.update(overrides)
    return value


def test_quote_contract_is_exact_immutable_and_slotted():
    result = adapt_quote(_valid())
    assert [field.name for field in fields(Quote)] == QUOTE_FIELDS
    with pytest.raises(FrozenInstanceError):
        result.quote.price = 1
    assert not hasattr(result.quote, "__dict__")


def test_quote_serializes_datetime_to_iso_without_mutation():
    quote = adapt_quote(_valid()).quote
    before = quote.timestamp
    value = quote.to_dict()
    assert list(value) == QUOTE_FIELDS
    assert value["timestamp"] == "2026-07-17T10:30:00+08:00"
    assert quote.timestamp is before
    assert json.loads(json.dumps(value))["symbol"] == "2330"


def test_adapter_result_serialization_is_safe():
    result = adapt_quote(_valid())
    value = result.to_dict()
    assert value["ok"] is True
    assert value["reason"] == "ok"
    assert isinstance(value["quote"], dict)


def test_adapter_module_does_not_import_or_create_fubon_sdk():
    import services.providers.fubon_neo_quote as module
    assert "fubon_neo" not in module.__dict__
    assert "FubonSDK" not in module.__dict__


def test_dict_fixture_maps_twse_realtime(cases):
    result = adapt_quote(cases["twse_realtime"], expected_symbol="2330")
    assert result.ok is True
    assert result.quote.provider == "fubon_neo"
    assert result.quote.market == "TWSE"
    assert result.quote.price == 1000.0
    assert result.quote.change == 10
    assert result.quote.change_percent == pytest.approx(10 / 990 * 100)
    assert result.quote.is_realtime is True
    assert result.quote.data_quality == "realtime"


def test_attribute_fixture_maps_successfully():
    result = adapt_quote(SimpleNamespace(**_valid()))
    assert result.ok is True
    assert result.quote.symbol == "2330"


def test_tpex_alias_fixture_and_market_normalization(cases):
    result = adapt_quote(cases["tpex_realtime"])
    assert result.ok is True
    assert result.quote.symbol == "6488"
    assert result.quote.market == "TPEx"
    assert result.quote.timestamp.tzinfo is not None


def test_expected_symbol_must_match_exactly():
    assert adapt_quote(_valid(), expected_symbol="2330").ok is True
    result = adapt_quote(_valid(), expected_symbol="2317")
    assert result == AdapterResult(False, None, "symbol_mismatch")


@pytest.mark.parametrize("symbol", [None, "", "  ", True, 2330, [], {}])
def test_invalid_payload_symbol_fails_closed(symbol):
    result = adapt_quote(_valid(symbol=symbol))
    assert result.reason == "invalid_symbol"
    assert result.quote is None


@pytest.mark.parametrize("expected", ["", " ", True, 2330, [], {}])
def test_invalid_expected_symbol_fails_closed(expected):
    assert adapt_quote(_valid(), expected_symbol=expected).reason == "invalid_symbol"


@pytest.mark.parametrize("value", [None, "", "--"])
def test_missing_price_fails_closed(value):
    assert adapt_quote(_valid(price=value)).reason == "missing_price"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("101.25", 101.25), (Decimal("101.25"), 101.25), (101, 101.0), (101.25, 101.25)],
)
def test_supported_price_values_convert_to_float(value, expected):
    result = adapt_quote(_valid(price=value))
    assert result.quote.price == expected
    assert isinstance(result.quote.price, float)


@pytest.mark.parametrize(
    "value", [True, False, float("nan"), float("inf"), float("-inf"), -1, [], {}, object()]
)
def test_invalid_price_values_fail_closed(value):
    assert adapt_quote(_valid(price=value)).reason == "invalid_numeric_value"


@pytest.mark.parametrize(
    "value", [True, False, float("nan"), float("inf"), -1, [], {}, object()]
)
def test_invalid_volume_values_fail_closed(value):
    assert adapt_quote(_valid(volume=value)).reason == "invalid_numeric_value"


def test_volume_preserves_integer_or_finite_fraction():
    assert adapt_quote(_valid(volume="1000")).quote.volume == 1000
    assert adapt_quote(_valid(volume="1000.5")).quote.volume == 1000.5


def test_invalid_ohlc_fails_closed():
    result = adapt_quote(_valid(high=90, low=100))
    assert result.reason == "invalid_ohlc"


def test_missing_ohlc_returns_incomplete_quote():
    result = adapt_quote(_valid(open=None, high=None, low=None))
    assert result.ok is True
    assert result.quote.data_quality == "incomplete"
    assert result.quote.is_realtime is False


@pytest.mark.parametrize("missing", ["reference", "open", "high", "low", "volume"])
def test_incomplete_quote_is_never_realtime(missing):
    result = adapt_quote(_valid(**{missing: None}))
    assert result.ok is True
    assert result.quote.data_quality == "incomplete"
    assert result.quote.is_realtime is False


def test_only_complete_realtime_quote_is_realtime():
    result = adapt_quote(_valid())
    assert result.ok is True
    assert result.quote.data_quality == "realtime"
    assert result.quote.is_realtime is True


def test_explicit_change_and_percent_are_percentage_points():
    result = adapt_quote(_valid(change=-2, change_percent=-1.25))
    assert result.quote.change == -2
    assert result.quote.change_percent == -1.25


def test_missing_change_and_percent_are_derived():
    result = adapt_quote(_valid(price=105, reference=100, change=None, change_percent=None))
    assert result.quote.change == 5
    assert result.quote.change_percent == 5


def test_reference_zero_does_not_derive_change_percent():
    result = adapt_quote(_valid(price=10, reference=0, change=None, change_percent=None))
    assert result.ok is True
    assert result.quote.change == 10
    assert result.quote.change_percent is None
    assert result.quote.data_quality == "incomplete"


def test_timezone_aware_datetime_is_preserved():
    value = datetime(2026, 7, 17, 10, tzinfo=timezone(timedelta(hours=8)))
    assert adapt_quote(_valid(timestamp=value)).quote.timestamp is value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-07-17T02:30:00Z", datetime(2026, 7, 17, 2, 30, tzinfo=timezone.utc)),
        (1784255400, datetime.fromtimestamp(1784255400, tz=timezone.utc)),
        (1784255400000, datetime.fromtimestamp(1784255400, tz=timezone.utc)),
    ],
)
def test_supported_timestamps(value, expected):
    assert adapt_quote(_valid(timestamp=value)).quote.timestamp == expected


@pytest.mark.parametrize(
    "value",
    [1784255400, 1784255400000, 1784255400000000],
)
def test_unix_timestamp_seconds_milliseconds_and_microseconds(value):
    expected = datetime.fromtimestamp(1784255400, tz=timezone.utc)
    assert adapt_quote(_valid(timestamp=value)).quote.timestamp == expected


@pytest.mark.parametrize("value", [10**40, -(10**40), float("nan"), float("inf")])
def test_invalid_timestamp_units_fail_safely(value):
    assert adapt_quote(_valid(timestamp=value)).reason == "invalid_timestamp"


@pytest.mark.parametrize(
    "value",
    [
        "1999-12-31T23:59:59Z",
        "2100-01-01T00:00:01Z",
        datetime(1999, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        datetime(2100, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        -10**30,
        10**30,
    ],
)
def test_timestamp_outside_fixed_range_is_rejected(value):
    assert adapt_quote(_valid(timestamp=value)).reason == "invalid_timestamp"


def test_timestamp_fixed_range_boundaries_are_allowed():
    assert adapt_quote(_valid(timestamp="2000-01-01T00:00:00Z")).ok is True
    assert adapt_quote(_valid(timestamp="2100-01-01T00:00:00Z")).ok is True


@pytest.mark.parametrize(
    "value", ["invalid", "2026-07-17T10:00:00", datetime(2026, 7, 17), True, [], {}]
)
def test_invalid_or_naive_timestamp_fails_closed(value):
    assert adapt_quote(_valid(timestamp=value)).reason == "invalid_timestamp"


def test_missing_timestamp_is_incomplete_and_not_realtime():
    result = adapt_quote(_valid(timestamp=None))
    assert result.ok is True
    assert result.quote.timestamp is None
    assert result.quote.is_realtime is False
    assert result.quote.data_quality == "incomplete"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("TWSE", "TWSE"), ("tse", "TWSE"), ("OTC", "TPEx"), ("tpex", "TPEx")],
)
def test_known_market_normalization(value, expected):
    assert adapt_quote(_valid(market=value)).quote.market == expected


@pytest.mark.parametrize("value", [None, "unknown", 1, True])
def test_unknown_market_is_none(value):
    assert adapt_quote(_valid(market=value)).quote.market is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("trading", "trading"), ("open", "trading"),
        ("pre_open", "pre_open"), ("closed", "closed"),
        ("halted", "halted"), ("delayed", "delayed"),
        ("other", "unknown"), (None, "unknown"),
    ],
)
def test_status_normalization(value, expected):
    assert adapt_quote(_valid(status=value)).quote.status == expected
    assert expected in QUOTE_STATUSES


def test_realtime_requires_explicit_true_timestamp_and_trading_status():
    assert adapt_quote(_valid(is_realtime=True)).quote.is_realtime is True
    assert adapt_quote(_valid(is_realtime="true")).quote.is_realtime is False
    assert adapt_quote(_valid(status="closed", is_realtime=True)).quote.is_realtime is False
    assert adapt_quote(_valid(timestamp=None, is_realtime=True)).quote.is_realtime is False


def test_delayed_and_closed_fixtures_are_not_realtime(cases):
    for name in ("delayed", "closed"):
        quote = adapt_quote(cases[name]).quote
        assert quote.is_realtime is False
        assert quote.data_quality == "delayed"


def test_incomplete_fixture_is_not_falsely_realtime(cases):
    quote = adapt_quote(cases["incomplete"]).quote
    assert quote.data_quality == "incomplete"
    assert quote.is_realtime is False
    assert quote.data_quality in DATA_QUALITIES


def test_production_fixture_maps_nested_volume_microseconds_and_closed_status():
    payload = json.loads(PRODUCTION_FIXTURE_PATH.read_text(encoding="utf-8"))
    result = adapt_quote(payload, expected_symbol="2330")
    assert result.ok is True
    quote = result.quote
    assert quote.symbol == payload["symbol"]
    assert quote.price == float(payload["lastPrice"])
    assert quote.reference == float(payload["referencePrice"])
    assert quote.open == float(payload["openPrice"])
    assert quote.high == float(payload["highPrice"])
    assert quote.low == float(payload["lowPrice"])
    assert quote.volume == payload["total"]["tradeVolume"]
    assert quote.timestamp == datetime.fromtimestamp(
        payload["lastUpdated"] / 1_000_000,
        tz=timezone.utc,
    )
    assert payload["exchange"] == "TWSE"
    assert quote.market == "TWSE"
    assert quote.status == "closed"
    assert quote.is_realtime is False
    assert quote.data_quality == "delayed"
    assert quote.data_quality in DATA_QUALITIES


@pytest.mark.parametrize(
    "total",
    [None, 1, "invalid", {}, {"tradeVolume": None}, {"tradeVolume": "invalid"}],
)
def test_invalid_nested_total_volume_degrades_safely(total):
    payload = _valid()
    payload.pop("volume")
    payload["total"] = total
    result = adapt_quote(payload)
    assert result.ok is True
    assert result.quote.volume is None
    assert result.quote.data_quality == "incomplete"


@pytest.mark.parametrize("payload", [None, {}])
def test_empty_payload(payload):
    assert adapt_quote(payload) == AdapterResult(False, None, "empty_payload")


def test_unsupported_schema_fixture(cases):
    assert adapt_quote(cases["malformed"]).reason == "unsupported_schema"


@pytest.mark.parametrize(
    "payload",
    [
        _valid(price=100, lastPrice=100),
        _valid(price="100", lastPrice=100),
    ],
)
def test_equivalent_alias_values_are_accepted(payload):
    result = adapt_quote(payload)
    assert result.ok is True
    assert result.quote.price == 100


def test_conflicting_price_aliases_fail_closed():
    result = adapt_quote(_valid(price=100, lastPrice=101))
    assert result == AdapterResult(False, None, "conflicting_fields")


def test_conflicting_symbol_aliases_fail_closed():
    result = adapt_quote(_valid(symbol="2330", stockNo="2317"))
    assert result == AdapterResult(False, None, "conflicting_fields")


def test_conflicting_timestamp_aliases_fail_closed():
    result = adapt_quote(
        _valid(
            timestamp="2026-07-17T10:30:00+08:00",
            time="2026-07-17T10:31:00+08:00",
        )
    )
    assert result == AdapterResult(False, None, "conflicting_fields")


def test_conflict_result_does_not_contain_original_payload():
    payload = _valid(price=100, lastPrice=101, symbol="SECRET-SYMBOL")
    result = adapt_quote(payload)
    assert result.reason == "conflicting_fields"
    assert result.quote is None
    assert "SECRET-SYMBOL" not in repr(result)
    assert "lastPrice" not in repr(result)


def test_adapter_failure_does_not_include_payload_or_secrets():
    payload = {"symbol": "SECRET-ACCOUNT", "price": "SECRET-PASSWORD"}
    result = adapt_quote(payload, expected_symbol="2330")
    text = repr(result)
    assert result.ok is False
    assert "SECRET-ACCOUNT" not in text
    assert "SECRET-PASSWORD" not in text
    assert result.to_dict() == {"ok": False, "quote": None, "reason": "symbol_mismatch"}


def test_quote_repr_contains_no_sdk_object():
    result = adapt_quote(_valid())
    assert "SimpleNamespace" not in repr(result.quote)
    assert "FubonSDK" not in repr(result.quote)
