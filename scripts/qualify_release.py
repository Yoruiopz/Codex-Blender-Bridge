"""Fail-closed qualification of retained evidence for the full-artist 1.0 release.

This reads evidence; it never runs Blender, changes readiness records, or publishes.
Native runner reports keep their independent NOT_ASSESSED verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_addon, build_release, run_blender_checks  # noqa: E402

REQUIREMENTS = (
    "EVID-01", "SAFE-01", "SAFE-02", "REC-01", "JOB-01", "EVID-02", "ASSET-01",
    "LOOK-01", "PAINT-01", "CHAR-01", "SIM-01", "UX-01", "DELIVER-01", "RC-01",
)
CHECKS = (
    "success", "permission_denial", "invalid_context", "preservation", "recovery",
    "structural", "visual",
)
SCENARIOS = tuple("ABCDEF")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _digest(stream)


def _digest(stream: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def source_inventory(source: Path) -> dict[str, str]:
    return {
        path.relative_to(source).as_posix(): sha256(path)
        for folder in ("addon", "mcp_server", "scripts")
        for path in sorted((source / folder).rglob("*.py"))
    }


def inventory_digest(inventory: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()


def committed_source_inventory(source: Path, commit: str) -> dict[str, str]:
    """Read committed blobs directly; ignored files and checkout filters cannot add code."""
    tree = subprocess.run(["git", "ls-tree", "-rz", "--full-tree", commit], cwd=source, capture_output=True, check=True, timeout=10).stdout
    objects: dict[str, str] = {}
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        _, kind, object_id = header.decode().split()
        path = raw_path.decode("utf-8")
        if kind == "blob" and path.endswith(".py") and path.split("/", 1)[0] in {"addon", "mcp_server", "scripts"}:
            objects[path] = object_id
    if not objects:
        return {}
    unique = sorted(set(objects.values()))
    data = subprocess.run(["git", "cat-file", "--batch"], cwd=source, input=("\n".join(unique) + "\n").encode(), capture_output=True, check=True, timeout=10).stdout
    offset, digests = 0, {}
    for expected in unique:
        end = data.index(b"\n", offset)
        object_id, kind, raw_size = data[offset:end].decode().split()
        size = int(raw_size)
        if object_id != expected or kind != "blob":
            raise ValueError("unexpected Git blob identity")
        start = end + 1
        digests[object_id] = hashlib.sha256(data[start:start + size]).hexdigest()
        offset = start + size + 1
    return {path: digests[object_id] for path, object_id in objects.items()}


class Qualification:
    def __init__(self, ledger: Path, source: Path) -> None:
        self.ledger_path = ledger.resolve()
        self.source = source.resolve()
        self.blockers: list[str] = []
        self.commit: str | None = None
        self.inventory = source_inventory(self.source)
        self.source_sha256 = inventory_digest(self.inventory)
        self.package_sha256: dict[str, str] = {}
        self.package_paths: dict[str, Path] = {}
        self.artifact_hashes: dict[Path, str] = {}
        self.qualified = False

    def require(self, condition: bool, message: str) -> bool:
        if not condition:
            self.blockers.append(message)
        return condition

    def json_file(self, path: Path, label: str) -> dict[str, Any]:
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("expected a JSON object")
            digest = hashlib.sha256(raw).hexdigest()
            self.require(path not in self.artifact_hashes or self.artifact_hashes[path] == digest, f"{label}: artifact changed while reading")
            self.artifact_hashes[path] = digest
            return value
        except (OSError, ValueError, RecursionError) as exc:
            self.blockers.append(f"{label}: cannot read JSON ({exc})")
            return {}

    def reference(self, value: Any, base: Path, label: str) -> Path | None:
        if not self.require(isinstance(value, dict), f"{label}: missing artifact reference"):
            return None
        if not self.require(isinstance(value.get("path"), str) and bool(value["path"]), f"{label}: missing artifact path"):
            return None
        expected = value.get("sha256")
        if not self.require(isinstance(expected, str) and SHA256.fullmatch(expected) is not None, f"{label}: invalid SHA-256"):
            return None
        path = (base / value["path"]).resolve()
        if not self.require(path.is_relative_to(self.ledger_path.parent), f"{label}: artifact must be inside the retained evidence bundle"):
            return None
        try:
            valid = path.is_file() and sha256(path) == expected
        except OSError:
            valid = False
        if not self.require(valid, f"{label}: artifact missing or hash mismatch"):
            return None
        self.require(path not in self.artifact_hashes or self.artifact_hashes[path] == expected, f"{label}: contradictory artifact hashes")
        self.artifact_hashes[path] = expected
        return path

    def receipt(self, value: Any, label: str) -> tuple[dict[str, Any], Path] | None:
        path = self.reference(value, self.ledger_path.parent, label)
        if path is None:
            return None
        data = self.json_file(path, label)
        self.require(type(data.get("schema_version")) is int and data["schema_version"] == 1, f"{label}: unsupported receipt schema")
        self.require(data.get("commit") == self.commit, f"{label}: commit mismatch")
        self.require(data.get("source_sha256") == self.source_sha256, f"{label}: source mismatch")
        self.require(data.get("package_sha256") == self.package_sha256, f"{label}: package hashes mismatch")
        artifacts = data.get("artifacts")
        if self.require(isinstance(artifacts, list) and bool(artifacts), f"{label}: retained artifacts required"):
            for index, artifact in enumerate(artifacts):
                self.reference(artifact, path.parent, f"{label} artifact {index}")
        return data, path

    def check_provenance(self, ledger: dict[str, Any]) -> None:
        try:
            self.commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=self.source, capture_output=True,
                text=True, check=True, timeout=10,
            ).stdout.strip()
            dirty = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=self.source, capture_output=True, text=True, check=True, timeout=10,
            ).stdout
            self.require(not dirty.strip(), "source checkout must be clean, including untracked files")
            committed = committed_source_inventory(self.source, self.commit)
            self.require(self.inventory == committed, "source Python paths and bytes must match committed Git blobs; ignored/uncommitted code and checkout conversions do not qualify")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            self.blockers.append(f"cannot establish clean Git provenance ({exc})")
        self.require(bool(self.commit and COMMIT.fullmatch(self.commit)), "exact 40-character Git commit required")
        self.require(ledger.get("commit") == self.commit and self.commit is not None, "ledger commit does not match checkout")
        self.require(ledger.get("source_sha256") == self.source_sha256, "ledger source digest does not match checkout")
        self.require(ledger.get("source_files") == self.inventory, "ledger source inventory does not match checkout")

    def check_packages(self, ledger: dict[str, Any]) -> None:
        expected = {
            "addon": "blender_codex_bridge-1.0.0.zip",
            "mcp": "blender_codex_bridge-1.0.0-py3-none-any.whl",
            "plugin": "blender-codex-bridge-plugin-1.0.0.zip",
            "checksums": "SHA256SUMS.txt",
        }
        packages = ledger.get("packages")
        if not self.require(isinstance(packages, dict) and set(packages) == set(expected), "all four matching release assets are required"):
            return
        paths: dict[str, Path] = {}
        for name, filename in expected.items():
            path = self.reference(packages[name], self.ledger_path.parent, f"package {name}")
            if path is not None:
                paths[name] = path
                self.package_sha256[name] = sha256(path)
                self.require(path.name == filename, f"package {name}: unexpected release filename")
        if set(paths) != set(expected):
            return
        self.package_paths = paths
        try:
            self.require(build_release.release_version(self.source) == "1.0.0", "source components must all be version 1.0.0")
            build_addon.validate_archive(paths["addon"])
            build_release.validate_wheel(paths["mcp"], "1.0.0")
            for name, folder, prefix in (
                ("addon", "addon/blender_codex_bridge", "blender_codex_bridge/"),
                ("mcp", "mcp_server", "mcp_server/"),
                ("plugin", "plugins/blender-codex-bridge", "blender-codex-bridge/"),
            ):
                self.check_archive(paths[name], self.source / folder, prefix, wheel=name == "mcp")
            lines = paths["checksums"].read_text(encoding="utf-8").splitlines()
            expected_lines = {f"{self.package_sha256[name]}  {expected[name]}" for name in ("addon", "mcp", "plugin")}
            self.require(len(lines) == 3 and set(lines) == expected_lines, "SHA256SUMS.txt must match exactly the three qualified packages")
        except (OSError, ValueError, KeyError, BadZipFile) as exc:
            self.blockers.append(f"package validation failed ({exc})")

    def check_archive(self, archive_path: Path, folder: Path, prefix: str, *, wheel: bool) -> None:
        expected = {
            prefix + path.relative_to(folder).as_posix(): sha256(path)
            for path in sorted(folder.rglob("*"))
            if path.is_file() and not any(part in {"__pycache__", ".agents"} for part in path.relative_to(folder).parts)
            and path.suffix != ".pyc"
        }
        with ZipFile(archive_path) as archive:
            names = archive.namelist()
            self.require(len(names) == len(set(names)), f"{archive_path.name}: duplicate archive members")
            self.require(archive.testzip() is None, f"{archive_path.name}: corrupt archive")
            self.require(all(not name.startswith("/") and ".." not in name.split("/") and "\\" not in name for name in names), f"{archive_path.name}: unsafe archive paths")
            if wheel:
                self.require(all(name.startswith(prefix) or name.startswith("blender_codex_bridge-1.0.0.dist-info/") for name in names), f"{archive_path.name}: unexpected wheel payload outside package/metadata")
            actual = {
                name: hashlib.sha256(archive.read(name)).hexdigest()
                for name in names if not name.endswith("/") and (not wheel or name.startswith(prefix))
            }
        self.require(actual == expected, f"{archive_path.name}: packaged source differs from qualified checkout")

    def check_review(self, data: dict[str, Any], path: Path, label: str) -> None:
        self.require(data.get("status") == "accepted", f"{label}: not accepted")
        self.require(data.get("structured_tools") is True, f"{label}: structured-tool workflow evidence required")
        self.require(isinstance(data.get("reviewed_by"), str) and bool(data["reviewed_by"].strip()), f"{label}: named reviewer required")
        checks = data.get("checks")
        self.require(isinstance(checks, dict) and all(checks.get(key) == "passed" for key in CHECKS), f"{label}: all success/failure/preservation/recovery/visual checks must pass")
        visual = data.get("visual_evidence")
        if self.require(isinstance(visual, list) and bool(visual), f"{label}: reviewed visual artifacts required"):
            for index, artifact in enumerate(visual):
                self.reference(artifact, path.parent, f"{label} visual {index}")

    def check_quality(self, ledger: dict[str, Any]) -> None:
        receipt = self.receipt(ledger.get("quality_matrix"), "quality matrix")
        if receipt is None:
            return
        data, _ = receipt
        self.require(data.get("kind") == "quality_matrix", "quality matrix: wrong receipt kind")
        expected = {(python, mcp) for python in ("3.10", "3.11", "3.12") for mcp in ("2.0.0", "2.2.0")}
        entries = data.get("matrix")
        actual: list[tuple[str, str]] = []
        self.require(isinstance(entries, list) and len(entries) == len(expected) and all(isinstance(entry, dict) and entry.get("status") == "passed" for entry in entries), "quality matrix: exactly six passing entries required; failed/extra entries are not discarded")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("status") == "passed":
                    actual.append((entry.get("python"), entry.get("mcp")))
        self.require(len(actual) == len(expected) and set(actual) == expected, "quality matrix: all six Python/MCP combinations must pass exactly once")
        checks = data.get("checks")
        required = ("lint", "typing", "compileall", "inventory", "diff", "packages", "checksums")
        self.require(isinstance(checks, dict) and all(checks.get(key) == "passed" for key in required), "quality matrix: required quality/package checks must pass")

    def check_requirements(self, ledger: dict[str, Any]) -> None:
        requirements = ledger.get("requirements")
        if not self.require(isinstance(requirements, dict) and set(requirements) == set(REQUIREMENTS), "mandatory requirement ledger is incomplete or changed"):
            return
        for requirement in REQUIREMENTS:
            entry = requirements[requirement]
            label = f"requirement {requirement}"
            if not self.require(isinstance(entry, dict) and entry.get("status") == "accepted", f"{label}: still open"):
                continue
            evidence = entry.get("evidence")
            if not self.require(isinstance(evidence, list) and bool(evidence), f"{label}: evidence required"):
                continue
            for index, reference in enumerate(evidence):
                receipt = self.receipt(reference, f"{label} evidence {index}")
                if receipt is not None:
                    data, path = receipt
                    self.require(data.get("kind") == "requirement_acceptance" and data.get("requirement_id") == requirement, f"{label}: wrong acceptance receipt")
                    self.check_review(data, path, label)

    def check_native(self, ledger: dict[str, Any], versions: set[str]) -> None:
        references = ledger.get("native_matrices")
        covered: set[str] = set()
        if not self.require(isinstance(references, list) and bool(references), "full Windows 11 native matrix evidence required"):
            return
        for index, reference in enumerate(references):
            label = f"native matrix {index}"
            receipt = self.receipt(reference, label)
            if receipt is None:
                continue
            data, path = receipt
            self.require(data.get("kind") == "native_matrix", f"{label}: wrong receipt kind")
            self.require(data.get("platform") == {"system": "Windows", "release": "11"}, f"{label}: Windows 11 host evidence required")
            report_path = self.reference(data.get("report"), path.parent, f"{label} report")
            if report_path is None:
                continue
            report = self.json_file(report_path, label)
            platform = report.get("platform")
            self.require(isinstance(platform, dict) and platform.get("system") == "Windows" and platform.get("release") == "11", f"{label}: native report must identify Windows 11")
            self.require(report.get("release_readiness") == "NOT_ASSESSED", f"{label}: native runner readiness must remain NOT_ASSESSED")
            self.require(report.get("commit") == self.commit and report.get("worktree_dirty") is False, f"{label}: clean exact-commit native evidence required")
            self.require(report.get("source_files") == self.inventory and report.get("source_sha256") == self.source_sha256, f"{label}: native source fingerprint mismatch")
            cases = set(run_blender_checks.CASES)
            self.require(report.get("checks_passed") is True and report.get("all_cases_selected") is True, f"{label}: incomplete/failing native run")
            selected = report.get("selected_cases")
            self.require(isinstance(selected, list) and len(selected) == len(cases) and set(selected) == cases, f"{label}: all current native cases required")
            results = report.get("results")
            if not self.require(isinstance(results, list) and bool(results) and all(isinstance(result, dict) for result in results), f"{label}: native results missing"):
                continue
            groups: dict[str, list[dict[str, Any]]] = {}
            logs: dict[tuple[str, str, str | None], Path] = {}
            retained_logs = data.get("logs")
            if isinstance(retained_logs, list):
                for log in retained_logs:
                    if not isinstance(log, dict):
                        continue
                    key = (log.get("blender_executable"), log.get("case"), log.get("phase"))
                    log_path = self.reference(log.get("artifact"), path.parent, f"{label} log {key}")
                    self.require(key not in logs, f"{label}: duplicate retained log identity")
                    if log_path is not None:
                        logs[key] = log_path
            for result in results:
                executable = result.get("blender_executable")
                if not isinstance(executable, str) or not executable:
                    self.blockers.append(f"{label}: native executable identity missing")
                    continue
                groups.setdefault(executable, []).append(result)
            for executable, group in groups.items():
                names = [result.get("case") for result in group]
                self.require(len(names) == len(cases) and set(names) == cases, f"{label}: missing/duplicate cases for {executable}")
                observed: set[str] = set()
                for result in group:
                    case = result.get("case")
                    if case not in cases:
                        continue
                    match = re.match(r"^(\d+\.\d+\.\d+)(?:\s+LTS)?$", str(result.get("blender_version")))
                    if match:
                        observed.add(match.group(1))
                    self.require(match is not None, f"{label}/{case}: stable numeric Blender version required")
                    self.require(result.get("status") == "passed", f"{label}/{case}: native success evidence missing")
                    script = run_blender_checks.CASES[case][0]
                    self.require(result.get("script_sha256") == self.inventory.get(f"scripts/{script}"), f"{label}/{case}: fixture source mismatch")
                    expected_mode = "private_windows_desktop" if case in run_blender_checks.INTERACTIVE_CASES else "background"
                    self.require(result.get("execution_mode") == expected_mode, f"{label}/{case}: incorrect Windows execution isolation")
                    if case in run_blender_checks.PHASED_CASES:
                        phases = result.get("phases")
                        self.require(result.get("fresh_process_verified") is True and result.get("reader_started") is True and result.get("phase_sequence") == ["writer", "reader"], f"{label}/{case}: verified writer/reader sequence required")
                        if not self.require(isinstance(phases, list) and len(phases) == 2 and all(isinstance(phase, dict) for phase in phases), f"{label}/{case}: both process phases required"):
                            continue
                        tokens: list[str] = []
                        for phase, phase_name, marker in zip(phases, ("writer", "reader"), run_blender_checks.PHASED_CASES[case], strict=True):
                            self.require(phase.get("phase") == phase_name and phase.get("blender_version") == result.get("blender_version"), f"{label}/{case}: wrong phase or Blender version")
                            token = phase.get("process_instance")
                            self.require(isinstance(token, str) and bool(token), f"{label}/{case}: missing process instance")
                            tokens.append(token)
                            proof = phase.get("evidence", {})
                            self.require(isinstance(proof, dict) and proof.get("process_instance") == token and proof.get("phase") == phase_name and type(proof.get("process_id")) is int and proof["process_id"] > 0, f"{label}/{case}: process-instance evidence mismatch")
                            self.require(phase.get("script_sha256") == result.get("script_sha256") and phase.get("execution_mode") == expected_mode, f"{label}/{case}: phase source/isolation mismatch")
                            self.check_native_process(phase, logs.get((executable, case, phase_name)), marker, f"{label}/{case}/{phase_name}")
                        self.require(len(set(tokens)) == 2, f"{label}/{case}: writer/reader must use distinct process instances")
                    else:
                        self.check_native_process(result, logs.get((executable, case, None)), run_blender_checks.CASES[case][1], f"{label}/{case}")
                self.require(len(observed) == 1, f"{label}: inconsistent Blender version for {executable}")
                if len(observed) == 1:
                    covered.update(observed)
        self.require(versions <= covered, "native matrices do not cover both selected Blender versions")

    def check_native_process(self, result: dict[str, Any], log_path: Path | None, marker: str, label: str) -> None:
        self.require(result.get("status") == "passed" and type(result.get("exit_code")) is int and result["exit_code"] == 0 and isinstance(result.get("evidence"), dict) and bool(result["evidence"]), f"{label}: native success evidence missing")
        evidence = result.get("evidence")
        observed_version = next((evidence.get(key) for key in ("blender_version", "blender", "version") if isinstance(evidence.get(key), str)), None) if isinstance(evidence, dict) else None
        self.require(observed_version is not None and observed_version == result.get("blender_version"), f"{label}: native success payload version differs from reported Blender version")
        if self.require(log_path is not None, f"{label}: retained hashed log required"):
            with log_path.open("rb") as stream:
                stream.seek(max(0, log_path.stat().st_size - 65536))
                payload = run_blender_checks.success_payload(stream.read().decode("utf-8", errors="replace"), marker)
            self.require(payload == result.get("evidence"), f"{label}: retained log success marker differs from report")

    def check_installed(self, ledger: dict[str, Any], versions: set[str]) -> None:
        references = ledger.get("installed_scenarios")
        covered: set[tuple[str, str]] = set()
        if not self.require(isinstance(references, list) and bool(references), "installed-package scenarios A-F required on both Blender versions"):
            return
        for index, reference in enumerate(references):
            label = f"installed scenario {index}"
            receipt = self.receipt(reference, label)
            if receipt is None:
                continue
            data, path = receipt
            key = (data.get("scenario"), data.get("blender_version"))
            self.require(data.get("kind") == "installed_scenario", f"{label}: wrong receipt kind")
            self.require(data.get("platform") == {"system": "Windows", "release": "11"}, f"{label}: Windows 11 required")
            self.require(data.get("installed_packages") is True and data.get("source_checkout_imports") is False, f"{label}: installed package execution must exclude source imports")
            self.require(key[0] in SCENARIOS and key[1] in versions, f"{label}: unexpected scenario or Blender version")
            self.require(key not in covered, f"{label}: duplicate scenario/version receipt")
            covered.add(key)
            self.check_review(data, path, label)
            if key[0] == "F":
                self.require(data.get("upgrade_from") == "0.3.0" and data.get("rollback_verified") is True, f"{label}: 0.3.0 upgrade and rollback evidence required")
        self.require(covered == {(scenario, version) for scenario in SCENARIOS for version in versions}, "installed A-F acceptance is incomplete for the selected Blender matrix")

    def run(self) -> dict[str, Any]:
        ledger = self.json_file(self.ledger_path, "ledger")
        self.require(type(ledger.get("schema_version")) is int and ledger["schema_version"] == 1, "unsupported ledger schema")
        self.require(ledger.get("target_version") == "1.0.0", "qualification only supports the full 1.0.0 target")
        self.check_provenance(ledger)
        support = ledger.get("support", {})
        if not isinstance(support, dict):
            support = {}
        lts, stable = support.get("blender_lts"), support.get("blender_stable")
        valid_versions = isinstance(lts, str) and re.fullmatch(r"4\.5\.\d+", lts) is not None and isinstance(stable, str) and re.fullmatch(r"5\.\d+\.\d+", stable) is not None
        self.require(valid_versions and support.get("os") == "Windows 11", "select exact Blender 4.5 LTS and stable 5.x versions on Windows 11")
        versions = {lts, stable} if valid_versions else set()
        for check in (
            lambda: self.check_packages(ledger), lambda: self.check_requirements(ledger),
            lambda: self.check_quality(ledger), lambda: self.check_native(ledger, versions),
            lambda: self.check_installed(ledger, versions),
        ):
            try:
                check()
            except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
                self.blockers.append(f"invalid evidence structure ({exc})")
        self.qualified = not self.blockers
        return {"schema_version": 1, "release_readiness": "READY" if self.qualified else "NOT_READY", "commit": self.commit, "source_sha256": self.source_sha256, "package_sha256": self.package_sha256, "ledger_sha256": self.artifact_hashes.get(self.ledger_path), "blockers": self.blockers}

    def stage(self, output: Path, result: dict[str, Any]) -> None:
        """Retain exact qualified bytes; changed inputs fail before publication is possible."""
        if not self.qualified:
            raise ValueError("cannot stage an unqualified release")
        output = output.resolve()
        if output.is_relative_to(self.source) or output.is_relative_to(self.ledger_path.parent):
            raise ValueError("staging must be outside the source and evidence directories")
        output.mkdir(parents=True, exist_ok=False)
        for name in ("addon", "mcp", "plugin", "checksums"):
            package = self.package_paths[name]
            destination = output / package.name
            shutil.copyfile(package, destination)
            if sha256(destination) != self.package_sha256[name]:
                raise ValueError(f"package {name} changed after qualification")
        evidence_zip = output / "release-evidence-1.0.0.zip"
        with ZipFile(evidence_zip, "w") as archive:
            for path in sorted(self.artifact_hashes):
                archive.write(path, path.relative_to(self.ledger_path.parent).as_posix())
        with ZipFile(evidence_zip) as archive:
            for path, digest in self.artifact_hashes.items():
                name = path.relative_to(self.ledger_path.parent).as_posix()
                if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                    raise ValueError(f"evidence changed after qualification: {name}")
        result["evidence_archive_sha256"] = sha256(evidence_zip)
        (output / "qualification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=ROOT / "docs/release-1.0-ledger.json")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--stage", type=Path, help="After qualification, copy matching assets and retained evidence to a new directory")
    args = parser.parse_args()
    qualification = Qualification(args.ledger, args.source)
    result = qualification.run()
    if args.stage is not None and result["release_readiness"] == "READY":
        try:
            qualification.stage(args.stage, result)
        except (OSError, ValueError, KeyError, BadZipFile) as exc:
            result["release_readiness"] = "NOT_READY"
            result["blockers"].append(f"release staging failed ({exc})")
    print(json.dumps(result, indent=2))
    return 0 if result["release_readiness"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
