import core.risk_manager as rm


def test_lot_size_from_risk_percent():
    lots = rm.calc_lot_size(equity=10000, risk_percent=1.0, sl_distance_price=0.0050,
                             tick_value=1.0, tick_size=0.00001)
    assert lots > 0
    # 50 pips SL on 5-digit FX = $500 risk per lot; $100 of risk buys 0.2 lots.
    # This asserted 2.0 before -- the exact 10x oversize the old pip/point maths produced.
    assert round(lots, 2) == 0.2


def test_lot_size_floors_to_broker_step():
    lots = rm.calc_lot_size(equity=1000, risk_percent=1.0, sl_distance_price=0.0050,
                             tick_value=1.0, tick_size=0.00001, lot_step=0.01, min_lot=0.01)
    assert lots >= 0.01
    assert round(lots % 0.01, 5) == 0


def test_check_max_concurrent_trades_blocks():
    ok, reason = rm.check_trade_allowed(
        open_position_count=3, max_concurrent_trades=3,
        daily_pnl_percent=0.0, daily_loss_limit_percent=5.0,
        drawdown_percent=0.0, max_drawdown_percent=15.0,
    )
    assert ok is False
    assert "concurrent" in reason.lower()


def test_check_daily_loss_limit_blocks():
    ok, reason = rm.check_trade_allowed(
        open_position_count=0, max_concurrent_trades=3,
        daily_pnl_percent=-6.0, daily_loss_limit_percent=5.0,
        drawdown_percent=0.0, max_drawdown_percent=15.0,
    )
    assert ok is False
    assert "daily loss" in reason.lower()


def test_check_max_drawdown_triggers_kill_switch():
    ok, reason = rm.check_trade_allowed(
        open_position_count=0, max_concurrent_trades=3,
        daily_pnl_percent=0.0, daily_loss_limit_percent=5.0,
        drawdown_percent=16.0, max_drawdown_percent=15.0,
    )
    assert ok is False
    assert "drawdown" in reason.lower()


def test_check_trade_allowed_passes_when_within_limits():
    ok, reason = rm.check_trade_allowed(
        open_position_count=1, max_concurrent_trades=3,
        daily_pnl_percent=-1.0, daily_loss_limit_percent=5.0,
        drawdown_percent=2.0, max_drawdown_percent=15.0,
    )
    assert ok is True


def test_should_flatten_all_on_max_drawdown():
    assert rm.should_flatten_all(drawdown_percent=16.0, max_drawdown_percent=15.0) is True
    assert rm.should_flatten_all(drawdown_percent=10.0, max_drawdown_percent=15.0) is False


def test_calc_lot_size_with_confidence_scales_down():
    full = rm.calc_lot_size(equity=10000, risk_percent=1.0, sl_distance_price=0.0050,
                             tick_value=1.0, tick_size=0.00001, confidence=1.0)
    half = rm.calc_lot_size(equity=10000, risk_percent=1.0, sl_distance_price=0.0050,
                             tick_value=1.0, tick_size=0.00001, confidence=0.5)
    assert half < full


def test_calc_confidence_higher_rr_gives_higher_confidence():
    low_rr = rm.calc_confidence(entry=1.10, sl=1.09, tp=1.11)
    high_rr = rm.calc_confidence(entry=1.10, sl=1.09, tp=1.14)
    assert high_rr > low_rr


def test_calc_confidence_clamped_to_bounds():
    assert rm.calc_confidence(entry=1.10, sl=1.099, tp=1.30) == 1.5
    assert rm.calc_confidence(entry=1.10, sl=1.05, tp=1.101) == 0.5


def test_streak_multiplier_full_size_after_win():
    assert rm.calc_streak_multiplier([10, -5, 10]) == 1.0


def test_streak_multiplier_shrinks_after_losses():
    mult = rm.calc_streak_multiplier([-5, -5, -5])
    assert mult < 1.0


