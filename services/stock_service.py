import os
import requests
import logging
from datetime import date, timedelta
from time import perf_counter
from dotenv import load_dotenv
from core.observability import elapsed_ms, log_event

load_dotenv()

TOKEN = os.getenv("FINMIND_API_TOKEN")
REQUEST_TIMEOUT = 10
logger = logging.getLogger(__name__)


def get_stock_info(stock_id: str):
    started_at = perf_counter()
    result = "error"
    error_type = None
    url = "https://api.finmindtrade.com/api/v4/data"

    start_date = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")

    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "token": TOKEN,
    }

    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        result = "timeout"
        error_type = "Timeout"
        log_event(logger, "price_request_end", result=result, elapsed=elapsed_ms(started_at), error_type=error_type, service="price", dataset="TaiwanStockPrice")
        return None
    except requests.exceptions.RequestException as error:
        result = "fallback"
        error_type = type(error).__name__
        log_event(logger, "price_request_end", result=result, elapsed=elapsed_ms(started_at), error_type=error_type, service="price", dataset="TaiwanStockPrice")
        return None

    if r.status_code != 200:
        log_event(logger, "price_request_end", result="fallback", elapsed=elapsed_ms(started_at), error_type="HttpStatus", service="price", dataset="TaiwanStockPrice")
        return None

    try:
        payload = r.json()
        data = payload.get("data", [])
    except (ValueError, TypeError, AttributeError) as error:
        log_event(logger, "price_request_end", result="error", elapsed=elapsed_ms(started_at), error_type=type(error).__name__, service="price", dataset="TaiwanStockPrice")
        raise

    if not data:
        log_event(logger, "price_request_end", result="fallback", elapsed=elapsed_ms(started_at), service="price", dataset="TaiwanStockPrice")
        return None

    try:
        latest = data[-1]
        stock = {
            "stock_id": stock_id,
            "date": latest["date"],
            "close": latest["close"],
            "open": latest["open"],
            "max": latest["max"],
            "min": latest["min"],
            "volume": latest["Trading_Volume"],
        }
    except Exception as error:
        log_event(logger, "price_request_end", result="error", elapsed=elapsed_ms(started_at), error_type=type(error).__name__, service="price", dataset="TaiwanStockPrice")
        raise
    log_event(logger, "price_request_end", result="success", elapsed=elapsed_ms(started_at), service="price", dataset="TaiwanStockPrice")
    return stock


def get_stock_history(stock_id: str, days: int = 250):
    """
    取得最近 N 天歷史股價資料（給 technical_service 使用）
    """

    started_at = perf_counter()
    url = "https://api.finmindtrade.com/api/v4/data"

    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "token": TOKEN,
    }

    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        log_event(logger, "price_history_request_end", result="timeout", elapsed=elapsed_ms(started_at), error_type="Timeout", service="technical", dataset="TaiwanStockPrice")
        return []
    except requests.exceptions.RequestException as error:
        log_event(logger, "price_history_request_end", result="fallback", elapsed=elapsed_ms(started_at), error_type=type(error).__name__, service="technical", dataset="TaiwanStockPrice")
        return []

    if r.status_code != 200:
        log_event(logger, "price_history_request_end", result="fallback", elapsed=elapsed_ms(started_at), error_type="HttpStatus", service="technical", dataset="TaiwanStockPrice")
        return []

    try:
        result = r.json()
        data = result.get("data", [])
    except (ValueError, TypeError, AttributeError) as error:
        log_event(logger, "price_history_request_end", result="error", elapsed=elapsed_ms(started_at), error_type=type(error).__name__, service="technical", dataset="TaiwanStockPrice")
        raise
    event_result = "success" if data else "fallback"
    log_event(logger, "price_history_request_end", result=event_result, elapsed=elapsed_ms(started_at), service="technical", dataset="TaiwanStockPrice")
    return data
