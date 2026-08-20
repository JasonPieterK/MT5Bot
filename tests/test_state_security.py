"""Write-throttling and shared-state locking around persistence.

The password-at-rest tests that used to live here went with the Accounts feature: the app
stores no credentials at all now, so there is nothing to encrypt or leak.
"""
import json
import os
import threading

import pytest


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    import app as app_module
    monkeypatch.setattr(app_module.persistence, "STATE_PATH", str(tmp_path / "app_state.json"))
    app_module._state_dirty = True
    return app_module


def _written(app_module):
    with open(app_module.persistence.STATE_PATH) as f:
        return json.load(f)


def test_no_credentials_are_persisted(app_module):
    app_module._save_persisted_state(force=True)
    assert set(_written(app_module)) == {"state", "strategy_settings", "global_settings"}


def test_unchanged_state_is_not_rewritten(app_module):
    app_module._save_persisted_state(force=True)
    stamp = os.stat(app_module.persistence.STATE_PATH).st_mtime_ns
    app_module._save_persisted_state()  # nothing changed since the last write
    assert os.stat(app_module.persistence.STATE_PATH).st_mtime_ns == stamp


def test_changed_state_is_rewritten(app_module):
    app_module._save_persisted_state(force=True)
    previous = app_module.global_settings["slippage_points"]
    app_module.global_settings["slippage_points"] = previous + 7
    app_module._mark_state_dirty()
    app_module._save_persisted_state()
    try:
        assert _written(app_module)["global_settings"]["slippage_points"] == previous + 7
    finally:
        app_module.global_settings["slippage_points"] = previous


def test_engine_snapshot_is_internally_consistent(app_module):
    """The tick must not read symbol from one moment and strategy from another -- that is
    how a XAUUSD selection ended up placing EURUSD orders."""
    stop = threading.Event()

    def flip():
        while not stop.is_set():
            with app_module.state_lock:
                app_module.state["symbol"] = "XAUUSD"
                app_module.state["active_strategy"] = "scalping"
            with app_module.state_lock:
                app_module.state["symbol"] = "EURUSD"
                app_module.state["active_strategy"] = "trend"

    t = threading.Thread(target=flip, daemon=True)
    t.start()
    try:
        for _ in range(400):
            snap = app_module._snapshot_state()
            pair = (snap["symbol"], snap["active_strategy"])
            assert pair in (("XAUUSD", "scalping"), ("EURUSD", "trend")), pair
    finally:
        stop.set()
        t.join(timeout=2)
