import pytest
from unittest.mock import MagicMock
import app as app_module


@pytest.fixture
def client(monkeypatch):
    app_module.bridge = MagicMock()
    app_module.bridge.get_open_positions.return_value = []
    app_module.bridge.get_account_equity.return_value = 10000
    app_module.bridge.get_margin_level.return_value = 500.0
    app_module.state = {"active_strategy": "trend", "symbol": "EURUSD",
                         "timeframe": "M5", "auto_enabled": False}
    app_module.alert_rules.clear()
    app_module.triggered_alerts.clear()
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
