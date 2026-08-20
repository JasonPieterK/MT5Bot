import core.profiles as profiles
import pytest


# This account: ~$5.43M equity, broker volume_max 50 lots, and a stop whose loss per 1.0 lot
# is ~$70 (H1 ATR on EURUSD). Those are the numbers that make risk_percent 1.0 unexpressible.
EQUITY = 5_430_000.0
PER_LOT = 70.0
BROKER_MAX_LOT = 50.0


def resolved(preset_id, equity=EQUITY, per_lot=PER_LOT, broker_max_lot=BROKER_MAX_LOT):
    return profiles.resolve(profiles.get(preset_id), equity, per_lot, broker_max_lot)


def test_every_preset_is_present_and_uniquely_identified():
    # Every preset is a rung on the ladder now, so the list IS the ladder, in order.
    ids = [p["id"] for p in profiles.PRESETS]
    assert ids == ["capital_preservation", "conservative", "balanced", "aggressive", "high_risk"]
    assert len(ids) == len(set(ids)), "preset ids must be unique"


def test_get_returns_none_for_an_unknown_preset():
    assert profiles.get("nope") is None


def test_max_lot_is_derived_from_the_brokers_limit_not_hardcoded():
    # Halving the broker's own ceiling must halve every preset's ceiling.
    big = resolved("balanced", broker_max_lot=50.0)["max_lot"]
    small = resolved("balanced", broker_max_lot=25.0)["max_lot"]
    assert big == 25.0
    assert small == 12.5


def test_balanced_risk_is_reduced_to_something_this_account_can_actually_express():
    # THE bug this system exists for: 1% of $5.43M over this stop needs 776 lots and the
    # profile allows 25, so applying a literal 1.0 would make the engine refuse every trade.
    item = resolved("balanced")
    assert item["requested_risk_percent"] == 1.0
    assert item["lot_cap_binds"] is True
    assert item["effective_risk_percent"] < 1.0
    assert item["settings"]["risk_percent"] == item["effective_risk_percent"]
    assert "requested" in item["risk_summary"] and "actual" in item["risk_summary"]


def test_applied_risk_keeps_headroom_below_what_the_lot_ceiling_can_express():
    """Resolving to exactly the ceiling means the next quiet hour makes the cap bind again --
    the stop shrinks with ATR, and the engine goes straight back to refusing every trade."""
    for preset in profiles.PRESETS:
        item = resolved(preset["id"])
        expressible = item["max_expressible_risk_percent"]
        assert item["effective_risk_percent"] <= expressible * profiles.LOT_HEADROOM + 1e-9, preset["id"]


def test_a_halving_of_volatility_does_not_make_an_applied_preset_start_refusing_trades():
    item = resolved("balanced")
    # per_lot scales with the stop distance, which scales with ATR. Halve it.
    quieter = profiles.resolve(profiles.get("balanced"), EQUITY, PER_LOT / 2, BROKER_MAX_LOT)
    assert item["effective_risk_percent"] <= quieter["max_expressible_risk_percent"] + 1e-9


def test_tiers_stay_ordered_even_when_the_broker_cap_binds_on_all_of_them():
    # Clamping every tier to the same account-wide cap would collapse "capital preservation"
    # and "high risk" onto an identical position size. The per-tier lot fraction prevents it.
    risks = [resolved(p["id"])["effective_risk_percent"] for p in profiles.PRESETS]
    assert risks == sorted(risks)
    assert risks[0] < risks[-1]


def test_no_preset_resolves_to_zero_risk():
    for preset in profiles.PRESETS:
        assert resolved(preset["id"])["effective_risk_percent"] >= profiles.MIN_RISK_PERCENT


def test_small_account_can_express_its_full_configured_risk():
    # $10k account, same instrument: 1% is 100 dollars, ~1.4 lots. Nothing binds.
    item = resolved("balanced", equity=10_000.0)
    assert item["lot_cap_binds"] is False
    assert item["effective_risk_percent"] == 1.0


