import pandas as pd
import analysis.indicators as indicators


def make_series(values):
    return pd.Series(values, dtype=float)


def test_sma():
    s = make_series([1, 2, 3, 4, 5])
    result = indicators.ma(s, period=3, ma_type="SMA")
    assert round(result.iloc[-1], 4) == 4.0


def test_ema_last_value_reasonable():
    s = make_series([1, 2, 3, 4, 5, 6, 7, 8])
    result = indicators.ma(s, period=3, ma_type="EMA")
    assert result.iloc[-1] > result.iloc[-2]


def test_rsi_bounds():
    s = make_series([1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5, 6, 7, 8])
    result = indicators.rsi(s, period=14)
    assert 0 <= result.iloc[-1] <= 100


def test_atr_positive():
    df = pd.DataFrame({
        "high": [1.2, 1.3, 1.25, 1.4, 1.35],
        "low": [1.1, 1.15, 1.1, 1.2, 1.25],
        "close": [1.15, 1.2, 1.2, 1.3, 1.3],
    })
    result = indicators.atr(df, period=3)
    assert result.iloc[-1] > 0


def test_macd_returns_macd_and_signal():
    s = make_series(list(range(1, 40)))
    macd_line, signal_line = indicators.macd(s)
    assert len(macd_line) == len(s)
    assert len(signal_line) == len(s)


def test_bollinger_bands_upper_gt_lower():
    s = make_series([1, 2, 1, 3, 2, 4, 3, 5, 4, 6])
    upper, mid, lower = indicators.bollinger_bands(s, period=5, std_dev=2)
    assert upper.iloc[-1] > mid.iloc[-1] > lower.iloc[-1]


def test_classic_pivot_points():
    pivots = indicators.classic_pivot(high=1.2000, low=1.1000, close=1.1500)
    assert round(pivots["pivot"], 4) == 1.1500
    assert pivots["r1"] > pivots["pivot"]
    assert pivots["s1"] < pivots["pivot"]


def test_swing_highs_lows_detected():
    df = pd.DataFrame({
        "high": [1, 2, 3, 2, 1, 2, 3, 4, 3, 2],
        "low": [0.5, 1.5, 2.5, 1.5, 0.5, 1.5, 2.5, 3.5, 2.5, 1.5],
    })
    swings = indicators.swing_points(df, lookback=2)
    assert any(swings["swing_high"])
    assert any(swings["swing_low"])
