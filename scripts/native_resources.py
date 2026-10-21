"""Linux memory measurements for disposable native fixtures, not resource limits."""

from __future__ import annotations

from pathlib import Path


def _kib_fields(path: Path) -> dict[str, int]:
    result = {}
    for line in path.read_text(encoding="ascii").splitlines():
        name, _, value = line.partition(":")
        parts = value.split()
        if len(parts) == 2 and parts[1] == "kB":
            result[name] = int(parts[0]) * 1024
    return result


def linux_available_memory(proc: Path = Path("/proc"),
                           cgroup: Path = Path("/sys/fs/cgroup")) -> int:
    """Read host availability and every visible cgroup-v2 ancestor's headroom.

    A cgroup-v1 hierarchy is unsupported: fail before allocating a large fixture
    rather than reporting host RAM as the process's available budget. This is a
    point-in-time measurement, not a reservation or a constrained-memory test.
    """
    available = _kib_fields(proc / "meminfo")["MemAvailable"]
    memberships = (proc / "self/cgroup").read_text(encoding="ascii").splitlines()
    if len(memberships) != 1 or not memberships[0].startswith("0::/"):
        raise RuntimeError("Native fixture requires a measurable cgroup-v2 memory hierarchy")
    relative = Path(memberships[0][4:])
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("Invalid native fixture cgroup membership")
    root = cgroup.resolve(strict=True)
    current = (root / relative).resolve(strict=True)
    if not current.is_relative_to(root):
        raise RuntimeError("Native fixture cgroup membership escapes its hierarchy")
    for folder in (current, *current.parents):
        limit_file = folder / "memory.max"
        if limit_file.exists():
            limit = limit_file.read_text(encoding="ascii").strip()
            if limit != "max":
                used = int((folder / "memory.current").read_text(encoding="ascii"))
                available = min(available, max(0, int(limit) - used))
        if folder == root:
            break
    return available


def linux_process_memory(proc: Path = Path("/proc")) -> dict[str, object]:
    fields = _kib_fields(proc / "self/status")
    return {"supported": True, "resident_bytes": fields["VmRSS"],
            "peak_resident_bytes": fields["VmHWM"],
            "scope": "Whole isolated Blender process lifetime; Linux procfs RSS/high-water mark, not a cap or attribution"}
