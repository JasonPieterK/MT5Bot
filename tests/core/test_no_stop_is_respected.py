"""Choosing "no stop loss" must survive the position being opened.

Live report: with the stop slider fully left, positions still ended up with a stop. The
order goes out naked (sl=0), and then the trailing-stop / break-even automation attaches one
on the next 5-second tick -- `apply_trailing` treats "no stop yet" as the very case it
should fix. Two settings contradicted each other and the automation silently won, so the
slider lied about what the bot was doing.

The user's explicit choice wins. Position management stands down, and says so once.
"""
from unittest.mock import MagicMock

import core.engine as engine


NO_STOP = {"bot_stop_override_enabled": True, "bot_sl_atr_multiple": 0,
            "trailing_enabled": True, "breakeven_enabled": True, "partial_tp_enabled": True}
NORMAL = {"bot_stop_override_enabled": False, "bot_sl_atr_multiple": 2.0,
           "trailing_enabled": True, "breakeven_enabled": True, "partial_tp_enabled": True}


def _bridge():
    b = MagicMock()
    b.get_open_positions.return_value = [
        {"ticket": 1, "symbol": "GOLD.i#", "volume": 1.0, "profit": 5.0,
         "type": "BUY", "price_open": 4000.0, "sl": 0.0, "tp": 4100.0}]
    b.get_current_price.return_value = (4010.0, 4010.2)
    b.get_symbol_point.return_value = 0.01
    b.modify_position.return_value = (True, 10009)
    return b


def test_no_stop_chosen_means_nothing_attaches_one(monkeypatch):
    b = _bridge()
    engine.reset_state_latches()
    engine._manage_positions(b, NO_STOP)
    assert not b.modify_position.called, (
        "trailing/break-even attached a stop to a position the user chose to run without one")


def test_normal_settings_still_manage_the_position():
    """The stand-down must be narrow: ordinary runs keep their trailing stop."""
    b = _bridge()
    b.get_open_positions.return_value[0]["sl"] = 3990.0
    engine.reset_state_latches()
    engine._manage_positions(b, NORMAL)
    assert b.modify_position.called


def test_the_stand_down_is_logged_once(monkeypatch, tmp_path):
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "a.log"))
    b = _bridge()
    engine.reset_state_latches()
    for _ in range(10):
        engine._manage_positions(b, NO_STOP)
    lines = [l for l in app_logger.tail(50) if "stop management" in l.lower()]
    assert len(lines) == 1, f"expected one line, got {len(lines)}"
