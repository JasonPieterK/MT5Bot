"""Portfolio-level risk gate: total money at risk across all open positions (each
position's SL distance converted to dollars with the broker's own tick economics), as a
second check beyond drawdown alone.

There is deliberately no pip/point conversion here -- the same reason it was removed from
risk_manager.calc_lot_size. Hardcoding point=0.0001 and $10/pip made this 10x wrong on FX
and 100x wrong on XAUUSD, which silently blocked or allowed the wrong trades."""

# Fallback when the caller has no broker to ask: 5-digit FX, $1 per 0.00001 per lot.
# Same fallback mt5_bridge.get_symbol_tick_economics uses.
DEFAULT_TICK_VALUE = 1.0
DEFAULT_TICK_SIZE = 0.00001


def _economics_for(tick_economics, symbol):
    if tick_economics is None:
        return DEFAULT_TICK_VALUE, DEFAULT_TICK_SIZE
    tick_value, tick_size = tick_economics(symbol)
    if not tick_value or not tick_size or tick_value <= 0 or tick_size <= 0:
        return DEFAULT_TICK_VALUE, DEFAULT_TICK_SIZE
    return tick_value, tick_size


def calc_portfolio_risk_percent(open_positions, equity, tick_economics=None):
    """tick_economics is a callable symbol -> (tick_value, tick_size), normally
    mt5_bridge.get_symbol_tick_economics."""
    if equity <= 0:
        return 0.0
    total_risk = 0.0
    for pos in open_positions:
        sl = pos.get("sl")
        if not sl:
            continue
        tick_value, tick_size = _economics_for(tick_economics, pos.get("symbol"))
        distance = abs(pos["price_open"] - sl)
        total_risk += (distance / tick_size) * tick_value * pos["volume"]
    return (total_risk / equity) * 100


