from __future__ import annotations

import pytest

from scripts.native_resources import linux_available_memory, linux_process_memory


@pytest.fixture
def resources(tmp_path):
    proc, cgroup = tmp_path / "proc", tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    cgroup.mkdir()
    (proc / "meminfo").write_text("MemTotal: 999999 kB\nMemAvailable: 100 kB\n")
    (proc / "self/cgroup").write_text("0::/\n")
    (cgroup / "memory.max").write_text("max\n")
    return proc, cgroup


def test_available_memory_uses_host_bytes_for_unlimited_cgroup(resources):
    assert linux_available_memory(*resources) == 102400


def test_available_memory_uses_tightest_visible_ancestor(resources):
    proc, cgroup = resources
    child = cgroup / "job"
    child.mkdir()
    (proc / "self/cgroup").write_text("0::/job\n")
    for folder, maximum, current in ((cgroup, 90000, 60000), (child, 70000, 10000)):
        (folder / "memory.max").write_text(str(maximum))
        (folder / "memory.current").write_text(str(current))
    assert linux_available_memory(proc, cgroup) == 30000


def test_cgroup_over_limit_has_zero_headroom(resources):
    proc, cgroup = resources
    (cgroup / "memory.max").write_text("20")
    (cgroup / "memory.current").write_text("30")
    assert linux_available_memory(proc, cgroup) == 0


@pytest.mark.parametrize("membership", ["2:memory:/\n", "0::/../outside\n", "0::/missing\n"])
def test_unmeasurable_hierarchy_fails_closed(resources, membership):
    proc, cgroup = resources
    (proc / "self/cgroup").write_text(membership)
    with pytest.raises((RuntimeError, FileNotFoundError)):
        linux_available_memory(proc, cgroup)


def test_process_memory_retains_whole_process_peak_bytes(resources):
    proc, _ = resources
    (proc / "self/status").write_text("VmRSS: 21 kB\nVmHWM: 34 kB\n")
    result = linux_process_memory(proc)
    assert result["supported"] and result["resident_bytes"] == 21 * 1024
    assert result["peak_resident_bytes"] == 34 * 1024
