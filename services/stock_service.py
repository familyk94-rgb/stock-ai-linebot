import os
import requests
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("FINMIND_API_TOKEN")
REQUEST_TIMEOUT = 10


def get_stock_info(stock_id: str):
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
        return None
    except requests.exceptions.RequestException:
        return None

    if r.status_code != 200:
        return None

    result = r.json()
    data = result.get("data", [])

    if not data:
        return None

    latest = data[-1]

    return {
        "stock_id": stock_id,
        "date": latest["date"],
        "close": latest["close"],
        "open": latest["open"],
        "max": latest["max"],
        "min": latest["min"],
        "volume": latest["Trading_Volume"],
    }


def get_stock_history(stock_id: str, days: int = 250):
    """
    取得最近 N 天歷史股價資料（給 technical_service 使用）
    """

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
        return []
    except requests.exceptions.RequestException:
        return []

    if r.status_code != 200:
        return []

    result = r.json()

    return result.get("data", [])
