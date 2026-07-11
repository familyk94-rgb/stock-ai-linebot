from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests

from services.news_service import NewsService


class FakeResponse:
    def __init__(self, payload=None, status_code=200, json_error=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


def payload(data, status=200):
    return {"status": status, "data": data}


def item(date_value="2026-07-10", title="News", **overrides):
    result = {
        "date": date_value,
        "title": title,
        "source": "Source",
        "link": "https://example.com/news",
    }
    result.update(overrides)
    return result


def mock_get(monkeypatch, response):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("services.news_service.requests.get", fake_get)
    return calls


def test_normal_news_and_request_contract(monkeypatch):
    calls = mock_get(
        monkeypatch,
        FakeResponse(payload([item("2026-07-10 12:30:00", "  Good   News  ")])),
    )
    monkeypatch.setenv("FINMIND_TOKEN", "test-token")

    result = NewsService().get_news(" 2330 ")

    assert result == {
        "items": [
            {
                "date": "2026-07-10",
                "title": "Good News",
                "source": "Source",
                "url": "https://example.com/news",
            }
        ],
        "count": 1,
        "available": True,
    }
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["timeout"] == 10
    assert kwargs["params"]["dataset"] == "TaiwanStockNews"
    assert kwargs["params"]["data_id"] == "2330"
    assert kwargs["params"]["token"] == "test-token"
    taipei_today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    assert kwargs["params"]["end_date"] == taipei_today.isoformat()
    assert kwargs["params"]["start_date"] == (
        taipei_today - timedelta(days=6)
    ).isoformat()


@pytest.mark.parametrize("stock_id", [None, "", "   "])
def test_invalid_stock_id_falls_back_without_http(monkeypatch, stock_id):
    calls = mock_get(monkeypatch, AssertionError("HTTP must not be called"))
    assert NewsService().get_news(stock_id) == {
        "items": [],
        "count": 0,
        "available": False,
    }
    assert calls == []


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status_code=500),
        requests.Timeout("timeout"),
        requests.RequestException("request failed"),
        FakeResponse(json_error=ValueError("invalid json")),
        FakeResponse([]),
        FakeResponse(payload([], status=500)),
        FakeResponse({"status": 200, "data": {}}),
        FakeResponse(payload([])),
    ],
)
def test_invalid_response_conditions_fall_back(monkeypatch, response):
    mock_get(monkeypatch, response)
    assert NewsService().get_news("2330") == {
        "items": [],
        "count": 0,
        "available": False,
    }


def test_payload_without_status_is_rejected(monkeypatch):
    mock_get(monkeypatch, FakeResponse({"data": [item()]}))
    assert NewsService().get_news("2330") == {
        "items": [],
        "count": 0,
        "available": False,
    }


def test_legacy_finmind_api_token_is_used_as_fallback(monkeypatch):
    calls = mock_get(monkeypatch, FakeResponse(payload([])))
    monkeypatch.delenv("FINMIND_TOKEN", raising=False)
    monkeypatch.setattr("services.news_service.FINMIND_API_TOKEN", "legacy-token")

    NewsService().get_news("2330")

    assert calls[0][1]["params"]["token"] == "legacy-token"


def test_dates_are_sorted_and_invalid_dates_ignored(monkeypatch):
    rows = [
        item("2026-07-08", "Older", link="older"),
        item("invalid", "Invalid", link="invalid"),
        item("2026-07-10", "Newest", link="newest"),
        item(None, "No date", link="none"),
        item("2026-07-09 18:00:00", "Middle", link="middle"),
    ]
    mock_get(monkeypatch, FakeResponse(payload(rows)))
    result = NewsService().get_news("2330")
    assert [news["title"] for news in result["items"]] == [
        "Newest",
        "Middle",
        "Older",
    ]


def test_blank_title_and_non_dict_items_are_ignored(monkeypatch):
    rows = [item(title="   ", link="blank"), None, "bad"]
    mock_get(monkeypatch, FakeResponse(payload(rows)))
    assert NewsService().get_news("2330")["available"] is False


def test_duplicate_url_keeps_newest(monkeypatch):
    rows = [
        item("2026-07-08", "Old title", link="same-url"),
        item("2026-07-10", "New title", link="same-url"),
    ]
    mock_get(monkeypatch, FakeResponse(payload(rows)))
    result = NewsService().get_news("2330")
    assert [news["title"] for news in result["items"]] == ["New title"]


def test_same_date_duplicate_keeps_first_api_item_stably(monkeypatch):
    rows = [
        item("2026-07-10", "First API item", link="same-url"),
        item("2026-07-10", "Second API item", link="same-url"),
    ]
    mock_get(monkeypatch, FakeResponse(payload(rows)))

    first_result = NewsService().get_news("2330")
    second_result = NewsService().get_news("2330")

    expected = ["First API item"]
    assert [news["title"] for news in first_result["items"]] == expected
    assert [news["title"] for news in second_result["items"]] == expected


def test_duplicate_normalized_title_without_url_keeps_newest(monkeypatch):
    rows = [
        item("2026-07-08", " Same NEWS ", link=""),
        item("2026-07-10", "same   news", link=None),
    ]
    mock_get(monkeypatch, FakeResponse(payload(rows)))
    result = NewsService().get_news("2330")
    assert result["count"] == 1
    assert result["items"][0]["date"] == "2026-07-10"


def test_different_titles_are_not_removed(monkeypatch):
    rows = [
        item("2026-07-10", "Company raises outlook", link=""),
        item("2026-07-09", "Company reports revenue", link=""),
    ]
    mock_get(monkeypatch, FakeResponse(payload(rows)))
    result = NewsService().get_news("2330")
    assert result["count"] == len(result["items"]) == 2
    assert result["available"] is True


def test_only_latest_twenty_items_are_returned(monkeypatch):
    rows = [
        item(
            f"2026-07-{day:02d}",
            f"News {day}",
            link=f"https://example.com/{day}",
        )
        for day in range(1, 26)
    ]
    mock_get(monkeypatch, FakeResponse(payload(rows)))
    result = NewsService().get_news("2330")
    assert result["count"] == len(result["items"]) == 20
    assert result["items"][0]["title"] == "News 25"
    assert result["items"][-1]["title"] == "News 6"


def test_missing_source_and_url_become_empty_strings(monkeypatch):
    mock_get(
        monkeypatch,
        FakeResponse(payload([item(source=None, link=None)])),
    )
    news = NewsService().get_news("2330")["items"][0]
    assert news["source"] == ""
    assert news["url"] == ""
