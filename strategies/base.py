"""Every strategy module exposes get_signal(rates_df, settings) -> (signal, sl, tp).
signal is one of "BUY", "SELL", "NONE". sl/tp are absolute prices, or None when signal is "NONE".
"""
