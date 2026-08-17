import automation.auto_tuner as auto_tuner


def make_stats(profit_factor, trade_count):
    return {"profit_factor": profit_factor, "win_rate": 50.0,
            "equity_curve": [1.0] * trade_count, "current_streak": 0}


def test_suggest_disable_flags_low_profit_factor_with_enough_trades():
    stats = {"trend": make_stats(0.5, 15), "scalping": make_stats(1.5, 15)}
    result = auto_tuner.suggest_strategy_disable(stats, min_profit_factor=0.8, min_trades=10)
    assert result == ["trend"]


def test_suggest_disable_ignores_small_sample():
    stats = {"trend": make_stats(0.5, 3)}
    result = auto_tuner.suggest_strategy_disable(stats, min_profit_factor=0.8, min_trades=10)
    assert result == []


def test_suggest_best_strategy_picks_highest_profit_factor():
    stats = {"trend": make_stats(1.2, 15), "scalping": make_stats(2.0, 15), "smc": make_stats(0.5, 5)}
    assert auto_tuner.suggest_best_strategy(stats, min_trades=10) == "scalping"


def test_suggest_best_strategy_none_when_no_eligible():
    stats = {"trend": make_stats(2.0, 3)}
    assert auto_tuner.suggest_best_strategy(stats, min_trades=10) is None


def test_apply_best_sweep_params_updates_settings():
    current = {"fast_period": 9, "slow_period": 21, "ma_type": "EMA"}
    sweep_results = [
        {"params": {"fast_period": 13, "slow_period": 34}, "stats": {"profit_factor": 2.0}},
        {"params": {"fast_period": 5, "slow_period": 21}, "stats": {"profit_factor": 1.0}},
    ]
    updated = auto_tuner.apply_best_sweep_params(sweep_results, current)
    assert updated == {"fast_period": 13, "slow_period": 34, "ma_type": "EMA"}


def test_apply_best_sweep_params_no_results_returns_unchanged():
    current = {"fast_period": 9}
    assert auto_tuner.apply_best_sweep_params([], current) == current
