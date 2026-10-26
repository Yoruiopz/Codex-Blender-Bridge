from __future__ import annotations

import base64
import hashlib
import importlib.util
import itertools
import json
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest


@pytest.fixture
def probe(monkeypatch):
    import sys
    for name in ("bpy", "addon_utils"):
        monkeypatch.setitem(sys.modules, name, SimpleNamespace())
    path = Path(__file__).resolve().parents[1] / "scripts/blender_installed_addon_probe_smoke.py"
    spec = importlib.util.spec_from_file_location("installed_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(tmp_path, names):
    path = tmp_path / "input.zip"
    members = {}
    with ZipFile(path, "w") as archive:
        for name in names:
            info = ZipInfo(name)
            info.external_attr = 0o100644 << 16
            archive.writestr(info, b"test")
            members[name] = hashlib.sha256(b"test").hexdigest()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "members_sha256": members}


@pytest.mark.parametrize("bad", [
    "blender_codex_bridge/../escaped.py", "/blender_codex_bridge/a.py",
    "blender_codex_bridge/a\\b.py", "blender_codex_bridge/C:a.py",
    "blender_codex_bridge//a.py", "blender_codex_bridge/./a.py",
    "other/__init__.py", "blender_codex_bridge/__INIT__.PY",
])
def test_unsafe_or_case_alias_archive_never_reaches_installer(probe, tmp_path, bad):
    configured = record(tmp_path, ["blender_codex_bridge/__init__.py", bad])
    owned = tmp_path / "owned"
    owned.mkdir()
    with pytest.raises(AssertionError):
        probe._archive(configured, owned, "bad")


