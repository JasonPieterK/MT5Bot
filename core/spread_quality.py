"""Spread-quality gate using the bar-level spread already present in OHLC rate data —
no extra API call needed."""


def is_spread_acceptable(rates_df, lookback=20, max_ratio=1.5):
    if "spread" not in rates_df or len(rates_df) < 2:
        return True
    recent = rates_df["spread"].tail(lookback)
    avg_spread = recent.mean()
    if avg_spread <= 0:
        return True
    current_spread = rates_df["spread"].iloc[-1]
    return bool(current_spread <= avg_spread * max_ratio)
