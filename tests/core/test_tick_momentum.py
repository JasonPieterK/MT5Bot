import core.tick_momentum as tick_momentum


def test_all_up_ticks_gives_positive_one():
    assert tick_momentum.momentum_score([1.0, 1.1, 1.2, 1.3]) == 1.0


def test_all_down_ticks_gives_negative_one():
    assert tick_momentum.momentum_score([1.3, 1.2, 1.1, 1.0]) == -1.0


def test_mixed_ticks_gives_zero():
    assert tick_momentum.momentum_score([1.0, 1.1, 1.0, 1.1, 1.0]) == 0.0


def test_insufficient_ticks_gives_zero():
    assert tick_momentum.momentum_score([1.0]) == 0.0


def test_buy_matches_positive_momentum():
    assert tick_momentum.signal_matches_momentum("BUY", 0.5, threshold=0.2) is True
    assert tick_momentum.signal_matches_momentum("BUY", 0.1, threshold=0.2) is False


def test_sell_matches_negative_momentum():
    assert tick_momentum.signal_matches_momentum("SELL", -0.5, threshold=0.2) is True
    assert tick_momentum.signal_matches_momentum("SELL", -0.1, threshold=0.2) is False
