# MT5 Bot

Multi-strategy automated trading robot for MetaTrader 5, with a local web dashboard. Python + Flask + the `MetaTrader5` package — no MQL5 required.

📖 **New here? Start with [GUIDE.md](GUIDE.md)** — full install and usage walkthrough, every dashboard tab explained.

## Features

- **5 strategy modules**: Trend-following, Scalping, SMC (break of structure), Grid/Martingale (hardcoded safety caps), Pivot Breakout
- **Uniform risk pipeline**: % equity lot sizing, max concurrent trades, daily loss limit, max drawdown kill-switch — applies to every strategy
- **Position manager**: trailing stop + break-even automation, applies to *any* open position on the account (not just bot-opened trades)
- **Alerts**: price and margin-level alerts with dashboard banner + sound
- **Trade journal**: per-ticket notes, persisted server-side
- **Analytics**: win rate, profit factor, equity curve, streaks — sourced from full MT5 account history, with CSV export
- **Multi-symbol watchlist**: run several symbol/strategy pairs concurrently, each in `auto` (executes trades) or `alert_only` (signal-only, no execution) mode
- **Backtesting**: bar-by-bar simulator reusing the live strategy/risk code, no MT5 Strategy Tester needed
- **News/session blackout filter**: manually defined time windows block new entries (e.g. NFP release)
- **Trading lock**: optional local passcode gate on enabling auto-trading
- **Confirmation dialogs** on Close All, Apply-to-All, and enabling auto-trading
- **Signal filters** (all opt-in): correlation-aware exposure cap, higher-timeframe bias filter, volatility-regime filter, generic session-hour filter, confidence/anti-martingale position sizing
- **Risk/execution**: partial take-profit, portfolio-level risk gate, execution latency/requote logging, swap-rollover blackout filter
- **Ops**: MT5 connection watchdog with webhook alerts, persistent app state across restarts, saved account profiles (switch logins), scheduled Friday-close flatten, structured JSON event log
- **Per-strategy analytics breakdown**, equity curve chart, backtest parameter sweep, trade-open webhook notifications
- **On-chart status panel**: a read-only MQL5 EA mirrors live status (auto state, strategy, equity, open positions) directly on an MT5 chart — see [mql5/](mql5/)
- **Ensemble mode**: trades only when a majority of the 4 directional strategies agree
- **ML win-probability filter**: small logistic regression trained on your own closed-deal history (strategy/hour/weekday features — MT5 deal history has no sl/tp, so reward:risk isn't a usable feature and isn't fabricated)
- **Microstructure filters**: spread-quality (bar-level spread vs recent average) and tick-momentum (direction bias of recent ticks)
- **Self-tuning**: flags strategies with a statistically meaningful losing track record, can auto-switch to the best performer; one-click applies the best backtest sweep result to a strategy's settings

## Requirements

- Windows (the `MetaTrader5` Python package is Windows-only)
- MetaTrader 5 terminal installed and logged into an account
- Python 3.11+

## Install

```bash
install.bat
```

Creates a virtualenv and installs `requirements.txt`.

## On-chart status panel (optional)

`mql5/MT5BotStatusPanel.mq5` is a small Expert Advisor that mirrors the app's status directly on an MT5 chart — auto/live state, active strategy, symbol/TF, equity, open positions, and how stale the data is. **It never places, modifies, or closes trades** — it only reads a status file the Python app writes every ~5s and draws labels. All trading logic stays in the Python app.

Setup:
1. In MT5: File → Open Data Folder → `MQL5/Experts/`. Copy `MT5BotStatusPanel.mq5` there.
2. Open MetaEditor (F4 in MT5), open the file, compile (F7).
3. In MT5's Navigator, drag `MT5BotStatusPanel` onto any chart (doesn't need to be the symbol you're trading).
4. MT5 requires "Allow Algo Trading" enabled for *any* EA to run its timer — turn it on even though this EA never trades.
5. With `app.py` running, the panel populates within a second or two. If it says "app not found", the Python app isn't running or hasn't written its first status snapshot yet.

The two processes sync via a plain text file in MT5's shared Common Files folder (`%APPDATA%\MetaQuotes\Terminal\Common\Files\mt5_bot_status.txt`) — no HTTP, no WebRequest allowlist needed.

## Run

```bash
start.bat
```

Opens the Flask server at `http://127.0.0.1:7500`. Open that URL in a browser for the dashboard.

## Project Layout

```
app.py                     Flask API + engine thread lifecycle (entry point: python app.py)

core/                       Trading engine and execution primitives
  engine.py                  Trading loop: strategy signal -> risk manager -> execution
  mt5_bridge.py               MetaTrader5 package wrapper
  risk_manager.py             Lot sizing, exposure caps, daily loss, drawdown kill-switch
  config.py                   Default settings, state

strategies/                 One module per strategy, common get_signal() interface
  trend.py, scalping.py, smc.py, grid.py, pivot_breakout.py

analysis/                   Data analysis and simulation
  indicators.py               MA/RSI/ATR/MACD/Bollinger Bands/Pivots/swing detection
  analytics.py                Win rate / profit factor / equity curve / streak stats
  backtest.py                 Bar-by-bar backtest simulator

automation/                 Background automation independent of any one strategy
  trailing_manager.py         Trailing-stop / break-even automation
  alerts.py                   Price / margin alert evaluation
  journal.py                  Per-ticket trade notes
  news_filter.py              Manual blackout-window filter

static/dashboard.html       Web dashboard (single file, no build step)
tests/                       Mirrors the source layout (tests/core, tests/analysis, ...)
```

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
