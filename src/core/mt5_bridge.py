"""Thin wrapper over the MetaTrader5 package. All MT5 API calls go through here."""
import time

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


def connect(path=None, login=None, password=None, server=None):
    kwargs = {}
    if path:
        kwargs["path"] = path
    if login:
        kwargs["login"] = login
    if password:
        kwargs["password"] = password
    if server:
        kwargs["server"] = server
    ok = mt5.initialize(**kwargs) if kwargs else mt5.initialize()
    if not ok:
        print(f"MT5 connect failed: {mt5.last_error()}")
    return ok


def is_connected():
    """Cheap local check -- no IPC round-trip to the terminal. connect()/mt5.initialize()
    is the expensive call and must not be used as a 5-second health check: besides the
    latency, calling it with no arguments can silently re-attach to a different terminal
    or account than the one the user selected."""
    return mt5.terminal_info() is not None


RATES_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]

# A symbol freshly added to Market Watch answers the first copy_rates_from_pos with zero
# bars while the terminal pulls history from the broker. Retrying a couple of seconds later
# returns the data.
RATES_WARMUP_ATTEMPTS = 3
RATES_WARMUP_SECONDS = 1.0


def get_rates(symbol, timeframe, count, _sleep=time.sleep):
    """Bars for a symbol, retrying while the terminal warms up its history cache.

    Without the retry an empty frame reaches the strategy, which reads it as "no signal" --
    so a symbol that has simply not finished syncing looks identical to a quiet market, and
    the bot does nothing for as long as that lasts without ever saying why. The caller is
    expected to treat an empty frame as "not ready", not as "no signal"."""
    tf = TIMEFRAME_MAP[timeframe]
    for attempt in range(RATES_WARMUP_ATTEMPTS):
        raw = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if raw is not None and len(raw) > 0:
            return pd.DataFrame(raw, columns=RATES_COLUMNS)
        if attempt < RATES_WARMUP_ATTEMPTS - 1:
            _sleep(RATES_WARMUP_SECONDS)
    return pd.DataFrame(columns=RATES_COLUMNS)


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


_fill_mode_cache = {}  # symbol -> filling mode the broker last accepted

# 10030 is the documented "broker refused this fill type". Some broker/terminal builds
# report the same condition as 10017 (trade disabled), which is why a bot that only ever
# sent IOC looked like it had algo trading switched off. Both mean "try the next mode".
RETRYABLE_FILL_RETCODES = (10030, 10017)


def _fill_modes_for(symbol):
    modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_FOK]
    cached = _fill_mode_cache.get(symbol)
    if cached in modes:
        # Most orders on a symbol use the same mode, so trying the winner first turns
        # three broker round-trips back into one.
        modes.remove(cached)
        modes.insert(0, cached)
    return modes


def _send(request):
    """Every order_send goes through here.

    Two things this handles that a bare order_send does not:
      1. mt5.order_send returns None when the terminal is disconnected or the request is
         malformed -- without a guard that surfaces as an opaque AttributeError.
      2. Execution orders cycle through every filling mode until the broker accepts one.
         Modification actions (SLTP/MODIFY) must NOT carry type_filling at all: injecting
         it makes some broker builds return None instead of a result object.
    """
    action = request.get("action")
    non_fill_actions = (getattr(mt5, "TRADE_ACTION_SLTP", None),
                        getattr(mt5, "TRADE_ACTION_MODIFY", None))
    if action in non_fill_actions:
        request.pop("type_filling", None)
        result = mt5.order_send(request)
        if result is None:
            return False, f"no response from MT5 terminal ({mt5.last_error()})"
        return result.retcode == mt5.TRADE_RETCODE_DONE, result.retcode

    symbol = request.get("symbol")
    result = None
    for fill in _fill_modes_for(symbol):
        # A fresh dict per attempt: mutating one shared request makes the retry history
        # impossible to read back (and to assert on).
        result = mt5.order_send(dict(request, type_filling=fill))
        if result is None:
            return False, f"no response from MT5 terminal ({mt5.last_error()})"
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            if symbol:
                _fill_mode_cache[symbol] = fill
            return True, result.retcode
        if result.retcode not in RETRYABLE_FILL_RETCODES:
            return False, result.retcode
    return False, result.retcode


