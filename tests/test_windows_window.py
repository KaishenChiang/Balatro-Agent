"""Portable window ownership/filtering checks; no native OS input."""
import ctypes
from ctypes import wintypes as w
from types import SimpleNamespace

import pytest

from balatro_agent.windows_game import GameProcessError, ProcessEntry, ProcessIdentity, WindowsGame


def backend(rows, enum_ok=True):
    process=ProcessIdentity(7116,1234)
    b=WindowsGame(None)
    b.find=lambda:process
    b.enum_callback=lambda f:f
    def pid(hwnd,out):
        ctypes.cast(out,ctypes.POINTER(w.DWORD)).contents.value=rows[hwnd]['pid']
        return 1
    def kind(hwnd,out,size):
        value=rows[hwnd]['class']
        out.value=value
        return len(value)
    def enum(callback,_):
        for hwnd in rows:callback(hwnd,0)
        return enum_ok
    b.u=SimpleNamespace(GetWindowThreadProcessId=pid,GetClassNameW=kind,
                        IsWindowVisible=lambda h:rows[h].get('visible',True),EnumWindows=enum)
    return b,process


def test_game_window_is_selected_with_visible_lovely_console():
    b,p=backend({10:{'pid':7116,'class':'ConsoleWindowClass'},20:{'pid':7116,'class':'SDL_app'}})
    assert b._window(p)==20


def test_other_process_or_hidden_render_window_is_not_selected():
    b,p=backend({10:{'pid':123,'class':'SDL_app'},20:{'pid':7116,'class':'SDL_app'},
                 30:{'pid':7116,'class':'SDL_app','visible':False}})
    assert b._window(p)==20


@pytest.mark.parametrize('rows,enum_ok',[
    ({10:{'pid':7116,'class':'ConsoleWindowClass'}},True),
    ({10:{'pid':7116,'class':'unknown'}},True),
    ({10:{'pid':7116,'class':'SDL_app'},20:{'pid':7116,'class':'SDL_app'}},True),
    ({10:{'pid':7116,'class':'SDL_app'}},False),
])
def test_window_ambiguity_or_enumeration_failure_refuses_close(rows,enum_ok):
    b,p=backend(rows,enum_ok)
    with pytest.raises(GameProcessError,match='game_window_unverified'):
        b._window(p)


def process_backend(monkeypatch, rows, *, end_error=18, snapshot=33):
    """Simulate process enumeration without querying the real computer."""
    last_error = {'code': 0}
    monkeypatch.setattr(ctypes, 'set_last_error', lambda value: last_error.update(code=value), raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: last_error['code'], raising=False)
    remaining = iter(rows)
    closed = []

    def step(handle, out):
        row = next(remaining, None)
        if row is None:
            last_error['code'] = end_error
            return False
        entry = ctypes.cast(out, ctypes.POINTER(ProcessEntry)).contents
        entry.exe, entry.pid = row
        return True

    b = WindowsGame(None)
    b._init = lambda: None
    b._identity = lambda pid: ProcessIdentity(pid, 1234)
    b.k = SimpleNamespace(CreateToolhelp32Snapshot=lambda *_: snapshot,
                          Process32FirstW=step, Process32NextW=step,
                          CloseHandle=closed.append)
    return b, closed


@pytest.mark.parametrize('rows', [[], [('other.exe', 1)], [('Balatro.exe', 7116)]])
def test_only_normal_enumeration_end_can_report_process_absence(monkeypatch, rows):
    b, closed = process_backend(monkeypatch, rows)
    assert b.find() == (ProcessIdentity(7116, 1234) if rows and rows[0][0] == 'Balatro.exe' else None)
    assert closed == [33]


@pytest.mark.parametrize('rows', [[], [('other.exe', 1)], [('Balatro.exe', 7116)]])
@pytest.mark.parametrize('error', [0, 5, 6])
def test_enumeration_failure_never_means_absent_or_verified(monkeypatch, rows, error):
    b, closed = process_backend(monkeypatch, rows, end_error=error)
    with pytest.raises(GameProcessError, match='process_unverified'):
        b.find()
    assert closed == [33]


@pytest.mark.parametrize('snapshot', [None, 0, ctypes.c_void_p(-1).value])
def test_invalid_process_snapshot_is_not_treated_as_absence(monkeypatch, snapshot):
    b, closed = process_backend(monkeypatch, [], snapshot=snapshot)
    with pytest.raises(GameProcessError, match='process_unverified'):
        b.find()
    assert closed == []
