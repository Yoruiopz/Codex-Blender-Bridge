from __future__ import annotations

import ctypes
import importlib
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest


@pytest.fixture
def windows_files(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}._windows_backup_files")
    original = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0, st_ino=9, st_nlink=1,
                               st_dev=1, st_size=23, st_mtime_ns=37, st_ctime_ns=41)
    path = Mock(spec=Path)
    path.lstat.return_value = original
    crt = SimpleNamespace(open_osfhandle=Mock(return_value=42))
    monkeypatch.setitem(sys.modules, "msvcrt", crt)
    os_api = SimpleNamespace(fstat=Mock(return_value=SimpleNamespace(**{**vars(original), "st_ctime_ns": 999})),
                             close=Mock(), O_RDONLY=0, O_BINARY=0x8000, O_NOINHERIT=0x80)
    monkeypatch.setattr(module, "os", os_api)
    monkeypatch.setattr(module, "_winerror", lambda: PermissionError("Win32 failure"))
    attributes = {17: 0, 28: 0x10}
    identities = {17: (91, b"f" * 16), 28: (95, b"d" * 16)}

    def file_information(handle, query, buffer, size):
        if query == 9:
            assert size == 8
            buffer[0] = attributes[handle]
        else:
            assert query == 18 and size == 24
            info = ctypes.cast(buffer, ctypes.POINTER(module._FileIDInfo)).contents
            info.volume, identifier = identities[handle]
            info.identifier[:] = identifier
        return True

    kernel = SimpleNamespace(CreateFileW=Mock(return_value=17), GetFileType=Mock(return_value=1),
                             GetFileInformationByHandleEx=Mock(side_effect=file_information),
                             FlushFileBuffers=Mock(return_value=True), CloseHandle=Mock(return_value=True))
    monkeypatch.setattr(module, "_kernel32", lambda: kernel)
    return SimpleNamespace(module=module, path=path, crt=crt, os=os_api, kernel=kernel, attributes=attributes,
                           identities=identities)


def test_leaf_open_is_no_follow_binary_and_closes_via_crt(windows_files):
    fixture = windows_files
    with fixture.module.open_leaf(fixture.path, links=1) as leaf:
        assert leaf.fd == 42 and leaf.signature == (1, 9, 23, 37) and leaf.file_id == (91, b"f" * 16)
        fixture.os.close.assert_not_called()
    fixture.kernel.CreateFileW.assert_called_once_with(str(fixture.path), 0x80000000, 1, None, 3, 0x00200000, None)
    fixture.crt.open_osfhandle.assert_called_once_with(17, 0x8080)
    fixture.os.close.assert_called_once_with(42)
    fixture.kernel.CloseHandle.assert_not_called()


def test_win32_failure_has_no_unverified_or_text_mode_fallback(windows_files):
    fixture = windows_files
    fixture.kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value
    with pytest.raises(PermissionError), fixture.module.open_leaf(fixture.path, links=1):
        pytest.fail("Failed native open exposed a descriptor")
    fixture.crt.open_osfhandle.assert_not_called()
    fixture.kernel.CloseHandle.assert_not_called()


@pytest.mark.parametrize("bad_shape", ["reparse", "directory", "wrong_link_count"])
def test_unsafe_named_leaf_refuses_before_createfile(windows_files, bad_shape):
    fixture = windows_files
    path_info = fixture.path.lstat.return_value
    if bad_shape == "reparse":
        path_info.st_file_attributes = 0x400
    elif bad_shape == "directory":
        path_info.st_mode = stat.S_IFDIR
    else:
        path_info.st_nlink = 2
    with pytest.raises(OSError, match="ordinary file"), fixture.module.open_leaf(fixture.path, links=1):
        pytest.fail("Rejected leaf was opened")
    fixture.kernel.CreateFileW.assert_not_called()


@pytest.mark.parametrize("bad_handle", ["reparse", "non_disk", "zero_identity", "crt_failure"])
def test_unaccepted_handle_is_closed_without_exposing_descriptor(windows_files, bad_handle):
    fixture = windows_files
    if bad_handle == "reparse":
        fixture.attributes[17] = 0x400
    elif bad_handle == "non_disk":
        fixture.kernel.GetFileType.return_value = 2
    elif bad_handle == "zero_identity":
        fixture.identities[17] = (91, bytes(16))
    else:
        fixture.crt.open_osfhandle.side_effect = OSError("CRT conversion failed")
    with pytest.raises(OSError), fixture.module.open_leaf(fixture.path, links=1):
        pytest.fail("Rejected handle was exposed")
    fixture.kernel.CloseHandle.assert_called_once_with(17)
    fixture.os.close.assert_not_called()


