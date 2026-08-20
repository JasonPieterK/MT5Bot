"""Background trading loop. run_once() is one iteration — called repeatedly by the
Flask-owned thread in app.py so the whole loop is testable without real threading/sleep."""
import csv
import os
import time
from datetime import datetime, timezone

import analysis.analytics as analytics
import analysis.indicators as indicators
import automation.app_logger as app_logger
import automation.execution_log as execution_log
import automation.json_logger as json_logger
import automation.schedule_filter as schedule_filter
import automation.swap_filter as swap_filter
import core.correlation as correlation
import core.ensemble as ensemble
import core.htf_filter as htf_filter
import core.ml_filter as ml_filter
import core.mt5_retcodes as mt5_retcodes
import core.portfolio_risk as portfolio_risk
import core.risk_manager as rm
import core.session_filter as session_filter
import core.spread_quality as spread_quality
import core.tick_momentum as tick_momentum
import automation.trailing_manager as trailing_manager
import automation.watchdog as watchdog
import analysis.volatility_regime as volatility_regime
from strategies import trend, scalping, smc, grid, pivot_breakout

STRATEGY_MODULES = {
    "trend": trend,
    "scalping": scalping,
    "smc": smc,
    "pivot_breakout": pivot_breakout,
}

LOG_PATH = os.path.join("logs", "trades.csv")

# (symbol, strategy) -> timestamp of the last closed bar we acted on. Strategies are pure
# functions of the last N bars, so without this one M15 crossover re-fires on every 5-second
# tick until max_concurrent_trades caps it.
# ponytail: in-memory only -- a restart re-arms the current bar. Persist it if double entries
# across restarts ever show up in logs/trades.csv.
_last_acted_bar = {}


# (symbol, strategy) -> the reason code we last refused to trade on. A signal stays true for
# the whole bar, so an undeduped "blocked because X" warning repeats every 5-second tick and
# buries the log it was written to make readable.
_last_block_reason = {}


# (symbol, strategy) -> the most recent evaluation, as structured data rather than log text.
# This is the twin of what log_block writes: same facts, queryable, so /api/why_no_trade can
# answer "why is it not opening a trade?" without the user reading logs/app.log and inferring.
# ponytail: in-memory only, last evaluation per pair. Persist or keep a ring buffer of the
# last N evaluations if "what happened an hour ago" ever becomes the question.
_last_eval = {}

# Outcomes, in the order a tick can reach them.
OUTCOME_EVALUATING = "evaluating"     # a signal exists and is being taken through the gates
OUTCOME_NO_SIGNAL = "no_signal"       # healthy and common: the strategy sees no setup
OUTCOME_WAITING_BAR = "waiting_bar"   # already acted on this bar; waiting for the next one
OUTCOME_BLOCKED = "blocked"           # a signal existed and a named gate refused it
OUTCOME_ORDER_SENT = "order_sent"     # signal found, every gate passed, order went out


# Auto mode's most recent decision (core/auto_mode.decide), plus the last line logged for
# it. Kept here rather than in app.py so /api/why_no_trade reads Auto's reasoning from the
# same place it reads every gate's -- the engine's own record of what it just decided.
_auto_decision = None
_last_auto_line = None


def reset_bar_gate():
    """Clears the one-order-per-bar memory (used by tests and by a mode change)."""
    global _auto_decision, _last_auto_line
    _last_acted_bar.clear()
    _last_block_reason.clear()
    _last_eval.clear()
    _auto_decision = None
    _last_auto_line = None


def record_auto_decision(decision):
    """Store Auto's current decision and log its plain-English line -- once per distinct
    line, exactly like log_block, because the same decision repeats every 5-second tick and
    would otherwise bury the log it exists to make readable."""
    global _auto_decision, _last_auto_line
    _auto_decision = decision
    line = (decision or {}).get("line") or ""
    if decision and decision.get("enabled") and line and line != _last_auto_line:
        _last_auto_line = line
        app_logger.info(line)
    return decision


def get_auto_decision():
    """Auto's current decision, or None when Auto has not been consulted yet."""
    return _auto_decision


def record_evaluation(symbol, strategy_name, outcome, **fields):
    """Store what just happened to this (symbol, strategy). `signal`/`sl`/`tp` carry over
    from the same tick's earlier record unless explicitly given, so a block recorded by
    log_block -- which does not know the signal -- still reports which signal was refused."""
    key = (symbol, strategy_name)
    prev = _last_eval.get(key) or {}
    entry = {
        "symbol": symbol,
        "strategy": strategy_name,
        "outcome": outcome,
        "at": datetime.now(timezone.utc).isoformat(),
        "signal": fields.pop("signal", prev.get("signal")),
        "sl": fields.pop("sl", prev.get("sl")),
        "tp": fields.pop("tp", prev.get("tp")),
        "gate": None,
        "message": "",
        "details": {},
        "remedy": None,
    }
    entry.update(fields)
    _last_eval[key] = entry
    return entry


def get_evaluations():
    """Every (symbol, strategy) the engine has evaluated since the last mode change."""
    return sorted(_last_eval.values(), key=lambda e: (e["symbol"], e["strategy"]))


# Latched on/off states that log on transition only. log_block already de-duplicates the
# per-tick gate refusals; these are the states that never went through it.
_state_latch = {}


def log_state_change(key, active, on_message, off_message):
    """Log `on_message` the tick a state becomes active and `off_message` the tick it clears.

    A kill switch that re-logs the same line every 5 seconds buries the log it exists to make
    readable -- the user's log had ~40 identical MAX DRAWDOWN lines in three minutes. The
    information is kept in full: both the moment it fired and the moment it stopped are still
    there, exactly once each."""
    was = _state_latch.get(key, False)
    if bool(active) == was:
        return False
    _state_latch[key] = bool(active)
    message = on_message if active else off_message
    if message:
        app_logger.warning(message)
    return True


def reset_state_latches():
    """Forget every latched state, so the next tick re-logs whatever is still true."""
    _state_latch.clear()


def log_block(symbol, strategy_name, code, message, details=None, remedy=None, **fields):
    """Says which gate stopped a trade and why -- once per distinct reason, not per tick.
    Every gate in the order path routes its refusal through here, so "the bot did nothing
    for an hour" is answerable from logs/app.log instead of by guesswork.

    The structured record is written on EVERY call, before the log de-duplication, so
    /api/why_no_trade always shows the current state even when the log line is suppressed."""
    record_evaluation(symbol, strategy_name, OUTCOME_BLOCKED, gate=code, message=message,
                       details=details or {}, remedy=remedy, **fields)
    key = (symbol, strategy_name)
    if _last_block_reason.get(key) == code:
        return
    _last_block_reason[key] = code
    app_logger.warning(f"Trade skipped on {symbol} ({strategy_name}): {message}")


