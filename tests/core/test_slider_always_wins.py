"""With the "let each strategy choose" box unticked, the sliders decide. Always.

The first version fell back to the strategy's own stop when ATR could not be read. That is a
silent disobedience: the user unticked the box precisely to stop the strategy deciding, and
would have had no way to know a trade went out on levels they had overridden.

If the slider's distance cannot be computed, the correct answer is to place no trade, not to
quietly use somebody else's numbers.
"""
import core.engine as engine

ON = {"bot_stop_override_enabled": True, "bot_sl_atr_multiple": 2.0, "bot_tp_atr_multiple": 3.0}
OFF = {"bot_stop_override_enabled": False, "bot_sl_atr_multiple": 2.0, "bot_tp_atr_multiple": 3.0}
NO_SL = {"bot_stop_override_enabled": True, "bot_sl_atr_multiple": 0, "bot_tp_atr_multiple": 3.0}
NO_TP = {"bot_stop_override_enabled": True, "bot_sl_atr_multiple": 2.0, "bot_tp_atr_multiple": 0}
NEITHER = {"bot_stop_override_enabled": True, "bot_sl_atr_multiple": 0, "bot_tp_atr_multiple": 0}

STRATEGY_SL, STRATEGY_TP = 95.0, 110.0


def _apply(settings, atr=2.0, entry=100.0, direction="BUY"):
    return engine.apply_stop_override(entry, STRATEGY_SL, STRATEGY_TP, atr, direction, settings)


def test_box_ticked_leaves_the_strategy_alone():
    assert _apply(OFF) == (STRATEGY_SL, STRATEGY_TP)


def test_box_unticked_replaces_both_levels():
    sl, tp = _apply(ON)
    assert (sl, tp) == (96.0, 106.0)
    assert sl != STRATEGY_SL and tp != STRATEGY_TP


def test_slider_at_zero_means_none_never_the_strategys_level():
    sl, tp = _apply(NO_SL)
    assert sl is None, "a stop slider at Off must not fall back to the strategy's stop"
    assert tp == 106.0
    sl, tp = _apply(NO_TP)
    assert sl == 96.0
    assert tp is None
    sl, tp = _apply(NEITHER)
    assert (sl, tp) == (None, None)


def test_unreadable_atr_does_not_hand_control_back_to_the_strategy():
    """The case that was wrong: no ATR meant the strategy's levels were used instead."""
    for atr in (0, None, -1):
        sl, tp = _apply(ON, atr=atr)
        assert sl != STRATEGY_SL, f"atr={atr!r} fell back to the strategy's stop"
        assert tp != STRATEGY_TP, f"atr={atr!r} fell back to the strategy's target"
    assert engine.stop_override_unavailable(ON, atr=0) is True
    assert engine.stop_override_unavailable(ON, atr=2.0) is False
    assert engine.stop_override_unavailable(OFF, atr=0) is False, "box ticked: not the slider's problem"


def test_missing_entry_price_is_treated_the_same_way():
    sl, tp = engine.apply_stop_override(None, STRATEGY_SL, STRATEGY_TP, 2.0, "BUY", ON)
    assert sl != STRATEGY_SL and tp != STRATEGY_TP


def test_sell_side_uses_the_slider_too():
    sl, tp = _apply(ON, direction="SELL")
    assert sl == 104.0 and tp == 94.0