def test_changed_archive_and_changed_member_fail_independent_proofs(probe, tmp_path):
    configured = record(tmp_path, ["blender_codex_bridge/__init__.py"])
    owned = tmp_path / "owned"
    owned.mkdir()
    configured["sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        probe._archive(configured, owned, "hash")
    configured["sha256"] = hashlib.sha256(Path(configured["path"]).read_bytes()).hexdigest()
    configured["members_sha256"]["blender_codex_bridge/__init__.py"] = "0" * 64
    with pytest.raises(AssertionError):
        probe._archive(configured, owned, "members")


def registry(descriptors, listed=None):
    names = [row["name"] for row in descriptors] if listed is None else listed
    return SimpleNamespace(list_tools=lambda: tuple(names), describe=lambda: {"tools": descriptors})


def expected_names(tmp_path, names):
    path = tmp_path / "expected-tools.json"
    payload = (json.dumps(names, indent=2) + "\n").encode()
    path.write_bytes(payload)
    return {"expected_tools": len(names), "expected_tool_names": sorted(names),
            "expected_tool_names_sha256": hashlib.sha256(payload).hexdigest(),
            "expected_tool_names_source": str(path)}


def test_public_projection_includes_toolsets_list_and_excludes_multiple_internal_tools(probe):
    descriptors = [{"name": "toolsets.list", "remote": True}, {"name": "scene.inspect", "remote": True},
                   {"name": "checkpoint.restore_last", "remote": False},
                   {"name": "jobs._scene_turn", "remote": False}, {"name": "jobs._other", "remote": False}]
    observed = probe._public_tool_surface(registry(descriptors), {"expected_tools": 2})
    assert observed["public_tool_names"] == ["scene.inspect", "toolsets.list"]
    assert observed["documented_tool_count"] == 2
    assert observed["hidden_tool_count"] == 3
    assert observed["hidden_tool_metadata"] == [
        {"name": "checkpoint.restore_last", "remote": False},
        {"name": "jobs._other", "remote": False}, {"name": "jobs._scene_turn", "remote": False}]
    assert observed["exact_expected_tool_names_verified"] is False


def test_public_projection_matches_actual_addon_and_mcp_surface(probe, addon_package, tmp_path):
    from mcp_server.tool_registry import create_default_registry

    actual = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools").register_all(actual)
    names = sorted(create_default_registry(None).tool_names(include_disabled=True))
    configured = expected_names(tmp_path, names)
    observed = probe._public_tool_surface(actual, configured)
    assert observed["public_tool_names"] == names
    assert "toolsets.list" in observed["public_tool_names"]
    # The runtime registers jobs._scene_turn separately from static register_all.
    assert "checkpoint.restore_last" in {item["name"] for item in observed["hidden_tool_metadata"]}
    assert "jobs._scene_turn" not in observed["public_tool_names"]
    assert observed["exact_expected_tool_names_verified"] is True
    assert observed["expected_tool_names_source_sha256"] == configured["expected_tool_names_sha256"]


@pytest.mark.parametrize("remote", [None, 0, 1, "true", [], {}])
def test_public_projection_refuses_nonboolean_remote_metadata(probe, remote):
    with pytest.raises(AssertionError, match="explicit bool"):
        probe._public_tool_surface(registry([{"name": "toolsets.list", "remote": remote}]), {"expected_tools": 1})


@pytest.mark.parametrize("descriptors,listed", [
    ([{"name": "toolsets.list"}], ["toolsets.list"]),
    ([{"name": "toolsets.list", "remote": True}] * 2, ["toolsets.list", "scene.inspect"]),
    ([{"name": "toolsets.list", "remote": True}], ["toolsets.list", "scene.inspect"]),
    ([{"name": "toolsets.list", "remote": True}, {"name": "scene.inspect", "remote": True}], ["toolsets.list"]),
    ([{"name": "toolsets.list", "remote": True}], ["scene.inspect"]),
    ([{"name": "toolsets.list", "remote": True}], ["toolsets.list", "toolsets.list"]),
    ([{"name": "bad\nname", "remote": True}], ["bad\nname"]),
    ([{"name": 1, "remote": True}], [1]),
])
def test_public_projection_refuses_incomplete_duplicate_or_invalid_descriptors(probe, descriptors, listed):
    with pytest.raises(AssertionError):
        probe._public_tool_surface(registry(descriptors, listed), {"expected_tools": 1})


@pytest.mark.parametrize("description", [None, [], {}, {"tools": None}, {"tools": ()}, {"tools": [None]}])
def test_public_projection_refuses_malformed_descriptor_inventory(probe, description):
    actual = SimpleNamespace(list_tools=lambda: ("toolsets.list",), describe=lambda: description)
    with pytest.raises(AssertionError):
        probe._public_tool_surface(actual, {"expected_tools": 1})


@pytest.mark.parametrize("names", [["toolsets.list", "scene.missing"], ["toolsets.list", "jobs._scene_turn"]])
def test_public_projection_checks_exact_names_even_when_counts_match(probe, tmp_path, names):
    actual = registry([{"name": "toolsets.list", "remote": True}, {"name": "scene.inspect", "remote": True},
                       {"name": "jobs._scene_turn", "remote": False}])
    with pytest.raises(AssertionError, match=r"missing.*extra"):
        probe._public_tool_surface(actual, expected_names(tmp_path, names))


@pytest.mark.parametrize("field", ["expected_tool_names", "expected_tool_names_sha256", "expected_tool_names_source"])
def test_exact_name_pin_requires_all_three_fields(probe, tmp_path, field):
    configured = expected_names(tmp_path, ["toolsets.list"])
    del configured[field]
    with pytest.raises(AssertionError, match="Incomplete"):
        probe._expected_tool_names(configured)


@pytest.mark.parametrize("names", [[], ["toolsets.list", "toolsets.list"], ["bad name"], [True], "toolsets.list"])
def test_expected_name_configuration_refuses_bad_names_duplicates_and_types(probe, tmp_path, names):
    configured = expected_names(tmp_path, ["toolsets.list"])
    configured["expected_tool_names"] = names
    with pytest.raises(AssertionError, match="Invalid expected tool names"):
        probe._expected_tool_names(configured)


@pytest.mark.parametrize("count", [True, False, 1.0, "1", 0, 4097, None])
def test_expected_name_configuration_refuses_noninteger_or_unbounded_counts(probe, count):
    with pytest.raises(AssertionError, match="count"):
        probe._expected_tool_names({"expected_tools": count})


def test_expected_name_source_hash_and_payload_are_both_verified(probe, tmp_path):
    configured = expected_names(tmp_path, ["toolsets.list"])
    path = Path(configured["expected_tool_names_source"])
    path.write_text('["scene.inspect"]\n')
    with pytest.raises(AssertionError, match="file changed"):
        probe._expected_tool_names(configured)
    configured["expected_tool_names_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(AssertionError, match="disagrees"):
        probe._expected_tool_names(configured)


@pytest.mark.parametrize("names,configured,expected", [
    (["toolsets.list"], {}, False),
    (["toolsets.list"], {"expected_geometry_preview": False}, False),
    (["preview.geometry_image", "preview.geometry_start"], {"expected_geometry_preview": True}, True),
    (["preview.geometry_image", "preview.geometry_start"],
     {"expected_tool_names": ["preview.geometry_image", "preview.geometry_start"]}, True),
])
def test_preview_execution_selected_by_pinned_capability_not_version(probe, names, configured, expected):
    for version in ("0.3.0", "0.5.0", "0.6.0", "9.9.9"):
        assert probe._preview_expected({"version": version, **configured}, {"public_tool_names": names}) is expected


@pytest.mark.parametrize("names,configured", [
    (["preview.geometry_start"], {"expected_geometry_preview": True}),
    (list(("preview.geometry_image", "preview.geometry_start")), {}),
    (list(("preview.geometry_image", "preview.geometry_start")), {"expected_geometry_preview": False}),
    (["toolsets.list"], {"expected_geometry_preview": True}),
    (["toolsets.list"], {"expected_geometry_preview": 0}),
    (["toolsets.list"], {"expected_geometry_preview": None}),
    (["toolsets.list"], {"expected_tool_names": ["preview.geometry_start"]}),
    (["toolsets.list"], {"expected_tool_names": ["toolsets.list"], "expected_geometry_preview": True}),
])
def test_preview_expectation_refuses_ambiguous_partial_or_disagreeing_capabilities(probe, names, configured):
    with pytest.raises(AssertionError):
        probe._preview_expected(configured, {"public_tool_names": names})


def png_payload(*, width=128, rows=None):
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)

    pixels = b"\x00" + b"\x30\x50\x70\xff" * 128
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 128, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels * 128 if rows is None else rows)) + chunk(b"IEND", b""))


