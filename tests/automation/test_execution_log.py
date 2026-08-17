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


def test_summarize_computes_avg_latency_and_requote_rate():
    rows = [
        {"symbol": "EURUSD", "latency_ms": "100", "requoted": "False"},
        {"symbol": "EURUSD", "latency_ms": "200", "requoted": "True"},
    ]
    summary = execution_log.summarize(rows)
    assert summary["EURUSD"]["count"] == 2
    assert summary["EURUSD"]["avg_latency_ms"] == 150.0
    assert summary["EURUSD"]["requote_rate_percent"] == 50.0


def test_summarize_separates_symbols():
    rows = [
        {"symbol": "EURUSD", "latency_ms": "100", "requoted": "False"},
        {"symbol": "GBPUSD", "latency_ms": "50", "requoted": "False"},
    ]
    summary = execution_log.summarize(rows)
    assert set(summary.keys()) == {"EURUSD", "GBPUSD"}
