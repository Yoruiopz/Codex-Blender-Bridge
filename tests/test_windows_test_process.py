from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import windows_test_process as launch


class FakeAPI:
    def __init__(self, failure=None, waiting=False):
        self.failure = failure
        self.waiting = waiting
        self.events = []

    def require(self, success):
        if not success:
            raise OSError("injected isolation failure")

    def create_desktop(self, name, device, mode, flags, rights, security):
        self.events.append("desktop")
        assert name.startswith("CodexBlenderTests_") and "\\" not in name
        assert rights & 0x100 == 0  # no desktop switching right
        assert security is None  # desktop handle not inherited
        self.desktop_name = name
        return 0 if self.failure == "desktop" else 10

    def close_desktop(self, handle):
        self.events.append("close_desktop")
        assert handle == 10
        return True

    def create_job(self, *_args):
        self.events.append("job")
        return 0 if self.failure == "job" else 20

    def set_job(self, job, kind, limits, size):
        assert job == 20 and kind == 9 and limits._obj.basic.flags == 0x2000
        return self.failure != "limits"

    def close_handle(self, handle):
        self.events.append(f"close_{handle}")
        return True

    def init_attributes(self, attributes, count, flags, size):
        size._obj.value = 64
        return attributes is not None and self.failure != "attributes"

    def update_attributes(self, attributes, flags, key, handles, size, *_args):
        assert key == 0x20002 and len(handles) == 2
        return self.failure != "handles"

    def delete_attributes(self, attributes):
        self.events.append("delete_attributes")

    def create_process(self, executable, command, pa, ta, inherit, flags, env, cwd, startup, pi):
        self.events.append("create")
        assert executable == "blender.exe" and command.value.startswith("blender.exe ")
        assert inherit and flags & 0x80000 and flags & 0x8000000 and flags & 4
        assert "TEST_VALUE=space with \u00fc" in env[:]
        assert startup._obj.StartupInfo.lpDesktop == self.desktop_name
        assert startup._obj.StartupInfo.hStdOutput == startup._obj.StartupInfo.hStdError
        assert startup._obj.lpAttributeList
        pi._obj.process, pi._obj.thread = 30, 40
        return self.failure != "create"

    def assign_job(self, job, process):
        self.events.append("assign")
        return self.failure != "assign"

    def resume(self, thread):
        self.events.append("resume")
        return 0xFFFFFFFF if self.failure == "resume" else 1

    def wait(self, process, timeout):
        self.events.append(f"wait_{timeout}")
        if self.failure == "interrupt" and timeout == 100:
            raise KeyboardInterrupt
        return 258 if self.waiting or self.failure in {"assign", "resume", "interrupt"} else 0

    def exit_code(self, process, code):
        code._obj.value = 7
        return True

    def terminate(self, process, code):
        self.events.append("terminate")
        self.waiting = False
        self.failure = None
        return True


@pytest.fixture
def fake_environment(monkeypatch):
    monkeypatch.setattr(launch, "os", SimpleNamespace(
        name="nt", devnull=os.devnull, dup=os.dup, close=os.close,
        set_handle_inheritable=lambda *_args: None,
    ))
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda fd: fd))


def invoke(api, monkeypatch, tmp_path):
    monkeypatch.setattr(launch, "WindowsTestAPI", lambda: api)
    with (tmp_path / "child.log").open("wb") as stream:
        return launch.run_isolated(["blender.exe", "--factory-startup"], cwd=tmp_path,
                                   env={"TEST_VALUE": "space with \u00fc"}, stdout=stream, timeout=1)


def test_desktop_process_is_suspended_until_placed_in_scoped_job(fake_environment, monkeypatch, tmp_path):
    api = FakeAPI()
    result = invoke(api, monkeypatch, tmp_path)
    assert result.returncode == 7
    assert api.events.index("create") < api.events.index("assign") < api.events.index("resume")
    assert api.events[-2:] == ["close_20", "close_desktop"]
    assert "close_30" in api.events and "close_40" in api.events
    assert "terminate" not in api.events


@pytest.mark.parametrize("failure", ["desktop", "job", "limits", "attributes", "handles", "create", "assign", "resume"])
def test_isolation_failure_cleans_resources_without_running_on_default_desktop(
    fake_environment, monkeypatch, tmp_path, failure
):
    api = FakeAPI(failure)
    with pytest.raises(OSError):
        invoke(api, monkeypatch, tmp_path)
    if failure != "desktop":
        assert api.events[-1] == "close_desktop"
    if failure in {"assign", "resume"}:
        assert "terminate" in api.events and "wait_5000" in api.events
    if failure == "assign":
        assert "resume" not in api.events


