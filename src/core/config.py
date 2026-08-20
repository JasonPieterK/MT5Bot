"""Runtime settings store. Grid hard caps live in strategies/grid.py, not here — not user-editable.

Timeframe defaults below were set from this broker's own bar and spread history, not from
habit. Measured over the most recent 8,000 bars per symbol, the round-trip spread as a
share of a 1.5x-ATR stop -- the cost every trade has to overcome before it can profit:

    symbol        M1      M5     M15      H1
    EURUSD#    89.3%   29.1%   14.1%    5.4%
    GBPUSD#    78.0%   23.3%   10.5%    3.9%
    USDJPY#    53.6%   20.5%   11.4%    2.7%
    GOLD.i#     8.3%    3.3%    1.6%    0.7%

On M1 FX the spread alone is most of the stop, so no entry rule can survive it. That is an
arithmetic fact about this broker's quotes, not a fitted parameter, which is why these
timeframe defaults were changed and the strategy parameters below were NOT -- walk-forward
optimisation of those produced out-of-sample results no better than the defaults, and worse
on H1 (see the report accompanying this change).

Read honestly: measured over real bars with spread charged, no strategy here showed a
positive out-of-sample expectancy on any symbol or timeframe. These defaults are the least
costly settings, not proven profitable ones.

NOTE: the per-strategy "timeframe" keys are a UI hint only -- the engine trades
state["timeframe"]. They are kept in step with new_state() below."""

DEFAULT_SETTINGS = {
    "scalping": {
        # Was M1, where 89% of a 1.5x-ATR stop on EURUSD# is spread. M15 cuts that to 14%.
        # Even so, scalping showed no positive out-of-sample expectancy at any timeframe.
        "timeframe": "M15",
        "max_spread_points": 20,
        # A 1x-ATR stop sits inside the average bar range, so ordinary noise closes the trade
        # before the setup has been proved wrong -- and the spread, a fixed cost, eats a
        # larger share of a small stop. Measured on this broker's bars, both directions,
        # spread charged, as the share of trades reaching TP before SL (40% is break-even at
        # a 1:1.5 payoff):
        #
        #     SL:TP        1.0:1.5   2.0:3.0   3.0:4.5
        #     EURUSD# M15    32.1%     35.5%     38.7%
        #     EURUSD# H1     35.8%     38.6%     38.9%
        #     GOLD.i#  M15   38.3%     38.9%     39.7%
        #
        # Widening moves the hit rate toward break-even; it does not cross it. No stop
        # placement creates an edge -- this only stops the stop itself being the reason the
        # trade lost. 2.0 also needs fewer lots for the same risk, so the broker lot cap
        # binds less often.
        "sl_atr_multiple": 2.0,
        "tp_atr_multiple": 3.0,
        "atr_period": 14,
        "min_candle_body_percent": 30,
        "session_start_hour": 0,
        "session_end_hour": 23,
    },
    "smc": {
        "timeframe": "H1",
        "swing_lookback": 10,
        "htf_timeframe": "H1",
        "ob_fvg_mitigation_percent": 50,
        "min_risk_reward": 1.5,
    },
    "trend": {
        # H1 beat M15 out of sample on all four symbols tested, entirely on cost.
        "timeframe": "H1",
        "ma_type": "EMA",
        "fast_period": 9,
        "slow_period": 21,
        "rsi_period": 14,
        "rsi_buy_below": 65,
        "rsi_sell_above": 35,
        "confirmation_bars": 1,
    },
    "grid": {
        "timeframe": "M5",
        "grid_step_points": 100,
        "lot_multiplier": 1.0,
    },
    "pivot_breakout": {
        # Fires 2-7 times per 8,000 bars, which is far too rarely to validate at all.
        # Treat this strategy as unproven rather than as an option that was checked.
        "timeframe": "H1",
        "pivot_type": "classic",
        "confirmation_bars": 1,
        "require_retest": False,
    },
}

