"""Private Windows file operations for already-authorized backup paths.

The caller validates local paths and keeps the existing directory ancestry pins
open for the entire operation. No handle is usable after its owning scope ends.
An observed Windows directory flush is an API result, with no power-loss claim.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes as w
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_SHARE_READ = 0x01
_SHARE_WRITE = 0x02
_OPEN_EXISTING = 3
_BACKUP_SEMANTICS = 0x02000000
_OPEN_REPARSE_POINT = 0x00200000
_ATTRIBUTE_DIRECTORY = 0x10
_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_TYPE_DISK = 1
_ATTRIBUTES_INFO = 9
_FILE_ID_INFO = 18

FileID = tuple[int, bytes]
LeafSignature = tuple[int, int, int, int]


class LeafDescriptor(NamedTuple):
    fd: int
    signature: LeafSignature
    file_id: FileID


class _FileIDInfo(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_uint64), ("identifier", ctypes.c_ubyte * 16)]


@lru_cache(maxsize=1)
def _kernel32():
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "Windows file operations require Windows.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.GetFileType.argtypes, kernel.GetFileType.restype = [w.HANDLE], w.DWORD
    kernel.GetFileInformationByHandleEx.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
    kernel.GetFileInformationByHandleEx.restype = w.BOOL
    kernel.FlushFileBuffers.argtypes, kernel.FlushFileBuffers.restype = [w.HANDLE], w.BOOL
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    return kernel


def _winerror() -> OSError:
    return ctypes.WinError(ctypes.get_last_error())


def _open_existing(path: Path, *, directory: bool) -> int:
    # A leaf read denies concurrent write/delete opens. The new writable
    # directory handle shares read/write with the pre-existing ancestry pin.
    handle = _kernel32().CreateFileW(
        str(path), _GENERIC_READ | (_GENERIC_WRITE if directory else 0),
        _SHARE_READ | (_SHARE_WRITE if directory else 0), None, _OPEN_EXISTING,
        _OPEN_REPARSE_POINT | (_BACKUP_SEMANTICS if directory else 0), None,
    )
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise _winerror()
    return handle


def _close_handle(handle: int) -> None:
    if not _kernel32().CloseHandle(handle):
        raise _winerror()


def _file_id(handle: int, *, directory: bool) -> FileID:
    kernel = _kernel32()
    if kernel.GetFileType(handle) != _FILE_TYPE_DISK:
        raise OSError(errno.EINVAL, "The backup handle is not a disk file or directory.")
    attributes = (ctypes.c_uint32 * 2)()
    info = _FileIDInfo()
    if not kernel.GetFileInformationByHandleEx(handle, _ATTRIBUTES_INFO, attributes, ctypes.sizeof(attributes)):
        raise _winerror()
    if attributes[0] & _ATTRIBUTE_REPARSE_POINT or bool(attributes[0] & _ATTRIBUTE_DIRECTORY) != directory:
        raise OSError(errno.EINVAL, "The backup handle is a reparse point or has the wrong file type.")
    if not kernel.GetFileInformationByHandleEx(handle, _FILE_ID_INFO, ctypes.byref(info), ctypes.sizeof(info)):
        raise _winerror()
    if not any(info.identifier):
        raise OSError(errno.EINVAL, "Windows did not provide a backup file identity.")
    return info.volume, bytes(info.identifier)


def _leaf_signature(info: os.stat_result, links: int) -> LeafSignature:
    if (not stat.S_ISREG(info.st_mode) or info.st_file_attributes & _ATTRIBUTE_REPARSE_POINT
            or not info.st_ino or info.st_nlink != links):
        raise OSError(errno.EINVAL, "The backup leaf is not an ordinary file with the expected link count.")
    # Windows CPython lstat/fstat do not consistently agree on ctime semantics.
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _binary_descriptor(handle: int) -> int:
    import msvcrt

    return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)


@contextmanager
def open_leaf(path: Path, *, links: int) -> Iterator[LeafDescriptor]:
    """Borrow a read-only binary fd to an exact existing leaf, with its parent pinned.

    The caller supplies the expected link count and retains the approved ancestry
    pins throughout this scope. The caller owns byte limits, hashing, and comparing
    identities across separate scopes. This context manager closes the descriptor.
    """
    _kernel32()  # Refuse unsupported platforms before probing the path.
    expected = _leaf_signature(path.lstat(), links)
    handle = _open_existing(path, directory=False)
    try:
        file_id = _file_id(handle, directory=False)
        fd = _binary_descriptor(handle)
    except BaseException:
        _close_handle(handle)
        raise
    # msvcrt now owns the native handle, closed only through the descriptor.
    try:
        if _leaf_signature(os.fstat(fd), links) != expected or _leaf_signature(path.lstat(), links) != expected:
            raise OSError(errno.EIO, "The named backup leaf changed during open.")
        yield LeafDescriptor(fd, expected, file_id)
        if _leaf_signature(os.fstat(fd), links) != expected or _leaf_signature(path.lstat(), links) != expected:
            raise OSError(errno.EIO, "The backup leaf changed during the read.")
    finally:
        os.close(fd)


def flush_pinned_directory(path: Path, pinned_handle: int) -> FileID:
    """Flush a separate writable handle to the exact directory of a live pin.

    The caller keeps that pin and its ancestry pins alive throughout, and owns
    closing them. This function closes only the new writable handle.
    """
    expected = _file_id(pinned_handle, directory=True)
    handle = _open_existing(path, directory=True)
    try:
        if _file_id(handle, directory=True) != expected:
            raise OSError(errno.EIO, "The writable backup directory is not the pinned directory.")
        if not _kernel32().FlushFileBuffers(handle):
            raise _winerror()
        if _file_id(handle, directory=True) != expected or _file_id(pinned_handle, directory=True) != expected:
            raise OSError(errno.EIO, "The pinned backup directory changed during the flush.")
        return expected
    finally:
        _close_handle(handle)
