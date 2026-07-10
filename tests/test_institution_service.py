import requests

from services.institution_service import InstitutionService


EXPECTED_FALLBACK = {
    "foreign_buy_sell": None,
    "investment_buy_sell": None,
    "dealer_buy_sell": None,
    "three_major_buy_sell": None,
    "foreign_streak": None,
    "investment_streak": None,
    "dealer_streak": None,
    "available": False,
}


class FakeResponse:
    def __init__(self, payload=None, http_error=None, json_error=None):
        self.payload = payload
        self.http_error = http_error
        self.json_error = json_error

    def raise_for_status(self):
        if self.http_error:
            raise self.http_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


def _mock_response(monkeypatch, response):
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append((params["dataset"], timeout))
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("services.institution_service.requests.get", fake_get)
    return calls


def _normal_rows():
    return [
        {"date": "2026-07-10", "name": "Foreign_Investor", "buy": 100, "sell": 40},
        {"date": "2026-07-10", "name": "Investment_Trust", "buy": 50, "sell": 20},
        {"date": "2026-07-10", "name": "Dealer_self", "buy": 30, "sell": 10},
        {"date": "2026-07-10", "name": "Dealer_Hedging", "buy": 25, "sell": 15},
    ]


def test_normal_data_combines_dealers_and_three_major(monkeypatch):
    calls = _mock_response(
        monkeypatch,
        FakeResponse({"status": 200, "data": _normal_rows()}),
    )

    result = InstitutionService().get_institution("2330")

    assert result["foreign_buy_sell"] == 60
    assert result["investment_buy_sell"] == 30
    assert result["dealer_buy_sell"] == 30
    assert result["three_major_buy_sell"] == 120
    assert result["available"] is True
    assert calls == [("TaiwanStockInstitutionalInvestorsBuySell", 10)]


def test_unsorted_dates_use_latest_trading_day(monkeypatch):
    rows = _normal_rows() + [
        {"date": "2026-07-09", "name": "Foreign_Investor", "buy": 1000, "sell": 0},
        {"date": "2026-07-11", "name": "Foreign_Investor", "buy": 20, "sell": 70},
        {"date": "2026-07-11", "name": "Investment_Trust", "buy": 10, "sell": 5},
        {"date": "2026-07-11", "name": "Dealer_self", "buy": 5, "sell": 5},
    ]
    _mock_response(monkeypatch, FakeResponse({"status": 200, "data": rows}))

    result = InstitutionService().get_institution("2330")

    assert result["foreign_buy_sell"] == -50
    assert result["investment_buy_sell"] == 5
    assert result["dealer_buy_sell"] == 0
    assert result["three_major_buy_sell"] == -45


def test_none_or_blank_stock_id_returns_fallback_without_http(monkeypatch):
    monkeypatch.setattr(
        "services.institution_service.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTTP called")),
    )

    assert InstitutionService().get_institution(None) == EXPECTED_FALLBACK
    assert InstitutionService().get_institution("") == EXPECTED_FALLBACK


def test_http_500_returns_fallback(monkeypatch):
    _mock_response(
        monkeypatch,
        FakeResponse(http_error=requests.HTTPError("500 Server Error")),
    )
    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_timeout_returns_fallback(monkeypatch):
    _mock_response(monkeypatch, requests.Timeout("timeout"))
    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_unsuccessful_api_status_returns_fallback(monkeypatch):
    _mock_response(
        monkeypatch,
        FakeResponse({"status": 402, "data": _normal_rows()}),
    )
    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_empty_data_returns_fallback(monkeypatch):
    _mock_response(monkeypatch, FakeResponse({"status": 200, "data": []}))
    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_json_error_returns_fallback(monkeypatch):
    _mock_response(
        monkeypatch,
        FakeResponse(json_error=ValueError("invalid json")),
    )
    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_no_valid_buy_sell_values_is_unavailable(monkeypatch):
    rows = [
        {"date": "2026-07-10", "name": "Foreign_Investor", "buy": "nan", "sell": 1},
    ]
    _mock_response(monkeypatch, FakeResponse({"status": 200, "data": rows}))

    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_payload_non_dict_returns_fallback(monkeypatch):
    _mock_response(monkeypatch, FakeResponse([1, 2, 3]))

    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_data_non_list_returns_fallback(monkeypatch):
    _mock_response(monkeypatch, FakeResponse({"status": 200, "data": {}}))

    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_request_exception_returns_fallback(monkeypatch):
    _mock_response(monkeypatch, requests.RequestException("request failed"))

    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_invalid_and_none_dates_are_ignored(monkeypatch):
    rows = [
        {"date": None, "name": "Foreign_Investor", "buy": 999, "sell": 0},
        {"date": "", "name": "Foreign_Investor", "buy": 999, "sell": 0},
        {"date": "invalid", "name": "Foreign_Investor", "buy": 999, "sell": 0},
        {"date": "2026/07/11", "name": "Foreign_Investor", "buy": 999, "sell": 0},
        {"date": "2026-07-10", "name": "Foreign_Investor", "buy": 100, "sell": 40},
    ]
    _mock_response(monkeypatch, FakeResponse({"status": 200, "data": rows}))

    result = InstitutionService().get_institution("2330")

    assert result["foreign_buy_sell"] == 60
    assert result["three_major_buy_sell"] == 60


def test_all_invalid_dates_return_fallback(monkeypatch):
    rows = [
        {"date": None, "name": "Foreign_Investor", "buy": 100, "sell": 0},
        {"date": "invalid", "name": "Investment_Trust", "buy": 100, "sell": 0},
    ]
    _mock_response(monkeypatch, FakeResponse({"status": 200, "data": rows}))

    assert InstitutionService().get_institution("2330") == EXPECTED_FALLBACK


def test_foreign_dealer_self_is_included_once(monkeypatch):
    rows = [
        {"date": "2026-07-10", "name": "Foreign_Investor", "buy": 100, "sell": 40},
        {"date": "2026-07-10", "name": "Foreign_Dealer_Self", "buy": 30, "sell": 10},
    ]
    _mock_response(monkeypatch, FakeResponse({"status": 200, "data": rows}))

    result = InstitutionService().get_institution("2330")

    assert result["foreign_buy_sell"] == 80
    assert result["three_major_buy_sell"] == 80


def test_three_major_sums_only_available_institutions(monkeypatch):
    rows = [
        {"date": "2026-07-10", "name": "Foreign_Investor", "buy": 1000, "sell": 0},
        {"date": "2026-07-10", "name": "Dealer_self", "buy": 0, "sell": 500},
    ]
    _mock_response(monkeypatch, FakeResponse({"status": 200, "data": rows}))

    result = InstitutionService().get_institution("2330")

    assert result["foreign_buy_sell"] == 1000
    assert result["investment_buy_sell"] is None
    assert result["dealer_buy_sell"] == -500
    assert result["three_major_buy_sell"] == 500
    assert result["available"] is True
