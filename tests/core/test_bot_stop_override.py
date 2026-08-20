"""The Dashboard's stop/target sliders override whatever levels a strategy proposed.

Needed because the strategies do not agree on how a stop is placed: Trend and Scalping use
ATR multiples, SMC uses the prior swing, Pivot breakout uses the pivot level. A single
control can only work by overriding the result, not by editing each strategy's own rule.

Sliding the stop fully left means NO stop. The engine normally refuses any signal without
one -- correctly, since that is an unbounded loss -- so the override has to switch that check
off deliberately. A gate that silently blocks every trade is worse than an honest warning.
"""
import core.config as config
import core.engine as engine


def test_override_is_off_by_default():
    """Ticking nothing must leave every strategy's own levels untouched."""
    assert config.GLOBAL_SETTINGS["bot_stop_override_enabled"] is False


def test_defaults_are_a_real_stop_and_target():
    g = config.GLOBAL_SETTINGS
    assert g["bot_sl_atr_multiple"] > 0
    assert g["bot_tp_atr_multiple"] > g["bot_sl_atr_multiple"], "target should exceed the stop"


def test_disabled_override_returns_the_strategys_own_levels():
    sl, tp = engine.apply_stop_override(entry=100.0, sl=95.0, tp=110.0, atr=2.0, direction="BUY",
                                         global_settings={"bot_stop_override_enabled": False})
    assert (sl, tp) == (95.0, 110.0)


def test_buy_places_the_stop_below_and_the_target_above():
    sl, tp = engine.apply_stop_override(
        entry=100.0, sl=95.0, tp=110.0, atr=2.0, direction="BUY",
        global_settings={"bot_stop_override_enabled": True,
                          "bot_sl_atr_multiple": 2.0, "bot_tp_atr_multiple": 3.0})
    assert sl == 96.0 and tp == 106.0


def test_sell_inverts_both_sides():
    sl, tp = engine.apply_stop_override(
        entry=100.0, sl=105.0, tp=90.0, atr=2.0, direction="SELL",
        global_settings={"bot_stop_override_enabled": True,
                          "bot_sl_atr_multiple": 2.0, "bot_tp_atr_multiple": 3.0})
    assert sl == 104.0 and tp == 94.0


def test_zero_means_no_stop_at_all():
    sl, tp = engine.apply_stop_override(
        entry=100.0, sl=95.0, tp=110.0, atr=2.0, direction="BUY",
        global_settings={"bot_stop_override_enabled": True,
                          "bot_sl_atr_multiple": 0, "bot_tp_atr_multiple": 3.0})
    assert sl is None, "fully-left must remove the stop, not fall back to the strategy's"
    assert tp == 106.0


def test_each_side_is_independent():
    sl, tp = engine.apply_stop_override(
        entry=100.0, sl=95.0, tp=110.0, atr=2.0, direction="BUY",
        global_settings={"bot_stop_override_enabled": True,
                          "bot_sl_atr_multiple": 2.0, "bot_tp_atr_multiple": 0})
    assert sl == 96.0 and tp is None


def test_unknown_atr_does_not_reinstate_the_strategys_levels():
    """This test used to assert the strategy's own levels were kept when ATR was unreadable.
    That was a silent disobedience: the user unticked the box to stop the strategy deciding,
    and a fallback put its numbers back with nothing on screen to say so. The override now
    yields no levels and the caller skips the trade -- see
    tests/core/test_slider_always_wins.py."""
    settings = {"bot_stop_override_enabled": True,
                "bot_sl_atr_multiple": 2.0, "bot_tp_atr_multiple": 3.0}
    sl, tp = engine.apply_stop_override(entry=100.0, sl=95.0, tp=110.0, atr=0.0,
                                         direction="BUY", global_settings=settings)
    assert (sl, tp) == (None, None)
    assert engine.stop_override_unavailable(settings, atr=0.0) is True


def test_deliberately_removing_the_stop_does_not_silently_block_every_trade():
    """The mandatory-stop gate must stand down when the user has chosen no stop, or the bot
    would accept the setting and then refuse every signal without saying why."""
    allowed = engine.stop_is_optional({"bot_stop_override_enabled": True,
                                        "bot_sl_atr_multiple": 0})
    assert allowed is True
    for settings in ({"bot_stop_override_enabled": False, "bot_sl_atr_multiple": 0},
                      {"bot_stop_override_enabled": True, "bot_sl_atr_multiple": 2.0}):
        assert engine.stop_is_optional(settings) is False
