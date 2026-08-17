import pandas as pd
from strategies.trend import get_signal
from core.config import DEFAULT_SETTINGS


def uptrend_df():
    price = 1.10
    closes = []
    for i in range(40):
        price += 0.0008 if i % 2 == 0 else -0.0006
        closes.append(price)
    return pd.DataFrame({
        "open": closes, "high": [c + 0.0005 for c in closes],
        "low": [c - 0.0005 for c in closes], "close": closes,
    })


def flat_df():
    closes = [1.10] * 40
    return pd.DataFrame({
        "open": closes, "high": [c + 0.0001 for c in closes],
        "low": [c - 0.0001 for c in closes], "close": closes,
    })


def test_uptrend_gives_buy_signal():
    signal, sl, tp = get_signal(uptrend_df(), DEFAULT_SETTINGS["trend"])
    assert signal == "BUY"
    assert sl < tp


def test_flat_market_gives_no_signal():
    signal, sl, tp = get_signal(flat_df(), DEFAULT_SETTINGS["trend"])
    assert signal == "NONE"


def test_downtrend_gives_sell_signal():
    price = 1.10
    closes = []
    for i in range(40):
        price += -0.0008 if i % 2 == 0 else 0.0006
        closes.append(price)
    df = pd.DataFrame({
        "open": closes, "high": [c + 0.0005 for c in closes],
        "low": [c - 0.0005 for c in closes], "close": closes,
    })
    signal, sl, tp = get_signal(df, DEFAULT_SETTINGS["trend"])
    assert signal == "SELL"
    assert sl > tp