@pytest.mark.parametrize("interrupted", [False, True])
def test_timeout_and_interrupt_kill_only_owned_process_and_close_job(
    fake_environment, monkeypatch, tmp_path, interrupted
):
    api = FakeAPI("interrupt" if interrupted else None, waiting=True)
    ticks = iter([0, 2])
    monkeypatch.setattr(launch.time, "monotonic", lambda: next(ticks))
    with pytest.raises(KeyboardInterrupt if interrupted else subprocess.TimeoutExpired):
        invoke(api, monkeypatch, tmp_path)
    assert "terminate" in api.events and "wait_5000" in api.events
    assert api.events[-2:] == ["close_20", "close_desktop"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native desktop isolation")
def test_native_child_really_creates_window_on_non_input_desktop(tmp_path):
    # Explicitly show a window: SW_HIDE alone is not sufficient protection. This
    # probes desktop identity without reading or manipulating the user's windows.
    script = r'''
import ctypes, json
from ctypes import wintypes as w
u = ctypes.WinDLL("user32", use_last_error=True)
k = ctypes.WinDLL("kernel32", use_last_error=True)
u.GetThreadDesktop.argtypes, u.GetThreadDesktop.restype = [w.DWORD], w.HANDLE
u.OpenInputDesktop.argtypes, u.OpenInputDesktop.restype = [w.DWORD,w.BOOL,w.DWORD], w.HANDLE
u.GetUserObjectInformationW.argtypes = [w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD)]
def name(h):
    assert h
    b, n = ctypes.create_unicode_buffer(256), w.DWORD()
    assert u.GetUserObjectInformationW(h, 2, b, ctypes.sizeof(b), ctypes.byref(n))
    return b.value
desktop = name(u.GetThreadDesktop(k.GetCurrentThreadId()))
input_handle = u.OpenInputDesktop(0, False, 1)
input_name = name(input_handle)
u.CloseDesktop.argtypes = [w.HANDLE]
assert u.CloseDesktop(input_handle)
u.CreateWindowExW.argtypes = [w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HANDLE,w.HANDLE,w.HINSTANCE,w.LPVOID]
u.CreateWindowExW.restype = w.HWND
hwnd = u.CreateWindowExW(0,"STATIC","Isolated bridge test",0x00CF0000,0,0,100,100,None,None,None,None)
assert hwnd
u.ShowWindow.argtypes = [w.HWND,ctypes.c_int]
u.ShowWindow(hwnd, 5)
u.IsWindowVisible.argtypes = [w.HWND]
assert u.IsWindowVisible(hwnd)
u.DestroyWindow.argtypes = [w.HWND]
assert u.DestroyWindow(hwnd)
print(json.dumps({"desktop": desktop, "input": input_name, "window_shown_on_private_desktop": True}))
'''
    log = tmp_path / "native.log"
    with log.open("wb") as stream:
        result = launch.run_isolated([sys.executable, "-c", script], cwd=tmp_path,
                                     env=dict(os.environ), stdout=stream, timeout=5)
    assert result.returncode == 0, log.read_text(errors="replace")
    evidence = json.loads(log.read_text())
    assert evidence["desktop"].startswith("CodexBlenderTests_")
    assert evidence["desktop"] != evidence["input"]
    assert evidence["window_shown_on_private_desktop"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native job cleanup")
def test_native_timeout_reaps_test_and_its_descendant(tmp_path):
    import ctypes
    from ctypes import wintypes as w

    log = tmp_path / "timeout.log"
    script = (
        "import os,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
        "creationflags=subprocess.CREATE_NO_WINDOW); "
        "print(os.getpid(),child.pid,flush=True); time.sleep(60)"
    )
    with log.open("wb") as stream, pytest.raises(subprocess.TimeoutExpired):
        launch.run_isolated([sys.executable, "-c", script], cwd=tmp_path,
                            env=dict(os.environ), stdout=stream, timeout=1)
    pids = [int(pid) for pid in log.read_text().split()]
    assert len(pids) == 2
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    for pid in pids:
        handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE, read-only
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 1000) == 0
            finally:
                assert kernel.CloseHandle(handle)
        else:
            assert ctypes.get_last_error() == 87  # already gone (ERROR_INVALID_PARAMETER)
