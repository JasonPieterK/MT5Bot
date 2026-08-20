"""Uniform risk pipeline every strategy signal passes through before execution."""

# No single trade risks more than this, whatever the settings file or the UI says. A typo
# in the risk box must not become a 500%-of-equity position.
HARD_MAX_RISK_PERCENT = 5.0

# The broker cap is treated as "binding" only once it costs more than this much of the
# requested size, so ordinary lot-step rounding is not reported as a clamp.
_CLAMP_EPSILON = 1.01


def loss_per_lot(sl_distance_price, tick_value, tick_size):
    """Money lost per 1.0 lot when price travels sl_distance_price against the position.

    tick_value / tick_size come from the broker (mt5_bridge.get_symbol_tick_economics), so
    this is correct for FX, gold, indices and crypto alike -- there is deliberately no pip
    or point conversion here, that is what made sizing 10x wrong on FX and 100x on gold.
    Returns 0.0 when the inputs cannot describe a real stop."""
    if sl_distance_price <= 0 or tick_size <= 0 or tick_value <= 0:
        return 0.0
    return (sl_distance_price / tick_size) * tick_value


def calc_lot_size(equity, risk_percent, sl_distance_price, tick_value, tick_size,
                   lot_step=0.01, min_lot=0.01, max_lot=100.0, confidence=1.0):
    """Lots such that being stopped out costs exactly risk_percent of equity."""
    risk_percent = min(risk_percent, HARD_MAX_RISK_PERCENT)
    risk_amount = equity * (risk_percent / 100) * confidence
    per_lot = loss_per_lot(sl_distance_price, tick_value, tick_size)
    if per_lot <= 0:
        return min_lot
    raw_lots = risk_amount / per_lot
    steps = int(raw_lots / lot_step + 1e-9)
    stepped = steps * lot_step
    return min(max(round(stepped, 2), min_lot), max_lot)


def lot_clamp_report(equity, risk_percent, sl_distance_price, tick_value, tick_size,
                      max_lot, actual_lots):
    """None when the broker's max-lot cap did not bind; otherwise the numbers needed to say
    out loud that the configured risk percentage is not the risk actually being taken.

    On a large account this is the normal case, not an edge case: $5.4M equity at 1% risk
    with a 20-pip stop wants 272 lots and the broker allows 50, so the user asks for 1% and
    gets 0.18% -- and, far worse, every trade then goes out at exactly max size regardless
    of stop distance, which is sizing by broker limit rather than by risk."""
    per_lot = loss_per_lot(sl_distance_price, tick_value, tick_size)
    if per_lot <= 0 or equity <= 0:
        return None
    requested_lots = (equity * (min(risk_percent, HARD_MAX_RISK_PERCENT) / 100)) / per_lot
    if requested_lots <= max_lot * _CLAMP_EPSILON:
        return None
    return {
        "requested_lots": requested_lots,
        "max_lot": max_lot,
        "configured_risk_percent": risk_percent,
        "actual_risk_percent": actual_lots * per_lot / equity * 100,
        "max_expressible_risk_percent": max_lot * per_lot / equity * 100,
    }


def min_lot_overrisk_report(equity, risk_percent, sl_distance_price, tick_value, tick_size,
                             min_lot, actual_lots):
    """The mirror of lot_clamp_report, and the more dangerous direction.

    When the requested size is below the broker's minimum lot, calc_lot_size rounds UP to
    that minimum -- so a small account, or a wide stop on an expensive instrument, quietly
    takes more risk than was asked for, not less. Returns None unless that happened."""
    per_lot = loss_per_lot(sl_distance_price, tick_value, tick_size)
    if per_lot <= 0 or equity <= 0:
        return None
    requested_lots = (equity * (min(risk_percent, HARD_MAX_RISK_PERCENT) / 100)) / per_lot
    if requested_lots >= min_lot or actual_lots <= 0:
        return None
    return {
        "requested_lots": requested_lots,
        "min_lot": min_lot,
        "configured_risk_percent": risk_percent,
        "actual_risk_percent": actual_lots * per_lot / equity * 100,
    }


def reward_risk(entry, sl, tp):
    """Planned TP distance divided by planned SL distance. 0.0 when either is missing or
    degenerate, so callers can treat "unknown" and "bad" identically."""
    if not sl or not tp or not entry:
        return 0.0
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    return abs(tp - entry) / risk


def check_reward_risk(entry, sl, tp, min_reward_risk):
    """The single highest-value gate in this file. This account's own history contains 825
    trades at an 84% win rate that still lost $5.7M, because the average win was $4,936 and
    the average loss $69,653 -- a 0.071 payoff ratio, when break-even at that win rate needs
    0.19. No win rate rescues a reward:risk this bad, so it is rejected before sizing."""
    rr = reward_risk(entry, sl, tp)
    if rr <= 0:
        return False, "no usable take-profit or stop-loss to measure reward:risk against"
    if rr < min_reward_risk - 1e-9:
        return False, (f"reward:risk {rr:.2f} is below the {min_reward_risk} floor "
                       f"(entry {entry}, sl {sl}, tp {tp})")
    return True, ""


def check_stop_sanity(entry, sl, atr, max_sl_atr_multiple):
    """A missing stop is an unbounded loss, and a stop many ATRs away is a missing stop with
    extra steps -- it is the "let losers run" half of the same failure."""
    if not sl:
        return False, "no stop loss on this signal"
    distance = abs(entry - sl)
    if distance <= 0:
        return False, "stop loss is at the entry price"
    if atr and atr > 0 and distance > atr * max_sl_atr_multiple:
        return False, (f"stop is {distance / atr:.1f}x ATR away, the limit is "
                       f"{max_sl_atr_multiple}x")
    return True, ""


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
