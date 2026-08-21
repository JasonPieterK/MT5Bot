"""A state file that parses as JSON but is the wrong SHAPE must not stop the app booting.

load_all() guarded against unparseable JSON, but returned whatever it found otherwise -- a
list, a string, a number. _load_persisted_state() then calls .get() on it, and it runs at
import time of app.py, so `import app` died with AttributeError before Flask existed. The
app simply would not start, and the corrupt-file recovery never fired because the JSON was
perfectly valid.
"""
import json
import os

import pytest

import core.persistence as persistence


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    p = str(tmp_path / "app_state.json")
    monkeypatch.setattr(persistence, "STATE_PATH", p)
    return p


@pytest.mark.parametrize("content", ["[1,2,3]", '"hello"', "42", "true"])
def test_wrong_shape_is_treated_as_no_state(state_path, content):
    open(state_path, "w").write(content)
    assert persistence.load_all() is None, f"{content} should not be handed back as settings"


@pytest.mark.parametrize("content", ["[1,2,3]", '"hello"'])
def test_wrong_shape_file_is_preserved_not_destroyed(state_path, content):
    open(state_path, "w").write(content)
    persistence.load_all()
    aside = [f for f in os.listdir(os.path.dirname(state_path)) if "corrupt" in f]
    assert aside, "the user's file must be kept, it may be recoverable by hand"


def test_a_real_state_file_still_loads(state_path):
    persistence.save_all({"state": {"symbol": "EURUSD#"}, "global_settings": {"risk_percent": 1.0}})
    loaded = persistence.load_all()
    assert loaded["state"]["symbol"] == "EURUSD#"


def test_null_json_is_no_state(state_path):
    open(state_path, "w").write("null")
    assert persistence.load_all() is None
