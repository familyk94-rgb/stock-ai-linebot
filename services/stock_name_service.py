import os
import json
import requests
import logging
from datetime import datetime, timedelta
from time import perf_counter
from app.config import FINMIND_API_TOKEN
from core.observability import elapsed_ms, log_event

logger = logging.getLogger(__name__)

CACHE_FILE = "data/stock_names.json"
CACHE_DAYS = 7
REQUEST_TIMEOUT = 10


def is_cache_valid():
    if not os.path.exists(CACHE_FILE):
        return False

    modified_time = datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
    return datetime.now() - modified_time < timedelta(days=CACHE_DAYS)


def download_stock_names():
    data, _ = _download_stock_names_with_result()
    return data


def _download_stock_names_with_result():
    url = "https://api.finmindtrade.com/api/v4/data"

    params = {
        "dataset": "TaiwanStockInfo",
        "token": FINMIND_API_TOKEN,
    }

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return {}, "timeout"
    except requests.exceptions.RequestException:
        return {}, "fallback"

    if response.status_code != 200:
        return {}, "fallback"

    try:
        data = response.json().get("data", [])
    except (ValueError, TypeError, AttributeError):
        raise

    stock_names = {}

    for item in data:
        stock_id = str(item.get("stock_id", "")).strip()
        stock_name = str(item.get("stock_name", "")).strip()

        if stock_id and stock_name:
            stock_names[stock_id] = {
                "stock_id": stock_id,
                "stock_name": stock_name,
            }

    os.makedirs("data", exist_ok=True)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(stock_names, f, ensure_ascii=False, indent=2)

    return stock_names, "success" if stock_names else "fallback"


def load_stock_names():
    if is_cache_valid():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return download_stock_names()


def get_stock_name(stock_id: str):
    started_at = perf_counter()
    result = "error"
    error_type = None
    try:
        stock_id = str(stock_id).strip()
        if is_cache_valid():
            stock_names = load_stock_names()
            result = "cache_hit"
        else:
            stock_names, result = _download_stock_names_with_result()
        stock = stock_names.get(stock_id)
        return stock["stock_name"] if stock else "未知股票"
    except Exception as error:
        error_type = type(error).__name__
        raise
    finally:
        log_event(
            logger,
            "stock_name_lookup_end",
            result=result,
            elapsed=elapsed_ms(started_at),
            error_type=error_type,
            cache_status="hit" if result == "cache_hit" else "miss",
        )


def find_stock_by_name(keyword: str):
    keyword = str(keyword).strip()
    stock_names = load_stock_names()

    results = []

    for stock_id, stock in stock_names.items():
        stock_name = stock["stock_name"]

        if keyword in stock_name:
            results.append({
                "stock_id": stock_id,
                "stock_name": stock_name,
            })

    return results


def get_stock_id_by_name(keyword: str):
    results = find_stock_by_name(keyword)

    if not results:
        return None

    return results[0]["stock_id"]
