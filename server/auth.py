"""Serialized, atomic credential configuration updates; never persist plaintext."""
import contextlib
import json
import os
import secrets
import tempfile
import threading
from pathlib import Path

_locks = {}
_mutex = threading.Lock()


@contextlib.contextmanager
def config_lock(home):
    home = Path(home)
    key = str(home.resolve())
    with _mutex:
        lock = _locks.setdefault(key, threading.RLock())
    with lock:
        with (home / 'auth.lock').open('a+b') as file:
            if os.name == 'nt':
                import msvcrt
                file.seek(0); file.write(b'\0'); file.flush(); file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    file.seek(0); msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(file, fcntl.LOCK_UN)


def save_credentials(home, config, password):
    """Caller holds config_lock. The atomic replace is the sole commit point.

    A new session epoch invalidates old sessions even if cleanup or a crash occurs
    after the replace. Initial plaintext removal must succeed BEFORE commit.
    """
    from core import password_hash
    home = Path(home)
    updated = dict(config)
    updated['admin_salt'] = secrets.token_hex(16)
    updated['admin_hash'] = password_hash(password, updated['admin_salt'])
    updated['admin_session_epoch'] = secrets.token_hex(32)
    fd, name = tempfile.mkstemp(prefix='.config-', suffix='.tmp', dir=home)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(updated, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        (home / 'admin-password.txt').unlink(missing_ok=True)
        os.replace(name, home / 'config.json')
        config.update(updated)
        # On POSIX persist the directory entry too. Do not report a false failure
        # after the replace commit point on filesystems without directory fsync.
        if os.name != 'nt':
            try:
                directory = os.open(home, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(directory)
                finally: os.close(directory)
            except OSError:
                pass
    finally:
        Path(name).unlink(missing_ok=True)