def test_independent_png_bytes_dimensions_crc_and_decompressed_size(probe):
    raw = png_payload()
    observed, proof = probe._png_proof(base64.b64encode(raw).decode("ascii"))
    assert observed == raw and proof["sha256"] == hashlib.sha256(raw).hexdigest()
    assert (proof["width"], proof["height"], proof["bytes"]) == (128, 128, len(raw))
    assert proof["compressed_rows_verified"] is True and proof["visual_review_performed"] is False


@pytest.mark.parametrize("payload", [
    b"not png", png_payload(width=127), png_payload(rows=b"x" * (128 * 513 + 1)),
    png_payload(rows=b"\x05" + b"\x00" * (128 * 513 - 1)),
    png_payload()[:-1], png_payload() + b"extra", png_payload()[:50] + b"\xff" + png_payload()[51:],
])
def test_independent_png_proof_refuses_mismatch_crc_truncation_or_bomb(probe, payload):
    with pytest.raises(AssertionError):
        probe._png_proof(base64.b64encode(payload).decode("ascii"))


def cube_model():
    points = list(itertools.product((-1., 1.), repeat=3))
    edges = [(a, b) for a in range(8) for b in range(a + 1, 8)
             if sum(x != y for x, y in zip(points[a], points[b], strict=True)) == 1]
    faces = [[index for index, point in enumerate(points) if point[axis] == sign]
             for axis in range(3) for sign in (-1., 1.)]
    faces = [[face[0], face[1], face[3], face[2]] for face in faces]
    mesh = SimpleNamespace(vertices=[SimpleNamespace(co=list(point)) for point in points],
                           edges=[SimpleNamespace(vertices=edge) for edge in edges],
                           polygons=[SimpleNamespace(vertices=face) for face in faces],
                           shape_keys=None, materials=[], as_pointer=lambda: 102, session_uid=202)
    return SimpleNamespace(type="MESH", data=mesh, as_pointer=lambda: 101, session_uid=201,
                           rotation_mode="XYZ", location=[1., 2., 3.], rotation_euler=[0., 0., 0.], scale=[1., 1., 1.],
                           delta_location=[0., 0., 0.], delta_rotation_euler=[0., 0., 0.],
                           delta_rotation_quaternion=[1., 0., 0., 0.], delta_scale=[1., 1., 1.],
                           parent=None, animation_data=None, modifiers=[], constraints=[])


