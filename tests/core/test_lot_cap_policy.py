"""The broker lot cap must not block a trade.

Hitting the cap makes the position SMALLER: the stop loss is unchanged, so the money at
risk is strictly below the configured percentage. Refusing it meant refusing trades for
being too safe -- which is what stopped this bot trading at all on a large account.

The genuinely dangerous direction is the mirror case, where the broker's MINIMUM lot forces
more risk than configured. That one still blocks; see test_min_lot_still_blocks.
"""
import core.config as config
import core.risk_manager as rm


# GOLD.i# on a $5M account, taken from a real refusal.
EQUITY, RISK, SL, TICK_VALUE, TICK_SIZE, CAP = 5_000_000.0, 0.388, 1.40824, 1.0, 0.01, 25.0


def test_capping_reduces_risk_rather_than_raising_it():
    per_lot = rm.loss_per_lot(SL, TICK_VALUE, TICK_SIZE)
    wanted_lots = EQUITY * RISK / 100 / per_lot
    assert wanted_lots > CAP, "this scenario is only interesting when the cap binds"
    risk_if_capped = CAP * per_lot / EQUITY * 100
    assert risk_if_capped < RISK, "capping must never increase the risk taken"


def test_report_states_the_smaller_realised_risk():
    lots = CAP
    report = rm.lot_clamp_report(EQUITY, RISK, SL, TICK_VALUE, TICK_SIZE, CAP, lots)
    assert report is not None
    assert report["actual_risk_percent"] < report["configured_risk_percent"]


def test_blocking_is_off_by_default():
    """A safer-than-requested trade should go through without the user changing anything."""
    assert config.GLOBAL_SETTINGS["block_when_lot_capped"] is False


def test_no_preset_turns_blocking_back_on():
    import core.profiles as profiles
    for preset in profiles.PRESETS:
        assert preset.get("toggles", {}).get("block_when_lot_capped", False) is False, (
            f"preset {preset['id']} would re-block capped sizing")


def test_min_lot_still_blocks_because_it_raises_risk():
    """The opposite case: a tiny account where min_lot forces MORE than the configured risk."""
    report = rm.min_lot_overrisk_report(equity=100.0, risk_percent=1.0, sl_distance_price=0.0050,
                                         tick_value=1.0, tick_size=0.00001, min_lot=0.01,
                                         actual_lots=0.01)
    assert report is not None, "min_lot over-risk must still be reported"
    assert report["actual_risk_percent"] > 1.0
