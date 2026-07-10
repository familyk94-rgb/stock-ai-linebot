from services.stock_service import get_stock_info
from services.technical_service import get_technical_indicators
from services.stock_name_service import get_stock_name
from core.ganzai_ai import GanzaiAI
from core.data_quality import calculate_data_completeness


def format_number(value):
    try:
        return f"{int(value):,}"
    except Exception:
        return "-"


def format_price(value):
    try:
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{float(value):,.2f}"
    except Exception:
        return "-"


def get_market_info(stock_id: str) -> dict:
    stock_id = str(stock_id).strip()

    stock_name = get_stock_name(stock_id) or ""

    stock = get_stock_info(stock_id)

    if not stock:
        return {
            "stock_id": stock_id,
            "stock_code": stock_id,
            "stock_name": stock_name,
            "date": "-",
            "price": None,
            "open": None,
            "high": None,
            "low": None,
            "change": None,
            "change_percent": None,
            "volume": None,
            "price_text": "-",
            "open_text": "-",
            "high_text": "-",
            "low_text": "-",
            "volume_text": "-",
            "trend": "資料不足",
            "ma_signal": "資料不足",
            "macd_signal": "資料不足",
            "rsi_signal": "資料不足",
            "technical": {},
            "core": {"data_completeness": 0},
        }

    technical = get_technical_indicators(stock_id) or {}

    stock_data = {
        "stock_id": stock_id,
        "stock_code": stock_id,
        "stock_name": stock_name,
        "date": stock.get("date", "-"),

        "price": stock.get("close"),
        "open": stock.get("open"),
        "high": stock.get("max"),
        "low": stock.get("min"),
        "change": stock.get("change"),
        "change_percent": stock.get("change_percent"),
        "volume": stock.get("volume"),

        "price_text": format_price(stock.get("close")),
        "open_text": format_price(stock.get("open")),
        "high_text": format_price(stock.get("max")),
        "low_text": format_price(stock.get("min")),
        "volume_text": format_number(stock.get("volume")),

        "trend": technical.get("trend", "未判定"),
        "ma_signal": technical.get("ma_signal", "未判定"),
        "macd_signal": technical.get("macd_signal", "未判定"),
        "rsi_signal": technical.get("rsi_signal", "未判定"),

        "technical": technical,
    }

    try:
        ai = GanzaiAI(stock_data)
        stock_data["core"] = ai.run() or {}
    except Exception as e:
        print(f"[GanzaiAI Error] {e}")
        stock_data["core"] = {
            "data_completeness": calculate_data_completeness(stock_data)
        }

    return stock_data
