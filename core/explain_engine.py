def explain_ai_index(stock, analysis):
    ai_index = analysis.get("ai_index") or {}
    details = ai_index.get("details") or {}

    explanations = []

    trend = details.get("trend", 0)
    momentum = details.get("momentum", 0)
    strength = details.get("strength", 0)
    price = details.get("price", 0)
    volume = details.get("volume", 0)

    explanations.append(f"📈 趨勢分數：{trend}/25")
    explanations.append(f"🚀 動能分數：{momentum}/20")
    explanations.append(f"🌡 強弱分數：{strength}/15")
    explanations.append(f"💰 價格位置：{price}/15")
    explanations.append(f"📊 成交量：{volume}/10")

    summary = []

    if trend >= 20:
        summary.append("均線結構偏多")
    elif trend >= 10:
        summary.append("均線仍有支撐")
    else:
        summary.append("均線結構偏弱")

    if momentum >= 15:
        summary.append("動能表現偏強")
    elif momentum >= 8:
        summary.append("動能中性")
    else:
        summary.append("動能偏弱")

    if strength >= 12:
        summary.append("RSI 位於相對健康區")
    elif strength <= 6:
        summary.append("RSI 顯示風險升高")

    return {
        "score_reason": explanations,
        "summary": summary,
    }