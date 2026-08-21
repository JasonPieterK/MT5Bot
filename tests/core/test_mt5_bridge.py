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
    fake.symbol_info.return_value = types.SimpleNamespace(digits=5)
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


def test_get_recent_ticks_returns_bid_prices(mt5_mock):
    bridge, fake = mt5_mock
    fake.COPY_TICKS_ALL = 1
    fake.copy_ticks_from.return_value = [
        {"bid": 1.1050}, {"bid": 1.1052}, {"bid": 1.1051},
    ]
    ticks = bridge.get_recent_ticks("EURUSD", count=3)
    assert ticks == [1.1050, 1.1052, 1.1051]


def test_get_recent_ticks_empty_when_none(mt5_mock):
    bridge, fake = mt5_mock
    fake.copy_ticks_from.return_value = None
    assert bridge.get_recent_ticks("EURUSD") == []


def test_get_symbol_volume_limits_returns_broker_values(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = types.SimpleNamespace(volume_min=0.01, volume_max=50.0, volume_step=0.01)
    min_lot, max_lot, step = bridge.get_symbol_volume_limits("EURUSD")
    assert min_lot == 0.01
    assert max_lot == 50.0
    assert step == 0.01


def test_get_symbol_volume_limits_falls_back_when_symbol_unknown(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = None
    min_lot, max_lot, step = bridge.get_symbol_volume_limits("BADSYMBOL")
    assert min_lot == 0.01
    assert max_lot == 100.0
    assert step == 0.01


def test_get_symbol_point(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = types.SimpleNamespace(point=0.00001)
    assert bridge.get_symbol_point("EURUSD") == 0.00001


def test_get_symbol_point_falls_back_when_symbol_unknown(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = None
    assert bridge.get_symbol_point("BADSYMBOL") == 0.0001


def test_close_position_by_ticket_success(mt5_mock):
    bridge, fake = mt5_mock
    fake.positions_get.return_value = [
        types.SimpleNamespace(ticket=555, symbol="EURUSD", volume=0.2, type=0),
    ]
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.1050, bid=1.1048)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    ok, retcode = bridge.close_position_by_ticket(555, slippage_points=20)
    assert ok is True
    assert retcode == 10009


def test_close_position_by_ticket_not_found(mt5_mock):
    bridge, fake = mt5_mock
    fake.positions_get.return_value = []
    ok, reason = bridge.close_position_by_ticket(999, slippage_points=20)
    assert ok is False
    assert reason == "position not found"


# ---------- trade-disabled preflight diagnostic (retcode 10017 and friends) ----------

def _diag_ok(fake):
    """All-clear MT5: terminal connected and algo-enabled, account tradeable, symbol live."""
    fake.SYMBOL_TRADE_MODE_DISABLED = 0
    fake.SYMBOL_TRADE_MODE_LONGONLY = 1
    fake.SYMBOL_TRADE_MODE_SHORTONLY = 2
    fake.SYMBOL_TRADE_MODE_CLOSEONLY = 3
    fake.SYMBOL_TRADE_MODE_FULL = 4
    fake.ACCOUNT_TRADE_MODE_DEMO = 0
    fake.ACCOUNT_TRADE_MODE_CONTEST = 1
    fake.ACCOUNT_TRADE_MODE_REAL = 2
    fake.terminal_info.return_value = types.SimpleNamespace(trade_allowed=True, connected=True)
    fake.account_info.return_value = types.SimpleNamespace(
        trade_allowed=True, trade_mode=0, margin_free=10000.0, login=123, server="Broker-Demo")
    fake.symbol_info.return_value = types.SimpleNamespace(
        name="EURUSD", visible=True, trade_mode=4, point=0.00001)
    import time as _time
    fake.symbol_info_tick.return_value = types.SimpleNamespace(
        bid=1.1, ask=1.1002, time=int(_time.time()))
    return fake


def test_diagnose_trading_all_clear_returns_no_findings(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    assert bridge.diagnose_trading("EURUSD") == []


def test_diagnose_trading_flags_algo_trading_off_in_terminal(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.terminal_info.return_value = types.SimpleNamespace(trade_allowed=False, connected=True)
    findings = bridge.diagnose_trading("EURUSD")
    assert any("Algo Trading" in f["problem"] for f in findings)


def test_diagnose_trading_flags_terminal_not_running(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.terminal_info.return_value = None
    findings = bridge.diagnose_trading("EURUSD")
    assert len(findings) == 1
    assert "terminal" in findings[0]["problem"].lower()


def test_diagnose_trading_flags_account_trading_disabled(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.account_info.return_value = types.SimpleNamespace(
        trade_allowed=False, trade_mode=2, margin_free=500.0, login=1, server="Broker-Live")
    findings = bridge.diagnose_trading("EURUSD")
    assert any("investor" in f["fix"].lower() for f in findings)


def test_diagnose_trading_suggests_close_symbol_names_when_symbol_unknown(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.symbol_info.return_value = None
    fake.symbols_get.return_value = [
        types.SimpleNamespace(name="XAUUSD.m"),
        types.SimpleNamespace(name="XAUEUR"),
        types.SimpleNamespace(name="EURUSD"),
    ]
    findings = bridge.diagnose_trading("XAUUSD")
    assert len(findings) == 1
    assert "XAUUSD.m" in findings[0]["fix"]


def test_diagnose_trading_flags_symbol_trading_disabled_by_broker(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.symbol_info.return_value = types.SimpleNamespace(
        name="EURUSD", visible=True, trade_mode=0, point=0.00001)
    findings = bridge.diagnose_trading("EURUSD")
    assert any("disabled trading on" in f["problem"] for f in findings)


def test_diagnose_trading_selects_a_symbol_that_is_not_in_market_watch(mt5_mock):
    # Not being in Market Watch is fixable without bothering the user, so resolve_symbol
    # selects it rather than reporting it as a problem.
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.symbol_info.return_value = types.SimpleNamespace(
        name="EURUSD", visible=False, trade_mode=4, point=0.00001)
    assert bridge.diagnose_trading("EURUSD") == []
    fake.symbol_select.assert_called_with("EURUSD", True)


def test_diagnose_trading_flags_close_only_symbol(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.symbol_info.return_value = types.SimpleNamespace(
        name="EURUSD", visible=True, trade_mode=3, point=0.00001)
    findings = bridge.diagnose_trading("EURUSD")
    assert any("close" in f["problem"].lower() for f in findings)


def test_diagnose_trading_flags_stale_quotes_as_market_closed(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    import time as _time
    fake.symbol_info_tick.return_value = types.SimpleNamespace(
        bid=1.1, ask=1.1, time=int(_time.time()) - 7200)
    findings = bridge.diagnose_trading("EURUSD")
    assert any("closed" in f["problem"].lower() for f in findings)


def test_get_account_summary(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    summary = bridge.get_account_summary()
    assert summary["trade_mode"] == "demo"
    assert summary["margin_free"] == 10000.0
    assert summary["trade_allowed"] is True


# ---------- C1: a close must reference the position it is closing ----------

def test_close_position_sends_the_position_ticket(mt5_mock):
    # Without "position" in the request, a close on a HEDGING account opens a brand-new
    # opposite position instead of closing anything -- doubling exposure during a flatten.
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.1050, bid=1.1048)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    ok, retcode = bridge.close_position(777, "EURUSD", 0.2, "BUY", slippage_points=20)
    assert ok is True
    sent = fake.order_send.call_args[0][0]
    assert sent["position"] == 777
    assert sent["type"] == fake.ORDER_TYPE_SELL  # opposite side of the BUY being closed
    assert sent["volume"] == 0.2


def test_place_order_does_not_send_a_position_field_for_a_new_trade(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.1050, bid=1.1048)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    bridge.place_order("EURUSD", "BUY", 0.1, sl=None, tp=None, slippage_points=20)
    assert "position" not in fake.order_send.call_args[0][0]


# ---------- H2: every timeframe the app can produce must be mappable ----------

def test_timeframe_map_covers_every_timeframe_config_can_produce(mt5_mock):
    bridge, _fake = mt5_mock
    import core.config as config
    used = {s["timeframe"] for s in config.DEFAULT_SETTINGS.values()}
    used.add(config.GLOBAL_SETTINGS["htf_timeframe"])
    used.add(config.DEFAULT_SETTINGS["smc"]["htf_timeframe"])
    used.add(config.new_state()["timeframe"])
    missing = used - set(bridge.TIMEFRAME_MAP)
    assert missing == set(), f"get_rates would raise KeyError on: {missing}"


def test_timeframe_map_includes_every_timeframe_the_ui_offers(mt5_mock):
    bridge, _fake = mt5_mock
    assert {"M1", "M5", "M15", "M30", "H1", "H4", "D1"} <= set(bridge.TIMEFRAME_MAP)


# ---------- H5: MT5 returning None must not become an opaque AttributeError ----------

def test_place_order_handles_order_send_returning_none(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.1050, bid=1.1048)
    fake.order_send.return_value = None
    fake.last_error.return_value = (-10004, "no connection")
    ok, reason = bridge.place_order("EURUSD", "BUY", 0.1, sl=None, tp=None, slippage_points=20)
    assert ok is False
    assert "no response" in str(reason)


def test_place_order_handles_unknown_symbol(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = None
    ok, reason = bridge.place_order("XAUUSD.m", "BUY", 0.1, sl=None, tp=None, slippage_points=20)
    assert ok is False
    assert "XAUUSD.m" in str(reason)
    fake.order_send.assert_not_called()


def test_modify_position_handles_order_send_returning_none(mt5_mock):
    bridge, fake = mt5_mock
    fake.TRADE_ACTION_SLTP = 6
    fake.order_send.return_value = None
    fake.last_error.return_value = (-10004, "no connection")
    ok, reason = bridge.modify_position(1, 1.09, 1.11)
    assert ok is False
    assert "no response" in str(reason)


def test_check_stops_valid_handles_unknown_symbol(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = None
    fake.symbol_info_tick.return_value = None
    ok, reason = bridge.check_stops_valid("NOPE", sl=1.0, tp=2.0)
    assert ok is False
    assert "NOPE" in reason


def test_get_current_price_returns_none_pair_for_unknown_symbol(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = None
    assert bridge.get_current_price("NOPE") == (None, None)


# ---------- C3/C4 support wrappers ----------

def test_get_symbol_tick_economics_returns_broker_values(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = types.SimpleNamespace(trade_tick_value=1.0, trade_tick_size=0.01)
    assert bridge.get_symbol_tick_economics("XAUUSD") == (1.0, 0.01)


def test_get_symbol_tick_economics_falls_back_when_symbol_unknown(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = None
    tick_value, tick_size = bridge.get_symbol_tick_economics("BADSYMBOL")
    assert tick_value > 0 and tick_size > 0


def test_get_symbol_tick_economics_falls_back_on_zero_values(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = types.SimpleNamespace(trade_tick_value=0.0, trade_tick_size=0.0)
    tick_value, tick_size = bridge.get_symbol_tick_economics("WEIRD")
    assert tick_value > 0 and tick_size > 0


def test_get_required_margin_uses_order_calc_margin(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.1050, bid=1.1048)
    fake.order_calc_margin.return_value = 3300.0
    assert bridge.get_required_margin("EURUSD", "BUY", 1.0) == 3300.0
    args = fake.order_calc_margin.call_args[0]
    assert args[1] == "EURUSD"
    assert args[2] == 1.0


def test_get_required_margin_none_when_symbol_unknown(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = None
    assert bridge.get_required_margin("NOPE", "BUY", 1.0) is None


def test_get_free_margin(mt5_mock):
    bridge, fake = mt5_mock
    fake.account_info.return_value = types.SimpleNamespace(margin_free=54321.0)
    assert bridge.get_free_margin() == 54321.0


def test_get_free_margin_zero_when_no_account(mt5_mock):
    bridge, fake = mt5_mock
    fake.account_info.return_value = None
    assert bridge.get_free_margin() == 0.0


# ---------- filling modes: the actual cause of the 10017 rejection loop ----------

def _fill_fake(fake):
    fake.ORDER_FILLING_IOC = 1
    fake.ORDER_FILLING_RETURN = 2
    fake.ORDER_FILLING_FOK = 3
    fake.TRADE_ACTION_SLTP = 6
    fake.TRADE_ACTION_MODIFY = 7
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.1050, bid=1.1048)
    return fake


def test_order_retries_next_fill_mode_when_broker_rejects_the_first(mt5_mock):
    bridge, fake = mt5_mock
    _fill_fake(fake)
    bridge._fill_mode_cache.clear()
    fake.order_send.side_effect = [
        types.SimpleNamespace(retcode=10030, order=None),  # broker refuses IOC
        types.SimpleNamespace(retcode=10009, order=1),     # accepts RETURN
    ]
    ok, retcode = bridge.place_order("EURUSD", "BUY", 0.1, sl=None, tp=None, slippage_points=20)
    assert ok is True
    assert retcode == 10009
    assert fake.order_send.call_count == 2
    assert fake.order_send.call_args_list[0][0][0]["type_filling"] == fake.ORDER_FILLING_IOC
    assert fake.order_send.call_args_list[1][0][0]["type_filling"] == fake.ORDER_FILLING_RETURN


def test_a_10017_rejection_also_retries_the_next_fill_mode(mt5_mock):
    # Some broker builds report a refused fill type as 10017 (trade disabled) rather than
    # the documented 10030 -- which is what made this look like an environment problem.
    bridge, fake = mt5_mock
    _fill_fake(fake)
    bridge._fill_mode_cache.clear()
    fake.order_send.side_effect = [
        types.SimpleNamespace(retcode=10017, order=None),
        types.SimpleNamespace(retcode=10017, order=None),
        types.SimpleNamespace(retcode=10009, order=1),
    ]
    ok, retcode = bridge.place_order("XAUUSD", "BUY", 0.1, sl=None, tp=None, slippage_points=20)
    assert ok is True
    assert fake.order_send.call_count == 3


def test_winning_fill_mode_is_cached_so_repeat_orders_send_once(mt5_mock):
    bridge, fake = mt5_mock
    _fill_fake(fake)
    bridge._fill_mode_cache.clear()
    fake.order_send.side_effect = [
        types.SimpleNamespace(retcode=10030, order=None),
        types.SimpleNamespace(retcode=10009, order=1),
    ]
    bridge.place_order("EURUSD", "BUY", 0.1, sl=None, tp=None, slippage_points=20)
    assert bridge._fill_mode_cache["EURUSD"] == fake.ORDER_FILLING_RETURN

    fake.order_send.side_effect = None
    fake.order_send.reset_mock()
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=2)
    bridge.place_order("EURUSD", "BUY", 0.1, sl=None, tp=None, slippage_points=20)
    assert fake.order_send.call_count == 1
    assert fake.order_send.call_args[0][0]["type_filling"] == fake.ORDER_FILLING_RETURN


def test_non_fill_rejection_is_not_retried_across_fill_modes(mt5_mock):
    bridge, fake = mt5_mock
    _fill_fake(fake)
    bridge._fill_mode_cache.clear()
    fake.order_send.return_value = types.SimpleNamespace(retcode=10016, order=None)  # bad stops
    ok, retcode = bridge.place_order("EURUSD", "BUY", 0.1, sl=1.1, tp=1.2, slippage_points=20)
    assert ok is False
    assert retcode == 10016
    assert fake.order_send.call_count == 1


def test_all_fill_modes_rejected_reports_the_last_retcode(mt5_mock):
    bridge, fake = mt5_mock
    _fill_fake(fake)
    bridge._fill_mode_cache.clear()
    fake.order_send.return_value = types.SimpleNamespace(retcode=10030, order=None)
    ok, retcode = bridge.place_order("EURUSD", "BUY", 0.1, sl=None, tp=None, slippage_points=20)
    assert ok is False
    assert retcode == 10030
    assert fake.order_send.call_count == 3


def test_modify_position_never_sends_a_filling_mode(mt5_mock):
    # Injecting type_filling into an SLTP request makes some broker builds return None
    # instead of a result object, which surfaces as an opaque failure.
    bridge, fake = mt5_mock
    _fill_fake(fake)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    bridge.modify_position(1, 1.09, 1.12)
    assert "type_filling" not in fake.order_send.call_args[0][0]
    assert fake.order_send.call_count == 1


def test_resolve_symbol_returns_visible_symbol_untouched(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = types.SimpleNamespace(name="EURUSD", visible=True)
    name, err = bridge.resolve_symbol("EURUSD")
    assert (name, err) == ("EURUSD", None)
    fake.symbol_select.assert_not_called()  # already streaming; no slow re-sync


def test_resolve_symbol_selects_a_symbol_not_yet_in_market_watch(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = types.SimpleNamespace(name="XAUUSD", visible=False)
    name, err = bridge.resolve_symbol("XAUUSD")
    assert (name, err) == ("XAUUSD", None)
    fake.symbol_select.assert_called_with("XAUUSD", True)


def test_resolve_symbol_finds_broker_suffix_variant(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = None
    fake.symbol_select.return_value = False
    fake.symbols_get.return_value = [
        types.SimpleNamespace(name="EURUSD.m"), types.SimpleNamespace(name="XAUUSD.m"),
    ]
    name, err = bridge.resolve_symbol("xau usd")
    assert name == "XAUUSD.m"
    assert err is None
    fake.symbol_select.assert_called_with("XAUUSD.m", True)


def test_resolve_symbol_suggests_near_matches_when_ambiguous(mt5_mock):
    # Two plausible instruments -- guessing could trade the wrong one, so the user picks.
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = None
    fake.symbol_select.return_value = False
    fake.symbols_get.return_value = [
        types.SimpleNamespace(name="XAUUSD.pro"), types.SimpleNamespace(name="XAUUSD.raw"),
        types.SimpleNamespace(name="EURUSD"),
    ]
    name, err = bridge.resolve_symbol("XAUUSD")
    assert name is None
    assert "XAUUSD.pro" in err and "XAUUSD.raw" in err


def test_resolve_symbol_reports_a_symbol_that_does_not_exist_at_all(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info.return_value = None
    fake.symbol_select.return_value = False
    fake.symbols_get.return_value = [types.SimpleNamespace(name="EURUSD")]
    name, err = bridge.resolve_symbol("NOTATHING")
    assert name is None
    assert "does not exist" in err


def test_resolve_symbol_rejects_blank_input(mt5_mock):
    bridge, _fake = mt5_mock
    assert bridge.resolve_symbol("   ")[0] is None


def test_is_connected_uses_the_cheap_terminal_check(mt5_mock):
    bridge, fake = mt5_mock
    fake.terminal_info.return_value = types.SimpleNamespace(connected=True)
    assert bridge.is_connected() is True
    fake.initialize.assert_not_called()


def test_is_connected_false_when_terminal_absent(mt5_mock):
    bridge, fake = mt5_mock
    fake.terminal_info.return_value = None
    assert bridge.is_connected() is False


def _sym(name, trade_mode=4, visible=True):
    return types.SimpleNamespace(name=name, trade_mode=trade_mode, visible=visible)


def test_resolve_symbol_skips_an_exact_match_the_broker_has_disabled(mt5_mock):
    """XM lists both 'EURUSD' (trade disabled) and 'EURUSD#' (tradeable). Taking the exact
    name sent every order to the disabled one and the broker answered 10017."""
    bridge, fake = mt5_mock
    fake.SYMBOL_TRADE_MODE_FULL = 4
    fake.symbol_info.side_effect = lambda n: {
        "EURUSD": _sym("EURUSD", trade_mode=0),
        "EURUSD#": _sym("EURUSD#", trade_mode=4),
    }.get(n)
    fake.symbols_get.return_value = [_sym("EURUSD", trade_mode=0), _sym("EURUSD#", trade_mode=4)]
    resolved, err = bridge.resolve_symbol("EURUSD")
    assert err is None
    assert resolved == "EURUSD#"


def test_resolve_symbol_keeps_a_tradeable_exact_match(mt5_mock):
    bridge, fake = mt5_mock
    fake.SYMBOL_TRADE_MODE_FULL = 4
    fake.symbol_info.side_effect = lambda n: _sym("EURUSD") if n == "EURUSD" else None
    fake.symbols_get.return_value = [_sym("EURUSD")]
    assert bridge.resolve_symbol("EURUSD") == ("EURUSD", None)


def test_resolve_symbol_reports_when_every_variant_is_disabled(mt5_mock):
    bridge, fake = mt5_mock
    fake.SYMBOL_TRADE_MODE_FULL = 4
    fake.symbol_info.side_effect = lambda n: _sym("EURUSD", trade_mode=0) if n == "EURUSD" else None
    fake.symbols_get.return_value = [_sym("EURUSD", trade_mode=0)]
    resolved, err = bridge.resolve_symbol("EURUSD")
    assert resolved is None
    assert "disabled" in err.lower()


def test_get_rates_retries_while_the_terminal_warms_up(mt5_mock):
    # copy_rates_from_pos returns 0 bars on the first call after symbol_select while MT5
    # pulls history. Treating that as "no signal" is how a symbol silently never trades.
    bridge, fake = mt5_mock
    fake.copy_rates_from_pos.side_effect = [
        [], None, [(1700000000, 1.1, 1.2, 1.05, 1.15, 100, 2, 0)],
    ]
    df = bridge.get_rates("EURUSD", "M5", 10, _sleep=lambda _s: None)
    assert len(df) == 1
    assert fake.copy_rates_from_pos.call_count == 3


def test_get_rates_gives_up_with_an_empty_frame_not_an_exception(mt5_mock):
    bridge, fake = mt5_mock
    fake.copy_rates_from_pos.return_value = None
    df = bridge.get_rates("EURUSD", "M5", 10, _sleep=lambda _s: None)
    assert len(df) == 0
    assert list(df.columns) == bridge.RATES_COLUMNS


def test_list_tradeable_symbols_excludes_untradeable_ones(mt5_mock):
    """The dashboard's symbol suggestions come from here. Offering a name the broker will
    not trade is what sent every order to the disabled 'EURUSD' in the first place."""
    bridge, fake = mt5_mock
    fake.SYMBOL_TRADE_MODE_FULL = 4
    fake.symbols_get.return_value = [
        _sym("EURUSD", trade_mode=0),
        _sym("EURUSD#", trade_mode=4),
        _sym("GOLD.i#", trade_mode=4),
    ]
    names = bridge.list_tradeable_symbols()
    assert "EURUSD#" in names and "GOLD.i#" in names
    assert "EURUSD" not in names


def test_list_tradeable_symbols_prefers_symbols_already_in_market_watch(mt5_mock):
    bridge, fake = mt5_mock
    fake.SYMBOL_TRADE_MODE_FULL = 4
    fake.symbols_get.return_value = [
        _sym("ZZZ#", trade_mode=4, visible=False),
        _sym("EURUSD#", trade_mode=4, visible=True),
    ]
    assert bridge.list_tradeable_symbols()[0] == "EURUSD#"


def test_list_tradeable_symbols_empty_when_terminal_has_none(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbols_get.return_value = None
    assert bridge.list_tradeable_symbols() == []


# ---------- finding severity: not everything the diagnostic reports is a blocker ----------

def test_an_auto_resolved_symbol_rename_is_informational_not_blocking(mt5_mock):
    """resolve_symbol already mapped the name and the engine trades the resolved one, so
    calling this "TRADING BLOCKED" contradicted the INFO line printed one line earlier."""
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.symbol_info.side_effect = lambda name: None if name == "EURUSD" else types.SimpleNamespace(
        name="EURUSD#", visible=True, trade_mode=4, point=0.00001)
    fake.symbols_get.return_value = [types.SimpleNamespace(name="EURUSD#")]
    findings = bridge.diagnose_trading("EURUSD")
    rename = [f for f in findings if "EURUSD#" in f["problem"]]
    assert rename, findings
    assert rename[0]["severity"] == bridge.INFO
    assert bridge.is_blocking(rename[0]) is False
    assert "nothing is blocked" in rename[0]["problem"].lower()


def test_algo_trading_off_stays_a_blocking_finding(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.terminal_info.return_value = types.SimpleNamespace(trade_allowed=False, connected=True)
    finding = [f for f in bridge.diagnose_trading("EURUSD") if "Algo Trading" in f["problem"]][0]
    assert finding["severity"] == bridge.BLOCKING
    assert bridge.is_blocking(finding) is True


def test_a_symbol_the_broker_refuses_to_trade_stays_blocking(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.symbol_info.return_value = types.SimpleNamespace(
        name="EURUSD", visible=True, trade_mode=3, point=0.00001)   # close-only
    fake.symbols_get.return_value = []
    findings = bridge.diagnose_trading("EURUSD")
    assert all(bridge.is_blocking(f) for f in findings)


def test_every_finding_carries_a_severity(mt5_mock):
    bridge, fake = mt5_mock
    _diag_ok(fake)
    fake.terminal_info.return_value = None
    for finding in bridge.diagnose_trading("EURUSD"):
        assert finding["severity"] in (bridge.BLOCKING, bridge.WARNING, bridge.INFO)


def test_is_blocking_defaults_to_blocking_for_a_finding_without_a_severity(mt5_mock):
    bridge, _fake = mt5_mock
    assert bridge.is_blocking({"problem": "x", "fix": "y"}) is True


def test_place_order_rounds_prices_to_the_symbols_digits(mt5_mock):
    """A stop carrying more decimals than the symbol allows is rejected by MT5 -- or worse,
    the broker fills the deal and silently drops the stop, leaving a naked position. Real
    case: sl=4411.716466763122 sent to GOLD.i#, which has digits=2."""
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=4393.71, bid=4393.55)
    fake.symbol_info.return_value = types.SimpleNamespace(digits=2, volume_min=0.01,
                                                          volume_max=50.0, volume_step=0.01)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    bridge.place_order("GOLD.i#", "BUY", 1.0, sl=4411.716466763122, tp=4354.419222061462,
                        slippage_points=20)
    sent = fake.order_send.call_args[0][0]
    assert sent["sl"] == 4411.72
    assert sent["tp"] == 4354.42
    assert sent["price"] == 4393.71


def test_place_order_rounds_five_digit_fx_prices(mt5_mock):
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.15771, bid=1.15769)
    fake.symbol_info.return_value = types.SimpleNamespace(digits=5, volume_min=0.01,
                                                          volume_max=50.0, volume_step=0.01)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    bridge.place_order("EURUSD#", "SELL", 1.0, sl=1.159106954832093, tp=1.156021741946512,
                        slippage_points=20)
    sent = fake.order_send.call_args[0][0]
    assert sent["sl"] == 1.15911
    assert sent["tp"] == 1.15602


def test_place_order_sends_absent_stops_as_zero(mt5_mock):
    """This test used to assert None stayed None, on the theory that 0.0 would read as
    "remove the stop". That was wrong and it hid a real failure: MT5's API spells "no stop"
    as 0.0, and a None gets the whole request refused with `Invalid "sl" argument` -- the
    order never reached the broker at all. See tests/core/test_no_stop_order_shape.py."""
    bridge, fake = mt5_mock
    fake.symbol_info_tick.return_value = types.SimpleNamespace(ask=1.1, bid=1.09)
    fake.symbol_info.return_value = types.SimpleNamespace(digits=5, volume_min=0.01,
                                                          volume_max=50.0, volume_step=0.01)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    bridge.place_order("EURUSD#", "BUY", 1.0, sl=None, tp=None, slippage_points=20)
    sent = fake.order_send.call_args[0][0]
    assert sent["sl"] == 0.0 and sent["tp"] == 0.0


def test_modify_position_rounds_to_symbol_digits(mt5_mock):
    bridge, fake = mt5_mock
    fake.TRADE_ACTION_SLTP = 6
    fake.positions_get.return_value = [
        types.SimpleNamespace(ticket=5, symbol="GOLD.i#", volume=1.0, profit=0.0, type=0,
                               price_open=4393.71, sl=0.0, tp=0.0)]
    fake.symbol_info.return_value = types.SimpleNamespace(digits=2)
    fake.order_send.return_value = types.SimpleNamespace(retcode=10009, order=1)
    bridge.modify_position(5, sl=4411.716466763122, tp=4354.419222061462)
    sent = fake.order_send.call_args[0][0]
    assert sent["sl"] == 4411.72
    assert sent["tp"] == 4354.42
