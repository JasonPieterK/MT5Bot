import os
import core.mt5_status_sync as mt5_status_sync


def test_write_status_file_writes_key_value_lines(tmp_path):
    ok = mt5_status_sync.write_status_file({"auto_enabled": 1, "symbol": "EURUSD"}, directory=str(tmp_path))
    assert ok is True
    path = tmp_path / mt5_status_sync.STATUS_FILENAME
    content = path.read_text()
    assert "auto_enabled=1" in content
    assert "symbol=EURUSD" in content


def test_write_status_file_returns_false_when_dir_missing(tmp_path):
    missing = str(tmp_path / "does_not_exist")
    ok = mt5_status_sync.write_status_file({"auto_enabled": 0}, directory=missing)
    assert ok is False


def test_write_status_file_returns_false_when_no_appdata(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    ok = mt5_status_sync.write_status_file({"auto_enabled": 0})
    assert ok is False


def test_build_status_shape():
    state = {"auto_enabled": True, "watchlist_enabled": False, "active_strategy": "trend",
              "symbol": "EURUSD", "timeframe": "M5"}
    status = mt5_status_sync.build_status(state, equity=10432.567, open_position_count=2)
    assert status["auto_enabled"] == 1
    assert status["watchlist_enabled"] == 0
    assert status["active_strategy"] == "trend"
    assert status["equity"] == 10432.57
    assert status["open_positions"] == 2
    assert status["last_update_unix"] > 0
