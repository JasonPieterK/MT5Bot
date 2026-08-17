import pandas as pd
import core.htf_filter as htf_filter


def uptrend_df():
    closes = [1.10 + i * 0.001 for i in range(60)]
    return pd.DataFrame({"close": closes})


def downtrend_df():
    closes = [1.10 - i * 0.001 for i in range(60)]
    return pd.DataFrame({"close": closes})


def test_bias_bull_in_uptrend():
    assert htf_filter.get_bias(uptrend_df()) == "BULL"


def test_bias_bear_in_downtrend():
    assert htf_filter.get_bias(downtrend_df()) == "BEAR"


def test_bias_neutral_with_insufficient_data():
    assert htf_filter.get_bias(pd.DataFrame({"close": [1.1, 1.1]})) == "NEUTRAL"


def test_buy_matches_bull_bias():
    assert htf_filter.signal_matches_bias("BUY", "BULL") is True
    assert htf_filter.signal_matches_bias("BUY", "BEAR") is False


def test_sell_matches_bear_bias():
    assert htf_filter.signal_matches_bias("SELL", "BEAR") is True
    assert htf_filter.signal_matches_bias("SELL", "BULL") is False


def test_neutral_bias_always_matches():
    assert htf_filter.signal_matches_bias("BUY", "NEUTRAL") is True
    assert htf_filter.signal_matches_bias("SELL", "NEUTRAL") is True
