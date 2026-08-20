import pandas as pd
from unittest.mock import MagicMock
import core.engine as engine
import pytest


def make_uptrend_rates():
    price = 1.10
    closes = []
    for i in range(40):
        price += 0.0008 if i % 2 == 0 else -0.0006
        closes.append(price)
    return pd.DataFrame({
        "open": closes, "high": [c + 0.0005 for c in closes],
        "low": [c - 0.0005 for c in closes], "close": closes, "spread": [5] * 40,
    })


def make_bridge():
    """A MagicMock bridge with realistic returns for every wrapper the order path now
    consults. Spec-less MagicMocks silently satisfy tuple-returning calls with garbage, so
    each of these has to be pinned to something a real broker would send."""
    bridge = MagicMock()
    bridge.check_stops_valid.return_value = (True, "")
    bridge.resolve_symbol.side_effect = lambda name: (name, None)
    bridge.get_symbol_volume_limits.return_value = (0.01, 100.0, 0.01)
    bridge.get_symbol_tick_economics.return_value = (1.0, 0.00001)  # 5-digit EURUSD
    bridge.get_symbol_point.return_value = 0.0001
    bridge.get_required_margin.return_value = 100.0
    bridge.get_free_margin.return_value = 1_000_000.0
    bridge.get_margin_level.return_value = 500.0
    bridge.place_order.return_value = (True, 10009)
    bridge.modify_position.return_value = (True, 10009)
    bridge.close_position.return_value = (True, 10009)
    return bridge


def test_run_once_places_order_when_signal_and_risk_allow(monkeypatch):
    bridge = make_bridge()
    bridge.get_rates.return_value = make_uptrend_rates()
    bridge.get_open_positions.return_value = []
    bridge.get_account_equity.return_value = 10000
    bridge.check_stops_valid.return_value = (True, "")
    bridge.place_order.return_value = (True, 10009)
    bridge.get_symbol_volume_limits.return_value = (0.01, 100.0, 0.01)
    bridge.get_margin_level.return_value = 500.0

    state = {"active_strategy": "trend", "symbol": "EURUSD", "timeframe": "M5"}
    strategy_settings = {"trend": {
        "ma_type": "EMA", "fast_period": 9, "slow_period": 21,
        "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35,
    }}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20}

    engine.run_once(bridge, state, strategy_settings, global_settings,
                     daily_pnl_percent=0.0, drawdown_percent=0.0)

    assert bridge.place_order.called


def test_run_once_skips_when_risk_manager_blocks(monkeypatch):
    bridge = make_bridge()
    bridge.get_rates.return_value = make_uptrend_rates()
    bridge.get_open_positions.return_value = [1, 2, 3]
    bridge.get_account_equity.return_value = 10000
    bridge.get_margin_level.return_value = 500.0

    state = {"active_strategy": "trend", "symbol": "EURUSD", "timeframe": "M5"}
    strategy_settings = {"trend": {
        "ma_type": "EMA", "fast_period": 9, "slow_period": 21,
        "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35,
    }}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20}

    engine.run_once(bridge, state, strategy_settings, global_settings,
                     daily_pnl_percent=0.0, drawdown_percent=0.0)

    assert not bridge.place_order.called


def test_run_once_flattens_on_max_drawdown(monkeypatch):
    bridge = make_bridge()
    bridge.get_open_positions.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "type": "BUY"}
    ]
    state = {"active_strategy": "trend", "symbol": "EURUSD", "timeframe": "M5"}
    strategy_settings = {"trend": {}}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20}

    engine.run_once(bridge, state, strategy_settings, global_settings,
                     daily_pnl_percent=0.0, drawdown_percent=20.0)

    assert bridge.close_position.called


def test_manage_positions_applies_trailing_when_enabled():
    bridge = make_bridge()
    bridge.get_open_positions.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "type": "BUY",
         "price_open": 1.1000, "sl": 1.0950, "tp": 1.1200},
    ]
    bridge.get_current_price.return_value = (1.1100, 1.1102)
    global_settings = {"trailing_enabled": True, "trailing_distance_points": 100,
                        "breakeven_enabled": False, "breakeven_trigger_points": 100,
                        "breakeven_offset_points": 10}

    engine._manage_positions(bridge, global_settings)

    assert bridge.modify_position.called


