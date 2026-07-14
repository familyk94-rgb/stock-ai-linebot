import logging
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
import requests

from core import observability
from services import fundamental_service, source_cache_service
from services.fundamental_service import FundamentalService


EXPECTED_KEYS = {
    "eps",
    "pe",
    "pb",
    "roe",
    "revenue_growth",
    "dividend_yield",
    "available",
    "applicability",
}


@pytest.fixture(autouse=True)
def _clear_fundamental_source_cache():
    source_cache_service.clear_all()
    yield
    source_cache_service.clear_all()


class FakeResponse:
    def __init__(self, data=None, payload=None, http_error=None):
        self.data = data
        self.payload = payload
        self.http_error = http_error

    def raise_for_status(self):
        if self.http_error:
            raise self.http_error
        return None

    def json(self):
        if self.payload is not None:
            return self.payload
        return {"status": 200, "data": self.data}


def _mock_finmind(monkeypatch, datasets):
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append((params["dataset"], timeout))
        value = datasets.get(params["dataset"], [])
        if isinstance(value, Exception):
            raise value
        if isinstance(value, FakeResponse):
            return value
        return FakeResponse(value)

    monkeypatch.setattr("services.fundamental_service.requests.get", fake_get)
    return calls


def test_fundamental_service_accepts_missing_stock_id_without_http(monkeypatch):
    monkeypatch.setattr(
        "services.fundamental_service.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTTP called")),
    )

    for stock_id in ("", None):
        result = FundamentalService().get_fundamental(stock_id)
        assert set(result) == EXPECTED_KEYS
        assert result["available"] is False


def test_parses_latest_per_pbr_dividend_revenue_and_eps(monkeypatch):
    calls = _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockPER": [
                {"date": "2026-01-01", "PER": "20", "PBR": "3", "dividend_yield": "2.5"},
                {"date": "2026-01-02", "PER": "18", "PBR": "2.5", "dividend_yield": "3.2"},
            ],
            "TaiwanStockMonthRevenue": [
                {"date": "2026-05-01", "revenue": 120, "revenue_year_growth": "12.5"},
            ],
            "TaiwanStockFinancialStatements": [
                {"date": "2026-03-31", "type": "IncomeAfterTaxes", "value": 999},
                {"date": "2026-03-31", "type": "EPS", "value": "5.25"},
            ],
        },
    )

    result = FundamentalService().get_fundamental("2330")

    assert result == {
        "eps": 5.25,
        "pe": 18.0,
        "pb": 2.5,
        "roe": None,
        "revenue_growth": 12.5,
        "dividend_yield": 3.2,
        "available": True,
        "applicability": "unknown",
    }
    assert sorted(calls) == sorted([
        ("TaiwanStockPER", 10),
        ("TaiwanStockMonthRevenue", 10),
        ("TaiwanStockFinancialStatements", 10),
    ])


def test_etf_skips_all_fundamental_http_and_token_access(monkeypatch):
    monkeypatch.setattr(
        "services.fundamental_service.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTTP called")),
    )
    monkeypatch.setattr(
        "services.fundamental_service.os.getenv",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("token read")),
    )
    result = FundamentalService().get_fundamental(
        "0050",
        asset={"type": "etf"},
    )
    assert result["applicability"] == "not_applicable"
    assert result["available"] is False
    assert all(result[key] is None for key in ("eps", "pe", "pb", "roe", "revenue_growth", "dividend_yield"))


def test_stock_keeps_existing_fundamental_requests(monkeypatch):
    calls = _mock_finmind(monkeypatch, {})
    result = FundamentalService().get_fundamental("2330", asset={"type": "stock"})
    assert result["applicability"] == "applicable"
    assert sorted(dataset for dataset, _ in calls) == sorted([
        "TaiwanStockPER",
        "TaiwanStockMonthRevenue",
        "TaiwanStockFinancialStatements",
    ])


def test_unknown_asset_keeps_conservative_query_flow(monkeypatch):
    calls = _mock_finmind(monkeypatch, {})
    result = FundamentalService().get_fundamental("2330", asset={"type": "unknown"})
    assert result["applicability"] == "unknown"
    assert len(calls) == 3


def test_calculates_revenue_yoy_from_same_month_last_year(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockMonthRevenue": [
                {"date": "2025-06-01", "revenue": 100, "revenue_year": 2025, "revenue_month": 5},
                {"date": "2026-06-01", "revenue": 125, "revenue_year": 2026, "revenue_month": 5},
            ],
        },
    )

    result = FundamentalService().get_fundamental("2330")

    assert result["revenue_growth"] == 25.0


