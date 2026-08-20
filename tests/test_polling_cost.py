"""The dashboard polls twice a second, so every wasted MT5 round-trip is 2/second.

/api/account fetched the open positions twice -- once to sum floating P&L and once to count
them -- for one number each. MT5 calls are IPC to the terminal, not free.
"""
from unittest.mock import MagicMock

import pytest

import app as app_module


@pytest.fixture
def client(monkeypatch):
    b = MagicMock()
    b.get_account_info.return_value = {"connected": True, "login": 1, "balance": 100.0,
                                        "equity": 100.0, "margin_free": 100.0,
                                        "currency": "USD", "server": "S", "company": "C",
                                        "trade_mode": "demo"}
    b.get_open_positions.return_value = [
        {"ticket": 1, "symbol": "GOLD.i#", "volume": 1.0, "profit": 5.0, "type": "BUY",
         "price_open": 4000.0, "sl": 0.0, "tp": 0.0},
        {"ticket": 2, "symbol": "GOLD.i#", "volume": 1.0, "profit": -2.0, "type": "SELL",
         "price_open": 4010.0, "sl": 0.0, "tp": 0.0}]
    b.get_account_equity.return_value = 100.0
    monkeypatch.setattr(app_module, "bridge", b)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client(), b


def test_account_reads_open_positions_once(client):
    c, b = client
    c.get("/api/account")
    assert b.get_open_positions.call_count == 1, (
        f"called {b.get_open_positions.call_count}x; each one is an IPC round-trip and this "
        f"endpoint runs twice a second")


def test_account_still_reports_both_numbers(client):
    c, b = client
    body = c.get("/api/account").get_json()
    assert body["open_pnl"] == pytest.approx(3.0)
    assert body["open_positions"] == 2


def test_status_reads_the_terminal_at_most_twice(client):
    c, b = client
    c.get("/api/status")
    total = b.get_open_positions.call_count + b.get_account_equity.call_count
    assert total <= 2, f"{total} terminal reads for one status poll"
