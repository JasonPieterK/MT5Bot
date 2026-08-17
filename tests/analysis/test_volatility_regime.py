import pandas as pd
import analysis.volatility_regime as volatility_regime


def make_df(ranges):
    rows = []
    price = 1.10
    for r in ranges:
        rows.append({"high": price + r / 2, "low": price - r / 2, "close": price})
    return pd.DataFrame(rows)


def test_low_regime_when_current_range_below_history():
    ranges = [0.01] * 50 + [0.001]
    df = make_df(ranges)
    assert volatility_regime.classify_regime(df) == "LOW"


def test_high_regime_when_current_range_spikes():
    ranges = [0.001] * 50 + [0.05]
    df = make_df(ranges)
    assert volatility_regime.classify_regime(df) == "HIGH"


def test_normal_regime_with_flat_ranges():
    ranges = [0.005] * 50
    df = make_df(ranges)
    assert volatility_regime.classify_regime(df) == "NORMAL"


def test_insufficient_data_returns_normal():
    df = make_df([0.005] * 5)
    assert volatility_regime.classify_regime(df) == "NORMAL"
