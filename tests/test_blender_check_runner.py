from __future__ import annotations

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
