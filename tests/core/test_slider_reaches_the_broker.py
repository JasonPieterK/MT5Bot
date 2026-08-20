"""End-to-end: with the box unticked, the prices that reach place_order are the slider's.

Unit-testing apply_stop_override is not enough -- anything between it and the broker call
could substitute other levels. This runs a real signal through the whole path and reads what
was actually sent.
"""
import pytest

import core.engine as engine
from tests.core.test_engine import BASE_GLOBALS, entry_bridge, run


def _sent(bridge):
    args, kwargs = bridge.place_order.call_args
    return {"sl": args[3] if len(args) > 3 else kwargs.get("sl"),
            "tp": args[4] if len(args) > 4 else kwargs.get("tp")}


def _globals(**over):
    g = dict(BASE_GLOBALS, bot_stop_override_enabled=True,
              bot_sl_atr_multiple=2.0, bot_tp_atr_multiple=3.0,
              trailing_enabled=False, breakeven_enabled=False, partial_tp_enabled=False,
              min_reward_risk=1.0, max_sl_atr_multiple=99.0)
    g.update(over)
    return g


@pytest.fixture(autouse=True)
def _clean():
    engine.reset_bar_gate()
    engine.reset_state_latches()
    yield
    engine.reset_bar_gate()
    engine.reset_state_latches()


def test_the_stop_that_reaches_the_broker_is_the_sliders():
    bridge = entry_bridge()
    run(bridge, globals_=_globals())
    assert bridge.place_order.called
    sent = _sent(bridge)
    entry = bridge.get_rates.return_value["close"].iloc[-1]
    atr = engine._atr_now(bridge.get_rates.return_value)
    assert sent["sl"] == pytest.approx(entry - atr * 2.0, rel=1e-6)
    assert sent["tp"] == pytest.approx(entry + atr * 3.0, rel=1e-6)


def test_stop_slider_off_reaches_the_broker_as_no_stop():
    bridge = entry_bridge()
    run(bridge, globals_=_globals(bot_sl_atr_multiple=0))
    assert bridge.place_order.called
    assert _sent(bridge)["sl"] is None, "a stop appeared that the user switched off"


def test_target_slider_off_reaches_the_broker_as_no_target():
    bridge = entry_bridge()
    run(bridge, globals_=_globals(bot_tp_atr_multiple=0))
    assert bridge.place_order.called
    assert _sent(bridge)["tp"] is None


def test_no_order_is_sent_when_the_slider_distance_cannot_be_computed(monkeypatch):
    bridge = entry_bridge()
    monkeypatch.setattr(engine, "_atr_now", lambda rates: 0.0)
    run(bridge, globals_=_globals())
    bridge.place_order.assert_not_called()
