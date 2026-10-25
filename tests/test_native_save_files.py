from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
from types import ModuleType
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def files(addon_package):
    return importlib.import_module(f"{addon_package}.native_save_files")


@pytest.fixture
def process_module(addon_package):
    return importlib.import_module(f"{addon_package}.native_save_process")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(files, tmp_path, *, mode="COPY_NEW", existing=False, save_version=1):
    root = tmp_path / "Project Folder"
    root.mkdir()
    current = root / "original.blend"
    current.write_bytes(b"initial original project")
    target = current if mode == "SAVE_CURRENT" else root / "new project.blend"
    if existing and target != current:
        target.write_bytes(b"initial target project")
    overwrite = "NO_CLOBBER" if mode == "COPY_NEW" else "NATIVE_REPLACE_EXPECTED" if target.exists() else "NATIVE_NEW_EXPECTED"
    return files.freeze_plan(str(root), str(target), mode, overwrite, str(current), save_version)


def drain(iterator):
    values = []
    while True:
        try:
            values.append(next(iterator))
        except StopIteration as result:
            return values, result.value


def test_permission_gate_precedes_path_parsing_or_probe(files, monkeypatch):
    def deny():
        raise PermissionError("model deny")

    monkeypatch.setattr(files, "_path", lambda *_args: pytest.fail("Path parsing preceded grant"))
    with pytest.raises(PermissionError):
        files.freeze_plan("", "", "COPY_NEW", "NO_CLOBBER", None, 0, deny)


@pytest.mark.parametrize("bad", ["relative.blend", "//network/share/a.blend", "/tmp/../a.blend",
                                "/tmp/./a.blend", "/tmp/bad\n.blend", "/tmp/bad\x7f.blend",
                                "/tmp/a\\b.blend", "/tmp/\ud800.blend", ""])
def test_rejects_nonliteral_project_paths(files, tmp_path, bad):
    with pytest.raises(files.BridgeError):
        files.freeze_plan(str(tmp_path), bad, "COPY_NEW", "NO_CLOBBER", None, 0)


@pytest.mark.parametrize("value", [-1, 4, True, 1.0, "1"])
def test_backup_versions_are_bounded_exact_int(files, tmp_path, value):
    with pytest.raises(files.BridgeError):
        files.freeze_plan(str(tmp_path), str(tmp_path / "new.blend"), "COPY_NEW", "NO_CLOBBER", None, value)


@pytest.mark.parametrize("mode,overwrite,exists", [
    ("COPY_NEW", "NATIVE_NEW_EXPECTED", False), ("COPY_NEW", "NO_CLOBBER", True),
    ("SAVE_AS", "NO_CLOBBER", False), ("SAVE_AS", "NATIVE_REPLACE_EXPECTED", False),
    ("SAVE_AS", "NATIVE_NEW_EXPECTED", True), ("SAVE_CURRENT", "NATIVE_NEW_EXPECTED", True),
])
def test_native_overwrite_policy_is_explicit(files, tmp_path, mode, overwrite, exists):
    current = tmp_path / "current.blend"
    current.write_bytes(b"current")
    target = current if mode == "SAVE_CURRENT" else tmp_path / "new.blend"
    if exists:
        target.write_bytes(b"target")
    with pytest.raises(files.BridgeError):
        files.freeze_plan(str(tmp_path), str(target), mode, overwrite, str(current), 0)


@pytest.mark.parametrize("which", ["root", "parent", "destination", "backup", "current"])
def test_symlink_aliases_are_never_followed(files, tmp_path, which):
    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target, current = root / "target.blend", root / "current.blend"
    current.write_bytes(b"original")
    if which == "root":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        root, target = alias, alias / target.name
    elif which == "parent":
        alias = root / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        target = alias / target.name
    elif which == "destination":
        target.symlink_to(root / "missing.blend")
    elif which == "backup":
        (root / "target.blend1").symlink_to(root / "missing.blend1")
    else:
        current.unlink()
        current.symlink_to(outside / "missing.blend")
    with pytest.raises(files.BridgeError):
        files.freeze_plan(str(root), str(target), "SAVE_AS", "NATIVE_NEW_EXPECTED", str(current), 1)


def test_empty_root_and_outside_source_do_not_grant_reads(files, tmp_path):
    destination = tmp_path / "x.blend"
    with pytest.raises(files.BridgeError) as error:
        files.freeze_plan("", str(destination), "COPY_NEW", "NO_CLOBBER", None, 0)
    assert error.value.code == "PERMISSION_DENIED"
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = tmp_path / "outside.blend"
    outside.write_bytes(b"outside")
    with pytest.raises(files.BridgeError) as error:
        files.freeze_plan(str(approved), str(approved / "x.blend"), "COPY_NEW", "NO_CLOBBER", str(outside), 0)
    assert error.value.code == "PERMISSION_DENIED"


def test_plan_binds_directory_identity_and_original_bytes(files, tmp_path):
    frozen = plan(files, tmp_path)
    assert frozen.fingerprint == frozen.fingerprint and frozen.summary()["native_destination_race_excluded"]
    frozen.current_path.write_bytes(b"manual newer original")
    with pytest.raises(files.BridgeError, match="could not be verified"):
        frozen.check()
    frozen.current_path.write_bytes(b"initial original project")
    old = frozen.root.with_name("old root")
    frozen.root.rename(old)
    frozen.root.mkdir()
    frozen.current_path.write_bytes(b"initial original project")
    with pytest.raises(files.BridgeError) as error:
        frozen.check()
    assert error.value.context["reason"] == "PROJECT_DIRECTORY_CHANGED"