def test_run_once_ensemble_strategy_places_order_on_agreement(monkeypatch):
    bridge = make_bridge()
    bridge.get_rates.return_value = make_uptrend_rates()
    bridge.get_open_positions.return_value = []
    bridge.get_account_equity.return_value = 10000
    bridge.get_margin_level.return_value = 500.0
    bridge.place_order.return_value = (True, 10009)
    bridge.get_symbol_volume_limits.return_value = (0.01, 100.0, 0.01)

    import core.ensemble as ensemble
    # SL/TP have to be a shape a real strategy could emit: the order path now rejects a
    # stop many ATRs away and a reward:risk below the configured floor.
    last = bridge.get_rates.return_value["close"].iloc[-1]
    monkeypatch.setattr(engine.ensemble, "get_ensemble_signal",
                         lambda rates, settings, min_agree=2: ("BUY", last - 0.0010,
                                                               last + 0.0020, ["trend", "scalping"]))

    state = {"active_strategy": "ensemble", "symbol": "EURUSD", "timeframe": "M5"}
    strategy_settings = {"trend": {}, "scalping": {}, "smc": {}, "pivot_breakout": {}}
    global_settings = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                        "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                        "slippage_points": 20, "margin_alert_level_percent": 100.0}

    engine.run_once(bridge, state, strategy_settings, global_settings,
                     daily_pnl_percent=0.0, drawdown_percent=0.0)

    assert bridge.place_order.called


# ---------- automatic diagnosis on trade-disabled rejections ----------

def test_trade_disabled_rejection_triggers_diagnosis(tmp_path, monkeypatch):
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    engine._last_diagnosis_at = 0.0
    bridge = make_bridge()
    bridge.place_order.return_value = (False, 10017)
    bridge.diagnose_trading.return_value = [
        {"problem": "The broker has disabled trading on 'XAUUSD'.", "fix": "Pick another symbol."},
    ]
    engine._place_order_logged(bridge, "XAUUSD", "BUY", 0.1, 2400.0, 2450.0, 20, "trend", {})
    bridge.diagnose_trading.assert_called_once_with("XAUUSD")
    assert "disabled trading on 'XAUUSD'" in "\n".join(app_logger.tail())


def test_diagnosis_is_rate_limited_so_a_repeating_rejection_does_not_spam_the_log():
    engine._last_diagnosis_at = 0.0
    bridge = make_bridge()
    bridge.place_order.return_value = (False, 10017)
    bridge.diagnose_trading.return_value = []
    for _ in range(5):
        engine._place_order_logged(bridge, "EURUSD", "BUY", 0.1, 1.09, 1.11, 20, "trend", {})
    assert bridge.diagnose_trading.call_count == 1


def test_successful_order_never_triggers_diagnosis():
    engine._last_diagnosis_at = 0.0
    bridge = make_bridge()
    bridge.place_order.return_value = (True, 10009)
    engine._place_order_logged(bridge, "EURUSD", "BUY", 0.1, 1.09, 1.11, 20, "trend", {})
    bridge.diagnose_trading.assert_not_called()


def test_non_trade_disabled_rejection_does_not_trigger_diagnosis():
    engine._last_diagnosis_at = 0.0
    bridge = make_bridge()
    bridge.place_order.return_value = (False, 10016)  # invalid stops, not trade-disabled
    engine._place_order_logged(bridge, "EURUSD", "BUY", 0.1, 1.09, 1.11, 20, "trend", {})
    bridge.diagnose_trading.assert_not_called()


# =====================================================================
# Order-path gates. These assert WHAT gets sent, not merely THAT something was.
# =====================================================================

TREND_SETTINGS = {"trend": {"ma_type": "EMA", "fast_period": 9, "slow_period": 21,
                            "rsi_period": 14, "rsi_buy_below": 65, "rsi_sell_above": 35}}
BASE_GLOBALS = {"risk_percent": 1.0, "max_concurrent_trades": 3,
                "daily_loss_limit_percent": 5.0, "max_drawdown_percent": 15.0,
                "slippage_points": 20, "margin_alert_level_percent": 100.0}


