def get_strategy(stock):
    ai_index = stock.get("ai_index") or {}
    technical = stock.get("technical") or {}

    score = ai_index.get("score", 0)
    signal = ai_index.get("signal", "中性觀望")

    price = stock.get("price")
    ma10 = technical.get("ma10")
    ma20 = technical.get("ma20")
    rsi = technical.get("rsi")
    k = technical.get("k")
    d = technical.get("d")
    macd = technical.get("macd")
    macd_signal = technical.get("signal")

    if score >= 90:
        entry = "可分批布局"
        holding = "建議續抱"
        add_position = "拉回 MA10 可觀察加碼"
        take_profit = "短線急漲可分批停利"
        stop_loss = "跌破 MA20 需提高警覺"
        risk_level = "中低風險"

    elif score >= 80:
        entry = "可小量分批布局"
        holding = "可續抱觀察"
        add_position = "不建議追高，等拉回"
        take_profit = "接近近期高點可部分停利"
        stop_loss = "跌破 MA20 可考慮減碼"
        risk_level = "中等風險"

    elif score >= 70:
        entry = "觀察為主，可等待確認"
        holding = "持有者可觀察"
        add_position = "暫不建議加碼"
        take_profit = "反彈接近壓力區可停利"
        stop_loss = "跌破 MA20 或轉弱需減碼"
        risk_level = "中等偏高風險"

    elif score >= 60:
        entry = "暫時觀望"
        holding = "持有者需留意轉弱"
        add_position = "不建議加碼"
        take_profit = "有獲利可分批落袋"
        stop_loss = "跌破 MA60 或支撐區需停損"
        risk_level = "偏高風險"

    else:
        entry = "不建議進場"
        holding = "持有者應審慎評估"
        add_position = "不建議加碼"
        take_profit = "反彈可考慮減碼"
        stop_loss = "跌破關鍵支撐應嚴格控管"
        risk_level = "高風險"

    warnings = []

    if rsi and rsi > 75:
        warnings.append("RSI 偏高，短線可能過熱")
    if k and d and k < d:
        warnings.append("KD 轉弱，留意短線修正")
    if macd is not None and macd_signal is not None and macd < macd_signal:
        warnings.append("MACD 偏弱，動能需觀察")
    if price and ma20 and price < ma20:
        warnings.append("股價跌破 MA20，趨勢轉弱風險提高")

    if not warnings:
        warnings.append("目前主要技術條件尚未出現明顯警訊")

    return {
        "signal": signal,
        "entry": entry,
        "holding": holding,
        "add_position": add_position,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "risk_level": risk_level,
        "warnings": warnings,
    }