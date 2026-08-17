"""Polls all non-stateful strategy modules and only signals when a minimum number
agree on direction. Grid is excluded — it's a ladder strategy, not a directional
signal comparable to the others."""
from strategies import trend, scalping, smc, pivot_breakout

VOTING_MODULES = {
    "trend": trend,
    "scalping": scalping,
    "smc": smc,
    "pivot_breakout": pivot_breakout,
}


def get_ensemble_signal(rates_df, strategy_settings, min_agree=2):
    votes = []
    for name, module in VOTING_MODULES.items():
        signal, sl, tp = module.get_signal(rates_df, strategy_settings[name])
        if signal != "NONE":
            votes.append((name, signal, sl, tp))

    buy_votes = [v for v in votes if v[1] == "BUY"]
    sell_votes = [v for v in votes if v[1] == "SELL"]

    if len(buy_votes) >= min_agree and len(buy_votes) > len(sell_votes):
        sl = sum(v[2] for v in buy_votes) / len(buy_votes)
        tp = sum(v[3] for v in buy_votes) / len(buy_votes)
        return "BUY", sl, tp, [v[0] for v in buy_votes]

    if len(sell_votes) >= min_agree and len(sell_votes) > len(buy_votes):
        sl = sum(v[2] for v in sell_votes) / len(sell_votes)
        tp = sum(v[3] for v in sell_votes) / len(sell_votes)
        return "SELL", sl, tp, [v[0] for v in sell_votes]

    return "NONE", None, None, []
