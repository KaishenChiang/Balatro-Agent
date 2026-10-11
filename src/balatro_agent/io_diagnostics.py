"""Bounded filesystem diagnostics, without paths, messages or tracebacks."""
import errno


STAGES = {'registration', 'intent', 'transport', 'feedback', 'checkpoint', 'delivery'}
ERRNOS = {errno.EACCES, errno.EPERM, errno.ENOSPC, errno.EROFS, errno.EIO,
          errno.EMFILE, errno.ENFILE, errno.EBUSY, errno.ENOENT, errno.EEXIST,
          errno.ENAMETOOLONG, errno.EAGAIN}
WINERRORS = {3, 4, 5, 6, 32, 33, 80, 112, 183, 206, 995}


def io_failure(error, stage):
    """Codes help diagnose a future failure; they never confirm execution."""
    result = {'stage': stage if stage in STAGES else 'unknown',
              'errno': None, 'winerror': None}
    # Registration wraps OS errors. Inspect only bounded numeric codes from
    # explicit causes, never exception text, filenames or arbitrary payloads.
    for _ in range(4):
        if not isinstance(error, OSError):
            break
        code = getattr(error, 'errno', None)
        windows = getattr(error, 'winerror', None)
        if type(code) is int and code in ERRNOS:
            result['errno'] = code
        if type(windows) is int and windows in WINERRORS:
            result['winerror'] = windows
        if result['errno'] is not None or result['winerror'] is not None:
            break
        error = error.__cause__
    return result
