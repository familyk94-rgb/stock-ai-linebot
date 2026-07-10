from services.fundamental_service import FundamentalService


REQUIRED_SERVICE_KEYS = {
    "eps",
    "pe",
    "pb",
    "roe",
    "revenue_growth",
    "available",
}


class FundamentalEngine:
    def analyze(self, stock_id: str) -> dict:
        service = FundamentalService()
        try:
            fundamental = service.get_fundamental(stock_id)
        except Exception:
            return _fundamental_fallback()

        if not isinstance(fundamental, dict):
            return _fundamental_fallback()
        if not REQUIRED_SERVICE_KEYS.issubset(fundamental):
            return _fundamental_fallback()

        return {
            "eps": fundamental.get("eps"),
            "pe": fundamental.get("pe"),
            "pb": fundamental.get("pb"),
            "roe": fundamental.get("roe"),
            "revenue_growth": fundamental.get("revenue_growth"),
            "score": 0,
            "summary": "尚未整合",
            "signals": [],
            "available": bool(fundamental.get("available")),
        }


def _fundamental_fallback() -> dict:
    return {
        "eps": None,
        "pe": None,
        "pb": None,
        "roe": None,
        "revenue_growth": None,
        "score": 0,
        "summary": "尚未整合",
        "signals": [],
        "available": False,
    }
