"""Background trading loop. run_once() is one iteration — called repeatedly by the
Flask-owned thread in app.py so the whole loop is testable without real threading/sleep."""
import csv
import os
import time
from datetime import datetime, timezone

import analysis.analytics as analytics
import automation.alerts as alerts
import automation.app_logger as app_logger
import automation.execution_log as execution_log
import automation.json_logger as json_logger
import automation.news_filter as news_filter
import automation.schedule_filter as schedule_filter
import automation.swap_filter as swap_filter
import core.correlation as correlation
import core.ensemble as ensemble
import core.htf_filter as htf_filter
import core.ml_filter as ml_filter
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
        app_logger.warning(f"Order REJECTED: {signal} {lots} lots {symbol} ({strategy}) — retcode {retcode}")


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


def _manage_positions(bridge, global_settings, alert_rules, triggered_alerts, partial_closed_tickets=None):
    partial_closed_tickets = partial_closed_tickets if partial_closed_tickets is not None else set()
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

    triggered = alerts.check_price_alerts(bridge, alert_rules)
    for rule in triggered:
        alert_rules.remove(rule)
        triggered_alerts.append(rule)
        app_logger.info(f"Price alert triggered: {rule['symbol']} {rule['condition']} {rule['price']}")

    if alerts.check_margin_alert(bridge, global_settings.get("margin_alert_level_percent", 100.0)):
        triggered_alerts.append({"id": "margin", "type": "margin", "message": "margin level below threshold"})


def _passes_signal_filters(bridge, symbol, timeframe, signal, rates_df, global_settings, open_positions,
                            strategy_name=None):
    if global_settings.get("spread_quality_filter_enabled", False):
        if not spread_quality.is_spread_acceptable(
                rates_df, max_ratio=global_settings.get("spread_quality_max_ratio", 1.5)):
            return False

    if global_settings.get("tick_momentum_filter_enabled", False):
        ticks = bridge.get_recent_ticks(symbol, count=global_settings.get("tick_momentum_count", 50))
        score = tick_momentum.momentum_score(ticks)
        if not tick_momentum.signal_matches_momentum(
                signal, score, threshold=global_settings.get("tick_momentum_threshold", 0.2)):
            return False

    if global_settings.get("ml_filter_enabled", False) and strategy_name is not None:
        weights = ml_filter.load_weights()
        if weights is not None:
            now = datetime.now(timezone.utc)
            features = ml_filter.build_features(strategy_name, now.hour, now.weekday())
            proba = ml_filter.predict_proba(weights, features)
            if proba < global_settings.get("ml_filter_min_probability", 0.5):
                return False

    if global_settings.get("session_filter_enabled", False):
        now_hour = datetime.now(timezone.utc).hour
        if not session_filter.in_session(now_hour, global_settings.get("session_start_hour", 0),
                                          global_settings.get("session_end_hour", 23)):
            return False

    if global_settings.get("correlation_filter_enabled", False):
        if not correlation.check_correlation_allowed(
                open_positions, symbol, global_settings.get("correlation_max_positions", 2)):
            return False

    if global_settings.get("htf_filter_enabled", False):
        htf_rates = bridge.get_rates(symbol, global_settings.get("htf_timeframe", "H1"), 60)
        bias = htf_filter.get_bias(htf_rates)
        if not htf_filter.signal_matches_bias(signal, bias):
            return False

    if global_settings.get("volatility_regime_filter_enabled", False):
        if volatility_regime.classify_regime(rates_df) == "HIGH":
            return False

    return True


def _passes_risk_gates(bridge, global_settings, open_positions, equity):
    if global_settings.get("swap_filter_enabled", False):
        if swap_filter.is_swap_blackout(
                datetime.now(timezone.utc),
                global_settings.get("swap_block_hours_before_rollover", 1),
                global_settings.get("swap_rollover_hour_utc", 21)):
            return False

    if global_settings.get("portfolio_risk_filter_enabled", False):
        if not portfolio_risk.check_portfolio_risk_allowed(
                open_positions, equity, global_settings.get("max_portfolio_risk_percent", 20.0)):
            return False

    return True


