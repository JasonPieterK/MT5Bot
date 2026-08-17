import os
import automation.app_logger as app_logger


def test_info_writes_readable_line(tmp_path, monkeypatch):
    path = str(tmp_path / "app.log")
    monkeypatch.setattr(app_logger, "LOG_PATH", path)
    app_logger.info("Auto-trading enabled by user")
    lines = open(path, encoding="utf-8").readlines()
    assert len(lines) == 1
    assert "INFO" in lines[0]
    assert "Auto-trading enabled by user" in lines[0]
    # timestamp looks like YYYY-MM-DD HH:MM:SS at the start of the line
    assert lines[0][:4].isdigit()


def test_warning_and_error_levels(tmp_path, monkeypatch):
    path = str(tmp_path / "app.log")
    monkeypatch.setattr(app_logger, "LOG_PATH", path)
    app_logger.warning("ML training skipped: only 4 trades, need 10")
    app_logger.error("MT5 connection lost")
    lines = open(path, encoding="utf-8").readlines()
    assert "WARNING" in lines[0]
    assert "ERROR" in lines[1]


def test_tail_returns_last_n_lines(tmp_path, monkeypatch):
    path = str(tmp_path / "app.log")
    monkeypatch.setattr(app_logger, "LOG_PATH", path)
    for i in range(10):
        app_logger.info(f"event {i}")
    result = app_logger.tail(max_lines=3)
    assert len(result) == 3
    assert "event 9" in result[-1]
    assert "event 7" in result[0]


def test_tail_returns_empty_list_when_no_file(tmp_path, monkeypatch):
    path = str(tmp_path / "does_not_exist.log")
    monkeypatch.setattr(app_logger, "LOG_PATH", path)
    assert app_logger.tail() == []


def test_rotates_when_over_max_bytes(tmp_path, monkeypatch):
    path = str(tmp_path / "app.log")
    monkeypatch.setattr(app_logger, "LOG_PATH", path)
    monkeypatch.setattr(app_logger, "MAX_BYTES", 10)
    app_logger.info("first")
    app_logger.info("second")
    assert os.path.exists(path + ".1")
