"""Save/restore app state (settings, watchlist, alert rules, blackout windows) to a
local JSON file so a restart doesn't lose configuration. Open positions themselves
live in MT5, not here — only the bot's own config is persisted."""
import json
import os
import time

import automation.app_logger as app_logger

STATE_PATH = os.path.join("logs", "app_state.json")


def save_all(snapshot):
    """Atomic: write a temp file in the same directory, fsync it, then os.replace onto the
    target. A crash mid-write used to leave truncated JSON that made the app fail to boot."""
    directory = os.path.dirname(STATE_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = STATE_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(snapshot, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, STATE_PATH)


def _set_aside_corrupt_file():
    """Move the unreadable file out of the way instead of deleting it — it is the user's
    only copy of their settings and accounts, and it may still be recoverable by hand."""
    aside = f"{STATE_PATH}.corrupt.{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        os.replace(STATE_PATH, aside)
    except OSError as exc:
        app_logger.error(f"Could not set the damaged settings file aside: {exc}")
        return None
    return aside


def load_all():
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        aside = _set_aside_corrupt_file()
        app_logger.error(
            f"Your saved settings file ({STATE_PATH}) is damaged and could not be read: {exc}. "
            f"Starting from defaults." +
            (f" The damaged file has been kept as {aside} in case it is needed." if aside else ""))
        return None
