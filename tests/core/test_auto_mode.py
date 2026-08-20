"""Auto mode: filter -> selector -> sizer, in that order and only that order.

The three mechanisms answer different questions, so these tests are mostly about proving
they cannot start answering each other's: the regime filter decides eligibility and never
sizes, the results selector chooses only from what the filter left and never sizes, and the
streak sizer never picks a strategy. Plus the two hard promises: the profile's bounds are
never exceeded in any direction, and a thin sample makes Auto do nothing and say so."""
import core.auto_mode as auto_mode
import core.config as config
import core.risk_manager as rm


def stats(profit_factor, trades):
    """The shape analysis.analytics.compute_per_strategy_stats returns. Trade count is the
    length of the equity curve -- that is what auto_tuner counts."""
    return {"profit_factor": profit_factor, "equity_curve": [1.0] * trades,
            "win_rate": 50.0, "current_streak": 0}


def decide(**kwargs):
    base = {"enabled": True, "regime": "NORMAL", "per_strategy_stats": {},
            "recent_results": [], "current_strategy": "trend", "profile_risk_percent": 1.0}
    base.update(kwargs)
    return auto_mode.decide(**base)


# ---------- off by default ----------

def test_auto_mode_is_off_in_the_shipped_defaults():
    assert config.GLOBAL_SETTINGS["auto_mode_enabled"] is False


def test_disabled_auto_changes_nothing_at_all():
    d = decide(enabled=False, regime="HIGH", profile_risk_percent=2.0,
               recent_results=[-1.0, -1.0, -1.0],
               per_strategy_stats={"smc": stats(3.0, 500)})
    assert d["enabled"] is False
    assert d["strategy"] is None
    assert d["strategy_changed"] is False
    assert d["risk_multiplier"] == 1.0
    assert d["risk_percent"] == 2.0
    assert "off" in d["line"].lower()


# ---------- 1. regime is the eligibility filter, applied first ----------

def test_high_volatility_excludes_scalping():
    eligible, excluded = auto_mode.eligible_strategies("HIGH")
    assert "scalping" not in eligible
    assert "scalping" in excluded
    assert excluded["scalping"]  # a stated reason, not a bare flag
    assert "trend" in eligible and "smc" in eligible


def test_low_volatility_excludes_the_expansion_strategies():
    eligible, excluded = auto_mode.eligible_strategies("LOW")
    assert "trend" not in eligible
    assert "pivot_breakout" not in eligible
    assert "scalping" in eligible and "smc" in eligible


def test_normal_volatility_excludes_nothing():
    eligible, excluded = auto_mode.eligible_strategies("NORMAL")
    assert list(eligible) == list(auto_mode.CANDIDATES)
    assert excluded == {}


def test_an_unreadable_regime_is_not_silently_treated_as_normal():
    eligible, excluded = auto_mode.eligible_strategies(None)
    assert eligible == []
    d = decide(regime=None, per_strategy_stats={"smc": stats(3.0, 500)})
    assert d["strategy"] is None
    assert "regime" in d["reason"].lower()


# ---------- precedence: the filter beats the selector ----------

def test_the_best_performer_is_not_picked_when_the_regime_excludes_it():
    """Scalping has by far the best realised profit factor AND a huge sample. In a HIGH
    volatility regime it is not eligible, so it must not be selected -- the filter runs
    first and the selector only ever sees what survived it."""
    per_strategy = {"scalping": stats(4.0, 500), "smc": stats(1.2, 500)}
    d = decide(regime="HIGH", per_strategy_stats=per_strategy)
    assert d["strategy"] == "smc"
    assert "scalping" in d["excluded"]

    # Same numbers, regime NORMAL: now scalping is eligible and wins on results.
    assert decide(regime="NORMAL", per_strategy_stats=per_strategy)["strategy"] == "scalping"


def test_the_regime_filter_never_changes_position_size():
    per_strategy = {"smc": stats(2.0, 500)}
    quiet = decide(regime="LOW", per_strategy_stats=per_strategy)
    loud = decide(regime="HIGH", per_strategy_stats=per_strategy)
    assert quiet["risk_percent"] == loud["risk_percent"] == 1.0


