"""Opt-in Windows backup primitive probe on an explicit disposable fixture parent.

Uses local synthetic files and retains one new, owned directory. The receipt
records an API-level directory flush and cross-process readback. Filesystem
power-loss behavior and the Blender backup workflow require separate evidence.
"""

from __future__ import annotations

import argparse
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
ABRUPT_EXIT = 91


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
            "competitor": receipt(root / "competing.bin", COMPETITOR, 1)}


def child(root: Path, phase: str, nonce: str) -> None:
    if not root.name.startswith(PREFIX) or re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
        raise RuntimeError("Expected a runner-created probe directory and nonce")
    # A fresh process receives only the owned root as its working directory.
    with closing(_DirectoryPins(root)) as pins:
        receipt(root / "owner", f"{os.getppid()}\n{nonce}".encode("ascii"), 1)
        if phase == "reader":
            print(json.dumps({"pid": os.getpid(), "files": file_receipts(root)}), flush=True)
            return
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
        volume, identifier = windows_files.flush_pinned_directory(root, pins.handles[-1])
        print(json.dumps({"pid": os.getpid(), "files": measured,
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
    report = {"python": list(sys.version_info[:3]),
              "module_sha256": hashlib.sha256(Path(windows_files.__file__).read_bytes()).hexdigest(),
              "file_fsync_returned_success": True, "create_only_collision_preserved": True,
              "pinned_directory_flush_returned_success": True, "process_exit_reopen_verified": True,
              "power_loss_durability_verified": False, "product_backup_durability_qualified": False,
              "writer_exit": ABRUPT_EXIT, "reader_exit": 0, "writer": writer, "reader": reader}
    encoded = json.dumps(report, sort_keys=True)
    with closing(_DirectoryPins(root)):
        write_exclusive(root / "report.json", (encoded + "\n").encode("utf-8"))
    print(encoded, flush=True)


if __name__ == "__main__":
    main()
