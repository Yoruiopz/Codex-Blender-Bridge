"""Opt-in Windows backup primitive probe on an explicit disposable fixture parent.

Uses local synthetic files and retains one new, owned directory. The receipt
records binary append, a competing Win32 open, directory flush, and cross-process
readback. Power-loss behavior and the Blender backup workflow require separate evidence.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))

from blender_codex_bridge import _windows_backup_files as windows_files
from blender_codex_bridge.image_files import _absolute
from blender_codex_bridge.texture_staging import _ancestors, _directory_id, _DirectoryPins

PREFIX = "bcb-backup-file-probe-"
PAYLOAD = b"\x00\r\n\x1a" + bytes(range(256)) * 2
COMPETITOR = b"owned competing file\r\n\x1a"
APPEND_PREFIX = b"owned append prefix\x00\r\n\x1a"
APPEND_BLOCK = b"\x00\r\n\x1afirst binary block\xff"
APPEND_TAIL = b"\x1a\r\n\x00second binary block\x80"
ABRUPT_EXIT = 91
ERROR_SHARING_VIOLATION = 32


def receipt(path: Path, expected: bytes, links: int) -> dict:
    with windows_files.open_leaf(path, links=links) as leaf:
        with os.fdopen(leaf.fd, "rb", closefd=False) as stream:
            observed = stream.read(len(expected) + 1)
        if observed != expected:
            raise RuntimeError(f"Complete binary readback failed for {path.name}")
    return {"sha256": hashlib.sha256(observed).hexdigest(), "bytes": len(observed),
            "file_id": [leaf.file_id[0], leaf.file_id[1].hex()], "links": links}


def write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def file_receipts(root: Path) -> dict:
    return {"stage": receipt(root / "staged.bin", PAYLOAD, 2),
            "published": receipt(root / "published.bin", PAYLOAD, 2),
            "competitor": receipt(root / "competing.bin", COMPETITOR, 1),
            "append": receipt(root / "appended.bin", APPEND_PREFIX + APPEND_BLOCK + APPEND_TAIL, 1)}


def probe_append(root: Path) -> dict:
    path = root / "appended.bin"
    write_exclusive(path, APPEND_PREFIX)
    before = receipt(path, APPEND_PREFIX, 1)
    volume, identifier = before["file_id"]
    expected_id = (volume, bytes.fromhex(identifier))

    # Isolate the share-mode check from the write itself. This is the same
    # handle primitive used by append_leaf, with an independent CreateFileW call.
    with windows_files._open_verified_leaf(path, links=1, writable=True) as (_, guard):
        if guard.file_id != expected_id or guard.signature[2] != before["bytes"]:
            raise RuntimeError("Share check did not bind the expected append file")
        try:
            competing_handle = windows_files._open_existing(path, directory=False, writable=True)
        except OSError as error:
            share_error = getattr(error, "winerror", None)
            if share_error != ERROR_SHARING_VIOLATION:
                raise
        else:
            windows_files._close_handle(competing_handle)
            raise RuntimeError("A competing Win32 writable open succeeded while the write handle was held")

    prefix = APPEND_PREFIX + APPEND_BLOCK
    first = windows_files.append_leaf(path, APPEND_BLOCK, expected_file_id=expected_id, prior_size=before["bytes"])
    intermediate = receipt(path, prefix, 1)
    if first[2] != len(prefix) or intermediate["file_id"] != before["file_id"]:
        raise RuntimeError("First append did not preserve its file identity and verify the expected length")

    wrong_prefix = b"!" + prefix[1:]
    try:
        windows_files.append_leaf(path, APPEND_TAIL, expected_file_id=expected_id,
                                  prior_size=intermediate["bytes"], prior_bytes=wrong_prefix)
    except OSError as error:
        if error.errno != errno.EIO or error.strerror != "The backup leaf prefix changed before append.":
            raise
    else:
        raise RuntimeError("Append accepted a competing prefix of the same length")
    if receipt(path, prefix, 1) != intermediate:
        raise RuntimeError("Rejected append changed the existing file")

    final = windows_files.append_leaf(path, APPEND_TAIL, expected_file_id=expected_id,
                                      prior_size=intermediate["bytes"], prior_bytes=prefix)
    complete = receipt(path, prefix + APPEND_TAIL, 1)
    if final[2] != complete["bytes"] or complete["file_id"] != before["file_id"]:
        raise RuntimeError("Checked-prefix append did not preserve the file identity and verify the expected length")
    return {"competing_writable_open_winerror": share_error, "competing_open_scope": "same_process_same_path",
            "initial": before, "after_first_append": intermediate, "after_checked_prefix_append": complete,
            "wrong_prefix_refused_unchanged": True, "successful_append_flushes": 2}


def child(root: Path, phase: str, nonce: str) -> None:
    if not root.name.startswith(PREFIX) or re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
        raise RuntimeError("Expected a runner-created probe directory and nonce")
    # A fresh process receives only the owned root as its working directory.
    with closing(_DirectoryPins(root)) as pins:
        receipt(root / "owner", f"{os.getppid()}\n{nonce}".encode("ascii"), 1)
        if phase == "reader":
            print(json.dumps({"pid": os.getpid(), "files": file_receipts(root)}), flush=True)
            return
        append = probe_append(root)
        stage, competitor = root / "staged.bin", root / "competing.bin"
        write_exclusive(stage, PAYLOAD)
        before = receipt(stage, PAYLOAD, 1)
        write_exclusive(competitor, COMPETITOR)
        occupied = receipt(competitor, COMPETITOR, 1)
        try:
            os.link(stage, competitor, follow_symlinks=False)
        except FileExistsError as error:
            if receipt(competitor, COMPETITOR, 1) != occupied:
                raise RuntimeError("The occupied destination changed") from error
        else:
            raise RuntimeError("Create-only hard link replaced the occupied destination")
        os.link(stage, root / "published.bin", follow_symlinks=False)
        measured = file_receipts(root)
        if measured["stage"] != measured["published"] or measured["stage"]["file_id"] != before["file_id"]:
            raise RuntimeError("Publication did not preserve the exact file identity")
        if measured["append"] != append["after_checked_prefix_append"]:
            raise RuntimeError("Appended file changed before the writer exit boundary")
        volume, identifier = windows_files.flush_pinned_directory(root, pins.handles[-1])
        print(json.dumps({"pid": os.getpid(), "files": measured, "append": append,
                          "flushed_directory_id": [volume, identifier.hex()]}), flush=True)
        # Exit before Python finally blocks release the directory pins.
        os._exit(ABRUPT_EXIT)


def run_child(root: Path, phase: str, nonce: str, expected_exit: int) -> dict:
    command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--child", phase, "--nonce", nonce]
    result = subprocess.run(command, cwd=root, stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=15, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != expected_exit:
        raise RuntimeError(f"{phase} exited with {result.returncode}: {result.stderr.decode(errors='replace')}")
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-parent", type=Path, help="Explicit existing directory owned by the test fixture")
    parser.add_argument("--child", choices=("writer", "reader"), help=argparse.SUPPRESS)
    parser.add_argument("--nonce", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows is required")
    if args.child:
        child(Path.cwd(), args.child, args.nonce or "")
        return
    if args.fixture_parent is None:
        parser.error("--fixture-parent is required")
    parent = _absolute(str(args.fixture_parent), "Probe parent")
    if parent == Path(parent.anchor) or parent.resolve(strict=True) != parent:
        parser.error("Use the direct path to an existing fixture-owned subdirectory")
    for directory in _ancestors(parent):
        _directory_id(directory)
    with closing(_DirectoryPins(parent)):
        root = Path(tempfile.mkdtemp(prefix=PREFIX, dir=parent))
    print(f"Owned probe directory {root}", flush=True)
    nonce = uuid4().hex
    with closing(_DirectoryPins(root)):
        write_exclusive(root / "owner", f"{os.getpid()}\n{nonce}".encode("ascii"))
    writer = run_child(root, "writer", nonce, ABRUPT_EXIT)
    reader = run_child(root, "reader", nonce, 0)
    if len({os.getpid(), writer["pid"], reader["pid"]}) != 3 or writer["files"] != reader["files"]:
        raise RuntimeError("Fresh reader did not verify the failed-process boundary and exact files")
    append = writer.pop("append")
    if append["after_checked_prefix_append"] != reader["files"]["append"]:
        raise RuntimeError("Fresh reader did not verify the exact appended file")
    report = {"python": list(sys.version_info[:3]),
              "module_sha256": hashlib.sha256(Path(windows_files.__file__).read_bytes()).hexdigest(),
              "file_fsync_returned_success": True, "create_only_collision_preserved": True,
              "pinned_directory_flush_returned_success": True, "process_exit_reopen_verified": True,
              "power_loss_durability_verified": False, "product_backup_durability_qualified": False,
              "writer_exit": ABRUPT_EXIT, "reader_exit": 0, "writer": writer, "reader": reader,
              "append": {**append, "process_exit_reopen_verified": True}}
    encoded = json.dumps(report, sort_keys=True)
    with closing(_DirectoryPins(root)):
        write_exclusive(root / "report.json", (encoded + "\n").encode("utf-8"))
    print(encoded, flush=True)


if __name__ == "__main__":
    main()
