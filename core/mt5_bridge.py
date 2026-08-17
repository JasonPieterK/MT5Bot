"""Thin wrapper over the MetaTrader5 package. All MT5 API calls go through here."""
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
}


def connect():
    ok = mt5.initialize()
    if not ok:
        print(f"MT5 connect failed: {mt5.last_error()}")
    return ok


def get_rates(symbol, timeframe, count):
    tf = TIMEFRAME_MAP[timeframe]
    raw = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    return pd.DataFrame(
        raw, columns=["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
    )


def get_open_positions(symbol=None):
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if positions is None:
        return []
    return [
        {
            "ticket": p.ticket,
            "symbol": p.symbol,
            "volume": p.volume,
            "profit": p.profit,
            "type": "BUY" if p.type == 0 else "SELL",
            "price_open": p.price_open,
            "sl": p.sl,
            "tp": p.tp,
        }
        for p in positions
    ]


def check_stops_valid(symbol, sl, tp):
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    min_dist = info.trade_stops_level * info.point
    if sl is not None and abs(tick.bid - sl) < min_dist:
        return False, f"sl too close to price: min stop distance is {min_dist}"
    if tp is not None and abs(tick.bid - tp) < min_dist:
        return False, f"tp too close to price: min stop distance is {min_dist}"
    return True, ""


def place_order(symbol, direction, volume, sl, tp, slippage_points):
    tick = mt5.symbol_info_tick(symbol)
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if direction == "BUY" else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": slippage_points,
        "type_filling": mt5.ORDER_FILLING_IOC if hasattr(mt5, "ORDER_FILLING_IOC") else 0,
    }
    result = mt5.order_send(request)
    ok = result.retcode == mt5.TRADE_RETCODE_DONE
    return ok, result.retcode


def close_position(ticket, symbol, volume, direction, slippage_points):
    close_direction = "SELL" if direction == "BUY" else "BUY"
    return place_order(symbol, close_direction, volume, sl=None, tp=None, slippage_points=slippage_points)


def get_account_equity():
    info = mt5.account_info()
    return info.equity if info else 0.0


def get_current_price(symbol):
    tick = mt5.symbol_info_tick(symbol)
    return tick.bid, tick.ask


def modify_position(ticket, sl, tp):
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl": sl,
        "tp": tp,
    }
    result = mt5.order_send(request)
    ok = result.retcode == mt5.TRADE_RETCODE_DONE
    return ok, result.retcode


def get_margin_level():
    info = mt5.account_info()
    return info.margin_level if info and info.margin_level else 0.0


def get_history_deals(from_date):
    deals = mt5.history_deals_get(from_date, datetime.now())
    if deals is None:
        return []
    return [
        {"ticket": d.ticket, "symbol": d.symbol, "profit": d.profit, "time": d.time}
        for d in deals if d.entry == mt5.DEAL_ENTRY_OUT
    ]
