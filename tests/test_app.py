import pandas as pd
import pytest
from unittest.mock import MagicMock
import core.auto_mode as auto_mode
import core.config as config
import app as app_module


@pytest.fixture
def client(monkeypatch):
    app_module.bridge = MagicMock()
    app_module.bridge.get_open_positions.return_value = []
    app_module.bridge.get_account_equity.return_value = 10000
    app_module.bridge.get_margin_level.return_value = 500.0
    app_module.bridge.resolve_symbol.side_effect = lambda name: (name, None)
    app_module.state = config.new_state()
    app_module.app.config["TESTING"] = True
    yield app_module.app.test_client()
    # Setting the flag only asks the loop to stop; it can be mid-sleep and tick again.
    # Join it, so a thread from this test cannot still be running (and writing) during
    # the next one. Belt-and-braces with conftest's session-scoped path isolation.
    app_module._stop_flag.set()
    thread = app_module._engine_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=10)


def test_get_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "positions" in body
    assert body["trading_mode"] == "off"


def test_post_select_symbol_timeframe_strategy(client):
    resp = client.post("/api/select", json={"symbol": "GBPUSD", "timeframe": "M15", "strategy": "smc"})
    assert resp.status_code == 200
    assert app_module.state["symbol"] == "GBPUSD"
    assert app_module.state["timeframe"] == "M15"
    assert app_module.state["active_strategy"] == "smc"


def test_post_settings_updates_strategy_settings(client):
    resp = client.post("/api/settings", json={"strategy": "trend", "settings": {"fast_period": 5}})
    assert resp.status_code == 200
    assert app_module.strategy_settings["trend"]["fast_period"] == 5


def test_grid_hard_caps_not_settable_via_api(client):
    resp = client.post("/api/settings", json={"strategy": "grid", "settings": {"max_levels": 999}})
    assert resp.status_code == 200
    assert "max_levels" not in app_module.strategy_settings["grid"]


def test_index_serves_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_journal_get_and_set(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.journal, "JOURNAL_PATH", str(tmp_path / "journal.json"))
    resp = client.post("/api/journal/555", json={"note": "watching for breakout"})
    assert resp.status_code == 200
    resp = client.get("/api/journal/555")
    assert resp.get_json()["note"] == "watching for breakout"


def test_save_state_endpoint(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.persistence, "STATE_PATH", str(tmp_path / "app_state.json"))
    resp = client.post("/api/state/save")
    assert resp.status_code == 200
    assert app_module.persistence.load_all() is not None


def test_ml_train_needs_enough_trades(client):
    app_module.bridge.get_history_deals.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "profit": 10.0, "time": 1700000000, "magic": 1001},
    ]
    resp = client.post("/api/ml/train")
    assert resp.status_code == 400
    assert "need 100" in resp.get_json()["error"]


def learnable_deals(n=300, magic=1001):
    """Hour of day decides the outcome, so a model that works has something real to find.
    One deal an hour, so both classes appear throughout and the time-ordered split is fair."""
    import datetime as _dt
    out = []
    for i in range(n):
        ts = 1700000000 + i * 3600
        hour = _dt.datetime.fromtimestamp(ts).hour
        out.append({"ticket": i, "symbol": "EURUSD", "time": ts, "magic": magic,
                    "profit": 10.0 if hour < 12 else -5.0})
    return out


def test_ml_train_saves_a_model_that_works_out_of_sample(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.ml_filter, "WEIGHTS_PATH", str(tmp_path / "ml_weights.json"))
    app_module.bridge.get_history_deals.return_value = learnable_deals()
    resp = client.post("/api/ml/train")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["report"]["accepted"] is True
    assert body["report"]["out_of_sample_auc"] >= app_module.ml_filter.MIN_OOS_AUC
    assert app_module.ml_filter.load_weights() is not None


def test_ml_train_refuses_a_model_with_no_out_of_sample_edge(client, tmp_path, monkeypatch):
    """The important case. On this account's real 1,079 closed trades the out-of-sample AUC
    is at or below chance, and a filter that cannot beat a coin flip is worse than none --
    it adds confidence that is not there."""
    monkeypatch.setattr(app_module.ml_filter, "WEIGHTS_PATH", str(tmp_path / "ml_weights.json"))
    import random
    rng = random.Random(7)
    deals = [{"ticket": i, "symbol": "EURUSD", "time": 1700000000 + i * 3600, "magic": 1001,
              "profit": rng.choice([10.0, -5.0])} for i in range(300)]
    app_module.bridge.get_history_deals.return_value = deals
    resp = client.post("/api/ml/train")
    body = resp.get_json()
    assert body["ok"] is False
    assert body["report"]["accepted"] is False
    assert "coin flip" in body["report"]["reason"]
    # No model written, and any previously saved one is left untouched.
    assert app_module.ml_filter.load_weights() is None


