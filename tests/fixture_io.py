"""Explicit fixture writes tolerate pre-open Windows scanner contention.

This does not monkeypatch pathlib or retry production stream writes.
"""
from balatro_agent.file_io import open_file
from balatro_agent import file_io


def write_text(path, data, encoding='utf-8'):
    with open_file(path, 'w', encoding=encoding) as stream:
        return stream.write(data)


def write_bytes(path, data):
    with open_file(path, 'wb') as stream:
        return stream.write(data)


def remove_fixture(path, root):
    """Only a named synthetic file below its explicit temporary root."""
    assert path.resolve().is_relative_to(root.resolve())
    return file_io._retry(lambda: path.unlink())