def make_uptrend_rates_with_time(bar_time=1_700_000_000):
    rates = make_uptrend_rates()
    # The timestamp of the last bar is what the one-order-per-bar gate keys on.
    rates["time"] = [bar_time - (len(rates) - 1 - i) * 300 for i in range(len(rates))]
    return rates


def entry_bridge(rates=None):
    bridge = make_bridge()
    bridge.get_rates.return_value = rates if rates is not None else make_uptrend_rates_with_time()
    bridge.get_open_positions.return_value = []
    bridge.get_account_equity.return_value = 10000
    return bridge


def single_state(strategy="trend", symbol="EURUSD"):
    return {"active_strategy": strategy, "symbol": symbol, "timeframe": "M5"}


def run(bridge, state=None, settings=None, globals_=None, dd=0.0, daily=0.0):
    engine.run_once(bridge, state or single_state(), settings or TREND_SETTINGS,
                     globals_ or BASE_GLOBALS, daily_pnl_percent=daily, drawdown_percent=dd)


# ---------- C3: the order carries a correctly sized lot ----------

def test_run_once_sends_lots_sized_from_broker_tick_economics():
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_account_equity.return_value = 100_000
    bridge.get_symbol_tick_economics.return_value = (1.0, 0.00001)  # 5-digit EURUSD
    run(bridge)
    args, kwargs = bridge.place_order.call_args
    assert args[0] == "EURUSD"
    assert args[1] == "BUY"
    # Risking 1% of 100k = $1,000 over the strategy's own SL distance.
    entry = bridge.get_rates.return_value["close"].iloc[-1]
    risked = args[2] * (abs(entry - kwargs["sl"]) / 0.00001) * 1.0
    assert abs(risked - 1000) < 20


def test_run_once_sizes_gold_from_gold_tick_economics():
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_account_equity.return_value = 100_000
    bridge.get_symbol_tick_economics.return_value = (1.0, 0.01)  # XAUUSD-like
    # High max_lot so the broker clamp isn't what decides the size -- the point of this
    # test is that the tick economics do.
    bridge.get_symbol_volume_limits.return_value = (0.01, 100_000.0, 0.01)
    run(bridge, state=single_state(symbol="XAUUSD"))
    args, kwargs = bridge.place_order.call_args
    entry = bridge.get_rates.return_value["close"].iloc[-1]
    risked = args[2] * (abs(entry - kwargs["sl"]) / 0.01) * 1.0
    assert abs(risked - 1000) < 20


# ---------- C5: stop distance is validated before sending ----------

def test_run_once_does_not_send_an_order_the_broker_will_reject_for_stops(tmp_path, monkeypatch):
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.check_stops_valid.return_value = (False, "sl too close to price: min stop distance is 0.003")
    run(bridge)
    bridge.place_order.assert_not_called()
    assert "min stop distance" in "\n".join(app_logger.tail())


# ---------- C6: one order per closed bar ----------

def test_same_signal_on_the_same_bar_places_only_one_order():
    # The engine ticks every 5s; an M15 crossover stays true for ~180 ticks.
    engine.reset_bar_gate()
    bridge = entry_bridge()
    run(bridge)
    run(bridge)
    run(bridge)
    assert bridge.place_order.call_count == 1


def test_a_new_bar_re_arms_the_signal():
    engine.reset_bar_gate()
    bridge = entry_bridge()
    run(bridge)
    bridge.get_rates.return_value = make_uptrend_rates_with_time(bar_time=1_700_000_900)
    run(bridge)
    assert bridge.place_order.call_count == 2


def test_bar_gate_is_per_symbol():
    engine.reset_bar_gate()
    bridge = entry_bridge()
    run(bridge, state=single_state(symbol="EURUSD"))
    run(bridge, state=single_state(symbol="GBPUSD"))
    assert bridge.place_order.call_count == 2


# ---------- C4: free-margin affordability ----------

def test_order_is_reduced_to_the_largest_affordable_size(tmp_path, monkeypatch):
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_required_margin.return_value = 10_000.0
    bridge.get_free_margin.return_value = 10_000.0  # budget is half of that
    run(bridge)
    assert bridge.place_order.call_args[0][2] > 0
    assert "size reduced" in "\n".join(app_logger.tail())


