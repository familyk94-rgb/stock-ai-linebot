from core.market.stock_engine import StockEngine
from core.market.technical_engine import TechnicalEngine
from core.market.financial_engine import FinancialEngine
from core.market.institution_engine import InstitutionEngine
from core.market.news_engine import NewsEngine


class MarketEngine:
    """
    Market Core v1.0
    所有市場資料的唯一入口。
    """

    def __init__(self):
        self.stock_engine = StockEngine()
        self.technical_engine = TechnicalEngine()
        self.financial_engine = FinancialEngine()
        self.institution_engine = InstitutionEngine()
        self.news_engine = NewsEngine()

    def run(self, stock_code: str) -> dict:
        stock_code = str(stock_code).strip()

        stock_data = self.stock_engine.run(stock_code)
        technical_data = self.technical_engine.run(stock_code)
        financial_data = self.financial_engine.run(stock_code)
        institution_data = self.institution_engine.run(stock_code)
        news_data = self.news_engine.run(stock_code)

        return {
            "stock_code": stock_code,
            "stock_name": stock_data.get("stock_name", ""),
            "date": stock_data.get("date", "-"),
            "price": stock_data.get("price"),
            "change": stock_data.get("change"),
            "change_percent": stock_data.get("change_percent"),
            "volume": stock_data.get("volume"),
            "technical": technical_data,
            "financial": financial_data,
            "institution": institution_data,
            "news": news_data,
            "_raw": {
                "stock": stock_data,
                "technical": technical_data,
                "financial": financial_data,
                "institution": institution_data,
                "news": news_data,
            },
        }