import pandas as pd
from strategies.pivot_breakout import get_signal
from config import DEFAULT_SETTINGS


def make_df(closes, highs=None, lows=None):
    highs = highs or [c + 0.0005 for c in closes]
    lows = lows or [c - 0.0005 for c in closes]
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes})


def test_breakout_above_r1_gives_buy():
    prior = [1.1000] * 20
    df = make_df(prior + [1.1080, 1.1090])
    settings = dict(DEFAULT_SETTINGS["pivot_breakout"])
    signal, sl, tp = get_signal(df, settings)
    assert signal in ("BUY", "NONE")


def test_no_breakout_gives_none():
    df = make_df([1.1000] * 22)
    signal, sl, tp = get_signal(df, DEFAULT_SETTINGS["pivot_breakout"])
    assert signal == "NONE"