def test_copy_publishes_without_clobber_and_cleanup_keeps_final_original(files, tmp_path):
    frozen = plan(files, tmp_path)
    resource = files.NativeSaveFiles(frozen)
    native = resource.prepare()
    assert native.parent.stat().st_mode & 0o777 == 0o700
    native.write_bytes(b"actual saved project")
    resource.native_returned(True)
    rows, record = drain(resource.observe_steps())
    assert rows and record.sha256 == sha(native)
    assert not resource.effects()["file_published"]
    result = resource.publish()
    assert result["file_published"] and result["published_bytes_verified"]
    assert frozen.path.read_bytes() == b"actual saved project"
    assert frozen.current_path.read_bytes() == b"initial original project"
    assert resource.close()["staging_cleanup"] == "complete"
    resource.check_saved()
    assert frozen.path.exists() and resource.close()["file_published"]


def test_untitled_copy_and_constructor_facts_are_not_rebasable(files, tmp_path):
    frozen = files.freeze_plan(str(tmp_path), str(tmp_path / "new.blend"), "COPY_NEW", "NO_CLOBBER", None, 0)
    resource = files.NativeSaveFiles(frozen)
    with pytest.raises(files.BridgeError):
        resource.plan = frozen
    resource.prepare()
    with pytest.raises(files.BridgeError):
        resource.native_path = tmp_path / "foreign.blend"


def test_direct_current_save_records_native_backup_and_never_deletes_them(files, tmp_path):
    frozen = plan(files, tmp_path, mode="SAVE_CURRENT")
    old = frozen.destination.sha256
    resource = files.NativeSaveFiles(frozen)
    assert resource.prepare() == frozen.path
    os.replace(frozen.path, str(frozen.path) + "1")
    frozen.path.write_bytes(b"new current project")
    resource.native_returned(True)
    assert resource.effects()["publication_outcome_unknown"]
    drain(resource.observe_steps())
    result = resource.close()
    assert result["file_published"] and result["published_bytes_verified"]
    assert len(result["artifacts"]) == 2 and sha(files.Path(str(frozen.path) + "1")) == old
    assert frozen.path.exists() and files.Path(str(frozen.path) + "1").exists()


@pytest.mark.parametrize("existing", [False, True])
def test_direct_save_as_preserves_other_original_and_expected_backup(files, tmp_path, existing):
    frozen = plan(files, tmp_path, mode="SAVE_AS", existing=existing)
    resource = files.NativeSaveFiles(frozen)
    native = resource.prepare()
    if existing:
        os.replace(native, str(native) + "1")
    native.write_bytes(b"new save-as")
    resource.native_returned(True)
    drain(resource.observe_steps())
    resource.check_saved()
    assert not resource.effects().get("native_destination_race_excluded", False)
    assert frozen.current_path.read_bytes() == b"initial original project"


def test_collision_between_copy_verification_and_link_never_replaces_user_file(files, tmp_path):
    frozen = plan(files, tmp_path)
    resource = files.NativeSaveFiles(frozen)
    resource.prepare().write_bytes(b"owned saved project")
    resource.native_returned(True)
    drain(resource.observe_steps())
    frozen.path.write_bytes(b"manual collision")
    with pytest.raises(files.BridgeError):
        resource.publish()
    assert frozen.path.read_bytes() == b"manual collision"
    resource.close()
    assert frozen.path.read_bytes() == b"manual collision"


def test_uncertain_link_outcome_retains_actual_final_even_after_error(files, tmp_path, monkeypatch):
    frozen = plan(files, tmp_path)
    resource = files.NativeSaveFiles(frozen)
    resource.prepare().write_bytes(b"owned saved project")
    resource.native_returned(True)
    drain(resource.observe_steps())
    link = files.os.link

    def create_then_fail(source, destination):
        link(source, destination)
        raise OSError("model unknown result after successful link")

    monkeypatch.setattr(files.os, "link", create_then_fail)
    with pytest.raises(files.BridgeError):
        resource.publish()
    effects = resource.close()
    assert effects["publication_outcome_unknown"] and not effects["file_published"]
    assert frozen.path.read_bytes() == b"owned saved project"


def test_late_gate_failure_keeps_known_publication_and_revokes_verification(files, tmp_path):
    frozen = plan(files, tmp_path)
    resource = files.NativeSaveFiles(frozen)
    resource.prepare().write_bytes(b"owned saved project")
    resource.native_returned(True)
    drain(resource.observe_steps())

    def gate():
        if resource.published:
            raise files.BridgeError("PERMISSION_DENIED", "revoked after link")

    with pytest.raises(files.BridgeError):
        resource.publish(gate)
    effects = resource.close(remove_files=False)
    assert effects["file_published"] and not effects["published_bytes_verified"]
    assert frozen.path.exists() and effects["retained_staging_path"]


def test_native_failure_and_missing_output_preserve_possible_direct_effects(files, tmp_path):
    frozen = plan(files, tmp_path, mode="SAVE_CURRENT")
    resource = files.NativeSaveFiles(frozen)
    resource.prepare()
    frozen.path.unlink()
    resource.native_returned(False)
    with pytest.raises(OSError):
        drain(resource.observe_steps())
    effects = resource.close()
    assert effects["publication_attempted"] and effects["publication_outcome_unknown"]
    assert effects["artifacts_incomplete"] and not effects["published_bytes_verified"]
    with pytest.raises(files.BridgeError):
        resource.native_returned(False)


def test_direct_native_start_latches_possible_file_effects_before_return(files, tmp_path):
    frozen = plan(files, tmp_path, mode="SAVE_CURRENT")
    resource = files.NativeSaveFiles(frozen)
    resource.prepare()
    resource.native_started()
    assert resource.effects()["publication_attempted"] and resource.effects()["publication_outcome_unknown"]
    assert resource.effects()["artifacts_incomplete"] and not resource.effects()["file_published"]
    with pytest.raises(files.BridgeError):
        resource.native_started()