def test_order_is_skipped_when_even_the_minimum_lot_does_not_fit(tmp_path, monkeypatch):
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_required_margin.return_value = 1_000_000.0
    bridge.get_free_margin.return_value = 10.0
    run(bridge)
    bridge.place_order.assert_not_called()
    assert "smallest size the broker allows" in "\n".join(app_logger.tail())


def test_a_large_account_is_never_blocked_by_the_margin_gate():
    # ~$5.4M equity: the gate must not get in the way of a legitimate order.
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_account_equity.return_value = 5_400_000
    bridge.get_required_margin.return_value = 50_000.0
    bridge.get_free_margin.return_value = 5_000_000.0
    # Broker cap raised out of the way: this test is about the margin gate, and the lot-cap
    # gate (tested separately below) would otherwise be what blocks a 5.4M account.
    bridge.get_symbol_volume_limits.return_value = (0.01, 10_000.0, 0.01)
    run(bridge)
    assert bridge.place_order.called


def test_margin_gate_defers_to_the_broker_when_mt5_cannot_price_it():
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_required_margin.return_value = None
    run(bridge)
    assert bridge.place_order.called


# ---------- C7: grid hard caps ----------

GRID_SETTINGS = {"grid": {"grid_step_points": 100, "lot_multiplier": 1.0}}
# grid.get_signal targets 1 step and stops at 3 steps -- a 0.33 reward:risk, which the
# default floor rejects outright (see test_grid_is_blocked_by_the_default_reward_risk_floor).
# These three tests are about the grid hard caps, so the floor is lowered out of the way.
GRID_GLOBALS = dict(BASE_GLOBALS, min_reward_risk=0.0, max_sl_atr_multiple=100.0)


def test_grid_entry_blocked_when_total_lots_cap_would_be_exceeded(tmp_path, monkeypatch):
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_open_positions.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "volume": 1.99, "type": "BUY", "profit": 0.0},
    ]
    run(bridge, state=single_state(strategy="grid"), settings=GRID_SETTINGS, globals_=GRID_GLOBALS)
    bridge.place_order.assert_not_called()
    assert "grid strategy's hard cap" in "\n".join(app_logger.tail())


def test_grid_entry_blocked_by_hard_equity_stop(tmp_path, monkeypatch):
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    engine.reset_bar_gate()
    bridge = entry_bridge()
    run(bridge, state=single_state(strategy="grid"), settings=GRID_SETTINGS, globals_=GRID_GLOBALS, dd=12.0)
    bridge.place_order.assert_not_called()
    assert "grid strategy's hard equity stop" in "\n".join(app_logger.tail())


def test_grid_entry_allowed_below_both_hard_caps():
    engine.reset_bar_gate()
    bridge = entry_bridge()
    run(bridge, state=single_state(strategy="grid"), settings=GRID_SETTINGS, globals_=GRID_GLOBALS, dd=1.0)
    assert bridge.place_order.called
    assert bridge.place_order.call_args[0][2] <= 2.0


def test_close_position_is_called_with_the_position_ticket_on_flatten():
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_open_positions.return_value = [
        {"ticket": 4242, "symbol": "EURUSD", "volume": 0.3, "type": "BUY", "profit": -5.0},
    ]
    run(bridge, dd=20.0)
    assert bridge.close_position.call_args[0][0] == 4242


# ---------- symbol resolution on the trading path ----------

def test_run_once_trades_the_brokers_name_for_the_symbol(tmp_path, monkeypatch):
    # "I pick XAU but the logs say something else" -- every call must use one resolved name.
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    engine._logged_symbol_mappings.clear()
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.resolve_symbol.side_effect = lambda name: ("XAUUSD.m", None)
    bridge.get_symbol_tick_economics.return_value = (1.0, 0.01)
    bridge.get_symbol_volume_limits.return_value = (0.01, 1000.0, 0.01)
    run(bridge, state=single_state(symbol="XAUUSD"))
    assert bridge.place_order.call_args[0][0] == "XAUUSD.m"
    assert bridge.get_open_positions.call_args_list[0][0][0] == "XAUUSD.m"
    assert "is called 'XAUUSD.m'" in "\n".join(app_logger.tail())


