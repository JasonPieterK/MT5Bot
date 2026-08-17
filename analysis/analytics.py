"""Trading performance stats computed from a list of closed-deal dicts
(as returned by mt5_bridge.get_history_deals)."""


def compute_stats(deals):
    if not deals:
        return {"win_rate": 0, "profit_factor": 0, "equity_curve": [], "current_streak": 0}

    wins = [d for d in deals if d["profit"] > 0]
    losses = [d for d in deals if d["profit"] < 0]

    win_rate = round(len(wins) / len(deals) * 100, 2)

    gross_profit = sum(d["profit"] for d in wins)
    gross_loss = abs(sum(d["profit"] for d in losses))
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
    else:
        profit_factor = round(gross_profit, 2) if gross_profit > 0 else 0

    equity = 0.0
    curve = []
    for d in deals:
        equity += d["profit"]
        curve.append(round(equity, 2))

    streak = 0
    for d in reversed(deals):
        if d["profit"] > 0 and streak >= 0:
            streak += 1
        elif d["profit"] < 0 and streak <= 0:
            streak -= 1
        else:
            break

    return {
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "equity_curve": curve,
        "current_streak": streak,
    }
