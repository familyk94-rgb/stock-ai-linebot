import requests

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
    assert calls == [
        ("TaiwanStockPER", 10),
        ("TaiwanStockMonthRevenue", 10),
        ("TaiwanStockFinancialStatements", 10),
    ]


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
    assert [dataset for dataset, _ in calls] == [
        "TaiwanStockPER",
        "TaiwanStockMonthRevenue",
        "TaiwanStockFinancialStatements",
    ]


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
