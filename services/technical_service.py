import pandas as pd

from services.stock_service import get_stock_history
from services.technical_indicators import (
    calculate_ma,
    calculate_rsi,
    calculate_macd,
    calculate_kd,
)


def get_technical_indicators(stock_id: str):
    data = get_stock_history(stock_id, days=250)

    if not data:
        return None

    df = pd.DataFrame(data)

    if df.empty or len(df) < 60:
        return None

    df = df.sort_values("date")

    for col in ["close", "max", "min"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["ma5"] = calculate_ma(df, 5)
    df["ma10"] = calculate_ma(df, 10)
    df["ma20"] = calculate_ma(df, 20)
    df["ma60"] = calculate_ma(df, 60)

    df["rsi"] = calculate_rsi(df)

    macd, signal, histogram = calculate_macd(df)
    df["macd"] = macd
    df["signal"] = signal
    df["histogram"] = histogram

    k, d = calculate_kd(df)
    df["k"] = k
    df["d"] = d

    latest = df.iloc[-1]

    return {
        "ma5": float(round(latest["ma5"], 2)),
        "ma10": float(round(latest["ma10"], 2)),
        "ma20": float(round(latest["ma20"], 2)),
        "ma60": float(round(latest["ma60"], 2)),
        "rsi": float(round(latest["rsi"], 2)),
        "k": float(round(latest["k"], 2)),
        "d": float(round(latest["d"], 2)),
        "macd": float(round(latest["macd"], 2)),
        "signal": float(round(latest["signal"], 2)),
        "histogram": float(round(latest["histogram"], 2)),
    }