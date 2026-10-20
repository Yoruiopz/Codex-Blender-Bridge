from __future__ import annotations

import importlib.util
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
