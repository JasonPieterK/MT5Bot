from unittest.mock import MagicMock, patch
import automation.watchdog as watchdog


def test_check_connection_true_when_connected():
    bridge = MagicMock()
    bridge.connect.return_value = True
    assert watchdog.check_connection(bridge) is True


def test_check_connection_false_when_disconnected():
    bridge = MagicMock()
    bridge.connect.return_value = False
    assert watchdog.check_connection(bridge) is False


def test_notify_webhook_returns_false_without_url():
    assert watchdog.notify_webhook("", "msg") is False


def test_notify_webhook_posts_and_returns_true():
    with patch("automation.watchdog.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda s, *a: None
        result = watchdog.notify_webhook("https://example.com/webhook", "MT5 disconnected")
    assert result is True
    assert mock_urlopen.called


def test_notify_webhook_returns_false_on_failure():
    with patch("automation.watchdog.urllib.request.urlopen", side_effect=Exception("boom")):
        result = watchdog.notify_webhook("https://example.com/webhook", "msg")
    assert result is False
