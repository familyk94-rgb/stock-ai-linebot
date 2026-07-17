import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from linebot.v3.messaging import FlexContainer, FlexMessage

from app.flex.builder import build_stock_dashboard_bubble, build_stock_dashboard_flex
from app.flex.design_system import BRAND, RISK, SUCCESS, WARNING


def _full_data(**overrides):
    data = {
        "stock_code": "2330",
        "stock_name": "台積電",
        "score": 82.6,
        "confidence": 85,
        "decision": "偏多",
        "risk_level": "中風險",
        "shopkeeper_message": "技術與整體訊號偏多，仍需留意風險。",
        "price": 1045,
        "change": 18,
        "change_percent": 1.75,
        "volume": 123456,
        "quote": {
            "symbol": "2330",
            "price": 1045,
            "reference_price": 1027,
            "change": 18,
            "change_percent": 1.75,
            "volume": 123456,
            "timestamp": "2026-07-17T14:23:00+08:00",
            "market": "TWSE",
            "provider": "fubon_neo",
            "status": "trading",
            "is_realtime": True,
            "data_quality": "realtime",
        },
        "trend": "多頭整理",
        "ma_signal": "站上 MA20",
        "macd_signal": "黃金交叉",
        "rsi_signal": "55.5",
        "composite_available": True,
        "composite_score": 72,
        "composite_summary": "整體訊號中性偏多",
        "composite_coverage": 100,
        "data_quality_status": "正常",
        "data_quality_is_stale": False,
        "ai_summary": (
            "趨勢總結：整體偏多\n"
            "短線建議：🟢 偏多\n"
            "中線建議：🟡 震盪\n"
            "長線建議：🟢 多頭\n"
            "AI 信心度：85%"
        ),
        "explain": "詳細原因\n技術面：整理\n綜合分析：中性偏多",
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
    return [item["text"] for item in _texts(component)]


def _buttons(component):
    return [item for item in _walk(component) if item.get("type") == "button"]


def _json_size(bubble):
    return len(json.dumps(bubble, ensure_ascii=False).encode("utf-8"))


@pytest.mark.parametrize("data", [None, {}])
def test_none_and_empty_data_build_valid_sdk_serializable_bubble(data):
    bubble = build_stock_dashboard_bubble(data)
    assert bubble["type"] == "bubble"
    assert bubble["size"] == "mega"
    assert {"header", "body", "footer"}.issubset(bubble)
    assert FlexContainer.from_dict(bubble) is not None
    assert json.loads(json.dumps(bubble, ensure_ascii=False)) == bubble


def test_public_builder_api_and_input_immutability_are_unchanged():
    data = _full_data()
    original = deepcopy(data)
    bubble = build_stock_dashboard_bubble(data)
    message = build_stock_dashboard_flex(data)
    assert isinstance(bubble, dict)
    assert isinstance(message, FlexMessage)
    assert message.alt_text == "股市柑仔店 AI Pro 股票分析"
    assert data == original


def test_dashboard_v3_snapshot_structure_and_order():
    bubble = build_stock_dashboard_bubble(_full_data())
    body = bubble["body"]["contents"]
    assert len(body) == 7
    assert [_text_values(card)[0] for card in body] == [
        "AI 技術分",
        "📈 偏多",
        "多面向分析",
        "AI 趨勢",
        "🍊 阿柑店長",
        "🔔 我的提醒",
        "📈 完整分析",
    ]
    assert _text_values(bubble["header"])[:2] == [
        "🍊 股市柑仔店 AI Pro",
        "2330 台積電",
    ]
    assert [button["action"]["label"] for button in _buttons(bubble["footer"])] == [
        "📈 完整分析",
        "⭐ 自選股",
        "🔔 設定提醒",
        "🔄 更新分析",
    ]


def test_header_live_quote_contract():
    texts = _text_values(build_stock_dashboard_bubble(_full_data())["header"])
    assert "1,045 元" in texts
    assert "▲ +18 (+1.75%)" in texts
    assert "14:23 更新" in texts
    assert "成交量 123,456｜富邦 Neo｜即時" in texts
    assert all("張" not in text for text in texts)


@pytest.mark.parametrize(
    ("change", "percent", "expected"),
    [
        (18, 1.75, "▲ +18 (+1.75%)"),
        (-5, -0.5, "▼ -5 (-0.5%)"),
        (0, 0, "— 0 (+0%)"),
        (None, None, "暫無漲跌資料"),
    ],
)
def test_header_change_states(change, percent, expected):
    quote = deepcopy(_full_data()["quote"])
    quote.update(change=change, change_percent=percent)
    assert expected in _text_values(build_stock_dashboard_bubble(_full_data(quote=quote))["header"])


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2026-07-17T06:23:00Z", "14:23 更新"),
        (1784269380, "14:23 更新"),
        (1784269380000, "14:23 更新"),
        (1784269380000000, "14:23 更新"),
        (datetime(2026, 7, 17, 6, 23, tzinfo=timezone.utc), "14:23 更新"),
        (None, "更新時間暫無資料"),
        ("invalid", "更新時間暫無資料"),
    ],
)
def test_header_timestamp_contract(timestamp, expected):
    quote = deepcopy(_full_data()["quote"])
    quote["timestamp"] = timestamp
    assert expected in _text_values(build_stock_dashboard_bubble(_full_data(quote=quote))["header"])


