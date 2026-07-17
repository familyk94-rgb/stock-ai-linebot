from datetime import datetime, timezone
from types import SimpleNamespace

from app import webhook
from services.alert_creation_service import AlertCreationService
from services.alert_creation_state_store import AlertCreationStateStore


class Repo:
    def __init__(self):
        self.rows = []
        self.error = False

    def exists_active_alert(self, user, stock, condition, target):
        return any(
            row["line_user_id"] == user and row["stock_id"] == stock
            and row["condition"] == condition and row["target_price"] == target
            for row in self.rows
        )

    def add_alert(self, **kwargs):
        if self.error: raise RuntimeError("database secret path")
        row = {"id": len(self.rows) + 1, "enabled": True, "is_active": False, **kwargs}
        self.rows.append(row)
        return row


def _event(text, user_id="u1"):
    source = SimpleNamespace(user_id=user_id) if user_id is not None else SimpleNamespace()
    return SimpleNamespace(message=SimpleNamespace(text=text), source=source, reply_token="reply")


def _setup(monkeypatch, repo=None):
    repo = repo or Repo()
    now = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    service = AlertCreationService(repo, AlertCreationStateStore(clock=now), lambda _: "台積電", now)
    texts, flexes = [], []
    calls = {"market": 0, "ai": 0, "runtime": 0, "push": 0}
    monkeypatch.setattr(webhook, "alert_creation_service", service)
    monkeypatch.setattr(webhook, "safe_reply_text", lambda token, text: texts.append((token, text)))
    monkeypatch.setattr(webhook, "reply_message", lambda token, message: flexes.append((token, message)))
    monkeypatch.setattr(webhook, "build_alert_creation_confirmation_flex", lambda result: ("confirmation", result))
    monkeypatch.setattr(webhook, "get_market_info", lambda _: calls.__setitem__("market", calls["market"] + 1))
    monkeypatch.setattr(webhook, "ai_stock_analysis", lambda _: calls.__setitem__("ai", calls["ai"] + 1))
    return service, repo, texts, flexes, calls


def test_complete_happy_path_creates_once_and_clears_session(monkeypatch):
    service, repo, texts, flexes, calls = _setup(monkeypatch)
    for text in ["新增提醒", "2330", "股價突破", "1150", "確認建立"]:
        webhook.handle_text_message(_event(text))
    assert len(repo.rows) == 1
    assert repo.rows[0]["line_user_id"] == "u1"
    assert repo.rows[0]["condition"] == "GT"
    assert str(repo.rows[0]["target_price"]) == "1150"
    assert service.get_session("u1") is None
    assert len(flexes) == 1 and "提醒建立成功" in texts[-1][1]
    assert calls == {"market": 0, "ai": 0, "runtime": 0, "push": 0}


def test_lt_mapping_and_decimal_target(monkeypatch):
    _, repo, _, _, _ = _setup(monkeypatch)
    for text in ["新增提醒", "2330", "跌破", "55.5", "確認"]:
        webhook.handle_text_message(_event(text))
    assert repo.rows[0]["condition"] == "LT" and str(repo.rows[0]["target_price"]) == "55.5"


def test_cancel_and_cancel_without_session(monkeypatch):
    service, repo, texts, _, _ = _setup(monkeypatch)
    webhook.handle_text_message(_event("新增提醒")); webhook.handle_text_message(_event("取消"))
    assert service.get_session("u1") is None and repo.rows == [] and texts[-1][1] == "已取消提醒設定。"
    webhook.handle_text_message(_event("取消"))
    assert texts[-1][1] == "目前沒有進行中的提醒設定。"


def test_restart_clears_old_fields(monkeypatch):
    service, repo, texts, _, _ = _setup(monkeypatch)
    for text in ["新增提醒", "2330", "GT", "1150", "重新輸入"]:
        webhook.handle_text_message(_event(text))
    session = service.get_session("u1")
    assert session.stock_id is session.condition is session.target_price is None
    assert repo.rows == [] and "股票代號" in texts[-1][1]


def test_invalid_inputs_do_not_advance(monkeypatch):
    service, _, texts, _, _ = _setup(monkeypatch)
    webhook.handle_text_message(_event("新增提醒")); webhook.handle_text_message(_event("ABCD"))
    assert "格式錯誤" in texts[-1][1]
    webhook.handle_text_message(_event("2330")); webhook.handle_text_message(_event("EQ"))
    assert "股價突破" in texts[-1][1]
    webhook.handle_text_message(_event("GT")); webhook.handle_text_message(_event("NaN"))
    assert "價格格式錯誤" in texts[-1][1]
    assert service.get_session("u1") is not None


def test_duplicate_does_not_create_or_clear(monkeypatch):
    service, repo, texts, _, _ = _setup(monkeypatch)
    for text in ["新增提醒", "2330", "GT", "1150", "確認"]: webhook.handle_text_message(_event(text))
    for text in ["新增提醒", "2330", "GT", "1150", "確認"]: webhook.handle_text_message(_event(text))
    assert len(repo.rows) == 1 and service.get_session("u1") is not None
    assert texts[-1][1] == "這筆提醒已經存在。"


def test_repository_error_safe_reply_and_session_preserved(monkeypatch):
    repo = Repo(); repo.error = True
    service, _, texts, _, _ = _setup(monkeypatch, repo)
    for text in ["新增提醒", "2330", "GT", "1150", "確認"]: webhook.handle_text_message(_event(text))
    assert texts[-1][1] == "提醒建立失敗，請稍後再試。" and service.get_session("u1") is not None


def test_missing_user_id_is_safe(monkeypatch):
    _, repo, texts, _, calls = _setup(monkeypatch)
    webhook.handle_text_message(_event("新增提醒", None))
    assert "無法識別使用者" in texts[-1][1] and repo.rows == [] and calls["market"] == 0


def test_users_are_isolated(monkeypatch):
    service, _, _, _, _ = _setup(monkeypatch)
    webhook.handle_text_message(_event("新增提醒", "u1")); webhook.handle_text_message(_event("新增提醒", "u2"))
    webhook.handle_text_message(_event("2330", "u1"))
    assert service.get_session("u1").stock_id == "2330" and service.get_session("u2").stock_id is None


def test_service_exception_is_safely_replied(monkeypatch):
    service, _, texts, _, _ = _setup(monkeypatch)
    monkeypatch.setattr(service, "get_session", lambda _: (_ for _ in ()).throw(RuntimeError("token secret")))
    webhook.handle_text_message(_event("anything"))
    assert texts == [("reply", "提醒設定暫時無法使用，請稍後再試。")]


def test_normal_dashboard_route_remains_available(monkeypatch):
    _, _, _, flexes, calls = _setup(monkeypatch)
    market = {"price": 100, "core": {}, "composite": {}, "data_quality": {}, "quote": {}}
    monkeypatch.setattr(webhook, "get_market_info", lambda _: (calls.__setitem__("market", 1) or market))
    monkeypatch.setattr(webhook, "ai_stock_analysis", lambda _: (calls.__setitem__("ai", 1) or {"ai_summary":"s", "explain":"e"}))
    monkeypatch.setattr(webhook, "build_stock_dashboard_flex", lambda _: "dashboard")
    webhook.handle_text_message(_event("2330"))
    assert calls["market"] == calls["ai"] == 1 and flexes == [("reply", "dashboard")]
