"""Stop distance has to clear normal bar noise.

Measured on this broker's own bars (both directions, spread charged, ~6,000 bars/symbol),
the share of trades whose take-profit is reached before the stop, against the 40% a 1:1.5
payoff needs just to break even:

    symbol      SL:TP     1.0:1.5   2.0:3.0   3.0:4.5   break-even
    EURUSD# M15             32.1%     35.5%     38.7%       40.0%
    EURUSD# H1              35.8%     38.6%     38.9%       40.0%
    GOLD.i# M15             38.3%     38.9%     39.7%       40.0%

A 1x-ATR stop sits inside the average bar range, so ordinary noise takes it out before the
setup has been proved wrong; the spread is a fixed cost that a tight stop pays a larger
share of. Widening moves the hit rate toward break-even -- it does not create an edge, and
none of these cells beats 40%.
"""
import core.config as config


def test_scalping_stop_clears_one_atr_of_noise():
    s = config.DEFAULT_SETTINGS["scalping"]
    assert s["sl_atr_multiple"] >= 2.0, (
        "a 1x-ATR stop is inside the average bar range; measured TP-first rate was 32% on "
        "EURUSD# M15 against the 40% needed to break even")


def test_scalping_keeps_the_reward_to_risk_floor():
    s = config.DEFAULT_SETTINGS["scalping"]
    ratio = s["tp_atr_multiple"] / s["sl_atr_multiple"]
    assert ratio >= config.GLOBAL_SETTINGS["min_reward_risk"], (
        "widening the stop must widen the target too, or the trade fails the R:R gate")


def test_stop_stays_within_the_max_sl_atr_gate():
    """The widened stop must not be rejected by the engine's own max-stop gate."""
    s = config.DEFAULT_SETTINGS["scalping"]
    assert s["sl_atr_multiple"] <= config.GLOBAL_SETTINGS["max_sl_atr_multiple"]
