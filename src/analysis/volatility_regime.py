"""Classifies current volatility vs its own recent history, so a strategy can be
gated in unusually quiet or unusually violent conditions."""
import analysis.indicators as indicators


def classify_regime(df, atr_period=14, lookback=100):
    if len(df) < atr_period + 2:
        return "NORMAL"
    atr = indicators.atr(df, period=atr_period).dropna()
    if len(atr) < 2:
        return "NORMAL"
    history = atr.iloc[-lookback:]
    current = atr.iloc[-1]
    below = (history < current).mean()
    equal = (history == current).mean()
    percentile = (below + 0.5 * equal) * 100
    if percentile < 33:
        return "LOW"
    if percentile > 67:
        return "HIGH"
    return "NORMAL"