def test_unknown_or_manually_changed_staging_is_retained(files, tmp_path):
    frozen = plan(files, tmp_path)
    resource = files.NativeSaveFiles(frozen)
    native = resource.prepare()
    native.write_bytes(b"owned project")
    resource.native_returned(True)
    drain(resource.observe_steps())
    native.write_bytes(b"manual changed staging")
    assert resource.close()["staging_cleanup"] == "retained_unverified"
    assert native.exists()
    (native.parent / "unknown.txt").write_text("new consumer")
    assert resource.close()["staging_cleanup"] == "retained_unverified"


def make_process(module, tmp_path, *, images=None):
    binary = tmp_path / "Blender With Spaces"
    binary.write_bytes(b"known official executable model")
    saved = tmp_path / "native saved.blend"
    saved.write_bytes(b"owned native file model")
    raw = json.dumps({"schema": "stock_native_project_v1", "objects": [], "images": images or []},
                     sort_keys=True, separators=(",", ":")).encode()
    return module.SaveReaderProcess(str(binary), saved, raw, "qualified_hash", "4.5.14 LTS", sha(saved))


def fake_process(pid=42):
    return NS(pid=pid, returncode=0, poll=lambda: 0, wait=lambda timeout: 0)


def test_fixed_reader_launch_owns_immutable_input_and_drops_credentials(process_module, tmp_path, monkeypatch):
    resource = make_process(process_module, tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "never-inherit-model")
    monkeypatch.setenv("PYTHONPATH", "untrusted-model")
    calls = []

    def popen(command, **kwargs):
        calls.append(command)
        assert command[0] == str(resource.binary)
        assert "--background" in command and "--factory-startup" in command and "--disable-autoexec" in command
        assert command[command.index("--python") + 1] == str(resource.reader)
        assert command[command.index("--python-expr") + 1] == "import sys; sys.dont_write_bytecode = True"
        assert command[-2:] == ["--token", resource.token]
        assert kwargs["shell"] is False and kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["stdout"] is kwargs["stderr"] is subprocess.DEVNULL
        assert "GITHUB_TOKEN" not in kwargs["env"] and "PYTHONPATH" not in kwargs["env"]
        assert kwargs["env"]["HOME"] != os.environ.get("HOME")
        return fake_process()

    monkeypatch.setattr(process_module.subprocess, "Popen", popen)
    list(resource.fingerprint_steps(lambda: None))
    assert resource.folder.stat().st_mode & 0o777 == 0o700
    assert (resource.folder / "saved.blend").read_bytes() == resource.saved_path.read_bytes()
    assert stat.S_IMODE((resource.folder / "saved.blend").stat().st_mode) == 0o400
    resource.launch(lambda: None)
    assert len(calls) == 1
    assert resource.close()["staging_cleanup"] == "complete"
    assert resource.saved_path.exists()


def test_source_change_during_immutable_copy_prevents_launch(process_module, tmp_path, monkeypatch):
    resource = make_process(process_module, tmp_path)
    source = resource.saved_path
    events = resource.fingerprint_steps(lambda: None)
    assert next(events)["phase"] == "verifying_reader_runtime"
    source.write_bytes(b"newer source save")
    with pytest.raises(process_module.BridgeError):
        list(events)
    monkeypatch.setattr(process_module.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("Late launch"))
    with pytest.raises(process_module.BridgeError):
        resource.launch(lambda: None)
    resource.close()
    assert source.read_bytes() == b"newer source save"


def receipt(resource):
    return {"schema": "native_save_reader_receipt_v1", "status": "succeeded", "token": resource.token,
            "saved_sha256": resource.saved_sha256, "projection_sha256": resource.projection_sha256,
            "actual_projection_sha256": resource.projection_sha256, "program": dict(resource.program),
            "process_id": 42, "blender_version": resource.version, "build_hash": resource.build_hash,
            "native_open_invoked": True, "native_open_completed": True, "declared_projection_reopened": True,
            "source_process_contacted": False, "source_restore_writes": 0, "reader_project_save_invoked": False,
            "native_effect_inventory_complete": False,
            "timings": {"worker_elapsed_seconds": .2, "native_open_seconds": .1, "projection_seconds": .02},
            "peak_memory": {"available": True, "metric": "ru_maxrss", "scope": "RUSAGE_SELF", "value": 4096,
                            "unit": "KiB", "platform": "linux"}, "error": None}


def ready(resource):
    list(resource.fingerprint_steps(lambda: None))
    object.__setattr__(resource, "_process", fake_process())
    object.__setattr__(resource, "reaped", True)
    return resource


def census_model(module):
    classes = {}
    for name, required in module.DECLARED_RNA.items():
        fields = {}
        for optional, layout in ((False, required), (True, module.OPTIONAL_RNA.get(name, ""))):
            for item in layout.split():
                field, expected = item.split(":")
                kind, _, shape = expected.partition("/")
                metadata = {"identifier": field, "type": kind, "is_runtime": False, "is_readonly": True}
                if shape:
                    metadata["array_length"] = int(shape)
                fields[field] = {"optional": optional, "metadata": None if optional else metadata}
        classes[name] = {"present": True, "fields": fields, "functions": ["model_method"]}
    return {"schema": "native_save_class_metadata_v1", "classes": classes, "mismatches": [],
            "scope": "declared descriptors/functions only; no ID values or hidden-storage proof",
            "python_methods": {"ID.as_pointer": True,
                               "bpy_prop_array.foreach_get": "C wrapper source binding; not an RNA function"}}