# ---------- 2. results are the selector ----------

def test_the_selector_picks_the_best_realised_profit_factor_among_the_eligible():
    d = decide(per_strategy_stats={"trend": stats(0.9, 100), "smc": stats(1.4, 100),
                                    "scalping": stats(1.1, 100)})
    assert d["strategy"] == "smc"
    assert d["strategy_from"] == "trend"
    assert d["strategy_changed"] is True


def test_a_strategy_flagged_for_poor_profit_factor_is_never_selected():
    # smc has the best PF of the two with enough trades, but is still under the 0.8 floor.
    d = decide(per_strategy_stats={"smc": stats(0.5, 100), "trend": stats(0.4, 100)})
    assert d["strategy"] is None
    assert sorted(d["flagged"]) == ["smc", "trend"]
    assert "flagged" in d["reason"].lower() or "profit factor" in d["reason"].lower()


def test_selecting_the_strategy_already_running_is_not_reported_as_a_change():
    d = decide(current_strategy="smc", per_strategy_stats={"smc": stats(1.4, 100),
                                                            "trend": stats(1.0, 100)})
    assert d["strategy"] == "smc"
    assert d["strategy_changed"] is False


# ---------- 3. the streak is only a sizer ----------

def test_the_streak_never_picks_a_strategy():
    per_strategy = {"trend": stats(1.5, 100), "smc": stats(1.2, 100)}
    flat = decide(per_strategy_stats=per_strategy, recent_results=[1.0, 1.0, 1.0])
    losing = decide(per_strategy_stats=per_strategy, recent_results=[-1.0, -1.0, -1.0])
    assert flat["strategy"] == losing["strategy"] == "trend"
    assert losing["risk_percent"] < flat["risk_percent"]


def test_streak_sizing_reduces_after_consecutive_losses_and_recovers_on_a_win():
    none = decide(recent_results=[1.0, 1.0])
    one = decide(recent_results=[1.0, -1.0])
    three = decide(recent_results=[-1.0, -1.0, -1.0])
    recovered = decide(recent_results=[-1.0, -1.0, -1.0, 1.0])

    assert none["risk_percent"] == 1.0 and none["streak"] == 0
    assert one["streak"] == 1 and one["risk_percent"] < none["risk_percent"]
    assert three["streak"] == 3 and three["risk_percent"] < one["risk_percent"]
    # A single win restores the full profile risk -- anti-martingale, not a ratchet.
    assert recovered["streak"] == 0 and recovered["risk_percent"] == 1.0


def test_streak_sizing_uses_the_existing_risk_manager_rule():
    results = [-1.0, -1.0]
    assert decide(recent_results=results)["risk_multiplier"] == rm.calc_streak_multiplier(results)


# ---------- the profile's bounds are absolute ----------

def test_risk_never_exceeds_the_profile_for_any_history():
    for results in ([], [1.0], [1.0] * 50, [-1.0], [-1.0] * 50, [1.0, -1.0] * 10):
        d = decide(profile_risk_percent=0.25, recent_results=results)
        assert d["risk_multiplier"] <= 1.0
        assert d["risk_percent"] <= 0.25 + 1e-12, results


def test_a_multiplier_above_one_is_clamped_rather_than_trusted(monkeypatch):
    """The single line that makes 'auto may only ever reduce' true regardless of what the
    sizer returns. Without the clamp, any future change to calc_streak_multiplier's base
    would quietly raise risk past the profile."""
    monkeypatch.setattr(rm, "calc_streak_multiplier", lambda *a, **k: 5.0)
    d = decide(profile_risk_percent=1.0)
    assert d["risk_multiplier"] == 1.0
    assert d["risk_percent"] == 1.0