def _clear_block(symbol, strategy_name, code=None):
    """Forget the last refusal so the next distinct one is logged. With `code`, only forgets
    that specific reason -- clearing unconditionally would re-arm every other gate's message
    on the next tick and bring the per-tick spam straight back."""
    key = (symbol, strategy_name)
    if code is None or _last_block_reason.get(key) == code:
        _last_block_reason.pop(key, None)


def _current_bar_time(rates):
    if rates is None or "time" not in getattr(rates, "columns", []) or len(rates) == 0:
        return None
    return rates["time"].iloc[-1]


def _bar_gate_allows(symbol, strategy_name, rates):
    """True if we have not already acted on this symbol+strategy for this closed bar."""
    bar_time = _current_bar_time(rates)
    if bar_time is None:
        return True  # no bar timestamps available (backtest frames) -- nothing to gate on
    return _last_acted_bar.get((symbol, strategy_name)) != bar_time


def _mark_bar_acted(symbol, strategy_name, rates):
    bar_time = _current_bar_time(rates)
    if bar_time is not None:
        _last_acted_bar[(symbol, strategy_name)] = bar_time


def log_trade(row):
    os.makedirs("logs", exist_ok=True)
    write_header = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["time", "symbol", "strategy", "signal", "lots", "sl", "tp", "retcode"])
        writer.writerow(row)

    fields = ["time", "symbol", "strategy", "signal", "lots", "sl", "tp", "retcode"]
    json_logger.log_event("trade", dict(zip(fields, row)))

    _time, symbol, strategy, signal, lots, sl, tp, retcode = row
    if signal == "ERROR":
        app_logger.error(f"Watchlist entry {symbol} ({strategy}) failed: {retcode}")
    elif retcode in (10009, "10009"):
        app_logger.info(f"Order placed: {signal} {lots} lots {symbol} ({strategy}) sl={sl} tp={tp}")
    else:
        app_logger.warning(f"Order REJECTED: {signal} {lots} lots {symbol} ({strategy}) — "
                            f"{mt5_retcodes.explain(retcode)}")


def _should_flatten(drawdown_percent, global_settings):
    if rm.should_flatten_all(drawdown_percent, global_settings["max_drawdown_percent"]):
        return True
    if global_settings.get("schedule_filter_enabled", False):
        if schedule_filter.should_flatten_for_schedule(
                datetime.now(timezone.utc),
                global_settings.get("schedule_disable_weekday", 4),
                global_settings.get("schedule_disable_hour_utc", 21)):
            return True
    return False


def _flatten_or_explain(bridge, symbol, strategy_name, open_positions, drawdown_percent,
                         global_settings):
    """True when the kill-switch is active and this tick must stop here.

    With positions open it closes them and says so. With none open it still says so: a
    drawdown or schedule kill-switch that has already flattened leaves the bot doing nothing
    indefinitely, and that silence is indistinguishable from a quiet market."""
    if not _should_flatten(drawdown_percent, global_settings):
        return False
    if open_positions:
        app_logger.warning(f"Flattening {len(open_positions)} position(s) on {symbol}: "
                            f"drawdown/schedule kill-switch triggered")
        for pos in open_positions:
            bridge.close_position(pos["ticket"], pos["symbol"], pos["volume"], pos["type"],
                                   global_settings["slippage_points"])
    else:
        log_block(symbol, strategy_name, "kill_switch",
                  f"the drawdown/schedule kill-switch is active (drawdown "
                  f"{drawdown_percent:.2f}%, limit {global_settings['max_drawdown_percent']}%) "
                  f"— no new trades until it clears")
    return True


def _manage_positions(bridge, global_settings, partial_closed_tickets=None):
    """Automated babysitting of every open position: trailing stop, break-even and partial
    take-profit, driven by the active profile's settings. This is what closes positions that
    would otherwise run unbounded, so it stays even though its manual UI is gone."""
    partial_closed_tickets = partial_closed_tickets if partial_closed_tickets is not None else set()

    # Two settings can contradict each other here: the stop slider set to Off asks for a
    # position with no stop, while trailing/break-even exist to put one on. apply_trailing
    # treats "no stop yet" as precisely the case to fix, so the order opened naked and got a
    # stop back on the next tick -- the slider said one thing and the bot did another.
    # The explicit choice wins; say so once rather than silently overriding it.
    if stop_is_optional(global_settings):
        log_state_change(
            "stop_mgmt_standdown", True,
            "Automatic stop management (trailing stop, break-even, partial take-profit) is "
            "standing down: the stop slider is set to Off, so positions are left with no "
            "stop as you asked. Nothing will close a losing trade automatically.",
            "Automatic stop management is active again — the stop slider is no longer Off.")
        return
    log_state_change("stop_mgmt_standdown", False, "", 
                      "Automatic stop management is active again — the stop slider is no longer Off.")

    positions = bridge.get_open_positions()
    for pos in positions:
        if global_settings.get("trailing_enabled", False):
            if trailing_manager.apply_trailing(
                    bridge, pos, global_settings.get("trailing_distance_points", 100)):
                app_logger.info(f"Trailing stop moved on ticket {pos['ticket']} ({pos['symbol']})")
        if global_settings.get("breakeven_enabled", False):
            if trailing_manager.apply_breakeven(
                    bridge, pos,
                    global_settings.get("breakeven_trigger_points", 100),
                    global_settings.get("breakeven_offset_points", 10)):
                app_logger.info(f"Break-even applied on ticket {pos['ticket']} ({pos['symbol']})")
        if global_settings.get("partial_tp_enabled", False):
            if trailing_manager.apply_partial_tp(
                    bridge, pos,
                    global_settings.get("partial_tp_trigger_points", 100),
                    global_settings.get("partial_tp_close_fraction", 0.5),
                    partial_closed_tickets):
                app_logger.info(f"Partial take-profit closed on ticket {pos['ticket']} ({pos['symbol']})")