def _place_order_logged(bridge, symbol, signal, lots, sl, tp, slippage_points, strategy_name, global_settings):
    magic = analytics.STRATEGY_MAGIC.get(strategy_name, 0)
    start = time.monotonic()
    ok, retcode = bridge.place_order(symbol, signal, lots, sl=sl, tp=tp,
                                      slippage_points=slippage_points, magic=magic)
    latency_ms = (time.monotonic() - start) * 1000
    execution_log.log_execution(symbol, latency_ms, retcode, requoted=not ok)

    if ok and global_settings.get("trade_notify_enabled", False):
        watchdog.notify_webhook(
            global_settings.get("watchdog_webhook_url", ""),
            f"MT5 Bot: opened {signal} {lots} {symbol} ({strategy_name})")

    return ok, retcode


def _calc_confidence(bridge, symbol, entry, sl, tp, global_settings):
    confidence = 1.0
    if global_settings.get("confidence_sizing_enabled", False):
        confidence *= rm.calc_confidence(entry, sl, tp)
    if global_settings.get("streak_sizing_enabled", False):
        from datetime import timedelta
        recent = bridge.get_history_deals(datetime.now(timezone.utc) - timedelta(days=2))
        results = [d["profit"] for d in recent[-10:]]
        confidence *= rm.calc_streak_multiplier(results)
    return confidence


def run_once(bridge, state, strategy_settings, global_settings, daily_pnl_percent, drawdown_percent,
             alert_rules=None, triggered_alerts=None, blackout_windows=None, partial_closed_tickets=None):
    open_positions = bridge.get_open_positions(state["symbol"])

    if _should_flatten(drawdown_percent, global_settings):
        if open_positions:
            app_logger.warning(f"Flattening {len(open_positions)} position(s): drawdown/schedule kill-switch triggered")
        for pos in open_positions:
            bridge.close_position(pos["ticket"], pos["symbol"], pos["volume"], pos["type"],
                                   global_settings["slippage_points"])
        return

    _manage_positions(bridge, global_settings, alert_rules if alert_rules is not None else [],
                       triggered_alerts if triggered_alerts is not None else [], partial_closed_tickets)

    strategy_name = state["active_strategy"]
    if strategy_name == "grid":
        rates = bridge.get_rates(state["symbol"], state["timeframe"], 60)
        signal, sl, tp = grid.get_signal(
            rates, strategy_settings["grid"], current_grid_levels=len(open_positions),
        )
    elif strategy_name == "ensemble":
        rates = bridge.get_rates(state["symbol"], state["timeframe"], 100)
        signal, sl, tp, agreeing = ensemble.get_ensemble_signal(
            rates, strategy_settings, min_agree=global_settings.get("ensemble_min_agree", 2))
    else:
        module = STRATEGY_MODULES[strategy_name]
        rates = bridge.get_rates(state["symbol"], state["timeframe"], 100)
        signal, sl, tp = module.get_signal(rates, strategy_settings[strategy_name])

    if signal == "NONE":
        return

    if news_filter.is_blackout_active(datetime.now(timezone.utc), blackout_windows or []):
        return

    if not _passes_signal_filters(bridge, state["symbol"], state["timeframe"], signal, rates,
                                   global_settings, open_positions, strategy_name):
        return

    allowed, reason = rm.check_trade_allowed(
        open_position_count=len(open_positions),
        max_concurrent_trades=global_settings["max_concurrent_trades"],
        daily_pnl_percent=daily_pnl_percent,
        daily_loss_limit_percent=global_settings["daily_loss_limit_percent"],
        drawdown_percent=drawdown_percent,
        max_drawdown_percent=global_settings["max_drawdown_percent"],
    )
    if not allowed:
        return

    equity = bridge.get_account_equity()

    if not _passes_risk_gates(bridge, global_settings, open_positions, equity):
        return

    entry_price = bridge.get_rates(state["symbol"], state["timeframe"], 1)["close"].iloc[-1]
    sl_distance = abs(entry_price - sl)
    confidence = _calc_confidence(bridge, state["symbol"], entry_price, sl, tp, global_settings)
    lots = rm.calc_lot_size(
        equity=equity, risk_percent=global_settings["risk_percent"],
        sl_distance_price=sl_distance, pip_value_per_lot=10, point=0.0001, confidence=confidence,
    )

    ok, retcode = _place_order_logged(bridge, state["symbol"], signal, lots, sl, tp,
                                       global_settings["slippage_points"], strategy_name, global_settings)
    log_trade([datetime.now(timezone.utc).isoformat(), state["symbol"], strategy_name, signal, lots, sl, tp, retcode])


