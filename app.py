"""Flask app: serves dashboard, REST API, owns the engine background thread."""
import copy
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

import analysis.analytics as analytics
import automation.alerts as alerts
import automation.auto_tuner as auto_tuner
import analysis.backtest as backtest
import core.accounts as accounts
import core.config as config
import core.engine as engine
import automation.journal as journal
import core.ml_filter as ml_filter
import core.mt5_bridge as mt5_bridge
import core.persistence as persistence
import automation.watchdog as watchdog

app = Flask(__name__, static_folder="static")

bridge = mt5_bridge
state = config.new_state()
strategy_settings = copy.deepcopy(config.DEFAULT_SETTINGS)
global_settings = copy.deepcopy(config.GLOBAL_SETTINGS)
alert_rules = []
triggered_alerts = []
_next_alert_id = 1
watchlist = []
manual_signals = []
_next_watchlist_id = 1
blackout_windows = []
_next_blackout_id = 1
partial_closed_tickets = set()
account_profiles = []
_next_account_id = 1
active_account_id = None
_was_connected = True

_engine_thread = None
_stop_flag = threading.Event()


def _load_persisted_state():
    saved = persistence.load_all()
    if not saved:
        return
    state.update(saved.get("state", {}))
    strategy_settings.update(saved.get("strategy_settings", {}))
    global_settings.update(saved.get("global_settings", {}))
    watchlist[:] = saved.get("watchlist", [])
    blackout_windows[:] = saved.get("blackout_windows", [])
    account_profiles[:] = saved.get("account_profiles", [])


def _save_persisted_state():
    persistence.save_all({
        "state": state,
        "strategy_settings": strategy_settings,
        "global_settings": global_settings,
        "watchlist": watchlist,
        "blackout_windows": blackout_windows,
        "account_profiles": account_profiles,
    })


_load_persisted_state()


@app.route("/")
def index():
    return send_from_directory("static", "dashboard.html")


@app.route("/api/status")
def status():
    positions = bridge.get_open_positions(state["symbol"])
    equity = bridge.get_account_equity()
    return jsonify({
        "positions": positions,
        "equity": equity,
        "active_strategy": state["active_strategy"],
        "symbol": state["symbol"],
        "timeframe": state["timeframe"],
        "auto_enabled": state["auto_enabled"],
        "triggered_alerts": triggered_alerts,
        "watchlist": watchlist,
        "manual_signals": manual_signals,
        "watchlist_enabled": state["watchlist_enabled"],
        "lock_enabled": state["lock_enabled"],
    })


def _check_lock(passcode):
    if not state.get("lock_enabled", False):
        return True
    return passcode == state.get("lock_passcode", "")


@app.route("/api/select", methods=["POST"])
def select():
    data = request.get_json()
    if "symbol" in data:
        state["symbol"] = data["symbol"]
    if "timeframe" in data:
        state["timeframe"] = data["timeframe"]
    if "strategy" in data:
        state["active_strategy"] = data["strategy"]
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["GET"])
def get_settings():
    strategy = request.args.get("strategy")
    if strategy:
        return jsonify(strategy_settings[strategy])
    return jsonify(strategy_settings)


@app.route("/api/settings", methods=["POST"])
def settings():
    data = request.get_json()
    strategy = data["strategy"]
    incoming = data["settings"]
    editable_keys = set(config.DEFAULT_SETTINGS[strategy].keys())
    for key, value in incoming.items():
        if key in editable_keys:
            strategy_settings[strategy][key] = value
    return jsonify({"ok": True, "settings": strategy_settings[strategy]})


@app.route("/api/global_settings", methods=["POST"])
def set_global_settings():
    data = request.get_json()
    editable_keys = set(config.GLOBAL_SETTINGS.keys())
    for key, value in data.items():
        if key in editable_keys:
            global_settings[key] = value
    return jsonify({"ok": True, "settings": global_settings})


@app.route("/api/auto", methods=["POST"])
def auto():
    data = request.get_json()
    if data["enabled"] and not _check_lock(data.get("passcode")):
        return jsonify({"ok": False, "error": "locked"}), 403
    state["auto_enabled"] = bool(data["enabled"])
    global _engine_thread
    if state["auto_enabled"] and (_engine_thread is None or not _engine_thread.is_alive()):
        _stop_flag.clear()
        _engine_thread = threading.Thread(target=_engine_loop, daemon=True)
        _engine_thread.start()
    if not state["auto_enabled"]:
        _stop_flag.set()
    return jsonify({"ok": True})


@app.route("/api/close_all", methods=["POST"])
def close_all():
    positions = bridge.get_open_positions(state["symbol"])
    for pos in positions:
        bridge.close_position(pos["ticket"], pos["symbol"], pos["volume"], pos["type"],
                               global_settings["slippage_points"])
    return jsonify({"ok": True})


@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    return jsonify(alert_rules)


@app.route("/api/alerts", methods=["POST"])
def post_alert():
    global _next_alert_id
    data = request.get_json()
    rule = {"id": _next_alert_id, "symbol": data["symbol"],
            "condition": data["condition"], "price": data["price"]}
    _next_alert_id += 1
    alert_rules.append(rule)
    return jsonify(rule)