def _alnum(text):
    return "".join(c for c in text.upper() if c.isalnum())


def _trade_mode_problem(info, name):
    """Full plain-English sentence for a symbol's trade_mode, so a rejection names the exact
    restriction instead of a blanket 'disabled'."""
    mode = getattr(info, "trade_mode", None)
    for const, text in (
            ("SYMBOL_TRADE_MODE_DISABLED", f"The broker has disabled trading on '{name}'."),
            ("SYMBOL_TRADE_MODE_CLOSEONLY", f"'{name}' is close-only right now -- the broker "
                                            f"allows closing trades but no new ones."),
            ("SYMBOL_TRADE_MODE_LONGONLY", f"'{name}' is long-only right now -- the broker "
                                           f"allows buys but not sells."),
            ("SYMBOL_TRADE_MODE_SHORTONLY", f"'{name}' is short-only right now -- the broker "
                                            f"allows sells but not buys.")):
        if mode == getattr(mt5, const, object()):
            return text
    return f"The broker has disabled trading on '{name}'."


def _is_tradeable(info):
    """Brokers list display-only duplicates of real instruments. XM ships both 'EURUSD'
    (trade_mode DISABLED) and 'EURUSD#' (FULL); sending an order to the first is what the
    broker answers with retcode 10017."""
    if info is None:
        return False
    full = getattr(mt5, "SYMBOL_TRADE_MODE_FULL", 4)
    return getattr(info, "trade_mode", full) == full


def resolve_symbol(name):
    """Turn a user-typed symbol into the broker's real symbol name, selected into Market
    Watch. Brokers rename the same instrument (XAUUSD / XAUUSD.m / GOLD / EURUSD.pro), and a
    pasted name can carry stray case or spacing. Returns (resolved_name, error_message):
    exactly one of the two is None."""
    if not name or not name.strip():
        return None, "No symbol given."
    name = name.strip()

    info = mt5.symbol_info(name)
    if info is not None and getattr(info, "visible", False) and _is_tradeable(info):
        return info.name, None  # already streaming prices -- the common repeat case
    if info is None and mt5.symbol_select(name, True):
        info = mt5.symbol_info(name)
    if _is_tradeable(info):
        mt5.symbol_select(info.name, True)
        return info.name, None

    # Either the name is unknown, or it matched a variant the broker refuses to trade. Both
    # are answered the same way: look for the sibling that IS tradeable.
    exact_but_disabled = info is not None
    all_symbols = mt5.symbols_get() or []
    upper, core = name.upper(), _alnum(name)

    for matches in (lambda s: s.name.upper() == upper,
                    lambda s: _alnum(s.name) == core,
                    lambda s: s.name.upper().startswith(upper) or _alnum(s.name).startswith(core)):
        hits = [s for s in all_symbols if matches(s) and _is_tradeable(s)]
        if len(hits) == 1:
            mt5.symbol_select(hits[0].name, True)
            return hits[0].name, None
        if len(hits) > 1:
            names = sorted(s.name for s in hits)
            return None, (f"Symbol '{name}' is ambiguous -- this broker offers: "
                          f"{', '.join(names[:8])}. Use the exact name.")

    if exact_but_disabled:
        return None, (f"{_trade_mode_problem(info, name)} There is no fully tradeable "
                      f"alternative under that name.")
    near = sorted({s.name for s in all_symbols
                   if s.name.upper().startswith(upper) or _alnum(s.name).startswith(core)})
    if near:
        return None, (f"Symbol '{name}' not found. This broker calls it one of: "
                      f"{', '.join(near[:8])}")
    return None, f"Symbol '{name}' does not exist at this broker."


