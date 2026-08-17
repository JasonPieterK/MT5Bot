from datetime import datetime, timezone
import automation.swap_filter as swap_filter


def test_inside_blackout_window():
    now = datetime(2026, 9, 5, 20, 30, tzinfo=timezone.utc)
    assert swap_filter.is_swap_blackout(now, block_hours_before_rollover=1, rollover_hour_utc=21) is True


def test_outside_blackout_window():
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    assert swap_filter.is_swap_blackout(now, block_hours_before_rollover=1, rollover_hour_utc=21) is False


def test_boundary_start_inclusive():
    now = datetime(2026, 9, 5, 20, 0, tzinfo=timezone.utc)
    assert swap_filter.is_swap_blackout(now, block_hours_before_rollover=1, rollover_hour_utc=21) is True


def test_boundary_end_exclusive():
    now = datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc)
    assert swap_filter.is_swap_blackout(now, block_hours_before_rollover=1, rollover_hour_utc=21) is False