def test_resolve_without_a_live_account_falls_back_to_nominal_numbers():
    item = profiles.resolve(profiles.get("balanced"), equity=0.0, per_lot=0.0, broker_max_lot=0.0)
    assert item["effective_risk_percent"] == 1.0
    assert item["max_expressible_risk_percent"] is None
    assert item["lot_cap_binds"] is False


def test_presets_never_choose_a_strategy():
    # No strategy in this bot has a demonstrated out-of-sample edge, so a preset that picked
    # one would be implying a validation that does not exist.
    for preset in profiles.PRESETS:
        assert resolved(preset["id"])["strategy"] is None


def test_preset_descriptions_never_promise_returns():
    banned = ("profit", "profitable", "returns", "win rate", "edge", "outperform", "gains")
    for preset in profiles.PRESETS:
        text = preset["description"].lower()
        assert not any(word in text for word in banned), preset["id"]


def test_high_risk_preset_requires_confirmation_and_states_the_arithmetic():
    item = resolved("high_risk")
    assert item["requires_confirmation"] is True
    assert "34%" in item["confirmation"]
    assert "ten losing trades" in item["confirmation"]


def test_confirmation_is_demanded_by_exactly_the_riskiest_presets():
    """Blocking every preset would train the user to click through the dialog unread."""
    demanding = {p["id"] for p in profiles.PRESETS if p.get("requires_confirmation")}
    assert demanding == {"high_risk"}
    for p in profiles.PRESETS:
        if p["risk_percent"] >= 3.0:
            assert p.get("requires_confirmation"), f"{p['id']} risks {p['risk_percent']}%"
        else:
            assert not p.get("requires_confirmation"), f"{p['id']} blocks needlessly"


def test_riskier_tiers_loosen_every_limit_monotonically():
    ladder = profiles.PRESETS
    for key in ("max_concurrent_trades", "daily_loss_limit_percent", "max_drawdown_percent"):
        values = [p[key] for p in ladder]
        assert values == sorted(values), key
    # The reward:risk floor moves the other way: the safest tier demands the most.
    floors = [p["min_reward_risk"] for p in ladder]
    assert floors == sorted(floors, reverse=True)


def test_diff_lists_only_what_would_change():
    item = resolved("balanced")
    current = dict(item["settings"])
    assert profiles.diff(current, item["timeframe"], item) == []
    current["max_concurrent_trades"] = 99
    changes = profiles.diff(current, item["timeframe"], item)
    assert [c["key"] for c in changes] == ["max_concurrent_trades"]
    assert changes[0]["from"] == 99
    assert changes[0]["to"] == 3
    assert changes[0]["label"] == "Max trades at once"


def test_diff_reports_a_timeframe_change():
    item = resolved("balanced")
    changes = profiles.diff(dict(item["settings"]), "M1", item)
    assert [c["key"] for c in changes] == ["timeframe"]
    assert changes[0]["to"] == "H1"


def test_bounds_reject_a_value_above_the_profile_ceiling():
    bounds = resolved("capital_preservation")["bounds"]
    assert profiles.bounds_violation(bounds, "max_concurrent_trades", 5) is not None
    assert profiles.bounds_violation(bounds, "max_concurrent_trades", 1) is None


def test_bounds_reject_a_reward_risk_below_the_profile_floor():
    # min_reward_risk is a floor, not a ceiling: lowering it is the violation.
    bounds = resolved("capital_preservation")["bounds"]
    assert bounds["min_reward_risk"] == 2.0
    assert profiles.bounds_violation(bounds, "min_reward_risk", 1.0) is not None
    assert profiles.bounds_violation(bounds, "min_reward_risk", 3.0) is None


def test_bounds_ignore_keys_the_profile_does_not_own():
    bounds = resolved("balanced")["bounds"]
    assert profiles.bounds_violation(bounds, "slippage_points", 9999) is None
    assert profiles.bounds_violation(None, "risk_percent", 999) is None
