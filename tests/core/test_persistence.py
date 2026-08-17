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