def schema_sidecar(resource, module):
    return {"schema": "native_save_schema_sidecar_v1", "token": resource.token, "process_id": 42,
            "blender_version": resource.version, "build_hash": resource.build_hash, "program": dict(resource.program),
            "saved_sha256": resource.saved_sha256, "projection_sha256": resource.projection_sha256,
            "request_sha256": resource.request_sha256, "census": census_model(module)}


def fail_reader(resource):
    row = receipt(resource)
    row.update(status="failed", actual_projection_sha256=None, declared_projection_reopened=False,
               error={"code": "NATIVE_SAVE_READER_FAILED", "type": "ProfileRefused",
                      "failure_stage": "projection_capture", "profile_reason": "UNSUPPORTED_ID_FAMILY:palettes"})
    output = resource.folder / "reader.json"
    output.write_text(json.dumps(row))
    output.chmod(0o600)
    object.__setattr__(resource, "_process", NS(pid=42, returncode=1, poll=lambda: 1))


def test_failed_reader_sidecar_is_bound_metadata_and_never_save_authority(process_module, tmp_path):
    resource = ready(make_process(process_module, tmp_path))
    fail_reader(resource)
    sidecar = schema_sidecar(resource, process_module)
    sidecar["census"]["classes"]["Scene"]["fields"]["collection"]["metadata"] = None
    sidecar["census"]["mismatches"] = [{"class": "Scene", "field": "collection", "reason": "FIELD_MISSING"}]
    path = resource.folder / "schema-census.json"
    path.write_text(json.dumps(sidecar))
    path.chmod(0o600)
    with pytest.raises(process_module.BridgeError) as failure:
        resource.result(lambda: None)
    assert failure.value.context["reader_schema_diagnostic"] == {"available": True, "reason": "AVAILABLE"}
    assert "census" not in json.dumps(failure.value.context) and "classes" not in json.dumps(failure.value.context)
    assert resource.evidence()["worker_receipt"]["status"] == "failed"
    assert path.exists() and resource.saved_path.exists()
    assert resource.close(remove_files=False)["staging_cleanup"] == "retained_permission_denied"
    assert path.exists() and resource.saved_path.exists()
    assert resource.close()["staging_cleanup"] == "complete" and resource.saved_path.exists()


@pytest.mark.parametrize("fault", ["unobserved", "modified", "replaced"])
def test_unexpected_or_changed_valid_sidecar_is_preserved_by_cleanup(process_module, tmp_path, fault):
    resource = ready(make_process(process_module, tmp_path))
    fail_reader(resource)
    path = resource.folder / "schema-census.json"
    sidecar = schema_sidecar(resource, process_module)
    path.write_text(json.dumps(sidecar))
    path.chmod(0o600)
    if fault != "unobserved":
        with pytest.raises(process_module.BridgeError) as failure:
            resource.result(lambda: None)
        assert failure.value.context["reader_schema_diagnostic"]["available"]
        if fault == "modified":
            sidecar["census"]["classes"]["Scene"]["fields"]["collection"]["metadata"]["is_readonly"] = False
            path.write_text(json.dumps(sidecar))
        else:
            raw = path.read_bytes()
            replacement = resource.folder / "replacement"
            replacement.write_bytes(raw)
            replacement.chmod(0o600)
            os.replace(replacement, path)
    assert resource.close()["staging_cleanup"] == "retained_unverified"
    assert path.exists() and (resource.folder / "saved.blend").exists() and resource.saved_path.exists()


@pytest.mark.parametrize("fault", ["absent", "oversized", "succeeded", "existing_foreign"])
def test_worker_sidecar_is_failure_only_bounded_and_never_overwrites_foreign_file(
    process_module, addon_package, tmp_path, fault
):
    reader = importlib.import_module(f"{addon_package}.native_save_reader")
    resource = ready(make_process(process_module, tmp_path))
    sidecar = schema_sidecar(resource, process_module)
    row = receipt(resource)
    row["status"] = "succeeded" if fault == "succeeded" else "failed"
    request = json.loads((resource.folder / "request.json").read_bytes())
    census = None if fault == "absent" else {"oversized": "x" * reader.MAX_SCHEMA_DIAGNOSTIC} if fault == "oversized" else sidecar["census"]
    path = resource.folder / "schema-census.json"
    if fault == "existing_foreign":
        path.write_text("foreign recovery evidence")
        path.chmod(0o600)
    reader._write_schema_sidecar(resource.folder, request, resource.request_sha256, row, census)
    assert path.exists() is (fault == "existing_foreign")
    if path.exists():
        assert path.read_text() == "foreign recovery evidence"
        assert resource.close()["staging_cleanup"] == "retained_unverified"
    else:
        assert resource.close()["staging_cleanup"] == "complete"
    assert resource.saved_path.exists()


@pytest.mark.parametrize("fault", ["missing", "oversized", "truncated", "deep_json", "duplicate_key", "symlink", "hardlink", "public_mode",
                                 "token", "process_id", "process_bool", "build", "program", "request", "source",
                                 "unknown_class", "missing_class", "missing_field", "unknown_metadata", "field_value",
                                 "metadata_type", "runtime_bool", "array_bool", "field_optional", "function_path",
                                 "function_budget", "mismatch_path", "method_value", "unknown_top"])
