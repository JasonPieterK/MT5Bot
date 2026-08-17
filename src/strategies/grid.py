"""Grid/martingale strategy. Hard safety caps below are intentionally NOT read from config.py
and NOT exposed via the settings API/UI. Change them only by editing this file."""

HARD_MAX_LEVELS = 5
HARD_MAX_TOTAL_LOTS = 2.0
HARD_EQUITY_STOP_PERCENT = 10.0


def get_signal(df, settings, current_grid_levels):
    if current_grid_levels >= HARD_MAX_LEVELS:
        return "NONE", None, None

    price = df["close"].iloc[-1]
    step = settings["grid_step_points"] * 0.0001
    direction = "BUY" if current_grid_levels % 2 == 0 else "SELL"

    if direction == "BUY":
        sl = price - step * 3
        tp = price + step
        return "BUY", sl, tp
    else:
        sl = price + step * 3
        tp = price - step
        return "SELL", sl, tp


def total_lots_within_cap(current_total_lots, next_lot_size):
    return (current_total_lots + next_lot_size) <= HARD_MAX_TOTAL_LOTS


def equity_stop_triggered(drawdown_percent):
    return drawdown_percent >= HARD_EQUITY_STOP_PERCENT
