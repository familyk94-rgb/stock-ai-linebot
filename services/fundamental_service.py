import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime, timedelta
from time import perf_counter
from zoneinfo import ZoneInfo

import requests

from app.config import FINMIND_API_TOKEN
from core.observability import elapsed_ms, log_event
from services.source_cache_service import CacheCopyError, get_or_load


logger = logging.getLogger(__name__)
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
REQUEST_TIMEOUT_SECONDS = 10
FUNDAMENTAL_CACHE_TTL_SECONDS = 300
FUNDAMENTAL_CACHE_SCHEMA_VERSION = "v1"
DATASET_REQUESTS = (
    ("per", "TaiwanStockPER", 45),
    ("revenue", "TaiwanStockMonthRevenue", 450),
    ("statements", "TaiwanStockFinancialStatements", 550),
)


class _DatasetRows(list):
    def __init__(self, rows, *, cacheable: bool):
        super().__init__(rows)
        self.cacheable = cacheable


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
        start_date, end_date = _request_date_range(days)
        key = (
            "fundamental",
            FUNDAMENTAL_CACHE_SCHEMA_VERSION,
            dataset,
            stock_id,
            start_date,
            end_date,
        )
        try:
            result = get_or_load(
                key=key,
                ttl_seconds=FUNDAMENTAL_CACHE_TTL_SECONDS,
                loader=lambda: self._fetch_dataset_uncached(
                    dataset, stock_id, start_date, end_date
                ),
                is_cacheable=lambda rows: (
                    isinstance(rows, _DatasetRows) and rows.cacheable
                ),
                service="fundamental",
                dataset=dataset,
            )
        except CacheCopyError:
            return []
        return list(result.value) if isinstance(result.value, list) else []

    def _fetch_dataset_uncached(
        self,
        dataset: str,
        stock_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        started_at = _safe_profile_start()
        params = {
            "dataset": dataset,
            "data_id": stock_id,
            "start_date": start_date,
            "end_date": end_date,
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
        raw_rows = payload["data"]
        return _DatasetRows(
            [row for row in raw_rows if isinstance(row, dict)],
            cacheable=_cacheable_rows(dataset, raw_rows),
        )


def _request_date_range(days: int) -> tuple[str, str]:
    end_date = _taipei_today()
    return (end_date - timedelta(days=days)).isoformat(), end_date.isoformat()


def _taipei_today():
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


def _cacheable_rows(dataset: str, value) -> bool:
    if not isinstance(value, list) or not value:
        return False
    validator = {
        "TaiwanStockPER": _valid_per_row,
        "TaiwanStockMonthRevenue": _valid_revenue_row,
        "TaiwanStockFinancialStatements": _valid_statement_row,
    }.get(dataset)
    return validator is not None and all(validator(row) for row in value)


def _valid_per_row(row) -> bool:
    return (
        isinstance(row, dict)
        and _valid_date(row.get("date"))
        and any(
            _valid_cache_number(row.get(field))
            for field in ("PER", "PBR", "dividend_yield")
        )
    )


def _valid_revenue_row(row) -> bool:
    if not isinstance(row, dict) or not _valid_date(row.get("date")):
        return False
    if _valid_cache_number(row.get("revenue_year_growth")):
        return True
    year_value = row.get("revenue_year")
    month_value = row.get("revenue_month")
    month = _safe_int(month_value)
    return (
        _valid_cache_number(row.get("revenue"))
        and _valid_cache_integer(year_value)
        and _valid_cache_integer(month_value)
        and 1 <= month <= 12
    )


def _valid_statement_row(row) -> bool:
    return (
        isinstance(row, dict)
        and _valid_date(row.get("date"))
        and isinstance(row.get("type"), str)
        and bool(row["type"].strip())
        and _valid_cache_number(row.get("value"))
    )


def _valid_date(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_cache_number(value) -> bool:
    return not isinstance(value, bool) and _safe_float(value) is not None


def _valid_cache_integer(value) -> bool:
    return not isinstance(value, bool) and _safe_int(value) is not None


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
