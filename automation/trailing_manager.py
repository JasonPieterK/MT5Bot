"""Trailing-stop and break-even automation. Operates on any open position, regardless
of which strategy (or a manual trade) opened it."""


def apply_trailing(bridge, position, distance_points, point=0.0001):
    bid, ask = bridge.get_current_price(position["symbol"])
    distance = distance_points * point

    if position["type"] == "BUY":
        current_price = bid
        new_sl = current_price - distance
        if position["sl"] is None or new_sl > position["sl"]:
            bridge.modify_position(position["ticket"], new_sl, position["tp"])
            return True
    else:
        current_price = ask
        new_sl = current_price + distance
        if position["sl"] is None or new_sl < position["sl"]:
            bridge.modify_position(position["ticket"], new_sl, position["tp"])
            return True

    return False


def apply_partial_tp(bridge, position, trigger_points, close_fraction, partial_closed_tickets, point=0.0001):
    """Closes close_fraction of the position once price moves trigger_points in profit,
    then moves SL to breakeven. Fires once per ticket — partial_closed_tickets tracks that."""
    if position["ticket"] in partial_closed_tickets:
        return False

    bid, ask = bridge.get_current_price(position["symbol"])
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


def apply_breakeven(bridge, position, trigger_points, offset_points, point=0.0001):
    bid, ask = bridge.get_current_price(position["symbol"])
    trigger = trigger_points * point
    offset = offset_points * point

    if position["type"] == "BUY":
        moved = bid - position["price_open"]
        if moved >= trigger:
            new_sl = position["price_open"] + offset
            if position["sl"] is None or new_sl > position["sl"]:
                bridge.modify_position(position["ticket"], new_sl, position["tp"])
                return True
    else:
        moved = position["price_open"] - ask
        if moved >= trigger:
            new_sl = position["price_open"] - offset
            if position["sl"] is None or new_sl < position["sl"]:
                bridge.modify_position(position["ticket"], new_sl, position["tp"])
                return True

    return False
