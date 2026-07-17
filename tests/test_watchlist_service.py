from copy import deepcopy

import pytest

from services.repositories.watchlist_repository import WatchlistRepository
from services.watchlist_service import WatchlistService


def _service(tmp_path):
    return WatchlistService(WatchlistRepository(tmp_path / "watchlist.db"))


def test_service_add_exists_and_list_stock(tmp_path):
    service = _service(tmp_path)

    assert service.add_stock(" user-1 ", " 2330 ", " 台積電 ") is True
    assert service.exists("user-1", "2330") is True
    stocks = service.list_stocks("user-1")

    assert len(stocks) == 1
    assert stocks[0]["line_user_id"] == "user-1"
    assert stocks[0]["stock_id"] == "2330"
    assert stocks[0]["stock_name"] == "台積電"
    assert stocks[0]["created_at"].endswith("+08:00")


def test_service_duplicate_add_returns_false_without_replacing_record(tmp_path):
    service = _service(tmp_path)
    assert service.add_stock("user-1", "2330", "台積電") is True
    original = deepcopy(service.list_stocks("user-1"))

    assert service.add_stock("user-1", "2330", "新名稱") is False
    assert service.list_stocks("user-1") == original


def test_service_remove_existing_then_missing_returns_false(tmp_path):
    service = _service(tmp_path)
    assert service.add_stock("user-1", "2330", "台積電") is True
    assert service.remove_stock("user-1", "2330") is True
    assert service.remove_stock("user-1", "2330") is False
    assert service.list_stocks("user-1") == []


def test_service_empty_watchlist(tmp_path):
    assert _service(tmp_path).list_stocks("user-1") == []


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("add_stock", ("", "2330", "台積電")),
        ("add_stock", ("user-1", None, "台積電")),
        ("add_stock", ("user-1", "2330", "  ")),
        ("remove_stock", ("user-1", "")),
        ("list_stocks", (None,)),
        ("exists", ("", "2330")),
    ],
)
def test_service_rejects_invalid_required_values(tmp_path, method, args):
    with pytest.raises(ValueError):
        getattr(_service(tmp_path), method)(*args)


def test_service_does_not_expose_or_execute_sql(tmp_path):
    service = _service(tmp_path)
    assert not hasattr(service, "_connect")
    assert not hasattr(service, "execute")
