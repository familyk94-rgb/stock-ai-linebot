import importlib
import json
from types import SimpleNamespace

import services.ai_service as ai_service
from core.explain_engine import build_analysis_sections
from services.cache_service import CACHE


def _stock(date: str = "2026-07-10") -> dict:
    return {
        "stock_id": "2330",
        "stock_name": "台積電",
        "date": date,
        "price": 90,
        "technical": {"ma20": 100, "ma60": 80, "rsi": 55},
        "core": {
            "trend": "整理",
            "decision": "觀察",
            "confidence": 75,
            "risk_level": "中等風險",
        },
    }


def test_no_api_key_import_and_fallback(monkeypatch):
    CACHE.clear()
    module = importlib.reload(ai_service)
    monkeypatch.setattr(module, "OPENAI_API_KEY", "")

    result = module.ai_stock_analysis(_stock("no-key"))

    assert "趨勢總結：" in result["ai_summary"]
    assert "技術面：" in result["explain"]


def test_timeout_uses_fallback(monkeypatch):
    CACHE.clear()
    observed = {}

    class FakeCompletions:
        def create(self, **kwargs):
            observed["timeout"] = kwargs.get("timeout")
            raise TimeoutError("simulated timeout")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(ai_service, "_create_client", lambda: fake_client)

    result = ai_service.ai_stock_analysis(_stock("timeout"))

    assert observed["timeout"] == 15
    assert result == build_analysis_sections(_stock("timeout"))


def test_duplicate_model_response_is_rejected():
    fallback = build_analysis_sections(_stock("duplicate"))
    repeated = "目前趨勢偏弱建議保守觀察"
    model_result = {
        "ai_summary": (
            f"摘要\n趨勢總結：{repeated}\n短線建議：避免追高\n"
            "中線建議：等待轉強\n長線建議：持續追蹤\nAI信心度：75%"
        ),
        "explain": (
            f"詳細原因\n技術面：{repeated}\n基本面：尚未整合\n"
            "籌碼面：尚未整合\n市場情緒：中性\n操作建議：觀察\n風險提醒：控制部位"
        ),
    }

    result = ai_service._parse_analysis(
        json.dumps(model_result, ensure_ascii=False),
        fallback,
        require_missing_fundamental=True,
        require_missing_chip=True,
    )

    assert result == fallback


def test_missing_fundamental_and_chip_are_preserved():
    fallback = build_analysis_sections(_stock("missing-data"))

    assert "基本面：尚未整合" in fallback["explain"]
    assert "籌碼面：尚未整合" in fallback["explain"]


def test_model_cannot_replace_missing_data_status():
    fallback = build_analysis_sections(_stock("invalid-missing-data"))
    model_result = {
        "ai_summary": (
            "摘要\n趨勢總結：整理\n短線建議：觀察\n中線建議：等待\n"
            "長線建議：追蹤\nAI信心度：75%"
        ),
        "explain": (
            "詳細原因\n技術面：中性\n基本面：未知\n籌碼面：資料不足\n"
            "市場情緒：中性\n操作建議：觀察\n風險提醒：控制部位"
        ),
    }

    result = ai_service._parse_analysis(
        json.dumps(model_result, ensure_ascii=False),
        fallback,
        require_missing_fundamental=True,
        require_missing_chip=True,
    )

    assert result == fallback


def test_stock_price_is_used_for_mid_term_advice():
    result = build_analysis_sections(_stock("stock-price"))

    assert "中線建議：尚未站回 MA20 前以保守觀察為主。" in result["ai_summary"]
