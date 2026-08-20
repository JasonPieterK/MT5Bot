"""The structured "why is it not opening a trade?" state the engine keeps per
(symbol, strategy). Log text alone made the user read logs/app.log and infer."""
import pandas as pd
import pytest

import core.engine as engine
from tests.core.test_engine import (BASE_GLOBALS, TREND_SETTINGS, entry_bridge, make_bridge,
                                    make_uptrend_rates_with_time, run, single_state)


@pytest.fixture(autouse=True)
def _clean_state():
    engine.reset_bar_gate()
    yield
    engine.reset_bar_gate()


def evaluation(symbol="EURUSD", strategy="trend"):
    return {(e["symbol"], e["strategy"]): e for e in engine.get_evaluations()}.get((symbol, strategy))


# ---------- the healthy, common case ----------

def test_no_signal_is_recorded_as_its_own_outcome_not_as_a_block():
    """A quiet market and a broken bot look identical in a log that only records refusals."""
    flat = pd.DataFrame({"open": [1.1] * 40, "high": [1.1] * 40, "low": [1.1] * 40,
                          "close": [1.1] * 40, "spread": [5] * 40,
                          "time": [1_700_000_000 + i * 300 for i in range(40)]})
    bridge = entry_bridge(rates=flat)
    run(bridge)
    ev = evaluation()
    assert ev["outcome"] == engine.OUTCOME_NO_SIGNAL
    assert ev["gate"] is None
    assert ev["signal"] is None
    assert "no entry setup" in ev["message"].lower()
    assert ev["details"]["bars"] == 40


def test_a_passing_trade_is_recorded_too_so_success_is_visible():
    bridge = entry_bridge()
    run(bridge)
    ev = evaluation()
    assert ev["outcome"] == engine.OUTCOME_ORDER_SENT
    assert ev["signal"] == "BUY"
    assert ev["details"]["accepted"] is True
    assert ev["details"]["lots"] > 0
    assert "every gate passed" in ev["message"]


def test_a_rejected_order_is_recorded_as_sent_but_not_accepted():
    bridge = entry_bridge()
    bridge.place_order.return_value = (False, 10016)
    run(bridge)
    ev = evaluation()
    assert ev["outcome"] == engine.OUTCOME_ORDER_SENT
    assert ev["details"]["accepted"] is False
    assert ev["details"]["retcode"] == 10016


def test_the_second_tick_on_the_same_bar_is_recorded_as_waiting_not_as_silence():
    bridge = entry_bridge()
    run(bridge)
    run(bridge)
    ev = evaluation()
    assert ev["outcome"] == engine.OUTCOME_WAITING_BAR
    assert "already acted on the current" in ev["message"]


# ---------- blocks name their gate and carry their numbers ----------

def test_a_blocked_trade_names_the_gate_and_keeps_the_signal_that_was_refused():
    bridge = entry_bridge()
    globals_ = dict(BASE_GLOBALS, max_concurrent_trades=0)
    run(bridge, globals_=globals_)
    ev = evaluation()
    assert ev["outcome"] == engine.OUTCOME_BLOCKED
    assert ev["gate"] == "risk_limits"
    assert ev["signal"] == "BUY"
    assert ev["details"]["max_concurrent_trades"] == 0
    assert ev["remedy"]


def test_the_lot_cap_is_explained_without_stopping_the_trade():
    """1% of $5.4M cannot be sized under a 50-lot cap. The panel must still explain the gap
    between configured and actual risk -- but the trade goes ahead, because sizing at the cap
    risks LESS than configured, with the same stop."""
    bridge = entry_bridge()
    bridge.get_account_equity.return_value = 5_430_000
    bridge.get_symbol_volume_limits.return_value = (0.01, 50.0, 0.01)
    run(bridge)
    # The trade is what matters: sized at the cap, which risks less than 1% -- not refused.
    assert bridge.place_order.called
    assert bridge.place_order.call_args[0][2] == 50.0
    ev = evaluation()
    assert ev["outcome"] == engine.OUTCOME_ORDER_SENT, "the cap must not end the tick in a block"

    # The size gap is still explained, independently of any block, via risk_reality().
    reality = engine.risk_reality(bridge, "EURUSD", "H1", "trend", TREND_SETTINGS,
                                   BASE_GLOBALS)
    assert reality["lot_cap_binds"] is True
    assert reality["max_expressible_risk_percent"] < reality["configured_risk_percent"]


def test_reward_risk_block_reports_the_computed_ratio_against_the_floor():
    bridge = entry_bridge()
    run(bridge, globals_=dict(BASE_GLOBALS, min_reward_risk=99.0))
    ev = evaluation()
    assert ev["gate"] == "reward_risk"
    assert ev["details"]["min_reward_risk"] == 99.0
    assert 0 < ev["details"]["reward_risk"] < 99.0


