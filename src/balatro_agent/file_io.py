"""Bounded retries before file writes or for the same atomic replacement.

Never retry stream writes, flushes, fsync, lock acquisition or game requests.
"""
import errno
import os
from pathlib import Path
import time


WINDOWS = os.name == 'nt'
DELAYS = (0, 0.02, 0.05, 0.1)


def _transient(error, *, prepared_replace=False):
    if not WINDOWS:
        return False
    windows = getattr(error, 'winerror', None)
    if type(windows) is int:
        # Windows may report a temporarily open destination as ACCESS_DENIED
        # during rename. Only the same prepared replacement gets that retry;
        # persistent ACL denials still fail within the fixed budget.
        return windows in (32, 33) or prepared_replace and windows == 5
    # CRT file opens can omit winerror and report only EACCES. A persistent
    # denial still fails after this short, fixed budget; no permission changes.
    return isinstance(error, PermissionError) and error.errno == errno.EACCES


def _retry(operation, *, can_retry=lambda: True, prepared_replace=False):
    for attempt, delay in enumerate(DELAYS):
        if delay:
            time.sleep(delay)
        try:
            return operation()
        except OSError as error:
            if attempt == len(DELAYS) - 1 or not _transient(error, prepared_replace=prepared_replace) or not can_retry():
                raise


def open_file(path, mode, **options):
    return _retry(lambda: path.open(mode, **options))


def replace_file(source, target):
    # If the prepared source disappeared, preserve uncertainty rather than
    # recreate it or assume that an earlier failed call did not take effect.
    return _retry(lambda: os.replace(source, target), can_retry=lambda: Path(source).is_file(), prepared_replace=True)
