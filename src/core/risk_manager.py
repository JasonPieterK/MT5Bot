"""Uniform risk pipeline every strategy signal passes through before execution."""


def calc_lot_size(equity, risk_percent, sl_distance_price, pip_value_per_lot, point,
                   lot_step=0.01, min_lot=0.01, max_lot=100.0, confidence=1.0):
    risk_amount = equity * (risk_percent / 100) * confidence
    sl_distance_points = sl_distance_price / point
    sl_distance_pips = sl_distance_points / 10
    if sl_distance_pips <= 0:
        return min_lot
    raw_lots = risk_amount / (sl_distance_pips * pip_value_per_lot)
    steps = int(raw_lots / lot_step + 1e-9)
    stepped = steps * lot_step
    return min(max(round(stepped, 2), min_lot), max_lot)


def calc_confidence(entry, sl, tp, min_confidence=0.5, max_confidence=1.5):
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0:
        return min_confidence
    rr = reward / risk
    return max(min_confidence, min(max_confidence, rr / 2))


def calc_streak_multiplier(recent_results, base=1.0, step=0.2, floor=0.2):
    """Anti-martingale: shrink size after consecutive losses. recent_results is a list
    of profit/loss floats, most recent last."""
    streak = 0
    for r in reversed(recent_results):
        if r < 0 and streak <= 0:
            streak -= 1
        else:
            break
    if streak >= 0:
        return base
    return max(floor, base + streak * step)


def check_trade_allowed(open_position_count, max_concurrent_trades,
                         daily_pnl_percent, daily_loss_limit_percent,
                         drawdown_percent, max_drawdown_percent):
    if drawdown_percent >= max_drawdown_percent:
        return False, f"max drawdown reached: {drawdown_percent}% >= {max_drawdown_percent}%"
    if daily_pnl_percent <= -daily_loss_limit_percent:
        return False, f"daily loss limit reached: {daily_pnl_percent}% <= -{daily_loss_limit_percent}%"
    if open_position_count >= max_concurrent_trades:
        return False, f"max concurrent trades reached: {open_position_count} >= {max_concurrent_trades}"
    return True, ""


def should_flatten_all(drawdown_percent, max_drawdown_percent):
    return drawdown_percent >= max_drawdown_percent
