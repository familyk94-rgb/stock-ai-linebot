import logging
import math
import os
from datetime import date, timedelta

import requests

from app.config import FINMIND_API_TOKEN


logger = logging.getLogger(__name__)
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
REQUEST_TIMEOUT_SECONDS = 10


class FundamentalService:
    def get_fundamental(self, stock_id: str) -> dict:
        stock_id = str(stock_id or "").strip()
        if not stock_id:
            return _unavailable_result()

        per_rows = self._fetch_dataset("TaiwanStockPER", stock_id, days=45)
        revenue_rows = self._fetch_dataset(
            "TaiwanStockMonthRevenue",
            stock_id,
            days=450,
        )
        statement_rows = self._fetch_dataset(
            "TaiwanStockFinancialStatements",
            stock_id,
            days=550,
        )

        per_data = _parse_per(per_rows)
        revenue_growth = _parse_revenue_growth(revenue_rows)
        eps = _parse_eps(statement_rows)

        result = {
            "eps": eps,
            "pe": per_data["pe"],
            "pb": per_data["pb"],
            "roe": None,
            "revenue_growth": revenue_growth,
            "dividend_yield": per_data["dividend_yield"],
        }
        result["available"] = any(value is not None for value in result.values())
        return result

    def _fetch_dataset(self, dataset: str, stock_id: str, days: int) -> list[dict]:
        end_date = date.today()
        params = {
            "dataset": dataset,
            "data_id": stock_id,
            "start_date": (end_date - timedelta(days=days)).isoformat(),
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
                "FinMind dataset unavailable (dataset=%s, error_type=%s)",
                dataset,
                type(error).__name__,
            )
            return []

        if not isinstance(payload, dict):
            logger.warning("FinMind dataset returned invalid JSON structure (dataset=%s)", dataset)
            return []
        if payload.get("status") != 200:
            logger.warning("FinMind dataset returned unsuccessful API status (dataset=%s)", dataset)
            return []
        if not isinstance(payload.get("data"), list):
            logger.warning("FinMind dataset returned invalid data structure (dataset=%s)", dataset)
            return []
        return [row for row in payload["data"] if isinstance(row, dict)]


def _parse_per(rows: list[dict]) -> dict:
    return {
        "pe": _latest_valid_value(rows, "PER"),
        "pb": _latest_valid_value(rows, "PBR"),
        "dividend_yield": _latest_valid_value(rows, "dividend_yield"),
    }


def _parse_revenue_growth(rows: list[dict]) -> float | None:
    latest = _latest_row(rows)
    if not latest:
        return None

    direct_growth = _safe_float(latest.get("revenue_year_growth"))
    if direct_growth is not None:
        return direct_growth

    latest_revenue = _safe_float(latest.get("revenue"))
    latest_year = _safe_int(latest.get("revenue_year"))
    latest_month = _safe_int(latest.get("revenue_month"))
    if latest_revenue is None or latest_year is None or latest_month is None:
        return None

    previous = next(
        (
            row
            for row in rows
            if _safe_int(row.get("revenue_year")) == latest_year - 1
            and _safe_int(row.get("revenue_month")) == latest_month
        ),
        None,
    )
    previous_revenue = _safe_float(previous.get("revenue")) if previous else None
    if previous_revenue in (None, 0):
        return None
    return round((latest_revenue - previous_revenue) / abs(previous_revenue) * 100, 2)


def _parse_eps(rows: list[dict]) -> float | None:
    # FinMind 此資料集無法可靠區分單季與累計 EPS；僅取最新有效 EPS，
    # 不進行跨季度成長比較。
    eps_rows = [row for row in rows if row.get("type") == "EPS"]
    return _latest_valid_value(eps_rows, "value")


def _latest_row(rows: list[dict]) -> dict | None:
    return max(rows, key=lambda row: str(row.get("date") or ""), default=None)


def _latest_valid_value(rows: list[dict], field: str) -> float | None:
    ordered_rows = sorted(
        rows,
        key=lambda row: str(row.get("date") or ""),
        reverse=True,
    )
    for row in ordered_rows:
        value = _safe_float(row.get(field))
        if value is not None:
            return value
    return None


def _safe_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_int(value) -> int | None:
    number = _safe_float(value)
    return int(number) if number is not None else None


def _unavailable_result() -> dict:
    return {
        "eps": None,
        "pe": None,
        "pb": None,
        "roe": None,
        "revenue_growth": None,
        "dividend_yield": None,
        "available": False,
    }
