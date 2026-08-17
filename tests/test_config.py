import config

def test_default_strategy_settings_has_all_five():
    keys = set(config.DEFAULT_SETTINGS.keys())
    assert keys == {"scalping", "smc", "trend", "grid", "pivot_breakout"}

def test_default_global_settings_present():
    assert "risk_percent" in config.GLOBAL_SETTINGS
    assert "max_concurrent_trades" in config.GLOBAL_SETTINGS
    assert "daily_loss_limit_percent" in config.GLOBAL_SETTINGS
    assert "max_drawdown_percent" in config.GLOBAL_SETTINGS

def test_grid_hard_caps_not_in_editable_settings():
    assert "max_levels" not in config.DEFAULT_SETTINGS["grid"]
    assert "max_total_lots" not in config.DEFAULT_SETTINGS["grid"]
    assert "equity_stop_percent" not in config.DEFAULT_SETTINGS["grid"]

def test_state_defaults():
    state = config.new_state()
    assert state["active_strategy"] == "trend"
    assert state["symbol"] == "EURUSD"
    assert state["timeframe"] == "M5"
    assert state["auto_enabled"] is False
