import indicators


def get_signal(df, settings):
    if len(df) < settings["atr_period"] + 1:
        return "NONE", None, None

    last = df.iloc[-1]
    if last["spread"] > settings["max_spread_points"]:
        return "NONE", None, None

    candle_range = last["high"] - last["low"]
    if candle_range <= 0:
        return "NONE", None, None
    body = abs(last["close"] - last["open"])
    body_percent = (body / candle_range) * 100
    if body_percent < settings["min_candle_body_percent"]:
        return "NONE", None, None

    atr = indicators.atr(df, period=settings["atr_period"]).iloc[-1]
    price = last["close"]
    bullish = last["close"] > last["open"]

    if bullish:
        sl = price - atr * settings["sl_atr_multiple"]
        tp = price + atr * settings["tp_atr_multiple"]
        return "BUY", sl, tp
    else:
        sl = price + atr * settings["sl_atr_multiple"]
        tp = price - atr * settings["tp_atr_multiple"]
        return "SELL", sl, tp
