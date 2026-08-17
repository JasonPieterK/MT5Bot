import pytest
from unittest.mock import MagicMock
import app as app_module


@pytest.fixture
def client(monkeypatch):
    app_module.bridge = MagicMock()
    app_module.bridge.get_open_positions.return_value = []
    app_module.bridge.get_account_equity.return_value = 10000
    app_module.state = {"active_strategy": "trend", "symbol": "EURUSD",
                         "timeframe": "M5", "auto_enabled": False}
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