def _passes_signal_filters(bridge, symbol, timeframe, signal, rates_df, global_settings, open_positions,
                            strategy_name=None):
    """Returns (ok, reason_code, message, details). Each filter used to return a bare False,
    so when the bot sat idle there was no way to tell which of a dozen gates was responsible.
    `details` carries the measured value and the threshold it failed against, so the UI can
    show "0.11 vs 0.20" rather than a sentence the user has to parse."""
    if global_settings.get("spread_quality_filter_enabled", False):
        if not spread_quality.is_spread_acceptable(
                rates_df, max_ratio=global_settings.get("spread_quality_max_ratio", 1.5)):
            return False, "spread", ("the current spread is wide relative to its recent "
                                     "average (spread quality filter)"), {
                "max_ratio": global_settings.get("spread_quality_max_ratio", 1.5),
                "current_spread": float(rates_df["spread"].iloc[-1]) if len(rates_df) and "spread" in rates_df else None,
            }

    if global_settings.get("tick_momentum_filter_enabled", False):
        ticks = bridge.get_recent_ticks(symbol, count=global_settings.get("tick_momentum_count", 50))
        score = tick_momentum.momentum_score(ticks)
        if not tick_momentum.signal_matches_momentum(
                signal, score, threshold=global_settings.get("tick_momentum_threshold", 0.2)):
            return False, "tick_momentum", (f"recent tick momentum ({score:.2f}) disagrees with "
                                            f"the {signal} signal"), {
                "momentum_score": round(score, 4),
                "threshold": global_settings.get("tick_momentum_threshold", 0.2),
                "signal": signal,
            }

    if global_settings.get("ml_filter_enabled", False) and strategy_name is not None:
        weights = ml_filter.load_weights()
        if weights is not None:
            now = datetime.now(timezone.utc)
            features = ml_filter.build_features(strategy_name, now.hour, now.weekday())
            proba = ml_filter.predict_proba(weights, features)
            floor = global_settings.get("ml_filter_min_probability", 0.5)
            if proba < floor:
                return False, "ml_filter", (f"the ML filter puts this trade's win probability "
                                            f"at {proba:.2f}, below the {floor} floor"), {
                    "probability": round(float(proba), 4), "floor": floor}

    if global_settings.get("session_filter_enabled", False):
        now_hour = datetime.now(timezone.utc).hour
        if not session_filter.in_session(now_hour, global_settings.get("session_start_hour", 0),
                                          global_settings.get("session_end_hour", 23)):
            return False, "session", (f"the current hour ({now_hour}:00 UTC) is outside the "
                                      f"configured trading session"), {
                "hour_utc": now_hour,
                "session_start_hour": global_settings.get("session_start_hour", 0),
                "session_end_hour": global_settings.get("session_end_hour", 23),
            }

    if global_settings.get("correlation_filter_enabled", False):
        if not correlation.check_correlation_allowed(
                open_positions, symbol, global_settings.get("correlation_max_positions", 2)):
            return False, "correlation", ("too many open positions already correlated with "
                                          "this symbol"), {
                "max_correlated_positions": global_settings.get("correlation_max_positions", 2),
                "open_positions": len(open_positions),
            }

    if global_settings.get("htf_filter_enabled", False):
        htf_rates = bridge.get_rates(symbol, global_settings.get("htf_timeframe", "H1"), 60)
        bias = htf_filter.get_bias(htf_rates)
        if not htf_filter.signal_matches_bias(signal, bias):
            return False, "htf", (f"the {global_settings.get('htf_timeframe', 'H1')} trend is "
                                  f"{bias}, which disagrees with the {signal} signal"), {
                "htf_timeframe": global_settings.get("htf_timeframe", "H1"),
                "htf_bias": bias, "signal": signal}

    if global_settings.get("volatility_regime_filter_enabled", False):
        # regime_for, not classify_regime: the sticky version, so this filter does not turn
        # itself on and off while ATR hovers on a band edge.
        if volatility_regime.regime_for(symbol, rates_df) == "HIGH":
            return False, "volatility", ("the volatility regime is HIGH — price is moving far "
                                         "more than usual, so stops are unreliable"), {
                "regime": "HIGH"}

    return True, "", "", {}


# One plain-English fix per signal filter, so the dashboard can say what to do rather than
# only what happened. Every one of these filters is optional and off by default.
FILTER_REMEDIES = {
    "spread": "Wait for the spread to narrow, or turn off the spread-quality filter on the "
              "Signal filters page.",
    "tick_momentum": "The very recent order flow disagrees with the signal. Turn off the "
                     "tick-momentum filter, or lower its threshold, on the Signal filters page.",
    "ml_filter": "Retrain the ML filter on more closed trades, lower its minimum probability, "
                 "or turn it off on the Signal filters page.",
    "session": "Widen the trading-hours window, or turn the session filter off, on the Signal "
               "filters page. Hours are UTC.",
    "correlation": "Close a correlated position, raise the correlated-position limit, or turn "
                   "the correlation filter off on the Signal filters page.",
    "htf": "The higher timeframe disagrees with the entry. Turn off the higher-timeframe "
           "filter, or change its timeframe, on the Signal filters page.",
    "volatility": "Wait for volatility to settle, or turn off the volatility-regime filter on "
                  "the Signal filters page.",
}


def effective_max_lot(broker_max_lot, global_settings):
    """The lot ceiling actually in force: the smaller of the broker's own volume_max and the
    active profile's max_lot. 0 or absent means "no profile ceiling, broker's limit stands"."""
    cap = float(global_settings.get("max_lot") or 0.0)
    return min(broker_max_lot, cap) if cap > 0 else broker_max_lot


# The stop a strategy would actually use, as a multiple of ATR, when it has no opinion.
DEFAULT_SL_ATR_MULTIPLE = 1.5


