"""Closing one open position from the dashboard.

This is all that remains of the old manual-trading surface: placing orders by hand was
removed, but closing a position was kept deliberately. It is a safety exit -- without it
there is no way to shut a single trade from the app, only Close All.
"""
import pytest
from unittest.mock import MagicMock

import core.config as config
import app as app_module


@pytest.fixture
def client(monkeypatch):
    app_module.bridge = MagicMock()
    app_module.bridge.get_open_positions.return_value = []
    app_module.bridge.get_account_equity.return_value = 10000
    app_module.state = config.new_state()
    app_module.app.config["TESTING"] = True
    yield app_module.app.test_client()
    app_module._stop_flag.set()


def test_close_position_closes_that_ticket(client):
    app_module.bridge.close_position_by_ticket.return_value = (True, 10009)
    resp = client.post("/api/manual/position/555/close")
    assert resp.get_json()["ok"] is True
    app_module.bridge.close_position_by_ticket.assert_called_once()
    assert app_module.bridge.close_position_by_ticket.call_args[0][0] == 555


def test_a_broker_refusal_is_reported_not_swallowed(client):
    app_module.bridge.close_position_by_ticket.return_value = (False, 10018)
    body = client.post("/api/manual/position/555/close").get_json()
    assert body["ok"] is False
    assert body["retcode"] == 10018


def test_placing_orders_by_hand_is_gone(client):
    """The BUY/SELL panel was removed; its route must not linger."""
    assert client.post("/api/manual/order",
                        json={"symbol": "EURUSD", "direction": "buy", "volume": 0.1}
                        ).status_code == 404