def test_run_once_skips_and_explains_an_unresolvable_symbol(tmp_path, monkeypatch):
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.resolve_symbol.side_effect = lambda name: (
        None, "Symbol 'GOLD' not found. This broker calls it one of: XAUUSD.m")
    run(bridge, state=single_state(symbol="GOLD"))
    bridge.place_order.assert_not_called()
    assert "XAUUSD.m" in "\n".join(app_logger.tail())


# =====================================================================
# Trade-quality gates. The account's own 825-trade group won 84% of the time and still
# lost $5.7M: tiny targets, unbounded stops, always at the broker's maximum lot size.
# These three gates are what that group did not have.
# =====================================================================

def log_text(app_logger):
    return "\n".join(app_logger.tail())


def _logged(tmp_path, monkeypatch):
    import automation.app_logger as app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    return app_logger


def test_signal_below_the_reward_risk_floor_is_rejected(tmp_path, monkeypatch):
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    last = bridge.get_rates.return_value["close"].iloc[-1]
    # 20 points of risk for 10 of reward -- 0.5 R:R, the shape that loses money at any win rate.
    monkeypatch.setattr(engine.STRATEGY_MODULES["trend"], "get_signal",
                         lambda df, settings: ("BUY", last - 0.0020, last + 0.0010))
    run(bridge)
    bridge.place_order.assert_not_called()
    assert "reward:risk" in log_text(app_logger)


def test_signal_at_the_reward_risk_floor_is_allowed(monkeypatch):
    engine.reset_bar_gate()
    bridge = entry_bridge()
    last = bridge.get_rates.return_value["close"].iloc[-1]
    monkeypatch.setattr(engine.STRATEGY_MODULES["trend"], "get_signal",
                         lambda df, settings: ("BUY", last - 0.0010, last + 0.0015))
    run(bridge)
    assert bridge.place_order.called


def test_signal_with_no_stop_loss_is_rejected(tmp_path, monkeypatch):
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    last = bridge.get_rates.return_value["close"].iloc[-1]
    monkeypatch.setattr(engine.STRATEGY_MODULES["trend"], "get_signal",
                         lambda df, settings: ("BUY", None, last + 0.0030))
    run(bridge)
    bridge.place_order.assert_not_called()
    assert "no stop loss" in log_text(app_logger)


def test_stop_many_atrs_wide_is_rejected(tmp_path, monkeypatch):
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    last = bridge.get_rates.return_value["close"].iloc[-1]
    # 500 points of stop on a ~13-point-ATR instrument: a stop this far away is an
    # unbounded loss wearing a stop's clothing, and it is exactly how -$69k average
    # losses happen next to $4.9k average wins.
    monkeypatch.setattr(engine.STRATEGY_MODULES["trend"], "get_signal",
                         lambda df, settings: ("BUY", last - 0.0500, last + 0.1000))
    run(bridge)
    bridge.place_order.assert_not_called()
    assert "atr" in log_text(app_logger).lower()


def test_grid_is_blocked_by_the_default_quality_gates(tmp_path, monkeypatch):
    # grid.get_signal targets one step and stops at three: a 0.33 payoff ratio, the same
    # shape as the losing magic-20250630 group in this account's history. Its fixed
    # 100-point step is also far wider than ATR on an M5 chart, so both quality gates
    # object -- either one is a correct refusal.
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    run(bridge, state=single_state(strategy="grid"), settings=GRID_SETTINGS)
    bridge.place_order.assert_not_called()
    text = log_text(app_logger)
    assert "Trade skipped on EURUSD (grid)" in text
    assert "reward:risk" in text or "ATR" in text

    # ...and with both quality gates relaxed it does place an order, which is what proves
    # the block above came from the gates and not from something else.
    engine.reset_bar_gate()
    bridge2 = entry_bridge()
    run(bridge2, state=single_state(strategy="grid"), settings=GRID_SETTINGS,
        globals_=GRID_GLOBALS)
    assert bridge2.place_order.called


# ---------- broker lot cap: never silently trade a different risk model ----------

def big_account_bridge():
    """The live account: $5.43M equity, broker max 50 lots on every symbol."""
    bridge = entry_bridge()
    bridge.get_account_equity.return_value = 5_431_669.0
    bridge.get_symbol_volume_limits.return_value = (0.01, 50.0, 0.01)
    bridge.get_free_margin.return_value = 5_000_000.0
    bridge.get_required_margin.return_value = 1000.0
    return bridge


