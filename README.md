<img src="static/logo.svg" width="64" height="64" alt="MT5 Bot logo">

# MT5 Bot

Multi-strategy automated trading robot for MetaTrader 5, with a local web dashboard. Python + Flask + the `MetaTrader5` package — no MQL5 required.

📖 **Install and usage instructions live in [GUIDE](GUIDE)** — requirements, `git clone`, setup, and every dashboard tab explained.

## Read this before anything else

**No strategy in this project has a demonstrated edge.**

Walk-forward testing across 4 strategies × 4 symbols × 3 timeframes, using real broker bars and real spread costs, put zero-spread expectancy within ±0.07R of zero everywhere — statistically indistinguishable from random entries before costs. Parameter tuning made things *worse*: every tuned set lost to the untouched defaults out of sample, the signature of curve-fitting. The bundled ML filter refuses to save a model on the data tested, because filtered P&L never beat unfiltered at any threshold.

So what this actually is: **a disciplined, honestly-instrumented execution framework**. It sizes positions from real contract economics, refuses trades it cannot size correctly, blocks negative-expectancy setups, and explains every decision in plain English. It is not a money-making strategy, and no amount of parameter tuning in this repo produced one.

Use it on a demo account. Judge it on payoff ratio and worst drawdown, never on win rate — the account this was built against had an 84% win rate and lost $5.7M.

## What it does

**Trading**
- **5 strategy modules**: trend-following, scalping, SMC (break of structure), grid (hardcoded safety caps), pivot breakout — plus an **ensemble** mode that trades only when a majority of the directional strategies agree
- **Trading profiles**: five risk presets (capital preservation → high risk) that set risk %, lot ceiling, concurrency, daily loss limit, max drawdown and minimum reward:risk as one bundle. Bounds are hard; nothing at runtime may exceed them
- **Auto mode** (opt-in, off by default): composes three existing mechanisms as *filter → selector → sizer* — the volatility regime decides which strategies are eligible, realised results choose among them (minimum 30 closed trades, or it refuses to pick), and an anti-martingale multiplier shrinks size after losing streaks. It may only ever tighten within the active profile, never loosen
- **Stop & target sliders**: set the stop loss and take profit for every bot trade as a multiple of ATR, or switch either off entirely. When set, they override whatever levels the strategy proposed

**Risk and safety**
- Position sizing from the symbol's real `tick_value`/`tick_size`, clamped to the broker's own min/max/step
- **Refuses to trade when the broker's lot cap binds**, rather than silently trading at a risk model you did not choose
- Mandatory stop loss, capped against ATR; minimum reward:risk floor; free-margin check before every order; broker stop-distance validation
- Daily-loss and max-drawdown kill switches computed from real closed + floating P&L
- One order per closed bar, so a persistent signal cannot re-fire every tick
- Automated trailing stop, break-even and partial take-profit, driven by the active profile
- Confirmation dialogs on every destructive action
- **Single-instance lock** — a second copy refuses to start, because two engines would place every trade twice

**Signal filters** (all opt-in, off by default): session hours, correlation exposure cap, higher-timeframe bias, volatility regime, spread quality, tick momentum, ML win-probability, ensemble agreement, confidence sizing, anti-martingale streak sizing, swap-rollover blackout, scheduled Friday flatten.

**Diagnostics** — the part that matters most in practice
- **"Why no trade?"**: live, per-symbol/strategy answer to *why isn't it trading*, naming the gate that blocked and showing the actual numbers (lots needed vs allowed, computed R:R vs the floor, stop distance)
- **Trading diagnostic**: asks MT5 itself what is blocking — algo trading off, investor-password login, symbol disabled, symbol not in Market Watch, wrong symbol name — and reports each with the fix
- **Broker symbol resolution**: brokers rename instruments (`EURUSD` → `EURUSD#`, gold → `GOLD.i#`). The bot resolves to a *tradeable* symbol and refuses to guess when ambiguous
- **Plain-English retcodes**: all 44 MT5 return codes translated to what went wrong and what to do
- **Human-readable log** at `logs/app.log`, plus a structured JSON event log and per-trade CSV
- **On-chart status panel**: optional read-only MQL5 EA mirroring live status onto an MT5 chart — see [mql5/](mql5/)

