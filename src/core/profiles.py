"""Trading profiles: one named bundle of the settings that decide how much of the account a
trade, a day, or a drawdown is allowed to cost.

These are RISK-MANAGEMENT profiles and nothing else. Walk-forward testing on this account
found no strategy with a demonstrated out-of-sample edge, and tuned parameters lost to the
defaults, so no preset here picks a strategy for you, and none of the descriptions claims an
expected return. What separates the tiers is only how much you can lose, and how quickly the
kill switches fire.

The other half of the job is arithmetic. At this account's equity the broker's 50-lot cap
binds long before a 1%-per-trade request can be sized: the position that would risk 1% over a
typical stop is several hundred lots, so the engine refuses every trade and the user is left
staring at a "1%" that was never real. Every preset therefore derives its lot ceiling from the
broker's own volume_max at apply time, and re-states its risk as the largest value this
account can actually express. See resolve()."""
import math

# Fraction of the broker's own max lot each tier will use as its hard ceiling. This is what
# keeps the tiers distinguishable on an account where the broker cap binds on all of them:
# clamping every tier to the same cap would collapse "capital preservation" and "high risk"
# onto the identical position size.
# PRESETS is one ordered risk ladder, capital_preservation -> high_risk, and nothing else.
# Each rung loosens every limit relative to the one below it and tests enforce that
# monotonicity, so there is no "tier" marker to check: every entry is a rung. Five
# purpose-built profiles used to sit alongside them (one-at-a-time, high-conviction,
# wide-stop, recovery, unguarded); they broke the ordering without covering any risk level
# the ladder misses, so they were removed.
PRESETS = [
    {
        "id": "capital_preservation",
        "label": "Capital preservation",
        "description": "Risks 0.25% per trade, one position at a time, stops opening trades "
                       "for the day after a 2% loss and flattens at 5% drawdown. The smallest "
                       "position ceiling of any tier.",
        "risk_percent": 0.25,
        "lot_fraction": 0.10,
        "max_concurrent_trades": 1,
        "daily_loss_limit_percent": 2.0,
        "max_drawdown_percent": 5.0,
        "min_reward_risk": 2.0,
        "max_sl_atr_multiple": 2.0,
        "max_portfolio_risk_percent": 1.0,
        "timeframe": "H1",
        "toggles": {
            "trailing_enabled": True, "breakeven_enabled": True, "partial_tp_enabled": True,
            "spread_quality_filter_enabled": True, "block_when_lot_capped": False,
            "portfolio_risk_filter_enabled": True, "streak_sizing_enabled": True,
            "confidence_sizing_enabled": True,
        },
    },
    {
        "id": "conservative",
        "label": "Conservative",
        "description": "Risks 0.5% per trade, up to two positions, stops for the day after a "
                       "3% loss and flattens at 8% drawdown.",
        "risk_percent": 0.5,
        "lot_fraction": 0.25,
        "max_concurrent_trades": 2,
        "daily_loss_limit_percent": 3.0,
        "max_drawdown_percent": 8.0,
        "min_reward_risk": 1.8,
        "max_sl_atr_multiple": 2.5,
        "max_portfolio_risk_percent": 2.0,
        "timeframe": "H1",
        "toggles": {
            "trailing_enabled": True, "breakeven_enabled": True, "partial_tp_enabled": False,
            "spread_quality_filter_enabled": True, "block_when_lot_capped": False,
            "portfolio_risk_filter_enabled": True, "streak_sizing_enabled": True,
            "confidence_sizing_enabled": False,
        },
    },
    {
        "id": "balanced",
        "label": "Balanced",
        "description": "Risks 1% per trade, up to three positions, stops for the day after a "
                       "5% loss and flattens at 12% drawdown. Half the broker's lot ceiling.",
        "risk_percent": 1.0,
        "lot_fraction": 0.50,
        "max_concurrent_trades": 3,
        "daily_loss_limit_percent": 5.0,
        "max_drawdown_percent": 12.0,
        "min_reward_risk": 1.5,
        "max_sl_atr_multiple": 3.0,
        "max_portfolio_risk_percent": 4.0,
        "timeframe": "H1",
        "toggles": {
            "trailing_enabled": True, "breakeven_enabled": True, "partial_tp_enabled": False,
            "spread_quality_filter_enabled": False, "block_when_lot_capped": False,
            "portfolio_risk_filter_enabled": True, "streak_sizing_enabled": True,
            "confidence_sizing_enabled": False,
        },
    },
    {
        "id": "aggressive",
        "label": "Aggressive",
        "description": "Risks 2% per trade, up to four positions, stops for the day after an "
                       "8% loss and flattens at 20% drawdown. Ten losses in a row costs about "
                       "18% of the account.",
        "warning": "At 2% per trade, ten losses in a row costs about 18% of the account. "
                   "Streaks that long are ordinary, not rare.",
        "risk_percent": 2.0,
        "lot_fraction": 0.80,
        "max_concurrent_trades": 4,
        "daily_loss_limit_percent": 8.0,
        "max_drawdown_percent": 20.0,
        "min_reward_risk": 1.3,
        "max_sl_atr_multiple": 3.0,
        "max_portfolio_risk_percent": 8.0,
        "timeframe": "M15",
        "toggles": {
            "trailing_enabled": True, "breakeven_enabled": False, "partial_tp_enabled": False,
            "spread_quality_filter_enabled": False, "block_when_lot_capped": False,
            "portfolio_risk_filter_enabled": True, "streak_sizing_enabled": False,
            "confidence_sizing_enabled": False,
        },
    },
    {
        "id": "high_risk",
        "label": "High risk",
        "description": "Risks 4% per trade, up to five positions, stops for the day after a "
                       "15% loss and flattens at 30% drawdown. Uses the broker's full lot "
                       "ceiling. Ten losses in a row costs about 34% of the account.",
        "warning": "Ten losses in a row costs about 34% of the account. Trailing stop, "
                   "break-even and the anti-martingale shrink are all off.",
        "risk_percent": 4.0,
        "lot_fraction": 1.00,
        "max_concurrent_trades": 5,
        "daily_loss_limit_percent": 15.0,
        "max_drawdown_percent": 30.0,
        "min_reward_risk": 1.2,
        "max_sl_atr_multiple": 3.0,
        "max_portfolio_risk_percent": 15.0,
        "timeframe": "M15",
        "requires_confirmation": True,
        # Stated as arithmetic, not as a scare or a nudge. 0.96**10 = 0.665.
        "confirmation": ("At 4% risk per trade, ten losing trades in a row costs about 34% of "
                         "the account (0.96^10 = 0.665). Losing streaks of ten are normal, not "
                         "rare — a strategy that wins 50% of the time hits one roughly every "
                         "thousand trades, and no strategy in this bot has a demonstrated edge. "
                         "The daily loss limit (15%) and max drawdown (30%) are the only things "
                         "that stop it going further."),
        "toggles": {
            "trailing_enabled": False, "breakeven_enabled": False, "partial_tp_enabled": False,
            "spread_quality_filter_enabled": False, "block_when_lot_capped": False,
            "portfolio_risk_filter_enabled": True, "streak_sizing_enabled": False,
            "confidence_sizing_enabled": False,
        },
    },
]

