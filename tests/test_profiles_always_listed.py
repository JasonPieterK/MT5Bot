"""The preset dropdown must never come up empty.

/api/profiles prices every preset against the live account so the real risk is visible
before applying. That pricing reads MT5. When the terminal hiccupped the whole route 500'd,
and the dashboard's `catch (e) { return; }` left the <select> empty, unexplained and never
retried -- the user saw a blank Preset box with no way to know why.

Presets are static data. They must always list, priced if possible, unpriced if not.
"""
from unittest.mock import MagicMock

import pytest

import app as app_module
import core.profiles as profiles


@pytest.fixture
def client(monkeypatch):
    b = MagicMock()
    b.get_open_positions.return_value = []
    b.get_account_equity.return_value = 100_000.0
    b.resolve_symbol.side_effect = lambda n: (n, None)
    b.get_symbol_volume_limits.return_value = (0.01, 50.0, 0.01)
    monkeypatch.setattr(app_module, "bridge", b)
    # A working terminal: real numbers, not MagicMocks, so the presets actually price.
    monkeypatch.setattr(app_module.engine, "risk_reality",
                        lambda *a, **k: {"equity": 100_000.0, "per_lot": 100.0})
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client(), b


def test_presets_list_when_mt5_pricing_works(client):
    c, b = client
    body = c.get("/api/profiles").get_json()
    assert len(body["presets"]) == len(profiles.PRESETS)


def test_presets_still_list_when_the_terminal_raises(client):
    c, b = client
    b.resolve_symbol.side_effect = ConnectionError("terminal gone")
    resp = c.get("/api/profiles")
    assert resp.status_code == 200, "a broker hiccup must not blank the preset list"
    body = resp.get_json()
    assert len(body["presets"]) == len(profiles.PRESETS)
    assert body.get("priced") is False


def test_presets_still_list_when_risk_pricing_fails(client):
    c, b = client
    b.get_symbol_volume_limits.side_effect = RuntimeError("ipc failed")
    resp = c.get("/api/profiles")
    assert resp.status_code == 200
    assert len(resp.get_json()["presets"]) == len(profiles.PRESETS)


def test_response_says_whether_the_figures_are_priced(client):
    c, b = client
    assert c.get("/api/profiles").get_json()["priced"] is True
    monkeypatch_target = app_module.engine
    b.resolve_symbol.side_effect = OSError("pipe closed")
    assert c.get("/api/profiles").get_json()["priced"] is False
