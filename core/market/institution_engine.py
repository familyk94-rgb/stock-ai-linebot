from services.institution_service import InstitutionService


SCORE_FIELDS = (
    ("foreign_buy_sell", "外資"),
    ("investment_buy_sell", "投信"),
    ("dealer_buy_sell", "自營商"),
    ("three_major_buy_sell", "三大法人合計"),
)
REQUIRED_SERVICE_KEYS = {
    "foreign_buy_sell",
    "investment_buy_sell",
    "dealer_buy_sell",
    "three_major_buy_sell",
    "foreign_streak",
    "investment_streak",
    "dealer_streak",
    "available",
}


class InstitutionEngine:
    def run(self, stock_code: str) -> dict:
        """保留舊 MarketEngine 空殼介面；正式分析流程使用 analyze。"""
        return {}

    def analyze(self, stock_id: str) -> dict:
        try:
            institution = InstitutionService().get_institution(stock_id)
        except Exception:
            return _institution_fallback()

        if not isinstance(institution, dict):
            return _institution_fallback()
        if not REQUIRED_SERVICE_KEYS.issubset(institution):
            return _institution_fallback()
        if not institution.get("available"):
            return _institution_fallback()

        score, signals = _score_institution(institution)
        if not signals:
            return _institution_fallback()

        return {
            "foreign_buy_sell": institution.get("foreign_buy_sell"),
            "investment_buy_sell": institution.get("investment_buy_sell"),
            "dealer_buy_sell": institution.get("dealer_buy_sell"),
            "three_major_buy_sell": institution.get("three_major_buy_sell"),
            "foreign_streak": institution.get("foreign_streak"),
            "investment_streak": institution.get("investment_streak"),
            "dealer_streak": institution.get("dealer_streak"),
            "score": score,
            "summary": _summary(score),
            "signals": signals,
            "available": True,
        }


def _score_institution(data: dict) -> tuple[int, list[str]]:
    scores = []
    signals = []
    for key, label in SCORE_FIELDS:
        value = data.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue

        scores.append(100 if value > 0 else 0 if value < 0 else 50)
        signals.append(_format_signal(label, value))

    if not scores:
        return 0, []

    score = round(sum(scores) / len(scores))
    sparse_caps = {1: 60, 2: 75, 3: 85}
    score = min(score, sparse_caps.get(len(scores), 100))
    return max(0, min(100, score)), signals


def _format_signal(label: str, value: int | float) -> str:
    amount = abs(value)
    amount_text = f"{int(amount):,}" if float(amount).is_integer() else f"{amount:,.2f}"
    if value > 0:
        return f"{label}買超 {amount_text} 張"
    if value < 0:
        return f"{label}賣超 {amount_text} 張"
    return f"{label}持平"


def _summary(score: int) -> str:
    if score >= 80:
        return "籌碼偏多"
    if score >= 60:
        return "籌碼中性偏多"
    if score >= 40:
        return "籌碼中性"
    if score >= 20:
        return "籌碼中性偏空"
    return "籌碼偏空"


def _institution_fallback() -> dict:
    return {
        "foreign_buy_sell": None,
        "investment_buy_sell": None,
        "dealer_buy_sell": None,
        "three_major_buy_sell": None,
        "foreign_streak": None,
        "investment_streak": None,
        "dealer_streak": None,
        "score": 0,
        "summary": "尚未整合",
        "signals": [],
        "available": False,
    }
