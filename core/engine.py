"""Background trading loop. run_once() is one iteration — called repeatedly by the
Flask-owned thread in app.py so the whole loop is testable without real threading/sleep."""
import csv
import os
from datetime import datetime, timezone

import automation.alerts as alerts
import automation.news_filter as news_filter
import core.correlation as correlation
import core.htf_filter as htf_filter
import core.risk_manager as rm
import core.session_filter as session_filter
import automation.trailing_manager as trailing_manager
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


def _manage_positions(bridge, global_settings, alert_rules, triggered_alerts):
    positions = bridge.get_open_positions()
    for pos in positions:
        if global_settings.get("trailing_enabled", False):
            trailing_manager.apply_trailing(
                bridge, pos, global_settings.get("trailing_distance_points", 100))
        if global_settings.get("breakeven_enabled", False):
            trailing_manager.apply_breakeven(
                bridge, pos,
                global_settings.get("breakeven_trigger_points", 100),
                global_settings.get("breakeven_offset_points", 10))

    triggered = alerts.check_price_alerts(bridge, alert_rules)
    for rule in triggered:
        alert_rules.remove(rule)
        triggered_alerts.append(rule)

    if alerts.check_margin_alert(bridge, global_settings.get("margin_alert_level_percent", 100.0)):
        triggered_alerts.append({"id": "margin", "type": "margin", "message": "margin level below threshold"})


def _passes_signal_filters(bridge, symbol, timeframe, signal, rates_df, global_settings, open_positions):
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
             alert_rules=None, triggered_alerts=None, blackout_windows=None):
    open_positions = bridge.get_open_positions(state["symbol"])

    if rm.should_flatten_all(drawdown_percent, global_settings["max_drawdown_percent"]):
        for pos in open_positions:
            bridge.close_position(pos["ticket"], pos["symbol"], pos["volume"], pos["type"],
                                   global_settings["slippage_points"])
        return

    _manage_positions(bridge, global_settings, alert_rules if alert_rules is not None else [],
                       triggered_alerts if triggered_alerts is not None else [])

    strategy_name = state["active_strategy"]
    if strategy_name == "grid":
        rates = bridge.get_rates(state["symbol"], state["timeframe"], 60)
        signal, sl, tp = grid.get_signal(
            rates, strategy_settings["grid"], current_grid_levels=len(open_positions),
        )
    else:
        module = STRATEGY_MODULES[strategy_name]
        rates = bridge.get_rates(state["symbol"], state["timeframe"], 100)
        signal, sl, tp = module.get_signal(rates, strategy_settings[strategy_name])

    if signal == "NONE":
        return

    if news_filter.is_blackout_active(datetime.now(timezone.utc), blackout_windows or []):
        return

    if not _passes_signal_filters(bridge, state["symbol"], state["timeframe"], signal, rates,
                                   global_settings, open_positions):
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
    entry_price = bridge.get_rates(state["symbol"], state["timeframe"], 1)["close"].iloc[-1]
    sl_distance = abs(entry_price - sl)
    confidence = _calc_confidence(bridge, state["symbol"], entry_price, sl, tp, global_settings)
    lots = rm.calc_lot_size(
        equity=equity, risk_percent=global_settings["risk_percent"],
        sl_distance_price=sl_distance, pip_value_per_lot=10, point=0.0001, confidence=confidence,
    )

    ok, retcode = bridge.place_order(
        state["symbol"], signal, lots, sl=sl, tp=tp,
        slippage_points=global_settings["slippage_points"],
    )
    log_trade([datetime.now(timezone.utc).isoformat(), state["symbol"], strategy_name, signal, lots, sl, tp, retcode])


def run_watchlist_once(bridge, watchlist, strategy_settings, global_settings,
                        daily_pnl_percent, drawdown_percent, alert_rules, triggered_alerts, manual_signals,
                        blackout_windows=None):
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
                       triggered_alerts if triggered_alerts is not None else [])


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

    if not _passes_signal_filters(bridge, symbol, timeframe, signal, rates, global_settings, open_positions):
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
    entry_price = bridge.get_rates(symbol, timeframe, 1)["close"].iloc[-1]
    sl_distance = abs(entry_price - sl)
    confidence = _calc_confidence(bridge, symbol, entry_price, sl, tp, global_settings)
    lots = rm.calc_lot_size(
        equity=equity, risk_percent=global_settings["risk_percent"],
        sl_distance_price=sl_distance, pip_value_per_lot=10, point=0.0001, confidence=confidence,
    )
    ok, retcode = bridge.place_order(symbol, signal, lots, sl=sl, tp=tp,
                                      slippage_points=global_settings["slippage_points"])
    log_trade([datetime.now(timezone.utc).isoformat(), symbol, strategy_name, signal, lots, sl, tp, retcode])
