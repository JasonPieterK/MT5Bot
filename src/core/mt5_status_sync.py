"""Writes a lightweight status snapshot to MT5's shared Common Files folder so an
on-chart EA panel (mql5/MT5BotStatusPanel.mq5) can mirror this app's state without
any HTTP call or WebRequest allowlist. One-way and read-only from the EA's side --
the EA never places, modifies, or closes trades."""
import os
import time

STATUS_FILENAME = "mt5_bot_status.txt"


def get_common_files_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return os.path.join(appdata, "MetaQuotes", "Terminal", "Common", "Files")


def write_status_file(status, directory=None):
    directory = directory if directory is not None else get_common_files_dir()
    if not directory or not os.path.isdir(directory):
        return False
    path = os.path.join(directory, STATUS_FILENAME)
    lines = [f"{key}={value}" for key, value in status.items()]
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return True


def build_status(state, equity, open_position_count):
    return {
        "auto_enabled": 1 if state.get("auto_enabled") else 0,
        "watchlist_enabled": 1 if state.get("watchlist_enabled") else 0,
        "active_strategy": state.get("active_strategy", ""),
        "symbol": state.get("symbol", ""),
        "timeframe": state.get("timeframe", ""),
        "equity": round(equity, 2),
        "open_positions": open_position_count,
        "last_update_unix": int(time.time()),
    }
