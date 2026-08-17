"""Flask app: serves dashboard, REST API, owns the engine background thread."""
import copy
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

import analytics
import alerts
import backtest
import config
import engine
import journal
import mt5_bridge

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

_engine_thread = None
_stop_flag = threading.Event()


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
    })


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


@app.route("/api/position_manager/apply_all", methods=["POST"])
def apply_all():
    engine._manage_positions(bridge, global_settings, alert_rules, triggered_alerts)
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


def _engine_loop():
    while not _stop_flag.is_set():
        if state.get("watchlist_enabled", False):
            engine.run_watchlist_once(bridge, watchlist, strategy_settings, global_settings,
                                       0.0, 0.0, alert_rules, triggered_alerts, manual_signals,
                                       blackout_windows=blackout_windows)
        else:
            engine.run_once(bridge, state, strategy_settings, global_settings,
                             daily_pnl_percent=0.0, drawdown_percent=0.0,
                             alert_rules=alert_rules, triggered_alerts=triggered_alerts,
                             blackout_windows=blackout_windows)
        time.sleep(5)


if __name__ == "__main__":
    bridge.connect()
    app.run(host="127.0.0.1", port=7500)