def test_one_dataset_timeout_does_not_discard_other_data(monkeypatch):
    events = []
    monkeypatch.setattr(
        fundamental_service,
        "log_event",
        lambda logger, event, **fields: events.append((event, fields)),
    )
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockPER": requests.Timeout("timeout"),
            "TaiwanStockMonthRevenue": [
                {"date": "2026-05-01", "revenue_year_growth": 8},
            ],
            "TaiwanStockFinancialStatements": [
                {"date": "2026-03-31", "type": "EPS", "value": 3},
            ],
        },
    )

    result = FundamentalService().get_fundamental("2330")

    assert result["pe"] is None
    assert result["revenue_growth"] == 8.0
    assert result["eps"] == 3.0
    assert result["available"] is True
    request_events = [fields for event, fields in events if event == "finmind_request_end"]
    assert len(request_events) == 3
    timeout_event = next(
        fields
        for fields in request_events
        if fields["dataset"] == "TaiwanStockPER"
    )
    assert timeout_event["result"] == "timeout"
    assert timeout_event["error_type"] == "Timeout"
    assert isinstance(timeout_event["elapsed"], int)
    assert timeout_event["elapsed"] >= 0


def test_http_exceptions_do_not_escape(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockPER": requests.ConnectionError("offline"),
            "TaiwanStockMonthRevenue": requests.ConnectionError("offline"),
            "TaiwanStockFinancialStatements": requests.ConnectionError("offline"),
        },
    )

    result = FundamentalService().get_fundamental("2330")

    assert result["available"] is False


def test_invalid_numeric_values_become_none(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockPER": [
                {"date": "2026-01-01", "PER": "nan", "PBR": "", "dividend_yield": "inf"},
            ],
            "TaiwanStockMonthRevenue": [
                {"date": "2026-05-01", "revenue_year_growth": "-inf"},
            ],
            "TaiwanStockFinancialStatements": [
                {"date": "2026-03-31", "type": "EPS", "value": "not-a-number"},
            ],
        },
    )

    result = FundamentalService().get_fundamental("2330")

    assert all(
        result[key] is None
        for key in EXPECTED_KEYS - {"available", "applicability"}
    )
    assert result["applicability"] == "unknown"
    assert result["available"] is False


def test_api_status_failure_only_discards_that_dataset(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockPER": FakeResponse(payload={"status": 402, "data": [{"PER": 10}]}),
            "TaiwanStockFinancialStatements": [
                {"date": "2026-03-31", "type": "EPS", "value": 2},
            ],
        },
    )

    result = FundamentalService().get_fundamental("2330")

    assert result["pe"] is None
    assert result["eps"] == 2.0
    assert result["available"] is True


def test_invalid_payload_and_data_structures_are_safe(monkeypatch):
    for payload in ([1, 2], {"status": 200, "data": {}}, {"data": []}):
        _mock_finmind(
            monkeypatch,
            {"TaiwanStockPER": FakeResponse(payload=payload)},
        )
        result = FundamentalService().get_fundamental("2330")
        assert result["available"] is False


def test_empty_data_is_unavailable(monkeypatch):
    _mock_finmind(monkeypatch, {})

    assert FundamentalService().get_fundamental("2330")["available"] is False


def test_http_500_is_safe(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockPER": FakeResponse(
                http_error=requests.HTTPError("500 Server Error")
            ),
        },
    )

    assert FundamentalService().get_fundamental("2330")["available"] is False


def test_per_fields_independently_use_latest_valid_value(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockPER": [
                {"date": "2026-01-02", "PER": "nan", "PBR": 3.0, "dividend_yield": ""},
                {"date": "2026-01-03", "PER": "", "PBR": "inf", "dividend_yield": 4.0},
                {"date": "2026-01-01", "PER": 18.0, "PBR": 2.0, "dividend_yield": 2.0},
            ],
        },
    )

    result = FundamentalService().get_fundamental("2330")

    assert result["pe"] == 18.0
    assert result["pb"] == 3.0
    assert result["dividend_yield"] == 4.0


def test_revenue_yoy_zero_or_missing_denominator_is_none(monkeypatch):
    for previous_rows in (
        [{"date": "2025-06-01", "revenue": 0, "revenue_year": 2025, "revenue_month": 5}],
        [],
    ):
        rows = previous_rows + [
            {"date": "2026-06-01", "revenue": 125, "revenue_year": 2026, "revenue_month": 5},
        ]
        _mock_finmind(monkeypatch, {"TaiwanStockMonthRevenue": rows})
        assert FundamentalService().get_fundamental("2330")["revenue_growth"] is None