def test_independent_cube_geometry_and_raw_channel_oracle(probe, addon_package):
    cube = cube_model()
    probe.bpy.data = SimpleNamespace(objects={"Cube": cube})
    projection = probe._cube_projection("Cube")
    packaged = importlib.import_module(f"{addon_package}.geometry_preview_dto")
    dto = packaged.make_dto("Cube", projection["vertices"], projection["edges"], projection["polygons"],
                            location=(1., 2., 3.))
    assert probe._cube_dto_sha256("Cube", projection) == hashlib.sha256(packaged.canonical(dto)).hexdigest()
    cube.data.vertices[0].co[0] = -.5
    with pytest.raises(AssertionError, match="vertex"):
        probe._cube_projection("Cube")


@pytest.mark.parametrize("change", ["edge", "face", "transform", "delta", "parent", "material"])
def test_independent_cube_oracle_refuses_wrong_topology_transforms_or_dependencies(probe, change):
    cube = cube_model()
    probe.bpy.data = SimpleNamespace(objects={"Cube": cube})
    if change == "edge":
        cube.data.edges[0].vertices = (0, 7)
    elif change == "face":
        cube.data.polygons[0].vertices = (0, 1, 2)
    elif change == "transform":
        cube.location[0] = 2.
    elif change == "delta":
        cube.delta_location[0] = .5
    elif change == "parent":
        cube.parent = object()
    else:
        cube.data.materials.append(object())
    with pytest.raises(AssertionError):
        probe._cube_projection("Cube")


def preview_model(probe, monkeypatch, tmp_path):
    import sys

    installed = tmp_path / "installed scripts with spaces" / "addons" / probe.MODULE
    installed.mkdir(parents=True)
    members = {}
    for name in ("geometry_preview_worker.py", "geometry_preview_dto.py", "geometry_preview_process.py"):
        path = installed / name
        path.write_text("# installed " + name + "\n")
        members[probe.MODULE + "/" + name] = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(sys.modules, probe.MODULE + ".geometry_preview_process",
                        SimpleNamespace(__file__=str(installed / "geometry_preview_process.py")))
    prefs = SimpleNamespace(allow_inspect_scene=True, allow_viewport_capture=True, allow_external_files=False)
    cube = cube_model()
    probe.bpy.context = SimpleNamespace(preferences=SimpleNamespace(addons={probe.MODULE: SimpleNamespace(preferences=prefs)}))
    probe.bpy.app = SimpleNamespace(build_hash=b"d13f752e3b9c", version=(5, 2, 2), build_type=b"Release",
                                   version_string="5.2.2", binary_path=str(tmp_path / "blender"))
    probe.bpy.data = SimpleNamespace(objects={"Cube": cube})
    expected = probe._cube_dto_sha256("Cube", probe._cube_projection("Cube"))
    raw = png_payload()
    sha = hashlib.sha256(raw).hexdigest()
    worker = {"process_id": probe.os.getpid() + 100, "build_hash": "d13f752e3b9c", "blender_version": "5.2.2",
              "dto_sha256": expected, "input_sha256": expected, "geometry_reconstructed": True,
              "raw_channels_reconstructed": True, "png": {"sha256": sha},
              "world_bounds": {"min": [0., 1., 2.], "max": [2., 3., 4.]}}
    programs = {name: members[probe.MODULE + "/" + name] for name in ("geometry_preview_worker.py", "geometry_preview_dto.py")}
    result = {"preview_id": "geometry_preview_owned", "source_fingerprint": expected, "width": 128, "height": 128,
              "mime_type": "image/png", "image_sha256": sha, "scene_changed": False, "project_saved": False,
              "worker_evidence": {"worker": worker, "parent_validated_png": {"sha256": sha}, "program_sha256": programs}}
    folder = tmp_path / "removed staging folder"
    process = SimpleNamespace(pid=worker["process_id"], returncode=0,
                              args=[probe.bpy.app.binary_path, "--background", "--factory-startup", "--disable-autoexec",
                                    "--python", str(installed / "geometry_preview_worker.py"), "--bundle", str(folder)])
    owned = SimpleNamespace(job_id="job_owned", process=SimpleNamespace(process=process, folder=folder))
    effects = {"worker_pid": worker["process_id"], "worker_reaped": True, "worker_exit_code": 0,
               "staging_cleanup": "complete", "retained_staging_path": None, "worker_receipt": worker}
    row = {"terminal": True, "state": "SUCCEEDED", "error": None, "result": result, "external_effects": effects}
    calls = []
    jobs = SimpleNamespace(active=None, ticks=0, cancelled=0)

    class BridgeError(Exception):
        code = "PERMISSION_DENIED"

        def __init__(self):
            super().__init__()
            self.context = {"missing_permissions": ["ACCESS_EXTERNAL_FILES"]}

    def dispatch(method, params):
        calls.append((method, prefs.allow_external_files))
        if method == "preview.geometry_start":
            if not prefs.allow_external_files:
                raise BridgeError()
            jobs.active = owned
            return {"accepted": True, "terminal": False, "job_id": owned.job_id, "source_fingerprint": expected}
        if method == "jobs.inspect":
            return row if jobs.ticks else {"terminal": False}
        assert method == "preview.geometry_image"
        return {**result, "png_base64": base64.b64encode(raw).decode("ascii")}

    def tick():
        jobs.ticks += 1
        jobs.active = None

    def cancel(reason):
        jobs.cancelled += 1
        jobs.active = None

    jobs.tick, jobs.cancel_all = tick, cancel
    permissions = SimpleNamespace(snapshot=lambda: {"INSPECT_SCENE": prefs.allow_inspect_scene,
                                                   "CAPTURE_VIEWPORT": prefs.allow_viewport_capture,
                                                   "ACCESS_EXTERNAL_FILES": prefs.allow_external_files})
    runtime = SimpleNamespace(dispatch=dispatch, jobs=jobs, permissions=permissions)
    return SimpleNamespace(runtime=runtime, installed=installed, members=members, BridgeError=BridgeError,
                           prefs=prefs, calls=calls, worker=worker, effects=effects, result=result, owned=owned, cube=cube)


