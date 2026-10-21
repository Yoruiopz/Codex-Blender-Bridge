"""Bounded file evidence for disposable, runner-owned native cache experiments.

This is fixture support, not a production approved-path policy or a sandbox against
concurrent hostile filesystem changes. Native cache writers must have stopped before
calling snapshot_files. Symlinks and special files are refused rather than followed.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path


def snapshot_files(directory: Path, *, max_files: int = 128, max_bytes: int = 64 << 20,
                   max_directories: int = 64) -> dict[str, dict[str, int | str]]:
    """Hash every regular file in a bounded owned directory, or fail explicitly."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("A real runner-owned cache directory is required")
    if min(max_files, max_bytes, max_directories) < 1:
        raise ValueError("Evidence budgets must be positive")
    root = directory.resolve(strict=True)
    pending = [root]
    directories, total_bytes = 1, 0
    result: dict[str, dict[str, int | str]] = {}
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError("Cache evidence refuses symlinks")
                if stat.S_ISDIR(info.st_mode):
                    directories += 1
                    if directories > max_directories:
                        raise ValueError("Cache directory evidence budget exceeded")
                    pending.append(path)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("Cache evidence refuses special files")
                if len(result) >= max_files or total_bytes + info.st_size > max_bytes:
                    raise ValueError("Complete cache-file evidence exceeds its budget")
                digest = hashlib.sha256()
                observed = 0
                with path.open("rb") as stream:
                    while data := stream.read(1 << 20):
                        observed += len(data)
                        if total_bytes + observed > max_bytes:
                            raise ValueError("Cache changed or exceeded its byte budget")
                        digest.update(data)
                if observed != info.st_size or path.stat().st_mtime_ns != info.st_mtime_ns:
                    raise ValueError("Cache changed during evidence collection")
                total_bytes += observed
                result[path.relative_to(root).as_posix()] = {
                    "bytes": observed, "sha256": digest.hexdigest(),
                }
    return dict(sorted(result.items()))


def compare_files(before: dict, after: dict) -> dict[str, list[str] | int]:
    """Keep additions, removals and same-count content edits distinct."""
    common = before.keys() & after.keys()
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "modified": sorted(name for name in common if before[name] != after[name]),
        "unchanged_count": sum(before[name] == after[name] for name in common),
    }
