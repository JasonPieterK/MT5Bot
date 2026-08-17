"""Save/restore app state (settings, watchlist, alert rules, blackout windows) to a
local JSON file so a restart doesn't lose configuration. Open positions themselves
live in MT5, not here — only the bot's own config is persisted."""
import json
import os

STATE_PATH = os.path.join("logs", "app_state.json")


def save_all(snapshot):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(snapshot, f)


def load_all():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, "r") as f:
        return json.load(f)
