def get_risk_level(risk_score: int):
    if risk_score <= 20:
        return "🟢 很低風險"
    if risk_score <= 40:
        return "🟢 低風險"
    if risk_score <= 60:
        return "🟡 中等風險"
    if risk_score <= 80:
        return "🟠 高風險"
    return "🔴 很高風險"


def calculate_stop_loss_price(stock):
    technical = stock.get("technical") or {}

    price = stock.get("price")
    ma20 = technical.get("ma20")
    ma60 = technical.get("ma60")

    if ma20:
        return round(ma20, 2)

    if ma60:
        return round(ma60, 2)

    if price:
        return round(price * 0.93, 2)

    return None


def calculate_take_profit_price(stock):
    price = stock.get("price")
    high = stock.get("high")

    if high and price:
        return round(max(high, price * 1.08), 2)

    if price:
        return round(price * 1.08, 2)

    return None


def calculate_risk(stock):
    technical = stock.get("technical") or {}

    risk_score = 0
    reports = []

    price = stock.get("price")
    ma20 = technical.get("ma20")
    ma60 = technical.get("ma60")
    rsi = technical.get("rsi")
    k = technical.get("k")
    d = technical.get("d")
    macd = technical.get("macd")
    macd_signal = technical.get("signal")

    if rsi is not None:
        if rsi > 80:
            risk_score += 25
            reports.append("RSI 超過 80，短線過熱風險高")
        elif rsi > 70:
            risk_score += 15
            reports.append("RSI 高於 70，短線需留意追高風險")
        elif rsi < 30:
            risk_score += 15
            reports.append("RSI 低於 30，股價偏弱但可能接近超跌區")
        else:
            reports.append("RSI 位於相對正常區間")

    if k is not None and d is not None:
        if k < d:
            risk_score += 15
            reports.append("KD 呈現轉弱，短線動能需觀察")
        elif k > 80:
            risk_score += 10
            reports.append("KD 位於高檔，需留意鈍化或反轉")
        else:
            reports.append("KD 尚未出現明顯弱化訊號")

    if macd is not None and macd_signal is not None:
        if macd < macd_signal:
            risk_score += 20
            reports.append("MACD 位於 Signal 下方，動能偏弱")
        else:
            reports.append("MACD 仍維持相對多方動能")

    if price and ma20:
        if price < ma20:
            risk_score += 25
            reports.append("股價跌破 MA20，趨勢轉弱風險提高")
        else:
            reports.append("股價仍站在 MA20 上方")

    if price and ma60:
        if price < ma60:
            risk_score += 20
            reports.append("股價跌破 MA60，中期趨勢偏弱")
        else:
            reports.append("股價仍站在 MA60 上方")

    risk_score = min(risk_score, 100)

    return {
        "risk_score": risk_score,
        "risk_level": get_risk_level(risk_score),
        "stop_loss_price": calculate_stop_loss_price(stock),
        "take_profit_price": calculate_take_profit_price(stock),
        "reports": reports,
    }