def list_tradeable_symbols(limit=400):
    """Symbol names this broker will actually accept an order on, Market Watch ones first.
    Feeds the dashboard's symbol suggestions so the user is never offered a name that cannot
    be traded (XM lists a disabled 'EURUSD' next to the real 'EURUSD#')."""
    symbols = mt5.symbols_get() or []
    tradeable = [s for s in symbols if _is_tradeable(s)]
    tradeable.sort(key=lambda s: (not getattr(s, "visible", False), s.name))
    return [s.name for s in tradeable[:limit]]


def check_stops_valid(symbol, sl, tp):
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return False, f"symbol not found or not selected in Market Watch: {symbol}"
    min_dist = info.trade_stops_level * info.point
    if sl is not None and abs(tick.bid - sl) < min_dist:
        return False, f"sl too close to price: min stop distance is {min_dist}"
    if tp is not None and abs(tick.bid - tp) < min_dist:
        return False, f"tp too close to price: min stop distance is {min_dist}"
    return True, ""


def _price_field(symbol, value):
    """A price ready for an MT5 request. MT5 spells "no stop" / "no target" as 0.0 -- passing
    Python's None gets the WHOLE request refused with `Invalid "sl" argument`, so a
    deliberately absent stop stopped the order dead instead of sending it unprotected."""
    if value is None:
        return 0.0
    return _round_price(symbol, value)


def _round_price(symbol, value):
    """Prices must carry exactly the symbol's decimal precision. An ATR-derived stop like
    4411.716466763122 on a digits=2 symbol is not merely untidy -- MT5 rejects it, and some
    brokers fill the deal while silently dropping the stop, which leaves a position open
    with no protection at all. None means "no stop", which must survive untouched."""
    if value is None:
        return None
    info = mt5.symbol_info(symbol)
    digits = getattr(info, "digits", None) if info is not None else None
    if not isinstance(digits, int) or isinstance(digits, bool):
        return value  # symbol info unavailable or unusable -- send the price untouched
    return round(float(value), digits)


