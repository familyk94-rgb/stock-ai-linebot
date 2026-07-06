def get_health_level(health_score: int):
    if health_score >= 90:
        return "❤️❤️❤️❤️❤️ 極健康"
    if health_score >= 80:
        return "❤️❤️❤️❤️☆ 健康"
    if health_score >= 70:
        return "❤️❤️❤️⭐☆ 尚可"
    if health_score >= 60:
        return "❤️❤️⭐☆☆ 普通"
    if health_score >= 50:
        return "❤️⭐☆☆☆ 偏弱"
    return "💔 結構不健康"


def calculate_ma_health(stock):
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
    if price > ma20 and ma5 > ma10 > ma20:
        return 20
    if price > ma20:
        return 15
    if price > ma60:
        return 10
    return 5


def calculate_rsi_health(stock):
    technical = stock.get("technical") or {}
    rsi = technical.get("rsi")

    if rsi is None:
        return 5

    if 45 <= rsi <= 65:
        return 15
    if 40 <= rsi < 45 or 65 < rsi <= 70:
        return 12
    if 30 <= rsi < 40 or 70 < rsi <= 80:
        return 8
    return 4


def calculate_macd_health(stock):
    technical = stock.get("technical") or {}

    macd = technical.get("macd")
    signal = technical.get("signal")
    histogram = technical.get("histogram")

    if macd is None or signal is None or histogram is None:
        return 5

    if macd > signal and histogram > 0:
        return 20
    if macd > signal:
        return 15
    if histogram > 0:
        return 10
    return 5


def calculate_kd_health(stock):
    technical = stock.get("technical") or {}

    k = technical.get("k")
    d = technical.get("d")

    if k is None or d is None:
        return 5

    if k > d and 20 <= k <= 80:
        return 15
    if k > d:
        return 10
    if k < 20:
        return 8
    return 5


def calculate_price_health(stock):
    price = stock.get("price")
    high = stock.get("high")
    low = stock.get("low")

    if not all([price, high, low]):
        return 5

    price_range = high - low

    if price_range <= 0:
        return 5

    position = (price - low) / price_range

    if 0.4 <= position <= 0.8:
        return 15
    if position > 0.8:
        return 10
    return 6


def calculate_volume_health(stock):
    volume = stock.get("volume")

    if volume and volume > 0:
        return 10

    return 0


def calculate_health(stock):
    ma_score = calculate_ma_health(stock)
    rsi_score = calculate_rsi_health(stock)
    macd_score = calculate_macd_health(stock)
    kd_score = calculate_kd_health(stock)
    price_score = calculate_price_health(stock)
    volume_score = calculate_volume_health(stock)

    total = (
        ma_score
        + rsi_score
        + macd_score
        + kd_score
        + price_score
        + volume_score
    )

    total = min(total, 100)

    return {
        "health_score": total,
        "health_level": get_health_level(total),
        "details": {
            "ma": ma_score,
            "rsi": rsi_score,
            "macd": macd_score,
            "kd": kd_score,
            "price": price_score,
            "volume": volume_score,
        }
    }