def test_latest_revenue_missing_is_none(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockMonthRevenue": [
                {"date": "2026-06-01", "revenue": "", "revenue_year": 2026, "revenue_month": 5},
                {"date": "2025-06-01", "revenue": 100, "revenue_year": 2025, "revenue_month": 5},
            ],
        },
    )

    assert FundamentalService().get_fundamental("2330")["revenue_growth"] is None


def test_latest_valid_eps_is_selected_from_unsorted_rows(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockFinancialStatements": [
                {"date": "2025-12-31", "type": "EPS", "value": 3},
                {"date": "2026-06-30", "type": "EPS", "value": "nan"},
                {"date": "2026-03-31", "type": "EPS", "value": 5},
                {"date": "2026-09-30", "type": "IncomeAfterTaxes", "value": 999},
            ],
        },
    )

    assert FundamentalService().get_fundamental("2330")["eps"] == 5.0


def test_missing_eps_and_non_eps_types_are_ignored(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockFinancialStatements": [
                {"date": "2026-03-31", "type": "IncomeAfterTaxes", "value": 999},
            ],
        },
    )

    assert FundamentalService().get_fundamental("2330")["eps"] is None


def test_three_datasets_overlap_and_are_called_exactly_once(monkeypatch):
    barrier = threading.Barrier(3)
    lock = threading.Lock()
    active = 0
    maximum_active = 0
    calls = []

    def fake_get(url, params, headers, timeout):
        nonlocal active, maximum_active
        with lock:
            calls.append(params["dataset"])
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            barrier.wait(timeout=1)
            time.sleep(0.02)
            return FakeResponse([])
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(fundamental_service.requests, "get", fake_get)
    FundamentalService().get_fundamental("2330")

    assert maximum_active == 3
    assert Counter(calls) == Counter(
        {
            "TaiwanStockPER": 1,
            "TaiwanStockMonthRevenue": 1,
            "TaiwanStockFinancialStatements": 1,
        }
    )


@pytest.mark.parametrize(
    "delays",
    [
        {"TaiwanStockPER": 0.01, "TaiwanStockMonthRevenue": 0.02, "TaiwanStockFinancialStatements": 0.03},
        {"TaiwanStockFinancialStatements": 0.01, "TaiwanStockPER": 0.02, "TaiwanStockMonthRevenue": 0.03},
        {"TaiwanStockMonthRevenue": 0.01, "TaiwanStockFinancialStatements": 0.02, "TaiwanStockPER": 0.03},
    ],
)
def test_completion_order_does_not_change_output(monkeypatch, delays):
    rows = {
        "TaiwanStockPER": [
            {"date": "2026-01-02", "PER": "18", "PBR": "2.5", "dividend_yield": "3.2"},
        ],
        "TaiwanStockMonthRevenue": [
            {"date": "2026-05-01", "revenue_year_growth": "12.5"},
        ],
        "TaiwanStockFinancialStatements": [
            {"date": "2026-03-31", "type": "EPS", "value": "5.25"},
        ],
    }

    def fake_get(url, params, headers, timeout):
        dataset = params["dataset"]
        time.sleep(delays[dataset])
        return FakeResponse(rows[dataset])

    monkeypatch.setattr(fundamental_service.requests, "get", fake_get)
    assert FundamentalService().get_fundamental("2330") == {
        "eps": 5.25,
        "pe": 18.0,
        "pb": 2.5,
        "roe": None,
        "revenue_growth": 12.5,
        "dividend_yield": 3.2,
        "available": True,
        "applicability": "unknown",
    }


@pytest.mark.parametrize(
    ("failed_dataset", "missing_key"),
    [
        ("TaiwanStockPER", "pe"),
        ("TaiwanStockMonthRevenue", "revenue_growth"),
        ("TaiwanStockFinancialStatements", "eps"),
    ],
)
def test_each_dataset_failure_preserves_other_results(monkeypatch, failed_dataset, missing_key):
    datasets = {
        "TaiwanStockPER": [{"date": "2026-01-02", "PER": 18}],
        "TaiwanStockMonthRevenue": [{"date": "2026-05-01", "revenue_year_growth": 12}],
        "TaiwanStockFinancialStatements": [{"date": "2026-03-31", "type": "EPS", "value": 5}],
    }
    datasets[failed_dataset] = requests.ConnectionError("offline")
    calls = _mock_finmind(monkeypatch, datasets)

    result = FundamentalService().get_fundamental("2330")

    assert result[missing_key] is None
    for key in {"pe", "revenue_growth", "eps"} - {missing_key}:
        assert result[key] is not None
    assert result["available"] is True
    assert Counter(dataset for dataset, _ in calls) == Counter(
        dataset for _, dataset, _ in fundamental_service.DATASET_REQUESTS
    )


