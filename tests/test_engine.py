import pandas as pd
from unittest.mock import MagicMock
import engine


def make_uptrend_rates():
    price = 1.10
    closes = []
    for i in range(40):
        price += 0.0008 if i % 2 == 0 else -0.0006
        closes.append(price)
    return pd.DataFrame({
        "open": closes, "high": [c + 0.0005 for c in closes],
        "low": [c - 0.0005 for c in closes], "close": closes, "spread": [5] * 40,
    })


def test_run_once_places_order_when_signal_and_risk_allow(monkeypatch):
    bridge = MagicMock()
    bridge.get_rates.return_value = make_uptrend_rates()
    bridge.get_open_positions.return_value = []
    bridge.get_account_equity.return_value = 10000
    bridge.check_stops_valid.return_value = (True, "")
    bridge.place_order.return_value = (True, 10009)

    state = {"active_strategy": "trend", "symbol": "EURUSD", "timeframe": "M5"}
    strategy_settings = {"trend": {
        "ma_type": "EMA", "fast_period": 9, "slow_period": 21,
        "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35,
    }}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20}

    engine.run_once(bridge, state, strategy_settings, global_settings,
                     daily_pnl_percent=0.0, drawdown_percent=0.0)

    assert bridge.place_order.called


def test_run_once_skips_when_risk_manager_blocks(monkeypatch):
    bridge = MagicMock()
    bridge.get_rates.return_value = make_uptrend_rates()
    bridge.get_open_positions.return_value = [1, 2, 3]
    bridge.get_account_equity.return_value = 10000

    state = {"active_strategy": "trend", "symbol": "EURUSD", "timeframe": "M5"}
    strategy_settings = {"trend": {
        "ma_type": "EMA", "fast_period": 9, "slow_period": 21,
        "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35,
    }}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20}

    engine.run_once(bridge, state, strategy_settings, global_settings,
                     daily_pnl_percent=0.0, drawdown_percent=0.0)

    assert not bridge.place_order.called


def test_run_once_flattens_on_max_drawdown(monkeypatch):
    bridge = MagicMock()
    bridge.get_open_positions.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "type": "BUY"}
    ]
    state = {"active_strategy": "trend", "symbol": "EURUSD", "timeframe": "M5"}
    strategy_settings = {"trend": {}}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20}

    engine.run_once(bridge, state, strategy_settings, global_settings,
                     daily_pnl_percent=0.0, drawdown_percent=20.0)

    assert bridge.close_position.called
