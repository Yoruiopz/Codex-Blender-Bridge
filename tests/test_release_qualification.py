"""Synthetic evidence exercises the gate; none of these fixtures are release evidence."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts import qualify_release as gate


def write_json(path: Path, data: dict) -> dict:
    path.write_text(json.dumps(data), encoding="utf-8")
    return {"path": str(path), "sha256": gate.sha256(path)}


@pytest.fixture
def evidence(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    files = {
        "pyproject.toml": 'version = "1.0.0"\n',
        "addon/blender_codex_bridge/__init__.py": 'bl_info = {"version": (1, 0, 0)}\n',
        "addon/blender_codex_bridge/constants.py": "ADDON_VERSION = (1, 0, 0)\n",
        "addon/blender_codex_bridge/blender_manifest.toml": 'version = "1.0.0"\n',
        "mcp_server/__init__.py": '__version__ = "1.0.0"\n',
        "plugins/blender-codex-bridge/.codex-plugin/plugin.json": '{"name":"blender-codex-bridge","version":"1.0.0"}',
    }
    files.update({f"scripts/{filename}": "# synthetic fixture\n" for filename, _ in gate.run_blender_checks.CASES.values()})
    for filename, content in files.items():
        path = source / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for command in (
        ["git", "init", "-q"], ["git", "config", "core.autocrlf", "false"], ["git", "add", "."],
        ["git", "-c", "user.name=Synthetic Test", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Synthetic release fixture"],
    ):
        subprocess.run(command, cwd=source, check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True).stdout.strip()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    packages = {}
    for key, filename, folder, prefix in (
        ("addon", "blender_codex_bridge-1.0.0.zip", "addon/blender_codex_bridge", "blender_codex_bridge/"),
        ("mcp", "blender_codex_bridge-1.0.0-py3-none-any.whl", "mcp_server", "mcp_server/"),
        ("plugin", "blender-codex-bridge-plugin-1.0.0.zip", "plugins/blender-codex-bridge", "blender-codex-bridge/"),
    ):
        path = bundle / filename
        with ZipFile(path, "w") as archive:
            for member in (source / folder).rglob("*"):
                if member.is_file():
                    archive.write(member, prefix + member.relative_to(source / folder).as_posix())
            if key == "mcp":
                archive.writestr("blender_codex_bridge-1.0.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: blender-codex-bridge\nVersion: 1.0.0\n")
        packages[key] = {"path": str(path), "sha256": gate.sha256(path)}
    sums = bundle / "SHA256SUMS.txt"
    sums.write_text("".join(f"{entry['sha256']}  {Path(entry['path']).name}\n" for entry in packages.values()), encoding="utf-8")
    packages["checksums"] = {"path": str(sums), "sha256": gate.sha256(sums)}
    inventory = gate.source_inventory(source)
    artifact = bundle / "synthetic-artifact.txt"
    artifact.write_text("Explicitly synthetic retained test evidence", encoding="utf-8")
    artifact_ref = {"path": str(artifact), "sha256": gate.sha256(artifact)}
    common = {
        "schema_version": 1, "commit": commit, "source_sha256": gate.inventory_digest(inventory),
        "package_sha256": {key: value["sha256"] for key, value in packages.items()},
        "artifacts": [artifact_ref],
    }
    review = {
        "status": "accepted", "structured_tools": True, "reviewed_by": "Synthetic test reviewer",
        "checks": dict.fromkeys(gate.CHECKS, "passed"), "visual_evidence": [artifact_ref],
    }
    ledger = {
        "schema_version": 1, "target_version": "1.0.0", "commit": commit,
        "source_sha256": common["source_sha256"], "source_files": inventory,
        "support": {"os": "Windows 11", "blender_lts": "4.5.1", "blender_stable": "5.1.2"},
        "packages": packages, "requirements": {}, "installed_scenarios": [],
    }
    for requirement in gate.REQUIREMENTS:
        receipt = {**common, **review, "kind": "requirement_acceptance", "requirement_id": requirement}
        reference = write_json(bundle / f"{requirement}.json", receipt)
        ledger["requirements"][requirement] = {"status": "accepted", "evidence": [reference]}
    quality = {
        **common, "kind": "quality_matrix",
        "matrix": [{"python": python, "mcp": mcp, "status": "passed"} for python in ("3.10", "3.11", "3.12") for mcp in ("2.0.0", "2.2.0")],
        "checks": dict.fromkeys(("lint", "typing", "compileall", "inventory", "diff", "packages", "checksums"), "passed"),
    }
    ledger["quality_matrix"] = write_json(bundle / "quality.json", quality)
    results, logs = [], []
    for version in ("4.5.1", "5.1.2"):
        executable = f"C:/Blender/{version}/blender.exe"
        for case, (script, marker) in gate.run_blender_checks.CASES.items():
            phased = case in gate.run_blender_checks.PHASED_CASES
            processes = []
            markers = gate.run_blender_checks.PHASED_CASES[case] if phased else (marker,)
            for index, process_marker in enumerate(markers):
                phase = ("writer", "reader")[index] if phased else None
                token = f"synthetic-{version}-{case}-{phase}"
                payload = {"blender_version": version}
                if phase:
                    payload.update(phase=phase, process_instance=token, process_id=123)
                if not process_marker.endswith(" "):
                    payload[process_marker] = "PASS"
                log = bundle / f"{version}-{case}-{phase}.log"
                log.write_text((process_marker if process_marker.endswith(" ") else "") + json.dumps(payload) + "\n", encoding="utf-8")
                logs.append({"case": case, "phase": phase, "blender_executable": executable, "artifact": {"path": str(log), "sha256": gate.sha256(log)}})
                processes.append({"case": case, "phase": phase, "process_instance": token, "script_sha256": inventory[f"scripts/{script}"], "status": "passed", "exit_code": 0, "blender_executable": executable, "blender_version": version, "evidence": payload, "execution_mode": "private_windows_desktop" if case in gate.run_blender_checks.INTERACTIVE_CASES else "background"})
            if phased:
                result = {key: value for key, value in processes[0].items() if key not in {"evidence", "exit_code"}}
                result.update(phases=processes, phase_sequence=["writer", "reader"], reader_started=True, fresh_process_verified=True)
                results.append(result)
            else:
                results.append(processes[0])
        for scenario in gate.SCENARIOS:
            receipt = {
                **common, **review, "kind": "installed_scenario", "scenario": scenario,
                "blender_version": version, "platform": {"system": "Windows", "release": "11"},
                "installed_packages": True, "source_checkout_imports": False,
                "upgrade_from": "0.3.0", "rollback_verified": True,
            }
            ledger["installed_scenarios"].append(write_json(bundle / f"{version}-{scenario}.json", receipt))
    native = {
        "platform": {"system": "Windows", "release": "11", "version": "synthetic", "machine": "AMD64"},
        "commit": commit, "worktree_dirty": False, "source_files": inventory,
        "source_sha256": common["source_sha256"], "release_readiness": "NOT_ASSESSED",
        "checks_passed": True, "all_cases_selected": True,
        "selected_cases": list(gate.run_blender_checks.CASES), "results": results,
    }
    native_ref = write_json(bundle / "native-report.json", native)
    ledger["native_matrices"] = [write_json(bundle / "native-receipt.json", {**common, "kind": "native_matrix", "platform": {"system": "Windows", "release": "11"}, "report": native_ref, "logs": logs})]
    ledger_path = bundle / "ledger.json"
    write_json(ledger_path, ledger)
    return source, ledger_path, ledger


def run(evidence):
    source, ledger_path, ledger = evidence
    write_json(ledger_path, ledger)
    return gate.Qualification(ledger_path, source).run()


def rewrite_receipt(reference: dict, change) -> None:
    path = Path(reference["path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    reference.update(write_json(path, data))


def test_complete_synthetic_bundle_qualifies(evidence) -> None:
    assert run(evidence)["release_readiness"] == "READY"


def test_committed_template_is_unready() -> None:
    result = gate.Qualification(gate.ROOT / "docs/release-1.0-ledger.json", gate.ROOT).run()
    assert result["release_readiness"] == "NOT_READY"
    assert any("requirement PAINT-01: still open" in blocker for blocker in result["blockers"])


@pytest.mark.parametrize("mutation,expected", [
    (lambda ledger: ledger["requirements"].pop("PAINT-01"), "mandatory requirement"),
    (lambda ledger: ledger["requirements"]["REC-01"].update(status="implemented"), "REC-01: still open"),
    (lambda ledger: ledger["requirements"]["SIM-01"].update(evidence=[]), "SIM-01: evidence required"),
    (lambda ledger: ledger.update(commit="a" * 40), "ledger commit"),
    (lambda ledger: ledger.update(source_sha256="b" * 64), "ledger source digest"),
    (lambda ledger: ledger["source_files"].clear(), "ledger source inventory"),
    (lambda ledger: ledger.update(native_matrices=[]), "native matrix evidence"),
    (lambda ledger: ledger["installed_scenarios"].pop(), "installed A-F acceptance"),
    (lambda ledger: ledger["support"].update(blender_stable="5.2.0-alpha"), "select exact Blender"),
    (lambda ledger: ledger.update(schema_version=True), "unsupported ledger schema"),
])
def test_missing_or_stale_coverage_blocks(evidence, mutation, expected) -> None:
    mutation(evidence[2])
    assert any(expected in blocker for blocker in run(evidence)["blockers"])


@pytest.mark.parametrize("change,expected", [
    (lambda data: data.update(commit="a" * 40), "commit mismatch"),
    (lambda data: data.update(package_sha256={}), "package hashes mismatch"),
    (lambda data: data.update(structured_tools=False), "structured-tool workflow"),
    (lambda data: data["checks"].update(recovery=True), "all success/failure"),
    (lambda data: data.update(visual_evidence=[]), "reviewed visual artifacts"),
    (lambda data: data.update(reviewed_by=" "), "named reviewer"),
])
def test_acceptance_needs_actual_review_fields(evidence, change, expected) -> None:
    reference = evidence[2]["requirements"]["PAINT-01"]["evidence"][0]
    rewrite_receipt(reference, change)
    assert any(expected in blocker for blocker in run(evidence)["blockers"])


def test_hash_mismatch_and_dirty_checkout_block(evidence) -> None:
    (evidence[0] / "untracked.txt").write_text("unexpected", encoding="utf-8")
    reference = evidence[2]["installed_scenarios"][0]
    Path(reference["path"]).write_text("{}", encoding="utf-8")
    blockers = run(evidence)["blockers"]
    assert any("checkout must be clean" in item for item in blockers)
    assert any("hash mismatch" in item for item in blockers)


@pytest.mark.parametrize("change,expected", [
    (lambda report: report.update(worktree_dirty=True), "clean exact-commit"),
    (lambda report: report.update(platform={"system": "Linux", "release": "6"}), "native report must identify Windows 11"),
    (lambda report: report.update(all_cases_selected=False), "incomplete/failing native"),
    (lambda report: report["results"].pop(), "missing/duplicate cases"),
    (lambda report: report["results"][0].update(status="timeout"), "native success evidence"),
    (lambda report: report["results"][0].update(exit_code=False), "native success evidence"),
    (lambda report: report["results"][0].update(script_sha256="a" * 64), "fixture source mismatch"),
    (lambda report: report["results"][0].update(execution_mode="interactive_display"), "execution isolation"),
    (lambda report: report.update(release_readiness="READY"), "must remain NOT_ASSESSED"),
])
def test_native_requires_complete_clean_current_source_matrix(evidence, change, expected) -> None:
    receipt_ref = evidence[2]["native_matrices"][0]
    def modify(receipt):
        rewrite_receipt(receipt["report"], change)
    rewrite_receipt(receipt_ref, modify)
    assert any(expected in blocker for blocker in run(evidence)["blockers"])


def test_native_success_flags_cannot_replace_retained_log(evidence) -> None:
    rewrite_receipt(evidence[2]["native_matrices"][0], lambda receipt: receipt.update(logs=[]))
    assert any("retained hashed log" in blocker for blocker in run(evidence)["blockers"])


def test_partial_quality_matrix_blocks(evidence) -> None:
    rewrite_receipt(evidence[2]["quality_matrix"], lambda receipt: receipt["matrix"].pop())
    assert any("all six Python/MCP" in blocker for blocker in run(evidence)["blockers"])


def test_failed_quality_entries_cannot_be_hidden_beside_passing_matrix(evidence) -> None:
    rewrite_receipt(evidence[2]["quality_matrix"], lambda receipt: receipt["matrix"].append({"python": "3.10", "mcp": "2.0.0", "status": "failed"}))
    assert any("failed/extra entries are not discarded" in blocker for blocker in run(evidence)["blockers"])


def test_source_imports_and_missing_upgrade_recovery_block(evidence) -> None:
    reference = evidence[2]["installed_scenarios"][-1]
    rewrite_receipt(reference, lambda receipt: receipt.update(source_checkout_imports=True, rollback_verified=False))
    blockers = run(evidence)["blockers"]
    assert any("exclude source imports" in blocker for blocker in blockers)
    assert any("upgrade and rollback" in blocker for blocker in blockers)


def test_malformed_nested_evidence_fails_closed(evidence) -> None:
    rewrite_receipt(evidence[2]["quality_matrix"], lambda receipt: receipt.update(matrix=[{"python": [], "mcp": {}, "status": "passed"}] * 6))
    result = run(evidence)
    assert result["release_readiness"] == "NOT_READY"
    assert any("invalid evidence structure" in blocker for blocker in result["blockers"])


def test_cli_template_exits_nonzero_with_machine_readable_blockers() -> None:
    completed = subprocess.run([gate.sys.executable, str(gate.ROOT / "scripts/qualify_release.py")], capture_output=True, text=True, check=False)
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["release_readiness"] == "NOT_READY"


def test_mismatched_package_source_and_checksums_are_rejected(evidence) -> None:
    source, ledger_path, ledger = evidence
    addon = Path(ledger["packages"]["addon"]["path"])
    with ZipFile(addon, "w") as archive:
        archive.writestr("blender_codex_bridge/__init__.py", 'bl_info = {"version": (1, 0, 0)}\n# different source')
        archive.writestr("blender_codex_bridge/constants.py", 'ADDON_VERSION = (1, 0, 0)\n')
        archive.writestr("blender_codex_bridge/blender_manifest.toml", 'version = "1.0.0"')
    ledger["packages"]["addon"]["sha256"] = gate.sha256(addon)
    check = gate.Qualification(ledger_path, source)
    check.check_packages(ledger)
    assert any("packaged source differs" in item for item in check.blockers)
    assert any("SHA256SUMS.txt" in item for item in check.blockers)


def test_native_log_marker_is_checked_even_when_rehashed(evidence) -> None:
    def remove_marker(receipt):
        artifact = receipt["logs"][0]["artifact"]
        path = Path(artifact["path"])
        path.write_text("Blender exited without a success marker", encoding="utf-8")
        artifact["sha256"] = gate.sha256(path)
    rewrite_receipt(evidence[2]["native_matrices"][0], remove_marker)
    assert any("success marker differs" in blocker for blocker in run(evidence)["blockers"])


@pytest.mark.parametrize("change,expected", [
    (lambda result: result.update(phases=[]), "both process phases"),
    (lambda result: result.update(fresh_process_verified=False), "verified writer/reader sequence"),
    (lambda result: result["phases"][1].update(process_instance=result["phases"][0]["process_instance"]), "distinct process instances"),
    (lambda result: result["phases"][0].update(exit_code=1), "native success evidence missing"),
])
def test_phased_native_evidence_cannot_be_replaced_by_parent_success(evidence, change, expected) -> None:
    def modify(receipt):
        def modify_report(report):
            result = next(result for result in report["results"] if result["case"] == "image_reopen")
            change(result)
        rewrite_receipt(receipt["report"], modify_report)
    rewrite_receipt(evidence[2]["native_matrices"][0], modify)
    assert any(expected in blocker for blocker in run(evidence)["blockers"])


def test_staging_retains_only_qualified_matching_bytes_and_evidence(evidence, tmp_path) -> None:
    source, ledger_path, ledger = evidence
    qualification = gate.Qualification(ledger_path, source)
    result = qualification.run()
    output = tmp_path / "staged"
    qualification.stage(output, result)
    assert len(list(output.iterdir())) == 6
    for package in ledger["packages"].values():
        assert gate.sha256(output / Path(package["path"]).name) == package["sha256"]
    with ZipFile(output / "release-evidence-1.0.0.zip") as archive:
        assert "ledger.json" in archive.namelist()
        assert "native-report.json" in archive.namelist()
        for path, digest in qualification.artifact_hashes.items():
            name = path.relative_to(ledger_path.parent).as_posix()
            assert gate.hashlib.sha256(archive.read(name)).hexdigest() == digest
    assert json.loads((output / "qualification.json").read_text())["evidence_archive_sha256"] == gate.sha256(output / "release-evidence-1.0.0.zip")


@pytest.mark.parametrize("changed", ["package", "evidence"])
def test_changed_bytes_cannot_be_staged_for_publication(evidence, tmp_path, changed) -> None:
    source, ledger_path, ledger = evidence
    qualification = gate.Qualification(ledger_path, source)
    result = qualification.run()
    path = ledger["packages"]["addon"]["path"] if changed == "package" else ledger["installed_scenarios"][0]["path"]
    Path(path).write_text("changed after acceptance", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after qualification"):
        qualification.stage(tmp_path / "staged", result)


def test_unqualified_release_never_stages_assets(evidence, tmp_path) -> None:
    source, ledger_path, ledger = evidence
    ledger["installed_scenarios"] = []
    write_json(ledger_path, ledger)
    qualification = gate.Qualification(ledger_path, source)
    result = qualification.run()
    output = tmp_path / "staged"
    with pytest.raises(ValueError, match="cannot stage an unqualified"):
        qualification.stage(output, result)
    assert not output.exists()


def test_external_artifact_cannot_escape_retained_bundle(evidence, tmp_path) -> None:
    artifact = tmp_path / "outside.txt"
    artifact.write_text("outside retained bundle", encoding="utf-8")
    reference = evidence[2]["installed_scenarios"][0]
    rewrite_receipt(reference, lambda receipt: receipt.update(artifacts=[{"path": str(artifact), "sha256": gate.sha256(artifact)}]))
    assert any("inside the retained evidence bundle" in blocker for blocker in run(evidence)["blockers"])


def test_staging_refuses_source_and_evidence_directories(evidence) -> None:
    source, ledger_path, _ = evidence
    qualification = gate.Qualification(ledger_path, source)
    result = qualification.run()
    for output in (source / "staged", ledger_path.parent / "staged"):
        with pytest.raises(ValueError, match="outside the source and evidence"):
            qualification.stage(output, result)


def test_wheel_cannot_hide_unqualified_executable_payload(evidence) -> None:
    source, ledger_path, ledger = evidence
    wheel = Path(ledger["packages"]["mcp"]["path"])
    with ZipFile(wheel, "a") as archive:
        archive.writestr("unexpected_startup.pth", "import unexpected_module\n")
    ledger["packages"]["mcp"]["sha256"] = gate.sha256(wheel)
    qualification = gate.Qualification(ledger_path, source)
    qualification.check_packages(ledger)
    assert any("unexpected wheel payload" in blocker for blocker in qualification.blockers)


@pytest.mark.parametrize("case", ["core", "image_reopen"])
def test_native_version_labels_cannot_relabel_actual_success_logs(evidence, case) -> None:
    def modify(receipt):
        phase = "writer" if case == "image_reopen" else None
        log = next(log for log in receipt["logs"] if log["case"] == case and log.get("phase") == phase)
        path = Path(log["artifact"]["path"])
        path.write_text(path.read_text().replace('"blender_version": "4.5.1"', '"blender_version": "4.3.2"'), encoding="utf-8")
        log["artifact"]["sha256"] = gate.sha256(path)
        def modify_report(report):
            result = next(result for result in report["results"] if result["case"] == case)
            process = result["phases"][0] if phase else result
            process["evidence"]["blender_version"] = "4.3.2"
        rewrite_receipt(receipt["report"], modify_report)
    rewrite_receipt(evidence[2]["native_matrices"][0], modify)
    assert any("success payload version differs" in blocker for blocker in run(evidence)["blockers"])


def test_ignored_uncommitted_source_cannot_be_attributed_to_clean_commit(evidence) -> None:
    source, ledger_path, ledger = evidence
    (source / ".git/info/exclude").write_text("mcp_server/ignored_extra.py\n", encoding="utf-8")
    (source / "mcp_server/ignored_extra.py").write_text("# uncommitted executable source", encoding="utf-8")
    ledger["source_files"] = gate.source_inventory(source)
    ledger["source_sha256"] = gate.inventory_digest(ledger["source_files"])
    qualification = gate.Qualification(ledger_path, source)
    qualification.check_provenance(ledger)
    assert any("must match committed Git blobs" in blocker for blocker in qualification.blockers)
    assert not any("checkout must be clean" in blocker for blocker in qualification.blockers)


def test_assume_unchanged_source_cannot_hide_different_committed_bytes(evidence) -> None:
    source, ledger_path, ledger = evidence
    subprocess.run(["git", "update-index", "--assume-unchanged", "mcp_server/__init__.py"], cwd=source, check=True)
    (source / "mcp_server/__init__.py").write_text('__version__ = "1.0.0"\n# hidden change\n', encoding="utf-8")
    ledger["source_files"] = gate.source_inventory(source)
    ledger["source_sha256"] = gate.inventory_digest(ledger["source_files"])
    qualification = gate.Qualification(ledger_path, source)
    qualification.check_provenance(ledger)
    assert any("must match committed Git blobs" in blocker for blocker in qualification.blockers)
