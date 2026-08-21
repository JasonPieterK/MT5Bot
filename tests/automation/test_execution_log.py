import os
import automation.execution_log as execution_log


def test_log_execution_writes_header_and_row(tmp_path, monkeypatch):
    path = str(tmp_path / "execution.csv")
    monkeypatch.setattr(execution_log, "LOG_PATH", path)
    execution_log.log_execution("EURUSD", 123.456, 10009, False)
    with open(path) as f:
        lines = f.read().splitlines()
    assert lines[0] == "symbol,latency_ms,retcode,requoted"
    assert lines[1] == "EURUSD,123.5,10009,False"


