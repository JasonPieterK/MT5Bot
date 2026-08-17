import analysis.analytics as analytics


def test_empty_deals_returns_zeroed_stats():
    stats = analytics.compute_stats([])
    assert stats["win_rate"] == 0
    assert stats["profit_factor"] == 0
    assert stats["equity_curve"] == []
    assert stats["current_streak"] == 0


def test_win_rate_and_profit_factor():
    deals = [
        {"ticket": 1, "symbol": "EURUSD", "profit": 100.0, "time": 1},
        {"ticket": 2, "symbol": "EURUSD", "profit": -50.0, "time": 2},
        {"ticket": 3, "symbol": "EURUSD", "profit": 100.0, "time": 3},
        {"ticket": 4, "symbol": "EURUSD", "profit": -25.0, "time": 4},
    ]
    stats = analytics.compute_stats(deals)
    assert stats["win_rate"] == 50.0
    assert stats["profit_factor"] == round(200.0 / 75.0, 2)


def test_equity_curve_is_cumulative():
    deals = [
        {"ticket": 1, "symbol": "EURUSD", "profit": 10.0, "time": 1},
        {"ticket": 2, "symbol": "EURUSD", "profit": -5.0, "time": 2},
        {"ticket": 3, "symbol": "EURUSD", "profit": 20.0, "time": 3},
    ]
    stats = analytics.compute_stats(deals)
    assert stats["equity_curve"] == [10.0, 5.0, 25.0]


def test_current_streak_counts_trailing_wins():
    deals = [
        {"ticket": 1, "symbol": "EURUSD", "profit": -5.0, "time": 1},
        {"ticket": 2, "symbol": "EURUSD", "profit": 10.0, "time": 2},
        {"ticket": 3, "symbol": "EURUSD", "profit": 10.0, "time": 3},
    ]
    stats = analytics.compute_stats(deals)
    assert stats["current_streak"] == 2


def test_current_streak_counts_trailing_losses_as_negative():
    deals = [
        {"ticket": 1, "symbol": "EURUSD", "profit": 10.0, "time": 1},
        {"ticket": 2, "symbol": "EURUSD", "profit": -5.0, "time": 2},
        {"ticket": 3, "symbol": "EURUSD", "profit": -5.0, "time": 3},
    ]
    stats = analytics.compute_stats(deals)
    assert stats["current_streak"] == -2
