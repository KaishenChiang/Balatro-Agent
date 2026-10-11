"""File retries cannot repeat a stream write, game request or missing source."""
import errno
from types import SimpleNamespace

import pytest

from balatro_agent import file_io


def windows_error(code=None):
    error = PermissionError(errno.EACCES, 'Synthetic file conflict')
    if code is not None:
        error.winerror = code
    return error


@pytest.fixture
def delays(monkeypatch):
    values = []
    monkeypatch.setattr(file_io, 'WINDOWS', True)
    monkeypatch.setattr(file_io.time, 'sleep', values.append)
    return values


@pytest.mark.parametrize('code', [None, 32, 33])
def test_open_conflict_is_retried_only_before_a_stream_is_returned(delays, code):
    attempts = []
    stream = object()
    def open_path(*args, **kwargs):
        attempts.append((args, kwargs))
        if len(attempts) == 1: raise windows_error(code)
        return stream
    assert file_io.open_file(SimpleNamespace(open=open_path), 'a', encoding='utf-8') is stream
    assert len(attempts) == 2 and delays == [0.02]


def test_persistent_crt_denial_has_a_fixed_budget(delays):
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(1)
        raise windows_error()
    with pytest.raises(PermissionError):
        file_io.open_file(SimpleNamespace(open=fail), 'a')
    assert len(attempts) == 4 and delays == [0.02, 0.05, 0.1]


@pytest.mark.parametrize('error', [windows_error(5), OSError(errno.ENOSPC, 'disk full')])
def test_known_permanent_errors_are_not_retried(delays, error):
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(1)
        raise error
    with pytest.raises(OSError):
        file_io.open_file(SimpleNamespace(open=fail), 'a')
    assert attempts == [1] and delays == []


def test_stream_failure_is_not_reopened_or_written_twice(delays):
    opened, writes = [], []
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def write(self, value):
            writes.append(value)
            raise windows_error(32)
    def open_path(*args, **kwargs):
        opened.append(1)
        return Stream()
    with pytest.raises(PermissionError):
        with file_io.open_file(SimpleNamespace(open=open_path), 'a') as stream:
            stream.write('one row')
    assert opened == [1] and writes == ['one row'] and delays == []


@pytest.mark.parametrize('code', [5, 32, 33])
def test_replace_retries_the_same_prepared_file_without_recreating_it(delays, monkeypatch, tmp_path, code):
    source, target = tmp_path / 'ready.tmp', tmp_path / 'checkpoint.json'
    source.write_text('prepared')
    target.write_text('old')
    original, calls = file_io.os.replace, []
    def replace(src, dst):
        calls.append((src, dst))
        if len(calls) == 1: raise windows_error(code)
        return original(src, dst)
    monkeypatch.setattr(file_io.os, 'replace', replace)
    file_io.replace_file(source, target)
    assert calls == [(source, target)] * 2 and delays == [0.02]
    assert target.read_text() == 'prepared' and not source.exists()


@pytest.mark.parametrize('code', [5, 32])
def test_lost_prepared_source_never_triggers_another_replacement(delays, monkeypatch, tmp_path, code):
    source, target = tmp_path / 'ready.tmp', tmp_path / 'checkpoint.json'
    source.write_text('prepared')
    calls = []
    def replace(src, dst):
        calls.append((src, dst))
        source.unlink()
        raise windows_error(code)
    monkeypatch.setattr(file_io.os, 'replace', replace)
    with pytest.raises(PermissionError):
        file_io.replace_file(source, target)
    assert len(calls) == 1 and delays == [] and not target.exists()


def test_persistent_replace_access_denial_preserves_both_files(delays, monkeypatch, tmp_path):
    source, target = tmp_path / 'ready.tmp', tmp_path / 'checkpoint.json'
    source.write_bytes(b'prepared'); target.write_bytes(b'old')
    calls = []
    def replace(src, dst):
        calls.append((src, dst))
        raise windows_error(5)
    monkeypatch.setattr(file_io.os, 'replace', replace)
    with pytest.raises(PermissionError):
        file_io.replace_file(source, target)
    assert calls == [(source, target)] * 4 and delays == [0.02, 0.05, 0.1]
    assert source.read_bytes() == b'prepared' and target.read_bytes() == b'old'
