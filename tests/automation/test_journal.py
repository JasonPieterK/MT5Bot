import automation.journal as journal


def test_set_and_get_note_round_trip(tmp_path, monkeypatch):
    path = str(tmp_path / "journal.json")
    monkeypatch.setattr(journal, "JOURNAL_PATH", path)
    journal.set_note(12345, "watch this one, entered on news spike")
    assert journal.get_note(12345) == "watch this one, entered on news spike"


def test_get_note_returns_empty_string_when_missing(tmp_path, monkeypatch):
    path = str(tmp_path / "journal.json")
    monkeypatch.setattr(journal, "JOURNAL_PATH", path)
    assert journal.get_note(99999) == ""


def test_set_note_overwrites_existing(tmp_path, monkeypatch):
    path = str(tmp_path / "journal.json")
    monkeypatch.setattr(journal, "JOURNAL_PATH", path)
    journal.set_note(1, "first note")
    journal.set_note(1, "updated note")
    assert journal.get_note(1) == "updated note"


def test_multiple_tickets_independent(tmp_path, monkeypatch):
    path = str(tmp_path / "journal.json")
    monkeypatch.setattr(journal, "JOURNAL_PATH", path)
    journal.set_note(1, "note one")
    journal.set_note(2, "note two")
    assert journal.get_note(1) == "note one"
    assert journal.get_note(2) == "note two"
