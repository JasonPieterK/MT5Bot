import indicators


def get_signal(df, settings):
    lookback = 20
    if len(df) < lookback + settings["confirmation_bars"] + 1:
        return "NONE", None, None

    prior = df.iloc[-(lookback + settings["confirmation_bars"] + 1):-settings["confirmation_bars"] - 1]
    day_high, day_low, day_close = prior["high"].max(), prior["low"].min(), prior["close"].iloc[-1]
    pivots = indicators.classic_pivot(day_high, day_low, day_close)

    confirm_window = df.iloc[-settings["confirmation_bars"]:]
    price = df["close"].iloc[-1]

    if (confirm_window["close"] > pivots["r1"]).all():
        sl = pivots["pivot"]
        tp = pivots["r2"]
        return "BUY", sl, tp

    if (confirm_window["close"] < pivots["s1"]).all():
        sl = pivots["pivot"]
        tp = pivots["s2"]
        return "SELL", sl, tp

    return "NONE", None, None
