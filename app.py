"""Flask app: serves dashboard, REST API, owns the engine background thread."""
import atexit
import copy
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

import analysis.analytics as analytics
import analysis.indicators as indicators
import automation.app_logger as app_logger
import automation.auto_tuner as auto_tuner
import analysis.volatility_regime as volatility_regime
import core.auto_mode as auto_mode
import core.config as config
import core.engine as engine
import automation.journal as journal
import core.ml_filter as ml_filter
import core.mt5_bridge as mt5_bridge
import core.mt5_status_sync as mt5_status_sync
import core.persistence as persistence
import core.profiles as profiles
import core.single_instance as single_instance
import automation.watchdog as watchdog

app = Flask(__name__, static_folder="static")


@app.errorhandler(Exception)
def handle_unhandled_error(e):
    """The detail goes to logs/app.log; the browser gets a reference id. Exception text
    routinely carries absolute local paths (FileNotFoundError on logs/app_state.json) and
    other internals that have no business in an HTTP response body.

    A client error is not a server fault. Werkzeug's own HTTPExceptions (400 on a malformed
    JSON body, 404, 405) already carry the right status and a safe, caller-facing message,
    so they are returned as they stand. Relabelling them 500 and dumping a stack trace told
    the user their bot had crashed when in fact their request was simply wrong."""
    import traceback
    import uuid
    if isinstance(e, HTTPException):
        return jsonify({"ok": False, "error": e.description, "status": e.code}), e.code
    error_id = uuid.uuid4().hex[:8]
    app_logger.error(f"Unhandled error [{error_id}] on {request.method} {request.path}: "
                      f"{e}\n{traceback.format_exc()}")
    return jsonify({"ok": False, "error_id": error_id,
                    "error": f"Something went wrong handling this request "
                              f"(reference {error_id}). The details are in logs/app.log."}), 500

bridge = mt5_bridge
state = config.new_state()
strategy_settings = copy.deepcopy(config.DEFAULT_SETTINGS)
global_settings = copy.deepcopy(config.GLOBAL_SETTINGS)
partial_closed_tickets = set()
_was_connected = True

_engine_thread = None
_stop_flag = threading.Event()

# Manual (human-placed) orders get their own magic so analytics can tell them apart from
# any strategy's trades instead of them all landing in the unattributable magic=0 bucket.
MANUAL_MAGIC = 9999

TRADING_MODES = ("off", "single")

# Engine health, surfaced on /api/status. Without this the UI reads "live" while the loop
# has been raising on every tick for hours.
_last_tick_at = None
_last_error = None
_last_error_at = None


# One reentrant lock guards every shared mutable structure below. The engine thread and
# Flask request threads both touch them; the critical sections are tiny and the tick is 5s,
# so contention is irrelevant and a single lock removes any chance of a lock-ordering
# deadlock. NEVER hold this across an MT5 IPC call -- snapshot, release, then do I/O.
# ponytail: one global lock. Split per-structure only if profiling ever shows contention.
state_lock = threading.RLock()

_state_dirty = True
_last_saved_blob = None


def _mark_state_dirty():
    global _state_dirty
    _state_dirty = True


def _snapshot_state():
    """A coherent copy of everything one engine tick needs. Taken under the lock in one go so
    a mid-tick UI change can never split a decision across two symbols."""
    with state_lock:
        return {
            "symbol": state["symbol"],
            "timeframe": state["timeframe"],
            "active_strategy": state["active_strategy"],
            "trading_mode": state.get("trading_mode", "off"),
            "strategy_settings": copy.deepcopy(strategy_settings),
            "global_settings": copy.deepcopy(global_settings),
        }


def _load_persisted_state():
    saved = persistence.load_all()
    if not saved:
        return
    with state_lock:
        state.update(saved.get("state", {}))
        # Never resume live trading from a restart -- no engine thread exists yet at this
        # point, so a persisted mode here would show "live" in the UI while nothing is
        # actually running. Trading must be re-armed explicitly every process start.
        state["trading_mode"] = "off"
        # Legacy flags from older builds; dropped so they cannot resurface in the UI.
        state.pop("auto_enabled", None)
        state.pop("watchlist_enabled", None)
        # Filtered to keys config.py still defines, exactly like the settings API does. An
        # older blob would otherwise reintroduce removed keys and -- the real hazard -- a
        # key added in a later version would stay at whatever the old blob said instead of
        # picking up its new default, so every quality gate added to GLOBAL_SETTINGS would
        # be silently absent for existing users.
        for name, saved_values in saved.get("strategy_settings", {}).items():
            if name in strategy_settings:
                known = set(config.DEFAULT_SETTINGS[name])
                strategy_settings[name].update(
                    {k: v for k, v in saved_values.items() if k in known})
        known_globals = set(config.GLOBAL_SETTINGS)
        global_settings.update(
            {k: v for k, v in saved.get("global_settings", {}).items() if k in known_globals})


