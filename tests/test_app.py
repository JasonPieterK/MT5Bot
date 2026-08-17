import pytest
from unittest.mock import MagicMock
import core.config as config
import app as app_module


@pytest.fixture
def client(monkeypatch):
    app_module.bridge = MagicMock()
    app_module.bridge.get_open_positions.return_value = []
    app_module.bridge.get_account_equity.return_value = 10000
    app_module.bridge.get_margin_level.return_value = 500.0
    app_module.state = config.new_state()
    app_module.alert_rules.clear()
    app_module.triggered_alerts.clear()
    app_module.watchlist.clear()
    app_module.manual_signals.clear()
    app_module.blackout_windows.clear()
    app_module.account_profiles.clear()
    app_module.app.config["TESTING"] = True
    yield app_module.app.test_client()
    app_module._stop_flag.set()


def test_get_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "positions" in body
    assert "auto_enabled" in body


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


def test_post_auto_toggle(client):
    resp = client.post("/api/auto", json={"enabled": True})
    assert resp.status_code == 200
    assert app_module.state["auto_enabled"] is True


def test_grid_hard_caps_not_settable_via_api(client):
    resp = client.post("/api/settings", json={"strategy": "grid", "settings": {"max_levels": 999}})
    assert resp.status_code == 200
    assert "max_levels" not in app_module.strategy_settings["grid"]


def test_index_serves_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_get_alerts_empty_initially(client):
    resp = client.get("/api/alerts")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_post_alert_creates_rule(client):
    resp = client.post("/api/alerts", json={"symbol": "EURUSD", "condition": "above", "price": 1.15})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["symbol"] == "EURUSD"
    assert "id" in body
    list_resp = client.get("/api/alerts")
    assert len(list_resp.get_json()) == 1


def test_delete_alert_removes_rule(client):
    created = client.post("/api/alerts", json={"symbol": "EURUSD", "condition": "above", "price": 1.15}).get_json()
    resp = client.delete(f"/api/alerts/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/alerts").get_json() == []


def test_ack_triggered_alert(client):
    app_module.triggered_alerts.append({"id": 99, "type": "price"})
    resp = client.post("/api/alerts/ack/99")
    assert resp.status_code == 200
    assert app_module.triggered_alerts == []


def test_journal_get_and_set(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.journal, "JOURNAL_PATH", str(tmp_path / "journal.json"))
    resp = client.post("/api/journal/555", json={"note": "watching for breakout"})
    assert resp.status_code == 200
    resp = client.get("/api/journal/555")
    assert resp.get_json()["note"] == "watching for breakout"


def test_analytics_endpoint(client):
    app_module.bridge.get_history_deals.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "profit": 10.0, "time": 1},
    ]
    resp = client.get("/api/analytics")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["win_rate"] == 100.0


def test_status_includes_triggered_alerts(client):
    app_module.triggered_alerts.clear()
    app_module.triggered_alerts.append({"id": 1, "type": "price"})
    resp = client.get("/api/status")
    assert resp.get_json()["triggered_alerts"] == [{"id": 1, "type": "price"}]


def test_watchlist_crud(client):
    resp = client.post("/api/watchlist", json={"symbol": "GBPUSD", "timeframe": "M5",
                                                 "strategy": "trend", "mode": "auto"})
    assert resp.status_code == 200
    entry = resp.get_json()
    assert entry["enabled"] is True
    list_resp = client.get("/api/watchlist")
    assert len(list_resp.get_json()) == 1
    del_resp = client.delete(f"/api/watchlist/{entry['id']}")
    assert del_resp.status_code == 200
    assert client.get("/api/watchlist").get_json() == []


def test_watchlist_toggle_enabled(client):
    entry = client.post("/api/watchlist", json={"symbol": "GBPUSD", "timeframe": "M5",
                                                  "strategy": "trend", "mode": "auto"}).get_json()
    resp = client.post(f"/api/watchlist/{entry['id']}/toggle", json={"enabled": False})
    assert resp.status_code == 200
    updated = client.get("/api/watchlist").get_json()[0]
    assert updated["enabled"] is False


def test_status_includes_watchlist_and_manual_signals(client):
    resp = client.get("/api/status")
    body = resp.get_json()
    assert "watchlist" in body
    assert "manual_signals" in body


def test_blackout_crud(client):
    resp = client.post("/api/blackouts", json={"start": "2026-09-05T12:25:00+00:00",
                                                 "end": "2026-09-05T12:35:00+00:00", "label": "NFP"})
    assert resp.status_code == 200
    entry = resp.get_json()
    list_resp = client.get("/api/blackouts")
    assert len(list_resp.get_json()) == 1
    client.delete(f"/api/blackouts/{entry['id']}")
    assert client.get("/api/blackouts").get_json() == []


def test_backtest_endpoint(client):
    import pandas as pd
    price = 1.10
    rows = []
    for i in range(40):
        price += 0.0008 if i % 2 == 0 else -0.0006
        rows.append({"open": price, "high": price + 0.0005, "low": price - 0.0005, "close": price})
    app_module.bridge.get_rates.return_value = pd.DataFrame(rows)
    resp = client.get("/api/backtest?symbol=EURUSD&timeframe=M5&strategy=trend&bars=40&initial_equity=10000")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "stats" in body


