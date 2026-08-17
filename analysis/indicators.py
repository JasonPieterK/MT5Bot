"""Indicator calculations over pandas Series/DataFrame of OHLC rates."""
import pandas as pd


def ma(series, period, ma_type="SMA"):
    if ma_type == "SMA":
        return series.rolling(period).mean()
    if ma_type == "EMA":
        return series.ewm(span=period, adjust=False).mean()
    if ma_type == "WMA":
        weights = pd.Series(range(1, period + 1))
        return series.rolling(period).apply(lambda x: (x * weights.values).sum() / weights.sum(), raw=True)
    if ma_type == "SMMA":
        return series.ewm(alpha=1 / period, adjust=False).mean()
    raise ValueError(f"unknown ma_type: {ma_type}")


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def atr(df, period=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def macd(series, fast=12, slow=26, signal=9):
    macd_line = ma(series, fast, "EMA") - ma(series, slow, "EMA")
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def bollinger_bands(series, period=20, std_dev=2):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def stochastic(df, k_period=14, d_period=3):
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = 100 * (df["close"] - low_min) / (high_max - low_min)
    d = k.rolling(d_period).mean()
    return k, d


def classic_pivot(high, low, close):
    pivot = (high + low + close) / 3
    r1 = 2 * pivot - low
    s1 = 2 * pivot - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    return {"pivot": pivot, "r1": r1, "s1": s1, "r2": r2, "s2": s2}


def swing_points(df, lookback=5):
    high, low = df["high"], df["low"]
    swing_high = (high == high.rolling(lookback * 2 + 1, center=True).max())
    swing_low = (low == low.rolling(lookback * 2 + 1, center=True).min())
    return pd.DataFrame({"swing_high": swing_high.fillna(False), "swing_low": swing_low.fillna(False)})
