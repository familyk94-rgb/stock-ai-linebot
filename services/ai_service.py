import json
import logging
import re
from difflib import SequenceMatcher

from openai import OpenAI

from app.config import OPENAI_API_KEY
from core.explain_engine import build_analysis_sections
from services.cache_service import get_cache, set_cache


logger = logging.getLogger(__name__)
OPENAI_TIMEOUT_SECONDS = 15


def ai_stock_analysis(stock):
    cache_key = f"ai_dashboard_v2_{stock['stock_id']}_{stock['date']}"
    cached = get_cache(cache_key)

    if isinstance(cached, dict):
        return cached

    fallback = build_analysis_sections(stock)
    client = _create_client()

    if client is None:
        set_cache(cache_key, fallback)
        return fallback

    try:
        prompt = _build_prompt(stock, fallback)
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
        analysis = _parse_analysis(
            response.choices[0].message.content,
            fallback,
            require_missing_fundamental=not bool(stock.get("financial")),
            require_missing_chip=not bool(stock.get("institution")),
        )
    except Exception as error:
        logger.warning(
            "AI analysis failed; using local fallback (error_type=%s)",
            type(error).__name__,
        )
        analysis = fallback

    set_cache(cache_key, analysis)
    return analysis


def _create_client():
    api_key = (OPENAI_API_KEY or "").strip()
    if not api_key:
        logger.info("OpenAI API key is unavailable; using local fallback")
        return None
    return OpenAI(
        api_key=api_key,
        timeout=OPENAI_TIMEOUT_SECONDS,
        max_retries=0,
    )


def _build_prompt(stock: dict, fallback: dict) -> str:
    return f"""
你是「股市柑仔店 AI 投資助理」，請用繁體中文分析台股。
股票名稱：{stock.get('stock_name', '')}
股票代號：{stock.get('stock_id', '')}
日期：{stock.get('date', '')}

請根據下列既有引擎結果潤飾文字，不得虛構未提供的基本面、籌碼面或市場情緒資料：

{fallback['ai_summary']}

{fallback['explain']}

只回傳合法 JSON，不要 Markdown，不要額外說明：
{{
  "ai_summary": "摘要\\n趨勢總結：...\\n短線建議：...\\n中線建議：...\\n長線建議：...\\nAI信心度：...",
  "explain": "詳細原因\\n技術面：...\\n基本面：...\\n籌碼面：...\\n市場情緒：...\\n操作建議：...\\n風險提醒：..."
}}

摘要只寫結論與不同時間尺度建議；詳細原因只寫依據、操作與風險，兩區不要重複句子。
基本面或籌碼面沒有資料時必須寫「尚未整合」。內容總長不超過 420 字，不得保證獲利。
"""


def _parse_analysis(
    content: str,
    fallback: dict,
    require_missing_fundamental: bool = False,
    require_missing_chip: bool = False,
) -> dict:
    try:
        result = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return fallback

    if not isinstance(result, dict):
        return fallback

    summary = result.get("ai_summary")
    explain = result.get("explain")

    if not isinstance(summary, str) or not isinstance(explain, str):
        return fallback
    if not _has_required_labels(summary, explain):
        return fallback
    if require_missing_fundamental and _label_value(explain, "基本面") != "尚未整合":
        return fallback
    if require_missing_chip and _label_value(explain, "籌碼面") != "尚未整合":
        return fallback
    if _has_significant_overlap(summary, explain):
        return fallback

    return {
        "ai_summary": summary.strip(),
        "explain": explain.strip(),
    }


def _has_required_labels(summary: str, explain: str) -> bool:
    summary_labels = ("趨勢總結：", "短線建議：", "中線建議：", "長線建議：", "AI信心度：")
    explain_labels = ("技術面：", "基本面：", "籌碼面：", "市場情緒：", "操作建議：", "風險提醒：")
    return all(_label_value(summary, label.rstrip("：")) for label in summary_labels) and all(
        _label_value(explain, label.rstrip("：")) for label in explain_labels
    )


def _label_value(text: str, label: str) -> str | None:
    match = re.search(
        rf"(?:^|\n){re.escape(label)}：([^\n]*)",
        text,
    )
    if not match:
        return None
    return match.group(1).strip() or None


def _has_significant_overlap(summary: str, explain: str) -> bool:
    summary_parts = _content_parts(summary)
    explain_parts = _content_parts(explain)

    for summary_part in summary_parts:
        for explain_part in explain_parts:
            shorter_length = min(len(summary_part), len(explain_part))
            if shorter_length < 8:
                continue
            if summary_part in explain_part or explain_part in summary_part:
                return True
            if SequenceMatcher(None, summary_part, explain_part).ratio() >= 0.8:
                return True
    return False


def _content_parts(text: str) -> list[str]:
    parts = []
    for line in text.splitlines():
        value = line.split("：", 1)[-1]
        for sentence in re.split(r"[。！？!?；;]+", value):
            normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", sentence).lower()
            if normalized:
                parts.append(normalized)
    return parts
