import core.config as config

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
    assert state["timeframe"] == "H1"
    assert state["trading_mode"] == "off"

def test_state_has_single_trading_mode_not_two_booleans():
    # Two independent flags let the UI show a single-symbol selection while the watchlist
    # traded other symbols. There is now exactly one source of truth.
    state = config.new_state()
    assert state["trading_mode"] == "off"
    assert "auto_enabled" not in state
    assert "watchlist_enabled" not in state

def test_quality_gates_are_on_by_default():
    # These three are the difference between the account's +$1.15M trade group and its
    # -$5.7M one. Shipping them off by default would ship the failure mode.
    assert config.GLOBAL_SETTINGS["min_reward_risk"] >= 1.5
    assert config.GLOBAL_SETTINGS["max_sl_atr_multiple"] <= 3.0
    # block_when_lot_capped is deliberately NOT here. Hitting the broker's cap makes the
    # position smaller with the same stop, so it risks less than configured -- blocking it
    # refuses a trade for being too safe. See tests/core/test_lot_cap_policy.py.

def test_aggregate_risk_cap_is_reachable():
    # A cap no realistic position set can hit is not a cap. max_concurrent_trades trades at
    # risk_percent each must be able to reach it.
    g = config.GLOBAL_SETTINGS
    assert g["portfolio_risk_filter_enabled"] is True
    assert g["max_portfolio_risk_percent"] <= g["risk_percent"] * g["max_concurrent_trades"] * 2

def test_no_default_timeframe_is_one_where_spread_swamps_the_stop():
    # Measured on this broker's own bars: on M1 the round-trip spread is 54-89% of a
    # 1.5x-ATR stop on the FX majors. No entry rule survives that, so M1 must not be a
    # default anywhere.
    assert config.new_state()["timeframe"] != "M1"
    for name, settings in config.DEFAULT_SETTINGS.items():
        assert settings["timeframe"] != "M1", name
