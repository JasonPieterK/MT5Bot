import analysis.indicators as indicators


def get_signal(df, settings):
    lookback = settings["swing_lookback"]
    if len(df) < lookback * 4:
        return "NONE", None, None

    swings = indicators.swing_points(df, lookback=lookback)
    swing_highs = df["high"][swings["swing_high"]]
    swing_lows = df["low"][swings["swing_low"]]

    if len(swing_highs) < 2 or len(swing_lows) < 1:
        return "NONE", None, None

    last_swing_high = swing_highs.iloc[-2]
    price = df["close"].iloc[-1]
    prior_swing_low = swing_lows.iloc[-1]

    broke_structure_up = price > last_swing_high

    if broke_structure_up:
        entry = price
        sl = prior_swing_low
        risk = entry - sl
        if risk <= 0:
            return "NONE", None, None
        tp = entry + risk * settings["min_risk_reward"]
        return "BUY", sl, tp

    return "NONE", None, None
