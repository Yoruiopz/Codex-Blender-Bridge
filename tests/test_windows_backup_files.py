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
def sibling_link(windows_files, tmp_path):
    fixture = windows_files
    source = fixture.path
    source.is_absolute.return_value = True
    source.parent = tmp_path
    target = Mock(spec=Path)
    target.parent = tmp_path
    source_named = source.lstat.return_value
    source_open = fixture.os.fstat.return_value
    target_named = SimpleNamespace(**vars(source_named))
    target_open = SimpleNamespace(**vars(source_open))
    target.lstat.return_value = target_named
    fixture.attributes[19] = 0
    fixture.identities[19] = fixture.identities[17]
    fixture.kernel.CreateFileW.side_effect = [17, 19]
    fixture.crt.open_osfhandle.side_effect = [42, 43]
    fixture.os.fstat.side_effect = {42: source_open, 43: target_open}.__getitem__

    def create_link(_source, _target, **_options):
        for metadata in (source_named, source_open, target_named, target_open):
            metadata.st_nlink = 2

    fixture.os.link = Mock(side_effect=create_link)
    fixture.os.unlink = Mock()
    timeline = Mock()
    timeline.attach_mock(fixture.kernel.CreateFileW, "open")
    timeline.attach_mock(fixture.os.link, "link")
    timeline.attach_mock(fixture.os.close, "close")
    expected = {"expected_file_id": fixture.identities[17], "expected_signature": (1, 9, 23, 37)}

    def publish(path=target, **override):
        return fixture.module.link_leaf(source, path, **{**expected, **override})

    return SimpleNamespace(api=fixture, source=source, target=target, expected=expected, publish=publish,
                           timeline=timeline, create_link=create_link, source_open=source_open,
                           target_named=target_named, target_open=target_open)


def test_link_is_create_only_and_verifies_target_with_source_handle_held(sibling_link):
    model = sibling_link
    fixture = model.api
    assert model.publish() == model.expected["expected_signature"]
    assert model.timeline.mock_calls == [
        call.open(str(model.source), 0x80000000, 1, None, 3, 0x00200000, None),
        call.link(model.source, model.target, follow_symlinks=False),
        call.open(str(model.target), 0x80000000, 1, None, 3, 0x00200000, None),
        call.close(43), call.close(42),
    ]
    fixture.crt.open_osfhandle.assert_has_calls([call(17, 0x8080), call(19, 0x8080)])
    fixture.kernel.CloseHandle.assert_not_called()
    fixture.os.unlink.assert_not_called()


@pytest.mark.parametrize("fault", ["relative", "same_path", "other_parent", "invalid_identity", "invalid_signature"])
def test_invalid_link_requires_distinct_sibling_and_typed_expected_facts(sibling_link, fault):
    model = sibling_link
    kwargs = {}
    target = model.target
    if fault == "relative":
        model.source.is_absolute.return_value = False
    elif fault == "same_path":
        target = model.source
    elif fault == "other_parent":
        target.parent /= "subdirectory"
    elif fault == "invalid_identity":
        kwargs["expected_file_id"] = (91, bytes(16))
    else:
        kwargs["expected_signature"] = (True, 9, 23, 37)
    with pytest.raises(ValueError):
        model.publish(target, **kwargs)
    model.source.lstat.assert_not_called()
    model.api.os.link.assert_not_called()


@pytest.mark.parametrize("fault", ["native_id", "size", "already_linked"])
def test_link_refuses_changed_source_before_publication(sibling_link, fault):
    model = sibling_link
    kwargs = {}
    if fault == "native_id":
        kwargs["expected_file_id"] = (91, b"f" * 15 + b"!")
    elif fault == "size":
        kwargs["expected_signature"] = (1, 9, 24, 37)
    else:
        model.source.lstat.return_value.st_nlink = 2
    with pytest.raises(OSError, match=r"changed before hard-link publication|ordinary file"):
        model.publish(**kwargs)
    model.api.os.link.assert_not_called()
    model.target.lstat.assert_not_called()


@pytest.mark.parametrize("failure", [FileExistsError("occupied"), PermissionError("sharing violation")])
def test_native_link_failure_is_propagated_without_fallback(sibling_link, failure):
    model = sibling_link
    model.api.os.link.side_effect = failure
    with pytest.raises(type(failure)) as observed:
        model.publish()
    assert observed.value is failure
    model.api.os.link.assert_called_once_with(model.source, model.target, follow_symlinks=False)
    model.api.os.close.assert_called_once_with(42)
    model.target.lstat.assert_not_called()
    model.api.os.unlink.assert_not_called()