def test_invalid_or_foreign_schema_sidecar_is_unavailable_and_retained(process_module, tmp_path, fault):
    resource = ready(make_process(process_module, tmp_path))
    fail_reader(resource)
    sidecar = schema_sidecar(resource, process_module)
    census = sidecar["census"]
    metadata = census["classes"]["Scene"]["fields"]["collection"]["metadata"]
    if fault in {"token", "process_id", "process_bool", "build", "program", "request", "source"}:
        key, value = {"token": ("token", "0" * 32), "process_id": ("process_id", 43), "process_bool": ("process_id", True),
                      "build": ("build_hash", "other"), "program": ("program", {}), "request": ("request_sha256", "0" * 64),
                      "source": ("projection_sha256", "0" * 64)}[fault]
        sidecar[key] = value
    elif fault == "unknown_class":
        census["classes"]["UserObjectName"] = {"present": True, "fields": {}, "functions": []}
    elif fault == "missing_class":
        del census["classes"]["Scene"]
    elif fault == "missing_field":
        del census["classes"]["Scene"]["fields"]["collection"]
    elif fault == "unknown_metadata":
        metadata["default"] = "/private/secret"
    elif fault == "field_value":
        metadata["value"] = "UserObjectName"
    elif fault == "metadata_type":
        metadata["type"] = {}
    elif fault == "runtime_bool":
        metadata["is_runtime"] = 0
    elif fault == "array_bool":
        metadata["array_length"] = True
    elif fault == "field_optional":
        census["classes"]["Scene"]["fields"]["collection"]["optional"] = True
    elif fault == "function_path":
        census["classes"]["Scene"]["functions"] = ["/private/secret"]
    elif fault == "function_budget":
        census["classes"]["Scene"]["functions"] = ["function_" + str(index) for index in range(257)]
    elif fault == "mismatch_path":
        census["mismatches"] = [{"class": "Scene", "reason": "/private/secret"}]
    elif fault == "method_value":
        census["python_methods"]["ID.as_pointer"] = "UserObjectName"
    elif fault == "unknown_top":
        sidecar["native_values"] = {"Object": "UserObjectName"}
    path = resource.folder / "schema-census.json"
    if fault == "symlink":
        path.symlink_to(resource.saved_path)
    elif fault != "missing":
        path.write_text("x" * (process_module.MAX_SCHEMA_DIAGNOSTIC + 1) if fault == "oversized" else
                        '{"schema":' if fault == "truncated" else '[' * 1100 + '0' + ']' * 1100 if fault == "deep_json" else
                        '{"schema":"foreign",' + json.dumps(sidecar)[1:] if fault == "duplicate_key" else json.dumps(sidecar))
        path.chmod(0o644 if fault == "public_mode" else 0o600)
        if fault == "hardlink":
            os.link(path, resource.folder / "working" / "foreign-link")
    with pytest.raises(process_module.BridgeError) as failure:
        resource.result(lambda: None)
    diagnostic = failure.value.context["reader_schema_diagnostic"]
    assert diagnostic["available"] is False and set(diagnostic) == {"available", "reason"}
    assert resource.evidence()["worker_receipt"]["status"] == "failed" and resource.saved_path.exists()
    if fault == "missing":
        assert diagnostic["reason"] == "NOT_PRODUCED"
        assert resource.close()["staging_cleanup"] == "complete"
    else:
        assert resource.close()["staging_cleanup"] == "retained_unverified"
        assert os.path.lexists(path) and (resource.folder / "saved.blend").exists()


@pytest.mark.parametrize("key,value", [
    ("token", "0" * 32), ("process_id", True), ("process_id", 43), ("build_hash", "other"),
    ("saved_sha256", "0" * 64), ("actual_projection_sha256", "0" * 64),
    ("source_process_contacted", True), ("source_restore_writes", False),
    ("native_effect_inventory_complete", True), ("declared_projection_reopened", False),
    ("program", {}), ("timings", {"worker_elapsed_seconds": True}),
    ("peak_memory", {"available": True, "metric": "ru_maxrss", "scope": "RUSAGE_SELF", "value": True,
                     "unit": "KiB", "platform": "linux"}),
])
def test_unmatched_reader_receipts_never_become_success(process_module, tmp_path, key, value):
    resource = ready(make_process(process_module, tmp_path))
    row = receipt(resource)
    row[key] = value
    output = resource.folder / "reader.json"
    output.write_text(json.dumps(row))
    output.chmod(0o600)
    with pytest.raises(process_module.BridgeError):
        resource.result(lambda: None)
    assert resource.close()["staging_cleanup"] == "complete"


def test_valid_receipt_returns_independent_copy_and_failure_retains_measured_metrics(process_module, tmp_path):
    resource = ready(make_process(process_module, tmp_path))
    row = receipt(resource)
    output = resource.folder / "reader.json"
    output.write_text(json.dumps(row))
    output.chmod(0o600)
    result = resource.result(lambda: None)
    result["status"] = "forged"
    assert resource.evidence()["worker_receipt"]["status"] == "succeeded"
    row.update(status="failed", actual_projection_sha256=None, declared_projection_reopened=False,
               error={"code": "NATIVE_SAVE_READER_FAILED", "type": "ValueError", "failure_stage": "projection_capture"})
    output.write_text(json.dumps(row))
    object.__setattr__(resource, "_process", NS(pid=42, returncode=1, poll=lambda: 1))
    with pytest.raises(process_module.BridgeError) as failure:
        resource.result(lambda: None)
    assert failure.value.context["reader_failure"] == row["error"]
    assert resource.evidence()["worker_receipt"]["peak_memory"]["value"] == 4096
    resource.close()


@pytest.mark.parametrize("fault", ["missing_stage", "unknown_stage", "stage_type", "stage_budget", "extra_error",
                                 "path_reason", "newline_reason", "unicode_reason", "reason_budget", "reason_type",
                                 "reason_for_other_type", "reason_for_preload", "stage_before_open", "stage_native_open",
                                 "stage_after_projection", "unsafe_exception_type", "top_level_stage"])
