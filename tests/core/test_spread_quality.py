import pandas as pd
import core.spread_quality as spread_quality


def test_normal_spread_acceptable():
    df = pd.DataFrame({"spread": [10] * 19 + [12]})
    assert spread_quality.is_spread_acceptable(df, lookback=20, max_ratio=1.5) is True


def test_wide_spread_rejected():
    df = pd.DataFrame({"spread": [10] * 19 + [50]})
    assert spread_quality.is_spread_acceptable(df, lookback=20, max_ratio=1.5) is False


def test_no_spread_column_defaults_acceptable():
    df = pd.DataFrame({"close": [1.1, 1.1, 1.1]})
    assert spread_quality.is_spread_acceptable(df) is True


def test_zero_average_defaults_acceptable():
    df = pd.DataFrame({"spread": [0] * 20})
    assert spread_quality.is_spread_acceptable(df) is True