def test_a_signal_filter_block_reports_its_measurement_and_its_threshold():
    bridge = entry_bridge()
    bridge.get_recent_ticks.return_value = [1.1] * 50
    globals_ = dict(BASE_GLOBALS, tick_momentum_filter_enabled=True, tick_momentum_threshold=0.9)
    run(bridge, globals_=globals_)
    ev = evaluation()
    assert ev["gate"] == "tick_momentum"
    assert ev["details"]["threshold"] == 0.9
    assert "momentum_score" in ev["details"]
    assert "Signal filters page" in ev["remedy"]


def test_the_broker_stop_distance_refusal_is_a_named_gate_not_a_bare_log_line():
    bridge = entry_bridge()
    bridge.check_stops_valid.return_value = (False, "sl too close to price: min stop distance is 0.003")
    run(bridge)
    ev = evaluation()
    assert ev["gate"] == "stop_distance"
    assert "min stop distance" in ev["details"]["broker_reason"]


def test_the_free_margin_refusal_is_a_named_gate_with_the_numbers():
    bridge = entry_bridge()
    bridge.get_required_margin.return_value = 1_000_000.0
    bridge.get_free_margin.return_value = 10.0
    run(bridge)
    ev = evaluation()
    assert ev["gate"] == "free_margin"
    assert ev["details"]["free_margin"] == 10.0


def test_an_unresolvable_symbol_is_recorded_against_the_target_that_asked_for_it():
    bridge = entry_bridge()
    bridge.resolve_symbol.side_effect = lambda name: (None, f"'{name}' is not offered here")
    run(bridge, state=single_state(symbol="NOPEUSD"))
    ev = evaluation(symbol="NOPEUSD")
    assert ev["gate"] == "symbol"
    assert "not offered here" in ev["message"]
    assert "Market Watch" in ev["remedy"]


def test_a_block_is_recorded_on_every_tick_even_though_the_log_line_is_deduped():
    """log_block only logs a repeated reason once. The panel must still show current state."""
    bridge = entry_bridge()
    globals_ = dict(BASE_GLOBALS, max_concurrent_trades=0)
    run(bridge, globals_=globals_)
    engine._last_eval.clear()          # the log-dedupe memory deliberately survives this
    run(bridge, globals_=globals_)
    assert evaluation()["outcome"] == engine.OUTCOME_BLOCKED


def test_a_mode_change_clears_the_evaluations_so_stale_state_is_never_shown():
    bridge = entry_bridge()
    run(bridge)
    assert engine.get_evaluations()
    engine.reset_bar_gate()
    assert engine.get_evaluations() == []


# ---------- the risk arithmetic behind the lot cap ----------

def test_risk_reality_reports_the_gap_between_configured_and_expressible_risk():
    bridge = make_bridge()
    bridge.get_rates.return_value = make_uptrend_rates_with_time()
    bridge.get_account_equity.return_value = 5_430_000
    bridge.get_symbol_volume_limits.return_value = (0.01, 50.0, 0.01)
    reality = engine.risk_reality(bridge, "EURUSD", "H1", "trend", TREND_SETTINGS,
                                   dict(BASE_GLOBALS, risk_percent=1.0))
    assert reality["configured_risk_percent"] == 1.0
    assert reality["lot_cap_binds"] is True
    assert reality["effective_risk_percent"] < 1.0
    assert reality["max_lot"] == 50.0
    assert reality["lots_for_configured_risk"] > 50.0


def test_risk_reality_reports_no_gap_on_an_account_that_can_size_its_risk():
    bridge = make_bridge()
    bridge.get_rates.return_value = make_uptrend_rates_with_time()
    bridge.get_account_equity.return_value = 10_000
    reality = engine.risk_reality(bridge, "EURUSD", "H1", "trend", TREND_SETTINGS, BASE_GLOBALS)
    assert reality["lot_cap_binds"] is False
    assert reality["effective_risk_percent"] == 1.0


def test_risk_reality_returns_none_rather_than_raising_when_mt5_gives_nothing():
    bridge = make_bridge()
    bridge.get_rates.return_value = pd.DataFrame()
    assert engine.risk_reality(bridge, "EURUSD", "H1", "trend", TREND_SETTINGS, BASE_GLOBALS) is None


# ---------- the profile's lot ceiling is honoured on top of the broker's ----------

def test_the_profile_lot_ceiling_narrows_the_brokers_own_limit():
    assert engine.effective_max_lot(50.0, {"max_lot": 25.0}) == 25.0
    assert engine.effective_max_lot(50.0, {"max_lot": 0.0}) == 50.0
    assert engine.effective_max_lot(50.0, {}) == 50.0
    # A profile ceiling above the broker's is not a licence to exceed the broker.
    assert engine.effective_max_lot(50.0, {"max_lot": 500.0}) == 50.0


def test_the_profile_lot_ceiling_caps_the_lots_actually_sent():
    bridge = entry_bridge()
    bridge.get_account_equity.return_value = 1_000_000
    bridge.get_symbol_volume_limits.return_value = (0.01, 500.0, 0.01)
    run(bridge, globals_=dict(BASE_GLOBALS, max_lot=2.0, block_when_lot_capped=False))
    assert bridge.place_order.call_args[0][2] <= 2.0
