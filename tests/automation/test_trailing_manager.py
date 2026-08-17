from unittest.mock import MagicMock
import automation.trailing_manager as tm


def buy_position(sl=1.0950):
    return {"ticket": 1, "symbol": "EURUSD", "volume": 0.1, "type": "BUY",
            "price_open": 1.1000, "sl": sl, "tp": 1.1200}


def sell_position(sl=1.1050):
    return {"ticket": 2, "symbol": "EURUSD", "volume": 0.1, "type": "SELL",
            "price_open": 1.1000, "sl": sl, "tp": 1.0800}


def test_apply_trailing_moves_sl_up_for_buy_when_price_advances():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.1100, 1.1102)
    pos = buy_position(sl=1.0950)
    moved = tm.apply_trailing(bridge, pos, distance_points=100)
    assert moved is True
    bridge.modify_position.assert_called_once()
    args = bridge.modify_position.call_args[0]
    assert args[0] == 1
    assert round(args[1], 4) == round(1.1100 - 0.0100, 4)


def test_apply_trailing_does_not_move_sl_backward_for_buy():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.0960, 1.0962)
    pos = buy_position(sl=1.0950)
    moved = tm.apply_trailing(bridge, pos, distance_points=100)
    assert moved is False
    bridge.modify_position.assert_not_called()


def test_apply_trailing_moves_sl_down_for_sell_when_price_declines():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.0898, 1.0900)
    pos = sell_position(sl=1.1050)
    moved = tm.apply_trailing(bridge, pos, distance_points=100)
    assert moved is True
    bridge.modify_position.assert_called_once()


def test_apply_breakeven_moves_sl_to_entry_plus_offset_for_buy():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.1105, 1.1107)
    pos = buy_position(sl=1.0950)
    moved = tm.apply_breakeven(bridge, pos, trigger_points=100, offset_points=10)
    assert moved is True
    args = bridge.modify_position.call_args[0]
    assert round(args[1], 4) == round(1.1000 + 0.0010, 4)


def test_apply_breakeven_does_not_trigger_before_threshold():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.1005, 1.1007)
    pos = buy_position(sl=1.0950)
    moved = tm.apply_breakeven(bridge, pos, trigger_points=100, offset_points=10)
    assert moved is False
    bridge.modify_position.assert_not_called()


def test_apply_partial_tp_closes_fraction_and_moves_sl_to_be():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.1105, 1.1107)
    pos = buy_position(sl=1.0950)
    pos["volume"] = 0.2
    closed_tickets = set()
    result = tm.apply_partial_tp(bridge, pos, trigger_points=100, close_fraction=0.5,
                                  partial_closed_tickets=closed_tickets)
    assert result is True
    bridge.close_position.assert_called_once_with(1, "EURUSD", 0.1, "BUY", slippage_points=20)
    bridge.modify_position.assert_called_once_with(1, 1.1000, 1.1200)
    assert 1 in closed_tickets


def test_apply_partial_tp_does_not_trigger_before_threshold():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.1005, 1.1007)
    pos = buy_position(sl=1.0950)
    result = tm.apply_partial_tp(bridge, pos, trigger_points=100, close_fraction=0.5,
                                  partial_closed_tickets=set())
    assert result is False
    bridge.close_position.assert_not_called()


def test_apply_partial_tp_does_not_refire_same_ticket():
    bridge = MagicMock()
    bridge.get_current_price.return_value = (1.1105, 1.1107)
    pos = buy_position(sl=1.0950)
    closed_tickets = {1}
    result = tm.apply_partial_tp(bridge, pos, trigger_points=100, close_fraction=0.5,
                                  partial_closed_tickets=closed_tickets)
    assert result is False
    bridge.close_position.assert_not_called()