**Operations**: MT5 connection watchdog with webhook alerts, atomic state persistence that survives a crash mid-write, engine-health reporting so the UI can never show "live" while the loop is failing.

**No credentials are stored.** The bot uses whichever account your MT5 terminal is logged into. There is no password to save, encrypt, or leak.

## Dashboard

Six tabs:

| Tab | For |
|-----|-----|
| **Dashboard** | Account strip, trading mode, strategy, profile, Auto, stop/target sliders, open positions |
| **History** | Every closed deal — filterable by period, exportable as CSV |
| **Why no trade?** | Live explanation of what the engine is doing and what is blocking it |
| **Settings** | Risk and limits, position management, refresh |
| **Advanced** | Per-strategy parameters and all signal filters |
| **Logs** | Plain-English record of everything the bot does |

## Project Layout

```
app.py                     Flask API + engine thread lifecycle (entry point: python app.py)
conftest.py                Puts src/ on the path for pytest; isolates test writes from logs/

src/                        All Python packages live here
  core/                       Trading engine and execution primitives
    engine.py                  Trading loop: signal -> gates -> risk manager -> execution
    mt5_bridge.py              MetaTrader5 wrapper: orders, symbols, diagnostics
    risk_manager.py            Lot sizing, exposure caps, daily loss, drawdown kill-switch
    profiles.py                Risk presets and their bounds
    auto_mode.py               Auto: regime filter -> results selector -> streak sizer
    mt5_retcodes.py            Broker return codes in plain English
    single_instance.py         Stops a second copy trading the same account
    config.py                  Default settings, state

  strategies/                 One module per strategy, common get_signal() interface
    trend.py, scalping.py, smc.py, grid.py, pivot_breakout.py

  analysis/                   Indicators, analytics, volatility regime
  automation/                 Trailing/break-even, filters, logging, watchdog, journal

static/dashboard.html       Web dashboard (single file, no build step)
static/mt5-tokens.css       "Graphite & Amber" design tokens
mql5/                        Optional read-only on-chart status panel (MQL5 EA)
tests/                       Mirrors src/'s layout (tests/core, tests/analysis, ...)
```

Imports throughout the codebase stay as `import core.x`, `import analysis.x`, etc. — `app.py` and `conftest.py` each add `src/` to `sys.path` at the top, so nothing under `src/` needs a `src.` prefix.

Design docs and implementation plans for each build phase are in `docs/superpowers/`.

## Risk Disclaimer

⚠️ **CRITICAL: READ BEFORE USE**

This software directly places, modifies, and closes REAL TRADES on a MetaTrader 5 account connected to your broker. Trading foreign exchange, CFDs, commodities, and other leveraged instruments carries extreme risk of total capital loss. You assume ALL risk when using this software.

**THE AUTHOR(S), COPYRIGHT HOLDER(S), AND CONTRIBUTORS ARE NOT RESPONSIBLE AND DO NOT ASSUME LIABILITY FOR:**

- Any financial losses, gains, or outcomes resulting from use of this software
- Incorrect order execution, price slippage, broker delays, or connectivity failures
- Bugs, crashes, data loss, or unexpected behavior
- Missed trades, failed automated actions, or timing issues
- Account liquidation, margin calls, or forced closeouts
- Any direct, indirect, incidental, consequential, or punitive damages
- Any loss of data, profits, revenue, or opportunity

**THIS SOFTWARE IS PROVIDED "AS-IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, OR NON-INFRINGEMENT.**

You are solely responsible for:

- Understanding how each feature works before enabling it
- Testing extensively on a demo account first
- Reviewing all automated features (trailing stop, break-even, scheduled close, risk guards) and confirming they behave as expected
- Monitoring your account and being prepared to disable the app immediately if needed
- Ensuring your MT5 terminal, broker connection, and internet are stable
- Backing up your account settings and trade history

**DO NOT USE REAL MONEY UNTIL YOU ARE ABSOLUTELY CERTAIN OF THE SOFTWARE'S BEHAVIOR.**

By using this software, you acknowledge and accept all risks and agree that the author(s) shall not be liable for any losses or damages of any kind.

## License

MIT — see [LICENSE](LICENSE).
