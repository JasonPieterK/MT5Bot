"""Auto mode: three mechanisms, layered in one fixed order — filter, then selector, then sizer.

They do not compete, and there is deliberately no "conflict resolution" step, because by
construction they cannot disagree. Each answers a different question:

  1. FILTER   — analysis/volatility_regime.classify_regime says which strategies are ALLOWED
                to trade in the current market state. A hard gate, applied first. It decides
                eligibility and nothing else; it never sizes anything.
  2. SELECTOR — automation/auto_tuner picks, from what step 1 left, the strategy with the
                best realised profit factor on THIS account. It can only ever choose from
                the survivors of the filter, so it can never overrule it. It never sizes.
  3. SIZER    — core/risk_manager.calc_streak_multiplier scales position size down after
                consecutive losses and restores it on the first win. It runs on an
                independent axis and never picks a strategy.

If a future reader is tempted to add a precedence table: there is nothing to arbitrate. The
filter's output is the selector's input, and the sizer's output is a number, not a name.

What this is honestly doing
---------------------------
Walk-forward testing across 4 strategies x 4 symbols x 3 timeframes on this account found
no edge for any strategy: zero-spread expectancy sat within +/-0.07R of zero everywhere, and
tuned parameters lost to the defaults out of sample. So step 2 is choosing among options
that are all approximately zero-expectancy, on a small sample. It rotates away from whatever
has been losing on this account lately. It is not a way to make money, and nothing in this
module should ever be described as though it were.

That is also why MIN_TRADES here is higher than auto_tuner's own default — see below — and
why every path that lacks evidence returns "changed nothing", loudly, instead of guessing.

Pure by design: no MT5 calls live here. The caller reads the bars, the deal history and the
account, and passes the results in, so every decision is reproducible in a unit test.
"""
import automation.auto_tuner as auto_tuner
import core.risk_manager as rm

# The strategies Auto is allowed to rotate between.
#
# grid is excluded: it adds positions against the move and carries its own hard equity/lot
# stops, so rotating INTO it on a thin profit-factor comparison is not a risk Auto should be
# able to take on the user's behalf. ensemble is excluded because it is a vote over the
# others, so selecting it would double-count whatever the selector just measured.
CANDIDATES = ("trend", "scalping", "smc", "pivot_breakout")

# Which candidates each volatility regime rules out, and why in one plain sentence.
#
# These are statements about where a strategy's own mechanics stop working, not measured
# results — no strategy here has a demonstrated edge in any regime, and this table does not
# claim one. classify_regime returns LOW / NORMAL / HIGH by ATR percentile against its own
# recent history, so "HIGH" means "loud for this symbol lately", not "loud in absolute terms".
REGIME_EXCLUSIONS = {
    "HIGH": {
        "scalping": "its stop is about 1x ATR, and in the loudest third of recent volatility "
                    "a stop that size sits inside ordinary noise",
        "grid": "it adds positions against the move, which is unbounded when ranges expand",
    },
    "LOW": {
        "trend": "it needs the moving averages to separate, which the quietest third of "
                 "recent volatility rarely produces",
        "pivot_breakout": "a breakout level in the quietest third of recent volatility is "
                          "mostly noise around a flat mean",
    },
    "NORMAL": {},
}

# The minimum closed trades on a strategy before its realised results may be acted on.
#
# auto_tuner defaults to 10. Ten is not honest here. The measured gap between these
# strategies is within +/-0.07R with a per-trade spread of roughly 1R, so separating any two
# of them at ordinary confidence would need trades in the thousands, not tens. No threshold
# available on a real account makes this pick evidence of an edge.
#
# 30 is therefore not "enough to be sure" — it is the floor below which even the SIGN of a
# profit factor is a coin flip, and below which Auto refuses to act at all rather than
# dressing up noise as a decision. Read a switch at 30 trades as "stop repeating the one
# that has been losing", never as "this one works".
MIN_TRADES = 30

# The profit-factor floor under which a strategy is flagged and never selected, matching
# automation/auto_tuner.suggest_strategy_disable's own default.
MIN_PROFIT_FACTOR = 0.8

CAVEAT = ("Auto mode rotates between strategies on this account's own recent closed trades, "
          "and cuts position size after consecutive losses. Walk-forward testing on this "
          "account found no edge for any of these strategies, so rotating between them is "
          "not a way to make money — it is only a way to stop repeating whichever one has "
          f"been losing here lately. Below {MIN_TRADES} closed trades on a strategy it does "
          "nothing at all, and says so. It can only ever lower risk, never raise it: the "
          "active profile's limits are hard bounds and Auto moves strictly inside them.")


def eligible_strategies(regime, candidates=CANDIDATES):
    """(eligible, excluded) for this regime. An unrecognised or missing regime leaves
    NOTHING eligible: a regime the caller could not read is not the same as a calm one, and
    quietly treating it as NORMAL would let the filter be skipped by an MT5 hiccup."""
    if regime not in REGIME_EXCLUSIONS:
        return [], {}
    rules = REGIME_EXCLUSIONS[regime]
    excluded = {name: reason for name, reason in rules.items() if name in candidates}
    return [name for name in candidates if name not in excluded], excluded


