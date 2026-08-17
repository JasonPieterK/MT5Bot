# MT5 Bot — Phase 3 Design

## Purpose

Two remaining items from Phase 1's Out-of-Scope list: multi-symbol concurrent trading and manual/semi-auto (alert-only) mode. Built as an opt-in watchlist layered on top of the existing single-symbol engine, not a replacement — Phase 1/2 behavior is unchanged when the watchlist is empty/disabled.

## Architecture

```
MT5 Bot/
  config.py (extended)   new_state() gains "watchlist_enabled": False
                          new function: new_watchlist_entry(id, symbol, timeframe, strategy, mode)
                          mode is "auto" (executes trades) or "alert_only" (signal recorded, no order)
  engine.py (extended)    run_watchlist_once(bridge, watchlist, strategy_settings, global_settings,
                          daily_pnl_percent, drawdown_percent, alert_rules, triggered_alerts,
                          manual_signals) -> iterates enabled watchlist entries:
                          - "auto" entries: same signal -> risk -> execute pipeline as run_once,
                            scoped to that entry's symbol/timeframe/strategy
                          - "alert_only" entries: signal computed, if not NONE appended to
                            manual_signals (dashboard displays it, chart arrow equivalent is the
                            entry's row highlighting — no order placed)
                          trailing/BE/alerts position-management pass (_manage_positions) still
                          runs once per tick across the whole account, unchanged from Phase 2
  app.py (extended)       GET/POST/DELETE /api/watchlist, engine loop branches: if
                          state["watchlist_enabled"] is True, call run_watchlist_once instead of
                          run_once; otherwise existing single-symbol behavior is untouched
  static/dashboard.html   new Watchlist tab: add-row form (symbol/timeframe/strategy/mode),
                          table of entries with enable toggle and delete, manual_signals shown
                          inline per alert_only row
```

## Data Flow

1. Dashboard Watchlist tab: add entries via `/api/watchlist` POST, each gets an id.
2. `state["watchlist_enabled"]` toggle (separate from the existing single-symbol Auto ON/OFF) controls which code path `_engine_loop` takes each tick.
3. `run_watchlist_once` loops enabled entries: `auto` entries run the full Phase 1 pipeline (get_rates -> strategy.get_signal -> risk_manager -> place_order) scoped to that entry; `alert_only` entries run get_rates -> strategy.get_signal only, appending non-NONE signals to a `manual_signals` list exposed via `/api/status`.
4. Risk manager's `max_concurrent_trades` and daily-loss/drawdown checks apply per call (using the account-wide `open_position_count` from `bridge.get_open_positions()` with no symbol filter), so exposure caps hold across all watchlist symbols combined, not per-symbol.
5. Position management pass (trailing/BE/alerts) already operates account-wide (Phase 2), so it naturally covers positions opened via any watchlist entry without changes.

## Settings

Watchlist entries carry only `{id, symbol, timeframe, strategy, mode, enabled}` — no per-entry strategy parameter overrides. All entries trading strategy X share strategy X's settings from the existing `strategy_settings` dict (same settings used by the single-symbol mode). This avoids a second settings surface; users wanting different tuning per symbol run the bot's single-symbol mode for that case instead (documented limitation, not silently broken).

## Error Handling

Same per-entry error handling as Phase 1's `run_once` (bad rates, order rejection skip that entry this tick, no crash of the whole loop). One entry's exception should not stop the others — wrap each entry's processing in the loop with a try/except that logs to `logs/trades.csv`-style error row and continues.

## Testing

- `run_watchlist_once`: unit tests with mocked bridge — auto entry places order, alert_only entry does not place order but appends to manual_signals, disabled entry is skipped entirely, one entry raising doesn't stop processing of the next entry
- `app.py`: watchlist CRUD routes, `/api/status` includes `manual_signals` and `watchlist`

## Out of Scope (Phase 3)

Per-entry strategy setting overrides, per-symbol exposure caps (caps remain account-wide), watchlist entries for the grid strategy (grid's per-symbol state tracking via `current_grid_levels=len(open_positions)` doesn't cleanly generalize to shared multi-symbol exposure — grid stays single-symbol-mode only for now), portfolio-level correlation risk checks.