@pytest.mark.parametrize("phase", ["open", "read"])
def test_signature_change_refuses_even_when_win32_open_succeeds(windows_files, phase):
    fixture = windows_files
    if phase == "open":
        fixture.os.fstat.return_value.st_ino = 12
    expected = "during open" if phase == "open" else "during the read"
    with pytest.raises(OSError, match=expected), fixture.module.open_leaf(fixture.path, links=1):
        assert phase == "read"
        fixture.path.lstat.return_value.st_mtime_ns = 90
    fixture.os.close.assert_called_once_with(42)
    fixture.kernel.CloseHandle.assert_not_called()


@pytest.fixture
def append_file(windows_files):
    fixture = windows_files
    prefix = b"\x00\r\n\x1a" + b"x" * 19
    block = b"\r\n\x1a\x00"
    final_size = len(prefix) + len(block)
    fixture.attributes[19] = 0
    fixture.identities[19] = fixture.identities[17]
    fixture.kernel.CreateFileW.side_effect = [17, 19]
    fixture.crt.open_osfhandle.side_effect = [42, 43]
    fixture.os.O_RDWR = 2
    fixture.os.SEEK_SET = 0
    fixture.os.SEEK_END = 2
    fixture.os.read = Mock(return_value=prefix)
    fixture.os.lseek = Mock(side_effect=lambda _fd, _offset, whence: len(prefix) if whence == 2 else 0)

    def write(_fd, data):
        fixture.os.fstat.return_value.st_size += len(data)
        return len(data)

    def close(fd):
        if fd == 42:
            # Windows reports the final last-write time after closing the writer.
            fixture.path.lstat.return_value.st_size = fixture.os.fstat.return_value.st_size
            fixture.path.lstat.return_value.st_mtime_ns = 51
            fixture.os.fstat.return_value.st_mtime_ns = 51

    fixture.os.write = Mock(side_effect=write)
    fixture.os.close.side_effect = close
    timeline = Mock()
    timeline.attach_mock(fixture.kernel.CreateFileW, "open")
    timeline.attach_mock(fixture.os.read, "read")
    timeline.attach_mock(fixture.os.lseek, "seek")
    timeline.attach_mock(fixture.os.write, "write")
    timeline.attach_mock(fixture.kernel.FlushFileBuffers, "flush")
    timeline.attach_mock(fixture.os.close, "close")
    return SimpleNamespace(api=fixture, timeline=timeline, block=block, prefix=prefix, final_size=final_size,
                           append=lambda **overrides: fixture.module.append_leaf(
                               fixture.path, **{"block": block, "expected_file_id": fixture.identities[17],
                                                "prior_size": len(prefix), **overrides}))


def test_append_compares_prefix_on_write_handle_flushes_then_reopens(append_file):
    model = append_file
    fixture = model.api
    assert model.append(prior_bytes=model.prefix) == (1, 9, model.final_size, 51)
    assert model.timeline.mock_calls == [
        call.open(str(fixture.path), 0xC0000000, 1, None, 3, 0x00200000, None),
        call.seek(42, 0, 0), call.read(42, len(model.prefix) + 1), call.seek(42, 0, 2),
        call.write(42, model.block), call.flush(17), call.close(42),
        call.open(str(fixture.path), 0x80000000, 1, None, 3, 0x00200000, None), call.close(43),
    ]
    assert fixture.crt.open_osfhandle.call_args_list == [call(17, 0x8082), call(19, 0x8080)]
    fixture.kernel.CloseHandle.assert_not_called()


@pytest.mark.parametrize("kwargs", [
    {"block": b""}, {"block": b"x" * (1024 * 1024 + 1)}, {"prior_size": True}, {"prior_size": 2**63},
    {"expected_file_id": (91, bytes(16))}, {"prior_size": 65537, "prior_bytes": b"x" * 65537},
    {"prior_bytes": b"short"},
])
def test_invalid_append_inputs_never_probe_path(append_file, kwargs):
    with pytest.raises(ValueError):
        append_file.append(**kwargs)
    append_file.api.path.lstat.assert_not_called()
    append_file.api.kernel.CreateFileW.assert_not_called()


@pytest.mark.parametrize("fault", ["wrong_identity", "wrong_length", "wrong_prefix", "wrong_eof", "sharing_denied"])
def test_append_refuses_before_write_if_preconditions_fail(append_file, fault):
    model = append_file
    fixture = model.api
    kwargs = {}
    if fault == "wrong_identity":
        kwargs["expected_file_id"] = (91, b"f" * 15 + b"!")
    elif fault == "wrong_length":
        kwargs["prior_size"] = len(model.prefix) - 1
    elif fault == "wrong_prefix":
        kwargs["prior_bytes"] = b"!" * len(model.prefix)
    elif fault == "wrong_eof":
        fixture.os.lseek.side_effect = None
        fixture.os.lseek.return_value = len(model.prefix) - 1
    else:
        fixture.kernel.CreateFileW.side_effect = None
        fixture.kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value
    with pytest.raises(OSError):
        model.append(**kwargs)
    fixture.os.write.assert_not_called()
    fixture.kernel.FlushFileBuffers.assert_not_called()
    assert fixture.kernel.CreateFileW.call_count == 1
    if fault != "sharing_denied":
        fixture.os.close.assert_called_once_with(42)
    else:
        fixture.os.close.assert_not_called()


@pytest.mark.parametrize("fault", ["short_write", "flush_failed", "reopen_replaced"])
def test_append_preserves_late_failure_without_repeating_write(append_file, fault):
    fixture = append_file.api
    if fault == "short_write":
        fixture.os.write.side_effect = None
        fixture.os.write.return_value = 1
    elif fault == "flush_failed":
        fixture.kernel.FlushFileBuffers.return_value = False
    else:
        fixture.identities[19] = (91, b"f" * 15 + b"!")
    with pytest.raises(OSError, match=r"partial block|Win32 failure|after the append handle closed"):
        append_file.append()
    fixture.os.write.assert_called_once_with(42, append_file.block)
    assert fixture.os.close.call_args_list == ([call(42), call(43)] if fault == "reopen_replaced" else [call(42)])
    if fault == "short_write":
        fixture.kernel.FlushFileBuffers.assert_not_called()
    else:
        fixture.kernel.FlushFileBuffers.assert_called_once_with(17)


@pytest.fixture
def pinned_directory(windows_files):
    fixture = windows_files
    fixture.attributes[17] = 0x10
    fixture.identities[17] = fixture.identities[28]
    return fixture


def test_directory_flush_matches_live_pin_and_only_closes_new_handle(pinned_directory):
    fixture = pinned_directory
    assert fixture.module.flush_pinned_directory(fixture.path, 28) == (95, b"d" * 16)
    fixture.kernel.CreateFileW.assert_called_once_with(str(fixture.path), 0xC0000000, 3, None, 3, 0x02200000, None)
    fixture.kernel.FlushFileBuffers.assert_called_once_with(17)
    fixture.kernel.CloseHandle.assert_called_once_with(17)
    assert [call.args[:2] for call in fixture.kernel.GetFileInformationByHandleEx.call_args_list if call.args[1] == 18] == [
        (28, 18), (17, 18), (17, 18), (28, 18),
    ]


@pytest.mark.parametrize("wrong_field", ["volume", "high_file_id", "reparse"])
def test_directory_flush_refuses_wrong_native_identity(pinned_directory, wrong_field):
    fixture = pinned_directory
    if wrong_field == "volume":
        fixture.identities[17] = (99, b"d" * 16)
    elif wrong_field == "high_file_id":
        fixture.identities[17] = (95, b"d" * 8 + b"x" * 8)
    else:
        fixture.attributes[17] |= 0x400
    with pytest.raises(OSError, match=r"not the pinned directory|a reparse point"):
        fixture.module.flush_pinned_directory(fixture.path, 28)
    fixture.kernel.FlushFileBuffers.assert_not_called()
    fixture.kernel.CloseHandle.assert_called_once_with(17)


@pytest.mark.parametrize("failure", ["flush_failed", "pin_changed"])
def test_directory_flush_raises_without_certifying_failure_as_success(pinned_directory, failure):
    fixture = pinned_directory

    def flush(_handle):
        if failure == "flush_failed":
            return False
        fixture.identities[28] = (99, b"m" * 16)
        return True

    fixture.kernel.FlushFileBuffers.side_effect = flush
    with pytest.raises(OSError, match=r"Win32 failure|changed during the flush"):
        fixture.module.flush_pinned_directory(fixture.path, 28)
    fixture.kernel.CloseHandle.assert_called_once_with(17)