@app.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    alert_rules[:] = [r for r in alert_rules if r["id"] != alert_id]
    return jsonify({"ok": True})


@app.route("/api/alerts/ack/<alert_id>", methods=["POST"])
def ack_alert(alert_id):
    try:
        alert_id_val = int(alert_id)
    except ValueError:
        alert_id_val = alert_id
    triggered_alerts[:] = [t for t in triggered_alerts if t["id"] != alert_id_val]
    return jsonify({"ok": True})


@app.route("/api/journal/<int:ticket>", methods=["GET"])
def get_journal(ticket):
    return jsonify({"note": journal.get_note(ticket)})


@app.route("/api/journal/<int:ticket>", methods=["POST"])
def post_journal(ticket):
    data = request.get_json()
    journal.set_note(ticket, data["note"])
    return jsonify({"ok": True})


@app.route("/api/analytics")
def get_analytics():
    from datetime import datetime, timedelta
    from_date = datetime.now() - timedelta(days=30)
    deals = bridge.get_history_deals(from_date)
    return jsonify(analytics.compute_stats(deals))


@app.route("/api/analytics/per_strategy")
def get_analytics_per_strategy():
    from datetime import datetime, timedelta
    from_date = datetime.now() - timedelta(days=30)
    deals = bridge.get_history_deals(from_date)
    return jsonify(analytics.compute_per_strategy_stats(deals))


@app.route("/api/position_manager/apply_all", methods=["POST"])
def apply_all():
    engine._manage_positions(bridge, global_settings, alert_rules, triggered_alerts, partial_closed_tickets)
    return jsonify({"ok": True})


@app.route("/api/watchlist", methods=["GET"])
def get_watchlist():
    return jsonify(watchlist)


@app.route("/api/watchlist", methods=["POST"])
def post_watchlist():
    global _next_watchlist_id
    data = request.get_json()
    entry = config.new_watchlist_entry(_next_watchlist_id, data["symbol"], data["timeframe"],
                                        data["strategy"], data["mode"])
    _next_watchlist_id += 1
    watchlist.append(entry)
    return jsonify(entry)


@app.route("/api/watchlist/<int:entry_id>", methods=["DELETE"])
def delete_watchlist(entry_id):
    watchlist[:] = [w for w in watchlist if w["id"] != entry_id]
    return jsonify({"ok": True})


@app.route("/api/watchlist/<int:entry_id>/toggle", methods=["POST"])
def toggle_watchlist(entry_id):
    data = request.get_json()
    for w in watchlist:
        if w["id"] == entry_id:
            w["enabled"] = bool(data["enabled"])
    return jsonify({"ok": True})


@app.route("/api/blackouts", methods=["GET"])
def get_blackouts():
    return jsonify(blackout_windows)


@app.route("/api/blackouts", methods=["POST"])
def post_blackout():
    global _next_blackout_id
    data = request.get_json()
    entry = {"id": _next_blackout_id, "start": data["start"], "end": data["end"], "label": data.get("label", "")}
    _next_blackout_id += 1
    blackout_windows.append(entry)
    return jsonify(entry)


@app.route("/api/blackouts/<int:entry_id>", methods=["DELETE"])
def delete_blackout(entry_id):
    blackout_windows[:] = [b for b in blackout_windows if b["id"] != entry_id]
    return jsonify({"ok": True})


@app.route("/api/backtest")
def get_backtest():
    symbol = request.args.get("symbol", state["symbol"])
    timeframe = request.args.get("timeframe", state["timeframe"])
    strategy = request.args.get("strategy", state["active_strategy"])
    bars = int(request.args.get("bars", 200))
    initial_equity = float(request.args.get("initial_equity", 10000))
    rates = bridge.get_rates(symbol, timeframe, bars)
    result = backtest.run_backtest(rates, strategy, strategy_settings[strategy], global_settings, initial_equity)
    return jsonify(result)


@app.route("/api/backtest/sweep", methods=["POST"])
def post_backtest_sweep():
    data = request.get_json()
    symbol = data.get("symbol", state["symbol"])
    timeframe = data.get("timeframe", state["timeframe"])
    strategy = data["strategy"]
    bars = int(data.get("bars", 200))
    initial_equity = float(data.get("initial_equity", 10000))
    param_grid = data["param_grid"]
    rates = bridge.get_rates(symbol, timeframe, bars)
    results = backtest.run_sweep(rates, strategy, strategy_settings[strategy], param_grid,
                                  global_settings, initial_equity)
    return jsonify(results[:10])


@app.route("/api/lock", methods=["POST"])
def set_lock():
    data = request.get_json()
    state["lock_enabled"] = bool(data["enabled"])
    state["lock_passcode"] = data.get("passcode", "")
    return jsonify({"ok": True})


@app.route("/api/watchlist_mode", methods=["POST"])
def set_watchlist_mode():
    data = request.get_json()
    if data["enabled"] and not _check_lock(data.get("passcode")):
        return jsonify({"ok": False, "error": "locked"}), 403
    state["watchlist_enabled"] = bool(data["enabled"])
    return jsonify({"ok": True})