def test_unexpected_worker_exception_is_isolated(monkeypatch):
    service = FundamentalService()
    original = service._fetch_dataset
    events = []
    monkeypatch.setattr(
        fundamental_service,
        "log_event",
        lambda logger, event, **fields: events.append((event, fields)),
    )

    def unexpected(dataset, stock_id, days):
        if dataset == "TaiwanStockMonthRevenue":
            raise RuntimeError("worker failed")
        return original(dataset, stock_id, days)

    monkeypatch.setattr(service, "_fetch_dataset", unexpected)
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockPER": [{"date": "2026-01-02", "PER": 18}],
            "TaiwanStockFinancialStatements": [
                {"date": "2026-03-31", "type": "EPS", "value": 5},
            ],
        },
    )

    result = service.get_fundamental("2330")

    assert result["pe"] == 18
    assert result["revenue_growth"] is None
    assert result["eps"] == 5
    assert result["available"] is True
    request_events = [fields for event, fields in events if event == "finmind_request_end"]
    assert len(request_events) == 3
    failed_event = next(
        fields
        for fields in request_events
        if fields["dataset"] == "TaiwanStockMonthRevenue"
    )
    assert failed_event["result"] == "error"
    assert failed_event["error_type"] == "RuntimeError"
    assert not set(failed_event) & {
        "stock_id", "user_id", "prompt", "response", "market_data",
        "token", "secret", "url", "params",
    }


def test_each_worker_uses_an_independent_context_copy(monkeypatch):
    copies = []

    class ContextCopy:
        def __init__(self):
            self.used = False

        def run(self, function, *args):
            assert self.used is False
            self.used = True
            return function(*args)

    def fake_copy_context():
        context = ContextCopy()
        copies.append(context)
        return context

    monkeypatch.setattr(fundamental_service, "copy_context", fake_copy_context)
    _mock_finmind(monkeypatch, {})
    FundamentalService().get_fundamental("2330")

    assert len(copies) == 3
    assert len({id(context) for context in copies}) == 3
    assert all(context.used for context in copies)


def test_worker_events_keep_request_id_and_are_emitted_once(monkeypatch, caplog):
    _mock_finmind(monkeypatch, {})
    token = observability.set_request_id("fundamental-concurrency")
    try:
        with caplog.at_level(logging.INFO):
            FundamentalService().get_fundamental("2330")
    finally:
        observability.clear_request_id(token)

    messages = [
        record.getMessage()
        for record in caplog.records
        if "event=finmind_request_end" in record.getMessage()
        and "service=fundamental" in record.getMessage()
    ]
    assert len(messages) == 3
    for _, dataset, _ in fundamental_service.DATASET_REQUESTS:
        matching = [message for message in messages if f"dataset={dataset}" in message]
        assert len(matching) == 1
        assert "request_id=fundamental-concurrency" in matching[0]
        assert "elapsed_ms=" in matching[0]


def test_logging_and_elapsed_failures_do_not_change_result(monkeypatch):
    _mock_finmind(
        monkeypatch,
        {
            "TaiwanStockPER": [{"date": "2026-01-02", "PER": 18}],
            "TaiwanStockMonthRevenue": [{"date": "2026-05-01", "revenue_year_growth": 12}],
            "TaiwanStockFinancialStatements": [
                {"date": "2026-03-31", "type": "EPS", "value": 5},
            ],
        },
    )
    monkeypatch.setattr(
        fundamental_service,
        "elapsed_ms",
        lambda value: (_ for _ in ()).throw(RuntimeError("elapsed failed")),
    )
    monkeypatch.setattr(
        fundamental_service,
        "log_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("logging failed")),
    )

    result = FundamentalService().get_fundamental("2330")

    assert result["pe"] == 18
    assert result["revenue_growth"] == 12
    assert result["eps"] == 5
    assert result["available"] is True


def _successful_datasets():
    return {
        "TaiwanStockPER": [
            {"date": "2026-01-02", "PER": 18, "PBR": 2.5, "dividend_yield": 3.2}
        ],
        "TaiwanStockMonthRevenue": [
            {"date": "2026-05-01", "revenue_year_growth": 12}
        ],
        "TaiwanStockFinancialStatements": [
            {"date": "2026-03-31", "type": "EPS", "value": 5}
        ],
    }


