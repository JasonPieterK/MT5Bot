# MT5 Bot — Phase 1 Design

## Purpose

Auto-trading robot for MetaTrader 5. Runs as external Python app (not MQL5 EA), controlled via local web dashboard styled after MT5Manager (https://github.com/JasonPieterK/MT5Manager). Trades any symbol/timeframe the user selects, fully automatic (no confirm prompts), switchable between 5 strategy modules, each with granular per-strategy settings. Trades often — lower timeframes, relaxed entry filters — rather than waiting for rare high-confluence setups.

Phase 1 = core engine + risk pipeline + all 5 strategies + working dashboard (selectors, live stats, start/stop, settings). Phase 2 (separate future spec) = MT5Manager feature parity: analytics dashboard, trade journal, price/margin alerts, trailing-stop/break-even automation, installer.

## Architecture

```
MT5 Bot/
  app.py                 Flask app: serves dashboard.html, REST API, owns engine thread lifecycle
  mt5_bridge.py           MetaTrader5 package wrapper: connect/reconnect, get rates, get positions,
                           place/modify/close orders, symbol info (min stop level, freeze level, margin)
  risk_manager.py         % equity lot sizing, SL/TP calc, max concurrent trades, max exposure,
                           daily loss limit (disables new entries for the day), max drawdown kill-switch
                           (flattens all positions). Applies uniformly to every strategy.
  indicators.py           MA (SMA/EMA/WMA/SMMA), RSI, Stochastic, MACD, ATR, Bollinger Bands,
                           Pivot Points (Classic/Fibonacci/Camarilla/Woodie), swing-structure detector
                           (for SMC BOS/ChoCh), spread + session-time filter helpers
  strategies/
    base.py               Strategy interface: get_signal(rates_df, settings_dict) -> (BUY|SELL|NONE, sl, tp)
    scalping.py            M1-M5, ATR-based SL/TP, spread filter, min candle body %
    smc.py                 BOS/ChoCh detection, Order Block + FVG tagging, HTF bias confluence, retest entry
    trend.py                MA cross + RSI zone filter, optional slope filter
    grid.py                 Ladder of pending orders, fixed/ATR spacing, lot multiplier;
                            HARD CAPS (max levels, max total lots, equity kill-switch) hardcoded,
                            not exposed in settings UI/API — edit source only to change
    pivot_breakout.py       Daily/weekly pivot + S/R breakout with optional retest confirmation
  engine.py                Background thread: loop polls active symbol/TF rates each new bar (or tick
                           for scalping), asks active strategy for signal, passes through risk_manager,
                           executes via mt5_bridge, logs to CSV. Reads live settings dict each iteration
                           (no restart needed on settings change).
  config.py                Default settings per strategy, symbol/TF selection state, active-strategy state
  static/dashboard.html    Single-file HTML/CSS/JS. Dark theme matching MT5Manager's animated settings
                           panel + hover tooltips. Symbol/TF/strategy dropdowns, Auto ON/OFF switch,
                           live stats (open positions, floating P/L, today's P/L, drawdown %),
                           one settings tab per strategy, Close All / Close Profitable / Pause New Entries
  logs/                    CSV trade/event log (Logger.mqh equivalent)
```

## Data Flow

1. `app.py` starts Flask on `127.0.0.1:7500`, serves `dashboard.html`.
2. User toggles Auto ON → `app.py` starts `engine.py` loop in background thread.
3. Engine loop: get rates for active symbol+TF → active strategy's `get_signal()` → if signal, `risk_manager` computes lot size/SL/TP and checks caps/limits → if approved, `mt5_bridge` places order → `logs/` CSV append.
4. Dashboard polls `GET /api/status` every 1-2s: positions, P/L, active signal state, engine running/stopped.
5. Dashboard settings tabs `POST /api/settings` on change → `config.py` in-memory state updated → engine reads next loop, no restart.
6. Symbol/TF/strategy switch → `POST /api/select` → engine re-subscribes to new rates source next loop.

## Risk Management (applies to all 5 strategies)

- Position sizing by % risk of equity, not fixed lots
- Max concurrent trades / max exposure per symbol
- Daily loss limit → auto-disables new entries for the day (re-enables next trading day)
- Max drawdown kill-switch → flattens all open positions, disables Auto until manually re-enabled
- Broker/symbol safety checks before every order: min stop level, freeze level, margin sufficiency
- Slippage tolerance + retry-on-requote (ECN/market execution assumption)

## Strategy Defaults (Phase 1, tuned for frequent trading)

Lower timeframes (M1-M15) as default TF where applicable, entry filters relaxed vs. textbook strictness (e.g. SMC confluence requirement reduced, trend MA/RSI thresholds widened) so signals fire more often. Risk manager still caps total exposure regardless of signal frequency.

## Settings UI

Per-strategy settings tab, live-editable, no restart required:
- **Scalping:** max spread, TP/SL (pips or ATR multiple), min candle body %, session-time filter
- **SMC:** swing lookback, HTF bias timeframe, OB/FVG mitigation %, min RR
- **Trend:** MA type + fast/slow period, RSI period + thresholds, trend confirmation bars
- **Grid:** grid step, lot multiplier (max levels / max lots / equity stop NOT editable here — hardcoded)
- **Pivot Breakout:** pivot type, breakout confirmation bars, retest toggle

Global: risk % per trade, max concurrent trades, daily loss limit, max drawdown %.

## Error Handling

- MT5 connection lost → engine pauses new entries, dashboard shows connection state, auto-reconnect attempt each loop
- Order rejected (requote, invalid stops, insufficient margin) → log to CSV, skip this bar, no retry loop that could double-enter
- Bad/missing rates data → skip signal generation for that iteration, no crash

## Testing

- Each strategy's `get_signal()` unit-tested against fixed historical rate arrays with known expected signals
- `risk_manager` unit-tested: lot sizing math, cap enforcement, kill-switch trigger
- Manual demo-account smoke test before any live deployment (user responsibility, robot has no "live mode" gate beyond broker account selection)

## Out of Scope (Phase 1)

Analytics dashboard (win rate/profit factor/equity curve charts), trade journal, price/margin alerts, trailing-stop/break-even automation, installer script, manual/semi-auto alert-only mode, multi-symbol concurrent trading, MT5 Strategy Tester backtesting integration.
