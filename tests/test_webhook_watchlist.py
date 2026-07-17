from types import SimpleNamespace

import pytest
from linebot.v3.messaging import TextMessage

from app import webhook
from services.repositories.watchlist_repository import WatchlistRepository
from services.watchlist_service import WatchlistService


def _event(text, user_id="user-1"):
    source = SimpleNamespace(user_id=user_id) if user_id is not None else SimpleNamespace()
    return SimpleNamespace(
        message=SimpleNamespace(text=text),
        source=source,
        reply_token="reply-token",
    )


class FakeWatchlistService:
    def __init__(self, *, added=True, removed=True, stocks=None):
        self.added = added
        self.removed = removed
        self.stocks = list(stocks or [])
        self.calls = []

    def add_stock(self, user_id, stock_id, stock_name):
        self.calls.append(("add", user_id, stock_id, stock_name))
        return self.added

    def remove_stock(self, user_id, stock_id):
        self.calls.append(("remove", user_id, stock_id))
        return self.removed

    def list_stocks(self, user_id):
        self.calls.append(("list", user_id))
        return list(self.stocks)


def _setup(monkeypatch, service=None, stock_name="台積電"):
    replies = []
    calls = {"market": 0, "ai": 0, "builder": 0, "name": 0}
    service = service or FakeWatchlistService()
    monkeypatch.setattr(webhook, "watchlist_service", service)

    def resolve_name(stock_id):
        calls["name"] += 1
        return stock_name

    monkeypatch.setattr(webhook, "get_stock_name", resolve_name)
    monkeypatch.setattr(
        webhook,
        "get_market_info",
        lambda stock_id: calls.__setitem__("market", calls["market"] + 1),
    )
    monkeypatch.setattr(
        webhook,
        "ai_stock_analysis",
        lambda data: calls.__setitem__("ai", calls["ai"] + 1),
    )
    monkeypatch.setattr(
        webhook,
        "build_stock_dashboard_flex",
        lambda data: calls.__setitem__("builder", calls["builder"] + 1),
    )
    monkeypatch.setattr(
        webhook,
        "safe_reply_text",
        lambda token, text: replies.append((token, text)),
    )
    return service, calls, replies


def test_add_watchlist_stock_success(monkeypatch):
    service, calls, replies = _setup(monkeypatch)
    webhook.handle_text_message(_event("加入自選 2330"))

    assert service.calls == [("add", "user-1", "2330", "台積電")]
    assert replies == [("reply-token", "✅ 已加入自選股\n\n2330 台積電")]
    assert calls == {"market": 0, "ai": 0, "builder": 0, "name": 1}


def test_duplicate_watchlist_stock(monkeypatch):
    service, calls, replies = _setup(
        monkeypatch, FakeWatchlistService(added=False)
    )
    webhook.handle_text_message(_event("加入自選 2330"))
    assert replies == [("reply-token", "⚠️ 2330 已在自選股中")]
    assert calls["market"] == calls["ai"] == calls["builder"] == 0


def test_remove_watchlist_stock_success(monkeypatch):
    service = FakeWatchlistService(
        stocks=[{"stock_id": "2330", "stock_name": "台積電"}]
    )
    service, calls, replies = _setup(monkeypatch, service)
    webhook.handle_text_message(_event("移除自選 2330"))

    assert service.calls == [("list", "user-1"), ("remove", "user-1", "2330")]
    assert replies == [("reply-token", "✅ 已移除自選股\n\n2330 台積電")]
    assert calls["name"] == calls["market"] == calls["ai"] == calls["builder"] == 0


def test_remove_missing_watchlist_stock(monkeypatch):
    service, _, replies = _setup(
        monkeypatch, FakeWatchlistService(removed=False)
    )
    webhook.handle_text_message(_event("移除自選 2330"))
    assert service.calls == [("list", "user-1"), ("remove", "user-1", "2330")]
    assert replies == [("reply-token", "⚠️ 自選股中沒有 2330")]


def test_list_watchlist_with_stocks(monkeypatch):
    service = FakeWatchlistService(
        stocks=[
            {"stock_id": "2330", "stock_name": "台積電"},
            {"stock_id": "2454", "stock_name": "聯發科"},
        ]
    )
    _, calls, replies = _setup(monkeypatch, service)
    webhook.handle_text_message(_event("我的自選"))

    assert replies == [
        ("reply-token", "⭐ 我的自選股\n\n1. 2330 台積電\n2. 2454 聯發科")
    ]
    assert calls == {"market": 0, "ai": 0, "builder": 0, "name": 0}