def _dataset_key(dataset, stock_id="2330", date_range=None):
    days = next(
        days
        for _, configured_dataset, days in fundamental_service.DATASET_REQUESTS
        if configured_dataset == dataset
    )
    start_date, end_date = date_range or fundamental_service._request_date_range(days)
    return (
        "fundamental",
        fundamental_service.FUNDAMENTAL_CACHE_SCHEMA_VERSION,
        dataset,
        stock_id,
        start_date,
        end_date,
    )


def test_dataset_cache_cold_calls_each_once_and_warm_calls_zero(monkeypatch):
    calls = _mock_finmind(monkeypatch, _successful_datasets())
    cold = FundamentalService().get_fundamental("2330")
    warm = FundamentalService().get_fundamental("2330")
    assert cold == warm
    assert list(cold) == list(warm)
    assert Counter(dataset for dataset, _ in calls) == {
        dataset: 1 for _, dataset, _ in fundamental_service.DATASET_REQUESTS
    }


def test_partial_hit_only_calls_cleared_dataset(monkeypatch):
    calls = _mock_finmind(monkeypatch, _successful_datasets())
    FundamentalService().get_fundamental("2330")
    calls.clear()
    source_cache_service.clear_key(_dataset_key("TaiwanStockMonthRevenue"))
    result = FundamentalService().get_fundamental("2330")
    assert result["revenue_growth"] == 12
    assert calls == [("TaiwanStockMonthRevenue", 10)]


def test_expired_dataset_only_refetches_that_dataset(monkeypatch):
    class Clock:
        value = 100.0

        def __call__(self):
            return self.value

    clock = Clock()
    cache = source_cache_service.SourceCacheService(clock=clock)
    monkeypatch.setattr(source_cache_service, "_DEFAULT_CACHE", cache)
    calls = _mock_finmind(monkeypatch, _successful_datasets())
    FundamentalService().get_fundamental("2330")
    calls.clear()
    per_key = _dataset_key("TaiwanStockPER")
    cache._entries[per_key].expires_at = clock.value
    FundamentalService().get_fundamental("2330")
    assert calls == [("TaiwanStockPER", 10)]


@pytest.mark.parametrize(
    "failure",
    [
        [],
        requests.Timeout("timeout"),
        requests.ConnectionError("offline"),
        FakeResponse(http_error=requests.HTTPError("500")),
        FakeResponse(payload={"status": 500, "data": [{"PER": 1}]}),
        FakeResponse(payload={"status": 200, "data": {}}),
        FakeResponse(payload=[{"PER": 1}]),
    ],
    ids=["empty", "timeout", "request", "http", "api", "data", "payload"],
)
def test_failure_and_empty_results_are_not_cached(monkeypatch, failure):
    calls = _mock_finmind(monkeypatch, {"TaiwanStockPER": failure})
    service = FundamentalService()
    assert service._fetch_dataset("TaiwanStockPER", "2330", 45) == []
    assert service._fetch_dataset("TaiwanStockPER", "2330", 45) == []
    assert calls == [("TaiwanStockPER", 10), ("TaiwanStockPER", 10)]


def test_unexpected_exception_is_not_cached(monkeypatch):
    calls = []

    def unexpected(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("unexpected")

    monkeypatch.setattr(fundamental_service.requests, "get", unexpected)
    service = FundamentalService()
    assert service._fetch_dataset("TaiwanStockPER", "2330", 45) == []
    assert service._fetch_dataset("TaiwanStockPER", "2330", 45) == []
    assert calls == [1, 1]


def test_etf_not_applicable_never_touches_dataset_cache_or_http(monkeypatch):
    monkeypatch.setattr(
        fundamental_service,
        "get_or_load",
        lambda **kwargs: pytest.fail("cache should not be used"),
    )
    monkeypatch.setattr(
        fundamental_service.requests,
        "get",
        lambda *args, **kwargs: pytest.fail("HTTP should not be used"),
    )
    result = FundamentalService().get_fundamental("0050", asset={"type": "etf"})
    assert result["applicability"] == "not_applicable"
    assert result["available"] is False


def test_same_stock_concurrent_requests_call_each_dataset_once(monkeypatch):
    calls = []
    lock = threading.Lock()

    def fake_get(url, params, headers, timeout):
        with lock:
            calls.append(params["dataset"])
        time.sleep(0.05)
        return FakeResponse(_successful_datasets()[params["dataset"]])

    monkeypatch.setattr(fundamental_service.requests, "get", fake_get)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: FundamentalService().get_fundamental("2330"),
                range(2),
            )
        )
    assert results[0] == results[1]
    assert Counter(calls) == {
        dataset: 1 for _, dataset, _ in fundamental_service.DATASET_REQUESTS
    }


