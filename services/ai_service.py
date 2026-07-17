import json
import logging
import re
from time import perf_counter
from difflib import SequenceMatcher

from openai import OpenAI

from app.config import OPENAI_API_KEY
from core.explain_engine import build_analysis_sections
from services.cache_service import get_cache, set_cache
from core.observability import elapsed_ms, log_event
from services.usage_service import record_analysis_usage


logger = logging.getLogger(__name__)
OPENAI_TIMEOUT_SECONDS = 15
OPENAI_MODEL = "gpt-4.1-mini"
MAX_EXPLAIN_LENGTH = 3000
SUMMARY_LABELS = (
    "趨勢總結",
    "短線建議",
    "中線建議",
    "長線建議",
    "AI信心度",
)
EXPLAIN_LABELS = (
    "技術面",
    "基本面",
    "籌碼面",
    "新聞面",
    "綜合分析",
    "市場情緒",
    "操作建議",
    "風險提醒",
)
FORBIDDEN_EXPLAIN_TERMS = (
    "http://", "https://", "www.", "明確買進", "明確賣出",
    "強烈買進", "強烈賣出", "保證獲利", "必定上漲", "必定下跌",
    "無風險", "投資建議", "建議投資",
)
QUOTE_CONTRACT_FIELDS = (
    "symbol",
    "price",
    "reference_price",
    "change",
    "change_percent",
    "volume",
    "timestamp",
    "market",
    "provider",
    "status",
    "is_realtime",
    "data_quality",
)


def ai_stock_analysis(stock):
    stock = _analysis_market_data(stock)
    cache_key = f"ai_dashboard_v2_{stock['stock_id']}_{stock['date']}"
    cache_started = perf_counter()
    cache_elapsed = 0
    cache_error = None
    try:
        cached = get_cache(cache_key)
        cache_elapsed = elapsed_ms(cache_started)
    except Exception as error:
        cached = None
        cache_elapsed = elapsed_ms(cache_started)
        cache_error = error

    if isinstance(cached, dict):
        log_event(logger, "ai_cache_hit", result="cache_hit")
        fallback = _limit_analysis_explain(build_analysis_sections(stock))
        if not _is_valid_cached_analysis(cached):
            log_event(logger, "ai_cache_lookup_end", result="fallback", elapsed=cache_elapsed, error_type="InvalidCacheEntry", service="ai", cache_status="invalid")
            log_event(logger, "ai_analysis_end", result="fallback", error_type="InvalidCacheEntry")
            _track_usage(model=OPENAI_MODEL, result="fallback", cache_hit=False, openai_call=False)
            return fallback
        log_event(logger, "ai_cache_lookup_end", result="cache_hit", elapsed=cache_elapsed, service="ai", cache_status="hit")
        analysis = _limit_analysis_explain(cached, fallback=fallback)
        log_event(logger, "ai_analysis_end", result="cache_hit")
        _track_usage(model=OPENAI_MODEL, result="success", cache_hit=True, openai_call=False)
        return analysis

    if cache_error is not None:
        log_event(logger, "ai_cache_lookup_end", result="error", elapsed=cache_elapsed, error_type=type(cache_error).__name__, service="ai", cache_status="error")
    else:
        log_event(logger, "ai_cache_lookup_end", result="cache_miss", elapsed=cache_elapsed, service="ai", cache_status="miss")
    log_event(logger, "ai_cache_miss", result="cache_miss")
    fallback = _limit_analysis_explain(build_analysis_sections(stock))
    started_at = perf_counter()
    response = None
    try:
        client = _create_client()
    except Exception:
        log_event(logger, "openai_analysis_end", result="fallback", elapsed=elapsed_ms(started_at), error_type="ClientInitializationError")
        _track_usage(model=OPENAI_MODEL, result="fallback", cache_hit=False, openai_call=False)
        return fallback

    if client is None:
        log_event(logger, "openai_analysis_end", result="skipped", elapsed=elapsed_ms(started_at))
        _track_usage(model=OPENAI_MODEL, result="fallback", cache_hit=False, openai_call=False)
        return fallback

    cache_eligible = False
    try:
        prompt = _build_prompt(stock, fallback)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
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
        if analysis is fallback:
            log_event(logger, "openai_analysis_end", result="fallback", elapsed=elapsed_ms(started_at), error_type="InvalidAIResponse")
            usage_result = "fallback"
        else:
            log_event(logger, "openai_analysis_end", result="success", elapsed=elapsed_ms(started_at))
            usage_result = "success"
            cache_eligible = True
        response_model = getattr(response, "model", None)
        if not isinstance(response_model, str) or not response_model.strip():
            response_model = OPENAI_MODEL
        _track_usage(
            model=response_model,
            result=usage_result,
            cache_hit=False,
            openai_call=True,
            usage=getattr(response, "usage", None),
        )
    except Exception as error:
        result = "timeout" if type(error).__name__ in {"Timeout", "APITimeoutError", "TimeoutError"} else "fallback"
        log_event(logger, "openai_analysis_end", result=result, elapsed=elapsed_ms(started_at), error_type=type(error).__name__)
        response_model = getattr(response, "model", None)
        if not isinstance(response_model, str) or not response_model.strip():
            response_model = OPENAI_MODEL
        _track_usage(
            model=response_model,
            result=result,
            cache_hit=False,
            openai_call=True,
            usage=getattr(response, "usage", None),
        )
        analysis = fallback

    analysis = _limit_analysis_explain(analysis, fallback=fallback)
    if cache_eligible:
        _safe_set_cache(cache_key, analysis)
    return analysis