def test_untrusted_failure_diagnostics_are_rejected_and_never_retained(process_module, tmp_path, fault):
    resource = ready(make_process(process_module, tmp_path))
    row = receipt(resource)
    row.update(status="failed", actual_projection_sha256=None, declared_projection_reopened=False,
               error={"code": "NATIVE_SAVE_READER_FAILED", "type": "ProfileRefused",
                      "failure_stage": "projection_capture", "profile_reason": "UNSUPPORTED_ID_FAMILY:palettes"})
    error = row["error"]
    if fault == "missing_stage":
        del error["failure_stage"]
    elif fault == "extra_error":
        error["message"] = "/private/secret"
    elif fault == "top_level_stage":
        row["failure_stage"] = "projection_capture"
    else:
        key, value = {
            "unknown_stage": ("failure_stage", "unknown_future"), "stage_type": ("failure_stage", False),
            "stage_budget": ("failure_stage", "x" * 161), "path_reason": ("profile_reason", "/private/secret"),
            "newline_reason": ("profile_reason", "CODE\nsecret"), "unicode_reason": ("profile_reason", "CODE:é"),
            "reason_budget": ("profile_reason", "X" * 161), "reason_type": ("profile_reason", True),
            "reason_for_other_type": ("type", "ValueError"), "reason_for_preload": ("failure_stage", "image_preload"),
            "stage_before_open": ("failure_stage", "input_validation"), "stage_native_open": ("failure_stage", "native_open"),
            "stage_after_projection": ("failure_stage", "projection_compare"),
            "unsafe_exception_type": ("type", "/private/secret"),
        }[fault]
        error[key] = value
        if fault in {"stage_before_open", "stage_native_open", "stage_after_projection"}:
            del error["profile_reason"]
    output = resource.folder / "reader.json"
    output.write_text(json.dumps(row))
    output.chmod(0o600)
    object.__setattr__(resource, "_process", NS(pid=42, returncode=1, poll=lambda: 1))
    with pytest.raises(process_module.BridgeError) as failure:
        resource.result(lambda: None)
    assert "reader_failure" not in failure.value.context
    assert resource.evidence()["worker_receipt"] is None
    assert resource.saved_path.exists()
    resource.close()


def test_cancel_reaps_owned_child_even_when_file_cleanup_is_revoked(process_module, tmp_path):
    resource = ready(make_process(process_module, tmp_path))
    calls, alive = [], [True]

    def wait(timeout):
        calls.append(("wait", timeout))
        if timeout == .1:
            raise subprocess.TimeoutExpired("model", timeout)
        alive[0] = False

    process = NS(pid=42, returncode=None, poll=lambda: None if alive[0] else -9,
                 terminate=lambda: calls.append("terminate"), kill=lambda: calls.append("kill"), wait=wait)
    object.__setattr__(resource, "_process", process)
    object.__setattr__(resource, "reaped", False)
    evidence = resource.close(remove_files=False)
    assert calls == ["terminate", ("wait", .1), "kill", ("wait", .2)]
    assert evidence["worker_reaped"] and evidence["staging_cleanup"] == "retained_permission_denied"
    assert resource.folder.exists()
    assert resource.close()["staging_cleanup"] == "complete"


def test_reader_unknown_entry_or_link_prevents_cleanup(process_module, tmp_path):
    resource = ready(make_process(process_module, tmp_path))
    (resource.folder / "unknown.txt").write_text("foreign")
    assert resource.close()["staging_cleanup"] == "retained_unverified"
    (resource.folder / "unknown.txt").unlink()
    (resource.folder / "working" / "link").symlink_to(tmp_path)
    assert resource.close()["staging_cleanup"] == "retained_unverified"
    assert resource.saved_path.exists()


def test_immutable_reader_facts_cannot_be_retargeted(process_module, tmp_path):
    resource = make_process(process_module, tmp_path)
    for key, value in (("binary", tmp_path / "other"), ("saved_path", tmp_path / "other.blend"),
                       ("expected_raw", b"{}"), ("program", {}), ("_process", fake_process())):
        with pytest.raises(process_module.BridgeError):
            setattr(resource, key, value)


@pytest.mark.parametrize("fault", ["projection", "missing", "malformed", "phase", "exit_type"])
def test_invalid_reader_output_does_not_invent_success_or_metrics(process_module, tmp_path, fault):
    resource = ready(make_process(process_module, tmp_path))
    row = receipt(resource)
    if fault == "projection":
        row["status"], row["declared_projection_reopened"] = "failed", False
        row["native_open_invoked"], row["native_open_completed"] = False, False
        row["error"] = {"code": "NATIVE_SAVE_READER_FAILED", "type": "ValueError", "failure_stage": "input_validation"}
        # A render/comparison time with no native-open entry is not an observation.
    elif fault == "phase":
        row["native_open_invoked"] = False
    elif fault == "exit_type":
        object.__setattr__(resource, "_process", NS(pid=42, returncode=False, poll=lambda: False))
    output = resource.folder / "reader.json"
    if fault != "missing":
        output.write_text("not JSON" if fault == "malformed" else json.dumps(row))
        output.chmod(0o600)
    with pytest.raises(process_module.BridgeError):
        resource.result(lambda: None)
    assert resource.evidence()["worker_receipt"] is None
    resource.close()