def test_ml_train_uses_unattributed_deals_and_says_so(client, tmp_path, monkeypatch):
    # Every one of the 1,079 real closed trades on this account carries a magic number that
    # belongs to no strategy here, so the old filter dropped all of them and trained on zero
    # rows while reporting only "not enough labeled trades".
    monkeypatch.setattr(app_module.ml_filter, "WEIGHTS_PATH", str(tmp_path / "ml_weights.json"))
    app_module.bridge.get_history_deals.return_value = learnable_deals(magic=20250630)
    resp = client.post("/api/ml/train")
    body = resp.get_json()
    assert body["report"]["rows"] == 300
    assert "0 of 300" in body["report"]["attribution"]


def test_auto_tune_run_suggests_disable(client):
    app_module.bridge.get_history_deals.return_value = [
        {"ticket": i, "symbol": "EURUSD", "profit": -5.0, "time": 1700000000 + i, "magic": 1001}
        for i in range(15)
    ] + [
        {"ticket": 100 + i, "symbol": "EURUSD", "profit": 10.0, "time": 1700000000 + i, "magic": 1002}
        for i in range(15)
    ]
    resp = client.post("/api/auto_tune/run")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "trend" in body["disable_suggested"]
    assert body["best_strategy"] == "scalping"


def test_auto_tune_switches_strategy_when_enabled(client):
    app_module.state["active_strategy"] = "trend"
    app_module.global_settings["auto_tune_enabled"] = True
    app_module.bridge.get_history_deals.return_value = [
        {"ticket": i, "symbol": "EURUSD", "profit": -5.0, "time": 1700000000 + i, "magic": 1001}
        for i in range(15)
    ] + [
        {"ticket": 100 + i, "symbol": "EURUSD", "profit": 10.0, "time": 1700000000 + i, "magic": 1002}
        for i in range(15)
    ]
    resp = client.post("/api/auto_tune/run")
    body = resp.get_json()
    assert body["switched_to"] == "scalping"
    assert app_module.state["active_strategy"] == "scalping"
    app_module.global_settings["auto_tune_enabled"] = False


def test_load_persisted_state_never_resumes_live_trading(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.persistence, "STATE_PATH", str(tmp_path / "app_state.json"))
    app_module.persistence.save_all({
        # Includes the legacy booleans a pre-upgrade app_state.json would carry.
        "state": {"symbol": "GBPUSD", "trading_mode": "watchlist",
                   "auto_enabled": True, "watchlist_enabled": True},
    })
    app_module.state["trading_mode"] = "watchlist"
    app_module._load_persisted_state()
    assert app_module.state["trading_mode"] == "off"
    assert "auto_enabled" not in app_module.state
    assert "watchlist_enabled" not in app_module.state
    assert app_module.state["symbol"] == "GBPUSD"


def test_sync_mt5_status_panel_writes_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.mt5_status_sync, "get_common_files_dir", lambda: str(tmp_path))
    app_module.bridge.get_account_equity.return_value = 12345.6
    app_module.bridge.get_open_positions.return_value = []
    app_module._sync_mt5_status_panel()
    path = tmp_path / app_module.mt5_status_sync.STATUS_FILENAME
    assert path.exists()
    assert "equity=12345.6" in path.read_text()


def test_sync_mt5_status_panel_never_raises_on_bridge_error(client):
    app_module.bridge.get_account_equity.side_effect = RuntimeError("disconnected")
    app_module._sync_mt5_status_panel()  # must not raise


