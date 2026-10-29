from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def native_save_large_root(runner, monkeypatch, tmp_path):
    source = tmp_path / "source"
    for name in runner.NATIVE_SAVE_LARGE_SOURCES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# native save runner composition model\n")
    monkeypatch.setattr(runner, "ROOT", source)
    output = tmp_path / "output"
    output.mkdir()
    binary = tmp_path / "blender binary"
    binary.write_bytes(b"modeled executable, never launched")
    return output, binary


def native_save_large_resources():
    return {"scope": "LINUX_HOST_AND_VISIBLE_CGROUP_V2", "available_memory_bytes": 12 * 1024**3,
        "host_available_memory_bytes": 16 * 1024**3, "visible_cgroup_headroom_bytes": 12 * 1024**3,
        "visible_cgroup_levels": 2, "disk_free_bytes": 4 * 1024**3, "aggregate_image_pixels": 16_777_216,
        "required_memory_bytes": 8 * 1024**3, "required_disk_bytes": 2 * 1024**3, "measurement_is_reservation": False}


def native_save_large_model(runner, command, environment, *, build="d13f752e3b9c"):
    """Receipt composition model only; no large image or Blender is allocated."""
    report = Path(command[command.index("--bridge-report") + 1])
    sources = runner._native_save_sources()
    version = {"d13f752e3b9c": "5.2.2", "62c1db4208e8": "4.5.14 LTS"}[build]
    canonical = json.dumps(sources, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    full = {"schema": "native_save_large_fixture_v1", "profile": "NATIVE_SAVE_CLEAN_PACKED_4K_V1", "completed": True,
        "process_instance": environment["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": 77, "source_build": build,
        "blender_version": version, "source_fingerprints": sources,
        "source_snapshot_sha256": runner.hashlib.sha256(canonical).hexdigest(),
        "binary": {"path": str(Path(command[0]).resolve()), "sha256": runner._native_save_file(Path(command[0]), 1024**3)[0]},
        "real_queued_loopback": True, "manual_ticks": False, "direct_dispatch": False,
        "external_source_folder_unavailable": True, "parent_identity_preserved": True,
        "declared_authored_projection_preserved": True, "full_4k_dirty_generated_qualified": False, "windows_qualified": False,
        "phase_timeout_seconds": 300, "phase_elapsed_seconds": 20.,
        "source_peak_memory": {"available": True, "metric": "ru_maxrss", "scope": "RUSAGE_SELF",
                               "value": 2048, "unit": "KiB", "platform": "linux"},
        "image": {"width": 4096, "height": 4096, "channels": 4, "components": 67_108_864,
            "colorspace": "sRGB", "alpha_mode": "STRAIGHT", "packed_bytes": 64 * 1024**2,
            "packed_sha256": "a" * 64, "pixels_sha256_float32_le": "b" * 64},
        "low_resource_native_qualified": False,
        "assertions": dict.fromkeys(runner.NATIVE_SAVE_LARGE_CASES, True), "rows": []}
    def receipt(index, succeeded=True):
        value = {"schema": "native_save_reader_receipt_v1", "status": "succeeded" if succeeded else "failed",
            "token": f"{index:032x}", "process_id": 100 + index, "blender_version": version, "build_hash": build,
            "saved_sha256": "c" * 64, "projection_sha256": "d" * 64,
            "actual_projection_sha256": "d" * 64 if succeeded else "e" * 64,
            "program": {name: sources["addon/blender_codex_bridge/" + name]
                        for name in ("native_save_reader.py", "native_save_profile.py")},
            "native_open_invoked": True, "native_open_completed": True, "declared_projection_reopened": succeeded,
            "source_process_contacted": False, "source_restore_writes": 0, "reader_project_save_invoked": False,
            "native_effect_inventory_complete": False, "timings": {"worker_elapsed_seconds": 2., "native_open_seconds": .2,
                "projection_seconds": 1.}, "peak_memory": {"available": True, "metric": "ru_maxrss", "scope": "RUSAGE_SELF",
                    "value": 1024, "unit": "KiB", "platform": "linux"},
            "resource_checks": [{"phase": phase, "facts": native_save_large_resources()} for phase in
                ("before_open", "before_packed_decode", "before_packed_decode", "before_capture")],
            "error": None if succeeded else {"code": "NATIVE_SAVE_READER_FAILED", "type": "ValueError", "failure_stage": "projection_compare"}}
        if not succeeded:
            value.update(native_open_invoked=False, native_open_completed=False, actual_projection_sha256=None,
                         error={"code": "NATIVE_SAVE_READER_FAILED", "type": "ValueError", "failure_stage": "input_validation"})
            value["timings"].update(native_open_seconds=None, projection_seconds=None)
            value.pop("resource_checks")
        return value
    for index, case in enumerate(sorted(runner.NATIVE_SAVE_LARGE_CASES), 1):
        if case in {"permission_denial", "manual_drift"}:
            job = {"ok": False, "error": {"code": "PERMISSION_DENIED" if case == "permission_denial" else "OPERATION_FAILED"}}
            if case == "manual_drift":
                job["error"]["context"] = {"reason": "SOURCE_CHANGED"}
        else:
            job = {"state": "SUCCEEDED" if case in {"success_copy", "save_as", "save_current", "replace"} else "FAILED",
                   "terminal": True, "result": None}
        row = {"case": case, "job": job}
        if case == "manual_drift":
            row.update(manual_preserved=True, native_entry_invoked=False)
        if job.get("state") == "SUCCEEDED":
            job["result"] = {"fresh_process_reopen_verified": True, "declared_source_verified": True,
                             "native_save_interval_ms": 10., "reader_evidence": receipt(index)}
            row["source_resources"] = [native_save_large_resources()]
        elif case == "reader_failure":
            failed = receipt(index, False)
            row["reader_evidence"] = {"worker_receipt": failed}
            row["injection"] = {"injected": True, "kind": "owned_expected_json_single_space",
                                **{key: failed[key] for key in ("process_id", "token", "saved_sha256", "projection_sha256")}}
        full["rows"].append(row)
    compact = {key: full[key] for key in ("schema", "profile", "completed", "process_instance", "process_id", "source_build",
        "blender_version", "source_snapshot_sha256", "binary")}
    return report, full, compact


def write_native_save_large_model(runner, report, full, compact, *, raw=None):
    data = json.dumps(full).encode() if raw is None else raw
    report.write_bytes(data)
    compact["full_receipt"] = {"path": str(report), "bytes": len(data), "sha256": runner.hashlib.sha256(data).hexdigest()}


@pytest.mark.parametrize("requested_timeout", [10, 1200])
@pytest.mark.parametrize("build", ["62c1db4208e8", "d13f752e3b9c"])
@pytest.mark.parametrize("failure_stage", ["input_validation", "expected_projection"])
def test_large_native_save_requires_one_owned_interactive_process_and_bound_complete_receipt(
        runner, monkeypatch, tmp_path, requested_timeout, build, failure_stage):
    output, binary = native_save_large_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setenv("NATIVE_SAVE_LARGE_UNWANTED", "not-a-secret")
    monkeypatch.setenv("PYTHONPATH", "/unrelated/python")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert "--background" not in command and "--bridge-phase" not in command
        assert command.count("--disable-autoexec") == command.count("--bridge-large") == 1
        assert command[-4:] == ["--", "--bridge-large", "--bridge-report", str(Path(kwargs["env"]["TEMP"]) / "native-save-large-evidence.json")]
        assert command.index("--python-expr") < command.index("--python")
        assert kwargs["timeout"] == min(requested_timeout, 300)
        environment = kwargs["env"]
        assert "NATIVE_SAVE_LARGE_UNWANTED" not in environment and "PYTHONPATH" not in environment
        temporary = Path(environment["TEMP"])
        assert temporary.stat().st_mode & 0o777 == 0o700 and kwargs["cwd"] == temporary / "working"
        assert all(Path(environment[key]).is_relative_to(temporary) for key in
                   ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"))
        report, full, compact = native_save_large_model(runner, command, environment, build=build)
        failed = next(row for row in full["rows"] if row["case"] == "reader_failure")
        failed["reader_evidence"]["worker_receipt"]["error"]["failure_stage"] = failure_stage
        write_native_save_large_model(runner, report, full, compact)
        kwargs["stdout"].write((runner.CASES["native_project_saving_large"][1] + json.dumps(compact)).encode())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    case = "native_project_saving_large"
    assert case in runner.OPT_IN_CASES & runner.INTERACTIVE_CASES and case not in runner.PHASED_CASES
    result = runner.run_case(binary, case, output, requested_timeout)
    assert len(calls) == 1 and result["status"] == "passed" and result["execution_mode"] == "interactive_display"
    assert result["qualification_scope"]["full_project_or_H01_or_1_0_qualified"] is False


@pytest.mark.parametrize("stage,phase_count,valid", [
    (stage, count, count in allowed) for stage, allowed in {
        "build_validation": {None}, "program_validation": {None}, "input_validation": {None}, "runtime_validation": {None},
        "expected_projection": {None, 0, 1}, "reader_preferences": {1}, "native_open": {1},
        "image_preload": {1, 2, 3}, "projection_capture": {3, 4}, "projection_compare": {4}, "final_input_validation": {4},
    }.items() for count in (None, 0, 1, 2, 3, 4)
])
def test_failed_large_reader_resource_prefix_matches_actual_failure_stage(runner, monkeypatch, tmp_path, stage, phase_count, valid):
    _output, binary = native_save_large_root(runner, monkeypatch, tmp_path)
    _report, full, _compact = native_save_large_model(runner,
        [str(binary), "--bridge-report", str(tmp_path / "report.json")], {"BRIDGE_TEST_PROCESS_TOKEN": "a" * 32})
    success = next(row for row in full["rows"] if row["job"].get("state") == "SUCCEEDED")
    receipt = json.loads(json.dumps(success["job"]["result"]["reader_evidence"]))
    before_open = stage in {"build_validation", "program_validation", "input_validation", "runtime_validation",
                            "expected_projection", "reader_preferences"}
    completed = not before_open and stage != "native_open"
    receipt.update(status="failed", native_open_invoked=not before_open, native_open_completed=completed,
        declared_projection_reopened=False, actual_projection_sha256="e" * 64 if stage in {"projection_compare", "final_input_validation"} else None,
        error={"code": "NATIVE_SAVE_READER_FAILED", "type": "ValueError", "failure_stage": stage})
    receipt["timings"].update(native_open_seconds=None if before_open else .2, projection_seconds=1. if completed else None)
    if phase_count is None:
        receipt.pop("resource_checks")
    else:
        phases = ("before_open", "before_packed_decode", "before_packed_decode", "before_capture")
        receipt["resource_checks"] = [{"phase": phase, "facts": native_save_large_resources()} for phase in phases[:phase_count]]
    assert runner._native_save_reader_receipt(receipt, full, full["source_fingerprints"], succeeded=False) is valid


@pytest.mark.parametrize("fault", ["profile", "schema", "token", "pid_bool", "build", "version", "source", "source_drift",
    "binary", "binary_drift", "missing_report", "symlink", "fifo", "path", "hash", "size_bool", "oversize", "partial",
    "duplicate", "nonfinite", "overflow_float", "compact_duplicate", "duplicate_marker", "manual_ticks", "direct_dispatch", "no_loopback", "external", "identity", "projection",
    "windows", "dirty_claim", "small_dimensions", "component_count", "packed_old_limit", "pixel_hash", "missing_case",
    "duplicate_case", "false_assertion", "missing_reader", "reader_pid", "reader_program", "reader_digest", "reader_reused",
    "reader_failed", "reader_phases", "reader_memory", "reader_disk", "reader_effective_memory", "source_resources",
    "denial", "manual_lost", "manual_native_entry", "manual_wrong_error", "low_resource_claim", "reader_partial",
    "reader_bad_peak", "cancel_succeeded", "missing_failure_receipt", "foreign_failure_receipt", "failure_stage",
    "failure_before_open", "failure_open_flag", "failure_timing", "failure_missing_projection", "failure_resources",
    "failure_extra_field", "missing_source_peak", "source_peak_bool", "source_peak_foreign", "phase_limit", "phase_limit_bool",
    "phase_elapsed_bool", "phase_elapsed_long", "interval_missing", "interval_bool", "interval_long", "injection_missing",
    "injection_false", "injection_kind", "injection_pid", "injection_token", "injection_saved", "injection_projection",
    "injection_other_error", "small_marker", "exit", "timeout"])
def test_large_native_save_rejects_unbound_partial_foreign_or_nonqueued_evidence(runner, monkeypatch, tmp_path, fault):
    output, binary = native_save_large_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    def run(command, **kwargs):
        report, full, compact = native_save_large_model(runner, command, kwargs["env"])
        successes = [row for row in full["rows"] if row["job"].get("state") == "SUCCEEDED"]
        reader = successes[0]["job"]["result"]["reader_evidence"]
        rows = {row["case"]: row for row in full["rows"]}
        compact_faults = {"profile": "profile", "schema": "schema", "token": "process_instance", "pid_bool": "process_id",
                          "build": "source_build", "version": "blender_version", "binary": "binary"}
        if fault in compact_faults:
            compact[compact_faults[fault]] = True if fault == "pid_bool" else "foreign"
        elif fault == "source":
            full["source_fingerprints"] = {}
        elif fault in {"manual_ticks", "direct_dispatch", "windows", "dirty_claim"}:
            full[{"windows": "windows_qualified", "dirty_claim": "full_4k_dirty_generated_qualified"}.get(fault, fault)] = True
        elif fault in {"no_loopback", "external", "identity", "projection"}:
            full[{"no_loopback": "real_queued_loopback", "external": "external_source_folder_unavailable",
                  "identity": "parent_identity_preserved", "projection": "declared_authored_projection_preserved"}[fault]] = False
        elif fault == "small_dimensions":
            full["image"]["width"] = 2
        elif fault == "component_count":
            full["image"]["components"] -= 1
        elif fault == "packed_old_limit":
            full["image"]["packed_bytes"] = 20 * 1024**2
        elif fault == "pixel_hash":
            full["image"]["pixels_sha256_float32_le"] = "not-a-digest"
        elif fault == "missing_case":
            full["rows"].pop()
        elif fault == "duplicate_case":
            full["rows"][-1] = full["rows"][0]
        elif fault == "false_assertion":
            full["assertions"]["replace"] = False
        elif fault == "missing_reader":
            successes[0]["job"]["result"].pop("reader_evidence")
        elif fault == "reader_pid":
            reader["process_id"] = full["process_id"]
        elif fault == "reader_program":
            reader["program"]["native_save_reader.py"] = "a" * 64
        elif fault == "reader_digest":
            reader["actual_projection_sha256"] = "f" * 64
        elif fault == "reader_reused":
            successes[1]["job"]["result"]["reader_evidence"] = reader
        elif fault == "reader_failed":
            reader["status"] = "failed"
        elif fault == "reader_phases":
            reader["resource_checks"].pop()
        elif fault == "reader_memory":
            reader["resource_checks"][0]["facts"]["available_memory_bytes"] = 1
        elif fault == "reader_disk":
            reader["resource_checks"][0]["facts"]["disk_free_bytes"] = 1
        elif fault == "reader_effective_memory":
            reader["resource_checks"][0]["facts"]["visible_cgroup_headroom_bytes"] = 1
        elif fault == "source_resources":
            successes[0]["source_resources"] = []
        elif fault == "denial":
            rows["permission_denial"]["job"]["error"]["code"] = "NOT_IMPLEMENTED"
        elif fault == "manual_lost":
            rows["manual_drift"]["manual_preserved"] = False
        elif fault == "manual_native_entry":
            rows["manual_drift"]["native_entry_invoked"] = True
        elif fault == "manual_wrong_error":
            rows["manual_drift"]["job"]["error"]["context"]["reason"] = "FOREIGN"
        elif fault == "low_resource_claim":
            full["low_resource_native_qualified"] = True
        elif fault == "reader_partial":
            reader.pop("peak_memory")
        elif fault == "reader_bad_peak":
            reader["peak_memory"]["value"] = True
        elif fault == "missing_source_peak":
            full.pop("source_peak_memory")
        elif fault == "source_peak_bool":
            full["source_peak_memory"]["value"] = True
        elif fault == "source_peak_foreign":
            full["source_peak_memory"]["scope"] = "RUSAGE_CHILDREN"
        elif fault == "phase_limit":
            full["phase_timeout_seconds"] = 1200
        elif fault == "phase_limit_bool":
            full["phase_timeout_seconds"] = True
        elif fault == "phase_elapsed_bool":
            full["phase_elapsed_seconds"] = False
        elif fault == "phase_elapsed_long":
            full["phase_elapsed_seconds"] = 300.001
        elif fault == "interval_missing":
            successes[0]["job"]["result"].pop("native_save_interval_ms")
        elif fault == "interval_bool":
            successes[0]["job"]["result"]["native_save_interval_ms"] = False
        elif fault == "interval_long":
            successes[0]["job"]["result"]["native_save_interval_ms"] = 300_001.
        elif fault == "cancel_succeeded":
            rows["cancel"]["job"]["state"] = "SUCCEEDED"
        elif fault == "missing_failure_receipt":
            rows["reader_failure"].pop("reader_evidence")
        elif fault == "foreign_failure_receipt":
            rows["reader_failure"]["reader_evidence"]["worker_receipt"]["build_hash"] = "foreign"
        elif fault == "injection_missing":
            rows["reader_failure"].pop("injection")
        elif fault in {"injection_false", "injection_kind", "injection_pid", "injection_token", "injection_saved", "injection_projection"}:
            key = {"injection_false": "injected", "injection_kind": "kind", "injection_pid": "process_id",
                "injection_token": "token", "injection_saved": "saved_sha256", "injection_projection": "projection_sha256"}[fault]
            rows["reader_failure"]["injection"][key] = False if fault == "injection_false" else "foreign"
        elif fault == "injection_other_error":
            rows["reader_failure"]["reader_evidence"]["worker_receipt"]["error"]["type"] = "RuntimeError"
        elif fault.startswith("failure_"):
            failed = rows["reader_failure"]["reader_evidence"]["worker_receipt"]
            if fault == "failure_stage":
                failed["error"]["failure_stage"] = "foreign"
            elif fault == "failure_before_open":
                failed.update(native_open_invoked=True, native_open_completed=True, actual_projection_sha256="e" * 64)
                failed["error"]["failure_stage"] = "projection_compare"
                failed["timings"].update(native_open_seconds=.2, projection_seconds=1.)
                failed["resource_checks"] = [{"phase": phase, "facts": native_save_large_resources()} for phase in
                    ("before_open", "before_packed_decode", "before_packed_decode", "before_capture")]
            elif fault == "failure_open_flag":
                failed["native_open_invoked"] = True
            elif fault == "failure_timing":
                failed["timings"]["native_open_seconds"] = .2
            elif fault == "failure_missing_projection":
                failed["actual_projection_sha256"] = "e" * 64
            elif fault == "failure_resources":
                failed["resource_checks"] = []
            elif fault == "failure_extra_field":
                failed["foreign"] = True
        raw = None
        if fault == "partial":
            raw = b'{"completed":'
        elif fault == "duplicate":
            raw = json.dumps(full).encode()[:-1] + b',"completed":true}'
        elif fault == "nonfinite":
            full["untrusted"] = float("nan")
        elif fault == "overflow_float":
            raw = json.dumps(full).encode()[:-1] + b',"untrusted":1e999}'
        write_native_save_large_model(runner, report, full, compact, raw=raw)
        if fault == "source_drift":
            (runner.ROOT / runner.NATIVE_SAVE_LARGE_SOURCES[-1]).write_text("# changed source\n")
        elif fault == "binary_drift":
            binary.write_bytes(b"changed executable")
        elif fault == "missing_report":
            report.unlink()
        elif fault == "symlink":
            target = report.with_suffix(".other")
            report.rename(target)
            report.symlink_to(target)
        elif fault == "fifo":
            report.unlink()
            runner.os.mkfifo(report)
        elif fault == "path":
            compact["full_receipt"]["path"] += ".foreign"
        elif fault == "hash":
            compact["full_receipt"]["sha256"] = "0" * 64
        elif fault == "size_bool":
            compact["full_receipt"]["bytes"] = True
        elif fault == "oversize":
            compact["full_receipt"]["bytes"] = 8 * 1024**2 + 1
        marker = runner.CASES["native_project_saving" if fault == "small_marker" else "native_project_saving_large"][1]
        compact_raw = json.dumps(compact)
        if fault == "compact_duplicate":
            compact_raw = compact_raw[:-1] + ',"completed":true}'
        line = marker + compact_raw
        kwargs["stdout"].write((line + ("\n" + line if fault == "duplicate_marker" else "")).encode())
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, 300)
        return SimpleNamespace(returncode=1 if fault == "exit" else 0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(binary, "native_project_saving_large", output, 1200)
    assert result["status"] == ("timeout" if fault == "timeout" else "failed")


@pytest.mark.parametrize("fault", [None, "no_pressure", "too_much_pressure", "still_above_floor", "unsafe_floor",
    "fake_effective_memory", "wrong_error", "native_entry", "false_qualification", "bool_qualification"])
def test_large_native_save_optional_pressure_evidence_requires_actual_bounded_low_resources(runner, monkeypatch, tmp_path, fault):
    output, binary = native_save_large_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    def run(command, **kwargs):
        report, full, compact = native_save_large_model(runner, command, kwargs["env"])
        before, pressured = native_save_large_resources(), native_save_large_resources()
        before["available_memory_bytes"] = before["visible_cgroup_headroom_bytes"] = 8 * 1024**3 + 512 * 1024**2
        pressured["available_memory_bytes"] = pressured["visible_cgroup_headroom_bytes"] = 7 * 1024**3 + 512 * 1024**2
        row = {"case": "low_resource", "before_resources": before, "pressured_resources": pressured,
            "pressure_bytes": 1024**3, "native_entry_invoked": False,
            "job": {"ok": False, "error": {"code": "NOT_IMPLEMENTED", "context": {"reason": "LARGE_IMAGE_MEMORY_BUDGET"}}}}
        full["low_resource_native_qualified"] = True
        full["rows"].append(row)
        full["assertions"]["low_resource"] = True
        if fault == "no_pressure":
            row["pressure_bytes"] = 0
        elif fault == "too_much_pressure":
            row["pressure_bytes"] = 2 * 1024**3 + 1
        elif fault == "still_above_floor":
            pressured["available_memory_bytes"] = pressured["visible_cgroup_headroom_bytes"] = 8 * 1024**3
        elif fault == "unsafe_floor":
            pressured["available_memory_bytes"] = pressured["visible_cgroup_headroom_bytes"] = 6 * 1024**3 - 1
        elif fault == "fake_effective_memory":
            pressured["host_available_memory_bytes"] = 1
        elif fault == "wrong_error":
            row["job"]["error"]["context"]["reason"] = "FOREIGN"
        elif fault == "native_entry":
            row["native_entry_invoked"] = True
        elif fault == "false_qualification":
            full["low_resource_native_qualified"] = False
        elif fault == "bool_qualification":
            full["low_resource_native_qualified"] = 1
        write_native_save_large_model(runner, report, full, compact)
        kwargs["stdout"].write((runner.CASES["native_project_saving_large"][1] + json.dumps(compact)).encode())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    row = runner.run_case(binary, "native_project_saving_large", output, 1200)
    assert row["status"] == ("passed" if fault is None else "failed")


def test_native_save_report_regular_to_fifo_swap_is_nonblocking_and_refused(runner, monkeypatch, tmp_path):
    path = tmp_path / "report.json"
    path.write_bytes(b"{}")
    original = runner.os.open
    def changed(name, flags):
        assert flags & runner.os.O_NONBLOCK
        path.unlink()
        runner.os.mkfifo(path)
        return original(name, flags)
    # Restore the process-wide os.open before tmp_path's retention cleanup.
    with monkeypatch.context() as scoped:
        scoped.setattr(runner.os, "open", changed)
        with pytest.raises(ValueError, match="changed before read"):
            runner._native_save_file(path, 1024, capture=True)


def test_large_native_save_is_never_a_default_even_with_interactive(runner, monkeypatch, tmp_path):
    binary = tmp_path / "blender"
    binary.write_bytes(b"not launched")
    monkeypatch.setattr(runner.sys, "argv", ["run_blender_checks", "--blender", str(binary), "--output", str(tmp_path / "evidence"),
                                            "--include-interactive"])
    monkeypatch.setattr(runner, "git_value", lambda *_args: "")
    calls = []
    def run_case(_binary, case, _output, _timeout):
        calls.append(case)
        return {"case": case, "status": "passed"}
    monkeypatch.setattr(runner, "run_case", run_case)
    assert runner.main() == 0
    assert "native_project_saving_large" not in calls and "native_project_saving" in calls


def census_fixture_root(runner, monkeypatch, tmp_path):
    source = tmp_path / "source"
    for name in ("scripts/blender_current_pixels_lifecycle_smoke.py", "scripts/run_blender_checks.py",
                 "addon/blender_codex_bridge/current_pixels_graph.py"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# source-only runner composition model\n")
    monkeypatch.setattr(runner, "ROOT", source)
    output = tmp_path / "output"
    output.mkdir()
    return output


def census_model_receipt(runner, command, environment):
    report = Path(command[command.index("--bridge-report") + 1])
    sources = {str(path.relative_to(runner.ROOT)): runner.hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(runner.ROOT.rglob("*.py"))}
    canonical = json.dumps(sources, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    full = {"completed": True, "profile": "RNA_CENSUS_ONLY_V1", "scope": "class_metadata_only",
            "lifecycle_functional_acceptance": False, "windows_qualified": False,
            "process_instance": environment["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": 77,
            "blender_version": "5.2.2", "source_build": "d13f752e3b9c",
            "source_fingerprints": sources, "source_snapshot_sha256": runner.hashlib.sha256(canonical).hexdigest(),
            "catalog": {"schema": "current_pixels_complete_class_census_v1", "build_hash": "d13f752e3b9c",
                        "classes": {name: {"present": False} for name in sorted(runner.CURRENT_PIXELS_CENSUS_CLASSES)}}}
    compact = {key: value for key, value in full.items() if key not in {"source_fingerprints", "catalog"}}
    return report, full, compact


def write_census_model(runner, report, full, compact):
    data = json.dumps(full).encode()
    report.write_bytes(data)
    compact["full_receipt"] = {"path": str(report), "bytes": len(data),
                               "sha256": runner.hashlib.sha256(data).hexdigest()}


@pytest.mark.parametrize("requested_timeout", [10, 1200])
def test_census_uses_owned_opt_in_headless_process_and_complete_receipt(runner, monkeypatch, tmp_path, requested_timeout):
    output = census_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setenv("CENSUS_UNWANTED", "not-a-secret")
    monkeypatch.setenv("PYTHONPATH", "/unrelated/python")

    def run(command, **kwargs):
        assert all(flag in command for flag in ("--background", "--factory-startup", "--disable-autoexec", "--bridge-census-only"))
        assert command.count("--disable-autoexec") == command.count("--bridge-census-only") == 1
        assert kwargs["timeout"] == min(requested_timeout, 300)
        environment = kwargs["env"]
        assert "CENSUS_UNWANTED" not in environment and "PYTHONPATH" not in environment
        temporary = Path(environment["TEMP"])
        assert temporary.stat().st_mode & 0o777 == 0o700
        assert kwargs["cwd"] == temporary / "working"
        assert all(Path(environment[key]).is_relative_to(temporary) for key in
                   ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES", "XDG_RUNTIME_DIR"))
        report, full, compact = census_model_receipt(runner, command, environment)
        write_census_model(runner, report, full, compact)
        kwargs["stdout"].write((runner.CASES["current_pixels_lifecycle_census"][1] + json.dumps(compact)).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    case = "current_pixels_lifecycle_census"
    assert len(runner.CURRENT_PIXELS_CENSUS_CLASSES) == 57
    assert case in runner.OPT_IN_CASES and case not in runner.INTERACTIVE_CASES | set(runner.PHASED_CASES)
    result = runner.run_case(Path("blender"), case, output, requested_timeout)
    assert result["status"] == "passed" and result["execution_mode"] == "background"
    assert result["qualification_scope"]["lifecycle_functional_acceptance"] is False


@pytest.mark.parametrize("fault", ["profile", "token", "pid", "build", "version", "lifecycle", "windows",
    "missing_file", "symlink", "path", "hash", "size_bool", "oversize", "full_token", "full_false_integer", "source", "source_drift",
    "catalog_schema", "catalog_build", "catalog_count", "catalog_names", "old52", "extra58", "truncated", "exit", "timeout",
    *[f"{mode}:{name}" for mode in ("omit_nested", "substitute_nested") for name in
      ("TexMapping", "ColorMapping", "ColorRamp", "ColorRampElement", "ColorRampElements")]])
def test_census_refuses_unbound_incomplete_or_non_metadata_evidence(runner, monkeypatch, tmp_path, fault):
    output = census_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")

    def run(command, **kwargs):
        report, full, compact = census_model_receipt(runner, command, kwargs["env"])
        if fault == "full_token":
            full["process_instance"] = "b" * 32
        elif fault == "full_false_integer":
            full["lifecycle_functional_acceptance"] = 0
        elif fault == "source":
            full["source_fingerprints"] = {}
        elif fault in {"catalog_schema", "catalog_build"}:
            full["catalog"]["schema" if fault == "catalog_schema" else "build_hash"] = "foreign"
        elif fault == "catalog_count":
            full["catalog"]["classes"].pop("Image")
        elif fault == "catalog_names":
            full["catalog"]["classes"]["ForeignImage"] = full["catalog"]["classes"].pop("Image")
        elif fault == "old52":
            for name in ("TexMapping", "ColorMapping", "ColorRamp", "ColorRampElement", "ColorRampElements"):
                full["catalog"]["classes"].pop(name)
        elif fault == "extra58":
            full["catalog"]["classes"]["UnapprovedClass"] = {"present": False}
        elif fault.startswith(("omit_nested:", "substitute_nested:")):
            mode, name = fault.split(":", 1)
            removed = full["catalog"]["classes"].pop(name)
            if mode == "substitute_nested":
                full["catalog"]["classes"]["Foreign" + name] = removed
        write_census_model(runner, report, full, compact)
        if fault in {"profile", "token", "pid", "build", "version", "lifecycle", "windows"}:
            key = {"token": "process_instance", "pid": "process_id", "build": "source_build",
                   "version": "blender_version", "lifecycle": "lifecycle_functional_acceptance",
                   "windows": "windows_qualified"}.get(fault, fault)
            compact[key] = True if fault in {"pid", "lifecycle", "windows"} else "foreign"
        elif fault == "missing_file":
            report.unlink()
        elif fault == "symlink":
            target = report.with_suffix(".other")
            report.rename(target)
            report.symlink_to(target)
        elif fault == "path":
            compact["full_receipt"]["path"] = str(report.parent / "foreign.json")
        elif fault == "hash":
            compact["full_receipt"]["sha256"] = "0" * 64
        elif fault == "size_bool":
            compact["full_receipt"]["bytes"] = True
        elif fault == "oversize":
            compact["full_receipt"]["bytes"] = 2 * 1024 * 1024 + 1
        elif fault == "source_drift":
            (runner.ROOT / "addon/blender_codex_bridge/current_pixels_graph.py").write_text("# changed after receipt\n")
        elif fault == "truncated":
            report.write_bytes(b'{"incomplete":')
            compact["full_receipt"].update(bytes=report.stat().st_size, sha256=runner.hashlib.sha256(report.read_bytes()).hexdigest())
        kwargs["stdout"].write((runner.CASES["current_pixels_lifecycle_census"][1] + json.dumps(compact)).encode())
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, 300)
        return SimpleNamespace(returncode=1 if fault == "exit" else 0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), "current_pixels_lifecycle_census", output, 1200)
    assert result["status"] == ("timeout" if fault == "timeout" else "failed")


def graph_fixture_root(runner, monkeypatch, tmp_path):
    output = census_fixture_root(runner, monkeypatch, tmp_path)
    (runner.ROOT / "addon/blender_codex_bridge/current_pixels_source.py").write_text("# source origin model\n")
    return output


def graph_model_receipt(runner, command, environment):
    """Runner receipt model only; never native graph or source acceptance."""
    report, full, _compact = census_model_receipt(runner, command, environment)
    full.pop("catalog")
    full.update(profile="CURRENT_PIXELS_NATIVE_SOURCE_GRAPH_V1", scope="native_source_graph_read_only",
        current_pixels_origin_qualified=False,
        assertions=dict.fromkeys(runner.CURRENT_PIXELS_GRAPH_ASSERTIONS, True), checks=1,
        foreign_callbacks=0, peak_rss_bytes=1024,
        baseline={"profile": "FILE_F32_EXR_DATA_CURRENT_PIXELS_V1", "complete_pixels_verified": True,
            "snapshot_canonical_packed_verified": True, "original_canonical_packed_verified": True,
            **dict.fromkeys(("native_graph_sha256", "portable_graph_sha256", "full_native_prefix_sha256", "full_portable_prefix_sha256"), "a" * 64)},
        setup={"owned_empty_factory": True, "intentional_manual_edits_separate_from_observation": True,
            "production_files_written": False, "lifecycle_backup_files": []},
        limitations={"current_pixels_origin_qualified": False, "public_tool_acceptance": False,
            "windows_qualified": False, "first_authorization_pixel_only_change_detection": False,
            "trusted_canonical_native_registry": True, "provider_source_refusal_is_owned_probe_guard_only": True},
        full_read_intervals=[{"full_read_seconds": .1, "memory_available": 1024 ** 3, "disk_available": 1024 ** 3}] * 2)
    compact = {key: value for key, value in full.items() if key in {"completed", "profile", "scope", "process_instance",
        "process_id", "blender_version", "source_build", "source_snapshot_sha256", "lifecycle_functional_acceptance",
        "current_pixels_origin_qualified", "windows_qualified"}}
    return report, full, compact


@pytest.mark.parametrize("requested_timeout", [10, 1200])
def test_source_graph_uses_opt_in_owned_process_and_complete_source_bound_receipt(runner, monkeypatch, tmp_path, requested_timeout):
    output = graph_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setenv("SOURCE_GRAPH_UNWANTED", "not-a-secret")
    def run(command, **kwargs):
        assert "--background" in command and command.count("--bridge-source-graph") == 1
        assert "--bridge-census-only" not in command and kwargs["timeout"] == min(requested_timeout, 300)
        environment = kwargs["env"]
        assert "SOURCE_GRAPH_UNWANTED" not in environment
        temporary = Path(environment["TEMP"])
        assert temporary.stat().st_mode & 0o777 == 0o700 and kwargs["cwd"] == temporary / "working"
        report, full, compact = graph_model_receipt(runner, command, environment)
        assert report.name == "current-pixels-source-graph.json"
        write_census_model(runner, report, full, compact)
        kwargs["stdout"].write((runner.CASES["current_pixels_source_graph"][1] + json.dumps(compact)).encode())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    case = "current_pixels_source_graph"
    assert case in runner.OPT_IN_CASES and case not in runner.INTERACTIVE_CASES | set(runner.PHASED_CASES)
    result = runner.run_case(Path("blender"), case, output, requested_timeout)
    assert result["status"] == "passed" and result["execution_mode"] == "background"
    assert result["qualification_scope"]["current_pixels_origin_qualified"] is False


@pytest.mark.parametrize("fault", ["profile", "census", "token", "pid", "build", "version", "lifecycle", "origin", "windows",
    "hash", "path", "missing_file", "source", "source_drift", "missing_source_module", "missing_assertion", "false_assertion",
    "extra_assertion", "unverified_pixels", "digest", "foreign", "no_checks", "rss", "setup_write", "authority_claim",
    "first_window_claim", "unbounded_registry_claim", "no_intervals", "memory", "disk", "timeout", "exit"])
def test_source_graph_refuses_incomplete_or_misrepresented_native_evidence(runner, monkeypatch, tmp_path, fault):
    output = graph_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    def run(command, **kwargs):
        report, full, compact = graph_model_receipt(runner, command, kwargs["env"])
        if fault == "source":
            full["source_fingerprints"] = {}
        elif fault == "missing_assertion":
            full["assertions"].pop("positive_complete_graph")
        elif fault == "false_assertion":
            full["assertions"]["native_owner_refusal"] = False
        elif fault == "extra_assertion":
            full["assertions"]["stable_1_0"] = True
        elif fault == "unverified_pixels":
            full["baseline"]["complete_pixels_verified"] = False
        elif fault == "digest":
            full["baseline"]["full_native_prefix_sha256"] = "not-a-hash"
        elif fault == "foreign":
            full["foreign_callbacks"] = 1
        elif fault == "no_checks":
            full["checks"] = 0
        elif fault == "rss":
            full["peak_rss_bytes"] = True
        elif fault == "setup_write":
            full["setup"]["production_files_written"] = True
        elif fault in {"authority_claim", "first_window_claim", "unbounded_registry_claim"}:
            key = {"authority_claim": "public_tool_acceptance", "first_window_claim": "first_authorization_pixel_only_change_detection",
                   "unbounded_registry_claim": "trusted_canonical_native_registry"}[fault]
            full["limitations"][key] = fault != "unbounded_registry_claim"
        elif fault == "no_intervals":
            full["full_read_intervals"] = []
        elif fault in {"memory", "disk"}:
            full["full_read_intervals"][0]["memory_available" if fault == "memory" else "disk_available"] = 0
        write_census_model(runner, report, full, compact)
        if fault in {"profile", "token", "pid", "build", "version", "lifecycle", "origin", "windows"}:
            key = {"token": "process_instance", "pid": "process_id", "build": "source_build", "version": "blender_version",
                   "lifecycle": "lifecycle_functional_acceptance", "origin": "current_pixels_origin_qualified", "windows": "windows_qualified"}.get(fault, fault)
            compact[key] = True if fault in {"pid", "lifecycle", "origin", "windows"} else "foreign"
        elif fault == "census":
            compact.update(profile="RNA_CENSUS_ONLY_V1", scope="class_metadata_only")
        elif fault == "hash":
            compact["full_receipt"]["sha256"] = "0" * 64
        elif fault == "path":
            compact["full_receipt"]["path"] = str(report.with_name("current-pixels-census.json"))
        elif fault == "missing_file":
            report.unlink()
        elif fault in {"source_drift", "missing_source_module"}:
            source = runner.ROOT / "addon/blender_codex_bridge/current_pixels_source.py"
            if fault == "source_drift":
                source.write_text("# changed after receipt\n")
            else:
                source.unlink()
        kwargs["stdout"].write((runner.CASES["current_pixels_source_graph"][1] + json.dumps(compact)).encode())
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, 300)
        return SimpleNamespace(returncode=1 if fault == "exit" else 0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), "current_pixels_source_graph", output, 1200)
    assert result["status"] == ("timeout" if fault == "timeout" else "failed")
def glb_fixture_root(runner, monkeypatch, tmp_path):
    source = tmp_path / "source with spaces"
    for name in runner.GLB_STAGE_SOURCES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# independent runner input: " + name + "\n")
    binary = source / "blender with spaces"
    binary.write_bytes(b"owned executable witness; never executed by this model")
    monkeypatch.setattr(runner, "ROOT", source)
    output = tmp_path / "output"
    output.mkdir()
    return binary, output


def glb_receipt(runner, binary, environment, *, version=(4, 5, 14), version_text=None, fault=None):
    inputs = runner._glb_stage_inputs(binary)
    proof = {"schema": "glb_stage_constructor_v1", "profile": "GLB_PRIVATE_STAGE_V1", "completed": True,
             "blender_version": version_text or ".".join(map(str, version)) + (" LTS" if version[0] == 4 else ""),
             "version": list(version), "build_hash": runner.GLB_STAGE_BUILDS[version],
             "process_instance": environment["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": 77,
             **inputs,
             "cases": [{"name": name, "status": status} for name, status in (
                 ("success", "CONSTRUCTED"), ("cancel", "STOPPED"), ("owned_change", "STOPPED"),
                 ("invalid_context", "REFUSED_BEFORE_ALLOCATION"))],
             "observations": [{"phase": phase, "elapsed_seconds": elapsed, "preserved": True}
                              for phase, elapsed in (("immediate", 0.), ("timer_0_1", .1), ("timer_0_5", .5))]}
    marker = {key: proof[key] for key in ("schema", "profile", "completed", "blender_version", "version",
                                         "build_hash", "process_instance", "process_id", "source_sha256", "binary")}
    if fault is not None:
        fault(marker, proof)
    raw = (json.dumps(proof, allow_nan=True) + "\n").encode()
    path = Path(environment["TEMP"]) / "glb-stage-evidence.json"
    path.write_bytes(raw)
    marker["evidence_sha256"] = hashlib.sha256(raw).hexdigest()
    return marker, path


@pytest.mark.parametrize("version", [(4, 5, 14), (5, 2, 2)])
@pytest.mark.parametrize("suffix", ["", " LTS"])
def test_glb_constructor_requires_owned_interactive_bound_report(runner, monkeypatch, tmp_path, version, suffix):
    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setenv("GLB_UNWANTED_INHERITED", "not-a-secret")
    monkeypatch.setenv("PYTHONPATH", "/unrelated/python")
    monkeypatch.setenv("BRIDGE_TEST_PRIVATE_UI_MANIFEST", "/owned/display.json")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/owned/runtime")

    def run(command, **kwargs):
        assert "--background" not in command and command.count("--disable-autoexec") == 1
        assert command.index("--python-expr") < command.index("--python")
        assert "--factory-startup" in command and command[command.index("--python-exit-code") + 1] == "1"
        environment = kwargs["env"]
        assert "GLB_UNWANTED_INHERITED" not in environment and "PYTHONPATH" not in environment
        assert environment["BRIDGE_TEST_PRIVATE_UI_MANIFEST"] == "/owned/display.json"
        assert environment["XDG_RUNTIME_DIR"] == "/owned/runtime"
        assert kwargs["cwd"].name == "working" and kwargs["cwd"].parent == Path(environment["TEMP"])
        marker, _path = glb_receipt(runner, binary, environment, version=version,
                                    version_text=".".join(map(str, version)) + suffix)
        kwargs["stdout"].write((runner.CASES["glb_stage_constructor"][1] + json.dumps(marker)).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    assert "glb_stage_constructor" in runner.OPT_IN_CASES & runner.INTERACTIVE_CASES
    assert "glb_stage_constructor" not in runner.PHASED_CASES
    row = runner.run_case(binary, "glb_stage_constructor", output, 10)
    assert row["status"] == "passed" and row["retained_evidence_validation"]["passed"]
    assert row["qualification_scope"]["public_import_qualified"] is False
    assert row["qualification_scope"]["windows_testing_deferred"] is True


@pytest.mark.parametrize("fault", [
    "profile", "schema", "incomplete", "version", "build", "version_text", "instance", "pid", "pid_bool",
    "source_missing", "source_extra", "source_hash", "binary_path", "binary_hash", "retained_identity",
    "retained_pid_bool", "retained_version_float", "missing_case", "duplicate_case", "case_status",
    "missing_timer", "timer_early", "timer_false", "timer_bool", "timer_nan", "timer_huge_int", "immediate_late", "timer_order",
    "missing_report", "digest", "invalid_json", "deep_json", "duplicate_json", "oversize", "symlink", "source_changed",
    "binary_changed", "exit", "timeout",
])
def test_glb_constructor_refuses_unbound_or_incomplete_evidence(runner, monkeypatch, tmp_path, fault):
    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")

    def corrupt(marker, proof):
        if fault in {"profile", "schema", "build", "version_text", "instance"}:
            marker[{"build": "build_hash", "version_text": "blender_version", "instance": "process_instance"}.get(fault, fault)] = "foreign"
        elif fault == "incomplete":
            marker["completed"] = False
        elif fault == "version":
            marker["version"] = [5, 2, 3]
        elif fault in {"pid", "pid_bool"}:
            marker["process_id"] = 0 if fault == "pid" else True
        elif fault.startswith("source_") and fault != "source_changed":
            marker["source_sha256"] = dict(marker["source_sha256"])
            if fault == "source_missing":
                marker["source_sha256"].pop(runner.GLB_STAGE_SOURCES[0])
            elif fault == "source_extra":
                marker["source_sha256"]["foreign.py"] = "0" * 64
            else:
                marker["source_sha256"][runner.GLB_STAGE_SOURCES[0]] = "0" * 64
        elif fault in {"binary_path", "binary_hash"}:
            marker["binary"] = dict(marker["binary"])
            marker["binary"]["path" if fault == "binary_path" else "sha256"] = "foreign"
        elif fault == "retained_identity":
            proof["process_instance"] = "foreign"
        elif fault == "retained_pid_bool":
            proof["process_id"] = True
        elif fault == "retained_version_float":
            proof["version"] = [4., 5., 14.]
        elif fault == "missing_case":
            proof["cases"].pop()
        elif fault == "duplicate_case":
            proof["cases"][-1] = dict(proof["cases"][0])
        elif fault == "case_status":
            proof["cases"][1]["status"] = "CONSTRUCTED"
        elif fault == "missing_timer":
            proof["observations"].pop()
        elif fault == "timer_early":
            proof["observations"][2]["elapsed_seconds"] = .499
        elif fault == "timer_false":
            proof["observations"][1]["preserved"] = False
        elif fault == "timer_bool":
            proof["observations"][1]["elapsed_seconds"] = True
        elif fault == "timer_nan":
            proof["observations"][1]["elapsed_seconds"] = float("nan")
        elif fault == "timer_huge_int":
            proof["observations"][1]["elapsed_seconds"] = 2**4096
        elif fault == "immediate_late":
            proof["observations"][0]["elapsed_seconds"] = .1
        elif fault == "timer_order":
            proof["observations"][1]["elapsed_seconds"] = 1.

    def run(command, **kwargs):
        marker, path = glb_receipt(runner, binary, kwargs["env"], fault=corrupt)
        if fault == "missing_report":
            path.unlink()
        elif fault == "digest":
            marker["evidence_sha256"] = "0" * 64
        elif fault in {"invalid_json", "deep_json", "duplicate_json"}:
            raw = (b"not JSON" if fault == "invalid_json" else b"[" * 10000 + b"0" + b"]" * 10000
                   if fault == "deep_json" else b'{"schema":1,"schema":2}')
            path.write_bytes(raw)
            marker["evidence_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif fault == "oversize":
            monkeypatch.setattr(runner, "GLB_STAGE_MAX_EVIDENCE", path.stat().st_size - 1)
        elif fault == "symlink":
            elsewhere = tmp_path / "foreign-evidence.json"
            path.replace(elsewhere)
            path.symlink_to(elsewhere)
        elif fault == "source_changed":
            (runner.ROOT / runner.GLB_STAGE_SOURCES[2]).write_bytes(b"changed helper after launch")
        elif fault == "binary_changed":
            binary.write_bytes(b"changed executable after launch")
        kwargs["stdout"].write((runner.CASES["glb_stage_constructor"][1] + json.dumps(marker)).encode())
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        return SimpleNamespace(returncode=1 if fault == "exit" else 0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(binary, "glb_stage_constructor", output, 10)
    assert result["status"] == ("timeout" if fault == "timeout" else "failed")
    if fault not in {"exit", "timeout"}:
        assert result["retained_evidence_validation"]["passed"] is False


def test_glb_constructor_missing_pinned_source_prevents_launch(runner, monkeypatch, tmp_path):
    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    (runner.ROOT / runner.GLB_STAGE_SOURCES[2]).unlink()
    monkeypatch.setattr(runner.subprocess, "run", lambda *_a, **_k: pytest.fail("Unbound source was launched"))
    result = runner.run_case(binary, "glb_stage_constructor", output, 10)
    assert result["status"] == "failed" and result["exit_code"] is None


def paired_fixture_root(runner, monkeypatch, tmp_path):
    source = tmp_path / "source"
    scripts = source / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "blender_current_pixels_paired_recovery_smoke.py").write_text("# owned fixture model\n")
    monkeypatch.setattr(runner, "ROOT", source)
    output = tmp_path / "output"
    output.mkdir()
    return output


@pytest.mark.parametrize("case,profile", [
    ("image_current_pixels_paired_recovery", "SMALL2X2"),
    ("image_current_pixels_paired_recovery_large", "LARGE4K"),
])
@pytest.mark.parametrize("requested_timeout", [10, 1200])
def test_paired_recovery_phases_keep_exact_profile_private_environment_and_deadline(
        runner, monkeypatch, tmp_path, case, profile, requested_timeout):
    output = paired_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setenv("PAIRED_FIXTURE_UNWANTED", "not-a-secret")
    monkeypatch.setenv("PYTHONPATH", "/unrelated/python/path")
    monkeypatch.setenv("BRIDGE_TEST_PRIVATE_UI_MANIFEST", "/owned/private-display.json")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/owned/runtime")
    observed = []

    def run(command, **kwargs):
        phase = command[command.index("--bridge-phase") + 1]
        assert command[-2:] == ["--bridge-profile", profile]
        assert command.count("--bridge-profile") == 1
        assert "--background" not in command and command.count("--disable-autoexec") == 1
        assert command.index("--disable-autoexec") < command.index("--python")
        assert kwargs["timeout"] == min(requested_timeout, 300)
        environment = kwargs["env"]
        assert "PAIRED_FIXTURE_UNWANTED" not in environment and "PYTHONPATH" not in environment
        assert environment["BRIDGE_TEST_PRIVATE_UI_MANIFEST"] == "/owned/private-display.json"
        assert environment["XDG_RUNTIME_DIR"] == "/owned/runtime"
        assert kwargs["cwd"].name == "working" and kwargs["cwd"].parent == Path(environment["TEMP"])
        assert all(str(environment[key]).startswith(str(output)) for key in
                   ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"))
        marker = runner.PHASED_CASES[case][0 if phase == "writer" else 1]
        payload = {"blender_version": "5.2.2", "phase": phase, "profile": profile,
                   "process_instance": environment["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": 77}
        kwargs["stdout"].write((marker + json.dumps(payload)).encode())
        observed.append((phase, environment["BRIDGE_TEST_PROCESS_TOKEN"], environment["BLENDER_USER_CONFIG"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    assert case in runner.OPT_IN_CASES & runner.INTERACTIVE_CASES
    result = runner.run_case(Path("blender"), case, output, requested_timeout)
    assert result["status"] == "passed" and result["fresh_process_verified"]
    assert result["phase_sequence"] == ["writer", "reader"]
    assert observed[0][1] != observed[1][1] and observed[0][2] != observed[1][2]


@pytest.mark.parametrize("case", ["image_current_pixels_paired_recovery", "image_current_pixels_paired_recovery_large"])
@pytest.mark.parametrize("fault", ["profile", "missing_profile", "phase", "instance", "pid", "exit", "timeout"])
def test_paired_recovery_refuses_invalid_writer_before_reader(runner, monkeypatch, tmp_path, case, fault):
    output = paired_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    calls = []

    def run(command, **kwargs):
        phase = command[command.index("--bridge-phase") + 1]
        calls.append(phase)
        payload = {"blender_version": "5.2.2", "phase": phase, "profile": runner.PAIRED_RECOVERY_PROFILES[case],
                   "process_instance": kwargs["env"]["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": 77}
        if fault == "missing_profile":
            del payload["profile"]
        elif fault in {"profile", "phase", "instance", "pid"}:
            payload[{"instance": "process_instance", "pid": "process_id"}.get(fault, fault)] = "foreign"
        kwargs["stdout"].write((runner.PHASED_CASES[case][0] + json.dumps(payload)).encode())
        if fault == "timeout":
            raise subprocess.TimeoutExpired(command, 300)
        return SimpleNamespace(returncode=1 if fault == "exit" else 0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), case, output, 1200)
    assert calls == ["writer"] and not result["reader_started"]
    assert result["status"] == ("timeout" if fault == "timeout" else "failed")
    assert not result["fresh_process_verified"]


@pytest.mark.parametrize("case", ["image_current_pixels_paired_recovery", "image_current_pixels_paired_recovery_large"])
def test_paired_recovery_cannot_accept_reader_from_other_profile(runner, monkeypatch, tmp_path, case):
    output = paired_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")

    def run(command, **kwargs):
        phase = command[command.index("--bridge-phase") + 1]
        profile = runner.PAIRED_RECOVERY_PROFILES[case] if phase == "writer" else "FOREIGN"
        payload = {"blender_version": "5.2.2", "phase": phase, "profile": profile,
                   "process_instance": kwargs["env"]["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": 77}
        marker = runner.PHASED_CASES[case][0 if phase == "writer" else 1]
        kwargs["stdout"].write((marker + json.dumps(payload)).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), case, output, 1200)
    assert result["status"] == "failed" and result["reader_started"]
    assert not result["fresh_process_verified"]


@pytest.mark.parametrize("case", ["image_current_pixels_paired_recovery", "image_current_pixels_paired_recovery_large"])
def test_paired_recovery_refuses_unphased_launch(runner, monkeypatch, tmp_path, case):
    output = paired_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("Unphased launch attempted"))
    with pytest.raises(ValueError, match="isolated writer or reader"):
        runner._run_process(Path("blender"), case, output, 1200)


def test_registered_native_save_uses_owned_interactive_sanitized_process(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setenv("NATIVE_SAVE_TEST_UNWANTED", "not-a-secret")

    def run(command, **kwargs):
        assert "--background" not in command and "--disable-autoexec" in command
        assert "NATIVE_SAVE_TEST_UNWANTED" not in kwargs["env"] and "PYTHONPATH" not in kwargs["env"]
        kwargs["stdout"].write(b'BLENDER_NATIVE_PROJECT_SAVING_OK {"blender_version":"5.2.2"}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    assert "native_project_saving" in runner.INTERACTIVE_CASES & runner.OPT_IN_CASES
    assert runner.run_case(Path("blender"), "native_project_saving", tmp_path, 10)["status"] == "passed"


@pytest.fixture
def runner():
    spec = importlib.util.spec_from_file_location(
        "check_runner", ROOT / "scripts/run_blender_checks.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_existing_smokes_are_in_registry(runner):
    assert {filename for filename, _ in runner.CASES.values()} == {
        p.name for p in (ROOT / "scripts").glob("blender_*smoke.py")
    } | {"blender_surface_publication_probe.py", "blender_uv_edit_boundary_probe.py"}


@pytest.mark.parametrize("qualified", [False, True])
def test_populated_geometry_preview_requires_owned_interactive_qualified_variant(runner, monkeypatch, tmp_path, qualified):
    monkeypatch.setattr(runner.sys, "platform", "linux")
    case = "geometry_preview_populated_protection"
    assert case in runner.OPT_IN_CASES & runner.INTERACTIVE_CASES and case not in runner.PHASED_CASES

    def run(command, **kwargs):
        assert "--background" not in command and "--disable-autoexec" in command
        assert command[-2:] == ["--", "--bridge-populated-protection"]
        assert command.count("--bridge-populated-protection") == 1
        assert kwargs["env"]["BLENDER_USER_CONFIG"].startswith(str(tmp_path))
        assert kwargs["env"]["BRIDGE_TEST_PROCESS_TOKEN"]
        kwargs["stdout"].write((runner.CASES[case][1] + json.dumps({
            "blender_version": "5.2.2", "variant": "populated_data_baseline",
            "populated_protected_data_baseline_qualified": qualified})).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    row = runner.run_case(Path("blender"), case, tmp_path, 10)
    assert row["status"] == ("passed" if qualified else "failed")
    assert row["qualification_scope"]["selected_fields"] == ["mesh_geometry", "material_slots", "animation"]
    assert row["qualification_scope"]["full_H02_F04_or_protected_object_qualified"] is False


@pytest.mark.parametrize("case", [
    "core", "undo_lifecycle", "camera_focus", "curve_sampling", "surface_publication_probe", "sculpt_mask",
    "character_revision", "artist_target_verification", "artist_target_sidebar", "artist_quaternion_storage", "artist_quaternion",
    "uv_edit_storage", "uv_edit_boundary_probe", "large_surface_paint", "uv_edit_guard", "animation_intent", "weight_edit_guard",
])
def test_factory_fixture_bytecode_prelude_runs_before_script(runner, monkeypatch, tmp_path, case):
    monkeypatch.setattr(runner.sys, "platform", "linux")

    def run(command, **kwargs):
        expression = command.index("--python-expr")
        script = command.index("--python")
        assert expression < script
        assert command[expression + 1] == "import sys; sys.dont_write_bytecode = True"
        assert command[script + 1] == str(ROOT / "scripts" / runner.CASES[case][0])
        assert "--factory-startup" in command
        if case in {"artist_quaternion_storage", "artist_quaternion", "uv_edit_storage", "uv_edit_boundary_probe", "large_surface_paint", "uv_edit_guard", "animation_intent", "weight_edit_guard"}:
            assert command.index("--disable-autoexec") < script
        assert command[command.index("--python-exit-code") + 1] == "1"
        assert ("--background" in command) is (case not in runner.INTERACTIVE_CASES)
        marker = runner.CASES[case][1]
        kwargs["stdout"].write((marker + json.dumps({"blender_version": "5.2.2"})).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.run_case(Path("blender"), case, tmp_path, 10)["status"] == "passed"
    assert "camera_focus" in runner.OPT_IN_CASES and "camera_focus" not in runner.INTERACTIVE_CASES
    assert "curve_sampling" in runner.OPT_IN_CASES and "curve_sampling" not in runner.INTERACTIVE_CASES
    assert "surface_publication_probe" in runner.OPT_IN_CASES and "surface_publication_probe" not in runner.INTERACTIVE_CASES
    assert "sculpt_mask" in runner.OPT_IN_CASES and "sculpt_mask" not in runner.INTERACTIVE_CASES
    assert "character_revision" in runner.OPT_IN_CASES and "character_revision" not in runner.INTERACTIVE_CASES
    assert "artist_target_verification" in runner.OPT_IN_CASES and "artist_target_verification" not in runner.INTERACTIVE_CASES
    assert "artist_target_sidebar" in runner.OPT_IN_CASES and "artist_target_sidebar" in runner.INTERACTIVE_CASES
    assert "artist_quaternion_storage" in runner.OPT_IN_CASES and "artist_quaternion_storage" not in runner.INTERACTIVE_CASES
    assert "artist_quaternion" in runner.OPT_IN_CASES and "artist_quaternion" not in runner.INTERACTIVE_CASES
    assert "uv_edit_storage" in runner.OPT_IN_CASES and "uv_edit_storage" not in runner.INTERACTIVE_CASES
    assert "uv_edit_boundary_probe" in runner.OPT_IN_CASES and "uv_edit_boundary_probe" not in runner.INTERACTIVE_CASES
    assert "large_surface_paint" in runner.OPT_IN_CASES and "large_surface_paint" in runner.INTERACTIVE_CASES
    assert "uv_edit_guard" in runner.OPT_IN_CASES and "uv_edit_guard" not in runner.INTERACTIVE_CASES
    assert "animation_intent" in runner.OPT_IN_CASES and "animation_intent" in runner.INTERACTIVE_CASES
    assert "weight_edit_guard" in runner.OPT_IN_CASES and "weight_edit_guard" not in runner.INTERACTIVE_CASES


@pytest.mark.parametrize(
    "text,marker,valid",
    [
        ('OK {"blender":"5.1"}', "OK ", True),
        ('noise\n{"artist_smoke":"PASS","blender":"5.1"}', "artist_smoke", True),
        ('{"artist_smoke":"FAIL"}', "artist_smoke", False),
        ("OK not-json", "OK ", False),
        ("OK []", "OK ", False),
        ("noise OK {}", "OK ", False),
    ],
)
def test_success_marker_is_structured_and_exact(runner, text, marker, valid):
    assert (runner.success_payload(text, marker) is not None) == valid


@pytest.mark.parametrize(
    "code,output,status",
    [
        (0, 'BLENDER_CODEX_SMOKE_OK {"blender_version":"5.1.2"}', "passed"),
        (1, 'BLENDER_CODEX_SMOKE_OK {"blender_version":"5.1.2"}', "failed"),
        (0, "Blender quit", "failed"),
        (0, "BLENDER_CODEX_SMOKE_OK {}", "failed"),
    ],
)
def test_process_success_alone_is_not_evidence(runner, monkeypatch, tmp_path, code, output, status):
    def run(command, **kwargs):
        assert command[1:5] == ["--background", "--factory-startup", "--python-exit-code", "1"]
        assert "shell" not in kwargs
        kwargs["stdout"].write(output.encode())
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender.exe"), "core", tmp_path, 10)
    assert result["status"] == status
    assert len(result["script_sha256"]) == 64
    assert (tmp_path / "core.log").read_text() == output


def test_timeout_retains_failure_even_with_success_marker(runner, monkeypatch, tmp_path):
    def run(command, **kwargs):
        kwargs["stdout"].write(b'BLENDER_CODEX_SMOKE_OK {"blender_version":"5.1.2"}')
        raise subprocess.TimeoutExpired(command, 10)

    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender.exe"), "core", tmp_path, 10)
    assert result["status"] == "timeout" and result["exit_code"] is None


def test_interactive_case_uses_isolated_temporary_recovery(runner, monkeypatch, tmp_path):
    from scripts import windows_test_process

    monkeypatch.setattr(runner.sys, "platform", "win32")
    def run(command, **kwargs):
        assert "--factory-startup" in command and "--background" not in command
        for variable in ("TEMP", "TMP", "TMPDIR", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
            assert Path(kwargs["env"][variable]).is_relative_to(tmp_path)
            assert Path(kwargs["env"][variable]).is_dir()
        kwargs["stdout"].write(b'BLENDER_UNDO_LIFECYCLE_OK {"blender":"5.1.2"}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(windows_test_process, "run_isolated", run)
    monkeypatch.setattr(runner.subprocess, "run", lambda *_a, **_k: pytest.fail("visible fallback"))
    result = runner.run_case(Path("blender.exe"), "undo_lifecycle", tmp_path, 10)
    assert result["status"] == "passed"
    assert result["execution_mode"] == "private_windows_desktop"


def test_private_desktop_failure_never_launches_visible_fallback(runner, monkeypatch, tmp_path):
    from scripts import windows_test_process

    monkeypatch.setattr(runner.sys, "platform", "win32")
    def fail(*args, **kwargs):
        raise OSError("Desktop access denied")
    monkeypatch.setattr(windows_test_process, "run_isolated", fail)
    monkeypatch.setattr(runner.subprocess, "run", lambda *_a, **_k: pytest.fail("visible fallback"))
    result = runner.run_case(Path("blender.exe"), "undo_lifecycle", tmp_path, 10)
    assert result["status"] == "failed" and result["exit_code"] is None
    assert "Desktop access denied" in result["launch_error"]


def test_non_windows_interactive_mode_is_not_claimed_hidden(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner.sys, "platform", "linux")
    def run(command, **kwargs):
        assert "--background" not in command
        assert kwargs["creationflags"] == 0
        kwargs["stdout"].write(b'BLENDER_UNDO_LIFECYCLE_OK {"blender":"5.1.2"}')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), "undo_lifecycle", tmp_path, 10)
    assert result["status"] == "passed"
    assert result["execution_mode"] == "interactive_display"


def test_background_windows_case_cannot_create_console(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner.sys, "platform", "win32")
    monkeypatch.setattr(runner.subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False)
    def run(command, **kwargs):
        assert "--background" in command
        assert kwargs["creationflags"] == 0x8000000
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.run_case(Path("blender.exe"), "core", tmp_path, 10)["status"] == "failed"


def test_phased_case_has_independent_profiles_and_process_instances(runner, monkeypatch, tmp_path):
    profiles = []
    def run(command, **kwargs):
        phase = command[command.index("--bridge-phase") + 1]
        bundle = Path(command[command.index("--bridge-bundle") + 1])
        assert bundle == tmp_path / "image_reopen-bundle"
        if phase == "writer":
            (bundle / "writer.finished").write_text("closed")
        else:
            assert (bundle / "writer.finished").is_file()
        profiles.append({key: kwargs["env"][key] for key in
                         ("TEMP", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES")})
        marker = runner.PHASED_CASES["image_reopen"][0 if phase == "writer" else 1]
        payload = {"blender_version": "5.1.2", "phase": phase, "process_id": 12,
                   "process_instance": kwargs["env"]["BRIDGE_TEST_PROCESS_TOKEN"]}
        kwargs["stdout"].write((marker + json.dumps(payload)).encode())
        assert kwargs["timeout"] == 13
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), "image_reopen", tmp_path, 13)
    assert result["status"] == "passed" and result["fresh_process_verified"]
    assert result["phase_sequence"] == ["writer", "reader"]
    # PID reuse is permitted; the runner's independently issued instances differ.
    assert result["phases"][0]["process_instance"] != result["phases"][1]["process_instance"]
    assert all(profiles[0][key] != profiles[1][key] for key in profiles[0])
    assert {p["log"] for p in result["phases"]} == {
        str(tmp_path / "image_reopen-writer.log"), str(tmp_path / "image_reopen-reader.log")}


@pytest.mark.parametrize("failure", ["timeout", "exit", "marker", "identity"])
def test_failed_writer_never_starts_reader(runner, monkeypatch, tmp_path, failure):
    calls = []
    def run(command, **kwargs):
        phase = command[command.index("--bridge-phase") + 1]
        calls.append(phase)
        payload = {"blender_version": "5.1.2", "phase": phase, "process_id": 99,
                   "process_instance": kwargs["env"]["BRIDGE_TEST_PROCESS_TOKEN"] if failure != "identity" else "wrong"}
        if failure != "marker":
            kwargs["stdout"].write((runner.PHASED_CASES["image_reopen"][0] + json.dumps(payload)).encode())
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        return SimpleNamespace(returncode=1 if failure == "exit" else 0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), "image_reopen", tmp_path, 1)
    assert calls == ["writer"] and not result["reader_started"]
    assert result["status"] == ("timeout" if failure == "timeout" else "failed")
    assert not result["fresh_process_verified"]


def test_phased_version_mismatch_is_failure(runner, monkeypatch, tmp_path):
    def run(command, **kwargs):
        phase = command[command.index("--bridge-phase") + 1]
        marker = runner.PHASED_CASES["image_reopen"][0 if phase == "writer" else 1]
        payload = {"blender_version": "4.5.1" if phase == "writer" else "5.1.2",
                   "phase": phase, "process_id": 99,
                   "process_instance": kwargs["env"]["BRIDGE_TEST_PROCESS_TOKEN"]}
        kwargs["stdout"].write((marker + json.dumps(payload)).encode())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), "image_reopen", tmp_path, 1)
    assert result["status"] == "failed" and not result["fresh_process_verified"]


def glb_structure_model(runner, binary, environment, *, version=(4, 5, 14)):
    """Complete synthetic transcript for validator tests, never native proof."""
    import copy

    from scripts import blender_glb_stage_smoke as fixture

    def identity(name, uid, users=1):
        return {"name": name, "uid": uid, "pointer": uid * 100, "users": users,
                "fake_user": False, "class": name}

    tree = {"identity": identity("ShaderNodeTree", 4), "links": [
        ["ShaderNodeBsdfPrincipled", "BSDF", "ShaderNodeOutputMaterial", "Surface"]], "nodes": [
        {"type": "ShaderNodeBsdfPrincipled", "inputs": [
            {"identifier": key, "default": value} for key, value in {
                "Base Color": fixture.numeric((.25, .5, .75, 1.)), "Metallic": [fixture.bits(.25)],
                "Roughness": [fixture.bits(.75)], "Alpha": [fixture.bits(1.)]}.items()]},
        {"type": "ShaderNodeOutputMaterial", "inputs": [], "active_output": True, "target": "ALL"}]}
    material = {"identity": identity("Material", 3), "color": fixture.numeric((.25, .5, .75, 1.)),
                "backface": True, "use_nodes": True, "tree": tree}
    edges = [[0, 1], [0, 2], [1, 2], [3, 4], [3, 5], [4, 5]]
    attrs = {name: {"domain": domain, "type": kind, "values": values} for name, domain, kind, values in (
        ("position", "POINT", "FLOAT_VECTOR", [fixture.numeric(v) for v in fixture.STRUCTURE_VERTICES]),
        (".edge_verts", "EDGE", "INT32_2D", edges), (".corner_vert", "CORNER", "INT", list(range(6))),
        (".corner_edge", "CORNER", "INT", [0, 2, 1, 3, 5, 4]),
        ("sharp_face", "FACE", "BOOLEAN", [True, True]),
        (".select_vert", "POINT", "BOOLEAN", [True] * 6),
        (".select_edge", "EDGE", "BOOLEAN", [True] * 6),
        (".select_poly", "FACE", "BOOLEAN", [True] * 2),
        ("UVMap", "CORNER", "FLOAT2", [fixture.numeric(v) for v in fixture.STRUCTURE_UVS]),
        ("material_index", "FACE", "INT", [0, 0]),
        ("sharp_edge", "EDGE", "BOOLEAN", [False] * 6),
        ("custom_normal", "CORNER", "INT16_2D", [[100, 200] for _ in range(3)] + [[0, 0] for _ in range(3)]))}
    mesh = {"identity": identity("Mesh", 2, 2), "coordinates": attrs["position"]["values"],
        "corners": [[v, e] for v, e in zip(range(6), [0, 2, 1, 3, 5, 4], strict=True)],
        "faces": [[0, 3, [0, 1, 2], 0, False], [3, 3, [3, 4, 5], 0, False]],
        "edges": edges, "materials": [material["identity"]], "attributes": attrs,
        "has_custom_normals": True, "decoded_normals": [fixture.numeric(v) for v in
            ((.6, -.8, 0.),) * 3 + ((0., -1., 0.),) * 3],
        "uv": {"name": "UVMap", "vectors": attrs["UVMap"]["values"], "active": 0, "render": 0,
               "clone": 0, "stencil": 0, "clone_bound": True, "stencil_bound": True,
               "layer_pointer": 1234, "clone_pointer": 1234, "stencil_pointer": 1234,
               "active_flag": True, "render_flag": True, "clone_flag": True}}
    rows = {"collection": {"identity": identity("Collection", 1, 0), "children": [], "objects": [5, 6, 7]},
            "mesh:0": mesh, "material:0": material, "node_tree:0": tree}
    for index in range(3):
        channels = {name: fixture.numeric((0., 0., 0.)) for name in fixture.CHANNELS}
        channels.update(location=fixture.numeric(((2., -4., 3.), (1., 0., 0.), (0., 0., 1.))[index]),
            scale=fixture.numeric(((1., 1., 2.), (-1., 1., 1.), (0., 1., 1.))[index]),
            rotation_quaternion=fixture.numeric(((0., 0., 1., 0.), (1., 0., 0., 0.), (1., 0., 0., 0.))[index]))
        matrix = fixture.numeric(fixture.structure_matrix(fixture.STRUCTURE_BASIS[index]))
        rows[f"object:{index}"] = {"identity": identity("Object", 5 + index), "channels": channels,
            "rotation_mode": "QUATERNION", "parent_type": "OBJECT", "parent_uid": None if index == 0 else 5,
            "children": [6, 7] if index == 0 else [], "data_uid": None if index == 0 else 2,
            "type": "EMPTY" if index == 0 else "MESH", "collections": [1],
            "basis": matrix, "matrix": matrix, "local": matrix, "world": matrix,
            "parent_inverse": fixture.numeric(float(i % 5 == 0) for i in range(16))}
    proof = {"schema": fixture.STRUCTURE_SCHEMA, "profile": fixture.STRUCTURE_PROFILE,
        "completed": True, "blender_version": ".".join(map(str, version)) + " LTS", "version": list(version),
        "build_hash": runner.GLB_STAGE_BUILDS[version], "process_instance": environment["BRIDGE_TEST_PROCESS_TOKEN"],
        "process_id": 77, **runner._glb_stage_inputs(binary), "direct_private_controller": True,
        "queued_or_public_request": False, "project_saved": False, "destination_published": False,
        "native_failure_injected": False, "canonical_cancel_guaranteed": False, "cases": [], "observations": []}
    for name in fixture.STRUCTURE_CASES:
        stage = "model-only-" + name
        current_mesh = copy.deepcopy(mesh)
        current_mesh["materials"] = []
        current_mesh["identity"]["users"] = 0
        current_mesh["attributes"].pop("material_index")
        footprint_mesh = copy.deepcopy(current_mesh)
        if name == "cancel_after_uv":
            current_mesh["attributes"].pop("custom_normal")
            current_mesh["attributes"].pop("sharp_edge")
            current_mesh.update(has_custom_normals=False, decoded_normals=None)
        before = copy.deepcopy(current_mesh)
        if name == "encoded_short_drift":
            current_mesh["attributes"]["custom_normal"]["values"][0][0] += 1
        operations = [] if name == "invalid_context" else ["BUILD_MESH", "NEW_UV_LAYER"]
        if name in {"success", "encoded_short_drift"}:
            operations.append("WRITE_NORMALS")
        receipts = [{"operation": operation, "stage_id": stage, "role": "mesh:0", "capture_returned": True,
            "captured_before_generic_callback": True, "queued_stop_during_capture_qualified": False,
            "body_sha256": fixture.structure_digest(fixture.structure_body(footprint_mesh))} for operation in operations]
        entry_rows = [] if name == "invalid_context" else [
            ("NEW_COLLECTION", "collection", "collections.new"), ("NEW_MESH", "mesh:0", "meshes.new")]
        if entry_rows:
            entry_rows.extend(("BUILD_MESH", "mesh:0", entry) for entry in (
                "MeshVertices.add", "MeshLoops.add", "MeshPolygons.add", "vertices.foreach_set:co",
                "polygons.foreach_set:loop_start", "polygons.foreach_set:vertices", "polygons.foreach_set:use_smooth",
                "Mesh.update", "mesh_return.complete_read_attempt"))
            entry_rows.extend(("NEW_UV_LAYER", "mesh:0", entry) for entry in ("UVLoopLayers.new", "mesh_return.complete_read_attempt"))
            if version[:2] == (5, 2):
                entry_rows.extend(("UV_ROLE", "mesh:0", "Mesh." + role) for role in ("uv_layer_clone", "uv_layer_stencil"))
            entry_rows.append(("WRITE_UV", "mesh:0", "uv.foreach_set:vector"))
            if name != "cancel_after_uv":
                entry_rows.extend(("WRITE_NORMALS", "mesh:0", entry) for entry in (
                    "Mesh.normals_split_custom_set", "mesh_return.complete_read_attempt"))
            if name == "success":
                entry_rows.append(("NEW_MATERIAL", "material:0", "materials.new"))
                if version[:2] == (4, 5):
                    entry_rows.append(("INIT_MATERIAL", "material:0", "Material.use_nodes"))
                entry_rows.extend(("WRITE_PBR", "material:0", entry) for entry in (
                    "Material.diffuse_color", "Material.use_backface_culling", "NodeSocketColor.default_value",
                    "NodeSocketFloat.default_value", "NodeSocketFloat.default_value", "NodeSocketFloat.default_value"))
                entry_rows.extend([("BIND_MATERIALS", "mesh:0", "IDMaterials.append"),
                    ("BIND_MATERIALS", "mesh:0", "polygons.foreach_set:material_index")])
                entry_rows.extend(entry for index in range(3) for entry in (
                    ("NEW_OBJECT", f"object:{index}", "objects.new"),
                    ("LINK_OBJECT", "collection", "CollectionObjects.link")))
                entry_rows.extend(("OBJECT_FIELD", f"object:{index}", "Object." + field)
                    for index in range(3) for field in ("rotation_mode", "location", "scale"))
                entry_rows.extend([("OBJECT_FIELD", "object:0", "Object.rotation_quaternion"),
                    ("OBJECT_FIELD", "object:1", "Object.parent"), ("OBJECT_FIELD", "object:2", "Object.parent")])
        entries = [{"operation": operation, "role": role, "entry": entry,
                    "seconds": .001, "returned": True, "interruptible": False} for operation, role, entry in entry_rows]
        case = {"name": name, "status": "CONSTRUCTED" if name == "success" else
                "REFUSED_BEFORE_ALLOCATION" if name == "invalid_context" else "STOPPED",
            "stage_id": stage, "source_proof": {"file_bytes": len(fixture.structure_source_glb()),
                "file_sha256": hashlib.sha256(fixture.structure_source_glb()).hexdigest(), "source_write_performed": False,
                "filepath": "/owned/structure-input.glb", "approved_source_directory": "/owned", "file_identity": [1, 2, 3, 4]},
            "preservation_before": {"environment": {}, "sentinel": {}, "home": {"path": "/owned/home"}, "filepath": "",
                "dirty": True, "scene_pointer": 100, "layer_pointer": 200, "factory_objects": [{}, {}, {}],
                "nonowned_ids": [["objects", {"uid": 500 + index}] for index in range(3)], "window_pointers": [1, 2, 3]},
            "context_case": "declared_destination_witness_mismatch", "invalid_mode_or_volume_native_qualified": False,
            "native": {"build": {"version": proof["version"], "build_hash": proof["build_hash"]},
                       "native_entries": entries, "mesh_return_receipts": receipts,
                       "native_storage_effects": {"scope": "NEW_OWNED_PRIVATE_CONSTRUCTOR_STORAGE",
                           "implicit_selection_layers": [".select_vert", ".select_edge", ".select_poly"],
                           "attribute_data_reads_may_materialize_storage": True,
                           "blender_5_2_SINGLE_materialization_in_scope": version[:2] == (5, 2),
                           "single_materialization_observed": False,
                           "artist_read_only_inspection_qualified": False,
                           "representation_level_passivity_qualified": False}},
            "owned_rows": copy.deepcopy(rows) if name == "success" else {} if name == "invalid_context" else {"mesh:0": current_mesh},
            "retained": {"state": {"phase": "CONSTRUCTED" if name == "success" else "UNKNOWN"},
                         "native_cleanup_performed": False}, "error": None if name == "success" else {"context": {"cause": {"context": {"reason": "PRIVATE_OWNED_PREFIX_CHANGED"}}}},
            "action": {"fired": name not in {"success", "invalid_context"}, "private_validation_hook": True,
                       "native_entries": len(entries), "before_mesh": before, "after_mesh": current_mesh}}
        case["preservation_after"] = copy.deepcopy(case["preservation_before"])
        case["oracles"] = {**fixture.verify_structure_rows(rows), "preservation": True} if name == "success" else {
            "preservation": True, "zero_native_allocation" if name == "invalid_context" else
            "private_cancel_after_uv" if name == "cancel_after_uv" else "exact_encoded_short_cas_refusal": True}
        if name in {"success", "encoded_short_drift"}:
            body = fixture.structure_body(footprint_mesh)
            case["normal_return_footprint"] = {"mesh": footprint_mesh, "body": body,
                "body_sha256": fixture.structure_digest(body), "exact_future_cas": True}
        proof["cases"].append(case)
    proof["observations"] = [{"phase": phase, "elapsed_seconds": elapsed, "preserved": True,
        "real_timer_callback": phase != "immediate", "snapshot": {"owned": [copy.deepcopy(row["owned_rows"]) for row in proof["cases"]],
            "preservation": copy.deepcopy(proof["cases"][0]["preservation_before"])}}
        for phase, elapsed in fixture.STRUCTURE_OBSERVATIONS]
    return proof


def glb_structure_launch(runner, monkeypatch, binary, *, fault=None, version=(4, 5, 14)):
    def launch(command, **kwargs):
        assert "--background" not in command and "--bridge-glb-structure" in command
        assert "--disable-autoexec" in command and kwargs["cwd"].name == "working"
        proof = glb_structure_model(runner, binary, kwargs["env"], version=version)
        if fault is not None:
            fault(proof)
        raw = (json.dumps(proof) + "\n").encode()
        (Path(kwargs["env"]["TEMP"]) / "glb-stage-structure-evidence.json").write_bytes(raw)
        marker = {key: proof[key] for key in ("schema", "profile", "completed", "blender_version", "version",
            "build_hash", "process_instance", "process_id", "source_sha256", "binary")}
        marker["evidence_sha256"] = hashlib.sha256(raw).hexdigest()
        kwargs["stdout"].write((runner.CASES["glb_stage_structure"][1] + json.dumps(marker) + "\n").encode())
        return SimpleNamespace(pid=77, returncode=0, wait=lambda **_kw: 0)
    monkeypatch.setattr(runner.subprocess, "Popen", launch)


@pytest.mark.parametrize("version", [(4, 5, 14), (5, 2, 2)])
def test_glb_structure_is_distinct_owned_pid_bound_opt_in(runner, monkeypatch, tmp_path, version):
    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    glb_structure_launch(runner, monkeypatch, binary, version=version)
    assert "glb_stage_structure" in runner.OPT_IN_CASES & runner.INTERACTIVE_CASES
    assert runner.CASES["glb_stage_constructor"][1] != runner.CASES["glb_stage_structure"][1]
    row = runner.run_case(binary, "glb_stage_structure", output, 10)
    assert row["status"] == "passed" and row["process_id"] == 77
    assert row["retained_evidence_validation"]["passed"] is True
    assert row["qualification_scope"]["profile"] == "GLB_PRIVATE_STRUCTURE_V1"
    assert row["qualification_scope"]["public_import_qualified"] is False


@pytest.mark.parametrize("fault", ["status_only", "pid", "profile", "source", "case_order", "missing_uv",
    "encoded_short", "normal", "auto", "world", "parent", "footprint", "callback", "timer_middle",
    "timer_early", "snapshot", "preservation", "entry_return", "entry_nan", "receipt_before_callback",
    "extra_native_after_stop", "cancel_before_uv", "drift_not_changed", "invalid_allocated", "canonical_claim",
    "entry_incomplete", "success_error", "snapshot_empty", "future_short_drift", "source_asset", "nonowned_missing", "inactive_output", "output_target"])
def test_glb_structure_complete_transcript_countermodels_fail(runner, monkeypatch, tmp_path, fault):
    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")

    def corrupt(proof):
        success, cancel, drift, invalid = proof["cases"]
        mesh = success["owned_rows"]["mesh:0"]
        if fault in {"inactive_output", "output_target"}:
            import copy

            output_node = next(node for node in success["owned_rows"]["node_tree:0"]["nodes"]
                               if node["type"] == "ShaderNodeOutputMaterial")
            output_node["active_output" if fault == "inactive_output" else "target"] = False if fault == "inactive_output" else "CYCLES"
            for sample in proof["observations"]:
                sample["snapshot"]["owned"][0] = copy.deepcopy(success["owned_rows"])
        elif fault == "source_asset":
            success["source_proof"]["file_sha256"] = "0" * 64
        elif fault == "nonowned_missing":
            success["preservation_before"]["nonowned_ids"] = []
        elif fault == "entry_incomplete":
            success["native"]["native_entries"].pop(0)
        elif fault == "success_error":
            success["error"] = {"unexpected": True}
        elif fault == "snapshot_empty":
            for sample in proof["observations"]:
                sample["snapshot"] = {}
        elif fault == "future_short_drift":
            mesh["attributes"]["custom_normal"]["values"][0][0] += 1
        elif fault == "status_only":
            proof["cases"] = [{"name": row["name"], "status": row["status"]} for row in proof["cases"]]
        elif fault == "pid":
            proof["process_id"] = 999
        elif fault == "profile":
            proof["profile"] = "GLB_PRIVATE_STAGE_V1"
        elif fault == "source":
            proof["source_sha256"] = {}
        elif fault == "case_order":
            proof["cases"].reverse()
        elif fault == "missing_uv":
            mesh["attributes"].pop("UVMap")
        elif fault == "encoded_short":
            mesh["attributes"]["custom_normal"]["values"][0][0] = True
        elif fault in {"normal", "auto"}:
            mesh["decoded_normals"][0 if fault == "normal" else 3] = ["00000000"] * 3
        elif fault == "world":
            success["owned_rows"]["object:1"]["basis"][3] = "00000000"
        elif fault == "parent":
            success["owned_rows"]["object:2"]["parent_uid"] = None
        elif fault == "footprint":
            success["normal_return_footprint"]["body_sha256"] = "0" * 64
        elif fault == "callback":
            proof["observations"][1]["real_timer_callback"] = False
        elif fault == "timer_middle":
            proof["observations"].pop(2)
        elif fault == "timer_early":
            proof["observations"][2]["elapsed_seconds"] = .29
        elif fault == "snapshot":
            proof["observations"][3]["snapshot"] = {}
        elif fault == "preservation":
            cancel["preservation_after"] = {}
        elif fault == "entry_return":
            success["native"]["native_entries"][0]["returned"] = False
        elif fault == "entry_nan":
            success["native"]["native_entries"][0]["seconds"] = float("nan")
        elif fault == "receipt_before_callback":
            success["native"]["mesh_return_receipts"][-1]["captured_before_generic_callback"] = False
        elif fault == "extra_native_after_stop":
            drift["action"]["native_entries"] -= 1
        elif fault == "cancel_before_uv":
            cancel["action"]["after_mesh"]["uv"] = None
        elif fault == "drift_not_changed":
            drift["action"]["before_mesh"] = drift["action"]["after_mesh"]
        elif fault == "invalid_allocated":
            invalid["native"]["native_entries"] = success["native"]["native_entries"][:1]
        elif fault == "canonical_claim":
            proof["canonical_cancel_guaranteed"] = True

    glb_structure_launch(runner, monkeypatch, binary, fault=corrupt)
    row = runner.run_case(binary, "glb_stage_structure", output, 10)
    assert row["status"] == "failed" and row["retained_evidence_validation"]["passed"] is False


@pytest.mark.parametrize("fault", ["duplicate_marker", "duplicate_marker_key", "non_utf8", "missing_marker",
    "report_symlink", "report_fifo", "source_drift", "binary_drift", "digest_drift", "report_duplicate_key",
    "report_oversize", "exit_nonzero", "timeout"])
def test_glb_structure_refuses_launch_file_marker_and_process_faults(runner, monkeypatch, tmp_path, fault):
    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    glb_structure_launch(runner, monkeypatch, binary)
    launch = runner.subprocess.Popen
    killed = []

    def corrupt(command, **kwargs):
        process = launch(command, **kwargs)
        log = kwargs["stdout"]
        log.flush()
        report = Path(kwargs["env"]["TEMP"]) / "glb-stage-structure-evidence.json"
        if fault == "duplicate_marker":
            log.write(Path(log.name).read_bytes())
        elif fault == "duplicate_marker_key":
            raw = Path(log.name).read_bytes().replace(b'{"schema":', b'{"schema":"foreign","schema":', 1)
            log.seek(0)
            log.write(raw)
            log.truncate()
        elif fault == "non_utf8":
            log.write(b"\xff")
        elif fault == "missing_marker":
            log.seek(0)
            log.truncate()
        elif fault == "report_symlink":
            target = report.with_suffix(".elsewhere")
            report.replace(target)
            report.symlink_to(target)
        elif fault == "report_fifo":
            report.unlink()
            runner.os.mkfifo(report)
        elif fault == "source_drift":
            (runner.ROOT / runner.GLB_STAGE_SOURCES[3]).write_bytes(b"changed immutable product")
        elif fault == "binary_drift":
            binary.write_bytes(b"changed executable")
        elif fault == "digest_drift":
            report.write_bytes(report.read_bytes() + b" ")
        elif fault == "report_duplicate_key":
            raw = report.read_bytes().replace(b'{"schema":', b'{"schema":"foreign","schema":', 1)
            report.write_bytes(raw)
            marker = json.loads(Path(log.name).read_bytes().split(b" ", 1)[1])
            marker["evidence_sha256"] = hashlib.sha256(raw).hexdigest()
            log.seek(0)
            log.write((runner.CASES["glb_stage_structure"][1] + json.dumps(marker)).encode())
            log.truncate()
        elif fault == "report_oversize":
            monkeypatch.setattr(runner, "GLB_STAGE_MAX_EVIDENCE", report.stat().st_size - 1)
        elif fault == "exit_nonzero":
            process.returncode = 1
        elif fault == "timeout":
            calls = []
            def wait(**_kwargs):
                calls.append(True)
                if len(calls) == 1:
                    raise subprocess.TimeoutExpired(command, 10)
                return 1
            process.wait = wait
            process.kill = lambda: killed.append(True)
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", corrupt)
    row = runner.run_case(binary, "glb_stage_structure", output, 10)
    assert row["status"] == ("timeout" if fault == "timeout" else "failed")
    if fault == "timeout":
        assert killed == [True]


def test_glb_evidence_descriptor_replacement_is_bounded_and_detected(runner, monkeypatch, tmp_path):
    path = tmp_path / "receipt"
    path.write_bytes(b"original ordinary bytes")
    original_open, original_read = runner.os.open, runner.os.read
    reads = []
    def opened(path, flags, *args, **kwargs):
        assert flags & runner.os.O_NONBLOCK and flags & runner.os.O_NOFOLLOW
        return original_open(path, flags, *args, **kwargs)
    def replaced(descriptor, count):
        value = original_read(descriptor, count)
        if not reads:
            reads.append(True)
            other = path.with_suffix(".replacement")
            other.write_bytes(b"different ordinary file")
            other.replace(path)
        return value
    # Restore process-wide os bindings before pytest tears down tmp_path.
    with monkeypatch.context() as patch:
        patch.setattr(runner.os, "open", opened)
        patch.setattr(runner.os, "read", replaced)
        with pytest.raises(ValueError, match="GLB_STAGE_FILE_CHANGED"):
            runner._glb_stage_file(path, 100, retain=True)


@pytest.mark.parametrize("payload", [[1], "truthy non-object", 1, True], ids=["list", "string", "integer", "boolean"])
def test_glb_structure_nonobject_marker_retains_failed_row(runner, monkeypatch, tmp_path, payload):
    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    glb_structure_launch(runner, monkeypatch, binary)
    launch = runner.subprocess.Popen

    def nonobject(command, **kwargs):
        process = launch(command, **kwargs)
        log = kwargs["stdout"]
        log.seek(0)
        log.write((runner.CASES["glb_stage_structure"][1] + json.dumps(payload) + "\n").encode())
        log.truncate()
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", nonobject)
    row = runner.run_case(binary, "glb_stage_structure", output, 10)
    assert row["status"] == "failed" and row["evidence"] is None
    assert row["marker_validation_error"] == "GLB_STRUCTURE_MARKER_INVALID"
    assert row["retained_evidence_validation"]["passed"] is False
    retained = output / "retained-failed-row.json"
    retained.write_text(json.dumps(row))
    assert json.loads(retained.read_text())["case"] == "glb_stage_structure"


@pytest.mark.parametrize("name", [".select_vert", ".select_edge", ".select_poly"])
@pytest.mark.parametrize("fault", ["missing", "domain", "type", "short", "long", "integer", "false", "unknown"])
def test_glb_structure_selection_storage_countermodels_fail_independent_oracle(
    runner, monkeypatch, tmp_path, name, fault,
):
    import copy

    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    def corrupt(proof):
        attributes = proof["cases"][0]["owned_rows"]["mesh:0"]["attributes"]
        item = attributes[name]
        if fault == "missing":
            attributes.pop(name)
        elif fault == "domain":
            item["domain"] = "CORNER"
        elif fault == "type":
            item["type"] = "INT"
        elif fault == "short":
            item["values"].pop()
        elif fault == "long":
            item["values"].append(True)
        elif fault == "integer":
            item["values"][-1] = 1
        elif fault == "false":
            item["values"][-1] = False
        else:
            attributes[name + "_unqualified"] = attributes.pop(name)
        # Rebind every deferred observation: the independent literal oracle,
        # rather than an unrelated snapshot mismatch, must reject this edit.
        for sample in proof["observations"]:
            sample["snapshot"]["owned"][0] = copy.deepcopy(proof["cases"][0]["owned_rows"])
    glb_structure_launch(runner, monkeypatch, binary, fault=corrupt)
    result = runner.run_case(binary, "glb_stage_structure", output, 10)
    assert result["status"] == "failed"
    assert result["retained_evidence_validation"]["reason"] == "GLB_STRUCTURE_TRANSCRIPT_INVALID"


@pytest.mark.parametrize("fault", ["missing", "read_only_claim", "passivity_claim", "single_materialization_hidden", "single_observation_fabricated"])
def test_glb_structure_native_data_read_effects_are_explicitly_private_constructor_storage(
    runner, monkeypatch, tmp_path, fault,
):
    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    def corrupt(proof):
        report = proof["cases"][0]["native"]
        if fault == "missing":
            report.pop("native_storage_effects")
        elif fault == "read_only_claim":
            report["native_storage_effects"]["artist_read_only_inspection_qualified"] = True
        elif fault == "passivity_claim":
            report["native_storage_effects"]["representation_level_passivity_qualified"] = True
        elif fault == "single_materialization_hidden":
            report["native_storage_effects"]["attribute_data_reads_may_materialize_storage"] = False
        else:
            report["native_storage_effects"]["single_materialization_observed"] = True
    glb_structure_launch(runner, monkeypatch, binary, fault=corrupt)
    result = runner.run_case(binary, "glb_stage_structure", output, 10)
    assert result["status"] == "failed" and result["retained_evidence_validation"]["passed"] is False


def glb_runtime_model(runner, binary, environment, *, version=(4, 5, 14)):
    """Complete synthetic validator input; this is never a native receipt."""
    import copy

    from scripts import blender_glb_stage_runtime_smoke as runtime_fixture
    from scripts import blender_glb_stage_smoke as structure

    legacy = glb_structure_model(runner, binary, environment, version=version)
    rows = copy.deepcopy(legacy["cases"][0]["owned_rows"])
    protected = {"objects": [copy.deepcopy(rows["object:0"])], "meshes": [copy.deepcopy(rows["mesh:0"])],
        "materials": [copy.deepcopy(rows["material:0"])],
        "armatures": [{"identity": {"uid": 81}, "bones": []}],
        "actions": [{"identity": {"uid": 82}, "slots": [], "layers": []}],
        "scenes": [{"identity": {"uid": 83}, "unit_settings": ["NONE", 1.], "frame": [1, 0.], "world_uid": None, "camera_uid": None,
            "root_children": [84], "view_layers": [{"name": "ViewLayer", "objects": [1]}]}],
        "images": [{"identity": {"uid": 85}, "source": "FILE", "type": "IMAGE", "has_data": True}],
        "cameras": [{"identity": {"uid": 86}, "type": "PERSP", "lens": 50.}],
        "lights": [{"identity": {"uid": 87}, "type": "POINT", "energy": 1000.}],
        "worlds": [{"identity": {"uid": 88}, "color": [], "use_nodes": False, "tree": None}],
        "collections": [{"identity": {"uid": 84}, "children": [], "objects": []}]}
    baseline = {"protected": protected, "context": {"scene": 83, "view_layer": "ViewLayer", "active": None,
        "selected": [], "mode": "OBJECT", "areas": []}, "scene_edges": [[83, 84]], "owned": {}}
    inputs = runner._glb_stage_inputs(binary, runtime=True)
    proof = {key: copy.deepcopy(legacy[key]) for key in ("blender_version", "version", "build_hash", "process_instance", "process_id", "binary")}
    proof.update(schema=runtime_fixture.SCHEMA, profile=runtime_fixture.PROFILE, completed=True,
        source_sha256=inputs["source_sha256"], project_saved=False, direct_private_controller=False,
        manual_job_ticks=False, evaluated_world_qualified=False, source_write_performed=False,
        protected_observer_const_read_qualified=False, protected_observer_logical_profile_ready=True,
        preservation_contract="LOGICAL_AUTHORED_BITS_WITH_DECLARED_READ_EFFECTS_V1", hidden_layout_or_cache_passivity_claimed=False,
        single_storage_refusals=[], raw_storage_preparations=[], tcp=[], cases=[], observations=[])
    proof["runtime"] = {"host": "127.0.0.1", "port": 12345, "registered": True, "canonical_queue": True,
        "main_thread_executor": True, "runtime_identity": 1001, "registry_identity": 1002, "executor_identity": 1003,
        "process_id": proof["process_id"], "process_instance": proof["process_instance"], "source_sha256": proof["source_sha256"]}
    def call(row, method, result=None, *, ok=True, params=None):
        identifier = "model_"+str(len(proof["tcp"]))
        response = {"id": identifier, "ok": ok, "result" if ok else "error": result or ({"code": "REFUSED"} if not ok else {})}
        proof["tcp"].append({"index": len(proof["tcp"]), "host": "127.0.0.1", "port": 12345, "runtime_group": 0 if row["id"] in runtime_fixture.SCENARIOS[:2] else 1,
            "connection_instance": "c"*32, "request": {"id": identifier, "method": method,
                "params": params or {}, "protocol_version": "1.0"}, "response": response,
            "sent_at": 1., "received_at": 2., "delivered": True,
            "runtime_receipt": {"origin": "CANONICAL_SERVER_REQUEST_LIFETIME", "connection_identity": 9001,
                "delivered": True, "rejected": False, "disconnected": False, "deadline": 10., "observed_at": 2., "expired_without_delivery": False}})
        row["requests"].append(identifier)
        row["history"].append({"request_id": identifier, "method": method, "checkpoint_entered": False, "handler_entered": ok})
        return identifier
    def refusal(row, label):
        identifier = call(row, "asset.glb_stage_create_start", ok=False)
        row["witness"].setdefault("refusals", []).append({"label": label, "request_id": identifier,
            "before_native_identities": [["objects", 1]], "after_native_identities": [["objects", 1]]})
    for name in runtime_fixture.SCENARIOS:
        row = {"id": name, "status": "VERIFIED", "requests": [], "witness": {}, "before": copy.deepcopy(baseline),
            "after": copy.deepcopy(baseline), "native": {"native_entries": [], "owned_reference_roles": [], "footprint_complete": False}, "history": []}
        proof["cases"].append(row)
        if name == "TCP_SUCCESS_STAGE":
            row["after"]["owned"] = copy.deepcopy(rows)
            row["native"] = {"native_entries": [{"index": 0, "operation": "WRITE_NORMALS", "role": "mesh:0", "entry": "Mesh.normals_split_custom_set", "entered": True, "returned": True,
                "post_return_stop_checked": True, "seconds": .001}], "owned_reference_roles": list(rows), "footprint_complete": True}
            body = copy.deepcopy(legacy["cases"][0]["normal_return_footprint"]["body"])
            sha = structure.structure_digest(body)
            row["native"]["mesh_return_receipts"] = [{"operation": "WRITE_NORMALS", "role": "mesh:0", "capture_returned": True,
                "captured_before_generic_callback": True, "body_sha256": sha}]
            row["witness"] = {"source_sha256": hashlib.sha256(runtime_fixture.literal_source()).hexdigest(),
                "normal_source_loop_count": 3, "auto_normal_loop_count": 3,
                "normal_return_footprint": {"scope": "PURE_CACHED_RETURN_FRAME_OBSERVATION", "operation": "WRITE_NORMALS", "role": "mesh:0", "body": body, "body_sha256": sha}}
            call(row, "asset.glb_stage_preview", {"required_accepted_losses": runtime_fixture.LOSSES})
            call(row, "asset.glb_stage_create_start", {"accepted": True, "job_completed": False, "stage_id": "glb_stage_"+"a"*32}, params={"accepted_losses": runtime_fixture.LOSSES})
            call(row, "jobs.inspect", {"state": "SUCCEEDED"})
            call(row, "asset.glb_stage_inspect", {"phase": "CONSTRUCTED", "publication_observed": False, "stage_id": "glb_stage_"+"a"*32})
        elif name == "TCP_SUCCESS_PUBLISH":
            row["after"]["owned"] = copy.deepcopy(rows)
            row["after"]["owned"]["collection"]["identity"]["users"] = 1
            edge = [83, rows["collection"]["identity"]["uid"]]
            row["after"]["scene_edges"] = sorted([*row["before"]["scene_edges"], edge])
            row["witness"]["published_edge"] = edge
            call(row, "asset.glb_stage_publish_start", {"accepted": True})
            call(row, "jobs.inspect", {"state": "SUCCEEDED"})
            call(row, "asset.glb_stage_inspect", {"publication_observed": True})
        elif name == "PERMISSION_AND_TOOLSET":
            for label in [*("create_"+v for v in runtime_fixture.CREATE_GRANTS), *("publish_"+v for v in runtime_fixture.PUBLISH_GRANTS), "toolset", "paused", "emergency_stop"]:
                refusal(row, label)
        elif name == "SOURCE_AND_NAME_REFUSALS":
            for label in ["empty_root", "outside", "symlink", "fifo", "ancestry", "file_race", "source_stale", "root_stale", "collection_collision", "mesh_collision", "material_collision", "object_collision"]:
                refusal(row, label)
        elif name == "NORMAL_CONSENT":
            for label in ["omitted", "reordered", "duplicated", "wrong_type", "wrong_normal", "auto_without_normal", "mixed_uv", "alpha", "texture", "skin", "animation", "tangent", "uri", "extra_stream"]:
                refusal(row, label)
            row["witness"]["accepted_losses"] = runtime_fixture.LOSSES
        elif name == "START_HANDOFF_AND_DISCONNECT":
            row["witness"]["outcomes"] = []
            for kind in ("undelivered", "expired", "disconnect"):
                identifier = call(row, "asset.glb_stage_create_start")
                proof["tcp"][-1].update(delivered=False, response=None, received_at=None, transport_outcome="DISCONNECTED")
                proof["tcp"][-1]["runtime_receipt"].update(delivered=False, rejected=True, disconnected=True, deadline=1., expired_without_delivery=True)
                row["witness"]["outcomes"].append({"kind": kind, "request_id": identifier, "work_before_handoff": [],
                    "terminal": None, "native": {"native_entries": []}, "no_job_accepted": True})
        elif name in {"GENUINE_CANCEL_AFTER_UV", "STOP_AT_NATIVE_RETURN"}:
            identifier = call(row, "jobs.cancel", {"cancel_requested": True})
            call(row, "jobs.inspect", {"state": "CANCELLED"})
            row["native"].update(native_entries=[{"index": 0, "operation": "WRITE_UV", "role": "mesh:0", "entry": "uv.foreach_set", "entered": True,
                "returned": True, "post_return_stop_checked": True, "seconds": .001}], stopped=True, stop_native_entry_count=1, entries_after_stop=[])
            row["witness"].update(cancel_request_id=identifier, stop_ack_native_entry_count=1, genuine_return_escrow_roles=["mesh:0"], observed_uv_native_index=0)
        elif name == "PERMISSION_REVOCATION":
            call(row, "jobs.inspect", {"state": "FAILED", "error": {"code": "PERMISSION_DENIED"}})
            row["witness"]["revoked_grant"] = "EDIT_MESH"
            row["native"].update(stopped=True, stop_native_entry_count=0, entries_after_stop=[])
        elif name == "OWNED_MANUAL_DRIFT":
            row["witness"]["drifts"] = []
            for kind in ("encoded_short", "selection_bit", "uv_role", "authored_channel", "schema"):
                identifier = call(row, "asset.glb_stage_publish_start", ok=False)
                row["witness"]["drifts"].append({"kind": kind, "before": {"value": 0}, "after": {"value": 1}, "request_id": identifier,
                    "scene_edges_before": [[83, 84]], "scene_edges_after": [[83, 84]]})
        elif name == "DESTINATION_DRIFT_AND_UNITS":
            for kind in ("scene_identity", "master_identity", "child_inventory", "name", "context", "unit_scale"):
                refusal(row, kind)
        elif name == "PARTIAL_UNKNOWN_IDS":
            call(row, "asset.glb_stage_inspect", {"outcome_unknown": True})
            row["witness"].update(retained_identities=[[1, 100]], unknown_inventory=True, deletions=[])
        elif name == "PUBLICATION_STOP_OR_FAILURE":
            call(row, "asset.glb_stage_inspect", {"publication_observed": True})
            row["witness"].update(before_link={"edges_before": [[83, 84]], "edges_after": [[83, 84]]}, after_link={"phase": "PUBLISHED", "automatic_unlink": False})
        elif name == "UNDO_LOAD_RUNTIME_INVALIDATION":
            call(row, "asset.glb_stage_inspect", {"phase": "STALE"})
            row["witness"]["invalidations"] = [{"kind": kind, "actual_native_operation": True, "stale_phase": "STALE", "old_stage_id": "old", "fresh_stage_id": "fresh", "stale_native_entries": []}
                for kind in ("undo", "redo", "file_load", "runtime_reset")]
        elif name == "SHARED_SLOT_REENTRANCY":
            for kind in ("glb", "image", "scene", "native_save"):
                refusal(row, kind)
            row["witness"].update(canonical_slot_count=1, nested_executor_probes=[{"kind": kind, "scope": "TRUSTED_NESTED_EXECUTOR_ONLY", "outer_request_id": row["requests"][0],
                "response": {"ok": False}, "nested_grant_entries": 0, "nested_checkpoint_entries": 0, "nested_native_entries": 0}
                for kind in ("provider", "checkpoint", "handler", "finalizer")])
        else:
            call(row, "asset.glb_stage_inspect", {"phase": "CONSTRUCTED"})
    proof["observations"] = [{"phase": name, "elapsed_seconds": elapsed, "real_timer_callback": name != "immediate", "snapshot": copy.deepcopy(baseline)}
        for name, elapsed in runtime_fixture.OBSERVATIONS]
    proof["cases"][-2]["witness"]["observation_digests"] = [runtime_fixture.digest(value["snapshot"]) for value in proof["observations"]]
    proof["cases"][-1]["witness"]["countermodels"] = [{"kind": kind, "rejected": True, "reason": "synthetic validator control"} for kind in runtime_fixture.COUNTERMODELS]
    # These are detached validator inputs. No synthetic row is native evidence.
    def effect_report():
        effects = []
        for kind, facts in (
            ("EXISTING_ARRAY_GEOMETRY_READ", {"field": "vertices", "allowed_effects": ["BIT_PRESERVING_ARRAY_COW_UNSHARE", "NATIVE_CACHE_TAGGING"]}),
            ("EXISTING_ARRAY_ATTRIBUTE_READ", {"name": "position", "storage": "ARRAY", "allowed_effects": ["BIT_PRESERVING_ARRAY_COW_UNSHARE"]}),
            ("VERTEX_GROUP_READ", {"build": list(version), "allowed_effects": ["BIT_PRESERVING_GROUP_BUFFER_COW_UNSHARE", "EMPTY_CD_MDEFORMVERT_CREATION_AND_LAYER_DESCRIPTOR_REALLOCATION"]}),
        ):
            effects.append({"index": len(effects), "kind": kind, "mesh_uid": rows["mesh:0"]["identity"]["uid"], "count": 3,
                "attempts_entered": 1, "attempts_returned": 1, "entered_in_capture": 1, "returned_in_capture": 1,
                "last_attempt_returned": True, "logical_values_written": False, "physical_pointer_stability_required": False, **facts})
        return {"scope": "LOGICAL_AUTHORED_MESH_VALUES_WITH_DECLARED_PHYSICAL_READ_EFFECTS", "runtime_gate_bound": True,
            "read_effects": effects, "native_qualified": False, "hidden_layout_or_cache_passivity_qualified": False,
            "SINGLE_conversion_authorized": False, "empirical_pre_COW_value_hash_observed": False,
            "arbitrary_NaN_or_padding_bit_preservation_qualified": False,
            "copy_evidence": "SOURCE_EQUIVALENT_TYPED_LOGICAL_COPY_AND_COMPLETE_POSTREADBACK"}
    for row in proof["cases"]:
        group = 0 if row["id"] in runtime_fixture.SCENARIOS[:2] else 1
        row.update(runtime_group_start=group, runtime_group_end=group)
        if row["native"]["native_entries"]:
            row["native"]["protected_mesh_read_effects"] = effect_report()
    for request in proof["tcp"]:
        if request["request"]["method"] == "asset.glb_stage_preview" and request["response"]["ok"]:
            request["response"]["result"]["protected_mesh_read_effects"] = effect_report()
    second = proof["cases"][1]
    edge = second["witness"]["published_edge"]
    scene = second["after"]["protected"]["scenes"][0]
    scene["root_children"] = sorted([84, edge[1]])
    scene["view_layers"][0]["objects"] = sorted([1, *(value["identity"]["uid"] for role, value in rows.items() if role.startswith("object:"))])
    proof["observation_series"] = []
    for kind, case in zip(("CONSTRUCTED", "PUBLISHED"), proof["cases"][:2], strict=True):
        observed = [{"phase": phase, "elapsed_seconds": elapsed, "real_timer_callback": phase != "immediate",
            "snapshot": copy.deepcopy(case["after"]), "logical_sha256": runtime_fixture.digest(runtime_fixture.logical_snapshot(case["after"]))}
            for phase, elapsed in runtime_fixture.OBSERVATIONS]
        proof["observation_series"].append({"kind": kind, "runtime_group": 0, "started_at": 3., "observations": observed})
    before_record = {"stage_id": "glb_stage_"+"a"*32, "preview_id": "glb_preview_"+"a"*32,
        "phase": "PUBLISHED", "session_valid": True, "collection_name": "Synthetic", "observed_allocations": [],
        "possible_mutation": True, "outcome_unknown": False}
    stale_record = {**before_record, "phase": "STALE", "session_valid": False, "outcome_unknown": True}
    identities = [["objects", 1, 2, "Synthetic", 1, False, "Object"]]
    proof["main_id_families"] = sorted(protected)
    proof["retired_runtime_ledgers"] = [{"index": 0, "runtime_identity": 1001, "registered": False,
        "records_before": [before_record], "records_after_unregister": [stale_record], "native_evidence": {},
        "native_evidence_after_unregister": {}, "retained_runtime_object": True, "record_evictions": [], "native_cleanup": False,
        "identities_before": identities, "identities_after": copy.deepcopy(identities),
        "artist_main_before": copy.deepcopy(baseline), "artist_main_after": copy.deepcopy(baseline)}]
    stale_id = call(proof["cases"][2], "asset.glb_stage_inspect", {"code": "INVALID_ARGUMENT"}, ok=False, params={"stage_id": before_record["stage_id"]})
    proof["runtime_groups"] = [{"index": 0, "runtime": copy.deepcopy(proof["runtime"]), "issued_at": .1,
        "raw_owned_fixture_lifetime_setup": True, "prior": None},
        {"index": 1, "runtime": {**proof["runtime"], "runtime_identity": 2001, "registry_identity": 2002, "executor_identity": 2003},
         "issued_at": .5, "raw_owned_fixture_lifetime_setup": True,
         "prior": {"ledger_index": 0, "old_runtime_identity": 1001, "old_registered": False,
                   "old_stage_ids": [before_record["stage_id"]], "artist_main_preserved": True},
         "stale_lookup_refusals": [{"stage_id": before_record["stage_id"], "request_id": stale_id, "error_code": "INVALID_ARGUMENT"}]}]
    def disconnect_model(case, entry, *, publication=False, owner_number=0):
        owner_method = "asset.glb_stage_publish_start" if publication else "asset.glb_stage_create_start"
        owner = call(case, owner_method, {"accepted": True})
        request = proof["tcp"][-1]
        request["connection_instance"] = str(owner_number+4)*32
        request["runtime_receipt"].update(connection_identity=9010+owner_number, disconnected=True)
        native = {"native_entries": [{"index": 0, "operation": "PUBLISH" if publication else "NEW_MESH", "role": "collection" if publication else "mesh:0",
            "entry": entry, "entered": True, "returned": True, "post_return_stop_checked": False,
            "seconds": 1., "started_monotonic": 3., "returned_monotonic": 4.}],
            "native_access_counts": {"native": {"entered": 1, "returned": 1}}, "owned_reference_roles": [],
            "footprint_complete": False, "stopped": True, "stop_native_entry_count": 1, "entries_after_stop": [],
            "protected_mesh_read_effects": effect_report()}
        if publication:
            native["publication_physical_effects"] = {"declared_native_link_effects": ["MAIN_WIDE_COLLECTION_LAYER_BASE_SYNC", "LOCAL_VIEW_COLLECTION_SYNC"],
                "main_wide_sync_may_have_run": True, "hidden_layout_or_cache_passivity_qualified": False}
        case["native"] = native
        receipt = {"source_boundary": "RUNTIME_NATIVE_GATE_CALL_AFTER_RECORDED_C_RETURN", "maximum_rendezvous_seconds": 1.,
            "actual_owner_tcp_close": True, "network_disconnected_event_ack": True, "main_rpc_wait": False,
            "synthetic_cancel": False, "fabricated_c_failure": False, "owner_start_request_id": owner,
            "owner_connection_instance": request["connection_instance"], "runtime_group": 1, "connection_identity": 9010+owner_number,
            "entry_index": 0, "started_monotonic": 3., "returned_monotonic": 4., "notified_at": 4.1, "network_ack_at": 4.3,
            "close_receipt": [{"closed_at": 4.2, "actual_socket_fileno": -1, "closed_socket_fileno": 12}],
            "native_access_counts_at_return": copy.deepcopy(native["native_access_counts"]), "genuine_return_escrow_roles": [] if publication else ["mesh:0"]}
        case["witness"].update(disconnect=receipt, stop_ack_native_entry_count=1, atomic_native_interval_seconds=1.,
            genuine_return_escrow_roles=receipt["genuine_return_escrow_roles"], actual_terminal={"state": "CANCELLED"})
        return receipt
    stopped = next(row for row in proof["cases"] if row["id"] == "STOP_AT_NATIVE_RETURN")
    cancel_id = stopped["witness"].pop("cancel_request_id")
    old_cancel = next(row for row in proof["tcp"] if row["request"]["id"] == cancel_id)
    old_cancel["request"]["method"] = "asset.glb_stage_inspect"
    next(row for row in stopped["history"] if row["request_id"] == cancel_id)["method"] = "asset.glb_stage_inspect"
    disconnect_model(stopped, "meshes.new")
    partial = next(row for row in proof["cases"] if row["id"] == "PARTIAL_UNKNOWN_IDS")
    partial["witness"].update(raw_partial_identities=[["meshes", 110]], incomplete_native_footprint=True)
    disconnect_model(partial, "meshes.new", owner_number=1)
    publication = next(row for row in proof["cases"] if row["id"] == "PUBLICATION_STOP_OR_FAILURE")
    before_cancel = call(publication, "jobs.cancel", {"cancel_requested": True})
    publication["witness"]["before_link"]["cancel_request_id"] = before_cancel
    receipt = disconnect_model(publication, "CollectionChildren.link", publication=True, owner_number=2)
    after_link_before = copy.deepcopy(baseline)
    after_link_after = copy.deepcopy(after_link_before)
    after_link_after["scene_edges"].append([83, 200])
    after_link_after["protected"]["scenes"][0]["root_children"].append(200)
    after_link_after["protected"]["scenes"][0]["view_layers"][0]["objects"].extend([201, 202, 203])
    publication["witness"]["after_link"] = {"phase": "PUBLICATION_UNKNOWN", "retained": {"outcome_unknown": True},
        "automatic_unlink": False, "native": copy.deepcopy(publication["native"]), "disconnect": copy.deepcopy(receipt),
        "before": after_link_before, "after": after_link_after, "actual_edge": [83, 200], "object_closure": [201, 202, 203],
        "physical_effects": ["GLOBAL_BKE_MAIN_COLLECTION_SYNC_ALL_SCENES", "LAYER_COLLECTION_LOCAL_VIEW_BASE_CACHE_SYNC"]}
    proof["raw_observation_read_effects"] = [{"scope": "TRUSTED_RAW_FIXTURE_OBSERVER_NOT_RUNTIME_AUTHORITY",
        "mesh_uid": rows["mesh:0"]["identity"]["uid"], "at": 5., "read_effects": effect_report()["read_effects"],
        "mesh_profile": {"identity": {"uid": rows["mesh:0"]["identity"]["uid"], "pointer": 12, "name": "Synthetic"},
            "counts": {"vertices": 3, "edges": 0, "loops": 0, "polygons": 0}, "attributes": [{"name": "position", "domain": "POINT",
                "data_type": "FLOAT_VECTOR", "count": 3, "storage": "ARRAY", "schema_sha256": "a"*64, "supported": True,
                "native_class": "FloatVectorAttribute", "value_class": "FloatVectorAttributeValue"}]},
        "runtime_gate_bound": False, "native_qualified": False}]
    spans = {"OWNED_MANUAL_DRIFT": 4, "DESTINATION_DRIFT_AND_UNITS": 5,
        "PUBLICATION_STOP_OR_FAILURE": 1, "SHARED_SLOT_REENTRANCY": 4}
    group_index = 0
    for case_index, case in enumerate(proof["cases"]):
        if case_index >= 2 and case_index != len(proof["cases"])-1:
            group_index += 1
        case["runtime_group_start"] = group_index
        group_index += spans.get(case["id"], 0)
        case["runtime_group_end"] = group_index
        for request in proof["tcp"]:
            if request["request"]["id"] in case["requests"]:
                request["runtime_group"] = case["runtime_group_start"]
        if "disconnect" in case["witness"]:
            case["witness"]["disconnect"]["runtime_group"] = case["runtime_group_start"] + int(case["id"] == "PUBLICATION_STOP_OR_FAILURE")
            owner_id = case["witness"]["disconnect"]["owner_start_request_id"]
            next(request for request in proof["tcp"] if request["request"]["id"] == owner_id)["runtime_group"] = case["witness"]["disconnect"]["runtime_group"]
            if "after_link" in case["witness"]:
                case["witness"]["after_link"]["disconnect"] = copy.deepcopy(case["witness"]["disconnect"])
    original_ledger = proof["retired_runtime_ledgers"][0]
    proof["runtime_groups"] = [proof["runtime_groups"][0]]
    proof["retired_runtime_ledgers"] = []
    for index in range(1, group_index+1):
        ledger = copy.deepcopy(original_ledger)
        ledger.update(index=index-1, runtime_identity=proof["runtime_groups"][-1]["runtime"]["runtime_identity"])
        if index != 1:
            ledger.update(records_before=[], records_after_unregister=[])
        proof["retired_runtime_ledgers"].append(ledger)
        proof["runtime_groups"].append({"index": index,
            "runtime": {**proof["runtime"], "runtime_identity": 2001+index*10, "registry_identity": 2002+index*10, "executor_identity": 2003+index*10},
            "issued_at": .5+index*.001, "raw_owned_fixture_lifetime_setup": True,
            "prior": {"ledger_index": index-1, "old_runtime_identity": ledger["runtime_identity"], "old_registered": False,
                      "old_stage_ids": [before_record["stage_id"]] if index == 1 else [], "artist_main_preserved": True},
            "stale_lookup_refusals": [{"stage_id": before_record["stage_id"], "request_id": stale_id, "error_code": "INVALID_ARGUMENT"}] if index == 1 else []})
    for index in range(group_index+1):
        case = next(case for case in proof["cases"] if case["runtime_group_start"] <= index <= case["runtime_group_end"])
        call(case, "toolsets.enable", {"enabled": True})
        proof["tcp"][-1]["runtime_group"] = index
    for request in proof["tcp"]:
        if not request["runtime_receipt"]["disconnected"]:
            request["connection_instance"] = f"{request['runtime_group']+16:032x}"
            request["runtime_receipt"]["connection_identity"] = 20000+request["runtime_group"]
    # Detached inputs carry complete issued intent/job correlations. These are
    # synthetic validator controls and never evidence of native qualification.
    original = {row["request"]["id"]: row for row in proof["tcp"]}
    ordered, serial = [], [10000]
    def insert(case, method, result, params, group, template):
        serial[0] += 1
        row = copy.deepcopy(template)
        identifier = "bound_model_"+str(serial[0])
        row.update(runtime_group=group, delivered=True, received_at=2.)
        row["request"] = {"id": identifier, "method": method, "params": params, "protocol_version": "1.0"}
        row["response"] = {"id": identifier, "ok": True, "result": result}
        row["runtime_receipt"].update(delivered=True, rejected=False, disconnected=False,
            expired_without_delivery=False, deadline=10.)
        ordered.append(row)
        case["history"].append({"request_id": identifier, "method": method, "checkpoint_entered": False, "handler_entered": True})
        return row
    first_intent = None
    for case in proof["cases"]:
        selected, owner, last_group = None, None, None
        case_rows = []
        refusal_items = {item["request_id"]: item for item in case["witness"].get("refusals", [])}
        for identifier in case["requests"]:
            row = original[identifier]
            method, group = row["request"]["method"], row["runtime_group"]
            if identifier in refusal_items:
                method = runtime_fixture.refusal_contract(case["id"], refusal_items[identifier]["label"])[0]
                row["request"]["method"] = method
            if last_group is not None and group != last_group:
                selected, owner = None, None
            last_group = group
            result = row["response"]["result"] if row["delivered"] and row["response"]["ok"] else None
            def intent(case=case, first_intent=first_intent, group=group, row=row, case_rows=case_rows):
                nonlocal selected
                if selected is None:
                    if case["id"] == "TCP_SUCCESS_PUBLISH":
                        selected = first_intent
                    else:
                        number = serial[0]+1
                        selected = {"preview_id": f"glb_preview_{number:032x}", "stage_id": f"glb_stage_{number:032x}",
                            "expected_fingerprint": "b"*64, "required_accepted_losses": runtime_fixture.LOSSES,
                            "protected_mesh_read_effects": effect_report()}
                        inserted = insert(case, "asset.glb_stage_preview", selected, {}, group, row)
                        case_rows.append(inserted)
                return selected
            def accept(case=case, group=group, row=row, case_rows=case_rows, intent=intent):
                nonlocal owner
                value = intent()
                number = serial[0]+1
                owner = insert(case, "asset.glb_stage_create_start", {"accepted": True, "job_completed": False,
                    "stage_id": value["stage_id"], "job_id": f"job_{number:032x}"},
                    {"preview_id": value["preview_id"], "expected_fingerprint": value["expected_fingerprint"],
                     "accepted_losses": runtime_fixture.LOSSES}, group, row)
                owner["response"]["result"]["request_id"] = owner["request"]["id"]
                case_rows.append(owner)
                return owner
            def publication(case=case, group=group, row=row, case_rows=case_rows, intent=intent, accept=accept, current_owner=owner):
                value = intent()
                if case["id"] != "TCP_SUCCESS_PUBLISH" and current_owner is None:
                    current_owner = accept()
                    ready = insert(case, "jobs.inspect", {"state": "SUCCEEDED", "terminal": True,
                        "job_id": current_owner["response"]["result"]["job_id"], "request_id": current_owner["request"]["id"]},
                        {"job_id": current_owner["response"]["result"]["job_id"]}, group, row)
                    case_rows.append(ready)
                serial[0] += 1
                issued = {"stage_id": value["stage_id"], "publish_preview_id": f"glb_publish_{serial[0]:032x}",
                    "expected_fingerprint": "c"*64}
                case_rows.append(insert(case, "asset.glb_stage_publish_preview", issued,
                    {"stage_id": value["stage_id"]}, group, row))
                row["request"]["params"].update(stage_id=value["stage_id"], publish_preview_id=issued["publish_preview_id"],
                    expected_fingerprint=issued["expected_fingerprint"])
            if result is not None:
                if method == "asset.glb_stage_preview":
                    selected = result
                    result.update(preview_id="glb_preview_"+"a"*32, stage_id="glb_stage_"+"a"*32, expected_fingerprint="b"*64)
                    first_intent = result
                elif method in {"asset.glb_stage_create_start", "asset.glb_stage_publish_start"}:
                    if method == "asset.glb_stage_create_start":
                        issuing = next((item for item in reversed(ordered) if item["delivered"] and item["response"]["ok"]
                            and item["request"]["method"] == "asset.glb_stage_preview" and item["response"]["result"] is selected), None)
                        if owner is not None or (issuing is not None and issuing["connection_instance"] != row["connection_instance"]):
                            selected, owner = None, None
                    value = intent()
                    if method == "asset.glb_stage_publish_start":
                        publication()
                    else:
                        row["request"]["params"].update(preview_id=value["preview_id"], expected_fingerprint=value["expected_fingerprint"],
                            accepted_losses=runtime_fixture.LOSSES)
                    serial[0] += 1
                    result.update(accepted=True, job_completed=False, stage_id=value["stage_id"], job_id=f"job_{serial[0]:032x}", request_id=identifier)
                    owner = row
                elif method in {"jobs.inspect", "jobs.cancel"}:
                    if owner is None:
                        accept()
                    row["request"]["params"]["job_id"] = owner["response"]["result"]["job_id"]
                    result["job_id"] = row["request"]["params"]["job_id"]
                    if method == "jobs.inspect":
                        result["request_id"] = owner["request"]["id"]
                elif method == "asset.glb_stage_inspect":
                    value = intent()
                    row["request"]["params"]["stage_id"] = value["stage_id"]
                    result["stage_id"] = value["stage_id"]
                    if owner is not None:
                        result["job_id"] = owner["response"]["result"]["job_id"]
            elif not row["delivered"] and method == "asset.glb_stage_create_start":
                selected, owner = None, None
                value = intent()
                row["request"]["params"].update(preview_id=value["preview_id"], expected_fingerprint=value["expected_fingerprint"],
                    accepted_losses=runtime_fixture.LOSSES)
            elif identifier in refusal_items:
                item = refusal_items[identifier]
                label = item["label"]
                method, code, reason = runtime_fixture.refusal_contract(case["id"], label)
                row["request"]["method"] = method
                if method == "asset.glb_stage_create_start":
                    value = intent()
                    row["request"]["params"].update(preview_id=value["preview_id"], expected_fingerprint=value["expected_fingerprint"],
                        accepted_losses=runtime_fixture.LOSSES)
                elif method == "asset.glb_stage_publish_start":
                    publication()
                error = {"code": code, "context": {}}
                if reason is not None:
                    error["context"]["reason"] = reason
                row["response"]["error"] = error
                for entry in case["history"]:
                    if entry["request_id"] == identifier:
                        entry["method"] = method
                fault = {"scope": "RAW_OWNED_REFUSAL_BOUNDARY_OBSERVATION", "runtime_group": group,
                    "observed_at": .9, "permissions": dict.fromkeys(runtime_fixture.CREATE_GRANTS, True),
                    "enabled_toolsets": ["asset_delivery"], "paused": False, "emergency_stopped": False,
                    "source_root": "/owned/approved", "active_job_id": "job_"+"e"*32}
                if case["id"] == "PERMISSION_AND_TOOLSET":
                    if label.startswith(("create_", "publish_")):
                        grant = label.split("_", 1)[1]
                        fault["permissions"][grant] = False
                        error["context"].update(missing_permissions=[grant], required=list(
                            runtime_fixture.PUBLISH_GRANTS if label.startswith("publish_") else runtime_fixture.CREATE_GRANTS))
                    elif label == "toolset":
                        fault["enabled_toolsets"] = []
                        error["context"].update(tool=method, toolset="asset_delivery")
                    else:
                        fault["emergency_stopped" if label == "emergency_stop" else "paused"] = True
                elif case["id"] == "SOURCE_AND_NAME_REFUSALS":
                    if label == "empty_root":
                        fault["source_root"] = ""
                    elif label in {"symlink", "fifo", "outside"}:
                        fault["input_file"] = {"path": "/elsewhere/input.glb", "mode":
                            {"symlink": 0o120600, "fifo": 0o010600, "outside": 0o100600}[label]}
                    elif label.endswith("_collision"):
                        kind = label.split("_", 1)[0]
                        family = {"collection": "collections", "mesh": "meshes", "material": "materials", "object": "objects"}[kind]
                        suffix = {"collection": "", "mesh": ".M0", "material": ".P0", "object": ".O0"}[kind]
                        row["request"]["params"]["collection_name"] = "Collision"
                        item["before_native_identities"] = [[family, 123, 456, "Collision"+suffix, 1, False, "Synthetic"]]
                        item["after_native_identities"] = copy.deepcopy(item["before_native_identities"])
                    else:
                        field = {"ancestry": "parent_identity", "file_race": "file_identity", "source_stale": "sha256", "root_stale": "root"}[label]
                        fault["source_fault"] = {"kind": label, "before": {field: "before"}, "after": {field: "after"}}
                elif case["id"] == "NORMAL_CONSENT":
                    if method.endswith("create_start"):
                        row["request"]["params"]["accepted_losses"] = runtime_fixture.LOSSES[:-2]
                        error["message"] = "accepted_losses must repeat the structured GLB plan list exactly."
                    else:
                        fault["input_file"] = {"path": "/owned/approved/"+label+".glb", "sha256": "f"*64}
                elif case["id"] == "DESTINATION_DRIFT_AND_UNITS":
                    fault["destination_fault"] = {"kind": label, "before": {"value": 0}, "after": {"value": 1}}
                fault["request_params"] = copy.deepcopy(row["request"]["params"])
                item["fault_observation"] = fault
            elif row["delivered"] and method == "asset.glb_stage_publish_start":
                publication()
            ordered.append(row)
            case_rows.append(row)
        case["requests"] = [row["request"]["id"] for row in case_rows]
        order = {identifier: index for index, identifier in enumerate(case["requests"])}
        case["history"].sort(key=lambda item: order[item["request_id"]])
        for frame in case["history"]:
            frame.update(source_frame="addon/blender_codex_bridge/executor.py:_invoke_owned", raw_history=None)
            request = next(item for item in case_rows if item["request"]["id"] == frame["request_id"])
            if request["delivered"] and request["response"]["ok"] and frame["method"] in {"asset.glb_stage_create_start", "asset.glb_stage_publish_start"}:
                operation_id = "op_"+frame["request_id"]
                frame["raw_history"] = {"tool": frame["method"], "success": True, "operation_id": operation_id}
                request["response"]["result"]["operation"] = {"operation_id": operation_id, "undo_boundary_created": False}
        if "disconnect" in case["witness"]:
            owner_row = original[case["witness"]["disconnect"]["owner_start_request_id"]]
            accepted = owner_row["response"]["result"]
            case["witness"]["actual_terminal"].update(job_id=accepted["job_id"], request_id=accepted["request_id"])
            terminal = insert(case, "jobs.inspect", copy.deepcopy(case["witness"]["actual_terminal"]),
                {"job_id": accepted["job_id"]}, owner_row["runtime_group"], owner_row)
            case["requests"].append(terminal["request"]["id"])
            case["history"][-1].update(source_frame="addon/blender_codex_bridge/executor.py:_invoke_owned", raw_history=None)
            inspected = insert(case, "asset.glb_stage_inspect", {"stage_id": accepted["stage_id"], "job_id": accepted["job_id"],
                "phase": "UNKNOWN", "outcome_unknown": True}, {"stage_id": accepted["stage_id"]}, owner_row["runtime_group"], owner_row)
            case["requests"].append(inspected["request"]["id"])
            case["history"][-1].update(source_frame="addon/blender_codex_bridge/executor.py:_invoke_owned", raw_history=None)
            if case["id"] == "PARTIAL_UNKNOWN_IDS":
                case["witness"].update(retained_identities=[{"role": "collection", "native_uid": 110, "pointer": 111, "name": "Partial Collection"}],
                    raw_partial_identities=[["collections", 110, 111, "Partial Collection", 0, False, "Collection"],
                        ["meshes", 120, 121, "Partial Mesh", 0, False, "Mesh"]],
                    raw_escrow_identities=[{"stage_id": accepted["stage_id"], "role": "mesh:0", "family": "meshes",
                        "native_uid": 120, "pointer": 121, "name": "Partial Mesh"}])
                case["native"].update(owned_reference_roles=["collection", "mesh:0"], pending_returns=[{
                    "stage_id": accepted["stage_id"], "operation": "NEW_MESH", "role": "mesh:0", "returned_roles": ["mesh:0"], "drained": True}])
    proof["tcp"] = ordered
    proof["executor_history_frames"] = [copy.deepcopy(frame) for case in proof["cases"] for frame in case["history"]]
    # Use the independently authored complete native sequence from the private
    # structure model, preserving the runtime journal's stronger fields.
    first = proof["cases"][0]
    first["native"]["native_entries"] = [{**copy.deepcopy(entry), "index": index, "entered": True,
        "post_return_stop_checked": True, "started_monotonic": 2.1+index*.001,
        "returned_monotonic": 2.101+index*.001} for index, entry in enumerate(legacy["cases"][0]["native"]["native_entries"])]
    stage_id = first_intent["stage_id"]
    normal_index = next(entry["index"] for entry in first["native"]["native_entries"]
        if entry["operation"] == "WRITE_NORMALS" and entry["entry"] == "mesh_return.complete_read_attempt")
    first["witness"]["normal_return_footprint"].update(stage_id=stage_id, native_entry_index=normal_index)
    first["native"]["mesh_return_receipts"][0].update(stage_id=stage_id)
    second["native"] = copy.deepcopy(first["native"])
    second["native"]["native_entries"].append({"index": len(first["native"]["native_entries"]), "operation": "PUBLISH_COLLECTION",
        "role": "collection", "entry": "CollectionChildren.link", "entered": True, "returned": True,
        "post_return_stop_checked": True, "seconds": .001, "started_monotonic": 2.5, "returned_monotonic": 2.501})
    for case in proof["cases"][:2]:
        for request in proof["tcp"]:
            if request["request"]["id"] in case["requests"] and request["request"]["method"] == "asset.glb_stage_inspect":
                request["response"]["result"]["native_evidence"] = copy.deepcopy(case["native"])
    for series, case in zip(proof["observation_series"], proof["cases"][:2], strict=True):
        series["after_request_id"] = next(identifier for identifier in reversed(case["requests"])
            if next(row for row in proof["tcp"] if row["request"]["id"] == identifier)["request"]["method"] == "asset.glb_stage_inspect")
        for observation in series["observations"]:
            observation.update(runtime_group=series["runtime_group"], observed_at=series["started_at"]+observation["elapsed_seconds"])
    next(row for row in proof["tcp"] if row["request"]["id"] == proof["observation_series"][1]["after_request_id"])["response"]["result"]["phase"] = "PUBLISHED"
    proof["tcp"].sort(key=lambda request: request["runtime_group"])
    for index, request in enumerate(proof["tcp"]):
        request["index"] = index
        request["sent_at"] = 1.+index*.002
        if request["delivered"]:
            request["received_at"] = request["sent_at"]+.001
    request_order = {request["request"]["id"]: request["index"] for request in proof["tcp"]}
    for case in proof["cases"]:
        case["requests"].sort(key=request_order.__getitem__)
        case["history"].sort(key=lambda item: request_order[item["request_id"]])
    return proof


def glb_runtime_fixture_root(runner, monkeypatch, tmp_path):
    from scripts.blender_glb_stage_runtime_smoke import SOURCES

    binary, output = glb_fixture_root(runner, monkeypatch, tmp_path)
    for name in SOURCES:
        path = runner.ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# synthetic source-binding witness: "+name+"\n")
    return binary, output


def glb_runtime_launch(runner, monkeypatch, binary, *, fault=None, version=(4, 5, 14), marker_fault=None):
    from scripts import blender_glb_stage_runtime_smoke as fixture

    class Process:
        pid = 77
        returncode = 0

        def wait(self, **_kwargs):
            return self.returncode

    def launch(command, **kwargs):
        assert "--background" not in command and "--disable-autoexec" in command
        assert Path(command[-1]).name == "blender_glb_stage_runtime_smoke.py"
        proof = glb_runtime_model(runner, binary, kwargs["env"], version=version)
        if fault:
            fault(proof)
        raw = fixture.encode(fixture.pack_proof(proof))
        (Path(kwargs["env"]["TEMP"]) / fixture.FILENAME).write_bytes(raw)
        fields = ("schema", "profile", "completed", "blender_version", "version", "build_hash", "process_id", "process_instance", "source_sha256", "binary")
        marker = {key: proof[key] for key in fields}
        marker["evidence_sha256"] = hashlib.sha256(raw).hexdigest()
        text = fixture.MARKER+json.dumps(marker)+"\n"
        if marker_fault:
            text = marker_fault(text, marker, proof, kwargs)
        kwargs["stdout"].write(text.encode())
        return Process()

    monkeypatch.setattr(runner.subprocess, "Popen", launch)


@pytest.mark.parametrize("version", [(4, 5, 14), (5, 2, 2)])
def test_runtime_glb_is_distinct_seventeen_case_pid_bound_opt_in(runner, monkeypatch, tmp_path, version):
    binary, output = glb_runtime_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    glb_runtime_launch(runner, monkeypatch, binary, version=version)
    assert "glb_stage_runtime" in runner.OPT_IN_CASES & runner.INTERACTIVE_CASES
    assert len({runner.CASES[name][1] for name in ("glb_stage_runtime", "glb_stage_structure", "glb_stage_constructor")}) == 3
    row = runner.run_case(binary, "glb_stage_runtime", output, 10)
    assert row["status"] == "passed" and row["process_id"] == 77
    assert row["retained_evidence_validation"]["passed"] is True
    assert row["qualification_scope"]["genuine_runtime_tcp_required"] is True
    assert row["qualification_scope"]["complete_seventeen_scenarios_required"] is True
    assert row["qualification_scope"]["retained_fresh_runtime_groups_required"] is True
    assert row["qualification_scope"]["actual_owner_postreturn_disconnect_required"] is True
    assert row["qualification_scope"]["protected_logical_profile_with_read_effects_required"] is True
    assert row["qualification_scope"]["owned_fixture_storage_preparation_is_not_product_api"] is True
    assert row["qualification_scope"]["physical_cache_passivity_qualified"] is False
    assert row["qualification_scope"]["public_import_qualified"] is False


@pytest.mark.parametrize("kind", ["runtime", "pid", "source", "token", "loss", "entry", "return", "receipt", "ownership", "edge", "normal", "output_target", "selection", "stop", "history", "timer", "context", "status_only",
    "group_reuse", "group_eviction", "group_native_cleanup", "group_stale_lookup", "group_request",
    "disconnect_synthetic", "disconnect_wrong_owner", "disconnect_late_ack", "disconnect_extra_access",
    "postlink_unlink", "postlink_extra_scene_change", "constructed_timer", "published_timer",
    "read_effect_write", "read_effect_single", "read_effect_hidden_passivity", "single_refusal_late_data", "empty_read_nonzero",
    "unbacked_preparation", "preparation_before_refusal", "preparation_different_headers",
    "causal_tokens", "causal_native", "causal_refusals", "partial_identity",
    "disconnect_refused_start", "history_coverage", "timer_causality"])
def test_glb_runtime_complete_countermodels_never_become_runner_passes(runner, monkeypatch, tmp_path, kind):
    from scripts.blender_glb_stage_runtime_smoke import corrupt_countermodel

    binary, output = glb_runtime_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    glb_runtime_launch(runner, monkeypatch, binary, fault=lambda proof: corrupt_countermodel(proof, kind))
    row = runner.run_case(binary, "glb_stage_runtime", output, 10)
    assert row["status"] == "failed" and row["retained_evidence_validation"]["passed"] is False


@pytest.mark.parametrize("kind", ["depth", "multiplicity", "empty_branch", "roundtrip"])
def test_glb_runtime_interned_graph_accounts_for_every_reference(kind):
    """Tiny shared graphs must be bounded before any logical expansion."""
    from scripts import blender_glb_stage_runtime_smoke as fixture

    table = {}
    def node(value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        key = hashlib.sha256(raw).hexdigest()
        table[key] = value
        return {"ref": key}
    def object_node(pairs):
        return node({"kind": "object", "pairs": pairs})
    if kind == "roundtrip":
        value = {"left": [{"leaf": 1}]*4, "right": [{"leaf": 1}]*4}
        assert fixture.decode(fixture.encode(fixture.pack_proof(value))) == value
        return
    if kind == "depth":
        shared = object_node([["leaf", 1]])
        for _ in range(39):
            shared = object_node([["next", shared]])
        outer = shared
        for _ in range(39):
            outer = object_node([["outer", outer]])
        root = object_node([["first", shared], ["second", outer]])
    elif kind == "multiplicity":
        root = object_node([["leaf", 1]])
        for _ in range(22):
            root = object_node([["left", root], ["right", root]])
    else:
        root = node({"kind": "items", "values": []})
        for _ in range(5):
            root = node({"kind": "branch", "children": [root]*32})
        root = object_node([["array", node({"kind": "array", "root": root})]])
    raw = fixture.encode({"encoding": "GLB_RUNTIME_INTERNED_JSON_V1", "table": table, "root": root})
    assert len(raw) < 32768
    with pytest.raises(AssertionError, match=r"GLB_RUNTIME_SHARED_(DEPTH|EXPANSION_BUDGET)"):
        fixture.decode(raw)


@pytest.mark.parametrize("fault", [None, "outer_reporting_failure", "missing_acceptance", "wrong_owner", "wrong_terminal"])
def test_glb_runtime_undelivered_start_keeps_actual_canonical_acceptance(runner, monkeypatch, tmp_path, fault):
    """Canonical acceptance survives a lost client receipt without a fake ACK."""
    import copy

    binary, output = glb_runtime_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    def model(proof):
        case = next(row for row in proof["cases"] if row["id"] == "START_HANDOFF_AND_DISCONNECT")
        outcome = case["witness"]["outcomes"][0]
        start = next(row for row in proof["tcp"] if row["request"]["id"] == outcome["request_id"])
        intent = next(row["response"]["result"] for row in proof["tcp"] if row["delivered"] and row["response"]["ok"]
            and row["request"]["method"] == "asset.glb_stage_preview"
            and row["response"]["result"]["preview_id"] == start["request"]["params"]["preview_id"])
        identifier, job_id = start["request"]["id"], "job_"+"f"*32
        accepted = {"accepted": True, "job_completed": False, "request_id": identifier,
            "stage_id": intent["stage_id"], "job_id": job_id}
        frame = next(row for row in case["history"] if row["request_id"] == identifier)
        frame.update(accepted_result=accepted, returned_at=start["sent_at"]+.0001,
            accepted_at=start["sent_at"]+.00005, accepted_runtime_group=start["runtime_group"],
            accepted_result_source="addon/blender_codex_bridge/executor.py:_invoke_owned")
        terminal = {"state": "CANCELLED", "terminal": True, "job_id": job_id, "request_id": identifier}
        outcome.update(no_job_accepted=False, terminal=copy.deepcopy(terminal))
        for index, (method, params, result) in enumerate((
            ("jobs.inspect", {"job_id": job_id}, terminal),
            ("asset.glb_stage_inspect", {"stage_id": intent["stage_id"]}, {
                "phase": "UNKNOWN", "stage_id": intent["stage_id"], "job_id": job_id})), 1):
            row = copy.deepcopy(start)
            request_id = "canonical_after_undelivered_"+str(index)
            row.update(delivered=True, sent_at=start["sent_at"]+.0002*index, received_at=start["sent_at"]+.0002*index+.00001)
            row["request"] = {"id": request_id, "method": method, "params": params, "protocol_version": "1.0"}
            row["response"] = {"id": request_id, "ok": True, "result": copy.deepcopy(result)}
            row["runtime_receipt"].update(delivered=True, expired_without_delivery=False)
            proof["tcp"].append(row)
            case["requests"].append(request_id)
            case["history"].append({"request_id": request_id, "method": method, "checkpoint_entered": False,
                "handler_entered": True, "source_frame": "addon/blender_codex_bridge/executor.py:_invoke_owned", "raw_history": None})
        proof["tcp"].sort(key=lambda row: (row["runtime_group"], row["sent_at"]))
        for index, row in enumerate(proof["tcp"]):
            row["index"] = index
        order = {row["request"]["id"]: row["index"] for row in proof["tcp"]}
        case["requests"].sort(key=order.__getitem__)
        case["history"].sort(key=lambda row: order[row["request_id"]])
        if fault == "outer_reporting_failure":
            frame["accepted_result_source"] = "addon/blender_codex_bridge/glb_stage_runtime.py:attach_job"
            frame["raw_history"] = {"tool": frame["method"], "success": False}
        elif fault == "missing_acceptance":
            frame["accepted_result"] = None
        elif fault == "wrong_owner":
            accepted["request_id"] = "unrelated_request"
        elif fault == "wrong_terminal":
            outcome["terminal"]["job_id"] = "job_"+"0"*32
        proof["executor_history_frames"] = [copy.deepcopy(frame) for row in proof["cases"] for frame in row["history"]]
        assert start["delivered"] is False and start["response"] is None and start["received_at"] is None
        assert outcome["native"]["native_entries"] == []
    glb_runtime_launch(runner, monkeypatch, binary, fault=model)
    row = runner.run_case(binary, "glb_stage_runtime", output, 10)
    accepted = fault in {None, "outer_reporting_failure"}
    assert row["status"] == ("passed" if accepted else "failed")
    assert row["retained_evidence_validation"]["passed"] is accepted


@pytest.mark.parametrize("fault", ["token", "fingerprint", "connection"])
def test_glb_runtime_refused_start_still_binds_the_actual_issued_token(runner, monkeypatch, tmp_path, fault):
    binary, output = glb_runtime_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    def wrong_token(proof):
        case = next(row for row in proof["cases"] if row["id"] == "SOURCE_AND_NAME_REFUSALS")
        refusal = next(row for row in case["witness"]["refusals"] if row["label"] == "source_stale")
        request = next(row for row in proof["tcp"] if row["request"]["id"] == refusal["request_id"])
        if fault == "connection":
            request["connection_instance"] = "f"*32
            request["runtime_receipt"]["connection_identity"] = 987654
        else:
            field = "preview_id" if fault == "token" else "expected_fingerprint"
            request["request"]["params"][field] = "glb_preview_"+"0"*32 if field == "preview_id" else "0"*64
            refusal["fault_observation"]["request_params"][field] = request["request"]["params"][field]
    glb_runtime_launch(runner, monkeypatch, binary, fault=wrong_token)
    row = runner.run_case(binary, "glb_stage_runtime", output, 10)
    assert row["status"] == "failed" and row["retained_evidence_validation"]["passed"] is False


@pytest.mark.parametrize("fault", [None, "nonzero_domain", "nonzero_attribute", "missing_counts", "wrong_uid", "SINGLE", "boolean_zero"])
def test_glb_runtime_empty_mesh_read_receipt_requires_complete_zero_profile(runner, monkeypatch, tmp_path, fault):
    """Detached validator controls; an empty effect journal is no native proof."""
    from scripts import blender_glb_stage_runtime_smoke as runtime_fixture

    binary, _output = glb_runtime_fixture_root(runner, monkeypatch, tmp_path)
    proof = glb_runtime_model(runner, binary, {"BRIDGE_TEST_PROCESS_TOKEN": "a"*32})
    observation = proof["raw_observation_read_effects"][0]
    observation["read_effects"] = []
    profile = observation["mesh_profile"]
    profile["counts"] = dict.fromkeys(("vertices", "edges", "loops", "polygons"), 0)
    profile["attributes"][0]["count"] = 0
    if fault == "nonzero_domain":
        profile["counts"]["vertices"] = 1
        profile["attributes"][0]["count"] = 1
    elif fault == "nonzero_attribute":
        profile["attributes"][0]["count"] = 1
    elif fault == "missing_counts":
        profile.pop("counts")
    elif fault == "wrong_uid":
        profile["identity"]["uid"] += 1
    elif fault == "SINGLE":
        profile["attributes"][0]["storage"] = "SINGLE"
    elif fault == "boolean_zero":
        profile["counts"]["vertices"] = False
    if fault is None:
        assert runtime_fixture.validate_runtime_transcript(proof)
        profile["attributes"] = []
        assert runtime_fixture.validate_runtime_transcript(proof)
    else:
        with pytest.raises((AssertionError, KeyError, TypeError)):
            runtime_fixture.validate_runtime_transcript(proof)


@pytest.mark.parametrize("fault", [None, "unbacked", "before_refusal", "different_headers", "different_group", "changed_readback"])
def test_glb_runtime_raw_preparation_binds_genuine_prior_refusal_and_complete_readback(runner, monkeypatch, tmp_path, fault):
    """Typed detached controls only; this never qualifies a native conversion."""
    import copy

    from scripts import blender_glb_stage_runtime_smoke as runtime_fixture
    from scripts.blender_glb_stage_smoke import structure_digest

    binary, _output = glb_runtime_fixture_root(runner, monkeypatch, tmp_path)
    proof = glb_runtime_model(runner, binary, {"BRIDGE_TEST_PROCESS_TOKEN": "a"*32}, version=(5, 2, 2))
    case = proof["cases"][2]
    request = copy.deepcopy(next(row for row in proof["tcp"] if row["request"]["id"] == case["requests"][0]))
    request["request"].update(id="bound_single_refusal", method="asset.glb_stage_preview", params={})
    request["response"] = {"id": "bound_single_refusal", "ok": False,
        "error": {"code": "NOT_IMPLEMENTED", "context": {"reason": "PROTECTED_MESH_SINGLE_REQUIRES_SEPARATE_PREPARATION"}}}
    proof["tcp"].append(request)
    proof["tcp"].sort(key=lambda item: item["runtime_group"])
    for index, item in enumerate(proof["tcp"]):
        item["index"] = index
    case["requests"].append("bound_single_refusal")
    frame = {"request_id": "bound_single_refusal", "method": "asset.glb_stage_preview", "checkpoint_entered": False,
        "handler_entered": True, "source_frame": "addon/blender_codex_bridge/executor.py:_invoke_owned", "raw_history": None}
    case["history"].append(frame)
    proof["executor_history_frames"].append(copy.deepcopy(frame))
    identity = {"uid": 123, "pointer": 456, "name": "Prepared Fixture"}
    counts = {"vertices": 3, "edges": 0, "loops": 0, "polygons": 0}
    headers = {"identity": identity, "counts": counts, "uv_roles": {"active_index": -1, "clone_index": 0, "stencil_index": 0, "layers": []},
        "materials": [], "uv_auxiliary_presence": [], "shape_keys_ref": None,
        "attributes": [{"name": "flag", "domain": "POINT", "data_type": "BOOLEAN", "native_class": "BoolAttribute",
            "value_class": "BoolAttributeValue", "storage": "SINGLE", "count": 3, "schema_sha256": "a"*64, "supported": True},
            {"name": "position", "domain": "POINT", "data_type": "FLOAT_VECTOR", "native_class": "FloatVectorAttribute",
             "value_class": "FloatVectorAttributeValue", "storage": "ARRAY", "count": 3, "schema_sha256": "b"*64, "supported": True}]}
    after = copy.deepcopy(headers)
    after["attributes"][0]["storage"] = "ARRAY"
    projection = copy.deepcopy(after)
    projection["attributes"] = [{key: value for key, value in item.items() if key != "storage"} for item in after["attributes"]]
    projection.update(geometry={"vertices": [{"index": index, "co": ["00000000"]*3, "select": False, "hide": False, "groups": []} for index in range(3)],
        "edges": [], "loops": [], "polygons": []}, attribute_values={"flag": [False]*3, "position": [["00000000"]*3]*3}, uv_layers=[])
    row = {"identity": identity, "coordinates": [["00000000"]*3]*3, "corners": [], "faces": [], "edges": [],
        "materials": [], "attributes": {"flag": {"domain": "POINT", "type": "BOOLEAN", "values": [False]*3},
            "position": {"domain": "POINT", "type": "FLOAT_VECTOR", "values": [["00000000"]*3]*3}},
        "logical_projection": projection, "uv_roles": headers["uv_roles"], "uv_layers_complete": [], "memberships": [[], [], []]}
    baseline = copy.deepcopy(case["before"])
    baseline["protected"]["meshes"].append(copy.deepcopy(row))
    proof["single_storage_refusals"].append({"request_id": "bound_single_refusal", "runtime_group": 1,
        "error": copy.deepcopy(request["response"]["error"]), "headers": [copy.deepcopy(headers)], "mesh_target": None,
        "recorded_at": 2.1, "native_access_counts": {}, "protected_read_effect_attempts": [], "checkpoint_marker_entries": 0})
    preparation = {"scope": "RAW_OWNED_FIXTURE_PREPARATION_NOT_BRIDGE_API", "runtime_group": 1, "mesh_target": None,
        "refusal_request_id": "bound_single_refusal", "started_at": 2.2, "finished_at": 2.3, "baseline_observed_at": 2.4,
        "before_headers": [copy.deepcopy(headers)], "after_headers": [copy.deepcopy(after)], "baseline_after": baseline,
        "record_evictions": [], "native_qualified": False, "scalar_float_or_unknown_conversion": False, "logical_values_reset": False,
        "actions": [{"mesh_identity": identity, "attribute": "flag", "data_type": "BOOLEAN", "before_header": copy.deepcopy(headers["attributes"][0]),
            "after_header": copy.deepcopy(after["attributes"][0]), "authoring_scope": "RAW_OWNED_FIXTURE_EDIT_MESH", "production_preparation_api": False,
            "native_action": "QUALIFIED_GENERIC_ATTRIBUTE_DATA_MATERIALIZATION", "pre_single_value_sha256": None,
            "bit_preservation_basis": "PINNED_SOURCE_EQUIVALENCE_NOT_EMPIRICAL_PRE_SINGLE_READ", "known_fixture_oracles_required_after_readback": True}],
        "post_readback": [{"mesh_uid": 123, "headers": copy.deepcopy(after), "logical_projection": projection,
            "authored_sha256": structure_digest(projection), "row": row}]}
    proof["raw_storage_preparations"].append(preparation)
    if fault == "unbacked":
        proof["single_storage_refusals"] = []
    elif fault == "before_refusal":
        preparation["started_at"] = 2.09
    elif fault == "different_headers":
        preparation["before_headers"][0]["identity"]["uid"] += 1
    elif fault == "different_group":
        preparation["runtime_group"] = 2
    elif fault == "changed_readback":
        preparation["post_readback"][0]["authored_sha256"] = "0"*64
    if fault is None:
        assert runtime_fixture.validate_runtime_transcript(proof)
    else:
        with pytest.raises((AssertionError, KeyError, TypeError)):
            runtime_fixture.validate_runtime_transcript(proof)


@pytest.mark.parametrize("payload", [[1], "truthy", 1, True, None])
def test_glb_runtime_nonobject_marker_retains_failed_row(runner, monkeypatch, tmp_path, payload):
    from scripts.blender_glb_stage_runtime_smoke import MARKER

    binary, output = glb_runtime_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    glb_runtime_launch(runner, monkeypatch, binary,
        marker_fault=lambda *_args: MARKER+json.dumps(payload)+"\n")
    row = runner.run_case(binary, "glb_stage_runtime", output, 10)
    assert row["status"] == "failed" and row["evidence"] is None
    assert row["retained_evidence_validation"]["passed"] is False


@pytest.mark.parametrize("kind", ["duplicate_marker", "duplicate_key", "nonfinite", "deep", "missing", "log_budget", "report_symlink", "report_fifo", "report_replaced", "source_changed", "binary_changed", "wrong_pid", "digest"])
def test_glb_runtime_launch_storage_and_json_faults_fail_closed(runner, monkeypatch, tmp_path, kind):
    from scripts.blender_glb_stage_runtime_smoke import FILENAME, MARKER

    binary, output = glb_runtime_fixture_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    def fault(text, marker, _proof, kwargs):
        report = Path(kwargs["env"]["TEMP"]) / FILENAME
        if kind == "duplicate_marker":
            return text+text
        if kind == "duplicate_key":
            return MARKER+text[len(MARKER):].replace('"schema":', '"schema":"duplicate","schema":', 1)
        if kind == "nonfinite":
            return MARKER+'{"invalid":NaN}\n'
        if kind == "deep":
            return MARKER+'['*1000+'0'+']'*1000+'\n'
        if kind == "missing":
            return "unrelated process log\n"
        if kind == "log_budget":
            return "x"*(4*1024**2)+text
        if kind == "report_symlink":
            original = report.with_suffix(".retained")
            report.rename(original)
            report.symlink_to(original)
        elif kind == "report_fifo":
            import os
            report.unlink()
            os.mkfifo(report)
        elif kind == "report_replaced":
            replacement = report.with_suffix(".replacement")
            replacement.write_bytes(report.read_bytes()+b" ")
            replacement.replace(report)
        elif kind == "source_changed":
            (runner.ROOT / "addon/blender_codex_bridge/runtime.py").write_text("# changed after launch\n")
        elif kind == "binary_changed":
            binary.write_bytes(b"changed binary")
        elif kind == "wrong_pid":
            marker["process_id"] = 999
        elif kind == "digest":
            marker["evidence_sha256"] = "0"*64
        return MARKER+json.dumps(marker)+"\n"
    glb_runtime_launch(runner, monkeypatch, binary, marker_fault=fault)
    row = runner.run_case(binary, "glb_stage_runtime", output, 10)
    assert row["status"] == "failed" and row["retained_evidence_validation"]["passed"] is False


def mesh_storage_runner_root(runner, monkeypatch, tmp_path):
    """Pure receipt/launch model; no Blender or native storage is allocated."""
    source, output = tmp_path / "source", tmp_path / "output"
    output.mkdir()
    names = ("scripts/blender_mesh_storage_job_smoke.py", "scripts/run_blender_checks.py",
             "scripts/blender_current_pixels_lifecycle_smoke.py", "scripts/blender_artist_sidebar_smoke.py",
             "scripts/native_resources.py", "addon/blender_codex_bridge/mesh_storage_source.py",
             "addon/blender_codex_bridge/scene_jobs.py", "addon/blender_codex_bridge/tools/mesh_storage.py")
    for name in names:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# owned storage job composition model\n")
    helper = "addon/blender_codex_bridge/mesh_storage_prepare.py"
    (source / helper).write_bytes((ROOT / helper).read_bytes())
    binary = tmp_path / "blender binary"
    binary.write_bytes(b"MODELED EXECUTABLE, NEVER LAUNCHED")
    digest = runner.hashlib.sha256(binary.read_bytes()).hexdigest()
    monkeypatch.setattr(runner, "ROOT", source)
    monkeypatch.setattr(runner, "MESH_STORAGE_EXECUTABLE_SHA256", digest)
    monkeypatch.setattr(runner, "_domain_display", lambda: {"path": "/owned/private-display.json", "bytes": 42, "sha256": "d" * 64})
    return output, binary


def mesh_storage_snapshot_model(runner, *, prepared=True):
    image = ["Texture", 44, 16384]
    material = ["Material", 45, 20480]
    zero = runner.struct.pack("<f", 0.).hex()
    values = {".uv_select_face": [True], "UVSingle": [[runner.struct.pack("<f", .25).hex(), runner.struct.pack("<f", -.5).hex()]] * 3}
    return {"object_identity": ["Target", 42, 8192], "mesh_identity": ["Mesh", 43, 12288],
        "uv_roles": [-1, [["UVSingle", True, False]]],
        "selected_storage": [[".uv_select_face", "FACE", "BOOLEAN", "ARRAY" if prepared else "SINGLE", 1],
                             ["UVSingle", "CORNER", "FLOAT2", "ARRAY" if prepared else "SINGLE", 3]],
        "selected_values": values if prepared else {},
        "protected": {"Main_ids": [["objects", [["Target", 8192, 42, 1, False]]],
                                   ["meshes", [["Mesh", 12288, 43, 1, False]]]],
            "image": {"identity": image, "pixels_float32_le": runner.struct.pack("<16f", *([.25] * 16)).hex(),
                      "packed_sha256": "a" * 64, "packed_bytes": 72, "color_space": "Non-Color", "alpha_mode": "STRAIGHT",
                      "is_dirty": True, "has_data": True},
            "material_bindings": [[material, ["MaterialTree", 46, 24576], "Image Texture", 28672, image, [material]]],
            "unselected_attribute_headers": [[".select_edge", "EDGE", "BOOLEAN", "SINGLE", 3],
                                               ["position", "POINT", "FLOAT_VECTOR", "ARRAY", 3]],
            "original_ARRAY_values": [["position", "POINT", "FLOAT_VECTOR", [[zero] * 3 for _ in range(3)]]]}}


def mesh_storage_journal_model(runner, oracle):
    rows = []
    for name in (".uv_select_face", "UVSingle"):
        row = dict.fromkeys(("data_lookup_entered", "data_lookup_returned", "materialize_entered", "materialize_returned",
                             "after_storage_observed", "verified"), True)
        row.update(name=name, helper_attached=True, baseline_conflict=False, action="MATERIALIZE_SINGLE", entry_kind="FOREACH_GET",
                   before_storage="SINGLE", after_storage="ARRAY", readback_entries=2, readback_returns=2,
                   logical_values_sha256=runner.hashlib.sha256(json.dumps(oracle[name], sort_keys=True, ensure_ascii=True,
                       allow_nan=False, separators=(",", ":")).encode()).hexdigest(),
                   retained_physical_transition="OBSERVED_SINGLE_TO_ARRAY")
        rows.append(row)
    return {"schema": "mesh_storage_retained_effects_v1", "rows": rows, "sealed": True,
        "materialization_entered": True, "native_lookup_entered": True, "physical_cache_passivity_claimed": False,
        "verification_required": True, "inverse_attempted": False, "requires_fresh_image_preview": True,
        "independently_measured_SINGLE_pre_values": False, "project_saved": False, "durable_backup": False}


def mesh_storage_reply(request, result=None, *, error=None):
    return {"id": request["id"], "ok": error is None, "protocol_version": "1.0", "timestamp": "2026-10-29T19:00:00Z",
            "result" if error is None else "error": result if error is None else error}


def mesh_storage_full_model(runner, command, environment, pid):
    phase = command[command.index("--bridge-phase") + 1]
    report = Path(command[command.index("--bridge-report") + 1])
    sources = runner._mesh_storage_sources()
    before, after = mesh_storage_snapshot_model(runner, prepared=False), mesh_storage_snapshot_model(runner)
    oracle = json.loads(json.dumps(after["selected_values"]))
    journal = mesh_storage_journal_model(runner, oracle)
    job_id = "job_" + "1" * 32
    terminal = {"job_id": job_id, "kind": "mesh.attribute_storage_preparation", "state": "SUCCEEDED", "terminal": True,
                "storage_effects": journal, "terminal_history_evicted": False}
    requests = []
    parameters = {"object_name": "Target", "mesh_name": "Mesh", "attribute_names": [".uv_select_face", "UVSingle"]}
    for method, params, result in (("mesh.attribute_storage_prepare_preview", parameters,
                                   {"expected_preparation_fingerprint": "c" * 64}),
                                  ("mesh.attribute_storage_prepare_job_start", {**parameters,
                                   "expected_preparation_fingerprint": "c" * 64, "confirm_materialize_storage": True,
                                   "confirm_retained_partial_preparation": True},
                                   {"accepted": True, "job_id": job_id, "kind": "mesh.attribute_storage_preparation"}),
                                   ("jobs.inspect", {"job_id": job_id}, terminal)):
        request = {"id": f"request-{len(requests)}", "method": method, "params": params, "protocol_version": "1.0", "timeout_ms": 60000}
        requests.append({"request": request, "response": mesh_storage_reply(request, result)})
    stop = dict.fromkeys(("provider_before", "provider_after", "native_before", "native_after"), 0)
    positive = {"requests": requests, "assertions": dict.fromkeys(runner.MESH_STORAGE_CASE_ASSERTIONS, True),
        "evidence": {"before": before, "after": after, "oracle_values": oracle, "terminal": terminal, "journal": journal,
                     "stop_counts": stop, "history": [], "recovery": []}}
    request = {"id": "undo-1", "method": "checkpoint.undo_last", "params": {"confirm_global_undo": True}, "protocol_version": "1.0"}
    response = mesh_storage_reply(request, error={"code": "NOT_IMPLEMENTED", "message": "Measured recovery gap"})
    measurement = {"kind": "authorized_native_undo_measurement", "request_id": request["id"], "response": response,
                   "before": after, "after": after, "safety_qualified": False}
    recovery = {"requests": [{"request": request, "response": response}],
        "assertions": {"complete": True, "actual_undo_response_retained": True, "before_after_measured": True, "restore_safety_qualified": False},
        "evidence": {"before": after, "after": after, "oracle_values": oracle, "terminal": None, "journal": None,
                     "stop_counts": stop, "history": [], "recovery": [measurement]}}
    events = []
    for turn, attribute in enumerate((".uv_select_face", "UVSingle"), 1):
        for kind, boundary, selected in (("turn_enter", "scene_turn", None), ("prepare_enter", "helper_prepare", attribute),
            ("materialize_enter", "helper_prepare_C_foreach", attribute), ("materialize_return", "helper_prepare_C_foreach", attribute),
            ("prepare_return", "helper_prepare", attribute), ("turn_return", "scene_turn", None)):
            events.append({"sequence": len(events) + 1, "case": "two_rows", "kind": kind, "monotonic": 1. + len(events) / 100,
                           "job_id": job_id, "native_count": turn, "provider_count": turn, "turn": turn,
                           "attribute": selected, "boundary": boundary})
    counts = dict(native_entries=2, native_returns=2, provider_entries=2, provider_returns=2,
        prepare_entries=2, prepare_returns=2, materialize_entries=2, materialize_returns=2,
        after_accepted_stop_native_entries=0, after_accepted_stop_provider_entries=0)
    trace = {"scope": "BRIDGE_B2_ACTIVE_DOMAIN_ONLY", "covered_boundaries": ["helper_access_field", "graph_catalog", "helper_prepare_C_foreach"],
        "counts": counts, "events": events, "stops": [],
        "native_C_intervals": [{"case": "two_rows", "attribute": name, "seconds": .001, "returned": True}
                               for name in (".uv_select_face", "UVSingle")],
        "status_RPC_authorization_excluded": True, "all_hidden_Blender_native_calls_claimed": False,
        "wrapper_exit_counts_include_exception": True, "prepare_exit_counts_include_exception": True}
    identity = {"process_instance": environment["BRIDGE_TEST_PROCESS_TOKEN"], "runtime_id": 32768, "registry_id": 36864, "queue_id": 40960}
    def canonical(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    full = {"schema": "MESH_STORAGE_OWNED_JOB_NATIVE_V1", "completed": True, "phase": phase, "process_id": pid,
        "process_instance": identity["process_instance"], "runtime_nonce": runner.hashlib.sha256(canonical(identity)).hexdigest()[:32],
        "source_build": "d13f752e3b9c", "blender_version": "5.2.2", "runtime_identity": identity,
        "source_fingerprints": sources, "source_snapshot_sha256": runner.hashlib.sha256(canonical(sources)).hexdigest(),
        "binary_sha256": runner.MESH_STORAGE_EXECUTABLE_SHA256, "private_display": runner._domain_display(),
        "helper_sha256": runner.MESH_STORAGE_HELPER_SHA256,
        "transport": {"host": "127.0.0.1", "socket_json": True, "runtime_timer_queue": True, "direct_dispatch": False, "manual_scheduler_drain": False},
        "resources": {"available_memory_bytes": 2 * 1024**3}, "hardware": {"platform": "modeled Linux; not native evidence"},
        "seconds": 1., "assertions": dict.fromkeys(runner.MESH_STORAGE_ASSERTIONS, True),
        "cases": {"two_rows": positive, "recovery": recovery}, "native_trace": trace, "limitations": dict(runner.MESH_STORAGE_LIMITS)}
    return report, mesh_storage_other_phase_model(runner, full, phase) if phase != "success" else full


def mesh_storage_write_receipt(runner, report, full):
    raw = json.dumps(full, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    report.write_bytes(raw)
    keys = {"schema", "completed", "phase", "process_id", "process_instance", "runtime_nonce", "source_build",
            "blender_version", "source_snapshot_sha256", "binary_sha256"}
    compact = {key: full[key] for key in keys}
    compact["full_receipt"] = {"path": str(report), "bytes": len(raw), "sha256": runner.hashlib.sha256(raw).hexdigest()}
    return compact


@pytest.mark.parametrize("version", ["5.2.2", "5.2.2 LTS"])
def test_mesh_storage_positive_receipt_requires_full_native_prefix_and_real_pid(runner, monkeypatch, tmp_path, version):
    output, binary = mesh_storage_runner_root(runner, monkeypatch, tmp_path)
    bundle = output / "bundle"
    bundle.mkdir()
    class Process:
        pid = 77
        def __init__(self, command, **kwargs):
            assert "--background" not in command and "--disable-autoexec" in command
            assert kwargs["cwd"].is_relative_to(output) and kwargs["start_new_session"]
            assert kwargs["env"]["BRIDGE_TEST_PRIVATE_UI_MANIFEST"] == "owned-selector"
            report, full = mesh_storage_full_model(runner, command, kwargs["env"], self.pid)
            full["blender_version"] = version
            compact = mesh_storage_write_receipt(runner, report, full)
            kwargs["stdout"].write((runner.MESH_STORAGE_MARKER + json.dumps(compact)).encode())
        def wait(self, timeout):
            assert timeout == 300
            return 0
    monkeypatch.setenv("BRIDGE_TEST_PRIVATE_UI_MANIFEST", "owned-selector")
    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    sources = runner._mesh_storage_sources()
    _raw, binary_binding = runner._domain_regular(binary, binary.parent, 1024**3)
    result = runner._run_process(binary, runner.MESH_STORAGE_CASE, output, 1200, phase="success", bundle=bundle,
        phase_marker=runner.MESH_STORAGE_MARKER, domain_binary=binary_binding, domain_sources=sources, domain_display=runner._domain_display())
    assert result["status"] == "passed" and result["os_process_id"] == 77
    assert result["qualification_scope"] == runner.MESH_STORAGE_LIMITS


@pytest.mark.parametrize("fault", ("missing_case", "wrong_phase", "incomplete", "wrong_pid", "boolean_pid", "wrong_nonce",
    "wrong_source", "changed_source", "wrong_binary", "wrong_helper", "wrong_version", "next_patch", "version_type", "wrong_build",
    "hostname", "direct_dispatch", "manual_scheduler",
    "claim_windows", "missing_assertion", "false_assertion", "extra_field", "wrong_scope", "missing_exit_flag",
    "dropped_event", "wrong_counter", "late_native", "missing_interval", "failed_interval", "two_rows_one_turn",
    "image_pixel_drift", "image_color_drift", "packed_drift", "object_drift", "mesh_drift", "uv_clone_drift",
    "wrong_uv_roles", "nan_pixels", "dropped_array", "dropped_journal_row", "wrong_row_hash", "return_without_entry",
    "unverified_row", "fake_owner", "terminal_owner", "no_undo_confirm", "unsafe_undo_claim", "timeout", "exit",
    "dropped_ARRAY_header", "dropped_SINGLE_header", "extra_ARRAY_header", "wrong_header_type", "wrong_header_count",
    "duplicate_header", "unknown_header_storage", "SINGLE_payload", "claim_SINGLE_logical"))
def test_mesh_storage_refuses_forged_receipt_or_incomplete_native_prefix(runner, monkeypatch, tmp_path, fault):
    output, binary = mesh_storage_runner_root(runner, monkeypatch, tmp_path)
    bundle = output / "bundle"
    bundle.mkdir()
    class Process:
        pid = 77
        def __init__(self, command, **kwargs):
            report, full = mesh_storage_full_model(runner, command, kwargs["env"], self.pid)
            positive = full["cases"]["two_rows"]["evidence"]
            trace = full["native_trace"]
            if fault == "missing_case":
                full["cases"].pop("recovery")
            elif fault == "wrong_phase":
                full["phase"] = "cancel"
            elif fault == "incomplete":
                full["completed"] = False
            elif fault == "wrong_pid":
                full["process_id"] += 1
            elif fault == "boolean_pid":
                full["process_id"] = True
            elif fault == "wrong_nonce":
                full["runtime_nonce"] = "0" * 32
            elif fault == "wrong_source":
                full["source_fingerprints"]["addon/blender_codex_bridge/scene_jobs.py"] = "0" * 64
            elif fault == "changed_source":
                (runner.ROOT / "addon/blender_codex_bridge/scene_jobs.py").write_text("# late source change\n")
            elif fault == "wrong_binary":
                full["binary_sha256"] = "0" * 64
            elif fault == "wrong_helper":
                full["helper_sha256"] = "0" * 64
            elif fault == "wrong_version":
                full["blender_version"] = "5.2.2 Alpha"
            elif fault == "next_patch":
                full["blender_version"] = "5.2.3 LTS"
            elif fault == "version_type":
                full["blender_version"] = [5, 2, 2]
            elif fault == "wrong_build":
                full["source_build"] = "62c1db4208e8"
            elif fault == "hostname":
                full["transport"]["host"] = "localhost"
            elif fault in {"direct_dispatch", "manual_scheduler"}:
                full["transport"]["direct_dispatch" if fault == "direct_dispatch" else "manual_scheduler_drain"] = True
            elif fault == "claim_windows":
                full["limitations"]["windows"] = True
            elif fault == "missing_assertion":
                full["assertions"].pop("selected_active_mesh")
            elif fault == "false_assertion":
                full["assertions"]["selected_active_mesh"] = False
            elif fault == "extra_field":
                full["hidden_claim"] = True
            elif fault == "wrong_scope":
                trace["scope"] = "ALL_BLENDER_NATIVE_CALLS"
            elif fault == "missing_exit_flag":
                trace.pop("prepare_exit_counts_include_exception")
            elif fault == "dropped_event":
                trace["events"].pop(3)
            elif fault == "wrong_counter":
                trace["counts"]["native_entries"] = trace["counts"]["native_returns"] = 99
            elif fault == "late_native":
                trace["counts"]["after_accepted_stop_native_entries"] = 1
            elif fault == "missing_interval":
                trace["native_C_intervals"].pop()
            elif fault == "failed_interval":
                trace["native_C_intervals"][0]["returned"] = False
            elif fault == "two_rows_one_turn":
                for event in trace["events"][6:]:
                    event["turn"] = 1
            elif fault == "image_pixel_drift":
                positive["after"]["protected"]["image"]["pixels_float32_le"] = runner.struct.pack("<16f", *([.5] * 16)).hex()
            elif fault == "image_color_drift":
                positive["after"]["protected"]["image"]["color_space"] = "sRGB"
            elif fault == "packed_drift":
                positive["after"]["protected"]["image"]["packed_sha256"] = "f" * 64
            elif fault in {"object_drift", "mesh_drift"}:
                positive["after"]["object_identity" if fault == "object_drift" else "mesh_identity"][2] += 1
            elif fault == "uv_clone_drift":
                positive["after"]["uv_roles"][1][0][2] = True
            elif fault == "wrong_uv_roles":
                for stage in ("before", "after"):
                    positive[stage]["uv_roles"] = [2, [["UVSingle", True, False]]]
            elif fault == "nan_pixels":
                positive["after"]["protected"]["image"]["pixels_float32_le"] = runner.struct.pack("<16f", float("nan"), *([.25] * 15)).hex()
            elif fault == "dropped_array":
                positive["after"]["protected"]["original_ARRAY_values"] = []
            elif fault == "dropped_ARRAY_header":
                positive["after"]["protected"]["unselected_attribute_headers"].pop()
            elif fault == "dropped_SINGLE_header":
                positive["after"]["protected"]["unselected_attribute_headers"].pop(0)
            elif fault == "extra_ARRAY_header":
                positive["after"]["protected"]["unselected_attribute_headers"].append(["Extra", "EDGE", "INT", "ARRAY", 3])
            elif fault == "wrong_header_type":
                positive["after"]["protected"]["unselected_attribute_headers"][1][2] = "INT32_2D"
            elif fault == "wrong_header_count":
                positive["after"]["protected"]["unselected_attribute_headers"][1][4] = 2
            elif fault == "duplicate_header":
                headers = positive["after"]["protected"]["unselected_attribute_headers"]
                headers.append(list(headers[0]))
            elif fault == "unknown_header_storage":
                positive["after"]["protected"]["unselected_attribute_headers"][0][3] = "OTHER"
            elif fault == "SINGLE_payload":
                positive["after"]["protected"]["original_ARRAY_values"].append([".select_edge", "EDGE", "BOOLEAN", [False] * 3])
            elif fault == "claim_SINGLE_logical":
                full["limitations"]["unselected_SINGLE_logical_values"] = True
            elif fault == "dropped_journal_row":
                positive["journal"]["rows"].pop()
            elif fault == "wrong_row_hash":
                positive["journal"]["rows"][0]["logical_values_sha256"] = "f" * 64
            elif fault == "return_without_entry":
                positive["journal"]["rows"][0]["materialize_entered"] = False
            elif fault == "unverified_row":
                positive["journal"]["rows"][0]["verified"] = False
            elif fault == "fake_owner":
                full["cases"]["two_rows"]["requests"][1]["response"]["result"]["job_id"] = "job_" + "2" * 32
            elif fault == "terminal_owner":
                positive["terminal"]["job_id"] = "job_" + "2" * 32
            elif fault == "no_undo_confirm":
                full["cases"]["recovery"]["requests"][0]["request"]["params"]["confirm_global_undo"] = False
            elif fault == "unsafe_undo_claim":
                full["cases"]["recovery"]["evidence"]["recovery"][0]["safety_qualified"] = True
            compact = mesh_storage_write_receipt(runner, report, full)
            kwargs["stdout"].write((runner.MESH_STORAGE_MARKER + json.dumps(compact)).encode())
        def wait(self, timeout):
            if fault == "timeout":
                raise subprocess.TimeoutExpired("owned Blender model", timeout)
            return 1 if fault == "exit" else 0
    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    monkeypatch.setattr(runner.os, "killpg", lambda *_args: None)
    sources = runner._mesh_storage_sources()
    _raw, binary_binding = runner._domain_regular(binary, binary.parent, 1024**3)
    result = runner._run_process(binary, runner.MESH_STORAGE_CASE, output, 300, phase="success", bundle=bundle,
        phase_marker=runner.MESH_STORAGE_MARKER, domain_binary=binary_binding, domain_sources=sources, domain_display=runner._domain_display())
    assert result["status"] == ("timeout" if fault == "timeout" else "failed")


def test_mesh_storage_unqualified_binary_refuses_before_process_launch(runner, monkeypatch, tmp_path):
    output, binary = mesh_storage_runner_root(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "MESH_STORAGE_EXECUTABLE_SHA256", "bafec183e960819c76fe213c000cdb2284c53a87ef6791812f8728b51f07145b")
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_a, **_k: pytest.fail("Unsupported candidate launched"))
    result = runner.run_case(binary, runner.MESH_STORAGE_CASE, output, 300)
    assert result["status"] == "failed" and result["unsupported_binary"] is True and result["phases"] == []
    assert not result["fresh_process_verified"] and result["qualification_scope"]["blender_4_5"] is False


def mesh_storage_other_phase_model(runner, full, phase):
    """Compose independent stopped/history receipt examples, without a native run."""
    template = json.loads(json.dumps(full["cases"]["two_rows"]))
    oracle = template["evidence"]["oracle_values"]
    full["cases"] = {}
    trace = full["native_trace"]
    trace["events"], trace["stops"], trace["native_C_intervals"] = [], [], []
    trace["counts"] = dict.fromkeys(trace["counts"], 0)
    serial, turn = 0, 0

    def emit(case, job_id, kind, boundary, attribute=None):
        row = {"sequence": len(trace["events"]) + 1, "case": case, "kind": kind, "monotonic": 1. + len(trace["events"]) / 100,
            "job_id": job_id, "native_count": trace["counts"]["native_entries"],
            "provider_count": trace["counts"]["provider_entries"], "turn": turn, "attribute": attribute, "boundary": boundary}
        trace["events"].append(row)
        return row

    def case(case_name, *, state=None, completed=0, noop=False, prepared_before=False, error="NOT_IMPLEMENTED"):
        nonlocal serial, turn
        serial += 1
        row = json.loads(json.dumps(template))
        evidence = row["evidence"]
        before = mesh_storage_snapshot_model(runner, prepared=prepared_before)
        after = json.loads(json.dumps(before))
        journal = mesh_storage_journal_model(runner, oracle)
        job_id = "job_" + f"{serial:032x}"
        for index, item in enumerate(journal["rows"]):
            if index >= completed:
                journal["rows"][index] = {"name": item["name"], "helper_attached": False}
                continue
            if noop:
                for flag in ("data_lookup_entered", "data_lookup_returned", "materialize_entered", "materialize_returned"):
                    item[flag] = False
                item.update(action="NOOP_ALREADY_ARRAY", entry_kind="NOOP_ALREADY_ARRAY", before_storage="ARRAY",
                    readback_entries=0, readback_returns=0, logical_values_sha256=None, retained_physical_transition="NOOP_ALREADY_ARRAY")
            else:
                after["selected_storage"][index][3] = "ARRAY"
                after["selected_values"][item["name"]] = oracle[item["name"]]
        journal["materialization_entered"] = journal["native_lookup_entered"] = bool(completed and not noop)
        evidence.update(before=before, after=after, oracle_values=oracle,
            terminal=None, journal=None, history=[], recovery=[],
            stop_counts=dict.fromkeys(("provider_before", "provider_after", "native_before", "native_after"), 0))
        if state is None:
            request = {"id": f"denied-{serial}", "method": "mesh.attribute_storage_prepare_preview", "params": {}, "protocol_version": "1.0"}
            context = {"protected_scope_violation": True} if case_name == "protected_scope_denial" else {}
            row["requests"] = [{"request": request, "response": mesh_storage_reply(request, error={"code": error, "context": context})}]
            return row
        terminal = {"job_id": job_id, "kind": "mesh.attribute_storage_preparation", "state": state, "terminal": True,
                    "storage_effects": journal, "terminal_history_evicted": False}
        if case_name == "failure_after_second_native":
            journal["rows"][1].update(materialize_returned=False, verified=False, after_storage_observed=False,
                after_storage=None, logical_values_sha256=None, readback_entries=0, readback_returns=0,
                retained_physical_transition="ENTERED_OUTCOME_UNKNOWN")
        row["requests"] = []
        params = {"object_name": "Target", "mesh_name": "Mesh", "attribute_names": [".uv_select_face", "UVSingle"]}
        for method, arguments, result in (("mesh.attribute_storage_prepare_preview", params, {"expected_preparation_fingerprint": "c" * 64}),
            ("mesh.attribute_storage_prepare_job_start", {**params, "expected_preparation_fingerprint": "c" * 64,
             "confirm_materialize_storage": True, "confirm_retained_partial_preparation": True},
             {"accepted": True, "job_id": job_id, "kind": "mesh.attribute_storage_preparation"}),
            ("jobs.inspect", {"job_id": job_id}, terminal)):
            request = {"id": f"case-{serial}-{len(row['requests'])}", "method": method, "params": arguments,
                       "protocol_version": "1.0", "timeout_ms": 60000}
            row["requests"].append({"request": request, "response": mesh_storage_reply(request, result)})
        evidence.update(terminal=terminal, journal=journal)
        for index in range(max(1, completed)):
            turn += 1
            trace["counts"]["provider_entries"] += 1
            trace["counts"]["provider_returns"] += 1
            emit(case_name, job_id, "turn_enter", "scene_turn")
            if index < completed:
                attribute = (".uv_select_face", "UVSingle")[index]
                trace["counts"]["prepare_entries"] += 1
                emit(case_name, job_id, "prepare_enter", "helper_prepare", attribute)
                if not noop:
                    trace["counts"]["native_entries"] += 1
                    trace["counts"]["materialize_entries"] += 1
                    emit(case_name, job_id, "materialize_enter", "helper_prepare_C_foreach", attribute)
                    trace["counts"]["native_returns"] += 1
                    trace["counts"]["materialize_returns"] += 1
                    emit(case_name, job_id, "materialize_return", "helper_prepare_C_foreach", attribute)
                    trace["native_C_intervals"].append({"case": case_name, "attribute": attribute, "seconds": .001, "returned": True})
                trace["counts"]["prepare_returns"] += 1
                emit(case_name, job_id, "prepare_return", "helper_prepare", attribute)
            emit(case_name, job_id, "turn_return", "scene_turn")
        if state != "SUCCEEDED":
            event = emit(case_name, job_id, "stop_accepted", "job_stop")
            trace["stops"].append({"case": case_name, "job_id": job_id, "accepted_sequence": event["sequence"],
                "native_at_accept": event["native_count"], "provider_at_accept": event["provider_count"], "kind": "MODELED_MAIN_THREAD_ACCEPTANCE"})
            evidence["stop_counts"] = {"native_before": event["native_count"], "native_after": event["native_count"],
                "provider_before": event["provider_count"], "provider_after": event["provider_count"]}
        return row

    if phase == "cancel":
        full["cases"] = {"cancel_after_first": case("cancel_after_first", state="CANCELLED", completed=1)}
    elif phase == "native_failure":
        full["cases"] = {"failure_after_second_native": case("failure_after_second_native", state="FAILED", completed=2)}
    elif phase == "adversarial":
        for name in ("permission_denial", "invalid_context", "stale_preview", "protected_scope_denial"):
            full["cases"][name] = case(name, error={"permission_denial": "PERMISSION_DENIED", "protected_scope_denial": "INVALID_ARGUMENT"}.get(name, "NOT_IMPLEMENTED"))
        for name in ("undelivered", "pause_revoke", "disconnect"):
            full["cases"][name] = case(name, state="FAILED" if name == "pause_revoke" else "CANCELLED", completed=1 if name == "disconnect" else 0)
    elif phase == "history_eviction":
        seed = case("seed_cancel", state="CANCELLED", completed=1, noop=True, prepared_before=True)
        seed["evidence"]["history_setup_explicit_ARRAY"] = True
        rows = [case("history_eviction", state="SUCCEEDED", completed=2, noop=True, prepared_before=True) for _ in range(33)]
        retained = json.loads(json.dumps(seed["evidence"]["terminal"]))
        retained["terminal_history_evicted"] = True
        history = json.loads(json.dumps(seed))
        history["requests"] = [exchange for row in rows for exchange in row["requests"]]
        request = {"id": "retained-seed-inspect", "method": "jobs.inspect", "params": {"job_id": retained["job_id"]}, "protocol_version": "1.0"}
        history["requests"].append({"request": request, "response": mesh_storage_reply(request, retained)})
        history["evidence"].update(terminal=retained, journal=retained["storage_effects"],
            history=[{"job_evidence": {"job_id": retained["job_id"], "storage_effects": retained["storage_effects"]}}],
            recovery=[{"summary": retained}], stop_counts=dict.fromkeys(("provider_before", "provider_after", "native_before", "native_after"), 0))
        full["cases"] = {"seed_cancel": seed, "history_eviction": history}
    else:
        raise AssertionError("Unexpected composition-model phase")
    return full


@pytest.mark.parametrize("failure", (None, "cancel_exit", "native_failure_timeout", "reused_pid", "reused_nonce"))
def test_mesh_storage_five_fresh_factory_phases_stop_at_first_failure(runner, monkeypatch, tmp_path, failure):
    output, binary = mesh_storage_runner_root(runner, monkeypatch, tmp_path)
    phases = []
    class Process:
        def __init__(self, command, **kwargs):
            self.phase = command[command.index("--bridge-phase") + 1]
            self.pid = 77 if failure == "reused_pid" else 77 + len(phases)
            phases.append(self.phase)
            assert "--factory-startup" in command and "--disable-autoexec" in command and "--background" not in command
            assert kwargs["env"]["BLENDER_USER_CONFIG"].endswith("worker-profile-blender_user_config")
            assert "PYTHONPATH" not in kwargs["env"] and kwargs["cwd"].is_relative_to(output)
            report, full = mesh_storage_full_model(runner, command, kwargs["env"], self.pid)
            if failure == "reused_nonce" and self.phase == "cancel":
                full["runtime_nonce"] = "f" * 32  # Independent identity digest refuses this lie.
            compact = mesh_storage_write_receipt(runner, report, full)
            kwargs["stdout"].write((runner.MESH_STORAGE_MARKER + json.dumps(compact)).encode())
        def wait(self, timeout):
            if timeout == 10:
                return -9
            assert timeout == 300
            if failure == "native_failure_timeout" and self.phase == "native_failure":
                raise subprocess.TimeoutExpired("owned process model", timeout)
            return 1 if failure == "cancel_exit" and self.phase == "cancel" else 0
    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    monkeypatch.setattr(runner.os, "killpg", lambda *_args: None)
    result = runner.run_case(binary, runner.MESH_STORAGE_CASE, output, 1200)
    if failure is None:
        assert result["status"] == "passed" and result["fresh_process_verified"], result
        assert phases == list(runner.MESH_STORAGE_PHASES)
        assert len({row["os_process_id"] for row in result["phases"]}) == 5
        assert len({row["process_instance"] for row in result["phases"]}) == 5
        assert len({row["command"][row["command"].index("--bridge-bundle") + 1] for row in result["phases"]}) == 5
    else:
        assert result["status"] in {"failed", "timeout"} and not result["fresh_process_verified"]
        expected = ["success", "cancel", "native_failure"] if failure == "native_failure_timeout" else ["success", "cancel"]
        assert phases == expected


def test_mesh_storage_qualifier_accepts_actual_product_contract_methods(runner, monkeypatch, tmp_path, addon_package):
    import importlib
    contract = importlib.import_module(addon_package + ".mesh_storage_contract")
    output, binary = mesh_storage_runner_root(runner, monkeypatch, tmp_path)
    report = output / "mesh-storage-job.json"
    command = [str(binary), "--bridge-phase", "success", "--bridge-report", str(report)]
    _report, full = mesh_storage_full_model(runner, command, {"BRIDGE_TEST_PROCESS_TOKEN": "a" * 32}, 77)
    exchanges = full["cases"]["two_rows"]["requests"]
    # The producer uses these product constants rather than runner literals.
    # Feed the actual contract into the validator to detect independent drift.
    exchanges[0]["request"]["method"] = contract.PREVIEW
    exchanges[1]["request"]["method"] = contract.START
    parsed = runner._mesh_storage_requests(exchanges)
    assert parsed is not None and set(parsed[0]) == set(parsed[1]) == {"job_" + "1" * 32}
    exchanges[1]["request"]["method"] = "mesh.attribute_storage_prepare_start"
    assert runner._mesh_storage_requests(exchanges) is None