def test_broker_lot_cap_trades_the_smaller_size_and_says_so(tmp_path, monkeypatch):
    """The cap makes the position smaller, not riskier, so the trade goes ahead at the cap
    and the log states the reduced risk actually taken."""
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = big_account_bridge()
    run(bridge)
    assert bridge.place_order.called
    assert bridge.place_order.call_args[0][2] == 50.0     # sized at the cap
    text = log_text(app_logger)
    assert "Broker lot cap reached" in text
    assert "50.0" in text                                 # the cap
    assert "smaller position than requested" in text      # why this is safe


def test_broker_lot_cap_can_be_made_blocking_on_request(tmp_path, monkeypatch):
    """Opt-in for users who want the risk figure they set to be exactly the risk taken."""
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = big_account_bridge()
    run(bridge, globals_=dict(BASE_GLOBALS, block_when_lot_capped=True))
    bridge.place_order.assert_not_called()
    assert "REFUSED" in log_text(app_logger)


def test_no_lot_cap_warning_when_the_cap_does_not_bind(tmp_path, monkeypatch):
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()          # $10k equity, 100-lot cap
    run(bridge)
    assert bridge.place_order.called
    assert "LOT CAP" not in log_text(app_logger)


# ---------- every refusal names the gate that caused it ----------

def test_a_filter_rejection_says_which_filter(tmp_path, monkeypatch):
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_rates.side_effect = None
    run(bridge, globals_=dict(BASE_GLOBALS, session_filter_enabled=True,
                               session_start_hour=0, session_end_hour=0))
    bridge.place_order.assert_not_called()
    assert "trading session" in log_text(app_logger)


def test_repeating_block_reason_is_logged_once_not_once_per_tick(tmp_path, monkeypatch):
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    globals_ = dict(BASE_GLOBALS, session_filter_enabled=True,
                     session_start_hour=0, session_end_hour=0)
    for _ in range(5):
        run(bridge, globals_=globals_)
    assert log_text(app_logger).count("trading session") == 1


def test_empty_rates_are_reported_as_not_ready_not_as_no_signal(tmp_path, monkeypatch):
    # A symbol just selected into Market Watch answers the first fetch with zero bars while
    # the terminal syncs history. That used to reach the strategy and come back "NONE",
    # so a not-yet-ready symbol was indistinguishable from a quiet market.
    import pandas as pd
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_rates.return_value = pd.DataFrame()
    run(bridge)
    bridge.place_order.assert_not_called()
    assert "still loading history" in log_text(app_logger)


def test_history_recovering_re_arms_the_symbol(tmp_path, monkeypatch):
    import pandas as pd
    _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_rates.return_value = pd.DataFrame()
    run(bridge)
    bridge.get_rates.return_value = make_uptrend_rates_with_time()
    run(bridge)
    assert bridge.place_order.called


def test_kill_switch_with_nothing_open_still_says_why(tmp_path, monkeypatch):
    # Once the drawdown switch has flattened, every later tick found nothing to close and
    # returned in silence -- identical, from the log, to a quiet market.
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    bridge.get_open_positions.return_value = []
    run(bridge, dd=20.0)
    bridge.place_order.assert_not_called()
    bridge.close_position.assert_not_called()
    assert "kill-switch is active" in log_text(app_logger)


def test_portfolio_risk_cap_counts_every_symbol_not_just_this_one(tmp_path, monkeypatch):
    # An "aggregate portfolio risk" cap that only saw the traded symbol's own positions was
    # not an aggregate cap.
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    other = [{"ticket": 9, "symbol": "GBPUSD", "volume": 5.0, "type": "BUY",
              "profit": 0.0, "price_open": 1.2500, "sl": 1.2400}]
    bridge.get_open_positions.side_effect = lambda symbol=None: [] if symbol else other
    run(bridge, globals_=dict(BASE_GLOBALS, portfolio_risk_filter_enabled=True,
                               max_portfolio_risk_percent=6.0))
    bridge.place_order.assert_not_called()
    assert "across the account" in log_text(app_logger)


