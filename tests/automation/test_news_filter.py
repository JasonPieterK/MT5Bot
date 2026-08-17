from datetime import datetime, timezone
import automation.news_filter as news_filter


def test_inside_window_is_blackout():
    windows = [{"id": 1, "start": "2026-09-05T12:25:00+00:00",
                "end": "2026-09-05T12:35:00+00:00", "label": "NFP"}]
    now = datetime(2026, 9, 5, 12, 30, tzinfo=timezone.utc)
    assert news_filter.is_blackout_active(now, windows) is True


def test_outside_window_is_not_blackout():
    windows = [{"id": 1, "start": "2026-09-05T12:25:00+00:00",
                "end": "2026-09-05T12:35:00+00:00", "label": "NFP"}]
    now = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)
    assert news_filter.is_blackout_active(now, windows) is False


def test_boundary_start_is_inclusive():
    windows = [{"id": 1, "start": "2026-09-05T12:25:00+00:00",
                "end": "2026-09-05T12:35:00+00:00", "label": "NFP"}]
    now = datetime(2026, 9, 5, 12, 25, tzinfo=timezone.utc)
    assert news_filter.is_blackout_active(now, windows) is True


def test_empty_windows_never_blackout():
    now = datetime(2026, 9, 5, 12, 30, tzinfo=timezone.utc)
    assert news_filter.is_blackout_active(now, []) is False
