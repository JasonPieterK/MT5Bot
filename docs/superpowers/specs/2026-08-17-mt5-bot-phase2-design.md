# MT5 Bot — Phase 2 Design

## Purpose

MT5Manager feature parity, built on top of Phase 1's Flask app (`app.py`/`engine.py`/`mt5_bridge.py`). Adds: trailing-stop/break-even automation (applies to any open position on the account, not just bot-opened trades), price/margin alerts (sound + dashboard banner), a server-side trade journal, an analytics dashboard sourced from MT5 account history, and an installer.

## Architecture

```
MT5 Bot/
  trailing_manager.py     apply_trailing(bridge, position, distance_points)
                           apply_breakeven(bridge, position, trigger_points, offset_points)
                           acts on every open position returned by bridge.get_open_positions(),
                           regardless of which strategy (or a manual trade) opened it
  alerts.py                check_price_alerts(bridge, alert_rules) -> list of triggered rules
                           check_margin_alert(bridge, margin_level_threshold) -> bool
                           alert_rules: in-memory list of {id, symbol, condition ("above"|"below"), price}
  journal.py                get_note(ticket) -> str
                            set_note(ticket, text) -> None
                            backed by logs/journal.json ({ticket: note_text})
  analytics.py              compute_stats(deals) -> {win_rate, profit_factor, equity_curve, streaks}
                            deals sourced from mt5_bridge.get_history_deals(from_date)
  install.bat                creates venv, pip installs requirements.txt
  start.bat                  activates venv, runs app.py
  mt5_bridge.py (extended)  + get_history_deals(from_date), modify_position(ticket, sl, tp),
                            get_margin_level()
  engine.py (extended)      run_once() gains a second pass after strategy signal handling:
                            for every open position, apply trailing/BE (if enabled) and check
                            alert rules — independent of which strategy is active
  app.py (extended)         new routes: GET/POST /api/trailing_settings, GET/POST /api/alerts,
                            GET/POST /api/journal/<ticket>, GET /api/analytics
  static/dashboard.html     3 new tabs: Position Manager, Analytics, Alerts. Journal notes
                            inline in the open-positions table.
```

## Data Flow

1. Engine tick (existing 5s loop) — after strategy signal pass, iterates `bridge.get_open_positions()`:
   - if trailing enabled: `trailing_manager.apply_trailing()` calls `bridge.modify_position()` when price has moved favorably by `distance_points`
   - if break-even enabled: `trailing_manager.apply_breakeven()` moves SL to entry + offset once price has moved favorably by `trigger_points`
   - `alerts.check_price_alerts()` / `check_margin_alert()` evaluated against current tick/account state; triggered rules appended to an in-memory `triggered_alerts` list app.py exposes via `/api/status`
2. Dashboard polls `/api/status` (extended to include `triggered_alerts`) — on new triggered alert, plays a sound and shows a banner, then acks it via `POST /api/alerts/ack/<id>` to clear.
3. Analytics tab: `GET /api/analytics` calls `mt5_bridge.get_history_deals(from_date)` → `analytics.compute_stats()` → win rate / profit factor / equity curve points / current streak. Computed on request, not cached (Phase 2 scope: no need for real-time push).
4. Journal: clicking a ticket row in Open Positions reveals a note textarea; save posts to `/api/journal/<ticket>`, persisted to `logs/journal.json`.
5. Position Manager tab: trailing/BE settings (distance/trigger/offset in points) editable live like strategy settings; "Apply to All" button forces one immediate pass over all open positions.

## Settings

New global settings (in `config.py` `GLOBAL_SETTINGS`, editable via existing `/api/global_settings`):
- `trailing_enabled` (bool), `trailing_distance_points`
- `breakeven_enabled` (bool), `breakeven_trigger_points`, `breakeven_offset_points`
- `margin_alert_level_percent`

Alert price rules are separate CRUD resources (`/api/alerts`), not part of `GLOBAL_SETTINGS`, since they're a dynamic list rather than fixed keys.

## Error Handling

- `modify_position` failure (requote, invalid stops) → log to existing `logs/trades.csv` (reuse `engine.log_trade`, extend row type), skip that position this tick, retry next tick
- `get_history_deals` returns empty/None → analytics returns zeroed stats, dashboard shows "no trade history" rather than erroring
- Journal write failure (disk full, permissions) → API returns 500 with message, dashboard shows inline error, note not lost from the textarea (client keeps unsent text)

## Testing

- `trailing_manager`: unit tests with mocked bridge — verify `modify_position` called with correct new SL when price crosses distance/trigger thresholds, not called when it hasn't
- `alerts`: unit tests — rule triggers exactly once per crossing, margin alert triggers below threshold
- `journal`: unit tests — read/write round-trip through a temp file
- `analytics`: unit tests — known deal list → known win_rate/profit_factor/streak output
- Manual demo-account smoke test: enable trailing on an open demo position, confirm SL moves; add a price alert, confirm banner+sound fires; add a journal note, reload dashboard, confirm it persists; check Analytics tab renders real numbers from demo history

## Out of Scope (Phase 2)

Windows toast notifications (deferred per your choice — sound + banner only), multi-symbol concurrent trailing across a watchlist beyond what Phase 1 already scopes, alert delivery when dashboard tab is closed (browser-only, matches MT5Manager), editing/deleting individual analytics deals, CSV export of analytics.