@app.route("/api/analytics/export")
def export_analytics():
    from datetime import datetime, timedelta
    from flask import Response
    import csv
    import io
    from_date = datetime.now() - timedelta(days=30)
    deals = bridge.get_history_deals(from_date)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["ticket", "symbol", "profit", "time"])
    writer.writeheader()
    for d in deals:
        writer.writerow(d)
    return Response(buf.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": "attachment; filename=analytics_export.csv"})


@app.route("/api/accounts", methods=["GET"])
def get_accounts():
    return jsonify([{k: v for k, v in a.items() if k != "password"} for a in account_profiles])


@app.route("/api/accounts", methods=["POST"])
def post_account():
    global _next_account_id
    data = request.get_json()
    acc = accounts.new_account(_next_account_id, data["name"], data.get("path", ""),
                                data.get("login"), data.get("password", ""), data.get("server", ""))
    _next_account_id += 1
    account_profiles.append(acc)
    return jsonify({k: v for k, v in acc.items() if k != "password"})


@app.route("/api/accounts/<int:account_id>", methods=["DELETE"])
def delete_account(account_id):
    account_profiles[:] = [a for a in account_profiles if a["id"] != account_id]
    return jsonify({"ok": True})


@app.route("/api/accounts/<int:account_id>/connect", methods=["POST"])
def connect_account(account_id):
    global active_account_id
    acc = next((a for a in account_profiles if a["id"] == account_id), None)
    if not acc:
        return jsonify({"ok": False, "error": "not found"}), 404
    ok = bridge.connect(path=acc["path"] or None, login=acc["login"],
                         password=acc["password"], server=acc["server"] or None)
    if ok:
        active_account_id = account_id
    return jsonify({"ok": ok})


@app.route("/api/state/save", methods=["POST"])
def save_state_endpoint():
    _save_persisted_state()
    return jsonify({"ok": True})


@app.route("/api/ml/train", methods=["POST"])
def train_ml_filter():
    from datetime import datetime, timedelta
    body = request.get_json(silent=True) or {}
    days = int(body.get("days", 30))
    from_date = datetime.now() - timedelta(days=days)
    deals = bridge.get_history_deals(from_date)
    magic_to_strategy = {v: k for k, v in analytics.STRATEGY_MAGIC.items()}
    features, labels = [], []
    for d in deals:
        strategy = magic_to_strategy.get(d.get("magic"))
        if strategy is None:
            continue
        deal_time = datetime.fromtimestamp(d["time"])
        features.append(ml_filter.build_features(strategy, deal_time.hour, deal_time.weekday()))
        labels.append(1 if d["profit"] > 0 else 0)
    if len(features) < 10:
        return jsonify({"ok": False, "error": "not enough labeled trades yet (need at least 10)"}), 400
    weights = ml_filter.train(features, labels)
    ml_filter.save_weights(weights)
    return jsonify({"ok": True, "trained_on": len(features)})


@app.route("/api/auto_tune/run", methods=["POST"])
def run_auto_tune():
    from datetime import datetime, timedelta
    from_date = datetime.now() - timedelta(days=30)
    deals = bridge.get_history_deals(from_date)
    per_strategy = analytics.compute_per_strategy_stats(deals)
    min_trades = global_settings.get("auto_tune_min_trades", 10)
    min_pf = global_settings.get("auto_tune_min_profit_factor", 0.8)
    disable = auto_tuner.suggest_strategy_disable(per_strategy, min_pf, min_trades)
    best = auto_tuner.suggest_best_strategy(per_strategy, min_trades)
    switched = False
    if global_settings.get("auto_tune_enabled", False) and state["active_strategy"] in disable and best:
        state["active_strategy"] = best
        switched = True
    return jsonify({"disable_suggested": disable, "best_strategy": best, "switched_to": best if switched else None})


def _engine_loop():
    global _was_connected
    while not _stop_flag.is_set():
        connected = watchdog.check_connection(bridge)
        if _was_connected and not connected:
            watchdog.notify_webhook(global_settings.get("watchdog_webhook_url", ""),
                                     "MT5 Bot: lost connection to MT5 terminal")
        _was_connected = connected

        if state.get("watchlist_enabled", False):
            engine.run_watchlist_once(bridge, watchlist, strategy_settings, global_settings,
                                       0.0, 0.0, alert_rules, triggered_alerts, manual_signals,
                                       blackout_windows=blackout_windows,
                                       partial_closed_tickets=partial_closed_tickets)
        else:
            engine.run_once(bridge, state, strategy_settings, global_settings,
                             daily_pnl_percent=0.0, drawdown_percent=0.0,
                             alert_rules=alert_rules, triggered_alerts=triggered_alerts,
                             blackout_windows=blackout_windows,
                             partial_closed_tickets=partial_closed_tickets)
        _save_persisted_state()
        time.sleep(5)


if __name__ == "__main__":
    bridge.connect()
    app.run(host="127.0.0.1", port=7500)
