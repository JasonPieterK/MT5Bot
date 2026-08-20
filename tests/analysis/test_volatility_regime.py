import pandas as pd
import analysis.volatility_regime as volatility_regime


def make_df(ranges):
    rows = []
    price = 1.10
    for r in ranges:
        rows.append({"high": price + r / 2, "low": price - r / 2, "close": price})
    return pd.DataFrame(rows)


def test_low_regime_when_current_range_below_history():
    ranges = [0.01] * 50 + [0.001]
    df = make_df(ranges)
    assert volatility_regime.classify_regime(df) == "LOW"


def test_high_regime_when_current_range_spikes():
    ranges = [0.001] * 50 + [0.05]
    df = make_df(ranges)
    assert volatility_regime.classify_regime(df) == "HIGH"


def test_normal_regime_with_flat_ranges():
    ranges = [0.005] * 50
    df = make_df(ranges)
    assert volatility_regime.classify_regime(df) == "NORMAL"


def test_insufficient_data_returns_normal():
    df = make_df([0.005] * 5)
    assert volatility_regime.classify_regime(df) == "NORMAL"


# --- Hysteresis ------------------------------------------------------------------
# Real log, same symbol, minutes apart: NORMAL -> LOW -> HIGH -> NORMAL. Because the regime
# gates strategy eligibility, Auto's decision changed every few ticks for no change in the
# market. These pin the fix.

def test_hysteresis_holds_a_measure_that_is_hovering_on_a_band_edge(monkeypatch):
    """A reading parked in the dead zone must not reclassify. 40 is above the LOW entry (33)
    but below the LOW exit (45): from LOW it stays LOW, from NORMAL it stays NORMAL. The same
    reading giving two answers IS the hysteresis.

    The percentile is stubbed because the point under test is the banding, not the ATR
    arithmetic -- and a frame that lands on an exact percentile is a fixture, not a test."""
    df = make_df([0.005] * 50)
    for reading, from_low, from_normal, from_high in [
            (40, "LOW", "NORMAL", "NORMAL"),   # dead zone above ENTER_LOW, below EXIT_LOW
            (60, "NORMAL", "NORMAL", "HIGH"),  # dead zone below ENTER_HIGH, above EXIT_HIGH
            (50, "NORMAL", "NORMAL", "NORMAL"),
    ]:
        monkeypatch.setattr(volatility_regime, "_percentile", lambda *a, **k: reading)
        assert volatility_regime.classify_regime(df, previous="LOW") == from_low, reading
        assert volatility_regime.classify_regime(df, previous="NORMAL") == from_normal, reading
        assert volatility_regime.classify_regime(df, previous="HIGH") == from_high, reading


def test_a_measure_oscillating_across_one_band_edge_yields_a_stable_regime(monkeypatch):
    """The real complaint: ATR wobbling either side of the 33 boundary used to flip the
    classification every tick. Inside the dead zone it must not."""
    df = make_df([0.005] * 50)
    regime = "NORMAL"
    for reading in [34, 32.5, 36, 31.9, 40, 34, 33.5, 42]:
        monkeypatch.setattr(volatility_regime, "_percentile", lambda *a, **k: reading)
        regime = volatility_regime.classify_regime(df, previous=regime)
    # 32.5 and 31.9 dip under ENTER_LOW so LOW is entered, and nothing after that reaches
    # EXIT_LOW (45), so it stays put. One change, not eight.
    assert regime == "LOW"
    for reading in [46, 50, 55]:  # a real move out of the band
        monkeypatch.setattr(volatility_regime, "_percentile", lambda *a, **k: reading)
        regime = volatility_regime.classify_regime(df, previous=regime)
    assert regime == "NORMAL"


def test_a_genuine_sustained_shift_still_changes_the_regime():
    spike = make_df([0.001] * 50 + [0.05])
    assert volatility_regime.classify_regime(spike, previous="LOW") == "HIGH"
    calm = make_df([0.01] * 50 + [0.0001])
    assert volatility_regime.classify_regime(calm, previous="HIGH") == "LOW"


def test_too_little_data_holds_the_previous_regime_rather_than_inventing_normal():
    short = make_df([0.005] * 5)
    assert volatility_regime.classify_regime(short, previous="HIGH") == "HIGH"


def test_regime_for_requires_a_new_classification_to_repeat_before_adopting_it():
    volatility_regime.reset_regimes()
    calm = make_df([0.005] * 50)
    spike = make_df([0.001] * 50 + [0.05])
    assert volatility_regime.regime_for("X", calm) == "NORMAL"   # first read settles at once
    for _ in range(volatility_regime.CONFIRM_TICKS - 1):
        assert volatility_regime.regime_for("X", spike) == "NORMAL", "flipped on one tick"
    assert volatility_regime.regime_for("X", spike) == "HIGH"


def test_a_single_stray_read_cannot_flip_the_regime():
    volatility_regime.reset_regimes()
    calm = make_df([0.005] * 50)
    spike = make_df([0.001] * 50 + [0.05])
    assert volatility_regime.regime_for("Y", calm) == "NORMAL"
    for _ in range(10):
        assert volatility_regime.regime_for("Y", spike) == "NORMAL"
        assert volatility_regime.regime_for("Y", calm) == "NORMAL"


def test_each_symbol_keeps_its_own_regime():
    volatility_regime.reset_regimes()
    calm = make_df([0.005] * 50)
    assert volatility_regime.regime_for("A", calm) == "NORMAL"
    assert volatility_regime.regime_for("B", calm) == "NORMAL"
    assert set(volatility_regime._settled) == {"A", "B"}
