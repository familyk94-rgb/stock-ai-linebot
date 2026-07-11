import json
from copy import deepcopy

import pytest
from linebot.v3.messaging import FlexContainer, FlexMessage

from app.flex.builder import (
    build_stock_dashboard_bubble,
    build_stock_dashboard_flex,
)


def _full_data(**overrides):
    data = {
        "stock_code": "2330",
        "stock_name": "台積電 🚀",
        "score": 82,
        "decision": "偏多",
        "risk_level": "中等風險",
        "shopkeeper_message": "店長說：\"留意波動\" \\ 測試",
        "price": 1000,
        "change": 10,
        "change_percent": 1.01,
        "volume": 123456,
        "trend": "多頭",
        "ma_signal": "站上 MA20",
        "macd_signal": "黃金交叉",
        "rsi_signal": "55.5（健康區間）",
        "ai_summary": "摘要第一行\n摘要第二行 😀",
        "explain": "詳細原因\n技術面：整理\n綜合分析：中性",
    }
    data.update(overrides)
    return data


def _walk(component):
    if isinstance(component, dict):
        yield component
        for value in component.values():
            yield from _walk(value)
    elif isinstance(component, list):
        for value in component:
            yield from _walk(value)


def _texts(component):
    return [item for item in _walk(component) if item.get("type") == "text"]


def _text_values(component):
    return [item.get("text") for item in _texts(component)]


def _json_size(bubble):
    return len(json.dumps(bubble, ensure_ascii=False).encode("utf-8"))


def test_none_and_empty_data_build_valid_serializable_bubbles():
    for data in (None, {}):
        bubble = build_stock_dashboard_bubble(data)
        assert bubble["type"] == "bubble"
        assert {"header", "body", "footer"}.issubset(bubble)
        assert isinstance(json.dumps(bubble, ensure_ascii=False), str)
        assert FlexContainer.from_dict(bubble) is not None


def test_full_data_builds_flex_message_without_mutating_input():
    data = _full_data()
    original = deepcopy(data)
    bubble = build_stock_dashboard_bubble(data)
    message = build_stock_dashboard_flex(data)
    assert isinstance(message, FlexMessage)
    assert isinstance(bubble, dict)
    assert data == original


def test_bubble_card_order_and_no_independent_market_analysis_cards():
    bubble = build_stock_dashboard_bubble(_full_data())
    body = bubble["body"]["contents"]
    assert len(body) == 6
    assert body[0]["contents"][0]["text"] == "AI 儀表板"
    assert body[1]["contents"][0]["text"] == "阿柑店長"
    assert body[2]["contents"][0]["text"] == "市場資料"
    assert body[3]["contents"][0]["text"] == "技術分析"
    assert body[4]["contents"][0]["text"] == "AI 分析"
    assert body[5]["contents"][0]["text"] == "分析原因"
    headings = [card["contents"][0]["text"] for card in body]
    assert all(name not in headings for name in ("綜合分析", "基本面", "籌碼面", "新聞面"))
    assert bubble["footer"]["contents"][0]["text"]


def test_all_mapped_values_are_present_in_expected_cards():
    data = _full_data()
    bubble = build_stock_dashboard_bubble(data)
    body = bubble["body"]["contents"]
    dashboard, _, market, technical, summary, explain = body
    assert {"82.0", "偏多", "中等風險"}.issubset(set(_text_values(dashboard)))
    assert {"1000", "10", "1.01%", "123456"}.issubset(set(_text_values(market)))
    assert {"多頭", "站上 MA20", "黃金交叉", "55.5（健康區間）"}.issubset(
        set(_text_values(technical))
    )
    assert data["ai_summary"] in _text_values(summary)
    assert data["explain"] in _text_values(explain)


def test_summary_and_explain_are_wrapped():
    bubble = build_stock_dashboard_bubble(_full_data())
    summary_text = bubble["body"]["contents"][4]["contents"][1]
    explain_text = bubble["body"]["contents"][5]["contents"][1]
    assert summary_text["wrap"] is True
    assert explain_text["wrap"] is True
    assert "maxLines" not in summary_text
    assert "maxLines" not in explain_text


def test_three_thousand_unicode_explain_is_preserved_and_sdk_parses():
    explain = "測" * 3000
    data = _full_data(explain=explain)
    bubble = build_stock_dashboard_bubble(data)
    assert bubble["body"]["contents"][5]["contents"][1]["text"] == explain
    assert FlexContainer.from_dict(bubble) is not None


def test_unicode_quotes_backslashes_and_newlines_round_trip_json():
    value = "中文 😀\n雙引號：\"內容\"\n反斜線：C:\\Project\\file"
    bubble = build_stock_dashboard_bubble(_full_data(ai_summary=value, explain=value))
    serialized = json.dumps(bubble, ensure_ascii=False)
    restored = json.loads(serialized)
    assert value in _text_values(restored)


@pytest.mark.parametrize("data", [
    {"score": None, "ai_summary": None, "explain": None},
    {"decision": None, "risk_level": None},
    {"price": None, "change": None, "change_percent": None, "volume": None},
    {"trend": None, "ma_signal": None, "macd_signal": None, "rsi_signal": None},
])
def test_none_and_missing_fields_use_existing_fallbacks(data):
    bubble = build_stock_dashboard_bubble(data)
    assert FlexContainer.from_dict(bubble) is not None
    assert all(isinstance(value, str) for value in _text_values(bubble))


@pytest.mark.parametrize("value", [True, ["value"], {"value": 1}])
def test_abnormal_text_input_types_do_not_crash_builder(value):
    data = _full_data(stock_code=value, stock_name=value, price=value, volume=value)
    bubble = build_stock_dashboard_bubble(data)
    assert isinstance(bubble, dict)
    FlexContainer.from_dict(bubble)


def test_builder_is_deterministic_and_records_json_sizes(capsys):
    data = _full_data()
    first = build_stock_dashboard_bubble(data)
    second = build_stock_dashboard_bubble(data)
    long_bubble = build_stock_dashboard_bubble(_full_data(explain="測" * 3000))
    assert first == second
    normal_size = _json_size(first)
    long_size = _json_size(long_bubble)
    print(f"normal_bubble_json_bytes={normal_size}")
    print(f"long_explain_bubble_json_bytes={long_size}")
    assert normal_size > 0
    assert long_size > normal_size
    assert "services.flex_service" not in build_stock_dashboard_flex.__module__