# ---------- both entry paths apply every new gate, not just single-symbol mode ----------

def watchlist_run(bridge, globals_=None, strategy="trend"):
    entry = {"id": 1, "symbol": "EURUSD", "timeframe": "M5", "strategy": strategy,
             "mode": "auto", "enabled": True}
    engine.run_watchlist_once(bridge, [entry], TREND_SETTINGS, globals_ or BASE_GLOBALS,
                               0.0, 0.0, [], [], [])


def test_order_refused_when_the_brokers_minimum_lot_over_risks_the_account(tmp_path, monkeypatch):
    # The opposite of the max-lot clamp and the more dangerous one: rounding UP to the
    # broker minimum means the position risks more than was configured, silently.
    app_logger = _logged(tmp_path, monkeypatch)
    engine.reset_bar_gate()
    bridge = entry_bridge()
    # $100 account: 1% is $1 of risk, and the strategy's ~18-point stop costs ~$180 a lot,
    # so the risk allows about 0.005 lots -- half the broker's smallest tradeable size.
    bridge.get_account_equity.return_value = 100.0
    bridge.get_symbol_tick_economics.return_value = (1.0, 0.00001)
    bridge.get_symbol_volume_limits.return_value = (0.01, 50.0, 0.01)
    run(bridge)
    bridge.place_order.assert_not_called()
    text = log_text(app_logger)
    assert "BROKER MINIMUM LOT EXCEEDS YOUR RISK" in text
    assert "MORE than you configured" in text


# ---------- The stop slider set to Off must actually trade ----------
# The setting was accepted by the stop-sanity gate and then refused one gate lower by the
# reward:risk floor ("no usable take-profit or stop-loss to measure reward:risk against"),
# so the bot looked armed and never opened anything.

STOP_OFF = dict(BASE_GLOBALS, bot_stop_override_enabled=True,
                 bot_sl_atr_multiple=0, bot_tp_atr_multiple=3.0)


def test_stop_slider_off_still_reaches_place_order():
    engine.reset_bar_gate()
    bridge = entry_bridge()
    run(bridge, globals_=STOP_OFF)
    assert bridge.place_order.called, "reward:risk gate blocked a deliberately stopless trade"
    assert bridge.place_order.call_args.kwargs["sl"] is None, "an sl was sent despite the slider Off"


def test_target_slider_off_still_reaches_place_order():
    """Same trap on the other side: no target means no ratio, not a bad ratio."""
    engine.reset_bar_gate()
    bridge = entry_bridge()
    run(bridge, globals_=dict(BASE_GLOBALS, bot_stop_override_enabled=True,
                               bot_sl_atr_multiple=2.0, bot_tp_atr_multiple=0))
    assert bridge.place_order.called
    assert bridge.place_order.call_args.kwargs["tp"] is None


def test_confidence_sizing_survives_a_missing_stop():
    """rm.calc_confidence does abs(entry - sl); with the slider Off that used to be a
    TypeError rather than a trade."""
    engine.reset_bar_gate()
    bridge = entry_bridge()
    run(bridge, globals_=dict(STOP_OFF, confidence_sizing_enabled=True))
    assert bridge.place_order.called


def test_a_missing_reward_risk_is_still_refused_when_the_user_did_not_ask_for_it():
    """The stand-down is scoped to the deliberate choice. A strategy that simply produced no
    target must still be blocked -- that is the gate doing its job."""
    engine.reset_bar_gate()
    assert engine.reward_risk_is_measurable(None, 1.2, BASE_GLOBALS) is True
    assert engine.reward_risk_is_measurable(None, 1.2, STOP_OFF) is False
    assert engine.reward_risk_is_measurable(1.0, None, STOP_OFF) is True  # tp slider is on


def test_no_stop_loss_warning_is_logged_once_not_every_tick(tmp_path, monkeypatch):
    from automation import app_logger
    monkeypatch.setattr(app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    engine.reset_state_latches()
    for i in range(4):
        engine.reset_bar_gate()
        run(entry_bridge(make_uptrend_rates_with_time(1_700_000_000 + i * 300)),
            globals_=STOP_OFF)
    lines = app_logger.tail()
    assert sum("NO STOP LOSS" in ln for ln in lines) == 1, "per-tick spam is back"
