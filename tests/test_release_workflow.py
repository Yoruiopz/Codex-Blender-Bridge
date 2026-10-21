"""Execute publication guard snippets with synthetic GitHub replies, never publish."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/release-1.0.yml"
COMMIT = "a" * 40


def script(step: str) -> str:
    contents = WORKFLOW.read_text(encoding="utf-8").split(f"- name: {step}\n", 1)[1]
    body = contents.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(body)


def execute(step: str) -> None:
    exec(compile(script(step), str(WORKFLOW), "exec"), {})


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv("RELEASE_COMMIT", COMMIT)
    monkeypatch.setenv("EVIDENCE_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_REPOSITORY", "synthetic/fixture")
    return monkeypatch


@pytest.mark.parametrize("target,passes", [(COMMIT, True), ("b" * 40, False)])
def test_existing_tag_must_resolve_to_accepted_commit(environment, target, passes) -> None:
    environment.setattr(subprocess, "check_output", lambda *args, **kwargs: json.dumps({"object": {"type": "commit", "sha": target}}))
    if passes:
        execute("Require existing tag at the accepted commit")
    else:
        with pytest.raises(SystemExit, match="another commit"):
            execute("Require existing tag at the accepted commit")


def test_annotated_tag_is_dereferenced_without_mutation(environment) -> None:
    calls = []
    def reply(command, **kwargs):
        calls.append(command)
        return json.dumps({"object": {"type": "tag", "sha": "b" * 40}}) if len(calls) == 1 else json.dumps({"object": {"type": "commit", "sha": COMMIT}})
    environment.setattr(subprocess, "check_output", reply)
    execute("Require existing tag at the accepted commit")
    assert len(calls) == 2
    assert all(command[:2] == ["gh", "api"] and "--method" not in command for command in calls)


def test_missing_tag_cannot_create_a_tag(environment) -> None:
    def missing(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="HTTP 404")
    environment.setattr(subprocess, "check_output", missing)
    with pytest.raises(subprocess.CalledProcessError):
        execute("Require existing tag at the accepted commit")


@pytest.mark.parametrize("run,passes", [
    ({"head_sha": COMMIT, "conclusion": "success"}, True),
    ({"head_sha": "b" * 40, "conclusion": "success"}, False),
    ({"head_sha": COMMIT, "conclusion": "failure"}, False),
])
def test_evidence_producer_must_be_successful_same_commit(environment, run, passes) -> None:
    environment.setattr(subprocess, "check_output", lambda command, **kwargs: COMMIT if command[0] == "git" else json.dumps(run))
    if passes:
        execute("Verify exact-commit evidence producer")
    else:
        with pytest.raises(SystemExit, match="successful run of this exact commit"):
            execute("Verify exact-commit evidence producer")


@pytest.mark.parametrize("changed", [False, True])
def test_uploaded_asset_hashes_are_verified_before_publication(environment, tmp_path, changed) -> None:
    expected = tmp_path / "qualified-release"
    actual = tmp_path / "downloaded-release"
    expected.mkdir()
    actual.mkdir()
    (expected / "approved.whl").write_bytes(b"accepted bytes")
    (actual / "approved.whl").write_bytes(b"changed bytes" if changed else b"accepted bytes")
    environment.setenv("RUNNER_TEMP", str(tmp_path))
    if changed:
        with pytest.raises(SystemExit, match="differ from qualification"):
            execute("Verify uploaded assets before publication")
    else:
        execute("Verify uploaded assets before publication")
