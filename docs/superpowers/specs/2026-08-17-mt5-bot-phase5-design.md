# MT5 Bot — Phase 5 Design

## Purpose

Closes remaining MT5Manager UI-parity items from the original request: confirmation dialogs on trading actions, hover tooltips, an optional local trading-lock passcode (MT5Manager's "automated trading locks with optional password protection"), and analytics CSV export (previously flagged Out of Scope). Also fixes a gap found in this pass: Phase 3 added watchlist CRUD but never exposed a UI toggle for `state["watchlist_enabled"]` itself — added here.

## Scope

1. **Trading lock** — local-only convenience gate, not a real auth system (single-user desktop tool). `config.py` state gains `lock_enabled` (bool) and `lock_passcode` (string, plain — no external accounts or real credentials involved, matches the "prohibited: entering passwords for third parties" boundary not applying here since it's a self-set local PIN). `/api/lock` POST sets `{enabled, passcode}`. `/api/auto` and the new `/api/watchlist_mode` POST require a matching `passcode` field in the request body when `lock_enabled` is True and the request is turning trading **ON**; turning OFF is never blocked (never lock the user out of stopping the bot).
2. **Watchlist-mode toggle** (gap fix) — `/api/watchlist_mode` POST `{enabled, passcode}` sets `state["watchlist_enabled"]`, mirrored by a toggle button in the dashboard's Watchlist tab.
3. **Confirmation dialogs** — client-side `confirm()` before: Close All, Apply Now to All Positions, and turning Auto/Watchlist-mode ON (turning OFF needs no confirmation).
4. **Hover tooltips** — `title` attributes added to strategy-settings fields and Position Manager fields (static, one-line description per field key).
5. **Analytics CSV export** — `GET /api/analytics/export` streams the same deals `/api/analytics` uses as a CSV download.

## Architecture

```
config.py (extended)     new_state() gains "lock_enabled": False, "lock_passcode": ""
app.py (extended)        /api/lock (POST), /api/watchlist_mode (POST), /api/analytics/export (GET)
                          _check_lock(passcode) -> bool helper used by /api/auto and /api/watchlist_mode
static/dashboard.html     confirm() wraps on the 3 actions listed above; title attrs on settings
                          fields; Watchlist tab gains an enable/disable toggle button; a small
                          Lock Settings row (enable checkbox + passcode input) added to the
                          Position Manager tab (co-located with other global-trading controls)
```

## Testing

- `_check_lock`: unit-testable pure function — lock disabled always passes, lock enabled with correct passcode passes, wrong passcode fails
- `/api/auto` POST with lock enabled and wrong/missing passcode returns 403 and does not toggle state; turning OFF always succeeds regardless of passcode
- `/api/watchlist_mode` same pattern
- `/api/analytics/export` returns `text/csv` content type with a header row

## Out of Scope (Phase 5)

Passcode hashing/storage hardening (plain string is accepted here — this is a local single-user convenience lock, not a security boundary; documented explicitly, not silently weakened), any multi-user or network-facing auth, further MT5Manager visual-identity matching beyond dialogs/tooltips/lock (exact color/typography cloning was not specified in enough detail from the source repo to replicate precisely).
