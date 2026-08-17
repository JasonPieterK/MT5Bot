import core.portfolio_risk as portfolio_risk


def test_zero_risk_with_no_positions():
    assert portfolio_risk.calc_portfolio_risk_percent([], 10000) == 0.0


def test_risk_accumulates_across_positions():
    positions = [
        {"price_open": 1.1000, "sl": 1.0950, "volume": 0.1},
        {"price_open": 1.1000, "sl": 1.0950, "volume": 0.1},
    ]
    single = portfolio_risk.calc_portfolio_risk_percent(positions[:1], 10000)
    double = portfolio_risk.calc_portfolio_risk_percent(positions, 10000)
    assert double == round(single * 2, 10) or abs(double - single * 2) < 1e-6


def test_positions_without_sl_ignored():
    positions = [{"price_open": 1.1000, "sl": None, "volume": 0.1}]
    assert portfolio_risk.calc_portfolio_risk_percent(positions, 10000) == 0.0


def test_check_allowed_under_cap():
    positions = [{"price_open": 1.1000, "sl": 1.0950, "volume": 0.1}]
    assert portfolio_risk.check_portfolio_risk_allowed(positions, 10000, max_portfolio_risk_percent=10.0) is True


def test_check_blocked_over_cap():
    positions = [{"price_open": 1.1000, "sl": 1.0000, "volume": 5.0}]
    assert portfolio_risk.check_portfolio_risk_allowed(positions, 10000, max_portfolio_risk_percent=1.0) is False
