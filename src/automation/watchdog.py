"""MT5 connection watchdog. Detects disconnects and (optionally) posts to a
user-configured webhook URL — generic POST body, works with Telegram bot API,
Slack incoming webhooks, Discord webhooks, or any custom endpoint the user owns."""
import urllib.request
import json


def check_connection(bridge):
    return bridge.connect()


def notify_webhook(webhook_url, message):
    if not webhook_url:
        return False
    try:
        data = json.dumps({"text": message}).encode("utf-8")
        req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False
