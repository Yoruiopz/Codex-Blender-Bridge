from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
    }


@pytest.mark.parametrize("case", ["core", "undo_lifecycle", "camera_focus", "curve_sampling"])
def test_factory_fixture_bytecode_prelude_runs_before_script(runner, monkeypatch, tmp_path, case):
    monkeypatch.setattr(runner.sys, "platform", "linux")

    def run(command, **kwargs):
        expression = command.index("--python-expr")
        script = command.index("--python")
        assert expression < script
        assert command[expression + 1] == "import sys; sys.dont_write_bytecode = True"
        assert command[script + 1] == str(ROOT / "scripts" / runner.CASES[case][0])
        assert "--factory-startup" in command
        assert command[command.index("--python-exit-code") + 1] == "1"
        assert ("--background" in command) is (case not in runner.INTERACTIVE_CASES)
        marker = runner.CASES[case][1]
        kwargs["stdout"].write((marker + json.dumps({"blender_version": "5.2.2"})).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.run_case(Path("blender"), case, tmp_path, 10)["status"] == "passed"
    assert "camera_focus" in runner.OPT_IN_CASES and "camera_focus" not in runner.INTERACTIVE_CASES
    assert "curve_sampling" in runner.OPT_IN_CASES and "curve_sampling" not in runner.INTERACTIVE_CASES


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