def _safe_set_cache(cache_key: str, analysis: dict) -> None:
    try:
        set_cache(cache_key, analysis)
    except Exception as error:
        try:
            log_event(
                logger,
                "service_fallback",
                result="fallback",
                error_type=type(error).__name__,
                service="ai",
                operation="cache_store",
            )
        except Exception:
            pass


def _analysis_market_data(stock: dict) -> dict:
    result = dict(stock)
    raw_quote = stock.get("quote")
    if isinstance(raw_quote, dict):
        quote = {field: raw_quote.get(field) for field in QUOTE_CONTRACT_FIELDS}
    else:
        quote = {
            "symbol": stock.get("stock_id"),
            "price": stock.get("price"),
            "reference_price": stock.get("reference_price"),
            "change": stock.get("change"),
            "change_percent": stock.get("change_percent"),
            "volume": stock.get("volume"),
            "timestamp": stock.get("timestamp"),
            "market": stock.get("market"),
            "provider": stock.get("provider"),
            "status": stock.get("status", "unknown"),
            "is_realtime": stock.get("is_realtime") is True,
            "data_quality": stock.get("quote_data_quality", "invalid"),
        }
    result["quote"] = quote
    if result.get("provider") is None:
        result["provider"] = quote.get("provider")
    return result


def _track_usage(**kwargs) -> None:
    try:
        record_analysis_usage(**kwargs)
    except Exception as error:
        log_event(logger, "usage_record_error", result="error", error_type=type(error).__name__, operation="stock_analysis")


def _create_client():
    api_key = (OPENAI_API_KEY or "").strip()
    if not api_key:
        return None
    return OpenAI(
        api_key=api_key,
        timeout=OPENAI_TIMEOUT_SECONDS,
        max_retries=0,
    )


