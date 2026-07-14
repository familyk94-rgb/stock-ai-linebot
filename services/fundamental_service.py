import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import date, timedelta
from time import perf_counter

import requests

from app.config import FINMIND_API_TOKEN
from core.observability import elapsed_ms, log_event


logger = logging.getLogger(__name__)
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
REQUEST_TIMEOUT_SECONDS = 10
DATASET_REQUESTS = (
    ("per", "TaiwanStockPER", 45),
    ("revenue", "TaiwanStockMonthRevenue", 450),
    ("statements", "TaiwanStockFinancialStatements", 550),
)


class FundamentalService:
    def get_fundamental(self, stock_id: str, asset: dict | None = None) -> dict:
        applicability = _asset_applicability(asset)
        if applicability == "not_applicable":
            return _unavailable_result(applicability)

        stock_id = str(stock_id or "").strip()
        if not stock_id:
            return _unavailable_result(applicability)

        rows_by_key = self._fetch_datasets(stock_id)
        per_rows = rows_by_key["per"]
        revenue_rows = rows_by_key["revenue"]
        statement_rows = rows_by_key["statements"]

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
        result["applicability"] = applicability
        return result

    def _fetch_datasets(self, stock_id: str) -> dict[str, list[dict]]:
        futures = {}
        with ThreadPoolExecutor(max_workers=len(DATASET_REQUESTS)) as executor:
            for key, dataset, days in DATASET_REQUESTS:
                context = copy_context()
                futures[key] = executor.submit(
                    context.run,
                    self._run_dataset_task,
                    dataset,
                    stock_id,
                    days,
                )

            rows_by_key = {}
            for key, _, _ in DATASET_REQUESTS:
                try:
                    rows = futures[key].result()
                except Exception:
                    rows = []
                rows_by_key[key] = rows if isinstance(rows, list) else []
        return rows_by_key

    def _run_dataset_task(self, dataset: str, stock_id: str, days: int) -> list[dict]:
        try:
            return self._fetch_dataset(dataset, stock_id, days)
        except Exception as error:
            _safe_request_event(
                dataset,
                result="error",
                started_at=None,
                error_type=type(error).__name__,
            )
            return []

    def _fetch_dataset(self, dataset: str, stock_id: str, days: int) -> list[dict]:
        started_at = _safe_profile_start()
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
            result = "timeout" if isinstance(error, requests.Timeout) else "fallback"
            _safe_request_event(dataset, result=result, started_at=started_at, error_type=type(error).__name__)
            return []
        except Exception as error:
            _safe_request_event(
                dataset,
                result="error",
                started_at=started_at,
                error_type=type(error).__name__,
            )
            return []

        if not isinstance(payload, dict):
            _safe_request_event(dataset, result="fallback", started_at=started_at, error_type="InvalidPayload")
            return []
        if payload.get("status") != 200:
            _safe_request_event(dataset, result="fallback", started_at=started_at, error_type="ApiStatus")
            return []
        if not isinstance(payload.get("data"), list):
            _safe_request_event(dataset, result="fallback", started_at=started_at, error_type="InvalidData")
            return []
        _safe_request_event(dataset, result="success", started_at=started_at)
        return [row for row in payload["data"] if isinstance(row, dict)]


def _safe_profile_start():
    try:
        return perf_counter()
    except Exception:
        return None


def _safe_request_event(
    dataset: str,
    *,
    result: str,
    started_at,
    error_type: str | None = None,
) -> None:
    try:
        try:
            elapsed = elapsed_ms(started_at)
        except Exception:
            elapsed = 0
        log_event(
            logger,
            "finmind_request_end",
            result=result,
            elapsed=elapsed,
            error_type=error_type,
            service="fundamental",
            dataset=dataset,
        )
    except Exception:
        return


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


def _asset_applicability(asset) -> str:
    if not isinstance(asset, dict):
        return "unknown"
    if asset.get("type") == "etf":
        return "not_applicable"
    if asset.get("type") == "stock":
        return "applicable"
    return "unknown"


def _unavailable_result(applicability: str = "unknown") -> dict:
    return {
        "eps": None,
        "pe": None,
        "pb": None,
        "roe": None,
        "revenue_growth": None,
        "dividend_yield": None,
        "available": False,
        "applicability": applicability,
    }
