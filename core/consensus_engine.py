def get_consensus_level(score: int):
    if score >= 90:
        return "★★★★★ 完全一致"
    if score >= 80:
        return "★★★★☆ 高度一致"
    if score >= 70:
        return "★★★★ 中度一致"
    if score >= 60:
        return "★★★☆ 普通一致"
    if score >= 50:
        return "★★★ 分歧增加"
    return "★★ 指標分歧"


def calculate_consensus(stock):
    technical = stock.get("technical") or {}

    price = stock.get("price")
    ma20 = technical.get("ma20")
    ma60 = technical.get("ma60")

    k = technical.get("k")
    d = technical.get("d")

    macd = technical.get("macd")
    signal = technical.get("signal")

    rsi = technical.get("rsi")

    positive = 0
    total = 0

    details = []

    # MA
    if price and ma20:
        total += 1
        if price > ma20:
            positive += 1
            details.append(("MA20", "✅ 偏多"))
        else:
            details.append(("MA20", "❌ 偏空"))

    if price and ma60:
        total += 1
        if price > ma60:
            positive += 1
            details.append(("MA60", "✅ 偏多"))
        else:
            details.append(("MA60", "❌ 偏空"))

    # KD
    if k is not None and d is not None:
        total += 1
        if k > d:
            positive += 1
            details.append(("KD", "✅ 黃金交叉"))
        else:
            details.append(("KD", "❌ 死亡交叉"))

    # MACD
    if macd is not None and signal is not None:
        total += 1
        if macd > signal:
            positive += 1
            details.append(("MACD", "✅ 多方"))
        else:
            details.append(("MACD", "❌ 空方"))

    # RSI
    if rsi is not None:
        total += 1
        if 45 <= rsi <= 70:
            positive += 1
            details.append(("RSI", "✅ 健康"))
        elif rsi > 70:
            details.append(("RSI", "⚠ 過熱"))
        else:
            details.append(("RSI", "❌ 偏弱"))

    if total == 0:
        consensus = 0
    else:
        consensus = round((positive / total) * 100)

    return {
        "consensus_score": consensus,
        "consensus_level": get_consensus_level(consensus),
        "positive": positive,
        "total": total,
        "details": details,
    }