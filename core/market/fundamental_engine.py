from services.fundamental_service import FundamentalService


REQUIRED_SERVICE_KEYS = {
    "eps",
    "pe",
    "pb",
    "roe",
    "revenue_growth",
    "dividend_yield",
    "available",
}


class FundamentalEngine:
    def analyze(self, stock_id: str) -> dict:
        try:
            fundamental = FundamentalService().get_fundamental(stock_id)
        except Exception:
            return _fundamental_fallback()

        if not isinstance(fundamental, dict):
            return _fundamental_fallback()
        if not REQUIRED_SERVICE_KEYS.issubset(fundamental):
            return _fundamental_fallback()
        if not fundamental.get("available"):
            return _fundamental_fallback()

        score, signals = _score_fundamental(fundamental)
        return {
            "eps": fundamental.get("eps"),
            "pe": fundamental.get("pe"),
            "pb": fundamental.get("pb"),
            "roe": None,
            "revenue_growth": fundamental.get("revenue_growth"),
            "dividend_yield": fundamental.get("dividend_yield"),
            "score": score,
            "summary": _summary(score),
            "signals": signals,
            "available": True,
        }


def _score_fundamental(data: dict) -> tuple[int, list[str]]:
    scores = []
    signals = []

    eps = data.get("eps")
    if eps is not None:
        scores.append(100 if eps > 0 else 0)
        signals.append("EPS 為正值" if eps > 0 else "EPS 非正值")

    pe = data.get("pe")
    if pe is not None and pe > 0:
        if pe <= 15:
            scores.append(100)
            signals.append("本益比偏低")
        elif pe <= 25:
            scores.append(70)
            signals.append("本益比合理")
        else:
            scores.append(30)
            signals.append("本益比偏高")

    pb = data.get("pb")
    if pb is not None and pb > 0:
        if pb <= 1.5:
            scores.append(100)
            signals.append("股價淨值比偏低")
        elif pb <= 4:
            scores.append(70)
            signals.append("股價淨值比合理")
        else:
            scores.append(30)
            signals.append("股價淨值比偏高")

    growth = data.get("revenue_growth")
    if growth is not None:
        if growth > 10:
            scores.append(100)
            signals.append("月營收年增逾 10%")
        elif growth >= 0:
            scores.append(70)
            signals.append("月營收小幅成長")
        else:
            scores.append(20)
            signals.append("月營收年減")

    dividend_yield = data.get("dividend_yield")
    if dividend_yield is not None:
        if dividend_yield >= 4:
            scores.append(100)
            signals.append("殖利率較高")
        elif dividend_yield >= 2:
            scores.append(70)
            signals.append("殖利率中等")
        else:
            scores.append(30)
            signals.append("殖利率偏低")

    score = round(sum(scores) / len(scores)) if scores else 0
    sparse_caps = {1: 60, 2: 75, 3: 85}
    score = min(score, sparse_caps.get(len(scores), 100))
    return max(0, min(100, score)), signals


def _summary(score: int) -> str:
    if score >= 70:
        return "基本面偏佳"
    if score >= 40:
        return "基本面中性"
    return "基本面偏弱"


def _fundamental_fallback() -> dict:
    return {
        "eps": None,
        "pe": None,
        "pb": None,
        "roe": None,
        "revenue_growth": None,
        "dividend_yield": None,
        "score": 0,
        "summary": "尚未整合",
        "signals": [],
        "available": False,
    }
