import pandas as pd
import core.ensemble as ensemble


def test_majority_buy_agreement_returns_buy(monkeypatch):
    monkeypatch.setattr(ensemble.trend, "get_signal", lambda df, s: ("BUY", 1.09, 1.11))
    monkeypatch.setattr(ensemble.scalping, "get_signal", lambda df, s: ("BUY", 1.095, 1.105))
    monkeypatch.setattr(ensemble.smc, "get_signal", lambda df, s: ("NONE", None, None))
    monkeypatch.setattr(ensemble.pivot_breakout, "get_signal", lambda df, s: ("SELL", 1.11, 1.09))

    settings = {"trend": {}, "scalping": {}, "smc": {}, "pivot_breakout": {}}
    signal, sl, tp, agreeing = ensemble.get_ensemble_signal(pd.DataFrame(), settings, min_agree=2)

    assert signal == "BUY"
    assert set(agreeing) == {"trend", "scalping"}
    assert round(sl, 4) == round((1.09 + 1.095) / 2, 4)


def test_no_majority_returns_none(monkeypatch):
    monkeypatch.setattr(ensemble.trend, "get_signal", lambda df, s: ("BUY", 1.09, 1.11))
    monkeypatch.setattr(ensemble.scalping, "get_signal", lambda df, s: ("SELL", 1.11, 1.09))
    monkeypatch.setattr(ensemble.smc, "get_signal", lambda df, s: ("NONE", None, None))
    monkeypatch.setattr(ensemble.pivot_breakout, "get_signal", lambda df, s: ("NONE", None, None))

    settings = {"trend": {}, "scalping": {}, "smc": {}, "pivot_breakout": {}}
    signal, sl, tp, agreeing = ensemble.get_ensemble_signal(pd.DataFrame(), settings, min_agree=2)

    assert signal == "NONE"
    assert agreeing == []


def test_below_min_agree_returns_none(monkeypatch):
    monkeypatch.setattr(ensemble.trend, "get_signal", lambda df, s: ("BUY", 1.09, 1.11))
    monkeypatch.setattr(ensemble.scalping, "get_signal", lambda df, s: ("NONE", None, None))
    monkeypatch.setattr(ensemble.smc, "get_signal", lambda df, s: ("NONE", None, None))
    monkeypatch.setattr(ensemble.pivot_breakout, "get_signal", lambda df, s: ("NONE", None, None))

    settings = {"trend": {}, "scalping": {}, "smc": {}, "pivot_breakout": {}}
    signal, sl, tp, agreeing = ensemble.get_ensemble_signal(pd.DataFrame(), settings, min_agree=2)

    assert signal == "NONE"


def test_all_four_agree_sell(monkeypatch):
    for name in ["trend", "scalping", "smc", "pivot_breakout"]:
        monkeypatch.setattr(getattr(ensemble, name), "get_signal", lambda df, s: ("SELL", 1.11, 1.09))

    settings = {"trend": {}, "scalping": {}, "smc": {}, "pivot_breakout": {}}
    signal, sl, tp, agreeing = ensemble.get_ensemble_signal(pd.DataFrame(), settings, min_agree=2)

    assert signal == "SELL"
    assert len(agreeing) == 4
