"""peak_equity must belong to one account.

Real incident: the terminal was re-logged into a different account ($965) while
logs/app_state.json still held the previous account's peak ($5.32M). The drawdown
kill-switch read that as a 99.98% loss, blocked all trading and flattened positions
seven times. Nothing had actually gone wrong with the money.
"""
from unittest.mock import MagicMock

import pytest

import app as app_module


@pytest.fixture
def bridge(monkeypatch):
    b = MagicMock()
    b.get_history_deals.return_value = []
    b.get_open_positions.return_value = []
    monkeypatch.setattr(app_module, "bridge", b)
    app_module.state["peak_equity"] = None
    app_module.state["peak_equity_login"] = None
    yield b
    app_module.state["peak_equity"] = None
    app_module.state["peak_equity_login"] = None


def test_peak_follows_equity_up_on_one_account(bridge):
    bridge.get_account_login.return_value = 111
    bridge.get_account_equity.return_value = 10_000.0
    app_module._compute_risk_percents()
    bridge.get_account_equity.return_value = 12_000.0
    _, drawdown = app_module._compute_risk_percents()
    assert app_module.state["peak_equity"] == 12_000.0
    assert drawdown == 0.0


def test_real_drawdown_on_the_same_account_still_reported(bridge):
    bridge.get_account_login.return_value = 111
    bridge.get_account_equity.return_value = 10_000.0
    app_module._compute_risk_percents()
    bridge.get_account_equity.return_value = 6_000.0
    _, drawdown = app_module._compute_risk_percents()
    assert drawdown == pytest.approx(40.0)


def test_switching_account_resets_the_peak_instead_of_reporting_a_crash(bridge):
    bridge.get_account_login.return_value = 336655151
    bridge.get_account_equity.return_value = 5_324_069.72
    app_module._compute_risk_percents()

    bridge.get_account_login.return_value = 345821614
    bridge.get_account_equity.return_value = 965.48
    _, drawdown = app_module._compute_risk_percents()

    assert drawdown == 0.0, "a different account is not a 99.98% loss"
    assert app_module.state["peak_equity"] == 965.48
    assert app_module.state["peak_equity_login"] == 345821614


def test_disconnected_terminal_is_not_a_total_loss(bridge):
    """account_info() returns None when the terminal drops, and get_account_equity()
    reports 0.0 -- which must not read as a 100% drawdown and flatten the account."""
    bridge.get_account_login.return_value = 111
    bridge.get_account_equity.return_value = 10_000.0
    app_module._compute_risk_percents()

    bridge.get_account_equity.return_value = 0.0
    _, drawdown = app_module._compute_risk_percents()
    assert drawdown == 0.0
    assert app_module.state["peak_equity"] == 10_000.0, "peak must survive a dropout"


def test_unknown_login_does_not_wipe_the_peak(bridge):
    bridge.get_account_login.return_value = 111
    bridge.get_account_equity.return_value = 10_000.0
    app_module._compute_risk_percents()

    bridge.get_account_login.return_value = None  # terminal briefly unreadable
    bridge.get_account_equity.return_value = 9_000.0
    _, drawdown = app_module._compute_risk_percents()
    assert app_module.state["peak_equity"] == 10_000.0
    assert drawdown == pytest.approx(10.0)
