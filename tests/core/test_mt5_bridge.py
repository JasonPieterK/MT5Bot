import types
import sys
from unittest.mock import MagicMock
import pytest


@pytest.fixture
def mt5_mock(monkeypatch):
    fake = MagicMock()
    fake.TIMEFRAME_M1 = 1
    fake.TIMEFRAME_M5 = 5
    fake.ORDER_TYPE_BUY = 0
    fake.ORDER_TYPE_SELL = 1
    fake.TRADE_ACTION_DEAL = 1
    fake.TRADE_RETCODE_DONE = 10009
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    import importlib
    import core.mt5_bridge as mt5_bridge
    importlib.reload(mt5_bridge)
    return mt5_bridge, fake


def test_connect_success(mt5_mock):
    bridge, fake = mt5_mock
    fake.initialize.return_value = True
    assert bridge.connect() is True


def test_connect_failure(mt5_mock):
    bridge, fake = mt5_mock
    fake.initialize.return_value = False
    fake.last_error.return_value = (1, "no terminal")
    assert bridge.connect() is False


def test_get_rates_returns_dataframe(mt5_mock):
    bridge, fake = mt5_mock
    fake.copy_rates_from_pos.return_value = [
        (1700000000, 1.1, 1.2, 1.05, 1.15, 100, 2, 0),
    ]
    df = bridge.get_rates("EURUSD", "M5", 50)
    assert list(df.columns) == ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
    assert len(df) == 1


def test_place_order_builds_correct_request(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.1050, bid=1.1048)
    result = types.SimpleNamespace(retcode=10009, order=123)
    fake.order_send.return_value = result
    ok, retcode = bridge.place_order("EURUSD", "BUY", 0.1, sl=1.1000, tp=1.1100, slippage_points=20)
    assert ok is True
    assert retcode == 10009
    sent = fake.order_send.call_args[0][0]
    assert sent["symbol"] == "EURUSD"
    assert sent["type"] == fake.ORDER_TYPE_BUY
    assert sent["volume"] == 0.1
    assert sent["sl"] == 1.1000
    assert sent["tp"] == 1.1100
    assert sent["price"] == 1.1050


def test_place_order_reports_failure(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.1050, bid=1.1048)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10004, order=None)
    ok, retcode = bridge.place_order("EURUSD", "BUY", 0.1, sl=1.1000, tp=1.1100, slippage_points=20)
    assert ok is False
    assert retcode == 10004


def test_get_open_positions(mt5_mock):
    bridge, fake = mt5_mock
    fake.positions_get.return_value = [
        types.SimpleNamespace(ticket=1, symbol="EURUSD", volume=0.1, profit=5.0, type=0, price_open=1.1, sl=1.09, tp=1.12),
    ]
    positions = bridge.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["ticket"] == 1
    assert positions[0]["profit"] == 5.0


def test_symbol_safety_check_rejects_below_min_stop(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = types.SimpleNamespace(trade_stops_level=50, point=0.0001, trade_freeze_level=0)
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.10500, bid=1.10480)
    ok, reason = bridge.check_stops_valid("EURUSD", sl=1.10495, tp=1.10600)
    assert ok is False
    assert "min stop" in reason.lower()


def test_get_current_price(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(bid=1.1048, ask=1.1050)
    bid, ask = bridge.get_current_price("EURUSD")
    assert bid == 1.1048
    assert ask == 1.1050


def test_modify_position_success(mt5_mock):
    bridge, fake = mt5_mock
    fake.TRADE_ACTION_SLTP = 6
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    ok, retcode = bridge.modify_position(12345, sl=1.0950, tp=1.1100)
    assert ok is True
    sent = fake.order_send.call_args[0][0]
    assert sent["position"] == 12345
    assert sent["sl"] == 1.0950
    assert sent["tp"] == 1.1100


def test_get_margin_level(mt5_mock):
    bridge, fake = mt5_mock
    fake.account_info.return_value = types.SimpleNamespace(margin_level=250.5)
    assert bridge.get_margin_level() == 250.5


def test_get_margin_level_zero_when_no_account(mt5_mock):
    bridge, fake = mt5_mock
    fake.account_info.return_value = None
    assert bridge.get_margin_level() == 0.0


def test_get_history_deals_filters_closing_deals(mt5_mock):
    bridge, fake = mt5_mock
    fake.DEAL_ENTRY_OUT = 1
    fake.history_deals_get.return_value = [
        types.SimpleNamespace(ticket=1, symbol="EURUSD", profit=10.0, time=1700000000, entry=0),
        types.SimpleNamespace(ticket=2, symbol="EURUSD", profit=-5.0, time=1700000100, entry=1),
    ]
    from datetime import datetime
    deals = bridge.get_history_deals(datetime(2024, 1, 1))
    assert len(deals) == 1
    assert deals[0]["profit"] == -5.0


def test_get_history_deals_empty_when_none(mt5_mock):
    bridge, fake = mt5_mock
    fake.history_deals_get.return_value = None
    from datetime import datetime
    assert bridge.get_history_deals(datetime(2024, 1, 1)) == []


def test_connect_with_account_params(mt5_mock):
    bridge, fake = mt5_mock
    fake.initialize.return_value = True
    assert bridge.connect(path="C:/MT5/terminal64.exe", login=12345, password="pw", server="Demo") is True
    fake.initialize.assert_called_once_with(
        path="C:/MT5/terminal64.exe", login=12345, password="pw", server="Demo")


def test_connect_no_params_calls_bare_initialize(mt5_mock):
    bridge, fake = mt5_mock
    fake.initialize.return_value = True
    bridge.connect()
    fake.initialize.assert_called_once_with()