def risk_reality(bridge, symbol, timeframe, strategy_name, strategy_settings, global_settings):
    """Configured risk vs the risk this account can actually EXPRESS on this symbol.

    At $5.4M equity against a 50-lot broker cap, a 1% risk request cannot be sized -- the
    position that would risk 1% is several hundred lots. The user then sees "1%" on screen
    while the engine refuses every trade. This computes both numbers up front, using the
    symbol's current ATR as the stop distance, so the gap is visible BEFORE a signal appears
    rather than only in a refusal buried in the log. Returns None when it cannot be computed.
    """
    try:
        equity = bridge.get_account_equity()
        rates = bridge.get_rates(symbol, timeframe, SIGNAL_BARS)
        if rates is None or len(rates) == 0 or equity <= 0:
            return None
        atr = _atr_now(rates)
        params = (strategy_settings or {}).get(strategy_name) or {}
        sl_multiple = float(params.get("sl_atr_multiple", DEFAULT_SL_ATR_MULTIPLE))
        sl_distance = atr * sl_multiple
        tick_value, tick_size = bridge.get_symbol_tick_economics(symbol)
        min_lot, broker_max_lot, _step = bridge.get_symbol_volume_limits(symbol)
        max_lot = effective_max_lot(broker_max_lot, global_settings)
        per_lot = rm.loss_per_lot(sl_distance, tick_value, tick_size)
        if per_lot <= 0:
            return None
        configured = float(global_settings.get("risk_percent", 0.0))
        expressible = max_lot * per_lot / equity * 100
        min_expressible = min_lot * per_lot / equity * 100
        effective = min(configured, expressible)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "equity": round(equity, 2),
            "atr": round(atr, 8),
            "sl_atr_multiple": sl_multiple,
            "sl_distance": round(sl_distance, 8),
            "per_lot": round(per_lot, 6),
            "lots_for_configured_risk": round(equity * (configured / 100) / per_lot, 2),
            "broker_max_lot": broker_max_lot,
            "max_lot": max_lot,
            "min_lot": min_lot,
            "configured_risk_percent": configured,
            "effective_risk_percent": round(effective, 4),
            "max_expressible_risk_percent": round(expressible, 4),
            "min_expressible_risk_percent": round(min_expressible, 4),
            "lot_cap_binds": configured > expressible,
            "min_lot_overrisks": configured < min_expressible,
            "block_when_lot_capped": bool(global_settings.get("block_when_lot_capped", True)),
        }
    except Exception:  # a read-only readout must never take a request or a tick down
        return None


def _passes_risk_gates(bridge, global_settings, open_positions, equity, symbol="",
                        strategy_name=""):
    if global_settings.get("swap_filter_enabled", False):
        if swap_filter.is_swap_blackout(
                datetime.now(timezone.utc),
                global_settings.get("swap_block_hours_before_rollover", 1),
                global_settings.get("swap_rollover_hour_utc", 21)):
            log_block(symbol, strategy_name, "swap",
                      "inside the swap/rollover blackout window", details={
                          "rollover_hour_utc": global_settings.get("swap_rollover_hour_utc", 21),
                          "hours_before": global_settings.get("swap_block_hours_before_rollover", 1),
                      }, remedy="Nothing to fix — this clears itself once the rollover window passes.")
            return False

    if global_settings.get("portfolio_risk_filter_enabled", False):
        cap = global_settings.get("max_portfolio_risk_percent", 20.0)
        # Real broker tick economics, same source as lot sizing -- this used to assume
        # 5-digit FX for every instrument and was 100x out on gold.
        current = portfolio_risk.calc_portfolio_risk_percent(
            open_positions, equity, bridge.get_symbol_tick_economics)
        if current >= cap:
            log_block(symbol, strategy_name, "portfolio_risk",
                      f"open positions across the account already risk {current:.2f}% of "
                      f"equity, and the portfolio risk cap is {cap}%", details={
                          "current_portfolio_risk_percent": round(current, 3),
                          "max_portfolio_risk_percent": cap,
                          "open_positions": len(open_positions),
                      }, remedy="Close some open positions, or raise max_portfolio_risk_percent.")
            return False

    return True


MARGIN_USAGE_LIMIT = 0.5  # never commit more than half of free margin to one new order

_logged_symbol_mappings = set()


def resolve_symbol_or_skip(bridge, symbol, strategy_name=""):
    """Every symbol entering the trading path goes through here, so orders, rates and log
    lines all refer to the same instrument under the broker's own name. Returns None (and
    says why) when the symbol cannot be resolved."""
    resolved, error = bridge.resolve_symbol(symbol)
    if resolved is None:
        app_logger.error(f"Cannot trade '{symbol}': {error}")
        record_evaluation(symbol, strategy_name, OUTCOME_BLOCKED, gate="symbol",
                           signal=None, message=f"'{symbol}' cannot be resolved to a symbol this "
                           f"broker trades: {error}",
                           details={"requested_symbol": symbol},
                           remedy="Open Market Watch in MT5 and copy the exact symbol name your "
                                  "broker uses (many add a suffix, e.g. EURUSD#).")
        return None
    if resolved != symbol and (symbol, resolved) not in _logged_symbol_mappings:
        # Logged once per mapping -- this would otherwise repeat every 5-second tick.
        _logged_symbol_mappings.add((symbol, resolved))
        app_logger.info(f"Symbol '{symbol}' is called '{resolved}' at this broker — "
                         f"trading '{resolved}'")
    return resolved

# Retcodes that all mean "trading is disabled" without saying which of the half-dozen
# possible reasons it is. When one lands we ask MT5 directly instead of guessing.
TRADE_DISABLED_RETCODES = (10017, 10026, 10027)
DIAGNOSE_COOLDOWN_SECONDS = 300
_last_diagnosis_at = 0.0


def diagnose_and_log(bridge, symbol, force=False, after_rejection=False):
    """Run the trade-disabled preflight and write each finding to the app log. Rate-limited:
    a rejection that repeats every 5 seconds must not repeat the diagnosis every 5 seconds.

    `after_rejection` says whether the broker actually refused an order. Only then may an
    empty result be reported as "the broker says trading is disabled but every check
    passed" -- the same run started from the dashboard's Run diagnostic button means the
    opposite, and saying it anyway put a false, permanent-looking WARNING about a perfectly
    tradeable symbol in the user's log every time they pressed the button."""
    global _last_diagnosis_at
    now = time.monotonic()
    if not force and (now - _last_diagnosis_at) < DIAGNOSE_COOLDOWN_SECONDS:
        return None
    _last_diagnosis_at = now
    try:
        findings = bridge.diagnose_trading(symbol)
    except Exception as exc:  # diagnosis must never take the trading loop down with it
        app_logger.error(f"Could not run the trading diagnostic for {symbol}: {exc}")
        return None
    if not findings:
        if after_rejection:
            app_logger.warning(
                f"Broker says trading is disabled for {symbol}, but every terminal, account "
                f"and symbol check passed. Check the MT5 Journal tab for the broker's own "
                f"reason.")
        else:
            app_logger.info(
                f"Trading diagnostic for {symbol}: every terminal, account and symbol check "
                f"passed — nothing is blocking trading on this symbol.")
        return findings
    for f in findings:
        log_finding(f)
    return findings