def _save_persisted_state(force=False):
    """Skips the write when nothing changed. This runs on every 5s engine tick; rewriting an
    identical file all day is pure disk wear and a needless window to be interrupted in."""
    global _state_dirty, _last_saved_blob
    with state_lock:
        snapshot = {
            "state": copy.deepcopy(state),
            "strategy_settings": copy.deepcopy(strategy_settings),
            "global_settings": copy.deepcopy(global_settings),
        }
    # Compare the serialized snapshot rather than trusting callers to flag their own writes --
    # a route that forgets to mark state dirty would otherwise silently stop persisting.
    blob = json.dumps(snapshot, sort_keys=True, default=str)
    if not force and blob == _last_saved_blob:
        _state_dirty = False
        return
    persistence.save_all(snapshot)
    _last_saved_blob = blob
    _state_dirty = False


_load_persisted_state()


@app.route("/")
def index():
    return send_from_directory("static", "dashboard.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory("static", "logo.svg", mimetype="image/svg+xml")


@app.route("/api/symbols")
def list_symbols():
    """Feeds the dashboard's symbol suggestions with names this broker can actually trade."""
    return jsonify({"symbols": bridge.list_tradeable_symbols()})


@app.route("/api/status")
def status():
    positions = bridge.get_open_positions(state["symbol"])
    equity = bridge.get_account_equity()
    mode = state.get("trading_mode", "off")
    return jsonify({
        "positions": positions,
        "equity": equity,
        "active_strategy": state["active_strategy"],
        "symbol": state["symbol"],
        "timeframe": state["timeframe"],
        "trading_mode": mode,
        "last_tick_at": _last_tick_at,
        "last_error": _last_error,
        "last_error_at": _last_error_at,
    })


HISTORY_PERIOD_DAYS = {"week": 7, "month": 30, "3months": 90}


def _history_from_date(period):
    """`all` is deliberately a large finite window rather than datetime.min -- MT5 rejects
    pre-epoch dates on some builds and answers with nothing at all."""
    from datetime import datetime, timedelta
    return datetime.now() - timedelta(days=HISTORY_PERIOD_DAYS.get(period, 3650))


@app.route("/api/account")
def account():
    """The persistent account strip. Open P&L is floating profit on open positions, which
    account_info() does not report separately (equity - balance also counts credit)."""
    info = bridge.get_account_info()
    # One read, two numbers. This endpoint runs twice a second and each call is an IPC
    # round-trip to the terminal, so fetching the same list again for its length was pure
    # waste -- and the two reads could disagree if a position closed between them.
    positions = bridge.get_open_positions()
    info["open_pnl"] = sum(p["profit"] for p in positions)
    info["open_positions"] = len(positions)
    return jsonify(info)


@app.route("/api/history")
def history():
    period = request.args.get("period", "all")
    rows = sorted(bridge.get_history_rows(_history_from_date(period)),
                  key=lambda r: r["time"], reverse=True)
    return jsonify({
        "period": period,
        "deals": rows,
        "total": {"volume": round(sum(r["volume"] for r in rows), 2),
                  "profit": round(sum(r["profit"] for r in rows), 2),
                  "commission": round(sum(r["commission"] for r in rows), 2),
                  "swap": round(sum(r["swap"] for r in rows), 2),
                  "count": len(rows)},
    })


@app.route("/api/history/export")
def export_history():
    from flask import Response
    import csv
    import io
    rows = sorted(bridge.get_history_rows(_history_from_date(request.args.get("period", "all"))),
                  key=lambda r: r["time"], reverse=True)
    fields = ["time", "symbol", "type", "volume", "price", "profit", "commission", "swap", "ticket"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return Response(buf.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": "attachment; filename=trade_history.csv"})


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


# Bounds checked at the trust boundary, so a typo cannot become a position. The order path
# clamps risk_percent as well (risk_manager.HARD_MAX_RISK_PERCENT), but silently clamping a
# number the user typed is how people end up trading a risk model they did not choose.
SETTING_BOUNDS = {
    "risk_percent": (0.001, engine.rm.HARD_MAX_RISK_PERCENT),
    "max_concurrent_trades": (1, 50),
    "daily_loss_limit_percent": (0.1, 100.0),
    "max_drawdown_percent": (0.1, 100.0),
    "min_reward_risk": (0.0, 100.0),
    "max_sl_atr_multiple": (0.1, 100.0),
    "max_portfolio_risk_percent": (0.1, 100.0),
    "slippage_points": (0, 10000),
    "max_lot": (0.0, 10000.0),
}


@app.route("/api/global_settings", methods=["GET"])
def get_global_settings():
    """The Settings and Advanced pages fill every control from this before anything can be
    saved. Without it, opening a page and pressing Save wrote the HTML's hardcoded defaults
    over whatever the active profile had set."""
    return jsonify(global_settings)


@app.route("/api/global_settings", methods=["POST"])
def set_global_settings():
    # silent=True so a body that is not JSON is answered with a sentence naming the problem,
    # rather than werkzeug's generic "the browser sent a request this server could not
    # understand" arriving as a 500 with a stack trace behind it.
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        message = ("The request body was not a JSON object. Send "
                   '{"setting_name": value} with Content-Type: application/json.')
        app_logger.warning(f"Settings change ignored: {message}")
        return jsonify({"ok": False, "rejected": {}, "error": message}), 400
    editable_keys = set(config.GLOBAL_SETTINGS.keys())
    rejected = {}
    for key, value in data.items():
        if key not in editable_keys:
            continue
        low, high = SETTING_BOUNDS.get(key, (None, None))
        if low is not None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                rejected[key] = f"{value!r} is not a number"
                continue
            if not (low <= number <= high):
                rejected[key] = f"{number} is outside the allowed range {low} to {high}"
                app_logger.warning(f"Setting '{key}' REJECTED: {rejected[key]}")
                continue
            # Profile bounds are HARD: a profile is only a promise if nothing can quietly
            # step past it at runtime. Refused, never silently clamped.
            violation = profiles.bounds_violation(_active_profile_bounds(), key, number)
            if violation:
                rejected[key] = violation
                app_logger.warning(f"Setting '{key}' REJECTED: {violation}")
                continue
        global_settings[key] = value
    _mark_state_dirty()
    return jsonify({"ok": not rejected, "rejected": rejected, "settings": global_settings})


def _set_trading_mode(mode):
    """Single owner of both the mode and the engine thread."""
    global _engine_thread
    state["trading_mode"] = mode
    engine.reset_bar_gate()
    if mode == "off":
        _stop_flag.set()
        app_logger.info("Trading disabled (mode: off)")
        return
    app_logger.info(f"Trading ENABLED ({state['symbol']}/{state['timeframe']}, "
                    f"strategy: {state['active_strategy']})")
    if _engine_thread is not None and _engine_thread.is_alive() and _stop_flag.is_set():
        # A previous mode is still winding down; wait for it so we never end up with the
        # flag cleared but the old thread already past its while-check and exiting.
        _engine_thread.join(timeout=6)
    _stop_flag.clear()
    if _engine_thread is None or not _engine_thread.is_alive():
        _engine_thread = threading.Thread(target=_engine_loop, daemon=True)
        _engine_thread.start()


@app.route("/api/trading_mode", methods=["POST"])
def set_trading_mode():
    data = request.get_json()
    mode = data.get("mode", "off")
    if mode not in TRADING_MODES:
        return jsonify({"ok": False, "error": f"unknown mode: {mode}"}), 400
    _set_trading_mode(mode)
    return jsonify({"ok": True, "trading_mode": state["trading_mode"]})


@app.route("/api/close_all", methods=["POST"])
def close_all():
    positions = bridge.get_open_positions(state["symbol"])
    app_logger.info(f"Close all requested: closing {len(positions)} open position(s) on {state['symbol']}")
    for pos in positions:
        bridge.close_position(pos["ticket"], pos["symbol"], pos["volume"], pos["type"],
                               global_settings["slippage_points"])
    return jsonify({"ok": True})


def _clamp_volume(symbol, volume):
    """Never let a manual order bypass the broker min/max/step the automated engine
    already respects (see risk_manager.calc_lot_size / get_symbol_volume_limits)."""
    min_lot, max_lot, step = bridge.get_symbol_volume_limits(symbol)
    volume = max(min_lot, min(max_lot, volume))
    steps = round(volume / step)
    return round(steps * step, 2)


@app.route("/api/manual/position/<int:ticket>/close", methods=["POST"])
def manual_close_position(ticket):
    data = request.get_json(silent=True) or {}
    ok, retcode = bridge.close_position_by_ticket(ticket, global_settings["slippage_points"])
    if ok:
        app_logger.info(f"Manual close: ticket {ticket} (retcode {retcode})")
    else:
        app_logger.error(f"Manual close FAILED: ticket {ticket} — {retcode}")
    return jsonify({"ok": ok, "retcode": retcode})


@app.route("/api/journal/<int:ticket>", methods=["GET"])
def get_journal(ticket):
    return jsonify({"note": journal.get_note(ticket)})


@app.route("/api/journal/<int:ticket>", methods=["POST"])
def post_journal(ticket):
    data = request.get_json()
    journal.set_note(ticket, data["note"])
    return jsonify({"ok": True})


@app.route("/api/state/save", methods=["POST"])
def save_state_endpoint():
    _save_persisted_state()
    return jsonify({"ok": True})


# Fewer rows than this cannot produce a test set worth measuring (70/30 split against
# ml_filter.MIN_TEST_ROWS).
MIN_ML_TRAINING_ROWS = 100


@app.route("/api/ml/train", methods=["POST"])
def train_ml_filter():
    """Train the win-probability filter and, more importantly, refuse to keep it when it
    cannot be shown to work on trades it never saw.

    Deterministic and reproducible: deals are sorted by time, the split is by time (never
    shuffled -- shuffling leaks the future into training and flatters a useless model), and
    the optimiser starts from zeros with a fixed epoch count."""
    from datetime import datetime, timedelta
    body = request.get_json(silent=True) or {}
    days = int(body.get("days", 30))
    from_date = datetime.now() - timedelta(days=days)
    deals = sorted(bridge.get_history_deals(from_date), key=lambda d: d["time"])

    magic_to_strategy = {v: k for k, v in analytics.STRATEGY_MAGIC.items()}
    features, labels, attributed = [], [], 0
    for d in deals:
        # Deals from hand trades, another EA or an older build are labelled "unknown"
        # rather than dropped. Dropping them silently is how a training run over 1,079 real
        # closed trades produced zero rows and a message that never said why.
        strategy = magic_to_strategy.get(d.get("magic"))
        attributed += strategy is not None
        deal_time = datetime.fromtimestamp(d["time"])
        features.append(ml_filter.build_features(strategy or "unknown",
                                                  deal_time.hour, deal_time.weekday()))
        labels.append(1 if d["profit"] > 0 else 0)

    attribution = f"{attributed} of {len(deals)} trades carry one of this bot's magic numbers"
    if len(features) < MIN_ML_TRAINING_ROWS:
        message = (f"Not enough closed trades to train or validate anything: {len(features)} "
                   f"in the last {days} days, need {MIN_ML_TRAINING_ROWS}.")
        app_logger.warning(f"ML filter training skipped. {message}")
        return jsonify({"ok": False, "error": message, "attribution": attribution}), 400

    # Validated at the probability floor the filter will actually run at, not at a
    # default -- otherwise the report describes a different filter than the live one.
    weights, report = ml_filter.train_and_evaluate(
        features, labels,
        threshold=float(global_settings.get("ml_filter_min_probability", 0.5)))
    report["attribution"] = attribution
    report["days"] = days

    if weights is None:
        # The previous model is left exactly as it was: a failed retrain must not silently
        # disarm a filter the user believes is running.
        app_logger.warning(
            f"ML filter NOT updated — the model does not work out of sample. {report['reason']} "
            f"({attribution}.) Leave ml_filter_enabled off, or off for this data.")
        return jsonify({"ok": False, "error": report["reason"], "report": report}), 200

    ml_filter.save_weights(weights)
    app_logger.info(
        f"ML filter trained on {report['rows']} closed trades and saved: out-of-sample AUC "
        f"{report['out_of_sample_auc']:.3f} on {report['test_rows']} held-out trades "
        f"(0.5 is a coin flip). {attribution}. This is a weak prior, not a guarantee.")
    return jsonify({"ok": True, "trained_on": report["rows"], "report": report})


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
        app_logger.info(f"Auto-tune switched active strategy from {state['active_strategy']} to {best} "
                         f"(flagged for poor profit factor: {disable})")
        state["active_strategy"] = best
        switched = True
    elif disable:
        app_logger.info(f"Auto-tune run: flagged {disable} for poor profit factor, best performer is {best}")
    return jsonify({"disable_suggested": disable, "best_strategy": best, "switched_to": best if switched else None})


@app.route("/api/diagnose")
def diagnose():
    """Why won't it trade? Asks MT5 directly rather than listing possibilities. Findings are
    also written to logs/app.log so they survive the browser tab being closed."""
    symbol = request.args.get("symbol") or state["symbol"]
    findings = engine.diagnose_and_log(bridge, symbol, force=True) or []
    blocking = [f for f in findings if mt5_bridge.is_blocking(f)]
    return jsonify({
        "symbol": symbol,
        # "ok" means trading is possible, not that there is nothing to report. An
        # auto-resolved symbol rename is a note, and reporting it as "cannot trade" was
        # simply false -- the engine had already resolved it and traded.
        "ok": not blocking,
        "findings": findings,
        "blocking_count": len(blocking),
        "info_count": len(findings) - len(blocking),
        "account": bridge.get_account_summary(),
    })


def _traded_targets():
    """Exactly what the engine evaluates on each tick — always a single target.

    Off is not "nothing to explain": the user still wants to know what WOULD be traded."""
    # Off is not "nothing to explain": the user still wants to know what WOULD be traded.
    # When Auto has picked a strategy this tick, THAT is what single mode is trading -- the
    # panel would otherwise name the user's stored choice and be quietly wrong.
    auto = engine.get_auto_decision()
    strategy = state["active_strategy"]
    auto_strategy = bool(auto and auto.get("enabled") and auto.get("strategy"))
    if auto_strategy:
        strategy = auto["strategy"]
    return [{"symbol": state["symbol"], "timeframe": state["timeframe"],
             "strategy": strategy, "row_mode": "trade", "source": "single",
             "chosen_by_auto": auto_strategy}]


# Each target costs a couple of MT5 IPC reads and the panel polls every few seconds.
# ponytail: flat cap rather than a cache.
MAX_EXPLAINED_TARGETS = 20


def _utc_now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@app.route("/api/why_no_trade")
def why_no_trade():
    """The whole answer to "why is it not opening a trade?", as data rather than log text.

    Per target: whether a signal existed at all, and if it was refused, which named gate
    refused it, with the numbers and the fix. Plus the risk arithmetic that decides whether
    the configured risk is even expressible on this account -- the broker lot cap binds
    silently otherwise, and on a large account that is the single most common reason
    nothing trades."""
    mode = state.get("trading_mode", "off")
    evaluations = {(e["symbol"], e["strategy"]): e for e in engine.get_evaluations()}
    snapshot_settings = dict(global_settings)

    targets = []
    for target in _traded_targets()[:MAX_EXPLAINED_TARGETS]:
        resolved, resolve_error = bridge.resolve_symbol(target["symbol"])
        traded_symbol = resolved or target["symbol"]
        entry = dict(target)
        entry["traded_symbol"] = traded_symbol
        entry["symbol_error"] = resolve_error
        entry["evaluation"] = evaluations.get((traded_symbol, target["strategy"]))
        entry["risk"] = engine.risk_reality(bridge, traded_symbol, target["timeframe"],
                                             target["strategy"], strategy_settings,
                                             snapshot_settings) if resolved else None
        targets.append(entry)

    outcomes = [t["evaluation"]["outcome"] for t in targets if t["evaluation"]]
    return jsonify({
        "trading_mode": mode,
        "armed": mode != "off",
        "now": _utc_now_iso(),
        "last_tick_at": _last_tick_at,
        "last_error": _last_error,
        "last_error_at": _last_error_at,
        "headline": _why_headline(mode, targets, outcomes),
        "targets": targets,
        "summary": {
            "targets": len(targets),
            "blocked": outcomes.count(engine.OUTCOME_BLOCKED),
            "no_signal": outcomes.count(engine.OUTCOME_NO_SIGNAL),
            "waiting_bar": outcomes.count(engine.OUTCOME_WAITING_BAR),
            "order_sent": outcomes.count(engine.OUTCOME_ORDER_SENT),
            "not_yet_evaluated": len(targets) - len(outcomes),
        },
        "account": {
            "equity": bridge.get_account_equity(),
            "open_positions": len(bridge.get_open_positions()),
        },
        "active_profile": state.get("active_profile"),
        # Auto's current reasoning, alongside the gates, from the engine's own record.
        "auto": engine.get_auto_decision(),
    })


def _why_headline(mode, targets, outcomes):
    """One sentence a confused user can read before anything else."""
    if mode == "off":
        return ("Trading is switched OFF, so no orders are placed in any market. Everything "
                "below is what WOULD be evaluated once you arm it.")
    if not outcomes:
        return ("Trading is armed but the engine has not completed an evaluation yet. Give it "
                "one tick, about 5 seconds.")
    blocked = outcomes.count(engine.OUTCOME_BLOCKED)
    if blocked:
        gates = sorted({t["evaluation"]["gate"] for t in targets
                        if t["evaluation"]
                        and t["evaluation"]["outcome"] == engine.OUTCOME_BLOCKED
                        and t["evaluation"]["gate"]})
        return (f"{blocked} of {len(targets)} target(s) had a signal that was REFUSED by a "
                f"gate ({', '.join(gates)}). The detail and the fix are below.")
    if outcomes.count(engine.OUTCOME_ORDER_SENT):
        return "A signal passed every gate and an order was sent. Nothing is blocking trading."
    if outcomes.count(engine.OUTCOME_NO_SIGNAL) == len(outcomes):
        return ("Nothing is blocked. The strategies simply see no entry setup right now — this "
                "is the normal state most of the time, not a fault.")
    return "See each target below for what its last evaluation did."


# ---------- trading profiles ----------

def _active_profile_bounds():
    return (state.get("active_profile") or {}).get("bounds")


def _preset_inputs():
    """(equity, per_lot, broker_max_lot, lot_step, symbol) for the symbol currently targeted.
    per_lot is what turns a preset's nominal risk into the risk this account can express."""
    targets = _traded_targets()
    if not targets:
        return 0.0, 0.0, 0.0, 0.01, None
    target = targets[0]
    resolved, _err = bridge.resolve_symbol(target["symbol"])
    symbol = resolved or target["symbol"]
    reality = engine.risk_reality(bridge, symbol, target["timeframe"], target["strategy"],
                                   strategy_settings, global_settings)
    if not reality:
        return 0.0, 0.0, 0.0, 0.01, symbol
    _min_lot, broker_max_lot, lot_step = bridge.get_symbol_volume_limits(symbol)
    return reality["equity"], reality["per_lot"], broker_max_lot, lot_step, symbol


@app.route("/api/profiles")
def get_profiles():
    """Every preset, already resolved against this account, so the risk each one would really
    trade at is visible BEFORE it is applied."""
    equity, per_lot, broker_max_lot, lot_step, symbol = _preset_inputs()
    resolved = []
    for preset in profiles.PRESETS:
        item = profiles.resolve(preset, equity, per_lot, broker_max_lot, lot_step)
        item["changes"] = profiles.diff(global_settings, state["timeframe"], item)
        resolved.append(item)
    return jsonify({
        "presets": resolved,
        "active_profile": state.get("active_profile"),
        "priced_on": {"symbol": symbol, "equity": equity, "per_lot": per_lot,
                      "broker_max_lot": broker_max_lot},
        "honesty_note": ("Risk-management profiles only. Walk-forward testing on this account "
                         "found no strategy with a demonstrated edge, so no preset picks a "
                         "strategy and none is expected to be profitable. They differ only in "
                         "how much you can lose."),
    })


@app.route("/api/profiles/apply", methods=["POST"])
def apply_profile():
    data = request.get_json() or {}
    preset = profiles.get(data.get("id"))
    if preset is None:
        return jsonify({"ok": False, "error": "unknown profile: " + str(data.get("id"))}), 400
    if preset.get("requires_confirmation") and not data.get("confirmed"):
        return jsonify({"ok": False, "error": "this profile requires explicit confirmation",
                        "confirmation": preset["confirmation"]}), 400

    equity, per_lot, broker_max_lot, lot_step, _symbol = _preset_inputs()
    resolved = profiles.resolve(preset, equity, per_lot, broker_max_lot, lot_step)
    changes = profiles.diff(global_settings, state["timeframe"], resolved)

    previous = state.get("active_profile") or {}
    with state_lock:
        global_settings.update(resolved["settings"])
        if resolved["timeframe"]:
            state["timeframe"] = resolved["timeframe"]
        state["active_profile"] = {
            "id": resolved["id"], "label": resolved["label"],
            "applied_at": _utc_now_iso(),
            "requested_risk_percent": resolved["requested_risk_percent"],
            "effective_risk_percent": resolved["effective_risk_percent"],
            "max_expressible_risk_percent": resolved["max_expressible_risk_percent"],
            "risk_summary": resolved["risk_summary"],
            "lot_cap_binds": resolved["lot_cap_binds"],
            "bounds": resolved["bounds"],
        }
        _mark_state_dirty()

    bounds_text = ", ".join(profiles.LABELS.get(k, k) + "=" + str(v)
                            for k, v in resolved["bounds"].items())
    app_logger.info("Trading profile changed: " + str(previous.get("label", "none")) +
                    " -> " + resolved["label"] + ". " + resolved["risk_summary"] +
                    " Bounds: " + bounds_text)
    for change in changes:
        app_logger.info("  profile change: " + change["label"] + ": " +
                        str(change["from"]) + " -> " + str(change["to"]))

    return jsonify({"ok": True, "profile": state["active_profile"], "changes": changes,
                    "resolved": resolved})


# ---------- Auto mode ----------
#
# Opt-in, off by default. Auto never writes into `state` or `global_settings`: it writes into
# the per-tick snapshot only (see _apply_auto_mode), so switching it off restores exactly the
# strategy and risk the user chose, with nothing to undo.

def _auto_payload():
    return {
        "enabled": bool(global_settings.get("auto_mode_enabled", False)),
        "decision": engine.get_auto_decision(),
        "min_trades": auto_mode.MIN_TRADES,
        "candidates": list(auto_mode.CANDIDATES),
        "caveat": auto_mode.CAVEAT,
    }


@app.route("/api/auto_mode", methods=["GET"])
def get_auto_mode():
    return jsonify(_auto_payload())


@app.route("/api/auto_mode", methods=["POST"])
def set_auto_mode():
    data = request.get_json() or {}
    enabled = bool(data.get("enabled"))
    with state_lock:
        global_settings["auto_mode_enabled"] = enabled
        _mark_state_dirty()
    if enabled:
        app_logger.info(
            f"Auto mode ENABLED: the bot may now rotate between "
            f"{', '.join(auto_mode.CANDIDATES)} on this account's realised results (minimum "
            f"{auto_mode.MIN_TRADES} closed trades on a strategy before any switch), and "
            f"reduce position size after consecutive losses. It moves strictly inside the "
            f"active profile's bounds and can never raise risk above "
            f"{global_settings.get('risk_percent')}%.")
    else:
        # Recorded immediately so the panel and /api/why_no_trade stop reporting a stale
        # decision instead of waiting up to 5 seconds for the next tick to say "off".
        engine.record_auto_decision(auto_mode.decide(
            enabled=False, regime=None, per_strategy_stats={}, recent_results=[],
            current_strategy=state["active_strategy"],
            profile_risk_percent=global_settings.get("risk_percent", 0.0)))
        app_logger.info(
            f"Auto mode DISABLED: strategy and risk revert to your own settings "
            f"({state['active_strategy']}, {global_settings.get('risk_percent')}%).")
    return jsonify(dict(_auto_payload(), ok=True))


@app.route("/api/logs/recent")
def get_recent_logs():
    n = int(request.args.get("lines", 200))
    return jsonify({"lines": app_logger.tail(n)})


def _compute_risk_percents():
    """Real inputs for the daily-loss and max-drawdown kill switches. These were hardcoded
    to 0.0, which made both limits decorative -- the account could go to zero with the bot
    still adding trades.

    daily_pnl_percent: today's closed profit (deals since midnight) plus floating profit on
    open positions, as a percent of what equity was at the start of the day.
    drawdown_percent: how far equity is below its highest-ever observed value.
    """
    from datetime import datetime, time as dtime
    equity = bridge.get_account_equity()
    login = bridge.get_account_login()

    # The peak belongs to one account. Re-logging the terminal into a different account
    # otherwise measures the new balance against the old account's high-water mark: a
    # $965 account inherited a $5.32M peak, which read as a 99.98% drawdown and flattened
    # positions that were never in trouble.
    if login is not None and login != state.get("peak_equity_login"):
        if state.get("peak_equity_login") is not None:
            app_logger.info(
                f"MT5 account changed to {login} — resetting the drawdown high-water mark "
                f"(it belonged to account {state.get('peak_equity_login')}).")
        state["peak_equity"] = None
        state["peak_equity_login"] = login

    if equity <= 0:
        # account_info() returns None while the terminal is disconnected and equity reads
        # 0.0. That is a missing reading, not a wiped-out account -- treating it as a 100%
        # drawdown would trip the kill switch and flatten on every connection blip.
        drawdown_percent = 0.0
    else:
        peak = max(float(state.get("peak_equity") or 0.0), equity)
        state["peak_equity"] = peak
        drawdown_percent = ((peak - equity) / peak * 100) if peak > 0 else 0.0

    midnight = datetime.combine(datetime.now().date(), dtime.min)
    closed = sum(d["profit"] for d in bridge.get_history_deals(midnight))
    floating = sum(p["profit"] for p in bridge.get_open_positions())
    day_pnl = closed + floating
    day_start_equity = equity - day_pnl
    daily_pnl_percent = (day_pnl / day_start_equity * 100) if day_start_equity > 0 else 0.0

    # Both kill switches are latched states, not per-tick events: logged when they fire and
    # again when they clear. Re-logging every 5 seconds produced ~40 identical lines in three
    # minutes and buried everything else.
    engine.log_state_change(
        "daily_loss_limit",
        daily_pnl_percent <= -global_settings["daily_loss_limit_percent"],
        f"DAILY LOSS LIMIT hit: today's P&L is {daily_pnl_percent:.2f}% of starting equity, "
        f"limit is {global_settings['daily_loss_limit_percent']}% — no new trades until tomorrow",
        f"DAILY LOSS LIMIT cleared: today's P&L is back to {daily_pnl_percent:.2f}% of starting "
        f"equity, inside the {global_settings['daily_loss_limit_percent']}% limit — new trades "
        f"allowed again")
    engine.log_state_change(
        "max_drawdown",
        drawdown_percent >= global_settings["max_drawdown_percent"],
        f"MAX DRAWDOWN hit: equity {equity:.2f} is {drawdown_percent:.2f}% below its peak, "
        f"limit is {global_settings['max_drawdown_percent']}% — flattening and blocking new trades",
        f"MAX DRAWDOWN cleared: equity {equity:.2f} is {drawdown_percent:.2f}% below its peak, "
        f"back inside the {global_settings['max_drawdown_percent']}% limit — new trades allowed "
        f"again")
    return daily_pnl_percent, drawdown_percent


# Auto's inputs that come from MT5. The 30-day deal history is the expensive one and its
# numbers move a few times a day, so it is refreshed at most once a minute rather than on
# every 5-second tick.
# ponytail: a timestamp and a dict. Swap for a real cache only if more callers need it.
AUTO_HISTORY_DAYS = 30
AUTO_HISTORY_TTL_SECONDS = 60
_auto_history_cache = {"at": 0.0, "stats": {}, "recent": []}


def _auto_history():
    """(per-strategy stats, recent trade results) from closed deals. Read outside the lock."""
    from datetime import datetime, timedelta
    now = time.monotonic()
    if _auto_history_cache["at"] and (now - _auto_history_cache["at"]) < AUTO_HISTORY_TTL_SECONDS:
        return _auto_history_cache["stats"], _auto_history_cache["recent"]
    deals = bridge.get_history_deals(datetime.now() - timedelta(days=AUTO_HISTORY_DAYS))
    stats = analytics.compute_per_strategy_stats(deals)
    recent = [d["profit"] for d in deals[-10:]]
    _auto_history_cache.update({"at": now, "stats": stats, "recent": recent})
    return stats, recent


def _auto_regime(snap):
    """The volatility regime of what is actually being traded, or None when it cannot be
    read. None is NOT downgraded to "NORMAL" -- auto_mode treats an unreadable regime as
    "the filter could not run", which is the honest reading and leaves the strategy alone."""
    symbol, timeframe = snap["symbol"], snap["timeframe"]
    try:
        resolved, _err = bridge.resolve_symbol(symbol)
        rates = bridge.get_rates(resolved or symbol, timeframe, engine.SIGNAL_BARS)
        if rates is None or len(rates) == 0:
            return None
        # Sticky: Auto's eligibility list changes only on a confirmed regime change, not
        # every time ATR wobbles across a percentile boundary.
        return volatility_regime.regime_for(f"{resolved or symbol}:{timeframe}", rates)
    except Exception:
        return None


def _record_auto_block(snap, decision):
    """Auto's regime filter excluded the running strategy and Auto has no replacement it may
    justify, so this tick opens nothing. Routed through engine.log_block so "Why no trade?"
    names it exactly like every other gate -- otherwise the only place the user could find
    it is logs/app.log."""
    symbol = snap["symbol"]
    try:
        resolved, _err = bridge.resolve_symbol(symbol)
    except Exception:
        resolved = None
    engine.log_block(
        resolved or symbol, snap["active_strategy"], "auto_ineligible",
        f"Auto mode opened nothing this tick: {decision['reason']}.",
        details={"regime": decision["regime"] or "unreadable",
                 "eligible": ", ".join(decision["eligible"]) or "none",
                 "running_strategy": decision["strategy_from"]},
        remedy="Switch Auto mode off to keep trading this strategy whatever the volatility "
               "regime, or pick one of the eligible strategies yourself.")


def _apply_auto_mode(snap):
    """Consult Auto for this tick and write its decision into the SNAPSHOT only. Returns
    False when Auto's filter forbids opening anything this tick.

    Called after _snapshot_state() and outside state_lock, because it does MT5 IPC. Nothing
    here touches `state` or `global_settings`: the user's own strategy and risk stay exactly
    as they set them, and Auto's influence lasts precisely one tick."""
    settings = snap["global_settings"]
    profile_risk = float(settings.get("risk_percent", 0.0) or 0.0)
    if not settings.get("auto_mode_enabled", False):
        engine.record_auto_decision(auto_mode.decide(
            enabled=False, regime=None, per_strategy_stats={}, recent_results=[],
            current_strategy=snap["active_strategy"], profile_risk_percent=profile_risk))
        return True
    stats, recent = _auto_history()
    decision = engine.record_auto_decision(auto_mode.decide(
        enabled=True, regime=_auto_regime(snap), per_strategy_stats=stats,
        recent_results=recent, current_strategy=snap["active_strategy"],
        profile_risk_percent=profile_risk))
    if decision["strategy"]:
        snap["active_strategy"] = decision["strategy"]
    settings["risk_percent"] = decision["risk_percent"]
    # The filter is a hard gate, not a hint: when it has excluded the running strategy and
    # Auto may not justify a replacement, nothing opens.
    if decision["block_trading"]:
        _record_auto_block(snap, decision)
        return False
    return True


def _engine_loop():
    global _was_connected, _last_tick_at, _last_error, _last_error_at
    from datetime import datetime, timezone
    app_logger.info("Engine loop started")
    logged_mode = None
    while not _stop_flag.is_set():
        try:
            connected = watchdog.check_connection(bridge)
            if _was_connected and not connected:
                app_logger.error("Lost connection to MT5 terminal")
                watchdog.notify_webhook(global_settings.get("watchdog_webhook_url", ""),
                                         "MT5 Bot: lost connection to MT5 terminal")
            elif not _was_connected and connected:
                app_logger.info("MT5 terminal connection restored")
            _was_connected = connected

            # One coherent read of everything this tick needs. Without it a UI change landing
            # mid-tick could pair one symbol's rates with another symbol's order.
            snap = _snapshot_state()
            auto_allows_trading = _apply_auto_mode(snap)
            mode = snap["trading_mode"]
            if mode != logged_mode:
                # Logged on change rather than every 5s tick, which would bury the log.
                app_logger.info(f"Engine ticks now running in '{mode}' mode")
                logged_mode = mode
            daily_pnl_percent, drawdown_percent = _compute_risk_percents()

            # The kill-switch percentages above are still computed and still logged when Auto
            # blocks -- only the order path is skipped, and its reason is already recorded
            # per target by _record_auto_block.
            if not auto_allows_trading:
                pass
            elif mode == "single":
                engine.run_once(bridge, snap, snap["strategy_settings"], snap["global_settings"],
                                 daily_pnl_percent=daily_pnl_percent, drawdown_percent=drawdown_percent,
                                 partial_closed_tickets=partial_closed_tickets)
            _save_persisted_state()
            _sync_mt5_status_panel()
            _last_tick_at = datetime.now(timezone.utc).isoformat()
            _last_error = None
        except Exception as exc:
            import traceback
            _last_tick_at = datetime.now(timezone.utc).isoformat()
            _last_error = str(exc)
            _last_error_at = _last_tick_at
            app_logger.error(f"Engine loop tick failed (trading paused until next tick): {exc}\n{traceback.format_exc()}")
        time.sleep(5)
    app_logger.info("Engine loop stopped")


def _sync_mt5_status_panel():
    try:
        equity = bridge.get_account_equity()
        open_count = len(bridge.get_open_positions())
        mt5_status_sync.write_status_file(mt5_status_sync.build_status(state, equity, open_count))
    except Exception:
        pass  # panel sync is best-effort -- never let it break the trading loop


if __name__ == "__main__":
    # Two copies would each run an engine thread against the same account, turning one
    # signal into two full-size orders. Windows allows a second listener on the same
    # loopback port, so the port alone is not a guard.
    _ok, _other = single_instance.acquire()
    if not _ok:
        msg = (f"MT5 Bot is already running (process {_other}). Close that window first -- "
               f"two copies would place every trade twice, at double your configured risk.")
        app_logger.error(msg)
        print(os.linesep + "  " + msg + os.linesep)
        sys.exit(1)
    atexit.register(single_instance.release)
    bridge.connect()
    app.run(host="127.0.0.1", port=7500)