@pytest.mark.parametrize("fault", ["target_full_id", "target_signature", "source_link_count", "close_failed"])
def test_late_link_failure_reports_possible_effect_without_unlink_or_retry(sibling_link, fault):
    model = sibling_link

    def invalid_link(*args, **kwargs):
        model.create_link(*args, **kwargs)
        if fault == "target_full_id":
            model.api.identities[19] = (91, b"f" * 15 + b"!")
        elif fault == "target_signature":
            model.target_named.st_mtime_ns = model.target_open.st_mtime_ns = 39
        elif fault == "source_link_count":
            model.source_open.st_nlink = 1
        else:
            model.api.os.close.side_effect = [None, OSError("source close failed")]

    model.api.os.link.side_effect = invalid_link
    with pytest.raises(OSError, match="The target may exist") as error:
        model.publish()
    assert isinstance(error.value.__cause__, OSError)
    model.api.os.link.assert_called_once_with(model.source, model.target, follow_symlinks=False)
    assert model.api.os.close.call_args_list == [call(43), call(42)]
    model.api.os.unlink.assert_not_called()


@pytest.fixture
def stage_retirement(sibling_link, monkeypatch):
    model = sibling_link
    fixture = model.api
    model.create_link(model.source, model.target, follow_symlinks=False)
    fixture.attributes[20] = 0
    fixture.identities[20] = fixture.identities[17]
    refused_open = ctypes.c_void_p(-1).value
    fixture.kernel.CreateFileW.side_effect = [19, 17, refused_open, refused_open, 20]
    fixture.crt.open_osfhandle.side_effect = [43, 42, 44]
    fixture.os.fstat.side_effect = {42: model.source_open, 43: model.target_open, 44: model.target_open}.__getitem__
    expected_bytes = b"\r\n\x1a\x00" + b"x" * 19
    fixture.os.read = Mock(return_value=expected_bytes)

    names = {17: r"\\?\C:\fixture\stage.bin", 19: r"\\?\C:\fixture\published.bin"}

    def final_path(handle, buffer, capacity, flags):
        assert capacity == 4097 and flags == 0
        buffer.value = names[handle]
        return len(buffer.value)

    fixture.kernel.GetFinalPathNameByHandleW = Mock(side_effect=final_path)
    error = PermissionError("modeled sharing violation")
    error.winerror = 32
    monkeypatch.setattr(fixture.module, "_winerror", lambda: error)
    disposition = False

    def set_disposition(handle, query, buffer, size):
        assert handle == 17 and query == 4 and size == 4
        assert ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int32)).contents.value == 1
        nonlocal disposition
        disposition = True
        return True

    def close(fd):
        if fd == 42 and disposition:
            model.source.lstat.side_effect = FileNotFoundError
            model.target_named.st_nlink = model.target_open.st_nlink = 1

    fixture.kernel.SetFileInformationByHandle = Mock(side_effect=set_disposition)
    fixture.os.close.side_effect = close
    model.timeline.attach_mock(fixture.os.read, "read")
    model.timeline.attach_mock(fixture.kernel.SetFileInformationByHandle, "dispose")

    def retire(**override):
        return fixture.module.retire_stage_link(model.source, model.target,
                                                **{**model.expected, "expected_bytes": expected_bytes, **override})

    return SimpleNamespace(model=model, retire=retire, expected_bytes=expected_bytes, names=names,
                           share_error=error, refused_open=refused_open)


def test_retirement_holds_published_guard_through_disposition_close_and_reopen(stage_retirement):
    probe = stage_retirement
    model = probe.model
    assert probe.retire() == model.expected["expected_signature"]
    assert [(operation[0], operation.args[0]) for operation in model.timeline.mock_calls] == [
        ("open", str(model.target)), ("open", str(model.source)), ("read", 43),
        ("open", str(model.target)), ("open", str(model.source)), ("dispose", 17), ("close", 42),
        ("open", str(model.target)), ("read", 44), ("close", 44), ("close", 43),
    ]
    assert model.api.kernel.CreateFileW.call_args_list == [
        call(str(model.target), 0x80000000, 1, None, 3, 0x00200000, None),
        call(str(model.source), 0x80010000, 1, None, 3, 0x00200000, None),
        call(str(model.target), 0x80010000, 5, None, 3, 0x00200000, None),
        call(str(model.source), 0x80010000, 5, None, 3, 0x00200000, None),
        call(str(model.target), 0x80000000, 1, None, 3, 0x00200000, None),
    ]
    assert model.api.os.read.call_args_list == [call(43, 24), call(44, 24)]
    model.api.os.unlink.assert_not_called()


