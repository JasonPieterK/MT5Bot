"""Structured JSON-lines event log, additive to the existing flat CSV logs. Rotates
by file size so a long-running bot doesn't grow one unbounded file."""
import json
import os

LOG_PATH = os.path.join("logs", "events.jsonl")
MAX_BYTES = 5 * 1024 * 1024


def _rotate_if_needed():
    if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) >= MAX_BYTES:
        rotated = LOG_PATH + ".1"
        if os.path.exists(rotated):
            os.remove(rotated)
        os.rename(LOG_PATH, rotated)


def log_event(event_type, data):
    os.makedirs("logs", exist_ok=True)
    _rotate_if_needed()
    row = {"event": event_type, **data}
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(row) + "\n")
