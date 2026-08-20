"""MT5 spells "no stop loss" as 0.0, not as None.

Live evidence: with the stop slider set to Off the bot logged "opening with NO STOP LOSS"
and the terminal answered `(-2, 'Invalid "sl" argument')` — the whole request was refused,
so the feature could never place a single order.
"""
import types

import pytest

from tests.core.test_mt5_bridge import mt5_mock  # noqa: F401  (fixture)


def _prep(fake, digits=2):
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=4000.0, bid=3999.8)
    fake.symbol_info.return_value = types.SimpleNamespace(digits=digits)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)


def test_absent_stop_is_sent_as_zero_not_none(mt5_mock):
    bridge, fake = mt5_mock
    _prep(fake)
    bridge.place_order("GOLD.i#", "BUY", 0.1, sl=None, tp=None, slippage_points=20)
    sent = fake.order_send.call_args[0][0]
    assert sent["sl"] == 0.0 and sent["tp"] == 0.0
    assert sent["sl"] is not None and sent["tp"] is not None


def test_a_real_stop_is_still_rounded_and_sent(mt5_mock):
    bridge, fake = mt5_mock
    _prep(fake)
    bridge.place_order("GOLD.i#", "BUY", 0.1, sl=3990.126, tp=4020.874, slippage_points=20)
    sent = fake.order_send.call_args[0][0]
    assert sent["sl"] == 3990.13 and sent["tp"] == 4020.87


def test_one_side_absent_the_other_set(mt5_mock):
    bridge, fake = mt5_mock
    _prep(fake)
    bridge.place_order("GOLD.i#", "SELL", 0.1, sl=None, tp=3980.5, slippage_points=20)
    sent = fake.order_send.call_args[0][0]
    assert sent["sl"] == 0.0
    assert sent["tp"] == 3980.5


def test_modify_position_also_uses_zero_for_removal(mt5_mock):
    """Clearing a stop on an open position is the same convention."""
    bridge, fake = mt5_mock
    fake.TRADE_ACTION_SLTP = 6
    fake.positions_get.return_value = [
        types.SimpleNamespace(ticket=7, symbol="GOLD.i#", volume=1.0, profit=0.0, type=0,
                               price_open=4000.0, sl=0.0, tp=0.0)]
    fake.symbol_info.return_value = types.SimpleNamespace(digits=2)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    bridge.modify_position(7, sl=None, tp=None)
    sent = fake.order_send.call_args[0][0]
    assert sent["sl"] == 0.0 and sent["tp"] == 0.0
