"""Refuse to start a second copy of the bot against the same account.

Two instances each run their own engine thread, so one signal becomes two orders at full
size -- the account is silently traded at double the configured risk. Windows will happily
let a second process listen on the same loopback port, so the port is not the guard.
"""
import os

LOCK_PATH = os.path.join("logs", "app.lock")


def _pid_alive(pid):
    """True if a process with this id exists. On Windows os.kill(pid, 0) raises for a dead
    pid and returns cleanly for a live one."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError, PermissionError) as exc:
        # PermissionError means the process exists but belongs to someone else -- still alive.
        return isinstance(exc, PermissionError)
    return True


def acquire():
    """(True, None) if we now hold the lock, (False, other_pid) if another copy is running.
    A lock left behind by a crashed process is taken over rather than blocking startup."""
    directory = os.path.dirname(LOCK_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH) as f:
                other = int(f.read().strip())
        except (ValueError, OSError):
            other = None  # unreadable/garbage lock is not evidence of a live process
        if other is not None and other != os.getpid() and _pid_alive(other):
            return False, other
    with open(LOCK_PATH, "w") as f:
        f.write(str(os.getpid()))
    return True, None


def release():
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass
