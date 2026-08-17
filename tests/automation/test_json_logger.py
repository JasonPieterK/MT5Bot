import json
import os
import automation.json_logger as json_logger


def test_log_event_writes_json_line(tmp_path, monkeypatch):
    path = str(tmp_path / "events.jsonl")
    monkeypatch.setattr(json_logger, "LOG_PATH", path)
    json_logger.log_event("trade", {"symbol": "EURUSD", "signal": "BUY"})
    with open(path) as f:
        line = f.readline()
    parsed = json.loads(line)
    assert parsed["event"] == "trade"
    assert parsed["symbol"] == "EURUSD"


def test_rotate_when_over_max_bytes(tmp_path, monkeypatch):
    path = str(tmp_path / "events.jsonl")
    monkeypatch.setattr(json_logger, "LOG_PATH", path)
    monkeypatch.setattr(json_logger, "MAX_BYTES", 10)
    json_logger.log_event("a", {"x": 1})
    json_logger.log_event("b", {"x": 2})
    assert os.path.exists(path + ".1")
