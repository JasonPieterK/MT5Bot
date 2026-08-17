import core.correlation as correlation


def test_same_group_are_correlated():
    assert correlation.are_correlated("EURUSD", "GBPUSD") is True


def test_different_group_not_correlated():
    assert correlation.are_correlated("EURUSD", "USDJPY") is False


def test_check_correlation_allowed_under_cap():
    positions = [{"symbol": "GBPUSD"}]
    assert correlation.check_correlation_allowed(positions, "EURUSD", max_correlated_positions=2) is True


def test_check_correlation_blocked_at_cap():
    positions = [{"symbol": "GBPUSD"}, {"symbol": "AUDUSD"}]
    assert correlation.check_correlation_allowed(positions, "EURUSD", max_correlated_positions=2) is False


def test_uncorrelated_symbol_always_allowed():
    positions = [{"symbol": "GBPUSD"}, {"symbol": "AUDUSD"}, {"symbol": "NZDUSD"}]
    assert correlation.check_correlation_allowed(positions, "USDJPY", max_correlated_positions=2) is True