def test_installed_preview_calls_public_tools_with_real_consent_and_retains_independent_evidence(probe, monkeypatch, tmp_path):
    model = preview_model(probe, monkeypatch, tmp_path)
    observed = probe._installed_preview(model.runtime, "fresh-candidate", "Cube", model.installed, model.members, model.BridgeError)
    assert observed["completed"] and observed["default_permission_denied"] and observed["consent_restored"]
    assert observed["manual_main_thread_ticks"] == 1 and model.runtime.jobs.cancelled == 0
    assert model.calls[:2] == [("preview.geometry_start", False), ("preview.geometry_start", True)]
    assert [call[0] for call in model.calls[2:]] == ["jobs.inspect", "jobs.inspect", "preview.geometry_image"]
    assert model.prefs.allow_external_files is False
    assert observed["before"] == observed["after"] and observed["worker_and_parent_process_separate"]
    assert Path(observed["png_path"]).is_file() and Path(observed["receipt_path"]).is_file()
    assert all(" " in program["installed_path"] for program in observed["worker_program"].values())


@pytest.mark.parametrize("fault", ["pid", "build", "bounds", "dto", "png", "program", "exit", "reaping", "cleanup", "folder", "command", "source", "signed_zero"])
def test_installed_preview_rejects_contradictory_worker_evidence_and_restores_consent(probe, monkeypatch, tmp_path, fault):
    model = preview_model(probe, monkeypatch, tmp_path)
    if fault == "pid":
        model.worker["process_id"] = probe.os.getpid()
    elif fault == "build":
        model.worker["build_hash"] = "different"
    elif fault == "bounds":
        model.worker["world_bounds"]["min"][0] = .25
    elif fault == "dto":
        model.worker["input_sha256"] = "0" * 64
    elif fault == "png":
        model.worker["png"]["sha256"] = "0" * 64
    elif fault == "program":
        model.result["worker_evidence"]["program_sha256"]["geometry_preview_dto.py"] = "0" * 64
    elif fault == "exit":
        model.owned.process.process.returncode = 1
    elif fault == "reaping":
        model.effects["worker_reaped"] = False
    elif fault == "cleanup":
        model.effects["staging_cleanup"] = "unknown"
    elif fault == "folder":
        model.owned.process.folder.mkdir()
    elif fault == "command":
        model.owned.process.process.args[-3] = "/unrelated/geometry_preview_worker.py"
    else:
        old_tick = model.runtime.jobs.tick

        def edit_then_tick():
            old_tick()
            if fault == "signed_zero":
                model.cube.rotation_euler[0] = -0.
            else:
                model.cube.location[0] = 4.

        model.runtime.jobs.tick = edit_then_tick
    with pytest.raises(AssertionError):
        probe._installed_preview(model.runtime, "upgrade", "Cube", model.installed, model.members, model.BridgeError)
    assert model.prefs.allow_external_files is False and model.runtime.jobs.cancelled == 1
    receipt = model.installed.parent.parent.parent / "installed preview evidence with spaces" / "upgrade.json"
    retained = json.loads(receipt.read_bytes())
    assert retained["completed"] is False and retained["consent_restored"] is True
    assert not receipt.with_suffix(".png").exists()


