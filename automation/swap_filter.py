"""Blocks new entries near daily rollover, when swap is charged/credited — avoids opening
a position minutes before eating an unfavorable overnight swap. Applied every day since
rollover time is broker-specific and recurs daily (Wednesday's triple-swap is the same
window, just weighted 3x by the broker) — a per-weekday special case isn't needed."""


def is_swap_blackout(now_utc, block_hours_before_rollover=1, rollover_hour_utc=21):
    window_start = rollover_hour_utc - block_hours_before_rollover
    return window_start <= now_utc.hour < rollover_hour_utc