def place_order(symbol, direction, volume, sl, tp, slippage_points, magic=0, position=None):
    """position is only set when this DEAL is closing an existing position -- without it
    a close on a hedging account opens a brand-new opposite position instead."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, f"symbol not found or not selected in Market Watch: {symbol}"
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if direction == "BUY" else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": _round_price(symbol, price),
        "sl": _price_field(symbol, sl),
        "tp": _price_field(symbol, tp),
        "deviation": slippage_points,
        "magic": magic,
        # type_filling is set by _send, which cycles modes until the broker accepts one.
    }
    if position is not None:
        request["position"] = position
    return _send(request)


def close_position(ticket, symbol, volume, direction, slippage_points):
    close_direction = "SELL" if direction == "BUY" else "BUY"
    return place_order(symbol, close_direction, volume, sl=None, tp=None,
                        slippage_points=slippage_points, position=ticket)


def get_account_login():
    """Which account the terminal is logged into, or None if it cannot be read. Risk figures
    measured against a previous account's history are meaningless, so anything that
    accumulates across ticks has to be scoped to this."""
    info = mt5.account_info()
    return getattr(info, "login", None) if info is not None else None


def get_account_equity():
    info = mt5.account_info()
    return info.equity if info else 0.0


def get_current_price(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None, None
    return tick.bid, tick.ask


def modify_position(ticket, sl, tp):
    # Same precision rule as place_order: an unrounded stop here is rejected, so a trailing
    # stop or break-even move would silently never take effect.
    symbol = None
    for pos in get_open_positions():
        if pos["ticket"] == ticket:
            symbol = pos["symbol"]
            break
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl": _price_field(symbol, sl) if symbol else (0.0 if sl is None else sl),
        "tp": _price_field(symbol, tp) if symbol else (0.0 if tp is None else tp),
    }
    return _send(request)


def broker_clock_offset(symbol):
    """How far the broker's clock runs from this machine's, as a timedelta.

    mt5.history_deals_get() interprets its date arguments in SERVER time, but a caller
    naturally builds them from datetime.now(). Measured against a live XM account the broker
    ran +3h, so a "since midnight" window was three hours out -- the previous broker day's
    losses counted as today's and the current morning's did not. That decides when the
    daily-loss kill switch fires, so it is measured from a real tick rather than assumed."""
    from datetime import datetime, timedelta
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or not getattr(tick, "time", 0):
            return timedelta(0)
        return datetime.fromtimestamp(tick.time) - datetime.now()
    except Exception:
        return timedelta(0)   # no offset is safer than a guessed one


def broker_day_start(symbol):
    """Midnight of the current BROKER day, expressed the way history_deals_get expects."""
    from datetime import datetime
    offset = broker_clock_offset(symbol)
    broker_now = datetime.now() + offset
    return datetime.combine(broker_now.date(), datetime.min.time()) + offset


def get_history_deals(from_date):
    deals = mt5.history_deals_get(from_date, datetime.now())
    if deals is None:
        return []
    return [
        {"ticket": d.ticket, "symbol": d.symbol, "profit": d.profit, "time": d.time,
         "magic": getattr(d, "magic", 0)}
        for d in deals if d.entry == mt5.DEAL_ENTRY_OUT
    ]


DEAL_TYPE_LABEL = {0: "BUY", 1: "SELL"}


def get_history_rows(from_date):
    """Closing deals with everything the History tab shows. get_history_deals() above is the
    lean version the risk/auto-tune paths use on every tick; this one carries the money
    columns (commission, swap, volume, price) that only the table needs."""
    deals = mt5.history_deals_get(from_date, datetime.now())
    if deals is None:
        return []
    return [
        {"ticket": d.ticket, "symbol": d.symbol, "time": d.time,
         "type": DEAL_TYPE_LABEL.get(getattr(d, "type", None), "-"),
         "volume": float(getattr(d, "volume", 0.0) or 0.0),
         "price": float(getattr(d, "price", 0.0) or 0.0),
         "profit": float(d.profit or 0.0),
         "commission": float(getattr(d, "commission", 0.0) or 0.0),
         "swap": float(getattr(d, "swap", 0.0) or 0.0)}
        for d in deals if d.entry == mt5.DEAL_ENTRY_OUT
    ]


def get_account_info():
    """The persistent account strip: who we are logged in as and what the money looks like."""
    info = mt5.account_info()
    if info is None:
        return {"connected": False}
    return {
        "connected": True,
        "login": getattr(info, "login", None),
        "name": getattr(info, "name", ""),
        "server": getattr(info, "server", ""),
        "company": getattr(info, "company", ""),
        "currency": getattr(info, "currency", ""),
        "balance": float(getattr(info, "balance", 0.0) or 0.0),
        "equity": float(getattr(info, "equity", 0.0) or 0.0),
        "margin_free": float(getattr(info, "margin_free", 0.0) or 0.0),
        "margin_level": float(getattr(info, "margin_level", 0.0) or 0.0),
        "trade_mode": ACCOUNT_TRADE_MODES.get(getattr(info, "trade_mode", None), "unknown"),
    }


def get_symbol_point(symbol):
    """Price-per-point for this symbol (e.g. 0.00001 for 5-digit EURUSD, 0.01 for XAUUSD).
    Used to convert a manual TP/SL "points" input into a price distance."""
    info = mt5.symbol_info(symbol)
    return info.point if info and info.point else 0.0001



def close_position_by_ticket(ticket, slippage_points):
    """Manual-trading single close -- looks the position up by ticket so the route only
    needs to know the ticket, not symbol/volume/direction."""
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return False, "position not found"
    p = positions[0]
    direction = "BUY" if p.type == 0 else "SELL"
    return close_position(ticket, p.symbol, p.volume, direction, slippage_points)


def get_symbol_volume_limits(symbol):
    """Broker-defined min/max lot size and step for this symbol. Falls back to
    conservative defaults if the symbol info isn't available (e.g. bad symbol name),
    so a lot-size calculation never has an unbounded max."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.01, 100.0, 0.01
    min_lot = info.volume_min or 0.01
    max_lot = info.volume_max or 100.0
    step = info.volume_step or 0.01
    return min_lot, max_lot, step


