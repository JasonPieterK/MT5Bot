from unittest.mock import MagicMock
import automation.alerts as alerts


def test_price_alert_triggers_when_above_condition_met():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.1050, 1.1052)
    rules = [{"id": 1, "symbol": "EURUSD", "condition": "above", "price": 1.1000}]
    triggered = alerts.check_price_alerts(bridge, rules)
    assert len(triggered) == 1
    assert triggered[0]["id"] == 1


def test_price_alert_does_not_trigger_when_not_met():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.0950, 1.0952)
    rules = [{"id": 1, "symbol": "EURUSD", "condition": "above", "price": 1.1000}]
    triggered = alerts.check_price_alerts(bridge, rules)
    assert triggered == []


def test_price_alert_below_condition():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.0940, 1.0942)
    rules = [{"id": 2, "symbol": "EURUSD", "condition": "below", "price": 1.0950}]
    triggered = alerts.check_price_alerts(bridge, rules)
    assert len(triggered) == 1


def test_margin_alert_triggers_below_threshold():
    bridge = MagicMock()
    bridge.get_margin_level.return_value = 80.0
    assert alerts.check_margin_alert(bridge, margin_level_threshold=100.0) is True


def test_margin_alert_does_not_trigger_above_threshold():
    bridge = MagicMock()
    bridge.get_margin_level.return_value = 300.0
    assert alerts.check_margin_alert(bridge, margin_level_threshold=100.0) is False


def test_margin_alert_zero_level_does_not_trigger():
    bridge = MagicMock()
    bridge.get_margin_level.return_value = 0.0
    assert alerts.check_margin_alert(bridge, margin_level_threshold=100.0) is False
