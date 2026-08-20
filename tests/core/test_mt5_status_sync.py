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
    state = {"trading_mode": "single", "active_strategy": "trend",
              "symbol": "EURUSD", "timeframe": "M5"}
    status = mt5_status_sync.build_status(state, equity=10432.567, open_position_count=2)
    assert status["auto_enabled"] == 1
    assert status["watchlist_enabled"] == 0
    assert status["active_strategy"] == "trend"
    assert status["equity"] == 10432.57
    assert status["open_positions"] == 2
    assert status["last_update_unix"] > 0


def test_build_status_watchlist_mode_sets_only_watchlist_flag():
    state = {"trading_mode": "watchlist", "active_strategy": "trend", "symbol": "EURUSD",
              "timeframe": "M5"}
    status = mt5_status_sync.build_status(state, equity=100.0, open_position_count=0)
    assert status["auto_enabled"] == 0
    assert status["watchlist_enabled"] == 1


def test_build_status_reports_trading_mode_verbatim():
    status = mt5_status_sync.build_status({"trading_mode": "watchlist"}, equity=100.0,
                                           open_position_count=0)
    assert status["trading_mode"] == "watchlist"
    assert mt5_status_sync.build_status({}, 100.0, 0)["trading_mode"] == "off"


def test_build_status_drawdown_from_peak_equity():
    status = mt5_status_sync.build_status({"peak_equity": 1000.0}, equity=950.0,
                                           open_position_count=0)
    assert status["drawdown_percent"] == 5.0


def test_build_status_drawdown_zero_at_peak_and_when_disconnected():
    at_peak = mt5_status_sync.build_status({"peak_equity": 900.0}, equity=1000.0,
                                            open_position_count=0)
    assert at_peak["drawdown_percent"] == 0.0
    # equity 0 means "terminal not connected", which must not read as a 100% drawdown.
    disconnected = mt5_status_sync.build_status({"peak_equity": 1000.0}, equity=0.0,
                                                 open_position_count=0)
    assert disconnected["drawdown_percent"] == 0.0
