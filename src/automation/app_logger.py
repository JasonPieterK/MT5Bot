"""Human-readable application log — one plain-English line per event. This is the
log a user reads to figure out what happened; logs/events.jsonl (json_logger.py)
is the machine-readable twin of trade events specifically. This one covers
everything: connection state, trading toggles, order outcomes, filter kill-switches,
account actions, and every caught error."""
import datetime
import os

LOG_PATH = os.path.join("logs", "app.log")
MAX_BYTES = 5 * 1024 * 1024


def _rotate_if_needed():
    if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) >= MAX_BYTES:
        rotated = LOG_PATH + ".1"
        if os.path.exists(rotated):
            os.remove(rotated)
        os.rename(LOG_PATH, rotated)


def _write(level, message):
    directory = os.path.dirname(LOG_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    _rotate_if_needed()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {level:<7} | {message}\n")


def info(message):
    _write("INFO", message)


def warning(message):
    _write("WARNING", message)


def error(message):
    _write("ERROR", message)


def tail(max_lines=200):
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-max_lines:]]
