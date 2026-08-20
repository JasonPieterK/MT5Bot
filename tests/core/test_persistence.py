import json
import os

import core.persistence as persistence


def test_load_all_returns_none_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "STATE_PATH", str(tmp_path / "app_state.json"))
    assert persistence.load_all() is None


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "STATE_PATH", str(tmp_path / "app_state.json"))
    snapshot = {"state": {"symbol": "EURUSD"}, "watchlist": [{"id": 1}]}
    persistence.save_all(snapshot)
    loaded = persistence.load_all()
    assert loaded == snapshot


def test_save_overwrites_previous(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "STATE_PATH", str(tmp_path / "app_state.json"))
    persistence.save_all({"a": 1})
    persistence.save_all({"a": 2})
    assert persistence.load_all() == {"a": 2}


def test_save_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "STATE_PATH", str(tmp_path / "app_state.json"))
    persistence.save_all({"a": 1})
    assert os.listdir(tmp_path) == ["app_state.json"]


def test_save_never_truncates_the_live_file(tmp_path, monkeypatch):
    """The write goes to a temp file and is os.replace'd in, so a crash mid-write can
    never leave a half-written app_state.json behind."""
    path = tmp_path / "app_state.json"
    monkeypatch.setattr(persistence, "STATE_PATH", str(path))
    persistence.save_all({"a": 1})

    real_dump = json.dump

    def exploding_dump(obj, fp, **kwargs):
        real_dump(obj, fp, **kwargs)
        raise OSError("disk full")

    monkeypatch.setattr(persistence.json, "dump", exploding_dump)
    try:
        persistence.save_all({"a": 2})
    except OSError:
        pass
    assert persistence.load_all() == {"a": 1}


def test_corrupt_json_does_not_raise_and_preserves_the_bad_file(tmp_path, monkeypatch):
    path = tmp_path / "app_state.json"
    monkeypatch.setattr(persistence, "STATE_PATH", str(path))
    path.write_text('{"state": {"symbol": "EUR')  # truncated mid-write

    assert persistence.load_all() is None
    assert not path.exists()
    saved_aside = [p for p in os.listdir(tmp_path) if ".corrupt" in p]
    assert len(saved_aside) == 1
    assert (tmp_path / saved_aside[0]).read_text().startswith('{"state"')
