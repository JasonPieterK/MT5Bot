"""Manual news/session blackout windows. No live economic-calendar data source is
wired up (the MetaTrader5 package has no calendar endpoint) — windows are user-entered."""
from datetime import datetime


def is_blackout_active(now, blackout_windows):
    for window in blackout_windows:
        start = datetime.fromisoformat(window["start"])
        end = datetime.fromisoformat(window["end"])
        if start <= now <= end:
            return True
    return False
