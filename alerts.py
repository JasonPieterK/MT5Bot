"""Price and margin alert evaluation. Price alerts fire once — caller removes a rule
after it triggers. Margin alert re-fires every check while the condition holds."""


def check_price_alerts(bridge, alert_rules):
    triggered = []
    for rule in alert_rules:
        bid, ask = bridge.get_current_price(rule["symbol"])
        if rule["condition"] == "above" and bid >= rule["price"]:
            triggered.append(rule)
        elif rule["condition"] == "below" and bid <= rule["price"]:
            triggered.append(rule)
    return triggered


def check_margin_alert(bridge, margin_level_threshold):
    level = bridge.get_margin_level()
    return 0 < level <= margin_level_threshold
