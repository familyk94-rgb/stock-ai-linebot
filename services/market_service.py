from services.stock_service import get_stock_info
from services.technical_service import get_technical_indicators
from services.stock_name_service import get_stock_name


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


def get_market_info(stock_id: str):
    stock = get_stock_info(stock_id)

    if not stock:
        return None

    technical = get_technical_indicators(stock_id)
    stock_name = get_stock_name(stock_id)

    print("========== DEBUG ==========")
    print("stock_id =", stock_id)
    print("stock_name =", stock_name)
    print("===========================")

    return {
        "stock_id": stock_id,
        "stock_name": stock_name,
        "date": stock["date"],

        "price": stock["close"],
        "open": stock["open"],
        "high": stock["max"],
        "low": stock["min"],
        "volume": stock["volume"],

        "price_text": format_price(stock["close"]),
        "open_text": format_price(stock["open"]),
        "high_text": format_price(stock["max"]),
        "low_text": format_price(stock["min"]),
        "volume_text": format_number(stock["volume"]),

        "technical": technical,
    }