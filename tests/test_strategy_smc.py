import pandas as pd
from strategies.smc import get_signal
from config import DEFAULT_SETTINGS


def bos_up_df():
    highs = [1.10, 1.105, 1.10, 1.108, 1.104, 1.112, 1.115]
    lows = [1.095, 1.098, 1.096, 1.100, 1.099, 1.105, 1.108]
    closes = [1.098, 1.102, 1.099, 1.106, 1.101, 1.110, 1.113]
    rows = 8 * [{"high": 1.10, "low": 1.095, "close": 1.098, "open": 1.096}]
    rows += [{"high": h, "low": l, "close": c, "open": c - 0.0005}
             for h, l, c in zip(highs, lows, closes)]
    return pd.DataFrame(rows)


def test_break_of_structure_up_gives_buy_or_none():
    signal, sl, tp = get_signal(bos_up_df(), DEFAULT_SETTINGS["smc"])
    assert signal in ("BUY", "NONE")


def test_ranging_market_gives_none():
    rows = [{"high": 1.10, "low": 1.098, "close": 1.099, "open": 1.099}] * 30
    df = pd.DataFrame(rows)
    signal, sl, tp = get_signal(df, DEFAULT_SETTINGS["smc"])
    assert signal == "NONE"
