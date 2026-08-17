import pandas as pd
from strategies.scalping import get_signal
from config import DEFAULT_SETTINGS


def bullish_body_df():
    rows = []
    for i in range(20):
        rows.append({"open": 1.1000, "high": 1.1030, "low": 1.0995, "close": 1.1025, "spread": 5})
    return pd.DataFrame(rows)


def test_strong_bullish_candle_gives_buy():
    signal, sl, tp = get_signal(bullish_body_df(), DEFAULT_SETTINGS["scalping"])
    assert signal == "BUY"
    assert sl < tp


def test_wide_spread_blocks_signal():
    df = bullish_body_df()
    df["spread"] = 999
    signal, sl, tp = get_signal(df, DEFAULT_SETTINGS["scalping"])
    assert signal == "NONE"


def test_small_body_gives_no_signal():
    rows = [{"open": 1.10000, "high": 1.1005, "low": 1.0995, "close": 1.10005, "spread": 5}] * 20
    df = pd.DataFrame(rows)
    signal, sl, tp = get_signal(df, DEFAULT_SETTINGS["scalping"])
    assert signal == "NONE"