def test_streak_multiplier_has_floor():
    mult = rm.calc_streak_multiplier([-5] * 20, floor=0.2)
    assert mult == 0.2


def test_calc_lot_size_clamped_to_broker_max():
    # huge equity + tiny sl distance would otherwise blow past any sane lot size
    lots = rm.calc_lot_size(equity=5_000_000, risk_percent=1.0, sl_distance_price=0.00001,
                             tick_value=1.0, tick_size=0.00001, max_lot=50.0)
    assert lots == 50.0


def test_calc_lot_size_default_max_lot_still_applies():
    lots = rm.calc_lot_size(equity=5_000_000, risk_percent=1.0, sl_distance_price=0.00001,
                             tick_value=1.0, tick_size=0.00001)
    assert lots == 100.0


# --- property: money actually risked must equal equity * risk_percent, per instrument ---

def _risked_dollars(lots, sl_distance_price, tick_value, tick_size):
    return lots * (sl_distance_price / tick_size) * tick_value


def test_lot_size_risks_exactly_one_percent_on_eurusd():
    # 5-digit EURUSD: tick_size 0.00001, tick_value $1.00 per lot.
    lots = rm.calc_lot_size(equity=5_400_000, risk_percent=1.0, sl_distance_price=0.0020,
                             tick_value=1.0, tick_size=0.00001, max_lot=1000.0)
    assert lots == 270.0  # the old code produced 2700 here
    assert abs(_risked_dollars(lots, 0.0020, 1.0, 0.00001) - 54_000) < 54


def test_lot_size_risks_exactly_one_percent_on_xauusd():
    # XAUUSD: tick_size 0.01, tick_value $1.00 per lot ($100 per $1 move per lot).
    lots = rm.calc_lot_size(equity=5_400_000, risk_percent=1.0, sl_distance_price=3.00,
                             tick_value=1.0, tick_size=0.01, max_lot=1000.0)
    assert lots == 180.0  # the old code produced 1.8 here
    assert abs(_risked_dollars(lots, 3.00, 1.0, 0.01) - 54_000) < 54


def test_lot_size_risks_exactly_one_percent_on_usdjpy():
    # 3-digit USDJPY: tick_size 0.001, tick_value ~$0.67 per lot.
    lots = rm.calc_lot_size(equity=100_000, risk_percent=1.0, sl_distance_price=0.200,
                             tick_value=0.67, tick_size=0.001)
    assert abs(_risked_dollars(lots, 0.200, 0.67, 0.001) - 1_000) < 15


def test_lot_size_falls_back_to_min_lot_when_tick_economics_unusable():
    assert rm.calc_lot_size(equity=10000, risk_percent=1.0, sl_distance_price=0.005,
                             tick_value=0, tick_size=0, min_lot=0.01) == 0.01


# --- quality gates: the -$5.7M pattern in this account's own history was a payoff-ratio
# --- failure (84% win rate, 0.071 payoff), so reward:risk is a first-class gate now.

def test_reward_risk_ratio():
    assert rm.reward_risk(entry=1.1000, sl=1.0980, tp=1.1040) == 2.0


def test_reward_risk_is_zero_without_stops():
    assert rm.reward_risk(1.10, None, 1.11) == 0.0
    assert rm.reward_risk(1.10, 0.0, 1.11) == 0.0
    assert rm.reward_risk(1.10, 1.10, 1.11) == 0.0


def test_check_reward_risk_blocks_below_floor():
    ok, reason = rm.check_reward_risk(entry=1.1000, sl=1.0970, tp=1.1010, min_reward_risk=1.5)
    assert ok is False
    assert "reward:risk" in reason.lower()


def test_check_reward_risk_allows_at_exactly_the_floor():
    ok, _ = rm.check_reward_risk(entry=1.1000, sl=1.0980, tp=1.1030, min_reward_risk=1.5)
    assert ok is True


