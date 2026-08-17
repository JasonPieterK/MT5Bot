"""Generic session-hour gate, usable by any strategy (not just scalping's own filter)."""


def in_session(current_hour, start_hour, end_hour):
    if start_hour <= end_hour:
        return start_hour <= current_hour <= end_hour
    return current_hour >= start_hour or current_hour <= end_hour
