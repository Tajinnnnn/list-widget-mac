import fcntl
import os

from config import LOCK_PATH

_lock_fd = None


def already_running():
    global _lock_fd
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
