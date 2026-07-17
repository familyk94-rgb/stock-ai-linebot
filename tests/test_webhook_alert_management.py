from types import SimpleNamespace

from linebot.v3.messaging import FlexMessage

from app import webhook
from core.models.alert_management import AlertListResult


def _event(text, user_id="user-1"):
    source = SimpleNamespace(user_id=user_id) if user_id is not None else SimpleNamespace()
    return SimpleNamespace(
        message=SimpleNamespace(text=text),
        source=source,
        reply_token="reply-token",
    )


class Service:
    def __init__(self, result=None, error=None):
        self.result = result or AlertListResult.empty("user-1")
        self.error = error
        self.calls = []

    def list_user_alerts(self, user_id):
        self.calls.append(user_id)
        if self.error:
            raise self.error
        return self.result


def _setup(monkeypatch, service=None):
    service = service or Service()
    replies = []
    texts = []
    calls = {"market": 0, "ai": 0, "dashboard": 0}
    monkeypatch.setattr(webhook, "alert_management_service", service)
    monkeypatch.setattr(webhook, "reply_message", lambda token, message: replies.append((token, message)))
    monkeypatch.setattr(webhook, "safe_reply_text", lambda token, text: texts.append((token, text)))
    monkeypatch.setattr(webhook, "get_market_info", lambda stock_id: calls.__setitem__("market", calls["market"] + 1))
    monkeypatch.setattr(webhook, "ai_stock_analysis", lambda data: calls.__setitem__("ai", calls["ai"] + 1))
    monkeypatch.setattr(webhook, "build_stock_dashboard_flex", lambda data: calls.__setitem__("dashboard", calls["dashboard"] + 1))
    return service, replies, texts, calls


def test_my_alerts_uses_line_user_id_and_replies_with_flex(monkeypatch):
    service, replies, texts, calls = _setup(monkeypatch)
    webhook.handle_text_message(_event("我的提醒"))
    assert service.calls == ["user-1"]
    assert len(replies) == 1 and isinstance(replies[0][1], FlexMessage)
    assert texts == []
    assert calls == {"market": 0, "ai": 0, "dashboard": 0}


def test_empty_alerts_still_reply_once(monkeypatch):
    _, replies, _, _ = _setup(monkeypatch)
    webhook.handle_text_message(_event("我的提醒"))
    assert len(replies) == 1


def test_missing_user_id_is_safe(monkeypatch):
    service, replies, texts, _ = _setup(monkeypatch)
    webhook.handle_text_message(_event("我的提醒", None))
    assert service.calls == []
    assert replies == []
    assert texts == [("reply-token", "無法識別使用者，請稍後再試。")]


def test_service_error_uses_safe_text_fallback(monkeypatch):
    service = Service(error=RuntimeError("database unavailable token=secret"))
    _, replies, texts, calls = _setup(monkeypatch, service)
    webhook.handle_text_message(_event("我的提醒"))
    assert replies == []
    assert texts == [("reply-token", "提醒服務暫時無法使用，請稍後再試。")]
    assert calls == {"market": 0, "ai": 0, "dashboard": 0}


def test_add_alert_returns_coming_soon_without_service_or_database_write(monkeypatch):
    service, replies, texts, calls = _setup(monkeypatch)
    webhook.handle_text_message(_event("新增提醒"))
    assert service.calls == []
    assert replies == []
    assert texts == [("reply-token", "新增提醒功能即將開放。")]
    assert calls == {"market": 0, "ai": 0, "dashboard": 0}


def test_normal_stock_analysis_route_is_unchanged(monkeypatch):
    market_data = {
        "price": 100, "stock_name": "台積電", "core": {}, "composite": {},
        "data_quality": {}, "quote": {},
    }
    service, replies, _, calls = _setup(monkeypatch)
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
        lambda data: (calls.__setitem__("dashboard", calls["dashboard"] + 1) or "dashboard-flex"),
    )
    webhook.handle_text_message(_event("2330"))
    assert service.calls == []
    assert calls == {"market": 1, "ai": 1, "dashboard": 1}
    assert replies == [("reply-token", "dashboard-flex")]
