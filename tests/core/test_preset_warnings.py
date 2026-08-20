"""Every preset that can lose money faster than the default must say so on its own card.

The presets are the one place a user changes risk without reading any code, so the tier's
consequence has to travel with it rather than living in a doc they will not open.
"""
import core.profiles as profiles

BASELINE_RISK = 1.0          # the "balanced" tier
CONFIRM_ABOVE = 3.0          # anything this risky blocks until explicitly confirmed


def _by_id():
    return {p["id"]: p for p in profiles.PRESETS}


def test_every_preset_riskier_than_balanced_carries_a_warning():
    for p in profiles.PRESETS:
        if p["risk_percent"] > BASELINE_RISK:
            assert p.get("warning"), f"{p['id']} risks {p['risk_percent']}% with no warning"


def test_the_riskiest_presets_require_explicit_confirmation():
    for p in profiles.PRESETS:
        if p["risk_percent"] >= CONFIRM_ABOVE:
            assert p.get("requires_confirmation"), f"{p['id']} should require confirmation"
            assert p.get("confirmation"), f"{p['id']} confirms with no text"


def test_no_preset_promises_a_return():
    """These are risk-management tiers. No strategy here has a demonstrated edge, so no
    description may imply one."""
    banned = ("profit", "gain", "return", "win rate", "outperform", "best results",
               "recommended for growth", "maximise earnings")
    for p in profiles.PRESETS:
        text = f"{p['description']} {p.get('warning','')}".lower()
        for word in banned:
            assert word not in text, f"{p['id']} description implies a return: {word!r}"


def test_no_preset_picks_a_strategy():
    for p in profiles.PRESETS:
        assert "strategy" not in p, f"{p['id']} sets a strategy; tiers are risk-only"


def test_warnings_survive_resolve_so_the_ui_can_show_them():
    p = _by_id()["high_risk"]
    resolved = profiles.resolve(p, equity=100_000, per_lot=100.0, broker_max_lot=50.0)
    assert resolved["warning"]
    assert resolved["requires_confirmation"] is True
    assert "0.96^10" in resolved["confirmation"]

