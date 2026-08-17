"""Tick-level directional momentum, a finer-grained read than OHLC bars. Retail MT5
has no order-book depth, so this uses trade-tick direction bias instead."""


def momentum_score(tick_prices):
    if len(tick_prices) < 2:
        return 0.0
    diffs = [tick_prices[i] - tick_prices[i - 1] for i in range(1, len(tick_prices))]
    ups = sum(1 for d in diffs if d > 0)
    downs = sum(1 for d in diffs if d < 0)
    total = ups + downs
    if total == 0:
        return 0.0
    return (ups - downs) / total


def signal_matches_momentum(signal, score, threshold=0.2):
    if signal == "BUY":
        return score >= threshold
    if signal == "SELL":
        return score <= -threshold
    return True
