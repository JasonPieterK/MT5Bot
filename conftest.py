"""Puts src/ on the path so `import core.x` / `import analysis.x` / `import
automation.x` / `import strategies.x` resolve the same way for pytest as they
do for app.py, without touching any of those import statements.

It also redirects every file the app writes into a throwaway directory, BEFORE any
test module gets a chance to `import app`.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import automation.app_logger as app_logger
import automation.execution_log as execution_log
import automation.json_logger as json_logger
import core.engine as engine
import core.persistence as persistence

# Redirected at import time, not from a fixture, and never restored.
#
# Two reasons a fixture is too late and too short-lived:
#   * app.py calls _load_persisted_state() at import time. A fixture runs after that, so
#     the suite would read the user's real logs/app_state.json and inherit whatever
#     profile they have applied -- making tests depend on live settings.
#   * API tests start real daemon engine threads that outlive the test that made them,
#     and each tick writes the state file and logs. A function-scoped monkeypatch puts
#     the real paths back underneath a thread that is still running, so its writes land
#     in the user's live files. That once rewrote app_state.json, which holds their
#     DPAPI-encrypted MT5 account passwords.
#
# tests/test_repo_not_written.py asserts none of these point back into the repo.
_SANDBOX = tempfile.mkdtemp(prefix="mt5bot-tests-")

persistence.STATE_PATH = os.path.join(_SANDBOX, "app_state.json")
app_logger.LOG_PATH = os.path.join(_SANDBOX, "app.log")
engine.LOG_PATH = os.path.join(_SANDBOX, "trades.csv")
json_logger.LOG_PATH = os.path.join(_SANDBOX, "events.jsonl")
execution_log.LOG_PATH = os.path.join(_SANDBOX, "execution.csv")
