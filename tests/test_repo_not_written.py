"""A test run must never touch the user's real logs/ directory.

The suite once rewrote logs/app_state.json -- their live settings and the file holding
DPAPI-encrypted MT5 account passwords -- because daemon engine threads outlived their
test and kept calling _save_persisted_state() against a cwd-relative path.
"""
import os

import automation.app_logger as app_logger
import automation.execution_log as execution_log
import automation.json_logger as json_logger
import core.engine as engine
import core.persistence as persistence

REPO_LOGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


def _under_repo_logs(path):
    return os.path.abspath(path).startswith(os.path.abspath(REPO_LOGS) + os.sep)


def test_state_file_is_not_the_repos_own():
    assert not _under_repo_logs(persistence.STATE_PATH), (
        f"persistence.STATE_PATH points at {persistence.STATE_PATH} -- a suite run would "
        f"overwrite the user's real settings and saved account passwords.")


def test_app_log_is_not_the_repos_own():
    assert not _under_repo_logs(app_logger.LOG_PATH), (
        f"app_logger.LOG_PATH points at {app_logger.LOG_PATH} -- test output would be "
        f"written into the user's real trading log.")


def test_writing_through_both_modules_lands_outside_the_repo():
    """Not just the configured paths -- prove an actual write goes elsewhere."""
    app_logger.info("isolation check")
    persistence.save_all({"state": {"isolation": "check"}})
    assert os.path.exists(persistence.STATE_PATH)
    assert not _under_repo_logs(persistence.STATE_PATH)
    assert not _under_repo_logs(app_logger.LOG_PATH)


def test_no_module_writes_records_into_the_repo():
    """Trade CSV, JSON events and the execution log are what analytics and the ML filter
    read back -- fixture trades appended to the real ones would corrupt both."""
    for name, path in (("engine trades", engine.LOG_PATH),
                        ("json events", json_logger.LOG_PATH),
                        ("execution log", execution_log.LOG_PATH)):
        assert not _under_repo_logs(path), f"{name} points at the repo's logs/: {path}"


def test_a_logged_trade_does_not_reach_the_repo():
    engine.log_trade(["2026-01-01T00:00:00", "EURUSD#", "trend", "BUY", 0.1, 1.0, 1.1, 10009])
    assert os.path.exists(engine.LOG_PATH)
    assert not _under_repo_logs(engine.LOG_PATH)