@pytest.mark.parametrize("bad_bytes", [b"", b"short", b"x" * (1024 * 1024 + 1)])
def test_retirement_refuses_invalid_inline_readback_before_native_open(stage_retirement, bad_bytes):
    with pytest.raises(ValueError, match="exact bounded bytes"):
        stage_retirement.retire(expected_bytes=bad_bytes)
    stage_retirement.model.api.kernel.CreateFileW.assert_not_called()


@pytest.mark.parametrize("fault", ["same_actual_name", "target_id", "target_bytes", "target_delete_access_granted",
                                   "stage_delete_access_granted", "wrong_winerror"])
def test_retirement_refuses_unproven_target_before_disposition(stage_retirement, fault):
    probe = stage_retirement
    model = probe.model
    if fault == "same_actual_name":
        probe.names[19] = probe.names[17].upper()
    elif fault == "target_id":
        model.api.identities[19] = (91, b"z" * 16)
    elif fault == "target_bytes":
        model.api.os.read.return_value = b"z" * 23
    elif fault == "target_delete_access_granted":
        model.api.kernel.CreateFileW.side_effect = [19, 17, 21]
    elif fault == "stage_delete_access_granted":
        model.api.kernel.CreateFileW.side_effect = [19, 17, probe.refused_open, 21]
    else:
        probe.share_error.winerror = 5
    with pytest.raises(OSError):
        probe.retire()
    model.api.kernel.SetFileInformationByHandle.assert_not_called()
    if fault in {"target_delete_access_granted", "stage_delete_access_granted"}:
        model.api.kernel.CloseHandle.assert_called_once_with(21)
    else:
        model.api.kernel.CloseHandle.assert_not_called()
    assert model.api.os.close.call_args_list == [call(42), call(43)]
    model.api.os.unlink.assert_not_called()


def test_retirement_refuses_incompatible_independent_guards_without_loosening_share(stage_retirement):
    probe = stage_retirement
    model = probe.model
    model.api.kernel.CreateFileW.side_effect = [19, probe.refused_open]
    with pytest.raises(PermissionError, match="sharing violation"):
        probe.retire()
    assert model.api.kernel.CreateFileW.call_args_list == [
        call(str(model.target), 0x80000000, 1, None, 3, 0x00200000, None),
        call(str(model.source), 0x80010000, 1, None, 3, 0x00200000, None),
    ]
    model.api.os.close.assert_called_once_with(43)
    model.api.kernel.SetFileInformationByHandle.assert_not_called()
    model.api.os.unlink.assert_not_called()


@pytest.mark.parametrize("fault", ["disposition_refused", "target_replaced", "target_bytes", "stage_still_present"])
def test_retirement_preserves_uncertainty_after_disposition_attempt(stage_retirement, fault):
    probe = stage_retirement
    model = probe.model
    if fault == "disposition_refused":
        api = model.api.kernel.SetFileInformationByHandle
        api.side_effect = None
        api.return_value = False
    elif fault == "target_replaced":
        model.api.identities[20] = (91, b"z" * 16)
    elif fault == "target_bytes":
        model.api.os.read.side_effect = [probe.expected_bytes, b"z" * 23]
    else:
        close = model.api.os.close.side_effect

        def stage_remains(fd):
            close(fd)
            if fd == 42:
                model.source.lstat.side_effect = None

        model.api.os.close.side_effect = stage_remains
    with pytest.raises(OSError, match="The staging name may have changed") as error:
        probe.retire()
    assert isinstance(error.value.__cause__, OSError)
    model.api.kernel.SetFileInformationByHandle.assert_called_once()
    model.api.os.unlink.assert_not_called()


def test_retirement_does_not_release_published_guard_to_claim_deferred_deletion_succeeded(stage_retirement):
    model = stage_retirement.model
    apply_retirement = model.api.os.close.side_effect
    model.api.os.close.side_effect = lambda fd: apply_retirement(42) if fd == 43 else None
    with pytest.raises(OSError, match="The staging name may have changed") as error:
        stage_retirement.retire()
    assert "expected link count" in str(error.value.__cause__)
    model.api.kernel.SetFileInformationByHandle.assert_called_once()
    assert model.api.os.close.call_args_list == [call(42), call(43)]
    assert model.api.kernel.CreateFileW.call_count == 4
    model.api.os.unlink.assert_not_called()


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
