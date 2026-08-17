"""Per-ticket trade notes, persisted to a JSON file so they survive a browser cache clear."""
import json
import os

JOURNAL_PATH = os.path.join("logs", "journal.json")


def _load():
    if not os.path.exists(JOURNAL_PATH):
        return {}
    with open(JOURNAL_PATH, "r") as f:
        return json.load(f)


def _save(data):
    os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)
    with open(JOURNAL_PATH, "w") as f:
        json.dump(data, f)


def get_note(ticket):
    return _load().get(str(ticket), "")


def set_note(ticket, text):
    data = _load()
    data[str(ticket)] = text
    _save(data)
