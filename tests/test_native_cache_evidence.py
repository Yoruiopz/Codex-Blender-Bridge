"""Native cache proof must not hide truncation, follow links or miss same-count edits."""

from __future__ import annotations

import os

import pytest

from scripts.native_cache_evidence import compare_files, snapshot_files


def test_complete_cache_hashes_detect_content_change_with_identical_size(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "frame.uni").write_bytes(b"original")
    before = snapshot_files(cache)
    (cache / "frame.uni").write_bytes(b"modified")
    after = snapshot_files(cache)
    assert before["frame.uni"]["bytes"] == after["frame.uni"]["bytes"] == 8
    assert compare_files(before, after) == {
        "added": [], "removed": [], "modified": ["frame.uni"], "unchanged_count": 0,
    }


def test_added_removed_and_protected_files_remain_distinct(tmp_path):
    (tmp_path / "old").write_bytes(b"old")
    (tmp_path / "protected").write_bytes(b"same")
    before = snapshot_files(tmp_path)
    (tmp_path / "old").unlink()
    (tmp_path / "new").write_bytes(b"new")
    assert compare_files(before, snapshot_files(tmp_path)) == {
        "added": ["new"], "removed": ["old"], "modified": [], "unchanged_count": 1,
    }


@pytest.mark.parametrize("budget", [{"max_files": 1}, {"max_bytes": 5},
                                   {"max_directories": 1}])
def test_complete_evidence_fails_instead_of_truncating(tmp_path, budget):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/first").write_bytes(b"123")
    (tmp_path / "data/second").write_bytes(b"456")
    with pytest.raises(ValueError, match="budget"):
        snapshot_files(tmp_path, **budget)


@pytest.mark.parametrize("directory_link", [False, True])
def test_evidence_does_not_follow_file_or_directory_symlinks(tmp_path, directory_link):
    owned, other = tmp_path / "owned", tmp_path / "outside"
    owned.mkdir()
    other.mkdir()
    (other / "private").write_bytes(b"outside")
    target = other if directory_link else other / "private"
    try:
        (owned / "link").symlink_to(target, target_is_directory=directory_link)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem does not permit fixture symlinks")
    with pytest.raises(ValueError, match="symlink"):
        snapshot_files(owned)


def test_symlinked_root_is_rejected(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(cache, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Filesystem does not permit fixture symlinks")
    with pytest.raises(ValueError, match="real runner-owned"):
        snapshot_files(link)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO fixture")
def test_special_file_is_rejected_without_opening_it(tmp_path):
    os.mkfifo(tmp_path / "fifo")
    with pytest.raises(ValueError, match="special files"):
        snapshot_files(tmp_path)


def test_zero_budget_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        snapshot_files(tmp_path, max_files=0)