# The floor /api/global_settings accepts. A preset may never resolve below it.
MIN_RISK_PERCENT = 0.001

# How much of the lot ceiling's maximum expressible risk a preset is allowed to claim.
#
# Not decoration. The expressible risk moves with the stop distance, which moves with ATR:
# resolving to exactly the ceiling means the very next quiet hour makes the cap bind again
# and the engine goes back to refusing every trade -- observed live, an ATR dip of a few
# percent was enough. Half leaves room for the stop to halve before anything is refused.
LOT_HEADROOM = 0.5

# Keys a profile owns in global_settings. Anything not listed here is left alone by an apply.
SETTING_KEYS = ("risk_percent", "max_lot", "max_concurrent_trades", "daily_loss_limit_percent",
                "max_drawdown_percent", "min_reward_risk", "max_sl_atr_multiple",
                "max_portfolio_risk_percent")

# Human labels for the change preview and the bounds readout.
LABELS = {
    "risk_percent": "Risk per trade %",
    "max_lot": "Max lot size",
    "max_concurrent_trades": "Max trades at once",
    "daily_loss_limit_percent": "Daily loss limit %",
    "max_drawdown_percent": "Max drawdown %",
    "min_reward_risk": "Minimum reward:risk",
    "max_sl_atr_multiple": "Max stop distance (x ATR)",
    "max_portfolio_risk_percent": "Max portfolio risk %",
    "timeframe": "Candle size",
    "trailing_enabled": "Trailing stop",
    "breakeven_enabled": "Move to break-even",
    "partial_tp_enabled": "Partial take-profit",
    "spread_quality_filter_enabled": "Spread-quality filter",
    "block_when_lot_capped": "Refuse trades sized by the broker cap",
    "portfolio_risk_filter_enabled": "Portfolio risk cap",
    "streak_sizing_enabled": "Shrink size after losses",
    "confidence_sizing_enabled": "Size by setup quality",
}

# Bounds are ceilings, except min_reward_risk which is a floor: a profile that demands at
# least 1.5:1 is not respected by lowering the number.
FLOOR_KEYS = ("min_reward_risk",)


def get(preset_id):
    for preset in PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None


def _round_down(value, step):
    return math.floor(value / step + 1e-9) * step if step > 0 else value