GLOBAL_SETTINGS = {
    "risk_percent": 1.0,
    # Hard lot ceiling owned by the active trading profile, on top of the broker's own
    # volume_max. 0 means "no profile ceiling; the broker's limit stands". Presets derive
    # this from volume_max at apply time -- see core/profiles.py.
    "max_lot": 0.0,
    "max_concurrent_trades": 3,
    "daily_loss_limit_percent": 5.0,
    "max_drawdown_percent": 15.0,

    # --- trade-quality gates. On by default, because the one blown-up trade group in this
    # --- account's own history failed on exactly these three and nothing else.
    # Minimum planned TP:SL. 825 real trades won 84% of the time and still lost $5.7M at a
    # 0.071 payoff ratio; break-even at that win rate needs 0.19. Anything below this floor
    # is rejected before it is sized.
    "min_reward_risk": 1.5,
    # A stop many ATRs from price is an unbounded loss with a stop attached. Signals whose
    # stop is wider than this multiple of ATR(14) are refused.
    "max_sl_atr_multiple": 3.0,
    # When the broker's max-lot limit is smaller than the risk setting asks for, the
    # position is made SMALLER: the stop loss is unchanged, so the money at risk is strictly
    # below the configured percentage. That is safer than requested, not riskier, so it is
    # allowed by default and simply logged.
    #
    # This was briefly True, on the reasoning that the losing group in this account's history
    # had a median lot of exactly 50.0 (the cap). That conflated two different things: those
    # trades were unbounded because losses ran, not because the size was capped. Blocking
    # here meant refusing trades for being too small, which stopped the bot trading at all
    # on a large account. The dangerous direction -- min_lot forcing MORE risk than
    # configured -- is a separate check and still blocks.
    "block_when_lot_capped": False,
    # --- Dashboard stop/target sliders. Off by default, so each strategy keeps placing its
    # --- own levels: Trend and Scalping from ATR, SMC from the prior swing, Pivot breakout
    # --- from the pivot. A single control cannot edit four different rules, so when enabled
    # --- it OVERRIDES whatever the strategy proposed.
    "bot_stop_override_enabled": False,
    # 0 means no stop / no target at all -- the fully-left slider position. That really does
    # send the order naked on that side; see engine.stop_is_optional for why the mandatory
    # stop check stands down rather than blocking every trade in silence.
    "bot_sl_atr_multiple": 2.0,
    "bot_tp_atr_multiple": 3.0,
    "slippage_points": 20,
    "trailing_enabled": False,
    "trailing_distance_points": 100,
    "breakeven_enabled": False,
    "breakeven_trigger_points": 100,
    "breakeven_offset_points": 10,
    "correlation_filter_enabled": False,
    "correlation_max_positions": 2,
    "htf_filter_enabled": False,
    "htf_timeframe": "H1",
    "volatility_regime_filter_enabled": False,
    "confidence_sizing_enabled": False,
    "streak_sizing_enabled": False,
    "session_filter_enabled": False,
    "session_start_hour": 0,
    "session_end_hour": 23,
    "partial_tp_enabled": False,
    "partial_tp_trigger_points": 100,
    "partial_tp_close_fraction": 0.5,
    # Aggregate open risk. 20% was unreachable in practice (3 trades x 1% = 3%), so it
    # never gated anything; 6% is a real ceiling that still leaves room for the
    # configured 3 concurrent trades plus any manual positions.
    "portfolio_risk_filter_enabled": True,
    "max_portfolio_risk_percent": 6.0,
    "swap_filter_enabled": False,
    "swap_block_hours_before_rollover": 1,
    "swap_rollover_hour_utc": 21,
    "schedule_filter_enabled": False,
    "schedule_disable_weekday": 4,
    "schedule_disable_hour_utc": 21,
    "watchdog_webhook_url": "",
    "trade_notify_enabled": False,
    "ensemble_min_agree": 2,
    "ml_filter_enabled": False,
    "ml_filter_min_probability": 0.5,
    "spread_quality_filter_enabled": False,
    "spread_quality_max_ratio": 1.5,
    "tick_momentum_filter_enabled": False,
    "tick_momentum_count": 50,
    "tick_momentum_threshold": 0.2,
    # Auto mode: OPT-IN and off by default. When on, the bot may rotate between strategies
    # on this account's own realised results and shrink position size after consecutive
    # losses -- always strictly inside the active profile's bounds. See core/auto_mode.py.
    "auto_mode_enabled": False,
    "auto_tune_enabled": False,
    "auto_tune_min_trades": 10,
    "auto_tune_min_profit_factor": 0.8,
}


def new_state():
    return {
        "active_strategy": "trend",
        "symbol": "EURUSD",
        # This is the timeframe single-symbol mode actually trades. M5 charged ~29% of every
        # stop to spread on EURUSD#; H1 charges ~5%.
        "timeframe": "H1",
        # "off" | "single"
        "trading_mode": "off",
        # Highest equity seen, and the account it was seen on. The login matters: a peak
        # carried over from a previous account makes the new one look catastrophically
        # down, which trips the drawdown kill switch and flattens healthy positions.
        "peak_equity": None,
        "peak_equity_login": None,
    }
