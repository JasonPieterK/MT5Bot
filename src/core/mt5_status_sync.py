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
    # equity <= 0 means the terminal isn't connected, not that the account is wiped out --
    # reporting a 100% drawdown there would paint the panel red for a connection blip.
    peak = max(float(state.get("peak_equity") or 0.0), equity)
    drawdown_percent = ((peak - equity) / peak * 100) if (peak > 0 and equity > 0) else 0.0
    return {
        # Kept as two fields for the EA's existing schema, but both derive from the one
        # trading_mode so they can never disagree.
        "auto_enabled": 1 if state.get("trading_mode") == "single" else 0,
        "watchlist_enabled": 1 if state.get("trading_mode") == "watchlist" else 0,
        # The mode verbatim, so the panel prints what the app actually is rather than
        # reconstructing it from the two booleans above.
        "trading_mode": state.get("trading_mode", "off"),
        "active_strategy": state.get("active_strategy", ""),
        "symbol": state.get("symbol", ""),
        "timeframe": state.get("timeframe", ""),
        "equity": round(equity, 2),
        # The one risk number worth a chart row, and free here: peak_equity is already
        # tracked in state by the drawdown kill-switch.
        "drawdown_percent": round(drawdown_percent, 2),
        "open_positions": open_position_count,
        "last_update_unix": int(time.time()),
    }
