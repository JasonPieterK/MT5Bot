"""Runtime settings store. Grid hard caps live in strategies/grid.py, not here — not user-editable."""

DEFAULT_SETTINGS = {
    "scalping": {
        "timeframe": "M1",
        "max_spread_points": 20,
        "sl_atr_multiple": 1.0,
        "tp_atr_multiple": 1.5,
        "atr_period": 14,
        "min_candle_body_percent": 30,
        "session_start_hour": 0,
        "session_end_hour": 23,
    },
    "smc": {
        "timeframe": "M15",
        "swing_lookback": 10,
        "htf_timeframe": "H1",
        "ob_fvg_mitigation_percent": 50,
        "min_risk_reward": 1.5,
    },
    "trend": {
        "timeframe": "M15",
        "ma_type": "EMA",
        "fast_period": 9,
        "slow_period": 21,
        "rsi_period": 14,
        "rsi_buy_below": 65,
        "rsi_sell_above": 35,
        "confirmation_bars": 1,
    },
    "grid": {
        "timeframe": "M5",
        "grid_step_points": 100,
        "lot_multiplier": 1.0,
    },
    "pivot_breakout": {
        "timeframe": "M15",
        "pivot_type": "classic",
        "confirmation_bars": 1,
        "require_retest": False,
    },
}

GLOBAL_SETTINGS = {
    "risk_percent": 1.0,
    "max_concurrent_trades": 3,
    "daily_loss_limit_percent": 5.0,
    "max_drawdown_percent": 15.0,
    "slippage_points": 20,
    "trailing_enabled": False,
    "trailing_distance_points": 100,
    "breakeven_enabled": False,
    "breakeven_trigger_points": 100,
    "breakeven_offset_points": 10,
    "margin_alert_level_percent": 100.0,
    "correlation_filter_enabled": False,
    "correlation_max_positions": 2,
    "htf_filter_enabled": False,
    "htf_timeframe": "H1",
    "volatility_regime_filter_enabled": False,
    "confidence_sizing_enabled": False,
    "streak_sizing_enabled": False,
    "session_filter_enabled": False,
    "session_start_hour": 0,
    "session_end_hour": 23,
}


def new_state():
    return {
        "active_strategy": "trend",
        "symbol": "EURUSD",
        "timeframe": "M5",
        "auto_enabled": False,
        "watchlist_enabled": False,
        "lock_enabled": False,
        "lock_passcode": "",
    }


def new_watchlist_entry(entry_id, symbol, timeframe, strategy, mode):
    return {"id": entry_id, "symbol": symbol, "timeframe": timeframe,
            "strategy": strategy, "mode": mode, "enabled": True}
