import pandas as pd
from strategies.grid import get_signal, HARD_MAX_LEVELS, HARD_MAX_TOTAL_LOTS, HARD_EQUITY_STOP_PERCENT
from core.config import DEFAULT_SETTINGS


def flat_df():
    rows = [{"open": 1.10, "high": 1.1005, "low": 1.0995, "close": 1.10}] * 25
    return pd.DataFrame(rows)


def test_hard_caps_exist_and_are_not_in_default_settings():
    assert HARD_MAX_LEVELS > 0
    assert HARD_MAX_TOTAL_LOTS > 0
    assert HARD_EQUITY_STOP_PERCENT > 0
    assert "max_levels" not in DEFAULT_SETTINGS["grid"]


def test_no_signal_when_max_levels_reached():
    settings = dict(DEFAULT_SETTINGS["grid"])
    signal, sl, tp = get_signal(flat_df(), settings, current_grid_levels=HARD_MAX_LEVELS)
    assert signal == "NONE"


def test_first_level_entry_allowed():
    settings = dict(DEFAULT_SETTINGS["grid"])
    signal, sl, tp = get_signal(flat_df(), settings, current_grid_levels=0)
    assert signal in ("BUY", "SELL")
