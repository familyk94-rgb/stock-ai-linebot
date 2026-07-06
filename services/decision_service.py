from services.strategy_service import get_strategy
from services.risk_service import calculate_risk


def calculate_consensus(stock):
    technical = stock.get("technical") or {}

    signals = []

    price = stock.get("price")
    ma20 = technical.get("ma20")
    ma60 = technical.get("ma60")
    k = technical.get("k")
    d = technical.get("d")
    macd = technical.get("macd")
    macd_signal = technical.get("signal")
    rsi = technical.get("rsi")

    if price and ma20:
        signals.append(price > ma20)

    if price and ma60:
        signals.append(price > ma60)

    if k is not None and d is not None:
        signals.append(k > d)

    if macd is not None and macd_signal is not None:
        signals.append(macd > macd_signal)

    if rsi is not None:
        signals.append(40 <= rsi <= 70)

    if not signals:
        return 0

    positive_count = sum(1 for s in signals if s)
    return int((positive_count / len(signals)) * 100)


def get_decision(stock):
    ai_index = stock.get("ai_index") or {}
    score = ai_index.get("score", 0)

    strategy = get_strategy(stock)
    risk = calculate_risk(stock)
    consensus = calculate_consensus(stock)

    if score >= 85 and risk["risk_score"] <= 40 and consensus >= 70:
        decision = "可分批布局"
    elif score >= 70 and risk["risk_score"] <= 60:
        decision = "多方觀察"
    elif score >= 60:
        decision = "觀望等待"
    else:
        decision = "不建議進場"

    return {
        "decision": decision,
        "ai_index": score,
        "stars": ai_index.get("stars"),
        "signal": ai_index.get("signal"),
        "consensus": consensus,
        "risk_score": risk["risk_score"],
        "risk_level": risk["risk_level"],
        "strategy": strategy,
        "risk": risk,
    }