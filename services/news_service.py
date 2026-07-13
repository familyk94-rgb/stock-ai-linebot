"""FinMind news data access and normalization."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any
from time import perf_counter
from zoneinfo import ZoneInfo

import requests

from app.config import FINMIND_API_TOKEN
from core.observability import elapsed_ms, log_event


logger = logging.getLogger(__name__)

FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
NEWS_DATASET = "TaiwanStockNews"
REQUEST_TIMEOUT = 10
MAX_NEWS_ITEMS = 20

# Keep the upstream schema mapping in one place so callers only see stable keys.
_NEWS_FIELDS = {
    "date": "date",
    "title": "title",
    "source": "source",
    "url": "link",
}


def _fallback() -> dict:
    return {"items": [], "count": 0, "available": False}


def _clean_text(value: Any, *, collapse_whitespace: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    value = " ".join(value.split()) if collapse_whitespace else value.strip()
    return value


def _parse_news_date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    return None


def _normalize_title(title: str) -> str:
    return " ".join(title.split()).lower()


class NewsService:
    """Retrieve and normalize recent stock news from FinMind."""

    def get_news(self, stock_id: str) -> dict:
        if not isinstance(stock_id, str) or not stock_id.strip():
            return _fallback()

        end_date = datetime.now(ZoneInfo("Asia/Taipei")).date()
        start_date = end_date - timedelta(days=6)
        token = (os.getenv("FINMIND_TOKEN") or FINMIND_API_TOKEN or "").strip()
        params = {
            "dataset": NEWS_DATASET,
            "data_id": stock_id.strip(),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "token": token,
        }

        started_at = perf_counter()
        try:
            response = requests.get(
                FINMIND_API_URL,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code != 200:
                log_event(logger, "finmind_request_end", result="fallback", elapsed=elapsed_ms(started_at), error_type="HttpStatus", service="news", dataset=NEWS_DATASET)
                return _fallback()
            payload = response.json()
        except (requests.Timeout, requests.RequestException, ValueError) as exc:
            result = "timeout" if isinstance(exc, requests.Timeout) else "fallback"
            log_event(logger, "finmind_request_end", result=result, elapsed=elapsed_ms(started_at), error_type=type(exc).__name__, service="news", dataset=NEWS_DATASET)
            return _fallback()

        if not isinstance(payload, dict):
            log_event(logger, "finmind_request_end", result="fallback", elapsed=elapsed_ms(started_at), error_type="InvalidPayload", service="news", dataset=NEWS_DATASET)
            return _fallback()
        if payload.get("status") != 200:
            log_event(logger, "finmind_request_end", result="fallback", elapsed=elapsed_ms(started_at), error_type="ApiStatus", service="news", dataset=NEWS_DATASET)
            return _fallback()

        raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            log_event(logger, "finmind_request_end", result="fallback", elapsed=elapsed_ms(started_at), error_type="InvalidData", service="news", dataset=NEWS_DATASET)
            return _fallback()

        log_event(logger, "finmind_request_end", result="success", elapsed=elapsed_ms(started_at), service="news", dataset=NEWS_DATASET)
        cleaned_items = []
        for raw_item in raw_items:
            cleaned = self._clean_item(raw_item)
            if cleaned is not None:
                cleaned_items.append(cleaned)

        cleaned_items.sort(key=lambda item: item["_datetime"], reverse=True)

        unique_items = []
        seen_urls: set[str] = set()
        seen_titles_without_url: set[str] = set()
        for item in cleaned_items:
            url = item["url"]
            if url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
            else:
                normalized_title = _normalize_title(item["title"])
                if normalized_title in seen_titles_without_url:
                    continue
                seen_titles_without_url.add(normalized_title)

            unique_items.append(
                {
                    "date": item["date"],
                    "title": item["title"],
                    "source": item["source"],
                    "url": item["url"],
                }
            )
            if len(unique_items) == MAX_NEWS_ITEMS:
                break

        return {
            "items": unique_items,
            "count": len(unique_items),
            "available": bool(unique_items),
        }

    @staticmethod
    def _clean_item(raw_item: Any) -> dict | None:
        if not isinstance(raw_item, dict):
            return None

        parsed_date = _parse_news_date(raw_item.get(_NEWS_FIELDS["date"]))
        title = _clean_text(
            raw_item.get(_NEWS_FIELDS["title"]), collapse_whitespace=True
        )
        if parsed_date is None or not title:
            return None

        return {
            "_datetime": parsed_date,
            "date": parsed_date.date().isoformat(),
            "title": title,
            "source": _clean_text(raw_item.get(_NEWS_FIELDS["source"])),
            "url": _clean_text(raw_item.get(_NEWS_FIELDS["url"])),
        }
