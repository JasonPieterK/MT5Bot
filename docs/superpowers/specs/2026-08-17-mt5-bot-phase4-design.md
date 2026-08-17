# MT5 Bot — Phase 4 Design

## Purpose

Two remaining backlog items: backtesting/walk-forward validation, and a news/high-impact-event filter. The `MetaTrader5` Python package has no economic-calendar endpoint (that's terminal-UI only), so a scraped/live calendar is out of scope here — instead, a manual blackout-window filter: user defines time ranges (e.g. "NFP: 2026-09-05 12:25–12:35 UTC") and the engine skips new entries during them. Backtesting reuses the existing strategy modules and risk manager against historical bars fetched via `mt5_bridge.get_rates`, no MT5 Strategy Tester UI needed.

## Architecture

```
MT5 Bot/
  backtest.py            run_backtest(rates_df, strategy_name, strategy_settings, global_settings,
                          initial_equity) -> {deals, stats}
                          walks the rates DataFrame bar by bar starting after enough bars exist for
                          the strategy's lookback; at each bar calls strategy.get_signal() on the
                          slice up to that bar; if a signal fires and no simulated position is open,
                          opens one sized via risk_manager.calc_lot_size against a running equity
                          total; closes it on a later bar when high/low crosses sl or tp (whichever
                          hit first, using each bar's high/low); appends a deal dict compatible with
                          analytics.compute_stats
  news_filter.py          is_blackout_active(now, blackout_windows) -> bool
                          blackout_windows: list of {id, start, end, label} (ISO datetime strings)
  engine.py (extended)     both run_once's and _run_watchlist_entry's execution branches call
                          news_filter.is_blackout_active(now, blackout_windows) before placing an
                          order; if active, the signal is skipped (same as a NONE signal) — position
                          management (trailing/BE/alerts) is unaffected, blackout only blocks new entries
  app.py (extended)        GET/POST/DELETE /api/blackouts, GET /api/backtest (query params: symbol,
                          timeframe, strategy, bars, initial_equity) -> runs backtest.run_backtest
                          synchronously using bridge.get_rates and returns {deals, stats}
  static/dashboard.html    Backtest tab: symbol/timeframe/strategy/bar-count inputs, Run button,
                          result stats + equity curve (reuses the Analytics tab's stat-row style);
                          Blackout Windows section (added to the existing Alerts tab, since both are
                          small time/condition-based rule lists)
```

## Data Flow

1. Backtest: dashboard posts params to `/api/backtest` → `app.py` fetches `bridge.get_rates(symbol, timeframe, bars)` → `backtest.run_backtest()` simulates → returns deals + `analytics.compute_stats(deals)` reused as-is → dashboard renders the same stat fields as the live Analytics tab.
2. Blackout: `engine.run_once` / `_run_watchlist_entry`, right before the `check_trade_allowed` call, additionally checks `news_filter.is_blackout_active(datetime.now(timezone.utc), blackout_windows)`; if active, the function returns early (no order), same code path as an unmet risk check.

## Backtest Fill Model

Simplified, documented explicitly as an approximation: on the bar after a signal, the position is assumed filled at that bar's open. On each subsequent bar, if the bar's high >= tp (for a BUY) the trade closes at tp; if the bar's low <= sl it closes at sl; if both are crossed within the same bar, sl is assumed to have hit first (conservative). Only one simulated position open at a time per backtest run (single-strategy, single-symbol — matches the existing single-symbol engine's assumption, not the Phase 3 watchlist). No spread/slippage modeled — documented as a known gap between backtest and live results.

## Testing

- `backtest.run_backtest`: unit tests with a small synthetic rates DataFrame — signal fires, a favorable bar closes at tp (win recorded), a signal that never resolves by the end of data is left unclosed and excluded from `deals`
- `news_filter.is_blackout_active`: inside window → True, outside → False, window boundary inclusive
- `engine`: a blackout-active tick does not call `bridge.place_order` even when a valid signal exists

## Out of Scope (Phase 4)

Live/scraped economic calendar data, spread/slippage/commission modeling in the backtest, multi-position backtesting (watchlist-style concurrent symbols), walk-forward parameter optimization (grid search over strategy settings) — this phase runs one fixed-settings backtest per request, not a sweep.
