from services.stock_service import get_stock_info
from services.stock_name_service import get_stock_name


class StockEngine:
    """
    Stock Engine v1.0
    只負責取得股票基本行情，不呼叫 AI Core。
    """

    def run(self, stock_code: str) -> dict:
        stock_code = str(stock_code).strip()

        stock = get_stock_info(stock_code) or {}
        stock_name = get_stock_name(stock_code) or ""

        if not stock:
            return {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "date": "-",
                "price": None,
                "open": None,
                "high": None,
                "low": None,
                "change": None,
                "change_percent": None,
                "volume": None,
            }

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "date": stock.get("date", "-"),
            "price": stock.get("close"),
            "open": stock.get("open"),
            "high": stock.get("max"),
            "low": stock.get("min"),
            "change": stock.get("change"),
            "change_percent": stock.get("change_percent"),
            "volume": stock.get("volume"),
        }