def packed_reader_image(name, events):
    payload = b"known complete encoded pixels:" + name.encode()
    row = {"name": name, "fake_user": False, "native_animation_descriptor_present": True,
           "source": "FILE", "filepath": "//" + name + ".png", "size": [2, 2], "colorspace": "sRGB",
           "alpha_mode": "STRAIGHT", "packed_sha256": hashlib.sha256(payload).hexdigest(),
           "packed_bytes": len(payload), "pixels_sha256": "a" * 64}

    class Packed:
        size = len(payload)

        @property
        def data(self):
            events.append(("packed_bytes", name))
            return payload

    class Pixels:
        def __getitem__(self, index):
            assert index == 0
            events.append(("prime", name))
            image.has_data = True
            return 0.

    class Image:
        @property
        def size(self):
            pytest.fail("Image size getter ran during preloading")

        @property
        def channels(self):
            pytest.fail("Image channels getter ran during preloading")

        @property
        def pixels(self):
            events.append(("pixels_getter", name))
            return Pixels()

    image = Image()
    image.name, image.source, image.filepath = name, "FILE", row["filepath"]
    image.colorspace_settings, image.alpha_mode = NS(name="sRGB"), "STRAIGHT"
    image.use_fake_user, image.has_data, image.packed_file = False, False, Packed()
    return row, image


@pytest.mark.parametrize("fault", ["source", "filepath", "colorspace", "alpha", "fake_user", "missing_packed",
                                 "packed_size", "packed_length", "packed_hash", "missing_image", "extra_image", "duplicate_name"])
def test_reader_rejects_all_packed_input_mismatches_before_any_pixel_getter(addon_package, fault):
    reader = importlib.import_module(f"{addon_package}.native_save_reader")
    events = []
    first, image_a = packed_reader_image("A", events)
    second, image_b = packed_reader_image("B", events)
    images = [image_a, image_b]
    if fault in {"source", "filepath", "alpha", "fake_user"}:
        key = {"alpha": "alpha_mode", "fake_user": "use_fake_user"}.get(fault, fault)
        setattr(image_b, key, True if fault == "fake_user" else "changed")
    elif fault == "colorspace":
        image_b.colorspace_settings.name = "Non-Color"
    elif fault == "missing_packed":
        image_b.packed_file = None
    elif fault == "packed_size":
        image_b.packed_file.size += 1
    elif fault == "packed_length":
        image_b.packed_file = NS(size=second["packed_bytes"], data=b"truncated")
    elif fault == "packed_hash":
        second["packed_sha256"] = "b" * 64
    elif fault == "missing_image":
        images.pop()
    elif fault == "extra_image":
        images.append(packed_reader_image("C", events)[1])
    else:
        image_b.name = image_a.name
    with pytest.raises(ValueError):
        reader._prime_verified_packed_images(NS(images=images), {"images": [first, second]})
    assert not any(event[0] in {"pixels_getter", "prime"} for event in events)
    assert not image_a.has_data and not image_b.has_data


@pytest.mark.parametrize("fault", ["missing", "not_list", "too_many", "duplicate", "extra_field", "missing_field",
                                 "not_row", "source", "name", "fake_user", "animation_flag", "filepath", "colorspace",
                                 "alpha", "size", "boolean_size", "dimension", "pixels", "packed_bytes",
                                 "packed_boolean", "packed_budget", "aggregate_pixels", "aggregate_packed",
                                 "packed_digest", "pixel_digest"])
def test_reader_bounds_immutable_expected_images_before_reading_loaded_images(addon_package, fault):
    reader = importlib.import_module(f"{addon_package}.native_save_reader")
    row, _ = packed_reader_image("A", [])
    expected = {"images": [row]}
    if fault == "missing":
        expected.clear()
    elif fault == "not_list":
        expected["images"] = {}
    elif fault == "too_many":
        expected["images"] *= 5
    elif fault == "duplicate":
        expected["images"] *= 2
    elif fault == "extra_field":
        row["unknown"] = True
    elif fault == "missing_field":
        del row["pixels_sha256"]
    elif fault == "not_row":
        expected["images"] = [None]
    elif fault in {"aggregate_pixels", "aggregate_packed"}:
        second = dict(row, name="B")
        expected["images"].append(second)
        for item in expected["images"]:
            if fault == "aggregate_pixels":
                item["size"] = [1024, 513]
            else:
                item["packed_bytes"] = 11 * 1024 * 1024
    else:
        key, value = {
            "source": ("source", "GENERATED"), "name": ("name", ""), "fake_user": ("fake_user", 0),
            "animation_flag": ("native_animation_descriptor_present", 1), "filepath": ("filepath", None),
            "colorspace": ("colorspace", ""), "alpha": ("alpha_mode", False), "size": ("size", [2]),
            "boolean_size": ("size", [True, 2]), "dimension": ("size", [4097, 1]),
            "pixels": ("size", [1024, 1025]), "packed_bytes": ("packed_bytes", 0),
            "packed_boolean": ("packed_bytes", True), "packed_budget": ("packed_bytes", reader.MAX_PACKED_BYTES + 1),
            "packed_digest": ("packed_sha256", "x" * 64), "pixel_digest": ("pixels_sha256", "A" * 64),
        }[fault]
        row[key] = value

    class NoLoadedImages:
        @property
        def images(self):
            pytest.fail("Loaded images read before expected input validation")

    with pytest.raises(ValueError):
        reader._prime_verified_packed_images(NoLoadedImages(), expected)


def test_reader_verifies_all_packed_roles_and_bytes_before_priming_any_image(addon_package):
    reader = importlib.import_module(f"{addon_package}.native_save_reader")
    events = []
    rows, images = zip(*(packed_reader_image(name, events) for name in ("A", "B")), strict=True)
    reader._prime_verified_packed_images(NS(images=list(images)), {"images": list(rows)})
    assert events == [("packed_bytes", "A"), ("packed_bytes", "B"), ("pixels_getter", "A"), ("prime", "A"),
                      ("pixels_getter", "B"), ("prime", "B")]
    assert all(image.has_data for image in images)