# Each severity gets the log level and the wording that is actually true of it. Logging an
# auto-resolved symbol rename as "TRADING BLOCKED" at ERROR, one line after the INFO line
# saying the bot had resolved it and was trading, is the contradiction this fixes.
_FINDING_LOG = {
    "blocking": (app_logger.error, "TRADING BLOCKED"),
    "warning": (app_logger.warning, "TRADING LIMITED"),
    "info": (app_logger.info, "Diagnostic note"),
}


def log_finding(finding):
    log, label = _FINDING_LOG.get(finding.get("severity", "blocking"), _FINDING_LOG["blocking"])
    log(f"{label} — {finding['problem']} FIX: {finding['fix']}")


def check_stops(bridge, symbol, sl, tp, strategy_name=""):
    """Broker minimum stop distance. An order that violates it is rejected with retcode
    10016 forever, so it is cheaper to not send it and say why."""
    ok, reason = bridge.check_stops_valid(symbol, sl, tp)
    if not ok:
        log_block(symbol, strategy_name, "stop_distance",
                  f"the broker refuses this stop/target: {reason}",
                  details={"sl": sl, "tp": tp, "broker_reason": reason},
                  remedy="The stop or target sits inside the broker's minimum stop distance. "
                         "Use a wider stop multiple, or a timeframe with more range per bar.")
    return ok


def fit_to_free_margin(bridge, symbol, direction, lots, min_lot, lot_step, strategy_name=""):
    """Return the largest affordable lot size (possibly the requested one), or None if even
    min_lot doesn't fit. Reducing rather than skipping keeps a legitimate signal alive on a
    thin account; skipping only happens when nothing at all is affordable."""
    required = bridge.get_required_margin(symbol, direction, lots)
    if required is None or required <= 0:
        return lots  # MT5 can't price the margin -- let the broker be the gate
    free = bridge.get_free_margin()
    budget = free * MARGIN_USAGE_LIMIT
    if required <= budget:
        return lots
    affordable = lots * (budget / required)
    steps = int(affordable / lot_step + 1e-9)
    reduced = round(steps * lot_step, 2)
    if reduced < min_lot:
        log_block(symbol, strategy_name, "free_margin",
                  f"{lots} lots needs {required:.2f} of margin but only {free:.2f} is free, and "
                  f"the smallest size the broker allows ({min_lot}) still does not fit inside "
                  f"the {int(MARGIN_USAGE_LIMIT * 100)}% free-margin budget",
                  details={"required_margin": round(required, 2), "free_margin": round(free, 2),
                            "budget": round(budget, 2), "requested_lots": lots, "min_lot": min_lot},
                  remedy="Close some open positions to release margin, or lower risk_percent so "
                         "each position is smaller.")
        return None
    app_logger.warning(
        f"Order size reduced on {symbol}: {lots} lots needs {required:.2f} margin, only "
        f"{free:.2f} free — placing {reduced} lots instead")
    return reduced


def _place_order_logged(bridge, symbol, signal, lots, sl, tp, slippage_points, strategy_name, global_settings):
    magic = analytics.STRATEGY_MAGIC.get(strategy_name, 0)
    start = time.monotonic()
    ok, retcode = bridge.place_order(symbol, signal, lots, sl=sl, tp=tp,
                                      slippage_points=slippage_points, magic=magic)
    latency_ms = (time.monotonic() - start) * 1000
    execution_log.log_execution(symbol, latency_ms, retcode, requoted=not ok)

    if not ok and retcode in TRADE_DISABLED_RETCODES:
        diagnose_and_log(bridge, symbol, after_rejection=True)

    if ok and global_settings.get("trade_notify_enabled", False):
        watchdog.notify_webhook(
            global_settings.get("watchdog_webhook_url", ""),
            f"MT5 Bot: opened {signal} {lots} {symbol} ({strategy_name})")

    return ok, retcode


def _calc_confidence(bridge, symbol, entry, sl, tp, global_settings):
    confidence = 1.0
    if global_settings.get("confidence_sizing_enabled", False) and sl is not None and tp is not None:
        # No stop or no target means no reward:risk to scale confidence by; leave it at 1.0
        # rather than crash on abs(entry - None).
        confidence *= rm.calc_confidence(entry, sl, tp)
    if global_settings.get("streak_sizing_enabled", False):
        from datetime import timedelta
        recent = bridge.get_history_deals(datetime.now(timezone.utc) - timedelta(days=2))
        results = [d["profit"] for d in recent[-10:]]
        confidence *= rm.calc_streak_multiplier(results)
    return confidence


# Defaults for the quality gates, used when a caller passes a partial global_settings dict.
DEFAULT_MIN_REWARD_RISK = 1.5
DEFAULT_MAX_SL_ATR_MULTIPLE = 3.0
ATR_PERIOD = 14


def _atr_now(rates):
    """Last ATR value, or 0.0 when the frame is too short to have one. 0.0 means "unknown"
    to check_stop_sanity, which then only enforces that a stop exists at all."""
    try:
        value = float(indicators.atr(rates, period=ATR_PERIOD).iloc[-1])
    except Exception:
        return 0.0
    return 0.0 if value != value else value  # NaN


def stop_is_optional(global_settings):
    """True when the user has deliberately set the stop slider to Off.

    check_stop_sanity refuses any signal with no stop, which is right by default. But if the
    override is on and the stop multiple is 0, that refusal would reject every single signal
    while the UI happily showed "Off" -- the bot would look armed and never trade. Honour the
    choice and warn instead; the warning is in the UI at the point the choice is made."""
    return bool(global_settings.get("bot_stop_override_enabled")) and \
        float(global_settings.get("bot_sl_atr_multiple") or 0) <= 0


def target_is_optional(global_settings):
    """True when the user has deliberately set the take-profit slider to Off. Same reasoning
    as stop_is_optional: a gate that needs a target cannot judge one that was removed on
    purpose, so it stands down rather than refusing the trade."""
    return bool(global_settings.get("bot_stop_override_enabled")) and         float(global_settings.get("bot_tp_atr_multiple") or 0) <= 0


def reward_risk_is_measurable(sl, tp, global_settings):
    """False when a level the ratio needs is missing *because the user removed it*.

    A reward:risk ratio with no stop or no target is not a bad ratio, it is no ratio at all.
    Refusing the trade there would accept the slider setting and then silently disobey it --
    exactly what stop_is_optional exists to prevent, one gate lower."""
    if sl is None and stop_is_optional(global_settings):
        return False
    if tp is None and target_is_optional(global_settings):
        return False
    return True