def get_symbol_tick_economics(symbol):
    """(tick_value, tick_size) -- money per one tick of price movement per 1.0 lot, and how
    big one tick is in price. Together they are the only correct way to turn an SL distance
    in price into money at risk, for FX, metals, indices and crypto alike. Falls back to
    5-digit FX economics ($10 per 0.0001 per lot) when the symbol isn't available."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return 1.0, 0.00001
    tick_value = getattr(info, "trade_tick_value", 0.0) or 0.0
    tick_size = getattr(info, "trade_tick_size", 0.0) or 0.0
    if tick_value <= 0 or tick_size <= 0:
        return 1.0, 0.00001
    return tick_value, tick_size


def get_required_margin(symbol, direction, volume):
    """Margin the broker will lock up for this order, or None if MT5 can't tell us."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if direction == "BUY" else tick.bid
    margin = mt5.order_calc_margin(order_type, symbol, volume, price)
    return None if margin is None else float(margin)


def get_free_margin():
    info = mt5.account_info()
    return float(info.margin_free) if info and info.margin_free is not None else 0.0


STALE_QUOTE_SECONDS = 15 * 60

ACCOUNT_TRADE_MODES = {0: "demo", 1: "contest", 2: "real"}


def get_account_summary():
    """Account facts that decide whether an order can be placed at all."""
    info = mt5.account_info()
    if info is None:
        return {"connected": False, "trade_allowed": False, "trade_mode": None, "margin_free": 0.0}
    return {
        "connected": True,
        "trade_allowed": bool(getattr(info, "trade_allowed", False)),
        "trade_mode": ACCOUNT_TRADE_MODES.get(getattr(info, "trade_mode", None), "unknown"),
        "margin_free": float(getattr(info, "margin_free", 0.0) or 0.0),
        "login": getattr(info, "login", None),
        "server": getattr(info, "server", ""),
    }


# Findings are not all the same thing. A symbol the resolver already renamed for us is a
# note; Algo Trading being off stops every order. Logging both as "TRADING BLOCKED" produced
# an app.log that contradicted itself one line apart, so severity travels with the finding.
BLOCKING = "blocking"   # nothing can trade until this is fixed
WARNING = "warning"     # some trades will be refused, not all
INFO = "info"           # already handled automatically -- shown so it is not a surprise


def _finding(problem, fix, severity=BLOCKING):
    return {"problem": problem, "fix": fix, "severity": severity}


def is_blocking(finding):
    return finding.get("severity", BLOCKING) == BLOCKING