def test_list_empty_watchlist(monkeypatch):
    _, _, replies = _setup(monkeypatch)
    webhook.handle_text_message(_event("我的自選"))
    assert replies == [("reply-token", "目前沒有自選股")]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("加入自選", "請輸入股票代號"),
        ("移除自選", "請輸入股票代號"),
        ("加入自選 ABCD", "股票代號格式錯誤"),
    ],
)
def test_watchlist_command_input_validation(monkeypatch, text, expected):
    service, calls, replies = _setup(monkeypatch)
    webhook.handle_text_message(_event(text))
    assert replies == [("reply-token", expected)]
    assert service.calls == []
    assert calls == {"market": 0, "ai": 0, "builder": 0, "name": 0}


def test_unknown_stock_is_not_added(monkeypatch):
    service, calls, replies = _setup(monkeypatch, stock_name="未知股票")
    webhook.handle_text_message(_event("加入自選 999999"))
    assert replies == [("reply-token", "查無此股票")]
    assert service.calls == []
    assert calls["name"] == 1
    assert calls["market"] == calls["ai"] == calls["builder"] == 0


def test_watchlist_users_are_isolated_with_real_service(monkeypatch, tmp_path):
    service = WatchlistService(WatchlistRepository(tmp_path / "watchlist.db"))
    _, _, replies = _setup(monkeypatch, service)

    webhook.handle_text_message(_event("加入自選 2330", "user-1"))
    webhook.handle_text_message(_event("我的自選", "user-2"))

    assert service.exists("user-1", "2330") is True
    assert service.exists("user-2", "2330") is False
    assert replies[-1] == ("reply-token", "目前沒有自選股")


def test_missing_user_id_is_safe_and_skips_all_services(monkeypatch):
    service, calls, replies = _setup(monkeypatch)
    webhook.handle_text_message(_event("加入自選 2330", None))
    assert replies == [("reply-token", "無法識別使用者，請稍後再試。")]
    assert service.calls == []
    assert calls == {"market": 0, "ai": 0, "builder": 0, "name": 0}


def test_watchlist_service_exception_is_safely_replied(monkeypatch):
    service = FakeWatchlistService()

    def fail(user_id):
        raise RuntimeError("database unavailable")

    service.list_stocks = fail
    _, calls, replies = _setup(monkeypatch, service)
    webhook.handle_text_message(_event("我的自選"))
    assert replies == [("reply-token", "自選股服務暫時無法使用，請稍後再試。")]
    assert calls["market"] == calls["ai"] == calls["builder"] == 0


def test_normal_stock_query_still_uses_existing_market_ai_flex_flow(monkeypatch):
    calls = {"market": 0, "ai": 0, "builder": 0, "reply": []}
    market_data = {
        "price": 100,
        "stock_name": "台積電",
        "core": {},
        "composite": {},
        "data_quality": {},
        "quote": {},
    }
    monkeypatch.setattr(
        webhook,
        "get_market_info",
        lambda stock_id: (calls.__setitem__("market", calls["market"] + 1) or market_data),
    )
    monkeypatch.setattr(
        webhook,
        "ai_stock_analysis",
        lambda data: (calls.__setitem__("ai", calls["ai"] + 1) or {"ai_summary": "摘要", "explain": "原因"}),
    )
    monkeypatch.setattr(
        webhook,
        "build_stock_dashboard_flex",
        lambda data: (calls.__setitem__("builder", calls["builder"] + 1) or "flex"),
    )
    monkeypatch.setattr(
        webhook,
        "reply_message",
        lambda token, message: calls["reply"].append((token, message)),
    )

    webhook.handle_text_message(_event("2330"))

    assert calls == {
        "market": 1,
        "ai": 1,
        "builder": 1,
        "reply": [("reply-token", "flex")],
    }


def test_watchlist_reply_uses_existing_line_text_reply_path(monkeypatch):
    service = FakeWatchlistService()
    sent = []
    monkeypatch.setattr(webhook, "watchlist_service", service)
    monkeypatch.setattr(
        webhook,
        "reply_message",
        lambda token, message: sent.append((token, message)),
    )

    webhook.handle_text_message(_event("我的自選"))

    assert len(sent) == 1
    assert sent[0][0] == "reply-token"
    assert isinstance(sent[0][1], TextMessage)
    assert sent[0][1].text == "目前沒有自選股"