@pytest.mark.parametrize("changed_expected", [False, True])
@pytest.mark.parametrize("packed_images", [False, True])
@pytest.mark.parametrize("capture_fault", [None, "profile", "descriptor", "unsafe_profile", "arbitrary", "projection"])
def test_installed_reader_model_opens_only_owned_copy_and_never_saves_source(
    process_module, addon_package, tmp_path, monkeypatch, changed_expected, packed_images, capture_fault
):
    image_events = []
    image_pairs = [packed_reader_image(name, image_events) for name in ("A", "B")] if packed_images else []
    resource = ready(make_process(process_module, tmp_path, images=[pair[0] for pair in image_pairs]))
    reader = importlib.import_module(f"{addon_package}.native_save_reader")
    events = []
    data = NS(images=[pair[1] for pair in image_pairs])
    fake_bpy = ModuleType("bpy")
    fake_bpy.app = NS(background=True, version_string=resource.version,
                      build_hash=resource.build_hash.encode(), binary_path=str(resource.binary))
    fake_bpy.context = NS(preferences=NS(use_preferences_save=True,
                         filepaths=NS(use_auto_save_temporary_files=True)))
    fake_bpy.types = object()
    census_events = []

    def native_open(**params):
        assert census_events == [True]
        events.append(params)
        assert params == {"filepath": str(resource.folder / "saved.blend"), "load_ui": False, "use_scripts": False}
        return {"FINISHED"}

    fake_bpy.ops = NS(wm=NS(open_mainfile=native_open))
    fake_bpy.data = data
    profile = ModuleType("native_save_profile")
    profile.SCHEMA = "stock_native_project_v1"
    profile.ProfileRefused = importlib.import_module(f"{addon_package}.native_save_profile").ProfileRefused
    profile.canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    def schema_census(types):
        assert types is fake_bpy.types
        census_events.append(True)
        return census_model(process_module)

    profile.schema_census = schema_census

    class HiddenMessage(RuntimeError):
        def __str__(self):
            pytest.fail("Arbitrary exception message must not be formatted")

        def __repr__(self):
            pytest.fail("Arbitrary exception representation must not be formatted")

    def capture(actual):
        assert actual is data
        assert all(image.has_data for image in data.images)
        if packed_images:
            assert image_events[:2] == [("packed_bytes", "A"), ("packed_bytes", "B")]
            assert sum(event[0] == "prime" for event in image_events) == 2
        if capture_fault in {"profile", "descriptor", "unsafe_profile"}:
            reason = {"profile": "UNSUPPORTED_ID_FAMILY:palettes", "descriptor": "NATIVE_DESCRIPTOR_REQUIRED:ParticleEdit.scene",
                      "unsafe_profile": "/private/SECRET project.blend"}[capture_fault]
            raise profile.ProfileRefused(reason)
        if capture_fault == "arbitrary":
            raise HiddenMessage("/private/SECRET project.blend")
        return NS(raw=b'{"changed":true}' if capture_fault == "projection" else resource.expected_raw)

    profile.capture = capture
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    monkeypatch.setitem(sys.modules, "native_save_profile", profile)
    monkeypatch.setattr(reader.sys, "argv", ["blender", "--factory-startup", "--disable-autoexec"])
    monkeypatch.setattr(reader.sys, "path", list(reader.sys.path))
    if changed_expected:
        expected = resource.folder / "expected.json"
        expected.chmod(0o600)
        expected.write_bytes(b"{}")
    result = reader.run(resource.folder, resource.token)
    row = json.loads((resource.folder / "reader.json").read_text())
    assert row["source_restore_writes"] == 0 and row["source_process_contacted"] is False
    assert row["reader_project_save_invoked"] is False and resource.saved_path.exists()
    assert bool(events) is not changed_expected
    failed = changed_expected or capture_fault is not None
    assert result == int(failed)
    assert row["declared_projection_reopened"] is not failed
    assert b"SECRET" not in (resource.folder / "reader.json").read_bytes()
    if changed_expected:
        assert not image_events
    object.__setattr__(resource, "_process", NS(pid=os.getpid(), returncode=result, poll=lambda: result))
    if failed:
        with pytest.raises(process_module.BridgeError) as failure:
            resource.result(lambda: None)
        retained = resource.evidence()["worker_receipt"]
        assert retained["status"] == "failed" and not retained["declared_projection_reopened"]
        error = retained["error"]
        assert failure.value.context["reader_failure"] == error
        assert failure.value.context["reader_schema_diagnostic"] == {
            "available": not changed_expected, "reason": "NOT_PRODUCED" if changed_expected else "AVAILABLE"}
        assert (resource.folder / "schema-census.json").exists() is not changed_expected
        assert error["failure_stage"] == ("input_validation" if changed_expected else
                                          "projection_compare" if capture_fault == "projection" else "projection_capture")
        if not changed_expected and capture_fault in {"profile", "descriptor"}:
            assert error["profile_reason"] == ("UNSUPPORTED_ID_FAMILY:palettes" if capture_fault == "profile" else
                                               "NATIVE_DESCRIPTOR_REQUIRED:ParticleEdit.scene")
        else:
            assert "profile_reason" not in error
        if changed_expected:
            assert retained["timings"]["native_open_seconds"] is None
    else:
        assert row["error"] is None and set(row) == process_module.RECEIPT_KEYS
        assert not (resource.folder / "schema-census.json").exists()
        assert resource.result(lambda: None)["declared_projection_reopened"]
    resource.close()
