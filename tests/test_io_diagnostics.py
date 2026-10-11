"""Only known OS codes can leave the filesystem error boundary."""
import errno
import json

import pytest

from balatro_agent.io_diagnostics import io_failure


def test_wrapped_windows_error_exports_codes_without_private_text():
    cause = OSError(errno.EACCES, 'SECRET_MESSAGE', 'SECRET_FILENAME')
    cause.winerror = 32
    error = OSError('SECRET_WRAPPER')
    error.__cause__ = cause
    result = io_failure(error, 'checkpoint')
    assert result == {'stage': 'checkpoint', 'errno': errno.EACCES, 'winerror': 32}
    assert 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('code', [None, True, 'SECRET_CODE', 987654321])
def test_unknown_or_non_numeric_codes_remain_unknown(code):
    error = OSError('SECRET_MESSAGE')
    error.errno = code
    error.winerror = code
    assert io_failure(error, 'delivery') == {'stage': 'delivery', 'errno': None, 'winerror': None}


def test_cycle_and_unrecognized_stage_are_bounded_and_filtered():
    error = OSError('SECRET_MESSAGE')
    error.__cause__ = error
    assert io_failure(error, 'SECRET_STAGE') == {'stage': 'unknown', 'errno': None, 'winerror': None}


def test_lua_test_runtime_reads_a_unicode_filename(tmp_path):
    """A public temporary script, without game code or game state."""
    from lupa.lua51 import LuaRuntime
    path = tmp_path / '公开.lua'
    path.write_text('return 43', encoding='utf-8')
    lua = LuaRuntime(unpack_returned_tuples=True)
    loaded = lua.eval('loadfile')(path.as_posix())
    assert callable(loaded) and loaded() == 43
