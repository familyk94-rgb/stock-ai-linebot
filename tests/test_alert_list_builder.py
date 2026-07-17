import json

from linebot.v3.messaging import FlexContainer, FlexMessage

from app.flex.alert_list_card import (
    MAX_VISIBLE_ALERTS,
    build_alert_list_bubble,
    build_alert_list_flex,
)
from core.models.alert_management import AlertListItem, AlertListResult


def _item(
    alert_id=1,
    stock_id="2330",
    stock_name="台積電",
    condition_type="GT",
    condition_label="股價突破",
    target_value="1150",
    enabled=True,
):
    return AlertListItem(
        alert_id=alert_id,
        stock_id=stock_id,
        stock_name=stock_name,
        condition_type=condition_type,
        condition_label=condition_label,
        target_value=target_value,
        enabled=enabled,
    )


def _result(items=()):
    items = tuple(items)
    enabled = sum(item.enabled for item in items)
    return AlertListResult("user-1", items, len(items), enabled, len(items) - enabled)


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _texts(bubble):
    return [item["text"] for item in _walk(bubble) if item.get("type") == "text"]


def _buttons(bubble):
    return [item for item in _walk(bubble) if item.get("type") == "button"]


def test_none_and_empty_result_are_safe_valid_bubbles():
    for result in (None, _result()):
        bubble = build_alert_list_bubble(result)
        assert "目前沒有提醒" in _texts(bubble)
        assert "共 0 筆" in _texts(bubble)[1]
        assert FlexContainer.from_dict(bubble) is not None
        assert json.loads(json.dumps(bubble, ensure_ascii=False)) == bubble


def test_single_enabled_alert_and_flex_message():
    result = _result([_item()])
    bubble = build_alert_list_bubble(result)
    texts = _texts(bubble)
    assert {"2330 台積電", "🟢 啟用", "股價突破 1150"}.issubset(texts)
    message = build_alert_list_flex(result)
    assert isinstance(message, FlexMessage)
    assert message.alt_text == "我的股票提醒"


def test_enabled_disabled_and_multiple_items_are_visually_distinct():
    bubble = build_alert_list_bubble(
        _result([
            _item(),
            _item(2, "2882", "國泰金", "LT", "股價跌破", "55", False),
        ])
    )
    texts = _texts(bubble)
    assert "共 2 筆　啟用 1 筆　停用 1 筆" in texts
    assert {"🟢 啟用", "⚪ 停用", "股價跌破 55"}.issubset(texts)


def test_unknown_condition_long_name_and_none_target_are_safe():
    long_name = "很長的股票名稱" * 30
    bubble = build_alert_list_bubble(
        _result([_item(stock_name=long_name, condition_type="X", condition_label="自訂提醒", target_value="—")])
    )
    assert "自訂提醒 —" in _texts(bubble)
    name_text = next(item for item in _walk(bubble) if item.get("text") == f"2330 {long_name}")
    assert name_text["wrap"] is True
    assert name_text["maxLines"] == 2
    assert FlexContainer.from_dict(bubble) is not None


def test_many_alerts_are_limited_and_hidden_count_is_shown():
    items = [_item(index + 1, f"{index:04d}") for index in range(20)]
    bubble = build_alert_list_bubble(_result(items))
    texts = _texts(bubble)
    assert sum(text in {"🟢 啟用", "⚪ 停用"} for text in texts) == MAX_VISIBLE_ALERTS
    assert "另有 12 筆提醒未顯示" in texts
    assert len(json.dumps(bubble, ensure_ascii=False).encode("utf-8")) < 50_000
    assert FlexContainer.from_dict(bubble) is not None


def test_footer_actions_use_existing_safe_message_contract():
    buttons = _buttons(build_alert_list_bubble(_result()))
    assert [(item["action"]["label"], item["action"]["text"]) for item in buttons] == [
        ("＋ 新增提醒", "新增提醒"),
        ("🔄 重新整理", "我的提醒"),
    ]
    assert all(item["action"]["type"] == "message" for item in buttons)
