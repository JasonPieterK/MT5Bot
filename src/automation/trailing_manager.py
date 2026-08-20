"""Trailing-stop and break-even automation. Operates on any open position, regardless
of which strategy (or a manual trade) opened it."""

# An SL only gets moved when it improves by at least this many points. MT5 prices wobble
# by a fraction of a point every tick, so without it every BUY gets a pointless
# modify_position (and an INFO log line) on every single engine tick.
MIN_MOVE_POINTS = 1


def _point_for(bridge, position, point):
    """The real per-symbol point. Hardcoding 0.0001 turned a 100-point trail on XAUUSD
    (point 0.01, so $1.00) into one cent."""
    if point is not None:
        return point
    return bridge.get_symbol_point(position["symbol"])


def _current_sl(position):
    """MT5 reports an unset stop loss as 0.0, never None. Treating 0.0 as a real price is
    why trailing never engaged on any SELL that had no SL yet."""
    sl = position.get("sl")
    if sl is None or sl == 0:
        return None
    return sl


def apply_trailing(bridge, position, distance_points, point=None):
    point = _point_for(bridge, position, point)
    bid, ask = bridge.get_current_price(position["symbol"])
    if bid is None or ask is None:
        return False
    distance = distance_points * point
    min_move = MIN_MOVE_POINTS * point
    sl = _current_sl(position)

    if position["type"] == "BUY":
        new_sl = bid - distance
        if sl is None or new_sl > sl + min_move:
            bridge.modify_position(position["ticket"], new_sl, position["tp"])
            return True
    else:
        new_sl = ask + distance
        if sl is None or new_sl < sl - min_move:
            bridge.modify_position(position["ticket"], new_sl, position["tp"])
            return True

    return False


def apply_partial_tp(bridge, position, trigger_points, close_fraction, partial_closed_tickets, point=None):
    """Closes close_fraction of the position once price moves trigger_points in profit,
    then moves SL to breakeven. Fires once per ticket — partial_closed_tickets tracks that."""
    if position["ticket"] in partial_closed_tickets:
        return False

    point = _point_for(bridge, position, point)
    bid, ask = bridge.get_current_price(position["symbol"])
    if bid is None or ask is None:
        return False
    trigger = trigger_points * point

    if position["type"] == "BUY":
        moved = bid - position["price_open"]
    else:
        moved = position["price_open"] - ask

    if moved < trigger:
        return False

    close_volume = round(position["volume"] * close_fraction, 2)
    if close_volume <= 0:
        return False

    bridge.close_position(position["ticket"], position["symbol"], close_volume,
                           position["type"], slippage_points=20)
    bridge.modify_position(position["ticket"], position["price_open"], position["tp"])
    partial_closed_tickets.add(position["ticket"])
    return True


def apply_breakeven(bridge, position, trigger_points, offset_points, point=None):
    point = _point_for(bridge, position, point)
    bid, ask = bridge.get_current_price(position["symbol"])
    if bid is None or ask is None:
        return False
    trigger = trigger_points * point
    offset = offset_points * point
    min_move = MIN_MOVE_POINTS * point
    sl = _current_sl(position)

    if position["type"] == "BUY":
        moved = bid - position["price_open"]
        if moved >= trigger:
            new_sl = position["price_open"] + offset
            if sl is None or new_sl > sl + min_move:
                bridge.modify_position(position["ticket"], new_sl, position["tp"])
                return True
    else:
        moved = position["price_open"] - ask
        if moved >= trigger:
            new_sl = position["price_open"] - offset
            if sl is None or new_sl < sl - min_move:
                bridge.modify_position(position["ticket"], new_sl, position["tp"])
                return True

    return False
