import logging
import math
import os
from datetime import date, datetime, timedelta

import requests

from app.config import FINMIND_API_TOKEN


logger = logging.getLogger(__name__)
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
DATASET = "TaiwanStockInstitutionalInvestorsBuySell"
REQUEST_TIMEOUT_SECONDS = 10


class InstitutionService:
    def get_institution(self, stock_id: str) -> dict:
        stock_id = str(stock_id or "").strip()
        if not stock_id:
            return _fallback()

        rows = self._fetch(stock_id)
        if not rows:
            return _fallback()

        dated_rows = [
            (row, parsed_date)
            for row in rows
            if (parsed_date := _parse_date(row.get("date"))) is not None
        ]
        if not dated_rows:
            return _fallback()

        latest_date = max(parsed_date for _, parsed_date in dated_rows)
        latest_rows = [row for row, parsed_date in dated_rows if parsed_date == latest_date]

        foreign_names = {"Foreign_Investor", "Foreign_Dealer_Self"}
        foreign = _net_for_names(latest_rows, foreign_names)
        investment = _net_for_names(latest_rows, {"Investment_Trust"})
        dealer = _net_for_names(latest_rows, {"Dealer_self", "Dealer_Hedging"})
        valid_major_values = [
            value for value in (foreign, investment, dealer) if value is not None
        ]
        three_major = sum(valid_major_values) if valid_major_values else None

        values = (foreign, investment, dealer, three_major)
        return {
            "foreign_buy_sell": foreign,
            "investment_buy_sell": investment,
            "dealer_buy_sell": dealer,
            "three_major_buy_sell": three_major,
            "foreign_streak": _streak(rows, foreign_names),
            "investment_streak": _streak(rows, {"Investment_Trust"}),
            "dealer_streak": _streak(rows, {"Dealer_self", "Dealer_Hedging"}),
            "available": any(value is not None for value in values),
        }

    def _fetch(self, stock_id: str) -> list[dict]:
        end_date = date.today()
        params = {
            "dataset": DATASET,
            "data_id": stock_id,
            "start_date": (end_date - timedelta(days=45)).isoformat(),
            "end_date": end_date.isoformat(),
        }
        token = (os.getenv("FINMIND_TOKEN") or FINMIND_API_TOKEN or "").strip()
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        try:
            response = requests.get(
                FINMIND_API_URL,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.Timeout, requests.RequestException, ValueError) as error:
            logger.warning(
                "FinMind institution data unavailable (error_type=%s)",
                type(error).__name__,
            )
            return []

        if not isinstance(payload, dict) or payload.get("status") != 200:
            return []
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]


def _net_for_names(rows: list[dict], names: set[str]) -> float | None:
    total = 0.0
    found = False
    for row in rows:
        if row.get("name") not in names:
            continue
        buy = _safe_float(row.get("buy"))
        sell = _safe_float(row.get("sell"))
        if buy is None or sell is None:
            continue
        total += buy - sell
        found = True
    return total if found else None


def _streak(rows: list[dict], names: set[str]) -> int | None:
    dates = sorted(
        {
            parsed_date
            for row in rows
            if (parsed_date := _parse_date(row.get("date"))) is not None
        },
        reverse=True,
    )
    daily_values = []
    for row_date in dates:
        day_rows = [row for row in rows if _parse_date(row.get("date")) == row_date]
        value = _net_for_names(day_rows, names)
        if value is not None:
            daily_values.append(value)

    if not daily_values:
        return None
    if daily_values[0] == 0:
        return 0

    direction = 1 if daily_values[0] > 0 else -1
    count = 0
    for value in daily_values:
        if value == 0 or (1 if value > 0 else -1) != direction:
            break
        count += 1
    return count * direction


def _safe_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_date(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def _fallback() -> dict:
    return {
        "foreign_buy_sell": None,
        "investment_buy_sell": None,
        "dealer_buy_sell": None,
        "three_major_buy_sell": None,
        "foreign_streak": None,
        "investment_streak": None,
        "dealer_streak": None,
        "available": False,
    }