def test_auto_blocked_when_locked_and_wrong_passcode(client):
    app_module.state["lock_enabled"] = True
    app_module.state["lock_passcode"] = "1234"
    resp = client.post("/api/auto", json={"enabled": True, "passcode": "wrong"})
    assert resp.status_code == 403
    assert app_module.state["auto_enabled"] is False


def test_auto_allowed_when_locked_and_correct_passcode(client):
    app_module.state["lock_enabled"] = True
    app_module.state["lock_passcode"] = "1234"
    resp = client.post("/api/auto", json={"enabled": True, "passcode": "1234"})
    assert resp.status_code == 200
    assert app_module.state["auto_enabled"] is True


def test_auto_off_never_blocked_by_lock(client):
    app_module.state["lock_enabled"] = True
    app_module.state["lock_passcode"] = "1234"
    app_module.state["auto_enabled"] = True
    resp = client.post("/api/auto", json={"enabled": False})
    assert resp.status_code == 200
    assert app_module.state["auto_enabled"] is False


def test_post_lock_sets_state(client):
    resp = client.post("/api/lock", json={"enabled": True, "passcode": "9999"})
    assert resp.status_code == 200
    assert app_module.state["lock_enabled"] is True
    assert app_module.state["lock_passcode"] == "9999"


def test_watchlist_mode_toggle_respects_lock(client):
    app_module.state["lock_enabled"] = True
    app_module.state["lock_passcode"] = "1234"
    resp = client.post("/api/watchlist_mode", json={"enabled": True, "passcode": "wrong"})
    assert resp.status_code == 403
    resp = client.post("/api/watchlist_mode", json={"enabled": True, "passcode": "1234"})
    assert resp.status_code == 200
    assert app_module.state["watchlist_enabled"] is True


def test_analytics_export_returns_csv(client):
    app_module.bridge.get_history_deals.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "profit": 10.0, "time": 1},
    ]
    resp = client.get("/api/analytics/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type
    assert "ticket" in resp.get_data(as_text=True)


def test_account_crud(client):
    resp = client.post("/api/accounts", json={"name": "Demo", "path": "C:/MT5/terminal64.exe",
                                                "login": 12345, "password": "pw", "server": "Broker-Demo"})
    assert resp.status_code == 200
    acc = resp.get_json()
    assert "password" not in acc
    list_resp = client.get("/api/accounts")
    assert len(list_resp.get_json()) == 1
    client.delete(f"/api/accounts/{acc['id']}")
    assert client.get("/api/accounts").get_json() == []


def test_connect_account_calls_bridge_connect(client):
    created = client.post("/api/accounts", json={"name": "Demo", "path": "C:/MT5/terminal64.exe",
                                                   "login": 12345, "password": "pw", "server": "Broker-Demo"}).get_json()
    app_module.bridge.connect.return_value = True
    resp = client.post(f"/api/accounts/{created['id']}/connect")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    app_module.bridge.connect.assert_called_once_with(
        path="C:/MT5/terminal64.exe", login=12345, password="pw", server="Broker-Demo")


def test_save_state_endpoint(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.persistence, "STATE_PATH", str(tmp_path / "app_state.json"))
    resp = client.post("/api/state/save")
    assert resp.status_code == 200
    assert app_module.persistence.load_all() is not None


def test_analytics_per_strategy_endpoint(client):
    app_module.bridge.get_history_deals.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "profit": 10.0, "time": 1, "magic": 1001},
        {"ticket": 2, "symbol": "EURUSD", "profit": 20.0, "time": 2, "magic": 1002},
    ]
    resp = client.get("/api/analytics/per_strategy")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"trend", "scalping"}


def test_backtest_sweep_endpoint(client):
    import pandas as pd
    price = 1.10
    rows = []
    for i in range(40):
        price += 0.0008 if i % 2 == 0 else -0.0006
        rows.append({"open": price, "high": price + 0.0005, "low": price - 0.0005, "close": price})
    app_module.bridge.get_rates.return_value = pd.DataFrame(rows)
    resp = client.post("/api/backtest/sweep", json={
        "symbol": "EURUSD", "timeframe": "M5", "strategy": "trend", "bars": 40,
        "initial_equity": 10000, "param_grid": {"fast_period": [5, 9]},
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 2
    assert "params" in body[0]


def test_ml_train_needs_enough_trades(client):
    app_module.bridge.get_history_deals.return_value = [
        {"ticket": 1, "symbol": "EURUSD", "profit": 10.0, "time": 1700000000, "magic": 1001},
    ]
    resp = client.post("/api/ml/train")
    assert resp.status_code == 400


def test_ml_train_succeeds_with_enough_trades(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.ml_filter, "WEIGHTS_PATH", str(tmp_path / "ml_weights.json"))
    deals = [{"ticket": i, "symbol": "EURUSD", "profit": 10.0 if i % 2 == 0 else -5.0,
              "time": 1700000000 + i * 1000, "magic": 1001} for i in range(12)]
    app_module.bridge.get_history_deals.return_value = deals
    resp = client.post("/api/ml/train")
    assert resp.status_code == 200
    assert resp.get_json()["trained_on"] == 12
    assert app_module.ml_filter.load_weights() is not None


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