def test_check_stop_sanity_requires_a_stop_loss():
    for missing in (None, 0.0):
        ok, reason = rm.check_stop_sanity(entry=1.10, sl=missing, atr=0.001,
                                           max_sl_atr_multiple=3.0)
        assert ok is False
        assert "stop loss" in reason.lower()


def test_check_stop_sanity_blocks_absurdly_wide_stop():
    ok, reason = rm.check_stop_sanity(entry=1.10, sl=1.05, atr=0.001, max_sl_atr_multiple=3.0)
    assert ok is False
    assert "atr" in reason.lower()


def test_check_stop_sanity_allows_normal_atr_stop():
    ok, _ = rm.check_stop_sanity(entry=1.10, sl=1.0985, atr=0.001, max_sl_atr_multiple=3.0)
    assert ok is True


def test_loss_per_lot_matches_broker_economics():
    # EURUSD# at XM: tick_value 1.0 per 0.00001. A 20-pip (0.0020) stop is $200 per lot.
    assert rm.loss_per_lot(0.0020, tick_value=1.0, tick_size=0.00001) == 200.0
    # GOLD.i#: tick_value 1.0 per 0.01, so $100 per $1 of price -- a $5 stop is $500 a lot.
    assert rm.loss_per_lot(5.0, tick_value=1.0, tick_size=0.01) == 500.0


def test_lot_clamp_report_none_when_cap_does_not_bind():
    assert rm.lot_clamp_report(equity=10_000, risk_percent=1.0, sl_distance_price=0.0020,
                                tick_value=1.0, tick_size=0.00001, max_lot=50.0,
                                actual_lots=0.5) is None


def test_lot_clamp_report_quantifies_the_real_risk():
    # The live account: $5.43M equity, 1% asked, 20-pip stop -> 271 lots wanted, 50 allowed.
    report = rm.lot_clamp_report(equity=5_431_669.0, risk_percent=1.0,
                                  sl_distance_price=0.0020, tick_value=1.0, tick_size=0.00001,
                                  max_lot=50.0, actual_lots=50.0)
    assert report is not None
    assert round(report["requested_lots"]) == 272
    assert report["configured_risk_percent"] == 1.0
    # 50 lots * $200 = $10,000 of $5.43M
    assert round(report["actual_risk_percent"], 3) == 0.184
    assert round(report["max_expressible_risk_percent"], 3) == 0.184


def test_calc_lot_size_never_exceeds_the_hard_risk_ceiling():
    # 500% risk typed by hand must not become a 500% position.
    lots = rm.calc_lot_size(equity=10_000, risk_percent=500.0, sl_distance_price=0.0050,
                             tick_value=1.0, tick_size=0.00001, max_lot=1000.0)
    capped = rm.calc_lot_size(equity=10_000, risk_percent=rm.HARD_MAX_RISK_PERCENT,
                               sl_distance_price=0.0050, tick_value=1.0, tick_size=0.00001,
                               max_lot=1000.0)
    assert lots == capped


def test_min_lot_overrisk_none_when_the_floor_does_not_bind():
    assert rm.min_lot_overrisk_report(equity=10_000, risk_percent=1.0,
                                       sl_distance_price=0.0020, tick_value=1.0,
                                       tick_size=0.00001, min_lot=0.01,
                                       actual_lots=0.5) is None


def test_min_lot_overrisk_is_the_dangerous_direction():
    # $200 account, 1% = $2 of risk. A $5 gold stop costs $500 a lot, so the risk allows
    # 0.004 lots -- and the broker's smallest trade is 0.01, which risks $5, i.e. 2.5%.
    report = rm.min_lot_overrisk_report(equity=200.0, risk_percent=1.0, sl_distance_price=5.0,
                                         tick_value=1.0, tick_size=0.01, min_lot=0.01,
                                         actual_lots=0.01)
    assert report is not None
    assert round(report["requested_lots"], 4) == 0.004
    assert round(report["actual_risk_percent"], 2) == 2.5
    assert report["actual_risk_percent"] > report["configured_risk_percent"]
