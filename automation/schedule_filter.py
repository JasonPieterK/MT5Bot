"""Scheduled flatten window — e.g. flatten and stop opening new trades ahead of the
Friday forex close, so nothing is left open over the weekend gap risk."""


def should_flatten_for_schedule(now_utc, disable_weekday=4, disable_hour_utc=21):
    """disable_weekday: Monday=0 ... Friday=4 (default: Friday)."""
    return now_utc.weekday() == disable_weekday and now_utc.hour >= disable_hour_utc