def is_excluded(regime, strategy):
    """Whether the regime filter rules THIS strategy out — asked of the running strategy,
    which is not necessarily one Auto may rotate into.

    `eligible_strategies` trims its `excluded` dict to `candidates`, so grid never appears
    there even though HIGH volatility rules it out by name. Asking "is it in eligible?"
    instead would also catch ensemble, which no regime excludes, and stop it for no stated
    reason. An unreadable regime counts as excluded for everything: a regime the caller
    could not read is not a permission to keep trading."""
    if regime not in REGIME_EXCLUSIONS:
        return True
    return strategy in REGIME_EXCLUSIONS[regime]


def losing_streak(recent_results):
    """How many losses in a row end this list. Mirrors the rule inside
    risk_manager.calc_streak_multiplier, which returns the multiplier but not the count —
    and the count is the evidence the user has to be shown alongside it."""
    streak = 0
    for result in reversed(recent_results or []):
        if result < 0:
            streak += 1
        else:
            break
    return streak


def clamp_risk(profile_risk_percent, multiplier):
    """The one line that makes "Auto may only ever reduce" true no matter what the sizer
    returns. The profile's risk is a ceiling, so a multiplier above 1.0 is clamped rather
    than trusted; a negative one is floored at zero rather than flipping the sign."""
    factor = min(1.0, max(0.0, float(multiplier)))
    return round(min(float(profile_risk_percent), float(profile_risk_percent) * factor), 6)


def decide(*, enabled, regime, per_strategy_stats, recent_results, current_strategy,
           profile_risk_percent, candidates=CANDIDATES, min_trades=MIN_TRADES,
           min_profit_factor=MIN_PROFIT_FACTOR):
    """One tick's Auto decision, as data. Returns a strategy name (or None for "leave it
    alone") and a risk percent that is never above `profile_risk_percent`.

    Note what is NOT in the returned dict: max_lot, concurrency, the loss limits, the
    reward:risk floor. Auto cannot loosen those because it never produces a value for them.
    """
    decision = {
        "enabled": bool(enabled),
        "regime": regime,
        "eligible": [],
        "excluded": {},
        "min_trades": min_trades,
        "min_profit_factor": min_profit_factor,
        "sample": {},
        "sample_sufficient": False,
        "flagged": [],
        "strategy": None,
        "strategy_from": current_strategy,
        "strategy_changed": False,
        # Set when the filter has excluded the running strategy and Auto has no replacement
        # it may justify. The caller must open nothing this tick -- see the hard-gate block
        # in decide().
        "block_trading": False,
        "streak": 0,
        "risk_multiplier": 1.0,
        "profile_risk_percent": profile_risk_percent,
        "risk_percent": profile_risk_percent,
        "reason": "",
    }

    if not enabled:
        decision["reason"] = ("Auto mode is off, so the strategy and the position size are "
                              "exactly what you set.")
        decision["line"] = describe(decision)
        return decision

    # --- 1. FILTER -------------------------------------------------------------------
    eligible, excluded = eligible_strategies(regime, candidates)
    decision["eligible"] = eligible
    decision["excluded"] = excluded

    # --- 2. SELECTOR (only ever over what the filter left) ----------------------------
    eligible_stats = {name: s for name, s in (per_strategy_stats or {}).items()
                      if name in eligible}
    decision["sample"] = {name: len(s.get("equity_curve", []))
                          for name, s in eligible_stats.items()}
    largest = max(decision["sample"].values(), default=0)
    decision["sample_sufficient"] = largest >= min_trades
    decision["flagged"] = auto_tuner.suggest_strategy_disable(
        eligible_stats, min_profit_factor, min_trades)

    if regime not in REGIME_EXCLUSIONS:
        decision["reason"] = ("the volatility regime could not be read, so the eligibility "
                              "filter cannot run and Auto is not switching strategy")
    elif not eligible:
        decision["reason"] = (f"the {regime} volatility regime leaves none of the candidate "
                              f"strategies eligible")
    elif not decision["sample_sufficient"]:
        decision["reason"] = (
            f"the largest sample on any eligible strategy is {largest} closed trades, below "
            f"the {min_trades}-trade minimum, so there is nothing here to choose on")
    else:
        # Flagged strategies are removed BEFORE the pick, so Auto can never rotate into one
        # merely because it was the least bad of a bad set.
        pickable = {name: s for name, s in eligible_stats.items()
                    if name not in decision["flagged"]}
        best = auto_tuner.suggest_best_strategy(pickable, min_trades)
        if best is None:
            decision["reason"] = (
                f"every eligible strategy with enough history is flagged for a profit factor "
                f"below {min_profit_factor}, so there is nothing to rotate into")
        else:
            decision["strategy"] = best
            decision["strategy_changed"] = best != current_strategy
            decision["reason"] = (
                f"{best} has the best realised profit factor "
                f"({eligible_stats[best]['profit_factor']}) of the eligible strategies on "
                f"{decision['sample'][best]} closed trades")

    # --- 1b. THE FILTER IS A GATE ON WHAT RUNS, NOT ONLY ON WHAT GETS PICKED ----------
    #
    # Every non-selecting branch above leaves decision["strategy"] as None, which the caller
    # reads as "leave the running strategy alone". That is only safe while the running
    # strategy is itself eligible. When the filter has just excluded it, "leave it alone"
    # means "keep trading the strategy we declared ineligible" -- Auto printing
    # "excludes scalping" and "strategy unchanged (scalping)" in one breath, which is what
    # sent us here. A gate that only constrains selection is not a gate.
    if decision["strategy"] is None and is_excluded(regime, current_strategy):
        regime_text = regime or "unreadable"
        ruled_out = excluded.get(current_strategy) or REGIME_EXCLUSIONS.get(
            regime, {}).get(current_strategy)
        because = f" ({ruled_out})" if ruled_out else ""
        if len(eligible) == 1:
            # The only permitted option needs no performance evidence, because there is no
            # choice to make: MIN_TRADES guards CHOICES between strategies, and one option
            # is not a choice. Refusing to switch here would only mean continuing to trade
            # the one strategy the filter has already ruled out.
            only = eligible[0]
            decision["strategy"] = only
            decision["strategy_changed"] = only != current_strategy
            decision["reason"] = (
                f"the {regime_text} volatility regime rules out {current_strategy}"
                f"{because}, and {only} is the only strategy it leaves eligible — the only "
                f"permitted option needs no performance evidence to justify it")
        else:
            # Several eligible and nothing that can separate them, or none eligible at all.
            # Picking one anyway is exactly the noise-chasing MIN_TRADES exists to stop, and
            # leaving the excluded one running is what the filter just forbade. So: trade
            # nothing this tick and say why. Doing nothing is the only option here that is
            # not either guessing or ignoring the filter.
            decision["block_trading"] = True
            unable = decision["reason"]
            if not eligible:
                tail = ("and the same regime leaves no strategy eligible to replace it, so "
                        "no new trades are opened this tick")
            else:
                tail = (f"and the evidence cannot choose between the {len(eligible)} it does "
                        f"leave eligible ({', '.join(eligible)}) — {unable} — so rather than "
                        f"pick one at random, no new trades are opened this tick")
            decision["reason"] = (
                f"the {regime_text} volatility regime rules out the running strategy "
                f"{current_strategy}{because}, {tail}")

    # --- 3. SIZER (independent axis: it needs no cross-strategy comparison) -----------
    decision["streak"] = losing_streak(recent_results)
    decision["risk_multiplier"] = min(1.0, max(0.0, rm.calc_streak_multiplier(
        list(recent_results or []))))
    decision["risk_percent"] = clamp_risk(profile_risk_percent, decision["risk_multiplier"])

    decision["line"] = describe(decision)
    return decision


