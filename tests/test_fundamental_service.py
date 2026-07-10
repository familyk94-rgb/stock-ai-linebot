from services.fundamental_service import FundamentalService


EXPECTED_KEYS = {
    "eps",
    "pe",
    "pb",
    "roe",
    "revenue_growth",
    "available",
}


def test_fundamental_service_returns_fixed_structure():
    result = FundamentalService().get_fundamental("2330")

    assert set(result) == EXPECTED_KEYS
    assert result == {
        "eps": None,
        "pe": None,
        "pb": None,
        "roe": None,
        "revenue_growth": None,
        "available": False,
    }


def test_fundamental_service_is_currently_unavailable():
    result = FundamentalService().get_fundamental("2330")

    assert result["available"] is False


def test_fundamental_service_accepts_empty_stock_id():
    result = FundamentalService().get_fundamental("")

    assert set(result) == EXPECTED_KEYS
    assert result["available"] is False


def test_fundamental_service_accepts_none_stock_id():
    result = FundamentalService().get_fundamental(None)

    assert set(result) == EXPECTED_KEYS
    assert result["available"] is False
