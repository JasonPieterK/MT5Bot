import pandas as pd
from unittest.mock import MagicMock
import core.engine as engine


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
    bridge.get_margin_level.return_value = 500.0

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
    bridge.get_margin_level.return_value = 500.0

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


def test_manage_positions_applies_trailing_when_enabled():
    bridge = MagicMock()
    bridge.get_open_positions.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "type": "BUY",
         "price_open": 1.1000, "sl": 1.0950, "tp": 1.1200},
    ]
    bridge.get_current_price.return_value = (1.1100, 1.1102)
    bridge.get_margin_level.return_value = 500.0
    global_settings = {"trailing_enabled": True, "trailing_distance_points": 100,
                        "breakeven_enabled": False, "breakeven_trigger_points": 100,
                        "breakeven_offset_points": 10, "margin_alert_level_percent": 100.0}

    triggered = []
    engine._manage_positions(bridge, global_settings, [], triggered)

    assert bridge.modify_position.called
    assert triggered == []


def test_manage_positions_triggers_price_alert_and_removes_rule():
    bridge = MagicMock()
    bridge.get_open_positions.return_value = []
    bridge.get_current_price.return_value = (1.1050, 1.1052)
    bridge.get_margin_level.return_value = 500.0
    global_settings = {"trailing_enabled": False, "breakeven_enabled": False,
                        "margin_alert_level_percent": 100.0}
    rules = [{"id": 1, "symbol": "EURUSD", "condition": "above", "price": 1.1000}]
    triggered = []

    engine._manage_positions(bridge, global_settings, rules, triggered)

    assert len(triggered) == 1
    assert rules == []


def test_manage_positions_triggers_margin_alert():
    bridge = MagicMock()
    bridge.get_open_positions.return_value = []
    bridge.get_margin_level.return_value = 50.0
    global_settings = {"trailing_enabled": False, "breakeven_enabled": False,
                        "margin_alert_level_percent": 100.0}
    triggered = []

    engine._manage_positions(bridge, global_settings, [], triggered)

    assert any(t.get("type") == "margin" for t in triggered)