def test_different_stocks_are_not_serialized_by_cache(monkeypatch):
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active_stocks = set()
    maximum_stocks = 0

    def fake_get(url, params, headers, timeout):
        nonlocal maximum_stocks
        if params["dataset"] == "TaiwanStockPER":
            with lock:
                active_stocks.add(params["data_id"])
                maximum_stocks = max(maximum_stocks, len(active_stocks))
            barrier.wait(timeout=2)
        try:
            return FakeResponse(_successful_datasets()[params["dataset"]])
        finally:
            if params["dataset"] == "TaiwanStockPER":
                with lock:
                    active_stocks.discard(params["data_id"])

    monkeypatch.setattr(fundamental_service.requests, "get", fake_get)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda stock_id: FundamentalService().get_fundamental(stock_id),
                ("2330", "2317"),
            )
        )
    assert all(result["available"] is True for result in results)
    assert maximum_stocks == 2


def test_cache_hit_has_no_external_event_and_uses_current_request_id(
    monkeypatch, caplog
):
    _mock_finmind(monkeypatch, _successful_datasets())
    first_token = observability.set_request_id("cold-request")
    try:
        FundamentalService().get_fundamental("2330")
    finally:
        observability.clear_request_id(first_token)

    caplog.clear()
    second_token = observability.set_request_id("warm-request")
    try:
        with caplog.at_level(logging.INFO):
            FundamentalService().get_fundamental("2330")
    finally:
        observability.clear_request_id(second_token)

    messages = [record.getMessage() for record in caplog.records]
    cache_hits = [message for message in messages if "source_cache_lookup_end" in message]
    assert len(cache_hits) == 3
    assert all("result=cache_hit" in message for message in cache_hits)
    assert all("request_id=warm-request" in message for message in cache_hits)
    assert not any("event=finmind_request_end" in message for message in messages)


def test_single_flight_follower_has_no_duplicate_external_event(monkeypatch, caplog):
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append(params["dataset"])
        time.sleep(0.04)
        return FakeResponse(_successful_datasets()[params["dataset"]])

    monkeypatch.setattr(fundamental_service.requests, "get", fake_get)
    with caplog.at_level(logging.INFO):
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(
                executor.map(
                    lambda _: FundamentalService().get_fundamental("2330"),
                    range(2),
                )
            )
    request_events = [
        record.getMessage()
        for record in caplog.records
        if "event=finmind_request_end" in record.getMessage()
        and "service=fundamental" in record.getMessage()
    ]
    assert len(request_events) == 3
    assert Counter(calls) == {
        dataset: 1 for _, dataset, _ in fundamental_service.DATASET_REQUESTS
    }


def test_cache_range_changes_across_taipei_midnight(monkeypatch):
    today = {"value": date(2026, 7, 14)}
    monkeypatch.setattr(
        fundamental_service, "_taipei_today", lambda: today["value"]
    )
    calls = _mock_finmind(monkeypatch, _successful_datasets())
    FundamentalService().get_fundamental("2330")
    FundamentalService().get_fundamental("2330")
    assert len(calls) == 3
    today["value"] = date(2026, 7, 15)
    FundamentalService().get_fundamental("2330")
    assert len(calls) == 6


@pytest.mark.parametrize(
    "ranges",
    [
        [("2026-06-01", "2026-07-15"), ("2026-06-01", "2026-07-16")],
        [("2026-06-01", "2026-07-15"), ("2026-06-02", "2026-07-15")],
    ],
    ids=["end-changed", "start-changed"],
)
def test_each_request_range_component_participates_in_key(monkeypatch, ranges):
    current = {"value": ranges[0]}
    monkeypatch.setattr(
        fundamental_service,
        "_request_date_range",
        lambda days: current["value"],
    )
    calls = _mock_finmind(
        monkeypatch,
        {"TaiwanStockPER": _successful_datasets()["TaiwanStockPER"]},
    )
    service = FundamentalService()
    service._fetch_dataset("TaiwanStockPER", "2330", 45)
    current["value"] = ranges[1]
    service._fetch_dataset("TaiwanStockPER", "2330", 45)
    assert calls == [("TaiwanStockPER", 10), ("TaiwanStockPER", 10)]


