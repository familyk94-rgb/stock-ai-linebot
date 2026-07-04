import os
import requests
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("FINMIND_API_TOKEN")


def get_stock_info(stock_id: str):
    url = "https://api.finmindtrade.com/api/v4/data"

    start_date = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")

    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "token": TOKEN,
    }

    r = requests.get(url, params=params)

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