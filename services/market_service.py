from services.stock_service import get_stock_info


STOCK_NAMES = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2303": "聯電",
    "2308": "台達電",
    "2412": "中華電",
    "0050": "元大台灣50",
    "0056": "元大高股息",
}


def format_number(value):
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def format_price(value):
    try:
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)


def get_stock_name(stock_id: str):
    return STOCK_NAMES.get(stock_id, "未知股票")


def get_market_info(stock_id: str):
    stock = get_stock_info(stock_id)

    if not stock:
        return None

    stock_name = get_stock_name(stock_id)

    close_price = stock["close"]
    open_price = stock["open"]
    high_price = stock["max"]
    low_price = stock["min"]
    volume = stock["volume"]

    return {
        "stock_id": stock_id,
        "stock_name": stock_name,
        "date": stock["date"],
        "price": close_price,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "volume": volume,
        "price_text": format_price(close_price),
        "open_text": format_price(open_price),
        "high_text": format_price(high_price),
        "low_text": format_price(low_price),
        "volume_text": format_number(volume),
    }