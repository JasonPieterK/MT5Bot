import pandas as pd
import analysis.backtest as backtest


def make_rates():
    rows = []
    price = 1.10
    for i in range(30):
        price += 0.0008 if i % 2 == 0 else -0.0006
        rows.append({"open": price, "high": price + 0.0005, "low": price - 0.0005, "close": price})
    rows.append({"open": price, "high": price + 0.0200, "low": price - 0.0001, "close": price + 0.0150})
    for i in range(10):
        rows.append({"open": price, "high": price + 0.0005, "low": price - 0.0005, "close": price})
    return pd.DataFrame(rows)


def test_backtest_returns_deals_and_stats():
    settings = {"ma_type": "EMA", "fast_period": 9, "slow_period": 21,
                "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35}
    global_settings = {"risk_percent": 1.0}
    result = backtest.run_backtest(make_rates(), "trend", settings, global_settings, initial_equity=10000)
    assert "deals" in result
    assert "stats" in result
    assert "win_rate" in result["stats"]


def test_backtest_empty_rates_returns_zero_stats():
    settings = {"ma_type": "EMA", "fast_period": 9, "slow_period": 21,
                "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35}
    result = backtest.run_backtest(pd.DataFrame(), "trend", settings, {"risk_percent": 1.0}, 10000)
    assert result["deals"] == []
    assert result["stats"]["win_rate"] == 0
