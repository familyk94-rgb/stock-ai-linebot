import json
from decimal import Decimal

import pytest
from linebot.v3.messaging import FlexContainer, FlexMessage

from app.flex.alert_creation_card import build_alert_creation_confirmation_bubble, build_alert_creation_confirmation_flex
from core.models.alert_creation import AlertCreationResult, AlertCreationSession, AlertCreationStep


def _result(condition="GT", price=Decimal("1150"), name="台積電"):
    session = AlertCreationSession("u1", AlertCreationStep.AWAITING_CONFIRMATION, "2330", name, condition, price)
    return AlertCreationResult("awaiting_confirmation", "confirm", session)


def _texts(value):
    if isinstance(value, dict):
        return [value.get("text")] + sum((_texts(v) for v in value.values()), [])
    if isinstance(value, list): return sum((_texts(v) for v in value), [])
    return []


@pytest.mark.parametrize(("condition", "label"), [("GT", "股價突破"), ("LT", "股價跌破")])
def test_complete_confirmation_and_condition(condition, label):
    bubble = build_alert_creation_confirmation_bubble(_result(condition))
    texts = _texts(bubble)
    assert "2330 台積電" in texts and label in texts and "1150" in texts


def test_decimal_small_and_empty_name():
    texts = _texts(build_alert_creation_confirmation_bubble(_result(price=Decimal("55.50"), name="")))
    assert "55.5" in texts and "2330" in texts


def test_none_and_missing_data_are_safe():
    assert "暫無資料" in _texts(build_alert_creation_confirmation_bubble(None))


def test_long_name_wraps_and_no_external_image():
    bubble = build_alert_creation_confirmation_bubble(_result(name="很長的股票名稱" * 30))
    encoded = json.dumps(bubble, ensure_ascii=False).encode()
    assert b"http" not in encoded and len(encoded) < 50_000


def test_sdk_parse_json_and_public_flex_type():
    bubble = build_alert_creation_confirmation_bubble(_result())
    FlexContainer.from_dict(bubble)
    json.dumps(bubble, ensure_ascii=False)
    assert isinstance(build_alert_creation_confirmation_flex(_result()), FlexMessage)


def test_action_payloads_are_exact():
    bubble = build_alert_creation_confirmation_bubble(_result())
    payloads = []
    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "message": payloads.append(value.get("text"))
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(bubble)
    assert payloads == ["確認建立", "重新輸入", "取消"]
