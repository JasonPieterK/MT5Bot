import core.portfolio_risk as portfolio_risk


def fx_economics(symbol):
    """5-digit FX: $1 per 0.00001 per lot == $10 per pip per lot."""
    return 1.0, 0.00001


def gold_economics(symbol):
    """XAUUSD: $1 per 0.01 of price per lot == $100 per $1 move per lot."""
    return 1.0, 0.01


def test_zero_risk_with_no_positions():
    assert portfolio_risk.calc_portfolio_risk_percent([], 10000) == 0.0


def test_risk_accumulates_across_positions():
    positions = [
        {"symbol": "EURUSD", "price_open": 1.1000, "sl": 1.0950, "volume": 0.1},
        {"symbol": "EURUSD", "price_open": 1.1000, "sl": 1.0950, "volume": 0.1},
    ]
    single = portfolio_risk.calc_portfolio_risk_percent(positions[:1], 10000, fx_economics)
    double = portfolio_risk.calc_portfolio_risk_percent(positions, 10000, fx_economics)
    assert abs(double - single * 2) < 1e-6


def test_positions_without_sl_ignored():
    positions = [{"symbol": "EURUSD", "price_open": 1.1000, "sl": None, "volume": 0.1}]
    assert portfolio_risk.calc_portfolio_risk_percent(positions, 10000, fx_economics) == 0.0


def test_fx_risk_is_real_dollars():
    """0.1 lots of EURUSD with a 50-pip stop risks $50, i.e. 0.5% of a $10,000 account.
    The old point=0.0001/pip_value=10 approximation reported 5%."""
    positions = [{"symbol": "EURUSD", "price_open": 1.1000, "sl": 1.0950, "volume": 0.1}]
    assert abs(portfolio_risk.calc_portfolio_risk_percent(positions, 10000, fx_economics) - 0.5) < 1e-6


def test_gold_risk_is_real_dollars():
    """1.0 lot of XAUUSD with a $3.00 stop risks $300, i.e. 3% of a $10,000 account.
    The old maths reported 300% -- 100x wrong."""
    positions = [{"symbol": "XAUUSD", "price_open": 2300.0, "sl": 2297.0, "volume": 1.0}]
    assert abs(portfolio_risk.calc_portfolio_risk_percent(positions, 10000, gold_economics) - 3.0) < 1e-6


def test_unusable_tick_economics_fall_back_instead_of_dividing_by_zero():
    positions = [{"symbol": "EURUSD", "price_open": 1.1000, "sl": 1.0950, "volume": 0.1}]
    risk = portfolio_risk.calc_portfolio_risk_percent(positions, 10000, lambda s: (0.0, 0.0))
    assert abs(risk - 0.5) < 1e-6