def test_watchlist_auto_entry_places_order():
    bridge = MagicMock()
    bridge.get_rates.return_value = make_uptrend_rates()
    bridge.get_open_positions.return_value = []
    bridge.get_account_equity.return_value = 10000
    bridge.get_margin_level.return_value = 500.0
    bridge.place_order.return_value = (True, 10009)
    watchlist = [{"id": 1, "symbol": "EURUSD", "timeframe": "M5", "strategy": "trend",
                  "mode": "auto", "enabled": True}]
    strategy_settings = {"trend": {"ma_type": "EMA", "fast_period": 9, "slow_period": 21,
                                    "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35}}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20, "margin_alert_level_percent": 100.0}
    manual_signals = []
    engine.run_watchlist_once(bridge, watchlist, strategy_settings, global_settings,
                               0.0, 0.0, [], [], manual_signals)
    assert bridge.place_order.called
    assert manual_signals == []


def test_watchlist_alert_only_entry_does_not_place_order():
    bridge = MagicMock()
    bridge.get_rates.return_value = make_uptrend_rates()
    bridge.get_open_positions.return_value = []
    bridge.get_margin_level.return_value = 500.0
    watchlist = [{"id": 2, "symbol": "GBPUSD", "timeframe": "M5", "strategy": "trend",
                  "mode": "alert_only", "enabled": True}]
    strategy_settings = {"trend": {"ma_type": "EMA", "fast_period": 9, "slow_period": 21,
                                    "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35}}
    global_settings = {"max_concurrent_trades": 3, "daily_loss_limit_percent": 5.0,
                        "max_drawdown_percent": 15.0, "margin_alert_level_percent": 100.0}
    manual_signals = []
    engine.run_watchlist_once(bridge, watchlist, strategy_settings, global_settings,
                               0.0, 0.0, [], [], manual_signals)
    assert not bridge.place_order.called
    assert len(manual_signals) == 1
    assert manual_signals[0]["symbol"] == "GBPUSD"


def test_watchlist_disabled_entry_skipped():
    bridge = MagicMock()
    bridge.get_margin_level.return_value = 500.0
    watchlist = [{"id": 3, "symbol": "EURUSD", "timeframe": "M5", "strategy": "trend",
                  "mode": "auto", "enabled": False}]
    manual_signals = []
    engine.run_watchlist_once(bridge, watchlist, {"trend": {}}, {"margin_alert_level_percent": 100.0},
                               0.0, 0.0, [], [], manual_signals)
    assert not bridge.get_rates.called


def test_watchlist_one_entry_error_does_not_stop_others():
    bridge = MagicMock()
    def get_rates_side_effect(symbol, tf, count):
        if symbol == "EURUSD":
            raise RuntimeError("boom")
        return make_uptrend_rates()
    bridge.get_rates.side_effect = get_rates_side_effect
    bridge.get_open_positions.return_value = []
    bridge.get_account_equity.return_value = 10000
    bridge.get_margin_level.return_value = 500.0
    bridge.place_order.return_value = (True, 10009)
    watchlist = [
        {"id": 1, "symbol": "EURUSD", "timeframe": "M5", "strategy": "trend", "mode": "auto", "enabled": True},
        {"id": 2, "symbol": "GBPUSD", "timeframe": "M5", "strategy": "trend", "mode": "auto", "enabled": True},
    ]
    strategy_settings = {"trend": {"ma_type": "EMA", "fast_period": 9, "slow_period": 21,
                                    "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35}}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20, "margin_alert_level_percent": 100.0}
    manual_signals = []
    engine.run_watchlist_once(bridge, watchlist, strategy_settings, global_settings,
                               0.0, 0.0, [], [], manual_signals)
    assert bridge.place_order.called


def test_run_once_skips_order_during_blackout():
    bridge = MagicMock()
    bridge.get_rates.return_value = make_uptrend_rates()
    bridge.get_open_positions.return_value = []
    bridge.get_account_equity.return_value = 10000
    bridge.get_margin_level.return_value = 500.0
    state = {"active_strategy": "trend", "symbol": "EURUSD", "timeframe": "M5"}
    strategy_settings = {"trend": {"ma_type": "EMA", "fast_period": 9, "slow_period": 21,
                                    "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35}}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20, "margin_alert_level_percent": 100.0}
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    blackout_windows = [{"id": 1, "start": (now - timedelta(minutes=5)).isoformat(),
                          "end": (now + timedelta(minutes=5)).isoformat(), "label": "test"}]

    engine.run_once(bridge, state, strategy_settings, global_settings,
                     daily_pnl_percent=0.0, drawdown_percent=0.0, blackout_windows=blackout_windows)

    assert not bridge.place_order.called


def test_run_once_ensemble_strategy_places_order_on_agreement(monkeypatch):
    bridge = MagicMock()
    bridge.get_rates.return_value = make_uptrend_rates()
    bridge.get_open_positions.return_value = []
    bridge.get_account_equity.return_value = 10000
    bridge.get_margin_level.return_value = 500.0
    bridge.place_order.return_value = (True, 10009)

    import core.ensemble as ensemble
    monkeypatch.setattr(engine.ensemble, "get_ensemble_signal",
                         lambda rates, settings, min_agree=2: ("BUY", 1.09, 1.11, ["trend", "scalping"]))

    state = {"active_strategy": "ensemble", "symbol": "EURUSD", "timeframe": "M5"}
    strategy_settings = {"trend": {}, "scalping": {}, "smc": {}, "pivot_breakout": {}}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20, "margin_alert_level_percent": 100.0}

    engine.run_once(bridge, state, strategy_settings, global_settings,
                     daily_pnl_percent=0.0, drawdown_percent=0.0)

    assert bridge.place_order.called
