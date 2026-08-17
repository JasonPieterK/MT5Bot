"""Static FX correlation groups. Real-time correlation calc is out of scope for a
local single-account tool — these are well-known major-pair correlation clusters."""

CORRELATION_GROUPS = [
    {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"},
    {"USDCHF", "USDJPY", "USDCAD"},
    {"XAUUSD", "XAGUSD"},
]


def are_correlated(symbol_a, symbol_b):
    if symbol_a == symbol_b:
        return True
    for group in CORRELATION_GROUPS:
        if symbol_a in group and symbol_b in group:
            return True
    return False


def check_correlation_allowed(open_positions, new_symbol, max_correlated_positions=2):
    count = sum(1 for pos in open_positions if are_correlated(pos["symbol"], new_symbol))
    return count < max_correlated_positions
