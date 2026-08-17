"""Higher-timeframe bias filter. Blocks signals that fight the HTF trend direction."""
import analysis.indicators as indicators


def get_bias(htf_df, period=50):
    if len(htf_df) < period + 1:
        return "NEUTRAL"
    ema = indicators.ma(htf_df["close"], period, "EMA")
    price = htf_df["close"].iloc[-1]
    if price > ema.iloc[-1]:
        return "BULL"
    if price < ema.iloc[-1]:
        return "BEAR"
    return "NEUTRAL"


def signal_matches_bias(signal, bias):
    if bias == "NEUTRAL":
        return True
    if signal == "BUY":
        return bias == "BULL"
    if signal == "SELL":
        return bias == "BEAR"
    return True