def describe(decision):
    """The single plain-English line written to logs/app.log. It has to answer "why is it
    trading this way right now?" on its own, so it carries what changed, from what to what,
    why, and the evidence: the regime, the sample size and the streak length."""
    if not decision["enabled"]:
        return ("Auto mode is off — the strategy and position size are exactly your own "
                "settings.")

    if decision.get("block_trading"):
        # Never "strategy unchanged (X)" here: X is precisely the strategy the filter
        # excluded, and saying both in one line is the contradiction this head exists to
        # make unsayable.
        head = f"opening no new trades ({decision['strategy_from']} is not eligible here)"
    elif decision["strategy_changed"]:
        head = (f"switching strategy {decision['strategy_from']} -> {decision['strategy']}")
    elif decision["strategy"]:
        head = f"keeping strategy {decision['strategy']}"
    else:
        head = f"strategy unchanged ({decision['strategy_from']})"

    streak = decision["streak"]
    if streak:
        risk = (f"Risk {decision['profile_risk_percent']}% -> {decision['risk_percent']}% "
                f"after {streak} consecutive "
                f"{'loss' if streak == 1 else 'losses'}.")
    else:
        risk = f"Risk stays at {decision['profile_risk_percent']}% (no losing streak)."

    excluded = decision["excluded"]
    regime_text = f"volatility regime {decision['regime'] or 'unreadable'}"
    if excluded:
        regime_text += f" (excludes {', '.join(sorted(excluded))})"

    sample = decision["sample"]
    sample_text = (", ".join(f"{name} {count}" for name, count in sorted(sample.items()))
                   if sample else "no closed trades attributed to an eligible strategy")

    return (f"Auto mode: {head} — {decision['reason']}. {risk} "
            f"Evidence: {regime_text}; closed trades per eligible strategy: {sample_text}; "
            f"minimum to act on results is {decision['min_trades']}.")