@pytest.mark.parametrize(
    ("provider", "quality", "expected"),
    [
        ("fubon_neo", "realtime", "富邦 Neo｜即時"),
        ("finmind", "delayed", "FinMind｜延遲"),
        (None, None, "暫無資料｜暫無資料"),
    ],
)
def test_header_provider_and_quality(provider, quality, expected):
    quote = deepcopy(_full_data()["quote"])
    quote.update(provider=provider, data_quality=quality)
    line = _text_values(build_stock_dashboard_bubble(_full_data(quote=quote))["header"])[-1]
    assert expected in line


@pytest.mark.parametrize("quote", [None, {}, "invalid", [], {"price": None}])
def test_missing_quote_degrades_without_breaking_flex(quote):
    bubble = build_stock_dashboard_bubble(_full_data(quote=quote, price=None, change=None))
    texts = _text_values(bubble["header"])
    assert "暫無資料" in texts
    assert "暫無漲跌資料" in texts
    assert FlexContainer.from_dict(bubble) is not None


@pytest.mark.parametrize(
    ("score", "expected_score", "expected_gauge", "expected_stars"),
    [
        (82.6, "82.6", "████████░░", "★★★★☆"),
        (0, "0.0", "░░░░░░░░░░", "☆☆☆☆☆"),
        (100, "100.0", "██████████", "★★★★★"),
        (-1, "0.0", "░░░░░░░░░░", "☆☆☆☆☆"),
        (101, "100.0", "██████████", "★★★★★"),
        (None, "—", "░░░░░░░░░░", "☆☆☆☆☆"),
        (True, "—", "░░░░░░░░░░", "☆☆☆☆☆"),
    ],
)
def test_score_gauge_and_star_contract(score, expected_score, expected_gauge, expected_stars):
    score_card = build_stock_dashboard_bubble(_full_data(score=score))["body"]["contents"][0]
    texts = _text_values(score_card)
    assert expected_score in texts
    assert expected_gauge in texts
    assert expected_stars in texts


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [(85, "85%"), (85.6, "86%"), ("72", "72%"), (-1, "0%"), (101, "100%"), (None, "—"), (float("nan"), "—")],
)
def test_confidence_contract_is_preserved(confidence, expected):
    texts = _text_values(
        build_stock_dashboard_bubble(_full_data(confidence=confidence))["body"]["contents"][0]
    )
    assert "AI 信心度" in texts
    assert expected in texts


def test_score_card_keeps_composite_distinct():
    texts = _text_values(build_stock_dashboard_bubble(_full_data())["body"]["contents"][0])
    assert {"AI 技術分", "82.6", "綜合評分", "72.0", "AI 信心度", "85%"}.issubset(texts)
    assert "總分" not in texts


@pytest.mark.parametrize(
    ("decision", "risk", "expected"),
    [
        ("偏多", "中風險", {"📈 偏多", "分批布局", "⚠️", "中風險"}),
        ("偏空", "高風險", {"📉 偏空", "保守觀望", "⚠️", "高風險"}),
        (None, None, {"🔎 觀察", "耐心觀察", "⚠️", "未評估"}),
    ],
)
def test_decision_card_states(decision, risk, expected):
    texts = set(_text_values(
        build_stock_dashboard_bubble(_full_data(decision=decision, risk_level=risk))["body"]["contents"][1]
    ))
    assert expected.issubset(texts)


def test_four_aspect_grid_uses_only_available_contract_data():
    grid = build_stock_dashboard_bubble(_full_data())["body"]["contents"][2]
    texts = _text_values(grid)
    assert {"📈 技術", "💰 基本", "🏦 籌碼", "📰 新聞"}.issubset(texts)
    assert "83" in texts
    assert "多頭整理" in texts
    assert texts.count("—") == 3
    assert texts.count("資料未提供") == 3


