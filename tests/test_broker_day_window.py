"""Today's P&L must use the BROKER's day, not the local machine's.

`mt5.history_deals_get(from, to)` interprets its arguments in server time. The daily-loss
window was built from `datetime.now()`, the local clock. Measured against the live terminal
the broker runs +3h from local, so the window was three hours out: losses from the previous
broker day counted as today's, and this morning's were missed. That decides when the
daily-loss kill switch fires.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

import core.mt5_bridge as bridge


def test_broker_offset_is_measured_not_assumed(monkeypatch):
    fake = MagicMock()
    # Broker tick three hours ahead of this machine.
    local = datetime.now()
    fake.symbol_info_tick.return_value = MagicMock(
        time=int((local + timedelta(hours=3)).timestamp()))
    monkeypatch.setattr(bridge, "mt5", fake)
    off = bridge.broker_clock_offset("GOLD.i#")
    assert 2.5 < off.total_seconds() / 3600 < 3.5


def test_offset_is_zero_when_the_clocks_agree(monkeypatch):
    fake = MagicMock()
    fake.symbol_info_tick.return_value = MagicMock(time=int(datetime.now().timestamp()))
    monkeypatch.setattr(bridge, "mt5", fake)
    assert abs(bridge.broker_clock_offset("EURUSD#").total_seconds()) < 120


def test_unreadable_tick_falls_back_to_no_offset(monkeypatch):
    """Better to use the local day than to crash or invent a shift."""
    fake = MagicMock()
    fake.symbol_info_tick.return_value = None
    monkeypatch.setattr(bridge, "mt5", fake)
    assert bridge.broker_clock_offset("EURUSD#") == timedelta(0)


def test_broker_day_start_is_shifted_by_the_offset(monkeypatch):
    fake = MagicMock()
    local = datetime.now()
    fake.symbol_info_tick.return_value = MagicMock(
        time=int((local + timedelta(hours=3)).timestamp()))
    monkeypatch.setattr(bridge, "mt5", fake)
    start = bridge.broker_day_start("GOLD.i#")
    local_midnight = datetime.combine(local.date(), datetime.min.time())
    shift = (start - local_midnight).total_seconds() / 3600
    assert 2.5 < shift < 3.5, f"day start shifted {shift}h, expected ~3h"
