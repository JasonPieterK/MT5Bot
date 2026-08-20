import core.mt5_retcodes as mt5_retcodes


def test_explain_trade_disabled_tells_user_to_enable_algo_trading():
    msg = mt5_retcodes.explain(10017)
    assert "10017" in msg
    assert "DISABLED" in msg
    assert "Algo Trading" in msg


def test_explain_no_money_suggests_lowering_risk():
    msg = mt5_retcodes.explain(10019)
    assert "margin" in msg.lower()
    assert "risk_percent" in msg


def test_explain_accepts_string_retcode():
    assert "10017" in mt5_retcodes.explain("10017")


def test_explain_unknown_code_still_returns_the_number():
    msg = mt5_retcodes.explain(99999)
    assert "99999" in msg
    assert "Unknown" in msg


def test_explain_non_numeric_passes_through():
    """Watchlist failures log an exception string in the retcode slot."""
    assert mt5_retcodes.explain("boom") == "boom"