def test_four_aspect_grid_accepts_future_optional_ui_fields_without_mutation():
    data = _full_data(
        financial_score=70, financial_summary="營運穩定",
        institution_score=65, institution_summary="法人偏多",
        news_score=60, news_summary="新聞中性",
    )
    original = deepcopy(data)
    texts = _text_values(build_stock_dashboard_bubble(data)["body"]["contents"][2])
    assert {"70", "營運穩定", "65", "法人偏多", "60", "新聞中性"}.issubset(texts)
    assert data == original


def test_ai_trend_extracts_existing_summary_contract():
    texts = _text_values(build_stock_dashboard_bubble(_full_data())["body"]["contents"][3])
    assert texts == ["AI 趨勢", "短線", "🟢 偏多", "中線", "🟡 震盪", "長線", "🟢 多頭"]


@pytest.mark.parametrize("summary", [None, "", "沒有固定標籤", 123])
def test_ai_trend_missing_contract_degrades_safely(summary):
    texts = _text_values(build_stock_dashboard_bubble(_full_data(ai_summary=summary))["body"]["contents"][3])
    assert texts.count("資料不足") == 3


def test_shopkeeper_alert_and_full_analysis_contracts():
    body = build_stock_dashboard_bubble(_full_data())["body"]["contents"]
    assert _text_values(body[4]) == ["🍊 阿柑店長", _full_data()["shopkeeper_message"]]
    assert _text_values(body[5]) == ["🔔 我的提醒", "目前沒有提醒", "＋新增提醒"]
    full = _text_values(body[6])
    assert "📈 完整分析" in full
    assert _full_data()["ai_summary"] in full
    assert _full_data()["explain"] in full


def test_long_explain_is_preserved_wrapped_and_sdk_parses():
    explain = "測" * 3000
    bubble = build_stock_dashboard_bubble(_full_data(explain=explain))
    full_card = bubble["body"]["contents"][6]
    text = next(item for item in _texts(full_card) if item["text"] == explain)
    assert text["wrap"] is True
    assert "maxLines" not in text
    assert FlexContainer.from_dict(bubble) is not None


def test_footer_actions_preserve_message_only_boundary():
    bubble = build_stock_dashboard_bubble(_full_data())
    buttons = _buttons(bubble["footer"])
    assert len(buttons) == 4
    assert [button["action"]["text"] for button in buttons] == [
        "2330", "我的自選", "設定提醒 2330", "2330"
    ]
    assert all(button["action"]["type"] == "message" for button in buttons)


def test_design_system_colors_are_present_without_layout_side_effects():
    serialized = json.dumps(build_stock_dashboard_bubble(_full_data()), ensure_ascii=False)
    for color in (BRAND, SUCCESS, WARNING):
        assert color in serialized
    assert RISK not in serialized  # medium-risk sample uses warning, not high-risk red
    high_risk = json.dumps(
        build_stock_dashboard_bubble(_full_data(decision="偏空", risk_level="高風險")),
        ensure_ascii=False,
    )
    assert RISK in high_risk


def test_unicode_special_characters_round_trip_and_builder_is_deterministic():
    value = "多空交錯 🚀\n引號：\"測試\"\\路徑"
    data = _full_data(shopkeeper_message=value, explain=value)
    original = deepcopy(data)
    first = build_stock_dashboard_bubble(data)
    second = build_stock_dashboard_bubble(data)
    restored = json.loads(json.dumps(first, ensure_ascii=False))
    assert first == second == restored
    assert value in _text_values(restored)
    assert data == original


@pytest.mark.parametrize("value", [True, ["value"], {"value": 1}])
def test_abnormal_text_input_types_do_not_crash_builder(value):
    bubble = build_stock_dashboard_bubble(
        _full_data(stock_code=value, stock_name=value, ai_summary=value, explain=value)
    )
    assert FlexContainer.from_dict(bubble) is not None


def test_json_sizes_are_recorded_and_remain_reasonable(capsys):
    normal = build_stock_dashboard_bubble(_full_data())
    long = build_stock_dashboard_bubble(_full_data(explain="測" * 3000))
    normal_size, long_size = _json_size(normal), _json_size(long)
    print(f"dashboard_v3_json_bytes={normal_size}")
    print(f"dashboard_v3_long_json_bytes={long_size}")
    assert 0 < normal_size < long_size
    assert long_size < 50_000


def test_snapshot_has_no_internal_provider_or_analysis_payload_fields():
    data = _full_data()
    data.update(
        contributions={"technical": {"score": 99}},
        signals=["internal"],
        lastUpdated="internal",
        total={"tradeVolume": 1},
    )
    serialized = json.dumps(build_stock_dashboard_bubble(data), ensure_ascii=False)
    assert "contributions" not in serialized
    assert "internal" not in serialized
    assert "lastUpdated" not in serialized
    assert "tradeVolume" not in serialized
