"""Launch a disposable Windows test on a private desktop, never the input desktop.

This is UI isolation, not a security sandbox. No SwitchDesktop/SetForegroundWindow,
global window manipulation, registry changes, or Blender-session discovery is used.
Python's subprocess STARTUPINFO does not expose lpDesktop, so use CreateProcessW
with an explicit desktop and an allow-list of inherited log/null handles instead.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
import uuid
from contextlib import ExitStack
from ctypes import wintypes as w
from pathlib import Path
from typing import BinaryIO


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR),
        ("lpTitle", w.LPWSTR), ("dwX", w.DWORD), ("dwY", w.DWORD),
        ("dwXSize", w.DWORD), ("dwYSize", w.DWORD), ("dwXCountChars", w.DWORD),
        ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD), ("dwFlags", w.DWORD),
        ("wShowWindow", w.WORD), ("cbReserved2", w.WORD), ("lpReserved2", w.LPBYTE),
        ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE),
    ]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", StartupInfo), ("lpAttributeList", w.LPVOID)]


class ProcessInformation(ctypes.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


class BasicJobLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
        ("flags", w.DWORD), ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t), ("active_processes", w.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD),
    ]


class ExtendedJobLimits(ctypes.Structure):
    _fields_ = [
        ("basic", BasicJobLimits), ("io_counters", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


def _bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = arguments
    return function


class WindowsTestAPI:
    """Small, explicitly typed Win32 boundary; loaded only on Windows."""

    def __init__(self):
        user = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.create_desktop = _bind(user, "CreateDesktopW", w.HANDLE,
                                    w.LPCWSTR, w.LPCWSTR, w.LPVOID, w.DWORD, w.DWORD, w.LPVOID)
        self.close_desktop = _bind(user, "CloseDesktop", w.BOOL, w.HANDLE)
        self.create_process = _bind(kernel, "CreateProcessW", w.BOOL,
                                   w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL, w.DWORD,
                                   w.LPVOID, w.LPCWSTR, ctypes.POINTER(StartupInfoEx),
                                   ctypes.POINTER(ProcessInformation))
        self.init_attributes = _bind(kernel, "InitializeProcThreadAttributeList", w.BOOL,
                                    w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t))
        self.update_attributes = _bind(kernel, "UpdateProcThreadAttribute", w.BOOL,
                                      w.LPVOID, w.DWORD, ctypes.c_size_t, w.LPVOID,
                                      ctypes.c_size_t, w.LPVOID, w.LPVOID)
        self.delete_attributes = _bind(kernel, "DeleteProcThreadAttributeList", None, w.LPVOID)
        self.close_handle = _bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)
        self.create_job = _bind(kernel, "CreateJobObjectW", w.HANDLE, w.LPVOID, w.LPCWSTR)
        self.set_job = _bind(kernel, "SetInformationJobObject", w.BOOL,
                             w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD)
        self.assign_job = _bind(kernel, "AssignProcessToJobObject", w.BOOL, w.HANDLE, w.HANDLE)
        self.resume = _bind(kernel, "ResumeThread", w.DWORD, w.HANDLE)
        self.wait = _bind(kernel, "WaitForSingleObject", w.DWORD, w.HANDLE, w.DWORD)
        self.exit_code = _bind(kernel, "GetExitCodeProcess", w.BOOL,
                               w.HANDLE, ctypes.POINTER(w.DWORD))
        self.terminate = _bind(kernel, "TerminateProcess", w.BOOL, w.HANDLE, w.UINT)

    @staticmethod
    def require(success):
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())


def run_isolated(
    command: list[str], *, cwd: Path, env: dict[str, str], stdout: BinaryIO, timeout: int
) -> subprocess.CompletedProcess:
    """Fail closed if isolation fails. Kill only this test's job on exit/cancel.

    A suspended launch is assigned to a kill-on-close job before any Blender code
    runs. The private desktop handle stays alive until the child is reaped. Even
    if Blender ignores SW_HIDE and explicitly shows a window, it is not on the
    user's input desktop. No visible fallback is permitted.
    """
    if os.name != "nt":
        raise OSError("Private-desktop test execution requires Windows")
    import msvcrt

    api = WindowsTestAPI()
    desktop_name = "CodexBlenderTests_" + uuid.uuid4().hex
    with ExitStack() as cleanup:
        # No DESKTOP_SWITCHDESKTOP right and no inheritable desktop handle.
        desktop = api.create_desktop(desktop_name, None, None, 0, 0x00CF, None)
        api.require(desktop)
        cleanup.callback(api.close_desktop, desktop)
        job = api.create_job(None, None)
        api.require(job)
        cleanup.callback(api.close_handle, job)
        limits = ExtendedJobLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        api.require(api.set_job(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))

        null = cleanup.enter_context(open(os.devnull, "rb"))
        # Duplicate, don't change inheritance on the caller's handles. Only these
        # two go into PROC_THREAD_ATTRIBUTE_HANDLE_LIST (not other app handles).
        descriptors = []
        for source in (null, stdout):
            descriptor = os.dup(source.fileno())
            cleanup.callback(os.close, descriptor)
            os.set_handle_inheritable(msvcrt.get_osfhandle(descriptor), True)
            descriptors.append(descriptor)
        handles = (w.HANDLE * 2)(*(msvcrt.get_osfhandle(fd) for fd in descriptors))
        size = ctypes.c_size_t()
        api.init_attributes(None, 1, 0, ctypes.byref(size))
        if not size.value:
            raise OSError("Could not size isolated test handle list")
        attributes = ctypes.create_string_buffer(size.value)
        api.require(api.init_attributes(attributes, 1, 0, ctypes.byref(size)))
        cleanup.callback(api.delete_attributes, attributes)
        api.require(api.update_attributes(attributes, 0, 0x20002, handles,
                                          ctypes.sizeof(handles), None, None))
        startup = StartupInfoEx()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.lpDesktop = desktop_name
        startup.StartupInfo.dwFlags = 0x101 | 0x80  # USESTDHANDLES | USESHOWWINDOW | FORCEOFFFEEDBACK
        startup.StartupInfo.wShowWindow = 0
        startup.StartupInfo.hStdInput = handles[0]
        startup.StartupInfo.hStdOutput = startup.StartupInfo.hStdError = handles[1]
        startup.lpAttributeList = ctypes.cast(attributes, w.LPVOID)
        environment = ctypes.create_unicode_buffer(
            "\0".join(f"{key}={value}" for key, value in sorted(env.items(), key=lambda x: x[0].upper())) + "\0"
        )
        process = ProcessInformation()
        # CREATE_NO_WINDOW | UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT | SUSPENDED
        flags = 0x08000000 | 0x400 | 0x80000 | 0x4
        api.require(api.create_process(
            command[0], ctypes.create_unicode_buffer(subprocess.list2cmdline(command)),
            None, None, True, flags, environment, str(cwd), ctypes.byref(startup),
            ctypes.byref(process),
        ))
        cleanup.callback(api.close_handle, process.thread)
        cleanup.callback(api.close_handle, process.process)
        try:
            api.require(api.assign_job(job, process.process))
            if api.resume(process.thread) == 0xFFFFFFFF:
                raise OSError("Could not resume isolated test process")
            deadline = time.monotonic() + timeout
            while True:
                state = api.wait(process.process, 100)
                if state == 0:  # WAIT_OBJECT_0
                    code = w.DWORD()
                    api.require(api.exit_code(process.process, ctypes.byref(code)))
                    return subprocess.CompletedProcess(command, code.value)
                if state != 258:  # WAIT_TIMEOUT
                    raise OSError("Could not wait for isolated test process")
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
        finally:
            # Covers timeout, cancellation and failure before job assignment. No
            # name-based kill, no user-session process enumeration or window edits.
            if api.wait(process.process, 0) != 0:
                api.require(api.terminate(process.process, 1))
                if api.wait(process.process, 5000) != 0:
                    raise OSError("Isolated test process could not be reaped")
