"""Bar-by-bar backtest simulator. Reuses live strategy modules and risk_manager so
backtest and live logic never diverge. No spread/slippage modeled (documented gap)."""
import analytics
import risk_manager as rm
from strategies import trend, scalping, smc, pivot_breakout

STRATEGY_MODULES = {
    "trend": trend,
    "scalping": scalping,
    "smc": smc,
    "pivot_breakout": pivot_breakout,
}

MIN_BARS = 30


def run_backtest(rates_df, strategy_name, strategy_settings, global_settings, initial_equity):
    if len(rates_df) < MIN_BARS:
        return {"deals": [], "stats": analytics.compute_stats([])}

    module = STRATEGY_MODULES[strategy_name]
    equity = initial_equity
    deals = []
    open_trade = None

    for i in range(MIN_BARS, len(rates_df)):
        window = rates_df.iloc[:i]
        bar = rates_df.iloc[i]

        if open_trade is not None:
            hit_sl = bar["low"] <= open_trade["sl"] if open_trade["signal"] == "BUY" else bar["high"] >= open_trade["sl"]
            hit_tp = bar["high"] >= open_trade["tp"] if open_trade["signal"] == "BUY" else bar["low"] <= open_trade["tp"]
            if hit_sl or hit_tp:
                exit_price = open_trade["sl"] if hit_sl else open_trade["tp"]
                direction = 1 if open_trade["signal"] == "BUY" else -1
                profit = (exit_price - open_trade["entry"]) * direction * open_trade["lots"] * 100000
                equity += profit
                deals.append({"ticket": len(deals) + 1, "symbol": "BACKTEST", "profit": round(profit, 2), "time": i})
                open_trade = None
            continue

        signal, sl, tp = module.get_signal(window, strategy_settings)
        if signal == "NONE":
            continue

        entry = bar["open"]
        sl_distance = abs(entry - sl)
        lots = rm.calc_lot_size(equity=equity, risk_percent=global_settings["risk_percent"],
                                 sl_distance_price=sl_distance, pip_value_per_lot=10, point=0.0001)
        open_trade = {"signal": signal, "entry": entry, "sl": sl, "tp": tp, "lots": lots}

    return {"deals": deals, "stats": analytics.compute_stats(deals)}