def diagnose_trading(symbol):
    """Ask MT5 exactly why trading is refused, instead of guessing from a retcode.

    Returns a list of {"problem", "fix", "severity"} dicts -- empty means everything checks
    out. This is what turns a repeating 'retcode 10017' into one named, fixable condition.
    Only severity == BLOCKING findings actually stop trading; see is_blocking()."""
    findings = []

    terminal = mt5.terminal_info()
    if terminal is None:
        return [_finding(
            "Not connected to the MT5 terminal at all.",
            "Start MetaTrader 5, log in, then reconnect this bot from the Accounts tab.")]
    if not getattr(terminal, "trade_allowed", False):
        findings.append(_finding(
            "Algo Trading is switched OFF in the MT5 terminal.",
            "Click the 'Algo Trading' button in the MT5 toolbar so it turns green. If it is "
            "already green, check Tools > Options > Expert Advisors > 'Allow algorithmic trading'."))

    account = mt5.account_info()
    if account is None:
        findings.append(_finding(
            "MT5 is running but no trading account is logged in.",
            "Log in to your account in the MT5 terminal (File > Login to Trade Account)."))
    else:
        if not getattr(account, "trade_allowed", False):
            mode = ACCOUNT_TRADE_MODES.get(getattr(account, "trade_mode", None), "unknown")
            findings.append(_finding(
                f"The broker is not allowing trading on this account ({mode} account "
                f"{getattr(account, 'login', '?')} on {getattr(account, 'server', '?')}).",
                "Most often this means you are logged in with the INVESTOR (read-only) password "
                "— log out and log back in with the master/trader password. If that is not it, "
                "the broker has disabled trading server-side; contact them."))
        if float(getattr(account, "margin_free", 0.0) or 0.0) <= 0:
            findings.append(_finding(
                "The account has no free margin.",
                "Close some open positions or reduce risk_percent — there is nothing left to "
                "open a new position with."))

    # resolve_symbol both selects the symbol into Market Watch and, when it cannot, reports
    # what this broker actually calls the instrument.
    resolved, symbol_error = resolve_symbol(symbol)
    if resolved is None:
        # The resolver's message IS the diagnosis (disabled / close-only / wrong name), so it
        # belongs in the problem line rather than buried in the suggested fix.
        findings.append(_finding(
            symbol_error,
            "Pick a symbol this broker actually offers -- the Market Watch window in MT5 "
            "lists the exact names."))
        return findings
    if resolved != symbol:
        # Informational, NOT a blocker: resolve_symbol already mapped it and the engine is
        # trading the resolved name. Reporting this as "TRADING BLOCKED" was flatly untrue.
        findings.append(_finding(
            f"Your broker calls '{symbol}' '{resolved}'. The bot resolved that automatically "
            f"and is trading '{resolved}' — nothing is blocked by this.",
            f"No action needed. If you would rather see one name everywhere, set the symbol "
            f"to '{resolved}' so the dashboard, logs and orders all read the same.",
            INFO))

    symbol = resolved
    info = mt5.symbol_info(symbol)
    if info is None:
        return findings

    trade_mode = getattr(info, "trade_mode", None)
    if trade_mode == getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", object()):
        findings.append(_finding(
            f"The broker has disabled trading on '{symbol}'.",
            "Pick a different symbol, or ask the broker why this one is disabled."))
    elif trade_mode == getattr(mt5, "SYMBOL_TRADE_MODE_CLOSEONLY", object()):
        findings.append(_finding(
            f"'{symbol}' is close-only right now — existing positions can be closed but no "
            f"new ones opened.",
            "Wait for the broker to re-enable opening, or trade a different symbol."))
    elif trade_mode == getattr(mt5, "SYMBOL_TRADE_MODE_LONGONLY", object()):
        findings.append(_finding(
            f"'{symbol}' currently allows BUY orders only.",
            "SELL signals on this symbol will be rejected until the broker lifts the restriction. "
            "BUY signals still trade normally.",
            WARNING))
    elif trade_mode == getattr(mt5, "SYMBOL_TRADE_MODE_SHORTONLY", object()):
        findings.append(_finding(
            f"'{symbol}' currently allows SELL orders only.",
            "BUY signals on this symbol will be rejected until the broker lifts the restriction. "
            "SELL signals still trade normally.",
            WARNING))

    tick = mt5.symbol_info_tick(symbol)
    if tick is None or not getattr(tick, "time", 0):
        findings.append(_finding(
            f"No price quotes are arriving for '{symbol}'.",
            "Enable the symbol in Market Watch and check the terminal is connected."))
    elif (datetime.now().timestamp() - float(tick.time)) > STALE_QUOTE_SECONDS:
        findings.append(_finding(
            f"The market for '{symbol}' looks closed — the last quote is over "
            f"{STALE_QUOTE_SECONDS // 60} minutes old.",
            "Wait for the trading session to open. Orders sent now are rejected."))

    return findings


def get_recent_ticks(symbol, count=50):
    ticks = mt5.copy_ticks_from(symbol, datetime.now(), count, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return []
    return [float(t["bid"]) for t in ticks]
