class FundamentalService:
    def get_fundamental(self, stock_id: str) -> dict:
        return {
            "eps": None,
            "pe": None,
            "pb": None,
            "roe": None,
            "revenue_growth": None,
            "available": False,
        }