def _build_prompt(stock: dict, fallback: dict) -> str:
    quote_contract = json.dumps(
        stock.get("quote", {}),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"""
Quote Contract: {quote_contract}
你是「股市柑仔店 AI 投資助理」，請用繁體中文分析台股。
股票名稱：{stock.get('stock_name', '')}
股票代號：{stock.get('stock_id', '')}
日期：{stock.get('date', '')}

請根據下列既有引擎結果潤飾文字，不得虛構未提供的基本面、籌碼面或市場情緒資料：

{fallback['ai_summary']}

{fallback['explain']}

詳細原因必須依序完整保留以下八個段落，不得省略或調換：
技術面、基本面、籌碼面、新聞面、綜合分析、市場情緒、操作建議、風險提醒。
新聞面必須排在綜合分析之前。不得輸出 URL、直接買賣建議、保證獲利或無風險等文字。

只回傳合法 JSON，不要 Markdown，不要額外說明：
{{
  "ai_summary": "摘要\\n趨勢總結：...\\n短線建議：...\\n中線建議：...\\n長線建議：...\\nAI信心度：...",
  "explain": "詳細原因\\n技術面：...\\n基本面：...\\n籌碼面：...\\n新聞面：...\\n綜合分析：...\\n市場情緒：...\\n操作建議：...\\n風險提醒：..."
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
    if _contains_forbidden_explain_text(explain):
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
    return all(
        _label_value(summary, label) for label in SUMMARY_LABELS
    ) and _has_ordered_labels(summary, SUMMARY_LABELS) and _has_ordered_explain_labels(explain)


def _has_ordered_explain_labels(explain: str) -> bool:
    return _has_ordered_labels(explain, EXPLAIN_LABELS)


def _has_ordered_labels(text: str, labels: tuple[str, ...]) -> bool:
    positions = []
    for label in labels:
        match = re.search(rf"(?:^|\n){re.escape(label)}：", text)
        if not match:
            return False
        positions.append(match.start())
    return positions == sorted(positions) and len(set(positions)) == len(positions)


def _contains_forbidden_explain_text(explain: str) -> bool:
    lowered = explain.casefold()
    return any(term.casefold() in lowered for term in FORBIDDEN_EXPLAIN_TERMS)


def _is_valid_cached_analysis(cached: dict) -> bool:
    summary = cached.get("ai_summary")
    explain = cached.get("explain")
    if not isinstance(summary, str) or not summary.strip():
        return False
    if not isinstance(explain, str) or not explain.strip():
        return False
    if not _has_required_labels(summary, explain):
        return False
    return not (
        _contains_forbidden_explain_text(summary)
        or _contains_forbidden_explain_text(explain)
    )


def _limit_analysis_explain(analysis: dict, fallback: dict | None = None) -> dict:
    if not isinstance(analysis, dict):
        return analysis
    result = dict(analysis)
    explain = result.get("explain")
    if isinstance(explain, str) and len(explain) > MAX_EXPLAIN_LENGTH:
        limited = _limit_explain_preserving_sections(explain, MAX_EXPLAIN_LENGTH)
        if limited is None and isinstance(fallback, dict):
            fallback_explain = fallback.get("explain")
            if isinstance(fallback_explain, str):
                limited = _limit_explain_preserving_sections(
                    fallback_explain,
                    MAX_EXPLAIN_LENGTH,
                )
        result["explain"] = limited or _minimal_explain()
    return result


def _limit_explain_preserving_sections(
    explain: str,
    max_length: int = MAX_EXPLAIN_LENGTH,
) -> str | None:
    if len(explain) <= max_length:
        return explain

    parsed = _parse_explain_sections(explain)
    if parsed is None:
        return None
    prefix, sections = parsed

    if len(prefix) > 100:
        prefix = f"{prefix[:99]}…"
    prefix_text = f"{prefix}\n" if prefix else ""
    separators_length = len(EXPLAIN_LABELS) - 1
    fixed_length = len(prefix_text) + separators_length + sum(
        len(label) + 1 for label in EXPLAIN_LABELS
    )
    content_budget = max(0, max_length - fixed_length)
    allocations = _fair_allocations(
        [len(content) for _, content in sections],
        content_budget,
    )

    rendered = []
    for (label, content), allocation in zip(sections, allocations):
        if len(content) <= allocation:
            value = content
        elif allocation <= 1:
            value = "…" if allocation == 1 else ""
        else:
            value = f"{content[: allocation - 1]}…"
        rendered.append(f"{label}：{value}")

    result = prefix_text + "\n".join(rendered)
    return result if len(result) <= max_length else None


def _parse_explain_sections(explain: str) -> tuple[str, list[tuple[str, str]]] | None:
    matches = []
    for label in EXPLAIN_LABELS:
        match = re.search(rf"(?m)^{re.escape(label)}：", explain)
        if not match:
            return None
        matches.append((label, match))
    if [match.start() for _, match in matches] != sorted(
        match.start() for _, match in matches
    ):
        return None

    prefix = explain[: matches[0][1].start()].strip()
    sections = []
    for index, (label, match) in enumerate(matches):
        end = matches[index + 1][1].start() if index + 1 < len(matches) else len(explain)
        sections.append((label, explain[match.end():end].strip()))
    return prefix, sections


def _fair_allocations(lengths: list[int], budget: int) -> list[int]:
    allocations = [0] * len(lengths)
    active = {index for index, length in enumerate(lengths) if length > 0}
    remaining = budget
    while active and remaining > 0:
        share = max(1, remaining // len(active))
        progressed = False
        for index in tuple(sorted(active)):
            grant = min(share, lengths[index] - allocations[index], remaining)
            allocations[index] += grant
            remaining -= grant
            progressed = progressed or grant > 0
            if allocations[index] >= lengths[index]:
                active.remove(index)
            if remaining == 0:
                break
        if not progressed:
            break
    return allocations


def _minimal_explain() -> str:
    return "詳細原因\n" + "\n".join(
        f"{label}：資料不足" for label in EXPLAIN_LABELS
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