def test_get_recent_logs(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    app_module.app_logger.info("test line one")
    app_module.app_logger.info("test line two")
    resp = client.get("/api/logs/recent")
    assert resp.status_code == 200
    lines = resp.get_json()["lines"]
    assert len(lines) == 2
    assert "test line two" in lines[-1]


def test_get_recent_logs_respects_lines_param(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    for i in range(5):
        app_module.app_logger.info(f"line {i}")
    resp = client.get("/api/logs/recent?lines=2")
    lines = resp.get_json()["lines"]
    assert len(lines) == 2
    assert "line 4" in lines[-1]


def test_unhandled_error_returns_json_and_logs(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    app_module.app.config["PROPAGATE_EXCEPTIONS"] = False
    app_module.bridge.get_account_equity.side_effect = RuntimeError("simulated MT5 failure")
    resp = client.get("/api/status")
    app_module.app.config["PROPAGATE_EXCEPTIONS"] = True
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False
    # The browser gets a reference id, not the exception text -- exception messages
    # routinely carry absolute local paths and other internals.
    assert "simulated MT5 failure" not in body["error"]
    assert body["error_id"] in body["error"]
    logged = "\n".join(app_module.app_logger.tail())
    assert "simulated MT5 failure" in logged
    assert body["error_id"] in logged


def test_auto_enable_logs_event(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    client.post("/api/trading_mode", json={"mode": "single"})
    logged = "\n".join(app_module.app_logger.tail())
    assert "Trading ENABLED" in logged


# ---------- /api/diagnose (why won't it trade?) ----------

def test_diagnose_endpoint_reports_findings_and_logs_them(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    app_module.engine._last_diagnosis_at = 0.0
    app_module.bridge.diagnose_trading.return_value = [
        {"problem": "Algo Trading is switched OFF in the MT5 terminal.",
         "fix": "Click the 'Algo Trading' button in the MT5 toolbar."},
    ]
    app_module.bridge.get_account_summary.return_value = {"trade_mode": "real", "margin_free": 5.0}
    resp = client.get("/api/diagnose?symbol=XAUUSD")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert body["symbol"] == "XAUUSD"
    assert len(body["findings"]) == 1
    assert body["account"]["trade_mode"] == "real"
    assert "Algo Trading" in "\n".join(app_module.app_logger.tail())


def test_diagnose_endpoint_all_clear(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    app_module.engine._last_diagnosis_at = 0.0
    app_module.bridge.diagnose_trading.return_value = []
    app_module.bridge.get_account_summary.return_value = {"trade_mode": "demo", "margin_free": 100.0}
    body = client.get("/api/diagnose").get_json()
    assert body["ok"] is True
    assert body["findings"] == []


def test_diagnose_endpoint_defaults_to_selected_symbol(client):
    app_module.engine._last_diagnosis_at = 0.0
    app_module.state["symbol"] = "GBPUSD"
    app_module.bridge.diagnose_trading.return_value = []
    app_module.bridge.get_account_summary.return_value = {}
    assert client.get("/api/diagnose").get_json()["symbol"] == "GBPUSD"


def test_trading_mode_endpoint_sets_each_mode(client):
    for mode in ("single", "off"):
        resp = client.post("/api/trading_mode", json={"mode": mode})
        assert resp.status_code == 200
        assert resp.get_json()["trading_mode"] == mode
        assert app_module.state["trading_mode"] == mode


def test_trading_mode_rejects_an_unknown_mode(client):
    resp = client.post("/api/trading_mode", json={"mode": "yolo"})
    assert resp.status_code == 400
    assert app_module.state["trading_mode"] == "off"


def test_turning_trading_off_always_works(client):
    app_module.state["trading_mode"] = "single"
    assert client.post("/api/trading_mode", json={"mode": "off"}).status_code == 200
    assert app_module.state["trading_mode"] == "off"


def test_status_exposes_trading_mode(client):
    client.post("/api/trading_mode", json={"mode": "single"})
    assert client.get("/api/status").get_json()["trading_mode"] == "single"


# ---------- H3: engine health is visible ----------

def test_status_exposes_engine_health_fields(client):
    body = client.get("/api/status").get_json()
    assert "last_tick_at" in body
    assert "last_error" in body
    assert "last_error_at" in body


# ---------- C2: kill-switch inputs are real numbers, not hardcoded zeros ----------

def test_drawdown_percent_is_measured_from_peak_equity(client):
    app_module.state.pop("peak_equity", None)
    app_module.bridge.get_history_deals.return_value = []
    app_module.bridge.get_open_positions.return_value = []
    app_module.bridge.get_account_equity.return_value = 100_000
    app_module._compute_risk_percents()  # sets the peak
    app_module.bridge.get_account_equity.return_value = 80_000
    _daily, drawdown = app_module._compute_risk_percents()
    assert round(drawdown, 2) == 20.0


def test_peak_equity_only_ever_rises(client):
    app_module.state.pop("peak_equity", None)
    app_module.bridge.get_history_deals.return_value = []
    app_module.bridge.get_open_positions.return_value = []
    for equity in (100_000, 50_000, 90_000):
        app_module.bridge.get_account_equity.return_value = equity
        app_module._compute_risk_percents()
    assert app_module.state["peak_equity"] == 100_000


def test_daily_pnl_percent_counts_closed_deals_and_floating_profit(client):
    app_module.state.pop("peak_equity", None)
    app_module.bridge.get_account_equity.return_value = 9_400.0
    app_module.bridge.get_history_deals.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "profit": -400.0, "time": 1},
    ]
    app_module.bridge.get_open_positions.return_value = [
        {"ticket": 2, "symbol": "EURUSD", "volume": 0.1, "type": "BUY", "profit": -200.0,
         "price_open": 1.1, "sl": 0.0, "tp": 0.0},
    ]
    daily, _drawdown = app_module._compute_risk_percents()
    # Day started at 10,000; down 600 today = -6%.
    assert round(daily, 2) == -6.0


def test_daily_loss_limit_breach_is_logged(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    app_module.engine.reset_state_latches()  # the limit now logs on transition, not per tick
    app_module.state.pop("peak_equity", None)
    app_module.bridge.get_account_equity.return_value = 9_400.0
    app_module.bridge.get_history_deals.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "profit": -600.0, "time": 1},
    ]
    app_module.bridge.get_open_positions.return_value = []
    app_module._compute_risk_percents()
    assert "DAILY LOSS LIMIT hit" in "\n".join(app_module.app_logger.tail())


def test_max_drawdown_breach_is_logged(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    app_module.engine.reset_state_latches()
    # The peak and the current reading must belong to the SAME account, or the drawdown
    # is meaningless -- see tests/test_peak_equity_scope.py.
    app_module.state["peak_equity"] = 100_000.0
    app_module.state["peak_equity_login"] = 111
    app_module.bridge.get_account_login.return_value = 111
    app_module.bridge.get_history_deals.return_value = []
    app_module.bridge.get_open_positions.return_value = []
    app_module.bridge.get_account_equity.return_value = 80_000.0
    app_module._compute_risk_percents()
    assert "MAX DRAWDOWN hit" in "\n".join(app_module.app_logger.tail())


def test_flat_day_reports_zero_percent(client):
    app_module.state.pop("peak_equity", None)
    app_module.bridge.get_account_equity.return_value = 10_000.0
    app_module.bridge.get_history_deals.return_value = []
    app_module.bridge.get_open_positions.return_value = []
    daily, drawdown = app_module._compute_risk_percents()
    assert daily == 0.0
    assert drawdown == 0.0


def test_persisted_settings_cannot_hide_a_newly_added_default(client, monkeypatch):
    # A state file written before the quality gates existed must not leave them unset.
    import core.config as config
    saved = {
        "state": {"symbol": "GBPUSD"},
        "strategy_settings": {"trend": {"fast_period": 5, "a_key_that_no_longer_exists": 1}},
        "global_settings": {"risk_percent": 2.0, "removed_setting": True},
        "watchlist": [], "blackout_windows": [], "account_profiles": [],
    }
    monkeypatch.setattr(app_module.persistence, "load_all", lambda: saved)
    app_module._load_persisted_state()

    assert app_module.global_settings["risk_percent"] == 2.0          # user's value kept
    assert "removed_setting" not in app_module.global_settings         # stale key dropped
    for key in ("min_reward_risk", "max_sl_atr_multiple", "block_when_lot_capped"):
        assert app_module.global_settings[key] == config.GLOBAL_SETTINGS[key]
    assert app_module.strategy_settings["trend"]["fast_period"] == 5
    assert "a_key_that_no_longer_exists" not in app_module.strategy_settings["trend"]


def test_global_settings_rejects_a_risk_percent_above_the_hard_ceiling(client):
    before = app_module.global_settings["risk_percent"]
    resp = client.post("/api/global_settings", json={"risk_percent": 500})
    body = resp.get_json()
    assert body["ok"] is False
    assert "risk_percent" in body["rejected"]
    assert app_module.global_settings["risk_percent"] == before


def test_global_settings_accepts_a_sane_value(client):
    resp = client.post("/api/global_settings", json={"risk_percent": 0.05,
                                                       "min_reward_risk": 2.0})
    assert resp.get_json()["ok"] is True
    assert app_module.global_settings["risk_percent"] == 0.05
    assert app_module.global_settings["min_reward_risk"] == 2.0
    app_module.global_settings.update(config.GLOBAL_SETTINGS)


def test_global_settings_rejects_non_numeric_where_a_number_is_required(client):
    resp = client.post("/api/global_settings", json={"max_concurrent_trades": "lots"})
    assert resp.get_json()["ok"] is False


# ---------- /api/why_no_trade (the live "why is it not opening a trade?" answer) ----------

def _priced_bridge(equity=5_430_000, broker_max_lot=50.0):
    """A bridge that answers with this account's real shape: large equity, 50-lot cap."""
    import pandas as pd
    closes = [1.10 + i * 0.0002 for i in range(60)]
    app_module.bridge.get_rates.return_value = pd.DataFrame({
        "open": closes, "high": [c + 0.0005 for c in closes], "low": [c - 0.0005 for c in closes],
        "close": closes, "spread": [5] * 60,
        "time": [1_700_000_000 + i * 3600 for i in range(60)],
    })
    app_module.bridge.get_account_equity.return_value = equity
    app_module.bridge.get_symbol_volume_limits.return_value = (0.01, broker_max_lot, 0.01)
    app_module.bridge.get_symbol_tick_economics.return_value = (1.0, 0.00001)
    return app_module.bridge


def test_why_no_trade_explains_the_off_state_instead_of_returning_nothing(client):
    _priced_bridge()
    body = client.get("/api/why_no_trade").get_json()
    assert body["trading_mode"] == "off"
    assert body["armed"] is False
    assert "switched OFF" in body["headline"]
    # Off still names what WOULD be traded -- that is most of the question.
    assert body["summary"]["targets"] == 1
    assert body["targets"][0]["symbol"] == app_module.state["symbol"]


def test_why_no_trade_reports_the_gate_that_refused_the_last_signal(client):
    _priced_bridge()
    app_module.state["trading_mode"] = "single"
    app_module.engine.reset_bar_gate()
    app_module.engine.log_block(
        app_module.state["symbol"], app_module.state["active_strategy"], "lot_clamp",
        "BROKER LOT CAP BINDING", details={"max_lot": 50.0, "requested_lots": 776.0},
        remedy="Lower risk_percent to about 0.063")
    body = client.get("/api/why_no_trade").get_json()
    assert body["summary"]["blocked"] == 1
    assert "lot_clamp" in body["headline"]
    ev = body["targets"][0]["evaluation"]
    assert ev["gate"] == "lot_clamp"
    assert ev["details"]["requested_lots"] == 776.0
    assert "0.063" in ev["remedy"]


def test_why_no_trade_distinguishes_no_signal_from_a_block(client):
    _priced_bridge()
    app_module.state["trading_mode"] = "single"
    app_module.engine.reset_bar_gate()
    app_module.engine.record_evaluation(
        app_module.state["symbol"], app_module.state["active_strategy"],
        app_module.engine.OUTCOME_NO_SIGNAL, signal=None, message="No entry setup.")
    body = client.get("/api/why_no_trade").get_json()
    assert body["summary"]["no_signal"] == 1
    assert body["summary"]["blocked"] == 0
    assert "Nothing is blocked" in body["headline"]


def test_why_no_trade_includes_the_effective_risk_arithmetic_per_target(client):
    _priced_bridge()
    app_module.global_settings["risk_percent"] = 1.0
    app_module.global_settings["max_lot"] = 0.0
    risk = client.get("/api/why_no_trade").get_json()["targets"][0]["risk"]
    assert risk["configured_risk_percent"] == 1.0
    assert risk["lot_cap_binds"] is True
    assert risk["effective_risk_percent"] < 1.0
    assert risk["lots_for_configured_risk"] > 50.0


def test_why_no_trade_reports_the_broker_symbol_the_engine_actually_trades(client):
    _priced_bridge()
    app_module.bridge.resolve_symbol.side_effect = lambda name: (name + "#", None)
    target = client.get("/api/why_no_trade").get_json()["targets"][0]
    assert target["symbol"] == "EURUSD"
    assert target["traded_symbol"] == "EURUSD#"


# ---------- /api/profiles ----------

def test_profiles_are_priced_against_the_live_account(client):
    _priced_bridge()
    body = client.get("/api/profiles").get_json()
    assert [p["id"] for p in body["presets"]][0] == "capital_preservation"
    balanced = next(p for p in body["presets"] if p["id"] == "balanced")
    assert balanced["requested_risk_percent"] == 1.0
    assert balanced["lot_cap_binds"] is True
    assert balanced["effective_risk_percent"] < 1.0
    assert balanced["max_lot"] == 25.0        # half of the broker's 50, derived not hardcoded
    assert "no strategy with a demonstrated edge" in body["honesty_note"]


def test_profiles_preview_what_applying_would_change(client):
    _priced_bridge()
    app_module.global_settings["max_concurrent_trades"] = 3
    balanced = next(p for p in client.get("/api/profiles").get_json()["presets"]
                    if p["id"] == "capital_preservation")
    change = next(c for c in balanced["changes"] if c["key"] == "max_concurrent_trades")
    assert change["from"] == 3
    assert change["to"] == 1


def test_applying_a_preset_never_leaves_a_risk_that_blocks_every_trade(client):
    """The failure this whole system exists to prevent: applying 1% on this account made the
    engine refuse every single trade, silently."""
    _priced_bridge()
    resp = client.post("/api/profiles/apply", json={"id": "balanced"})
    assert resp.status_code == 200
    applied = app_module.global_settings["risk_percent"]
    reality = app_module.engine.risk_reality(
        app_module.bridge, "EURUSD", app_module.state["timeframe"], "trend",
        app_module.strategy_settings, app_module.global_settings)
    assert applied < 1.0
    assert reality["lot_cap_binds"] is False


def test_applying_a_preset_sets_every_setting_it_owns(client):
    _priced_bridge()
    client.post("/api/profiles/apply", json={"id": "capital_preservation"})
    g = app_module.global_settings
    assert g["max_concurrent_trades"] == 1
    assert g["daily_loss_limit_percent"] == 2.0
    assert g["max_drawdown_percent"] == 5.0
    assert g["min_reward_risk"] == 2.0
    assert g["max_lot"] == 5.0                # 10% of the broker's 50 lots
    assert g["trailing_enabled"] is True
    assert app_module.state["timeframe"] == "H1"
    assert app_module.state["active_profile"]["id"] == "capital_preservation"


def test_applying_a_preset_never_changes_the_strategy(client):
    _priced_bridge()
    app_module.state["active_strategy"] = "smc"
    client.post("/api/profiles/apply", json={"id": "aggressive"}, headers={})
    assert app_module.state["active_strategy"] == "smc"


def test_profile_change_is_logged_from_and_to(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    _priced_bridge()
    client.post("/api/profiles/apply", json={"id": "conservative"})
    client.post("/api/profiles/apply", json={"id": "balanced"})
    logged = "\n".join(app_module.app_logger.tail())
    assert "Conservative -> Balanced" in logged
    assert "profile change:" in logged


def test_high_risk_preset_is_refused_without_explicit_confirmation(client):
    _priced_bridge()
    resp = client.post("/api/profiles/apply", json={"id": "high_risk"})
    assert resp.status_code == 400
    assert "34%" in resp.get_json()["confirmation"]
    assert app_module.state.get("active_profile") is None


def test_high_risk_preset_applies_once_confirmed(client):
    _priced_bridge()
    resp = client.post("/api/profiles/apply", json={"id": "high_risk", "confirmed": True})
    assert resp.status_code == 200
    assert app_module.state["active_profile"]["id"] == "high_risk"
    assert app_module.global_settings["max_lot"] == 50.0


def test_unknown_profile_is_rejected(client):
    assert client.post("/api/profiles/apply", json={"id": "moon"}).status_code == 400


# ---------- profile bounds are hard ----------

def test_a_setting_beyond_the_active_profiles_bound_is_refused_not_clamped(client):
    _priced_bridge()
    client.post("/api/profiles/apply", json={"id": "capital_preservation"})
    resp = client.post("/api/global_settings", json={"max_concurrent_trades": 10})
    body = resp.get_json()
    assert body["ok"] is False
    assert "max_concurrent_trades" in body["rejected"]
    assert app_module.global_settings["max_concurrent_trades"] == 1


def test_a_setting_inside_the_active_profiles_bound_is_accepted(client):
    _priced_bridge()
    client.post("/api/profiles/apply", json={"id": "balanced"})
    resp = client.post("/api/global_settings", json={"max_concurrent_trades": 2})
    assert resp.get_json()["ok"] is True
    assert app_module.global_settings["max_concurrent_trades"] == 2


def test_lowering_reward_risk_below_the_profile_floor_is_refused(client):
    _priced_bridge()
    client.post("/api/profiles/apply", json={"id": "capital_preservation"})
    body = client.post("/api/global_settings", json={"min_reward_risk": 0.5}).get_json()
    assert "min_reward_risk" in body["rejected"]
    assert app_module.global_settings["min_reward_risk"] == 2.0


def test_settings_are_unbounded_when_no_profile_is_active(client):
    app_module.state.pop("active_profile", None)
    resp = client.post("/api/global_settings", json={"max_concurrent_trades": 9})
    assert resp.get_json()["ok"] is True


# ---------- diagnostic findings carry a severity ----------

def test_an_auto_resolved_symbol_rename_does_not_report_trading_as_blocked(client):
    """The reported contradiction: the log said the symbol was resolved and traded, then said
    TRADING BLOCKED for the same rename one line later."""
    app_module.engine._last_diagnosis_at = 0.0
    app_module.bridge.diagnose_trading.return_value = [
        {"problem": "Your broker calls 'EURUSD' 'EURUSD#'.", "fix": "No action needed.",
         "severity": "info"},
    ]
    app_module.bridge.get_account_summary.return_value = {}
    body = client.get("/api/diagnose").get_json()
    assert body["ok"] is True
    assert body["blocking_count"] == 0
    assert body["info_count"] == 1


def test_a_real_blocker_still_reports_trading_as_blocked(client):
    app_module.engine._last_diagnosis_at = 0.0
    app_module.bridge.diagnose_trading.return_value = [
        {"problem": "Algo Trading is switched OFF.", "fix": "Turn it on.", "severity": "blocking"},
        {"problem": "Renamed symbol.", "fix": "Nothing to do.", "severity": "info"},
    ]
    app_module.bridge.get_account_summary.return_value = {}
    body = client.get("/api/diagnose").get_json()
    assert body["ok"] is False
    assert body["blocking_count"] == 1
    assert body["info_count"] == 1


def test_informational_findings_are_logged_at_info_not_as_trading_blocked(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    app_module.engine._last_diagnosis_at = 0.0
    app_module.bridge.diagnose_trading.return_value = [
        {"problem": "Your broker calls 'EURUSD' 'EURUSD#'.", "fix": "No action needed.",
         "severity": "info"},
    ]
    app_module.bridge.get_account_summary.return_value = {}
    client.get("/api/diagnose")
    logged = "\n".join(app_module.app_logger.tail())
    assert "TRADING BLOCKED" not in logged
    assert "Diagnostic note" in logged


# ---------- Auto mode ----------
# Auto is consulted per tick on the SNAPSHOT. These tests exercise that seam directly,
# because it is where "the profile's bounds are absolute" is actually enforced.


@pytest.fixture
def auto_client(client):
    """The client fixture leaves global_settings shared; Auto writes one key into it."""
    before = dict(app_module.global_settings)
    app_module.engine.reset_bar_gate()
    app_module._auto_history_cache.update({"at": 0.0, "stats": {}, "recent": []})
    yield client
    app_module.global_settings.clear()
    app_module.global_settings.update(before)
    app_module.engine.reset_bar_gate()


def _volatile_rates(n=120):
    closes = [1.10 + (i % 7) * 0.001 * (1 + i / n) for i in range(n)]
    return pd.DataFrame({"open": closes, "high": [c + 0.002 for c in closes],
                          "low": [c - 0.002 for c in closes], "close": closes,
                          "spread": [5] * n,
                          "time": [1_700_000_000 + i * 3600 for i in range(n)]})


def _deals(strategy_magic, count, profit):
    return [{"profit": profit, "magic": strategy_magic, "ticket": i} for i in range(count)]


def test_auto_mode_is_off_by_default(auto_client):
    body = auto_client.get("/api/auto_mode").get_json()
    assert body["enabled"] is False
    assert body["caveat"]
    assert body["min_trades"] == auto_mode.MIN_TRADES


def test_enabling_auto_mode_is_persisted_and_logged(auto_client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    resp = auto_client.post("/api/auto_mode", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.get_json()["enabled"] is True
    assert app_module.global_settings["auto_mode_enabled"] is True
    logged = "\n".join(app_module.app_logger.tail())
    assert "Auto mode ENABLED" in logged
    assert str(auto_mode.MIN_TRADES) in logged


def test_disabling_auto_mode_reports_the_off_decision_immediately(auto_client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    auto_client.post("/api/auto_mode", json={"enabled": True})
    body = auto_client.post("/api/auto_mode", json={"enabled": False}).get_json()
    assert body["enabled"] is False
    assert body["decision"]["enabled"] is False
    assert "Auto mode DISABLED" in "\n".join(app_module.app_logger.tail())


def test_why_no_trade_carries_autos_reasoning_alongside_the_gates(auto_client):
    app_module.bridge.get_rates.return_value = _volatile_rates()
    app_module.bridge.get_history_deals.return_value = []
    app_module.global_settings["auto_mode_enabled"] = True
    app_module._apply_auto_mode(app_module._snapshot_state())
    body = auto_client.get("/api/why_no_trade").get_json()
    assert body["auto"]["enabled"] is True
    assert body["auto"]["line"]
    assert body["auto"]["reason"]


def test_auto_never_pushes_risk_above_the_active_profile(auto_client):
    """Four losses in a row must shrink the tick's risk, never grow it, and never touch the
    stored setting -- the profile's number is the ceiling."""
    app_module.bridge.get_rates.return_value = _volatile_rates()
    app_module.bridge.get_history_deals.return_value = _deals(1001, 4, -50.0)
    app_module.global_settings["auto_mode_enabled"] = True
    app_module.global_settings["risk_percent"] = 0.5

    snap = app_module._snapshot_state()
    app_module._apply_auto_mode(snap)
    assert snap["global_settings"]["risk_percent"] < 0.5
    assert app_module.global_settings["risk_percent"] == 0.5  # stored setting untouched


def test_auto_off_leaves_the_snapshot_exactly_as_the_user_set_it(auto_client):
    app_module.global_settings["risk_percent"] = 0.5
    app_module.state["active_strategy"] = "smc"
    snap = app_module._snapshot_state()
    app_module._apply_auto_mode(snap)
    assert snap["global_settings"]["risk_percent"] == 0.5
    assert snap["active_strategy"] == "smc"
    assert app_module.engine.get_auto_decision()["enabled"] is False


def test_auto_overrides_the_traded_strategy_only_in_the_snapshot(auto_client):
    app_module.bridge.get_rates.return_value = _volatile_rates()
    # A large, healthy sample on smc only; trend is what the user selected.
    app_module.bridge.get_history_deals.return_value = _deals(1003, auto_mode.MIN_TRADES + 5, 25.0)
    app_module.global_settings["auto_mode_enabled"] = True
    app_module.state["active_strategy"] = "trend"

    snap = app_module._snapshot_state()
    app_module._apply_auto_mode(snap)
    decision = app_module.engine.get_auto_decision()
    if decision["strategy"]:  # only when the regime left smc eligible
        assert snap["active_strategy"] == decision["strategy"]
        assert app_module.state["active_strategy"] == "trend"
        # ...and the panel names what is really being traded, not the stored choice.
        assert app_module._traded_targets()[0]["strategy"] == decision["strategy"]


def test_an_unreadable_regime_leaves_the_strategy_alone(auto_client):
    app_module.bridge.get_rates.return_value = None
    app_module.bridge.get_history_deals.return_value = _deals(1003, 200, 25.0)
    app_module.global_settings["auto_mode_enabled"] = True
    app_module.state["active_strategy"] = "trend"

    snap = app_module._snapshot_state()
    app_module._apply_auto_mode(snap)
    assert snap["active_strategy"] == "trend"
    assert app_module.engine.get_auto_decision()["strategy"] is None


def test_the_auto_decision_line_is_logged_once_not_every_tick(auto_client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    app_module.bridge.get_rates.return_value = _volatile_rates()
    app_module.bridge.get_history_deals.return_value = []
    app_module.global_settings["auto_mode_enabled"] = True
    for _ in range(4):
        app_module._apply_auto_mode(app_module._snapshot_state())
    assert "\n".join(app_module.app_logger.tail()).count("Auto mode:") == 1


# ---------- account strip + history ----------

def test_account_endpoint_reports_the_live_account_and_open_pnl(client):
    app_module.bridge.get_account_info.return_value = {
        "connected": True, "login": 123, "server": "XM-Demo", "company": "XM",
        "currency": "USD", "balance": 5000.0, "equity": 5100.0, "margin_free": 4000.0,
        "trade_mode": "demo"}
    app_module.bridge.get_open_positions.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "type": "BUY", "volume": 0.1, "profit": 40.0},
        {"ticket": 2, "symbol": "EURUSD", "type": "SELL", "volume": 0.1, "profit": -15.0}]
    body = client.get("/api/account").get_json()
    assert body["trade_mode"] == "demo" and body["server"] == "XM-Demo"
    assert body["open_pnl"] == 25.0
    assert body["open_positions"] == 2


def _deal(ticket, t, profit, volume=0.1):
    return {"ticket": ticket, "symbol": "EURUSD", "time": t, "type": "BUY", "volume": volume,
            "price": 1.1, "profit": profit, "commission": -1.0, "swap": -0.5}


def test_history_totals_and_newest_first(client):
    app_module.bridge.get_history_rows.return_value = [_deal(1, 100, 10.0), _deal(2, 200, -4.0)]
    body = client.get("/api/history?period=month").get_json()
    assert [d["ticket"] for d in body["deals"]] == [2, 1]
    assert body["total"]["profit"] == 6.0
    assert body["total"]["volume"] == 0.2
    assert body["total"]["count"] == 2


def test_history_period_filter_picks_the_right_window(client):
    app_module.bridge.get_history_rows.return_value = []
    from datetime import datetime
    for period, days in (("week", 7), ("month", 30), ("3months", 90)):
        client.get(f"/api/history?period={period}")
        since = app_module.bridge.get_history_rows.call_args[0][0]
        assert round((datetime.now() - since).days) == days


def test_history_export_is_csv_with_a_header(client):
    app_module.bridge.get_history_rows.return_value = [_deal(1, 100, 10.0)]
    resp = client.get("/api/history/export")
    assert resp.mimetype == "text/csv"
    text = resp.get_data(as_text=True)
    assert text.splitlines()[0].startswith("time,symbol,type,volume,price,profit")
    assert "EURUSD" in text


def test_global_settings_get_returns_the_live_values(client):
    client.post("/api/global_settings", json={"slippage_points": 33})
    assert client.get("/api/global_settings").get_json()["slippage_points"] == 33


def test_kill_switch_lines_log_once_and_again_when_they_clear(client, tmp_path, monkeypatch):
    """~40 identical MAX DRAWDOWN lines in three minutes is what this prevents. The
    information must survive: fired once, cleared once."""
    monkeypatch.setattr(app_module.app_logger, "LOG_PATH", str(tmp_path / "app.log"))
    app_module.engine.reset_state_latches()
    app_module.state["peak_equity"] = 100_000.0
    app_module.state["peak_equity_login"] = 111
    app_module.bridge.get_account_login.return_value = 111
    app_module.bridge.get_history_deals.return_value = []
    app_module.bridge.get_open_positions.return_value = []

    app_module.bridge.get_account_equity.return_value = 80_000.0
    for _ in range(5):
        app_module._compute_risk_percents()
    lines = app_module.app_logger.tail()
    assert sum("MAX DRAWDOWN hit" in ln for ln in lines) == 1, "logged on every tick again"

    # Recovering above the limit must say so, exactly once.
    app_module.bridge.get_account_equity.return_value = 99_000.0
    for _ in range(5):
        app_module._compute_risk_percents()
    lines = app_module.app_logger.tail()
    assert sum("MAX DRAWDOWN cleared" in ln for ln in lines) == 1
    assert sum("MAX DRAWDOWN hit" in ln for ln in lines) == 1
