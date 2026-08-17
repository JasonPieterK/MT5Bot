"""Flask app: serves dashboard, REST API, owns the engine background thread."""
import copy
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

import config
import engine
import mt5_bridge

app = Flask(__name__, static_folder="static")

bridge = mt5_bridge
state = config.new_state()
strategy_settings = copy.deepcopy(config.DEFAULT_SETTINGS)
global_settings = copy.deepcopy(config.GLOBAL_SETTINGS)

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


def _engine_loop():
    while not _stop_flag.is_set():
        engine.run_once(bridge, state, strategy_settings, global_settings,
                         daily_pnl_percent=0.0, drawdown_percent=0.0)
        time.sleep(5)


if __name__ == "__main__":
    bridge.connect()
    app.run(host="127.0.0.1", port=7500)
