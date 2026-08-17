from datetime import datetime, timezone
import automation.schedule_filter as schedule_filter


def test_friday_after_hour_triggers_flatten():
    now = datetime(2026, 8, 21, 22, 0, tzinfo=timezone.utc)  # a Friday
    assert schedule_filter.should_flatten_for_schedule(now, disable_weekday=4, disable_hour_utc=21) is True


def test_friday_before_hour_does_not_trigger():
    now = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
    assert schedule_filter.should_flatten_for_schedule(now, disable_weekday=4, disable_hour_utc=21) is False


def test_other_weekday_does_not_trigger():
    now = datetime(2026, 8, 20, 22, 0, tzinfo=timezone.utc)  # a Thursday
    assert schedule_filter.should_flatten_for_schedule(now, disable_weekday=4, disable_hour_utc=21) is False
