"""Source-level data quality and freshness contract."""

from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any
from zoneinfo import ZoneInfo


SOURCE_NAMES = ("price", "technical", "fundamental", "institution", "news")
TECHNICAL_FIELDS = (
    "trend",
    "ma_signal",
    "macd_signal",
    "rsi_signal",
    "ma5",
    "ma20",
    "rsi",
    "macd",
    "k",
    "d",
)


class DataQualityEngine:
    """Analyze existing market data without fetching or mutating anything."""

    def analyze(self, market_data: dict) -> dict:
        try:
            fetched_at = _taipei_now()
            if not isinstance(market_data, dict):
                return data_quality_fallback(fetched_at)
            return _analyze(market_data, fetched_at)
        except Exception:
            return data_quality_fallback()


def _analyze(market_data: dict, fetched_at: datetime) -> dict:
    today = fetched_at.date()
    price_date = _not_future(_valid_date(market_data.get("date")), today)
    price_available = _finite_number(market_data.get("price")) and price_date is not None

    technical = market_data.get("technical")
    technical_available = isinstance(technical, dict) and any(
        _valid_technical_value(technical.get(field)) for field in TECHNICAL_FIELDS
    )
    # Technical indicators are calculated from the same price history. Until the
    # technical layer exposes its own date, the validated price date is reused.
    technical_date = _not_future(_metadata_date(technical), today) or (
        price_date if technical_available else None
    )

    financial = market_data.get("financial")
    fundamental_not_applicable = (
        isinstance(financial, dict)
        and financial.get("applicability") == "not_applicable"
    )
    fundamental_available = (
        not fundamental_not_applicable
        and isinstance(financial, dict)
        and financial.get("available") is True
    )
    fundamental_date = (
        _not_future(_metadata_date(financial), today) if fundamental_available else None
    )

    institution = market_data.get("institution")
    institution_available = isinstance(institution, dict) and institution.get("available") is True
    institution_date = (
        _not_future(_metadata_date(institution), today) if institution_available else None
    )

    news = market_data.get("news")
    news_available = isinstance(news, dict) and news.get("available") is True
    news_date = (
        _not_future(_latest_news_date(news, today), today) if news_available else None
    )

    availability = {
        "price": price_available,
        "technical": technical_available,
        "fundamental": fundamental_available,
        "institution": institution_available,
        "news": news_available,
    }
    source_date_values = {
        "price": price_date,
        "technical": technical_date,
        "fundamental": fundamental_date,
        "institution": institution_date,
        "news": news_date,
    }
    not_applicable_sources = ["fundamental"] if fundamental_not_applicable else []
    applicable_sources = [name for name in SOURCE_NAMES if name not in not_applicable_sources]
    available_sources = [name for name in applicable_sources if availability[name]]
    missing_sources = [name for name in applicable_sources if not availability[name]]

    is_stale = any(
        (
            availability[name]
            and source_date_values[name] is not None
            and (today - source_date_values[name]).days > max_age
        )
        for name, max_age in (("price", 4), ("technical", 4), ("institution", 7), ("news", 7))
    )

    available_count = len(available_sources)
    applicable_count = len(applicable_sources)
    if not price_available or available_count < 2:
        status = "資料不足"
    elif available_count < applicable_count - 1 or is_stale:
        status = "部分資料"
    else:
        status = "正常"

    valid_dates = [value for value in source_date_values.values() if value is not None]
    as_of_date = max(valid_dates).isoformat() if valid_dates else None
    return {
        "status": status,
        "as_of_date": as_of_date,
        "fetched_at": fetched_at.isoformat(),
        "is_stale": is_stale,
        "available_sources": available_sources,
        "missing_sources": missing_sources,
        "not_applicable_sources": not_applicable_sources,
        "source_dates": {
            name: source_date_values[name].isoformat() if source_date_values[name] else None
            for name in SOURCE_NAMES
        },
        "data_completeness": round(available_count / applicable_count * 100),
    }


def data_quality_fallback(fetched_at: datetime | None = None) -> dict:
    return {
        "status": "資料不足",
        "as_of_date": None,
        "fetched_at": fetched_at.isoformat() if fetched_at is not None else None,
        "is_stale": False,
        "available_sources": [],
        "missing_sources": list(SOURCE_NAMES),
        "not_applicable_sources": [],
        "source_dates": {name: None for name in SOURCE_NAMES},
        "data_completeness": 0,
    }


def _taipei_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Taipei"))


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _valid_technical_value(value: Any) -> bool:
    if _finite_number(value):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and text not in {"未判定", "資料不足"}


def _valid_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _metadata_date(value: Any) -> date | None:
    if not isinstance(value, dict):
        return None
    for key in ("as_of_date", "source_date", "latest_date", "date"):
        parsed = _valid_date(value.get(key))
        if parsed is not None:
            return parsed
    return None


def _latest_news_date(news: dict, today: date) -> date | None:
    items = news.get("items")
    if not isinstance(items, list):
        return _not_future(_metadata_date(news), today)
    dates = [
        parsed
        for item in items
        if isinstance(item, dict)
        if (parsed := _not_future(_valid_date(item.get("date")), today)) is not None
    ]
    return max(dates, default=_not_future(_metadata_date(news), today))


def _not_future(value: date | None, today: date) -> date | None:
    if value is None or value > today:
        return None
    return value
