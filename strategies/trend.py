import indicators


def get_signal(df, settings):
    if len(df) < settings["slow_period"] + 1:
        return "NONE", None, None

    close = df["close"]
    fast = indicators.ma(close, settings["fast_period"], settings["ma_type"])
    slow = indicators.ma(close, settings["slow_period"], settings["ma_type"])
    rsi = indicators.rsi(close, settings["rsi_period"])
    atr = indicators.atr(df, period=14)

    fast_now, slow_now = fast.iloc[-1], slow.iloc[-1]
    rsi_now = rsi.iloc[-1]
    price = close.iloc[-1]
    atr_now = atr.iloc[-1]

    if fast_now > slow_now and rsi_now < settings["rsi_buy_below"]:
        sl = price - atr_now * 1.5
        tp = price + atr_now * 2.5
        return "BUY", sl, tp

    if fast_now < slow_now and rsi_now > settings["rsi_sell_above"]:
        sl = price + atr_now * 1.5
        tp = price - atr_now * 2.5
        return "SELL", sl, tp

    return "NONE", None, None
