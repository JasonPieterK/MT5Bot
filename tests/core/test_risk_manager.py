import core.risk_manager as rm


def test_lot_size_from_risk_percent():
    lots = rm.calc_lot_size(equity=10000, risk_percent=1.0, sl_distance_price=0.0050,
                             pip_value_per_lot=10, point=0.0001)
    assert lots > 0
    assert round(lots, 2) == 2.0


def test_lot_size_floors_to_broker_step():
    lots = rm.calc_lot_size(equity=1000, risk_percent=1.0, sl_distance_price=0.0050,
                             pip_value_per_lot=10, point=0.0001, lot_step=0.01, min_lot=0.01)
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
                             pip_value_per_lot=10, point=0.0001, confidence=1.0)
    half = rm.calc_lot_size(equity=10000, risk_percent=1.0, sl_distance_price=0.0050,
                             pip_value_per_lot=10, point=0.0001, confidence=0.5)
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