def test_cache_key_and_http_params_share_exact_request_range(monkeypatch):
    expected_range = ("2026-06-01", "2026-07-15")
    monkeypatch.setattr(
        fundamental_service,
        "_request_date_range",
        lambda days: expected_range,
    )
    seen_params = []

    def fake_get(url, params, headers, timeout):
        seen_params.append(dict(params))
        return FakeResponse(_successful_datasets()[params["dataset"]])

    monkeypatch.setattr(fundamental_service.requests, "get", fake_get)
    FundamentalService()._fetch_dataset("TaiwanStockPER", "2330", 45)
    assert seen_params[0]["start_date"] == expected_range[0]
    assert seen_params[0]["end_date"] == expected_range[1]
    key = _dataset_key("TaiwanStockPER", date_range=expected_range)
    assert key in source_cache_service._DEFAULT_CACHE._entries


@pytest.mark.parametrize(
    ("dataset", "valid_row", "invalid_rows"),
    [
        (
            "TaiwanStockPER",
            {"date": "2026-07-14", "PER": 18},
            [
                None,
                1,
                {},
                {"PER": 18},
                {"date": "2026-07-14"},
                {"date": "2026-07-14", "PER": []},
                {"date": "2026-07-14", "PER": True},
            ],
        ),
        (
            "TaiwanStockMonthRevenue",
            {"date": "2026-07-01", "revenue_year_growth": 12},
            [
                None,
                1,
                {},
                {"revenue_year_growth": 12},
                {"date": "2026-07-01"},
                {"date": "2026-07-01", "revenue": []},
                {"date": "2026-07-01", "revenue_year_growth": True},
            ],
        ),
        (
            "TaiwanStockFinancialStatements",
            {"date": "2026-03-31", "type": "EPS", "value": 5},
            [
                None,
                1,
                {},
                {"type": "EPS", "value": 5},
                {"date": "2026-03-31", "type": "EPS"},
                {"date": "2026-03-31", "type": [], "value": 5},
                {"date": "2026-03-31", "type": "EPS", "value": []},
                {"date": "2026-03-31", "type": "EPS", "value": True},
            ],
        ),
    ],
)
def test_dataset_specific_cache_eligibility_rejects_malformed_rows(
    dataset, valid_row, invalid_rows
):
    assert fundamental_service._cacheable_rows(dataset, [valid_row]) is True
    assert fundamental_service._cacheable_rows(dataset, [valid_row, dict(valid_row)]) is True
    for invalid in invalid_rows:
        assert fundamental_service._cacheable_rows(dataset, [invalid]) is False
        assert fundamental_service._cacheable_rows(dataset, [valid_row, invalid]) is False


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"revenue_year": True, "revenue_month": 5},
        {"revenue_year": False, "revenue_month": 5},
        {"revenue_year": 2026, "revenue_month": True},
        {"revenue_year": 2026, "revenue_month": False},
        {"revenue_year": True, "revenue_month": True},
    ],
)
def test_month_revenue_cache_eligibility_rejects_bool_year_or_month(
    invalid_fields,
):
    row = {"date": "2026-07-01", "revenue": 100, **invalid_fields}
    assert fundamental_service._cacheable_rows(
        "TaiwanStockMonthRevenue", [row]
    ) is False


@pytest.mark.parametrize(
    ("year", "month"),
    [
        (2026, 7),
        ("2026", "7"),
    ],
)
def test_month_revenue_cache_eligibility_keeps_valid_year_month_contract(
    year, month
):
    row = {
        "date": "2026-07-01",
        "revenue": 100,
        "revenue_year": year,
        "revenue_month": month,
    }
    assert fundamental_service._cacheable_rows(
        "TaiwanStockMonthRevenue", [row]
    ) is True


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"revenue_year": True, "revenue_month": 5},
        {"revenue_year": False, "revenue_month": 5},
        {"revenue_year": 2026, "revenue_month": True},
        {"revenue_year": 2026, "revenue_month": False},
        {"revenue_year": True, "revenue_month": True},
    ],
)
def test_month_revenue_bool_year_or_month_follows_parser_flow_without_caching(
    monkeypatch, invalid_fields
):
    row = {"date": "2026-07-01", "revenue": 100, **invalid_fields}
    calls = _mock_finmind(monkeypatch, {"TaiwanStockMonthRevenue": [row]})
    service = FundamentalService()

    first = service._fetch_dataset("TaiwanStockMonthRevenue", "2330", 400)
    second = service._fetch_dataset("TaiwanStockMonthRevenue", "2330", 400)

    assert first == second == [row]
    assert fundamental_service._parse_revenue_growth(first) is None
    assert calls == [
        ("TaiwanStockMonthRevenue", 10),
        ("TaiwanStockMonthRevenue", 10),
    ]


