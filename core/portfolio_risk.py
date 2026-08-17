"""Portfolio-level risk gate: total $-at-risk across all open positions (sum of each
position's SL distance in pips * lot value), as a second check beyond drawdown alone."""


def calc_portfolio_risk_percent(open_positions, equity, point=0.0001, pip_value_per_lot=10):
    if equity <= 0:
        return 0.0
    total_risk = 0.0
    for pos in open_positions:
        sl = pos.get("sl")
        if not sl:
            continue
        distance_pips = abs(pos["price_open"] - sl) / point / 10
        total_risk += distance_pips * pip_value_per_lot * pos["volume"]
    return (total_risk / equity) * 100


def check_portfolio_risk_allowed(open_positions, equity, max_portfolio_risk_percent,
                                  point=0.0001, pip_value_per_lot=10):
    current = calc_portfolio_risk_percent(open_positions, equity, point, pip_value_per_lot)
    return current < max_portfolio_risk_percent
