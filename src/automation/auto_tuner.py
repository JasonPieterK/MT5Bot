"""Self-monitoring: flags strategies with enough trade history to be statistically
meaningful but poor live profit factor, and applies the best backtest.run_sweep
result to a strategy's settings in place."""


def suggest_strategy_disable(per_strategy_stats, min_profit_factor=0.8, min_trades=10):
    disable = []
    for name, stats in per_strategy_stats.items():
        trade_count = len(stats.get("equity_curve", []))
        if trade_count >= min_trades and stats["profit_factor"] < min_profit_factor:
            disable.append(name)
    return disable


def suggest_best_strategy(per_strategy_stats, min_trades=10):
    eligible = {
        name: stats for name, stats in per_strategy_stats.items()
        if len(stats.get("equity_curve", [])) >= min_trades
    }
    if not eligible:
        return None
    return max(eligible, key=lambda name: eligible[name]["profit_factor"])


def apply_best_sweep_params(sweep_results, current_settings):
    if not sweep_results:
        return current_settings
    best = sweep_results[0]
    updated = dict(current_settings)
    updated.update(best["params"])
    return updated