def test_clamp_risk_is_bounded_on_both_sides():
    assert auto_mode.clamp_risk(1.0, 0.4) == 0.4
    assert auto_mode.clamp_risk(1.0, 1.0) == 1.0
    assert auto_mode.clamp_risk(1.0, 2.5) == 1.0
    assert auto_mode.clamp_risk(1.0, -3.0) == 0.0


def test_auto_produces_no_value_for_any_bound_other_than_risk():
    """Concurrency, lot ceiling, daily loss, drawdown and the reward:risk floor cannot be
    loosened by Auto because Auto never emits them. This is the structural half of 'the
    profile's bounds are absolute' -- there is nothing to enforce because there is nothing
    to write."""
    d = decide(per_strategy_stats={"smc": stats(2.0, 500)}, recent_results=[-1.0] * 5)
    forbidden = {"max_lot", "max_concurrent_trades", "daily_loss_limit_percent",
                 "max_drawdown_percent", "min_reward_risk", "max_sl_atr_multiple",
                 "max_portfolio_risk_percent", "block_when_lot_capped"}
    assert forbidden & set(d) == set()


# ---------- insufficient sample: do nothing, and say so ----------

def test_the_minimum_sample_is_higher_than_the_auto_tuner_default():
    """auto_tuner defaults to 10. Ten closed trades cannot separate strategies whose
    measured zero-spread expectancy all sit within +/-0.07R of zero."""
    assert auto_mode.MIN_TRADES > 10


def test_a_thin_sample_makes_auto_do_nothing_and_report_the_numbers():
    d = decide(per_strategy_stats={"trend": stats(3.0, 4), "smc": stats(2.0, 3)})
    assert d["strategy"] is None
    assert d["strategy_changed"] is False
    assert d["sample_sufficient"] is False
    assert d["sample"]["trend"] == 4 and d["sample"]["smc"] == 3
    assert str(auto_mode.MIN_TRADES) in d["reason"]
    assert "4" in d["reason"]  # the largest sample it actually has


def test_a_thin_sample_does_not_stop_the_streak_sizer():
    """Sizing is an independent axis: it needs no cross-strategy comparison, only the last
    few results, so a thin sample must not disable it."""
    d = decide(per_strategy_stats={"trend": stats(3.0, 2)}, recent_results=[-1.0, -1.0])
    assert d["strategy"] is None
    assert d["risk_percent"] < 1.0


def test_no_history_at_all_is_reported_as_no_history_not_as_a_pick():
    d = decide(per_strategy_stats={})
    assert d["strategy"] is None
    assert d["sample_sufficient"] is False


def test_a_regime_that_leaves_nothing_eligible_does_nothing():
    d = decide(regime="HIGH", candidates=("scalping",),
               per_strategy_stats={"scalping": stats(5.0, 500)})
    assert d["eligible"] == []
    assert d["strategy"] is None
    assert "scalping" in d["excluded"]


# ---------- the log line ----------

def test_the_log_line_carries_the_evidence_a_user_needs():
    d = decide(regime="HIGH", recent_results=[-1.0, -1.0],
               per_strategy_stats={"smc": stats(1.6, 100), "trend": stats(1.1, 100)})
    line = d["line"]
    assert line == auto_mode.describe(d)
    assert "HIGH" in line                      # the regime detected
    assert "100" in line                       # the sample size
    assert "2 " in line and "loss" in line     # the streak length
    assert "smc" in line and "trend" in line   # from what, to what
    assert "%" in line                         # the risk, before and after


def test_the_log_line_says_plainly_when_nothing_changed():
    d = decide(per_strategy_stats={"trend": stats(3.0, 5)})
    assert "unchanged" in d["line"].lower() or "leaving" in d["line"].lower()
    assert str(auto_mode.MIN_TRADES) in d["line"]


def test_the_caveat_does_not_claim_an_edge():
    text = (auto_mode.CAVEAT + " " + auto_mode.__doc__).lower()
    for word in ("profitable", "edge", "outperform", "improve returns", "optimal"):
        # The words may appear, but only in a negation. Nothing here may read as a promise.
        if word in text:
            assert "no " + word in text or "not " + word in text or "never " + word in text
