def get_stars(score: int):
    if score >= 90:
        return "★★★★★"
    if score >= 80:
        return "★★★★☆"
    if score >= 70:
        return "★★★★"
    if score >= 60:
        return "★★★☆"
    if score >= 50:
        return "★★★"
    if score >= 40:
        return "★★"
    return "★"


def get_signal(score: int):
    if score >= 90:
        return "🟢 強勢多頭"
    if score >= 80:
        return "🟢 偏多強勢"
    if score >= 70:
        return "🟡 多方觀察"
    if score >= 60:
        return "🟡 盤整偏多"
    if score >= 50:
        return "🟠 中性觀望"
    if score >= 40:
        return "🟠 偏弱"
    return "🔴 弱勢"


def calculate_trend_score(stock):
    technical = stock.get("technical") or {}

    price = stock.get("price")
    ma5 = technical.get("ma5")
    ma10 = technical.get("ma10")
    ma20 = technical.get("ma20")
    ma60 = technical.get("ma60")

    if not all([price, ma5, ma10, ma20, ma60]):
        return 5

    if price > ma5 > ma10 > ma20 > ma60:
        return 25
    if price > ma20 and ma5 > ma10:
        return 20
    if price > ma20:
        return 15
    if price > ma60:
        return 10
    return 5


def calculate_momentum_score(stock):
    technical = stock.get("technical") or {}

    macd = technical.get("macd")
    signal = technical.get("signal")
    histogram = technical.get("histogram")
    k = technical.get("k")
    d = technical.get("d")

    score = 0

    if macd is not None and signal is not None and histogram is not None:
        if macd > signal and histogram > 0:
            score += 12
        elif macd > signal:
            score += 9
        elif histogram > 0:
            score += 6
        else:
            score += 3

    if k is not None and d is not None:
        if k > d and 20 <= k <= 80:
            score += 8
        elif k > d:
            score += 6
        elif k < 20:
            score += 5
        else:
            score += 2

    return min(score, 20)


def calculate_strength_score(stock):
    technical = stock.get("technical") or {}
    rsi = technical.get("rsi")

    if rsi is None:
        return 5

    if 50 <= rsi <= 70:
        return 15
    if 40 <= rsi < 50:
        return 12
    if 70 < rsi <= 80:
        return 10
    if 30 <= rsi < 40:
        return 8
    if rsi > 80:
        return 5
    return 6


def calculate_price_score(stock):
    close_price = stock.get("price")
    open_price = stock.get("open")
    high_price = stock.get("high")
    low_price = stock.get("low")

    if not all([close_price, open_price, high_price, low_price]):
        return 5

    price_range = high_price - low_price

    if price_range <= 0:
        return 5

    close_position = (close_price - low_price) / price_range

    if close_position >= 0.8:
        return 15
    if close_price > open_price:
        return 12
    if close_position >= 0.4:
        return 8
    return 4


def calculate_volume_score(stock):
    volume = stock.get("volume")

    if volume and volume > 0:
        return 10

    return 0


def calculate_ai_index(stock):
    trend_score = calculate_trend_score(stock)
    momentum_score = calculate_momentum_score(stock)
    strength_score = calculate_strength_score(stock)
    price_score = calculate_price_score(stock)
    volume_score = calculate_volume_score(stock)

    total_score = (
        trend_score
        + momentum_score
        + strength_score
        + price_score
        + volume_score
    )

    return {
        "score": total_score,
        "stars": get_stars(total_score),
        "signal": get_signal(total_score),
        "details": {
            "trend": trend_score,
            "momentum": momentum_score,
            "strength": strength_score,
            "price": price_score,
            "volume": volume_score,
        }
    }