def run_watchlist_once(bridge, watchlist, strategy_settings, global_settings,
                        daily_pnl_percent, drawdown_percent, alert_rules, triggered_alerts, manual_signals,
                        blackout_windows=None, partial_closed_tickets=None):
    for entry in watchlist:
        if not entry["enabled"]:
            continue
        try:
            _run_watchlist_entry(bridge, entry, strategy_settings, global_settings,
                                  daily_pnl_percent, drawdown_percent, manual_signals, blackout_windows)
        except Exception as exc:
            log_trade([datetime.now(timezone.utc).isoformat(), entry["symbol"], entry["strategy"],
                       "ERROR", 0, None, None, str(exc)])

    _manage_positions(bridge, global_settings, alert_rules if alert_rules is not None else [],
                       triggered_alerts if triggered_alerts is not None else [], partial_closed_tickets)


def _run_watchlist_entry(bridge, entry, strategy_settings, global_settings,
                          daily_pnl_percent, drawdown_percent, manual_signals, blackout_windows=None):
    symbol, timeframe, strategy_name = entry["symbol"], entry["timeframe"], entry["strategy"]
    module = STRATEGY_MODULES[strategy_name]
    rates = bridge.get_rates(symbol, timeframe, 100)
    signal, sl, tp = module.get_signal(rates, strategy_settings[strategy_name])

    if signal == "NONE":
        return

    if entry["mode"] == "alert_only":
        manual_signals.append({"symbol": symbol, "strategy": strategy_name, "signal": signal, "sl": sl, "tp": tp})
        return

    if news_filter.is_blackout_active(datetime.now(timezone.utc), blackout_windows or []):
        return

    open_positions = bridge.get_open_positions()

    if not _passes_signal_filters(bridge, symbol, timeframe, signal, rates, global_settings, open_positions,
                                   strategy_name):
        return

    allowed, reason = rm.check_trade_allowed(
        open_position_count=len(open_positions),
        max_concurrent_trades=global_settings["max_concurrent_trades"],
        daily_pnl_percent=daily_pnl_percent,
        daily_loss_limit_percent=global_settings["daily_loss_limit_percent"],
        drawdown_percent=drawdown_percent,
        max_drawdown_percent=global_settings["max_drawdown_percent"],
    )
    if not allowed:
        return

    equity = bridge.get_account_equity()

    if not _passes_risk_gates(bridge, global_settings, open_positions, equity):
        return

    entry_price = bridge.get_rates(symbol, timeframe, 1)["close"].iloc[-1]
    sl_distance = abs(entry_price - sl)
    confidence = _calc_confidence(bridge, symbol, entry_price, sl, tp, global_settings)
    lots = rm.calc_lot_size(
        equity=equity, risk_percent=global_settings["risk_percent"],
        sl_distance_price=sl_distance, pip_value_per_lot=10, point=0.0001, confidence=confidence,
    )
    ok, retcode = _place_order_logged(bridge, symbol, signal, lots, sl, tp,
                                       global_settings["slippage_points"], strategy_name, global_settings)
    log_trade([datetime.now(timezone.utc).isoformat(), symbol, strategy_name, signal, lots, sl, tp, retcode])
