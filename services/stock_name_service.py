import os
import json
import requests
from datetime import datetime, timedelta
from app.config import FINMIND_API_TOKEN

CACHE_FILE = "data/stock_names.json"
CACHE_DAYS = 7


def is_cache_valid():
    if not os.path.exists(CACHE_FILE):
        return False

    modified_time = datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
    return datetime.now() - modified_time < timedelta(days=CACHE_DAYS)


def download_stock_names():
    url = "https://api.finmindtrade.com/api/v4/data"

    params = {
        "dataset": "TaiwanStockInfo",
        "token": FINMIND_API_TOKEN,
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        return {}

    data = response.json().get("data", [])

    stock_names = {}

    for item in data:
        stock_id = str(item.get("stock_id", "")).strip()
        stock_name = str(item.get("stock_name", "")).strip()

        if stock_id and stock_name:
            stock_names[stock_id] = stock_name

    os.makedirs("data", exist_ok=True)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(stock_names, f, ensure_ascii=False, indent=2)

    return stock_names


def load_stock_names():
    if is_cache_valid():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return download_stock_names()


def get_stock_name(stock_id: str):
    stock_names = load_stock_names()
    return stock_names.get(stock_id, "未知股票")