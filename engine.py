"""Background trading loop. run_once() is one iteration — called repeatedly by the
Flask-owned thread in app.py so the whole loop is testable without real threading/sleep."""
import csv
import os
from datetime import datetime, timezone

import risk_manager as rm
from strategies import trend, scalping, smc, grid, pivot_breakout

STRATEGY_MODULES = {
    "trend": trend,
    "scalping": scalping,
    "smc": smc,
    "pivot_breakout": pivot_breakout,
}

LOG_PATH = os.path.join("logs", "trades.csv")


def log_trade(row):
    os.makedirs("logs", exist_ok=True)
    write_header = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["time", "symbol", "strategy", "signal", "lots", "sl", "tp", "retcode"])
        writer.writerow(row)


def run_once(bridge, state, strategy_settings, global_settings, daily_pnl_percent, drawdown_percent):
    open_positions = bridge.get_open_positions(state["symbol"])

    if rm.should_flatten_all(drawdown_percent, global_settings["max_drawdown_percent"]):
        for pos in open_positions:
            bridge.close_position(pos["ticket"], pos["symbol"], pos["volume"], pos["type"],
                                   global_settings["slippage_points"])
        return

    strategy_name = state["active_strategy"]
    if strategy_name == "grid":
        signal, sl, tp = grid.get_signal(
            bridge.get_rates(state["symbol"], state["timeframe"], 60),
            strategy_settings["grid"],
            current_grid_levels=len(open_positions),
        )
    else:
        module = STRATEGY_MODULES[strategy_name]
        rates = bridge.get_rates(state["symbol"], state["timeframe"], 100)
        signal, sl, tp = module.get_signal(rates, strategy_settings[strategy_name])

    if signal == "NONE":
        return

    allowed, reason = rm.check_trade_allowed(
        open_position_count=len(open_positions),
        max_concurrent_trades=global_settings["max_concurrent_trades"],
        daily_pnl_percent=daily_pnl_percent,
        daily_loss_limit_percent=global_settings["daily_loss_limit_percent"],
        drawdown_percent=drawdown_percent,
        max_drawdown_percent=global_settings["max_drawdown_percent"],
    )
    if not allowed:
        return

    equity = bridge.get_account_equity()
    sl_distance = abs(bridge.get_rates(state["symbol"], state["timeframe"], 1)["close"].iloc[-1] - sl)
    lots = rm.calc_lot_size(
        equity=equity, risk_percent=global_settings["risk_percent"],
        sl_distance_price=sl_distance, pip_value_per_lot=10, point=0.0001,
    )

    ok, retcode = bridge.place_order(
        state["symbol"], signal, lots, sl=sl, tp=tp,
        slippage_points=global_settings["slippage_points"],
    )
    log_trade([datetime.now(timezone.utc).isoformat(), state["symbol"], strategy_name, signal, lots, sl, tp, retcode])
