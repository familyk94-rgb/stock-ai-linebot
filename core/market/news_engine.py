"""Local, rule-based analysis for normalized stock news."""

from __future__ import annotations

from typing import Any

from services.news_service import NewsService


POSITIVE_KEYWORDS = frozenset(
    {
        "成長",
        "創新高",
        "上修",
        "獲利",
        "增加",
        "擴產",
        "接單",
        "得標",
        "法說看好",
        "營收成長",
        "買超",
        "調升",
        "需求強勁",
        "轉盈",
        "配息",
        "合作",
        "新產品",
        "ai",
        "受惠",
    }
)
NEGATIVE_KEYWORDS = frozenset(
    {
        "下修",
        "虧損",
        "衰退",
        "減少",
        "跌停",
        "賣超",
        "調降",
        "需求疲弱",
        "裁員",
        "停工",
        "罰款",
        "訴訟",
        "調查",
        "缺料",
        "延期",
        "暴跌",
        "轉虧",
        "下滑",
        "風險",
        "警示",
    }
)

REQUIRED_SERVICE_KEYS = {"items", "count", "available"}
SPARSE_SCORE_CAPS = {1: 60, 2: 75, 3: 85}
TITLE_SIGNAL_LIMIT = 40


class NewsEngine:
    """Convert NewsService data into deterministic sentiment indicators."""

    def run(self, stock_code: str) -> dict:
        """Keep compatibility with the legacy MarketEngine interface."""
        return {}

    def analyze(self, stock_id: str) -> dict:
        if not isinstance(stock_id, str) or not stock_id.strip():
            return _news_fallback()

        try:
            news = NewsService().get_news(stock_id.strip())
        except Exception:
            return _news_fallback()

        if not isinstance(news, dict):
            return _news_fallback()
        if not REQUIRED_SERVICE_KEYS.issubset(news):
            return _news_fallback()
        if not news.get("available") or not isinstance(news.get("items"), list):
            return _news_fallback()

        items = [item for item in news["items"] if _is_valid_item(item)]
        if not items:
            return _news_fallback()

        sentiments = [_classify_title(item["title"]) for item in items]
        positive_count = sentiments.count("positive")
        negative_count = sentiments.count("negative")
        neutral_count = sentiments.count("neutral")
        score = _calculate_score(sentiments)

        return {
            "items": items,
            "count": len(items),
            "positive_count": positive_count,
            "negative_count": negative_count,
            "neutral_count": neutral_count,
            "score": score,
            "summary": _summary(score),
            "signals": _signals(
                items,
                positive_count,
                negative_count,
                neutral_count,
                score,
            ),
            "available": True,
        }


def _is_valid_item(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("title"), str)
        and bool(item["title"].strip())
    )


def _classify_title(title: str) -> str:
    normalized_title = title.casefold()
    has_positive = any(keyword in normalized_title for keyword in POSITIVE_KEYWORDS)
    has_negative = any(keyword in normalized_title for keyword in NEGATIVE_KEYWORDS)
    if has_positive and not has_negative:
        return "positive"
    if has_negative and not has_positive:
        return "negative"
    return "neutral"


def _calculate_score(sentiments: list[str]) -> int:
    values = {"positive": 100, "neutral": 50, "negative": 0}
    raw_score = int(sum(values[value] for value in sentiments) / len(sentiments) + 0.5)
    score = min(raw_score, SPARSE_SCORE_CAPS.get(len(sentiments), 100))
    return max(0, min(100, score))


def _summary(score: int) -> str:
    if score >= 80:
        return "新聞情緒偏多"
    if score >= 60:
        return "新聞情緒中性偏多"
    if score >= 40:
        return "新聞情緒中性"
    if score >= 20:
        return "新聞情緒中性偏空"
    return "新聞情緒偏空"


def _signals(
    items: list[dict],
    positive_count: int,
    negative_count: int,
    neutral_count: int,
    score: int,
) -> list[str]:
    latest_title = items[0]["title"].strip()
    if len(latest_title) > TITLE_SIGNAL_LIMIT:
        latest_title = f"{latest_title[:TITLE_SIGNAL_LIMIT]}…"
    return [
        f"近 7 日利多新聞 {positive_count} 則",
        f"近 7 日利空新聞 {negative_count} 則",
        f"近 7 日中立新聞 {neutral_count} 則",
        f"最新新聞：{latest_title}",
        f"新聞情緒分數 {score}",
    ]


def _news_fallback() -> dict:
    return {
        "items": [],
        "count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "neutral_count": 0,
        "score": 0,
        "summary": "尚未整合",
        "signals": [],
        "available": False,
    }