def stop_override_unavailable(global_settings, atr, entry=0.0):
    """True when the sliders are in charge but their distance cannot be computed.

    The caller must skip the trade in that case. Falling back to the strategy's own levels
    would place a trade on numbers the user overrode precisely to stop using -- silently,
    with nothing on screen to say it happened."""
    if not global_settings.get("bot_stop_override_enabled"):
        return False
    needs_distance = (float(global_settings.get("bot_sl_atr_multiple") or 0) > 0 or
                       float(global_settings.get("bot_tp_atr_multiple") or 0) > 0)
    if not needs_distance:
        return False          # both sliders Off: no distance needed, nothing to fail
    return not atr or atr <= 0 or entry is None


def apply_stop_override(entry, sl, tp, atr, direction, global_settings):
    """(sl, tp) after the Dashboard sliders have had their say.

    With the override on, the sliders decide BOTH levels, always. A slider at Off yields
    None for that side -- never the strategy's level. When the distance cannot be computed
    the result is (None, None) and stop_override_unavailable() tells the caller to skip the
    trade; the strategy's numbers are not reinstated behind the user's back."""
    if not global_settings.get("bot_stop_override_enabled"):
        return sl, tp
    sl_mult = float(global_settings.get("bot_sl_atr_multiple") or 0)
    tp_mult = float(global_settings.get("bot_tp_atr_multiple") or 0)
    if not atr or atr <= 0 or entry is None:
        return None, None
    away = 1 if str(direction).upper() == "BUY" else -1
    new_sl = entry - away * atr * sl_mult if sl_mult > 0 else None
    new_tp = entry + away * atr * tp_mult if tp_mult > 0 else None
    return new_sl, new_tp


def _passes_quality_gates(symbol, strategy_name, sl, tp, rates, global_settings):
    """Trade-quality discipline, applied before any broker call because it costs nothing.

    Both gates here target one documented failure: this account's own 825-trade group won
    84% of the time and still lost $5.7M, by taking tiny profits against unbounded losses.
    A reward:risk floor and a stop that is actually near the price are what that group
    was missing."""
    entry = rates["close"].iloc[-1] if len(rates) else None
    atr = _atr_now(rates)

    max_sl_atr = global_settings.get("max_sl_atr_multiple", DEFAULT_MAX_SL_ATR_MULTIPLE)
    ok, reason = rm.check_stop_sanity(entry, sl, atr, max_sl_atr)
    if not ok and sl is None and stop_is_optional(global_settings):
        # The user set the stop slider to Off. Refusing here would block every signal while
        # the setting read "Off" -- accepted, then silently disobeyed.
        log_state_change(
            f"nostop:{symbol}:{strategy_name}", True,
            f"{symbol} ({strategy_name}): opening with NO STOP LOSS — the stop slider is set "
            f"to Off, so nothing closes this trade if it moves against you.",
            f"{symbol} ({strategy_name}): stop losses are back on — the stop slider is no "
            f"longer Off.")
        ok = True
    elif sl is not None:
        log_state_change(f"nostop:{symbol}:{strategy_name}", False, "",
                          f"{symbol} ({strategy_name}): stop losses are back on — the stop "
                          f"slider is no longer Off.")
    if not ok:
        log_block(symbol, strategy_name, "stop_sanity", reason, details={
            "entry": entry, "sl": sl, "tp": tp, "atr": round(atr, 8),
            "sl_distance": abs(entry - sl) if (entry and sl) else None,
            "sl_atr_multiple": round(abs(entry - sl) / atr, 2) if (entry and sl and atr) else None,
            "max_sl_atr_multiple": max_sl_atr,
        }, remedy=("Widen max_sl_atr_multiple, or use a strategy/timeframe whose stop sits "
                   "closer to price. A missing or very distant stop is an unbounded loss."))
        return False

    min_rr = global_settings.get("min_reward_risk", DEFAULT_MIN_REWARD_RISK)
    ok, reason = rm.check_reward_risk(entry, sl, tp, min_rr)
    if not ok and not reward_risk_is_measurable(sl, tp, global_settings):
        ok = True  # deliberately no stop and/or no target — there is no ratio to floor
    if not ok:
        log_block(symbol, strategy_name, "reward_risk", reason, details={
            "entry": entry, "sl": sl, "tp": tp,
            "reward_risk": round(rm.reward_risk(entry, sl, tp), 3),
            "min_reward_risk": min_rr,
        }, remedy=(f"This setup aims to win less than {min_rr}x what it risks. Either raise the "
                   f"strategy's take-profit multiple, or lower min_reward_risk — but this floor "
                   f"is what stops the 84%-win-rate/large-loss pattern in this account's history."))
        return False
    return True


def _lot_size_expresses_configured_risk(symbol, strategy_name, equity, sl_distance,
                                         tick_value, tick_size, min_lot, max_lot, lots,
                                         global_settings):
    """The broker caps lot size (50.0 on every symbol at this account's broker). Above a
    certain equity the cap binds on essentially every trade, and when it does, size stops
    being a function of stop distance and becomes a constant -- which is the same sizing
    behaviour as the account's own blown-up trade group, where the median lot was exactly
    the broker maximum.

    This never fails silently: the clamp is always logged with the numbers, and by default
    the trade is refused rather than sent at a risk the user did not choose."""
    floor = rm.min_lot_overrisk_report(equity, global_settings["risk_percent"], sl_distance,
                                        tick_value, tick_size, min_lot, lots)
    if floor is not None:
        # The dangerous direction: the broker's smallest tradeable size is already bigger
        # than the risk allows, so this trade risks MORE than configured, not less.
        message = (
            f"BROKER MINIMUM LOT EXCEEDS YOUR RISK on {symbol}: "
            f"{floor['configured_risk_percent']}% risk over this {sl_distance:.5f} stop "
            f"allows only {floor['requested_lots']:.4f} lots, but the smallest the "
            f"broker will trade is {floor['min_lot']}. That position would risk "
            f"{floor['actual_risk_percent']:.2f}% of equity — MORE than you configured. "
            f"Trade REFUSED. Use a tighter stop, a smaller-contract symbol, or accept "
            f"the higher risk by raising risk_percent.")
        log_block(symbol, strategy_name, "min_lot", message,
                  details=dict(floor, symbol=symbol, sl_distance=sl_distance),
                  remedy=(f"The broker's {floor['min_lot']}-lot minimum on {symbol} risks "
                          f"{floor['actual_risk_percent']:.3f}% of equity over this stop. Either "
                          f"accept that by raising risk_percent to at least that, or trade a "
                          f"symbol with a smaller contract size."))
        return False

    report = rm.lot_clamp_report(equity, global_settings["risk_percent"], sl_distance,
                                 tick_value, tick_size, max_lot, lots)
    if report is None:
        return True

    message = (
        f"Broker lot cap reached on {symbol}: {report['configured_risk_percent']}% risk over "
        f"this {sl_distance:.5f} stop would need {report['requested_lots']:.1f} lots, but the "
        f"broker allows at most {report['max_lot']}. Trading {lots} lots instead, which risks "
        f"{report['actual_risk_percent']:.3f}% of equity rather than "
        f"{report['configured_risk_percent']}% — a smaller position than requested, with the "
        f"same stop loss."
    )
    details = dict(report, symbol=symbol, sl_distance=sl_distance, actual_lots=lots)
    remedy = (f"Nothing to fix — the trade goes ahead at {lots} lots. This account cannot "
              f"express more than {report['max_expressible_risk_percent']:.3f}% on one "
              f"{symbol} trade at this stop distance, because the broker caps volume at "
              f"{report['max_lot']} lots. To have the risk figure you set match the risk "
              f"actually taken, set risk_percent at or below "
              f"{report['max_expressible_risk_percent']:.3f}.")

    if global_settings.get("block_when_lot_capped", False):
        # Off by default. Capped sizing is safer than requested, so blocking it refuses a
        # trade for being too small; this exists only for users who want the risk figure they
        # set to be exactly the risk taken, or nothing.
        log_block(symbol, strategy_name, "lot_clamp", message +
                   " Trade REFUSED because block_when_lot_capped is on.",
                   details=details, remedy=remedy)
        return False

    log_block(symbol, strategy_name, "lot_clamp_warn", message,
               details=details, remedy=remedy)
    return True


