"""Two app processes on one account both run an engine thread, so every signal is sized
and sent twice. This is the guard that stops a second copy from starting."""
import os

import pytest

import core.single_instance as si


@pytest.fixture
def lock_path(tmp_path, monkeypatch):
    p = str(tmp_path / "app.lock")
    monkeypatch.setattr(si, "LOCK_PATH", p)
    return p


def test_acquires_when_no_lock_exists(lock_path):
    ok, other = si.acquire()
    assert ok is True and other is None
    assert os.path.exists(lock_path)
    si.release()


def test_refuses_when_another_live_process_holds_it(lock_path, monkeypatch):
    """The lock names this interpreter (guaranteed alive), while we pretend to be a
    different process -- so the real liveness check is what does the blocking."""
    real_pid = os.getpid()
    with open(lock_path, "w") as f:
        f.write(str(real_pid))
    monkeypatch.setattr(si.os, "getpid", lambda: real_pid + 1)
    ok, other = si.acquire()
    assert ok is False
    assert other == real_pid


def test_takes_over_a_lock_left_by_a_dead_process(lock_path):
    with open(lock_path, "w") as f:
        f.write("999999999")  # PID that cannot be running
    ok, other = si.acquire()
    assert ok is True
    si.release()


def test_garbage_lock_file_does_not_block_startup(lock_path):
    with open(lock_path, "w") as f:
        f.write("not-a-pid")
    ok, _ = si.acquire()
    assert ok is True
    si.release()


def test_release_removes_the_lock(lock_path):
    si.acquire()
    si.release()
    assert not os.path.exists(lock_path)