def test_installed_runner_real_script_and_worker_path_contains_spaces(probe, monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/run_blender_checks.py"
    spec = importlib.util.spec_from_file_location("installed_preview_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    def launch(command, **kwargs):
        scripts = Path(kwargs["env"]["BLENDER_USER_SCRIPTS"])
        assert scripts.is_dir() and scripts.name == "installed scripts with spaces"
        assert scripts.is_relative_to(tmp_path)
        assert "--background" in command
        kwargs["stdout"].write(b'BLENDER_INSTALLED_ADDON_PROBE_OK {"blender_version":"5.2.2"}\n')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", launch)
    assert runner.run_case(Path("blender"), "installed_addon_probe", tmp_path, 10)["status"] == "passed"


@pytest.mark.parametrize("fault", ["malformed_acceptance", "default_denial_bypassed", "cancel_failure"])
def test_started_job_cleanup_does_not_depend_on_parsing_accepted_response(probe, monkeypatch, tmp_path, fault):
    model = preview_model(probe, monkeypatch, tmp_path)
    original = model.runtime.dispatch

    def dispatch(method, params):
        if method == "preview.geometry_start" and fault == "default_denial_bypassed":
            model.runtime.jobs.active = model.owned
            return {"accepted": True}
        result = original(method, params)
        if method == "preview.geometry_start":
            return {"accepted": False}  # A real accepted owner with an inconsistent envelope.
        return result

    model.runtime.dispatch = dispatch
    if fault == "cancel_failure":
        def cancel(reason):
            model.runtime.jobs.cancelled += 1
            raise RuntimeError("cleanup failed")

        model.runtime.jobs.cancel_all = cancel
    with pytest.raises((AssertionError, RuntimeError)):
        probe._installed_preview(model.runtime, "upgrade", "Cube", model.installed, model.members, model.BridgeError)
    assert model.prefs.allow_external_files is False and model.runtime.jobs.cancelled == 1
    receipt = model.installed.parent.parent.parent / "installed preview evidence with spaces" / "upgrade.json"
    retained = json.loads(receipt.read_bytes())
    assert retained["completed"] is False and retained["consent_restored"] is True
    assert retained["failure"]["type"] == "AssertionError"


@pytest.mark.parametrize("has_preview", [False, True])
@pytest.mark.parametrize("failure", [None, "create", "transform", "provider_drift"])
def test_package_row_keeps_installed_permission_services_and_restores_preference_grants(
        probe, addon_package, monkeypatch, tmp_path, has_preview, failure):
    import sys

    permission_module = importlib.import_module(f"{addon_package}.permissions")

    class BridgeError(Exception):
        code = "PERMISSION_DENIED"

    prefs = SimpleNamespace(auto_start=False, allow_inspect_scene=False,
                            allow_transform_objects=False, allow_external_files=False)
    default = {"DELETE_OBJECTS": False, "EXECUTE_PYTHON": False, "ACCESS_EXTERNAL_FILES": False,
               "INSPECT_SCENE": False, "TRANSFORM_OBJECTS": False}

    def preference_source():
        return {**default, "INSPECT_SCENE": prefs.allow_inspect_scene,
                "TRANSFORM_OBJECTS": prefs.allow_transform_objects}

    real = permission_module.PermissionManager(preference_source)
    probe.bpy.context = SimpleNamespace(preferences=SimpleNamespace(addons={probe.MODULE: SimpleNamespace(preferences=prefs)}))
    probe.bpy.data = SimpleNamespace(objects={})
    probe.bpy.ops = SimpleNamespace(preferences=SimpleNamespace(addon_install=lambda **kwargs: {"FINISHED"}))
    installed_module = SimpleNamespace(__name__=probe.MODULE, __file__=str(tmp_path / "installed.py"), bl_info={"version": (0, 8, 0)})
    probe.addon_utils.modules_refresh = lambda: None
    probe.addon_utils.modules = lambda: [installed_module]
    probe.addon_utils.enable = lambda *args, **kwargs: installed_module
    probe.addon_utils.check = lambda name: (True, True)
    runtime = SimpleNamespace(permissions=real, executor=SimpleNamespace(permissions=real), registry=object())
    calls, foreign_calls = [], []

    def foreign_provider():
        foreign_calls.append(True)
        raise AssertionError("A substituted provider must not be invoked")

    def dispatch(method, params):
        calls.append(method)
        assert runtime.permissions is real and runtime.executor.permissions is real
        assert real._source is preference_source
        if method == "bridge.status":
            return {"addon_version": "0.8.0"}
        if method == "object.delete":
            assert prefs.allow_transform_objects is False
            raise BridgeError()
        if method in {"object.create", "transform.set"}:
            assert prefs.allow_transform_objects is True and prefs.allow_inspect_scene is True
            grants = real.snapshot()
            assert grants["TRANSFORM_OBJECTS"] is True and grants["INSPECT_SCENE"] is True
            assert all(grants[key] is False for key in ("DELETE_OBJECTS", "EXECUTE_PYTHON", "ACCESS_EXTERNAL_FILES"))
        if method == "object.create":
            if failure == "create":
                raise RuntimeError("injected create failure")
            probe.bpy.data.objects[params["name"]] = SimpleNamespace(location=(0., 0., 0.))
            if failure == "provider_drift":
                real._source = foreign_provider
            return {"object": params["name"]}
        if method == "transform.set":
            if failure == "transform":
                raise RuntimeError("injected transform failure")
            probe.bpy.data.objects[params["object_name"]].location = tuple(params["location"])
        else:
            assert method in {"toolsets.enable", "toolsets.disable"}

    runtime.dispatch = dispatch
    monkeypatch.setitem(sys.modules, probe.MODULE + ".runtime", SimpleNamespace(get_runtime=lambda: runtime))
    monkeypatch.setitem(sys.modules, probe.MODULE + ".errors", SimpleNamespace(BridgeError=BridgeError))
    monkeypatch.setitem(sys.modules, probe.MODULE + ".permissions", permission_module)
    monkeypatch.setattr(probe, "_unload", lambda: None)
    monkeypatch.setattr(probe, "_installed_bytes", lambda *args: None)
    monkeypatch.setattr(probe, "_network", lambda *args: {"ok": True})
    names = sorted(probe.PREVIEW_TOOLS) if has_preview else ["toolsets.list"]
    monkeypatch.setattr(probe, "_public_tool_surface", lambda *args: {"public_tool_names": names})
    preview_calls = []

    def preview(actual, *args):
        assert actual is runtime and runtime.permissions is real and runtime.executor.permissions is real
        assert real._source is preference_source
        assert prefs.allow_transform_objects is False and prefs.allow_inspect_scene is False
        preview_calls.append(args)
        return {"completed": True}

    monkeypatch.setattr(probe, "_installed_preview", preview)
    arguments = ("fresh-candidate", tmp_path / "package.zip", {},
                 {"version": "0.8.0", "sha256": "0" * 64, "expected_geometry_preview": has_preview}, tmp_path)
    if failure is None:
        observed = probe._exercise(*arguments)
        assert len(preview_calls) == int(has_preview) and observed["geometry_preview_expected"] is has_preview
        assert observed["permission_service_identities_preserved_throughout"] is True
        assert observed["permission_provider_identities_preserved"] is True
        assert observed["creation_preference_consent_restored"] is True
        assert observed["creation_permissions"]["TRANSFORM_OBJECTS"] is True
        assert "transform.set" in calls
    else:
        with pytest.raises(AssertionError if failure == "provider_drift" else RuntimeError):
            probe._exercise(*arguments)
        assert preview_calls == []
        if failure in {"create", "provider_drift"}:
            assert "transform.set" not in calls
    assert runtime.permissions is real and runtime.executor.permissions is real
    assert prefs.allow_transform_objects is False and prefs.allow_inspect_scene is False
    assert foreign_calls == []
    assert "object.create" in calls and "object.delete" in calls