@pytest.mark.parametrize(
    ("dataset", "valid_row", "invalid_row"),
    [
        ("TaiwanStockPER", {"date": "2026-07-14", "PER": 18}, {}),
        (
            "TaiwanStockMonthRevenue",
            {"date": "2026-07-01", "revenue_year_growth": 12},
            None,
        ),
        (
            "TaiwanStockFinancialStatements",
            {"date": "2026-03-31", "type": "EPS", "value": 5},
            1,
        ),
    ],
)
def test_mixed_malformed_api_rows_are_returned_by_existing_parser_flow_but_not_cached(
    monkeypatch, dataset, valid_row, invalid_row
):
    calls = _mock_finmind(monkeypatch, {dataset: [valid_row, invalid_row]})
    service = FundamentalService()
    _, _, days = next(item for item in fundamental_service.DATASET_REQUESTS if item[1] == dataset)
    first = service._fetch_dataset(dataset, "2330", days)
    second = service._fetch_dataset(dataset, "2330", days)
    expected = (
        [valid_row, invalid_row]
        if isinstance(invalid_row, dict)
        else [valid_row]
    )
    assert first == second == expected
    assert calls == [(dataset, 10), (dataset, 10)]


def test_leader_and_follower_events_keep_distinct_request_ids(monkeypatch, caplog):
    loader_started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append(params["dataset"])
        loader_started.set()
        release.wait(timeout=2)
        return FakeResponse(_successful_datasets()[params["dataset"]])

    monkeypatch.setattr(fundamental_service.requests, "get", fake_get)

    def invoke(request_id):
        token = observability.set_request_id(request_id)
        try:
            return FundamentalService()._fetch_dataset(
                "TaiwanStockPER", "2330", 45
            )
        finally:
            observability.clear_request_id(token)

    with caplog.at_level(logging.INFO):
        with ThreadPoolExecutor(max_workers=2) as executor:
            leader = executor.submit(invoke, "leader-request")
            assert loader_started.wait(timeout=2)
            follower = executor.submit(invoke, "follower-request")
            time.sleep(0.02)
            release.set()
            assert leader.result() == follower.result()

    messages = [record.getMessage() for record in caplog.records]
    request_events = [message for message in messages if "finmind_request_end" in message]
    leader_cache_events = [
        message
        for message in messages
        if "source_cache_" in message and "request_id=leader-request" in message
    ]
    follower_events = [
        message
        for message in messages
        if "source_cache_lookup_end" in message
        and "request_id=follower-request" in message
    ]
    assert len(calls) == 1
    assert len(request_events) == 1
    assert "request_id=leader-request" in request_events[0]
    assert leader_cache_events
    assert len(follower_events) == 1
    assert "cache_status=loader_wait" in follower_events[0]
    assert all("2330" not in message for message in leader_cache_events + follower_events)


def test_copy_failure_follower_does_not_emit_fake_external_request(
    monkeypatch, caplog
):
    loader_started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append(params["dataset"])
        loader_started.set()
        release.wait(timeout=2)
        return FakeResponse(_successful_datasets()[params["dataset"]])

    monkeypatch.setattr(fundamental_service.requests, "get", fake_get)
    monkeypatch.setattr(
        source_cache_service,
        "deepcopy",
        lambda value: (_ for _ in ()).throw(RuntimeError("copy")),
    )
    service = FundamentalService()
    with caplog.at_level(logging.INFO):
        with ThreadPoolExecutor(max_workers=2) as executor:
            leader = executor.submit(
                service._fetch_dataset, "TaiwanStockPER", "2330", 45
            )
            assert loader_started.wait(timeout=2)
            follower = executor.submit(
                service._fetch_dataset, "TaiwanStockPER", "2330", 45
            )
            time.sleep(0.02)
            release.set()
            assert leader.result() == _successful_datasets()["TaiwanStockPER"]
            assert follower.result() == []
    request_events = [
        record.getMessage()
        for record in caplog.records
        if "event=finmind_request_end" in record.getMessage()
    ]
    follower_errors = [
        record.getMessage()
        for record in caplog.records
        if "event=source_cache_lookup_end" in record.getMessage()
        and "error_type=CacheCopyError" in record.getMessage()
    ]
    assert calls == ["TaiwanStockPER"]
    assert len(request_events) == 1
    assert len(follower_errors) == 1