def resolve(preset, equity=0.0, per_lot=0.0, broker_max_lot=0.0, lot_step=0.01):
    """Turn a preset into the settings that will actually be applied on THIS account.

    `per_lot` is the money a 1.0-lot position loses over a representative stop on the symbol
    being traded (risk_manager.loss_per_lot); it is what converts the broker's lot ceiling
    into a percentage of equity. With it we can say "1% requested, 0.063% actual" instead of
    applying a 1% that the engine will refuse on every single trade.

    Passing zeros (no live account) is fine: the preset then resolves to its nominal numbers
    and reports that the effective risk could not be computed."""
    requested = preset["risk_percent"]
    max_lot = round(_round_down(broker_max_lot * preset["lot_fraction"], lot_step), 2) \
        if broker_max_lot > 0 else 0.0

    expressible = None
    if equity > 0 and per_lot > 0 and max_lot > 0:
        expressible = max_lot * per_lot / equity * 100

    if expressible is None:
        effective, binds = requested, False
    else:
        # Rounded DOWN, so the applied risk always sits inside what the cap can express and
        # the engine's lot-clamp gate never fires purely because of a rounding artefact.
        capped = max(MIN_RISK_PERCENT, math.floor(expressible * LOT_HEADROOM * 1000) / 1000)
        effective = min(requested, capped)
        binds = effective < requested - 1e-9

    settings = {
        "risk_percent": round(effective, 4),
        "max_lot": max_lot,
        "max_concurrent_trades": preset["max_concurrent_trades"],
        "daily_loss_limit_percent": preset["daily_loss_limit_percent"],
        "max_drawdown_percent": preset["max_drawdown_percent"],
        "min_reward_risk": preset["min_reward_risk"],
        "max_sl_atr_multiple": preset["max_sl_atr_multiple"],
        "max_portfolio_risk_percent": preset["max_portfolio_risk_percent"],
    }
    settings.update(preset["toggles"])

    return {
        "id": preset["id"],
        "label": preset["label"],
        "description": preset["description"],
        "settings": settings,
        "timeframe": preset["timeframe"],
        # Presets never choose a strategy: none has a demonstrated edge, so picking one would
        # imply a validation that does not exist.
        "strategy": None,
        "requested_risk_percent": requested,
        "effective_risk_percent": round(effective, 4),
        "max_expressible_risk_percent": round(expressible, 4) if expressible is not None else None,
        "max_lot": max_lot,
        "broker_max_lot": broker_max_lot,
        "lot_fraction": preset["lot_fraction"],
        "lot_cap_binds": binds,
        "risk_summary": _risk_summary(requested, effective, expressible, binds, max_lot),
        "warning": preset.get("warning", ""),
        "requires_confirmation": bool(preset.get("requires_confirmation")),
        "confirmation": preset.get("confirmation", ""),
        "bounds": {k: settings[k] for k in SETTING_KEYS},
    }


def _risk_summary(requested, effective, expressible, binds, max_lot):
    if expressible is None:
        return (f"{requested}% per trade. The effective risk cannot be computed right now — "
                f"MT5 did not return equity or symbol pricing.")
    if binds:
        return (f"{requested}% requested → {effective:.3f}% actual (this profile's {max_lot}-lot "
                f"ceiling binds first; the applied figure sits below the ceiling's "
                f"{expressible:.3f}% maximum so an ordinary drop in volatility does not start "
                f"refusing trades).")
    return f"{requested}% per trade, and this account can size it in full ({max_lot}-lot ceiling)."


def diff(current_settings, current_timeframe, resolved):
    """What an apply would change, for the preview. Only differences are returned."""
    changes = []
    for key, value in resolved["settings"].items():
        before = current_settings.get(key)
        if _same(before, value):
            continue
        changes.append({"key": key, "label": LABELS.get(key, key),
                        "from": before, "to": value})
    if resolved["timeframe"] and resolved["timeframe"] != current_timeframe:
        changes.append({"key": "timeframe", "label": LABELS["timeframe"],
                        "from": current_timeframe, "to": resolved["timeframe"]})
    return changes


def _same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


def bounds_violation(bounds, key, value):
    """The hard part of "profile bounds are hard": a settings write that would push past the
    active profile's ceiling (or under its floor) is refused, not clamped. Returns a
    human-readable reason, or None when the value is within bounds."""
    if not bounds or key not in bounds:
        return None
    limit = bounds[key]
    try:
        number, limit_number = float(value), float(limit)
    except (TypeError, ValueError):
        return None
    if key in FLOOR_KEYS:
        if number < limit_number - 1e-9:
            return (f"{number} is below the active profile's floor of {limit_number} for "
                    f"{LABELS.get(key, key)}")
        return None
    if number > limit_number + 1e-9:
        return (f"{number} exceeds the active profile's limit of {limit_number} for "
                f"{LABELS.get(key, key)}")
    return None
