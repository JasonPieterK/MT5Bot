"""The dashboard must show every open position, and Close all must close every one.

Both read the account through a filter on the header symbol. Proven live: with one GOLD.i#
position open and the header set to EURUSD#, /api/status returned 0 positions while
/api/account reported 1 open -- the table looked stale while the counter was right.

Close all was the dangerous half: it closed only the header symbol's positions and reported
success, so the user could believe the account was flat while trades were still running.
"""
from unittest.mock import MagicMock

import pytest

import app as app_module


def _pos(ticket, symbol, profit=0.0):
    return {"ticket": ticket, "symbol": symbol, "volume": 0.01, "profit": profit,
            "type": "BUY", "price_open": 1.0, "sl": 0.0, "tp": 0.0}


ALL = [_pos(1, "GOLD.i#", 1.01), _pos(2, "EURUSD#", -0.5), _pos(3, "GBPUSD#", 2.0)]


@pytest.fixture
def client(monkeypatch):
    b = MagicMock()
    # The bridge filters when given a symbol -- mirror that faithfully.
    b.get_open_positions.side_effect = lambda sym=None: (
        [p for p in ALL if p["symbol"] == sym] if sym else list(ALL))
    b.get_account_equity.return_value = 10_000.0
    b.get_account_info.return_value = {"connected": True, "login": 1, "balance": 10_000.0,
                                        "equity": 10_000.0, "margin_free": 9_000.0,
                                        "currency": "USD", "server": "S", "company": "C",
                                        "trade_mode": "demo"}
    b.close_position.return_value = (True, 10009)
    monkeypatch.setattr(app_module, "bridge", b)
    app_module.state["symbol"] = "EURUSD#"
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client(), b


def test_status_lists_every_open_position_not_just_the_header_symbol(client):
    c, b = client
    positions = c.get("/api/status").get_json()["positions"]
    assert len(positions) == 3, "the table must show the whole account"
    assert {p["symbol"] for p in positions} == {"GOLD.i#", "EURUSD#", "GBPUSD#"}


def test_the_table_and_the_open_counter_agree(client):
    c, b = client
    table = len(c.get("/api/status").get_json()["positions"])
    counter = c.get("/api/account").get_json()["open_positions"]
    assert table == counter, "the table and the account strip must not disagree"


def test_close_all_closes_every_symbol(client):
    c, b = client
    c.post("/api/close_all")
    closed = {call.args[1] for call in b.close_position.call_args_list}
    assert closed == {"GOLD.i#", "EURUSD#", "GBPUSD#"}, (
        "a button called Close all must not leave other symbols open")


def test_close_all_reports_how_many_it_closed(client):
    c, b = client
    body = c.post("/api/close_all").get_json()
    assert body.get("closed") == 3
