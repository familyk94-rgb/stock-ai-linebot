MARKET_FIELDS = ("price", "open", "high", "low", "volume", "change_percent")
TECHNICAL_FIELDS = (
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "rsi",
    "k",
    "d",
    "macd",
    "signal",
    "histogram",
)
CONTEXT_FIELDS = ("financial", "institution", "news")


def calculate_data_completeness(stock: dict) -> int:
    """計算分析輸入欄位的可用比例，結果介於 0 到 100。"""
    stock = stock or {}
    technical = stock.get("technical") or {}

    values = [stock.get(field) for field in MARKET_FIELDS]
    values.extend(technical.get(field) for field in TECHNICAL_FIELDS)
    values.extend(stock.get(field) for field in CONTEXT_FIELDS)

    available = sum(1 for value in values if _is_available(value))
    return round(available / len(values) * 100)


def calculate_confidence(
    stock: dict,
    consensus_score: int | float | None,
    technical_signals: dict,
) -> int:
    """依訊號共識與有效程度計算信心度，不讀取 AI score。"""
    signals = [
        technical_signals.get("trend"),
        technical_signals.get("ma_signal"),
        technical_signals.get("macd_signal"),
        technical_signals.get("rsi_signal"),
        technical_signals.get("kd_signal"),
    ]
    directions = [direction for signal in signals if (direction := _direction(signal))]

    if not directions:
        return 0

    counts = {
        direction: directions.count(direction)
        for direction in set(directions)
    }
    consistency = max(counts.values()) / len(directions) * 100
    effective_ratio = len(directions) / len(signals) * 100

    try:
        consensus_certainty = abs(float(consensus_score) - 50) * 2
    except (TypeError, ValueError):
        consensus_certainty = consistency
    consensus_certainty = max(0, min(100, consensus_certainty))

    conflict_count = min(counts.get("bullish", 0), counts.get("bearish", 0))
    confidence = (
        consistency * 0.5
        + consensus_certainty * 0.3
        + effective_ratio * 0.2
        - conflict_count * 8
    )

    completeness = calculate_data_completeness(stock)
    if completeness < 40:
        confidence = min(confidence, 60)
    elif completeness < 60:
        confidence = min(confidence, 75)
    elif completeness < 80:
        confidence = min(confidence, 90)

    return max(0, min(95, round(confidence)))


def _is_available(value) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def _direction(signal) -> str | None:
    text = str(signal or "").strip()
    if not text or text in {"未判定", "資料不足"}:
        return None

    bearish_words = ("空", "死亡", "跌破", "偏弱", "過熱", "轉弱")
    bullish_words = ("多", "黃金", "站上", "健康", "偏強")

    if any(word in text for word in bearish_words):
        return "bearish"
    if any(word in text for word in bullish_words):
        return "bullish"
    return "neutral"
