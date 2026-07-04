import pandas as pd


def calculate_ma(df: pd.DataFrame, days: int):
    return df["close"].rolling(window=days).mean()


def calculate_rsi(df: pd.DataFrame, period: int = 14):
    delta = df["close"].diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_macd(df: pd.DataFrame):
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()

    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal

    return macd, signal, histogram


def calculate_kd(df: pd.DataFrame, period: int = 9):
    low_min = df["min"].rolling(window=period).min()
    high_max = df["max"].rolling(window=period).max()

    rsv = (df["close"] - low_min) / (high_max - low_min) * 100

    k = rsv.ewm(com=2).mean()
    d = k.ewm(com=2).mean()

    return k, d