def _execute_signal(bridge, symbol, timeframe, strategy_name, signal, sl, tp, rates,
                     open_positions, global_settings, daily_pnl_percent, drawdown_percent):
    """The single path every entry takes: filters, risk gates, sizing, stop validation,
    margin check, order, log."""
    # The Dashboard sliders replace whatever the strategy proposed, before any gate reads
    # them -- otherwise the reward:risk floor and stop-sanity check would judge levels that
    # are not the ones being sent to the broker.
    entry_price = rates["close"].iloc[-1] if len(rates) else None
    atr_now = _atr_now(rates)
    if stop_override_unavailable(global_settings, atr_now, entry_price):
        # The sliders are in charge but their distance is uncomputable. Skipping is the only
        # honest option: trading on the strategy's levels would ignore the override, and
        # trading with no levels would ignore the slider's actual values.
        log_block(symbol, strategy_name, "stop_override_unavailable",
                   "Your stop/target sliders set the levels for every trade, but the "
                   "volatility reading (ATR) needed to place them could not be computed "
                   "right now, so no trade was opened. The strategy's own levels were NOT "
                   "used instead.",
                   details={"atr": atr_now, "entry": entry_price,
                            "sl_atr_multiple": global_settings.get("bot_sl_atr_multiple"),
                            "tp_atr_multiple": global_settings.get("bot_tp_atr_multiple")},
                   remedy=("Usually a symbol that has just been added and has not finished "
                           "loading history. It clears by itself within a few candles. To "
                           "trade meanwhile, tick 'Let each strategy choose its own levels'."))
        return
    sl, tp = apply_stop_override(entry_price, sl, tp, atr_now, signal, global_settings)

    record_evaluation(symbol, strategy_name, OUTCOME_EVALUATING, signal=signal, sl=sl, tp=tp,
                       gate=None, message="", details={}, remedy=None)

    if not _bar_gate_allows(symbol, strategy_name, rates):
        # Deliberately not logged: this is the normal per-tick state, not a refusal. It IS
        # recorded, because "already traded this bar" is a perfectly good answer to
        # "why has nothing happened in the last ten minutes?".
        record_evaluation(symbol, strategy_name, OUTCOME_WAITING_BAR,
                           message=f"{strategy_name} already acted on the current {timeframe} bar "
                                   f"on {symbol}. One entry per bar — waiting for the next one.",
                           details={"timeframe": timeframe})
        return

    if not _passes_quality_gates(symbol, strategy_name, sl, tp, rates, global_settings):
        return

    ok, code, message, details = _passes_signal_filters(
        bridge, symbol, timeframe, signal, rates, global_settings, open_positions, strategy_name)
    if not ok:
        log_block(symbol, strategy_name, code, message, details=details,
                  remedy=FILTER_REMEDIES.get(code))
        return

    # max_concurrent_trades is an account-wide cap, counted across every symbol.
    all_positions = bridge.get_open_positions()
    allowed, reason = rm.check_trade_allowed(
        open_position_count=len(all_positions),
        max_concurrent_trades=global_settings["max_concurrent_trades"],
        daily_pnl_percent=daily_pnl_percent,
        daily_loss_limit_percent=global_settings["daily_loss_limit_percent"],
        drawdown_percent=drawdown_percent,
        max_drawdown_percent=global_settings["max_drawdown_percent"],
    )
    if not allowed:
        log_block(symbol, strategy_name, "risk_limits", reason, details={
            "open_positions": len(all_positions),
            "max_concurrent_trades": global_settings["max_concurrent_trades"],
            "daily_pnl_percent": round(daily_pnl_percent, 3),
            "daily_loss_limit_percent": global_settings["daily_loss_limit_percent"],
            "drawdown_percent": round(drawdown_percent, 3),
            "max_drawdown_percent": global_settings["max_drawdown_percent"],
        }, remedy="Close a position, or raise the limit this hit (max concurrent trades, daily "
                  "loss limit, or max drawdown) on the trading-profile card.")
        return

    equity = bridge.get_account_equity()

    # all_positions, not this symbol's: an "aggregate portfolio risk" cap that only counted
    # one symbol was not an aggregate cap at all.
    if not _passes_risk_gates(bridge, global_settings, all_positions, equity, symbol,
                               strategy_name):
        return

    if strategy_name == "grid" and grid.equity_stop_triggered(drawdown_percent):
        log_block(symbol, strategy_name, "grid_equity_stop",
                  f"the grid strategy's hard equity stop is hit ({drawdown_percent}% drawdown)",
                  details={"drawdown_percent": drawdown_percent},
                  remedy="This is a fixed safety limit inside the grid strategy, not a setting. "
                         "Recover the drawdown or switch strategy.")
        return

    entry_price = bridge.get_rates(symbol, timeframe, 1)["close"].iloc[-1]
    # sl may legitimately be None (stop slider Off). 0.0 means "no measurable risk per
    # lot", which calc_lot_size answers with min_lot -- the smallest position, which is the
    # right answer when the loss is unbounded.
    sl_distance = abs(entry_price - sl) if sl is not None else 0.0
    confidence = _calc_confidence(bridge, symbol, entry_price, sl, tp, global_settings)
    min_lot, broker_max_lot, lot_step = bridge.get_symbol_volume_limits(symbol)
    max_lot = effective_max_lot(broker_max_lot, global_settings)
    tick_value, tick_size = bridge.get_symbol_tick_economics(symbol)
    lots = rm.calc_lot_size(
        equity=equity, risk_percent=global_settings["risk_percent"],
        sl_distance_price=sl_distance, tick_value=tick_value, tick_size=tick_size,
        confidence=confidence, lot_step=lot_step, min_lot=min_lot, max_lot=max_lot,
    )

    if not _lot_size_expresses_configured_risk(symbol, strategy_name, equity, sl_distance,
                                                tick_value, tick_size, min_lot, max_lot, lots,
                                                global_settings):
        return

    if strategy_name == "grid":
        current_total_lots = sum(p["volume"] for p in open_positions)
        if not grid.total_lots_within_cap(current_total_lots, lots):
            log_block(symbol, strategy_name, "grid_lot_cap",
                      f"{current_total_lots} + {lots} lots would exceed the grid strategy's hard "
                      f"cap of {grid.HARD_MAX_TOTAL_LOTS} total lots",
                      details={"current_total_lots": current_total_lots, "new_lots": lots,
                                "hard_max_total_lots": grid.HARD_MAX_TOTAL_LOTS},
                      remedy="Close some grid positions. This cap is fixed in the strategy.")
            return

    if not check_stops(bridge, symbol, sl, tp, strategy_name):
        return

    lots = fit_to_free_margin(bridge, symbol, signal, lots, min_lot, lot_step, strategy_name)
    if lots is None:
        return

    _mark_bar_acted(symbol, strategy_name, rates)
    _clear_block(symbol, strategy_name)
    ok, retcode = _place_order_logged(bridge, symbol, signal, lots, sl, tp,
                                       global_settings["slippage_points"], strategy_name, global_settings)
    log_trade([datetime.now(timezone.utc).isoformat(), symbol, strategy_name, signal, lots, sl, tp, retcode])
    record_evaluation(symbol, strategy_name, OUTCOME_ORDER_SENT, gate=None, remedy=None,
                       message=(f"Signal found and every gate passed — {signal} {lots} lots of "
                                f"{symbol} sent to the broker"
                                + ("" if ok else f", which REJECTED it: "
                                   f"{mt5_retcodes.explain(retcode)}")),
                       details={"lots": lots, "sl": sl, "tp": tp, "retcode": retcode,
                                "accepted": bool(ok), "equity": equity})


