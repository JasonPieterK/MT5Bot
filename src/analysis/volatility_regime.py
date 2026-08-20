"""Classifies current volatility vs its own recent history, so a strategy can be
gated in unusually quiet or unusually violent conditions.

The classification is deliberately sticky. Plain percentile bands made ATR sitting near an
edge oscillate -- a real log showed one symbol go NORMAL -> LOW -> HIGH -> NORMAL within
minutes, which flipped the running strategy in and out of Auto's eligibility list for no
change in the market. Two things stop that:

  * hysteresis (a Schmitt trigger): leaving a regime needs a bigger move than entering it,
    so a measure hovering on an edge stays where it is;
  * confirmation: a new classification has to hold for CONFIRM_TICKS consecutive reads
    before it is adopted.

classify_regime stays a pure function -- the caller passes the previous regime in -- so both
behaviours are testable without a live feed. regime_for is the thin stateful wrapper the
trading loop uses.
"""
import analysis.indicators as indicators

# Enter a regime at these percentiles, leave it only past the wider exit. The gap between
# ENTER and EXIT is the dead zone in which the classification does not change.
ENTER_LOW, EXIT_LOW = 33, 45
ENTER_HIGH, EXIT_HIGH = 67, 55

# Consecutive reads a new classification must survive before regime_for adopts it.
CONFIRM_TICKS = 3


def _percentile(df, atr_period, lookback):
    """Where the latest ATR sits within its own recent history, 0-100. None when the frame
    is too short to say -- which is not the same as "normal"."""
    if len(df) < atr_period + 2:
        return None
    atr = indicators.atr(df, period=atr_period).dropna()
    if len(atr) < 2:
        return None
    history = atr.iloc[-lookback:]
    current = atr.iloc[-1]
    below = (history < current).mean()
    equal = (history == current).mean()
    return (below + 0.5 * equal) * 100


def classify_regime(df, atr_period=14, lookback=100, previous=None):
    """"LOW" / "NORMAL" / "HIGH". Pass the previous classification to get hysteresis; with
    previous=None this is the plain percentile banding."""
    percentile = _percentile(df, atr_period, lookback)
    if percentile is None:
        # Too little data to reclassify. Holding the previous answer beats inventing NORMAL,
        # which would itself be a flap.
        return previous or "NORMAL"
    if previous == "LOW":
        if percentile < EXIT_LOW:
            return "LOW"
    elif previous == "HIGH":
        if percentile > EXIT_HIGH:
            return "HIGH"
    if percentile < ENTER_LOW:
        return "LOW"
    if percentile > ENTER_HIGH:
        return "HIGH"
    return "NORMAL"


# key -> (settled regime, candidate regime, consecutive reads of that candidate)
# ponytail: a dict keyed by symbol. Nothing else needs this state; make it a class only if
# something does.
_settled = {}


def reset_regimes():
    """Forget every symbol's regime history. Used by tests and on a mode change."""
    _settled.clear()


def regime_for(key, df, atr_period=14, lookback=100):
    """classify_regime for `key`, remembering its previous answer and requiring a new one to
    repeat CONFIRM_TICKS times before it is adopted."""
    settled, candidate, count = _settled.get(key, (None, None, 0))
    fresh = classify_regime(df, atr_period, lookback, previous=settled)
    if fresh == settled:
        _settled[key] = (settled, None, 0)
        return settled
    count = count + 1 if fresh == candidate else 1
    if settled is None or count >= CONFIRM_TICKS:
        _settled[key] = (fresh, None, 0)
        return fresh
    _settled[key] = (settled, fresh, count)
    return settled