def run_once(bridge, state, strategy_settings, global_settings, daily_pnl_percent, drawdown_percent,
             partial_closed_tickets=None):
    symbol, timeframe = state["symbol"], state["timeframe"]
    strategy_name = state["active_strategy"]
    symbol = resolve_symbol_or_skip(bridge, symbol, strategy_name)
    if symbol is None:
        return
    open_positions = bridge.get_open_positions(symbol)

    if _flatten_or_explain(bridge, symbol, strategy_name, open_positions, drawdown_percent,
                            global_settings):
        return

    _manage_positions(bridge, global_settings, partial_closed_tickets)

    signal, sl, tp, rates = _get_signal_for(bridge, symbol, timeframe, strategy_name,
                                             strategy_settings, global_settings, open_positions)

    if signal == "NONE":
        return

    _execute_signal(bridge, symbol, timeframe, strategy_name, signal, sl, tp, rates,
                     open_positions, global_settings, daily_pnl_percent, drawdown_percent)


SIGNAL_BARS = 100


def _get_signal_for(bridge, symbol, timeframe, strategy_name, strategy_settings, global_settings,
                     open_positions):
    """Every strategy, including grid and ensemble, resolves here."""
    rates = bridge.get_rates(symbol, timeframe, SIGNAL_BARS)
    if rates is None or len(rates) == 0:
        # Not the same thing as "no signal". A symbol just added to Market Watch answers
        # with zero bars until the terminal finishes syncing history; feeding that to a
        # strategy produces a silent NONE that is indistinguishable from a quiet market.
        log_block(symbol, strategy_name, "no_bars",
                  f"no {timeframe} bars returned yet — the terminal is still loading history "
                  f"for this symbol. Waiting; this usually clears within a few seconds.",
                  details={"timeframe": timeframe, "bars": 0}, signal=None,
                  remedy="Usually nothing to do. If it persists, add the symbol to Market Watch "
                         "in MT5 and check the terminal is connected.")
        return "NONE", None, None, rates

    _clear_block(symbol, strategy_name, "no_bars")
    if strategy_name == "grid":
        signal, sl, tp = grid.get_signal(
            rates, strategy_settings["grid"], current_grid_levels=len(open_positions))
    elif strategy_name == "ensemble":
        signal, sl, tp, _agreeing = ensemble.get_ensemble_signal(
            rates, strategy_settings, min_agree=global_settings.get("ensemble_min_agree", 2))
    else:
        module = STRATEGY_MODULES[strategy_name]
        signal, sl, tp = module.get_signal(rates, strategy_settings[strategy_name])

    if signal == "NONE":
        # By far the most common state, and the one users mistake for a fault. Recorded
        # explicitly so the dashboard can say "the strategy simply sees no setup" instead of
        # leaving a blank where an explanation should be.
        record_evaluation(symbol, strategy_name, OUTCOME_NO_SIGNAL, signal=None, sl=None,
                           tp=None, gate=None, remedy=None,
                           message=(f"No entry setup. The {strategy_name} strategy looked at the "
                                    f"last {len(rates)} {timeframe} bars of {symbol} and its "
                                    f"entry conditions are not met. Nothing is blocked — there "
                                    f"is simply nothing to trade right now."),
                           details={"timeframe": timeframe, "bars": int(len(rates)),
                                     "last_close": float(rates["close"].iloc[-1]),
                                     "last_bar_time": _bar_time_iso(rates)})
    return signal, sl, tp, rates


def _bar_time_iso(rates):
    """The last bar's timestamp as an ISO string, or None for frames without one."""
    bar = _current_bar_time(rates)
    if bar is None:
        return None
    try:
        return datetime.fromtimestamp(float(bar), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(bar)
