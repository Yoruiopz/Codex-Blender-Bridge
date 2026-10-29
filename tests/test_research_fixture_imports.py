"""Importing native fixture helpers must never start their owned experiment."""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import runpy
import socket
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = (
    "scripts.blender_current_pixels_lifecycle_smoke",
    "scripts.blender_glb_stage_runtime_smoke",
    "scripts.blender_glb_stage_smoke",
    "scripts.blender_current_pixels_paired_recovery_smoke",
    "scripts.blender_native_save_smoke",
    "scripts.blender_geometry_preview_smoke",


    "scripts.blender_executor_history_containment_smoke",
    "scripts.blender_isolated_asset_preview_probe_smoke",
    "scripts.native_isolated_asset_preview",
    "scripts.blender_rigid_timer_probe_smoke",
    "scripts.blender_rigid_lifecycle_probe_smoke",
    "scripts.blender_scene_job_kernel_smoke",
    "scripts.blender_rigid_evaluation_jobs_smoke",
    "scripts.blender_simulation_cache_probe_smoke",
    "scripts.blender_camera_focus_smoke",
    "scripts.blender_animation_curve_sampling_smoke",
    "scripts.blender_animation_intent_smoke",
    "scripts.blender_surface_publication_probe",
    "scripts.blender_sculpt_mask_smoke",
    "scripts.blender_character_revision_smoke",
    "scripts.blender_artist_target_verification_smoke",
    "scripts.blender_artist_sidebar_smoke",
    "scripts.blender_artist_quaternion_storage_smoke",
    "scripts.blender_artist_quaternion_smoke",
    "scripts.blender_uv_edit_storage_smoke",
    "scripts.blender_uv_edit_boundary_probe",
    "scripts.blender_large_surface_paint_smoke",
    "scripts.blender_uv_edit_guard_smoke",
    "scripts.blender_weight_edit_guard_smoke",
    "scripts.native_character_revision_evidence",
    "scripts.native_character_evidence",
    "scripts.native_cache_evidence",
)


@pytest.fixture
def fixture_imports(addon_package, monkeypatch):
    events = []

    def forbidden(name):
        def call(*_args, **_kwargs):
            events.append(name)
            pytest.fail(f"Fixture import unexpectedly ran {name}")
        return call

    def module(name, **values):
        value = ModuleType(name)
        value.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, value)
        return value

    permissions = importlib.import_module(f"{addon_package}.permissions")
    errors = importlib.import_module(f"{addon_package}.errors")
    package = module("blender_codex_bridge", register=forbidden("addon.register"), __path__=[])
    module("blender_codex_bridge.errors", BridgeError=errors.BridgeError)
    module("blender_codex_bridge.permissions", Permission=permissions.Permission,
           PermissionManager=forbidden("PermissionManager construction"))
    module("blender_codex_bridge.command_queue", QueuedRequest=forbidden("QueuedRequest construction"))
    module("blender_codex_bridge.protocol", Request=forbidden("Request construction"))
    module("blender_codex_bridge.request_lifecycle", RequestLifetime=NS(local=forbidden("local request")))
    module("blender_codex_bridge.runtime", get_runtime=forbidden("get_runtime"))
    module("blender_codex_bridge.scene_job_reservations", TURN_METHOD="jobs._scene_turn")
    module("blender_codex_bridge.tool_registry", check_final_mutation=forbidden("mutation gate"))
    tools = module("blender_codex_bridge.tools", __path__=[])
    for name in ("_rigid_body_scope", "_scene_checkpoint_roles", "surface_brushes", "rig_ik"):
        setattr(tools, name, module(f"blender_codex_bridge.tools.{name}"))
    tools.rigid_body = module("blender_codex_bridge.tools.rigid_body", _Boundary=type("Boundary", (), {}),
                              PERMISSIONS=(permissions.Permission.EDIT_SCENE,))
    package.tools = tools
    timers = []

    def register(callback, **kwargs):
        timers.append((callback.__name__, kwargs))

    module("bpy", app=NS(timers=NS(register=register)),
           ops=NS(wm=NS(quit_blender=forbidden("quit_blender"))))
    monkeypatch.setattr(threading, "Thread", forbidden("worker construction"))
    monkeypatch.setattr(socket, "create_connection", forbidden("socket connection"))
    for name in ("write_text", "write_bytes", "mkdir", "replace"):
        monkeypatch.setattr(Path, name, forbidden(f"Path.{name}"))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.syspath_prepend(str(ROOT))
    scripts = importlib.import_module("scripts")
    previous = {name: getattr(scripts, name.rsplit(".", 1)[1], None) for name in HELPERS}
    for name in HELPERS:
        monkeypatch.delitem(sys.modules, name, raising=False)
    try:
        yield NS(events=events, timers=timers)
    finally:
        for name in HELPERS:
            sys.modules.pop(name, None)
            attribute = name.rsplit(".", 1)[1]
            if previous[name] is not None:
                setattr(scripts, attribute, previous[name])
            elif hasattr(scripts, attribute):
                delattr(scripts, attribute)


@pytest.mark.parametrize("name,helper", [
    ("scripts.blender_current_pixels_lifecycle_smoke", "main"),
    ("scripts.blender_glb_stage_smoke", "main"),
    ("scripts.blender_glb_stage_runtime_smoke", "main"),
    ("scripts.blender_current_pixels_paired_recovery_smoke", "main"),
    ("scripts.blender_native_save_smoke", "main"),
    ("scripts.blender_geometry_preview_smoke", "main"),


    ("scripts.blender_executor_history_containment_smoke", "main"),
    ("scripts.blender_isolated_asset_preview_probe_smoke", "main"),
    ("scripts.native_isolated_asset_preview", "validate_dto"),
    ("scripts.blender_rigid_timer_probe_smoke", "checkpointed_cache"),
    ("scripts.blender_rigid_lifecycle_probe_smoke", "make_scene"),
    ("scripts.blender_scene_job_kernel_smoke", "RigidDriver"),
    ("scripts.blender_rigid_evaluation_jobs_smoke", "Fixture"),
    ("scripts.blender_simulation_cache_probe_smoke", "values"),
    ("scripts.blender_camera_focus_smoke", "main"),
    ("scripts.blender_animation_curve_sampling_smoke", "main"),
    ("scripts.blender_animation_intent_smoke", "main"),
    ("scripts.blender_surface_publication_probe", "main"),
    ("scripts.blender_sculpt_mask_smoke", "main"),
    ("scripts.blender_character_revision_smoke", "main"),
    ("scripts.blender_artist_target_verification_smoke", "main"),
    ("scripts.blender_artist_sidebar_smoke", "main"),
    ("scripts.blender_artist_quaternion_storage_smoke", "main"),
    ("scripts.blender_artist_quaternion_smoke", "main"),
    ("scripts.blender_uv_edit_storage_smoke", "main"),
    ("scripts.blender_uv_edit_boundary_probe", "main"),
    ("scripts.blender_large_surface_paint_smoke", "main"),
    ("scripts.blender_uv_edit_guard_smoke", "main"),
    ("scripts.blender_weight_edit_guard_smoke", "main"),
    ("scripts.native_character_revision_evidence", "lbs_vertices"),
])
def test_importing_helper_fixture_does_not_start_experiment(fixture_imports, name, helper):
    imported = importlib.import_module(name)
    assert callable(getattr(imported, helper))
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_current_pixels_census_has_no_instance_or_scene_access():
    source = (ROOT / "scripts/blender_current_pixels_lifecycle_smoke.py").read_text()
    tree = ast.parse(source)
    # The explicit source-graph mode owns its separate native setup. The
    # unchanged census branch must still contain metadata access only.
    tree = ast.Module(body=[node for node in tree.body if not isinstance(node, ast.FunctionDef)
                           or node.name != "native_graph_probe"], type_ignores=[])
    assert not any(isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                   and node.value.id == "bpy" and node.attr in {"data", "context", "ops"}
                   for node in ast.walk(tree))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "catalog_census"]
    assert len(calls) == 1
    assert [ast.unparse(argument) for argument in calls[0].args] == ["bpy.types", "bpy.app.build_hash"]
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and
                   ((isinstance(node, ast.Import) and any(alias.name == "bpy" for alias in node.names))
                    or (isinstance(node, ast.ImportFrom) and node.module == "bpy"))
                   for node in tree.body)


def test_current_pixels_census_requires_explicit_opt_in_before_owned_profile(monkeypatch):
    script = importlib.import_module("scripts.blender_current_pixels_lifecycle_smoke")
    monkeypatch.setattr(script, "owned_profile", lambda *_args: pytest.fail("Profile checked without opt-in"))
    with pytest.raises(SystemExit):
        script.main(["--bridge-report", "/unused/current-pixels-census.json"])


def test_current_pixels_modes_are_exclusive_before_profile_or_native_setup(monkeypatch):
    script = importlib.import_module("scripts.blender_current_pixels_lifecycle_smoke")
    monkeypatch.setattr(script, "owned_profile", lambda *_args: pytest.fail("Profile checked before mode parsing"))
    with pytest.raises(SystemExit):
        script.main(["--bridge-census-only", "--bridge-source-graph", "--bridge-report", "/unused/current-pixels-source-graph.json"])


def test_source_graph_mode_preserves_inert_import_and_explicit_lifecycle_limits():
    script = importlib.import_module("scripts.blender_current_pixels_lifecycle_smoke")
    tree = ast.parse(Path(script.__file__).read_text())
    assert script.GRAPH_PROFILE == "CURRENT_PIXELS_NATIVE_SOURCE_GRAPH_V1"
    assert len(script.GRAPH_ASSERTIONS) == 18
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and
                   ((isinstance(node, ast.Import) and any(alias.name == "bpy" for alias in node.names))
                    or (isinstance(node, ast.ImportFrom) and node.module == "bpy")) for node in tree.body)
    assert not any(isinstance(node, ast.Assign) and any(isinstance(target, ast.Attribute)
        and target.attr == "_source" for target in node.targets) for node in ast.walk(tree))
    source = ast.get_source_segment(Path(script.__file__).read_text(), next(node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "native_graph_probe"))
    assert '"current_pixels_origin_qualified": False' in source and '"public_tool_acceptance": False' in source


@pytest.mark.parametrize("source_drift", [False, True])
def test_source_graph_main_dispatch_is_explicit_and_keeps_source_receipt_binding(monkeypatch, tmp_path, capsys, source_drift):
    """Dispatch model only; the native graph probe is not executed here."""
    script = importlib.import_module("scripts.blender_current_pixels_lifecycle_smoke")
    source = tmp_path / "source"
    for name in ("scripts/blender_current_pixels_lifecycle_smoke.py", "scripts/run_blender_checks.py",
                 "addon/blender_codex_bridge/current_pixels_graph.py", "addon/blender_codex_bridge/current_pixels_source.py"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# explicit source graph dispatch model\n")
    monkeypatch.setattr(script, "ROOT", source)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", ["blender", "--background", "--factory-startup", "--disable-autoexec"])
    events = []
    monkeypatch.setattr(script, "owned_profile", lambda _path: events.append("owned") or "a" * 32)
    bpy = ModuleType("bpy")
    bpy.app = NS(background=True, version=(5, 2, 2), version_string="5.2.2", build_hash=b"d13f752e3b9c", build_type=b"Release")
    graph = ModuleType("blender_codex_bridge.current_pixels_graph")
    graph.__file__ = str(source / "addon/blender_codex_bridge/current_pixels_graph.py")
    graph.catalog_census = lambda *_args: pytest.fail("Source graph dispatch selected census")
    package = ModuleType("blender_codex_bridge")
    package.current_pixels_graph = graph
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setitem(sys.modules, package.__name__, package)
    monkeypatch.setitem(sys.modules, graph.__name__, graph)
    def probe(actual_bpy, actual_graph, fingerprints, parent):
        assert actual_bpy is bpy and actual_graph is graph and parent == tmp_path
        assert fingerprints == script.source_fingerprints()
        events.append("native_probe_dispatch_model")
        if source_drift:
            Path(graph.__file__).write_text("# changed during modeled probe\n")
        return {"assertions": {"dispatch_model_only": True}}
    monkeypatch.setattr(script, "native_graph_probe", probe)
    report = tmp_path / script.GRAPH_REPORT_NAME
    args = ["--bridge-source-graph", "--bridge-report", str(report)]
    if source_drift:
        with pytest.raises(AssertionError, match="Source changed"):
            script.main(args)
        assert not report.exists()
    else:
        script.main(args)
        full = json.loads(report.read_bytes())
        compact = json.loads(capsys.readouterr().out.removeprefix(script.GRAPH_MARKER))
        assert compact["profile"] == full["profile"] == script.GRAPH_PROFILE
        assert compact["current_pixels_origin_qualified"] is full["lifecycle_functional_acceptance"] is False
        assert compact["full_receipt"]["sha256"] == script.hashlib.sha256(report.read_bytes()).hexdigest()
    assert events == ["owned", "native_probe_dispatch_model"]


def test_current_pixels_census_receipt_is_bounded_create_only_and_reopened(tmp_path):
    script = importlib.import_module("scripts.blender_current_pixels_lifecycle_smoke")
    path = tmp_path / script.REPORT_NAME
    proof = {"profile": script.PROFILE, "lifecycle_functional_acceptance": False,
             "missing_class": {"present": False}, "missing_descriptor": {"present": False}}
    binding = script.write_receipt(path, proof)
    assert binding == {"path": str(path), "bytes": path.stat().st_size,
                       "sha256": script.hashlib.sha256(path.read_bytes()).hexdigest()}
    assert json.loads(path.read_bytes()) == proof
    with pytest.raises(FileExistsError):
        script.write_receipt(path, proof)
    oversized = tmp_path / "oversized.json"
    with pytest.raises(AssertionError, match="complete report bound"):
        script.write_receipt(oversized, {"too_large": "x" * script.MAX_REPORT})
    assert not oversized.exists()


@pytest.mark.parametrize("fault", [None, "unqualified_build", "interactive", "source_change"])
def test_current_pixels_census_composes_only_attested_class_metadata(monkeypatch, tmp_path, capsys, fault):
    """Composition model; it provides no native RNA or lifecycle acceptance."""
    script = importlib.import_module("scripts.blender_current_pixels_lifecycle_smoke")
    source = tmp_path / "source"
    for name in ("scripts/blender_current_pixels_lifecycle_smoke.py", "scripts/run_blender_checks.py",
                 "addon/blender_codex_bridge/current_pixels_graph.py"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# census composition model\n")
    monkeypatch.setattr(script, "ROOT", source)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", ["blender", "--background", "--factory-startup", "--disable-autoexec"])
    events = []
    monkeypatch.setattr(script, "owned_profile", lambda _path: events.append("owned_profile") or "a" * 32)
    metadata = NS()

    class MetadataOnlyBlender(ModuleType):
        def __getattr__(self, name):
            pytest.fail(f"Census read non-metadata Blender field {name}")

    bpy = MetadataOnlyBlender("bpy")
    bpy.types = metadata
    bpy.app = NS(background=fault != "interactive", version=(5, 2, 2), version_string="5.2.2",
                 build_hash=b"unqualified" if fault == "unqualified_build" else b"d13f752e3b9c", build_type=b"Release")
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    graph = ModuleType("blender_codex_bridge.current_pixels_graph")
    graph.__file__ = str(source / "addon/blender_codex_bridge/current_pixels_graph.py")
    graph.CENSUS_TYPES = tuple(f"ModelClass{index}" for index in range(57))

    def catalog_census(types, build_hash):
        assert types is metadata and build_hash == b"d13f752e3b9c"
        events.append("class_catalog")
        if fault == "source_change":
            Path(graph.__file__).write_text("# changed during census\n")
        return {"schema": "current_pixels_complete_class_census_v1", "build_hash": "d13f752e3b9c",
                "classes": {name: {"present": False} for name in graph.CENSUS_TYPES}}

    graph.catalog_census = catalog_census
    package = ModuleType("blender_codex_bridge")
    package.current_pixels_graph = graph
    monkeypatch.setitem(sys.modules, "blender_codex_bridge", package)
    monkeypatch.setitem(sys.modules, "blender_codex_bridge.current_pixels_graph", graph)
    report = tmp_path / script.REPORT_NAME
    arguments = ["--bridge-census-only", "--bridge-report", str(report)]
    if fault is not None:
        with pytest.raises(AssertionError):
            script.main(arguments)
        assert not report.exists()
        assert events == (["owned_profile", "class_catalog"] if fault == "source_change" else ["owned_profile"])
    else:
        script.main(arguments)
        assert events == ["owned_profile", "class_catalog"]
        proof = json.loads(report.read_bytes())
        assert proof["lifecycle_functional_acceptance"] is proof["windows_qualified"] is False
        assert all(row == {"present": False} for row in proof["catalog"]["classes"].values())
        assert proof["source_fingerprints"] == script.source_fingerprints()
        compact = json.loads(capsys.readouterr().out.removeprefix(script.MARKER))
        assert compact["full_receipt"]["sha256"] == script.hashlib.sha256(report.read_bytes()).hexdigest()


@pytest.mark.parametrize("fault", ["relative", "wrong_name", "public_parent", "token", "pythonpath", "working"])
def test_current_pixels_census_rejects_unowned_profile_before_catalog(monkeypatch, tmp_path, fault):
    script = importlib.import_module("scripts.blender_current_pixels_lifecycle_smoke")
    monkeypatch.setattr(script.sys, "platform", "linux")
    temporary = tmp_path / "private"
    temporary.mkdir(mode=0o700)
    for key in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.setenv(key, str(temporary))
    for key in ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        directory = temporary / ("worker-profile-" + key.lower())
        directory.mkdir(mode=0o700)
        monkeypatch.setenv(key, str(directory))
    working = temporary / "working"
    working.mkdir(mode=0o700)
    monkeypatch.chdir(working)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.delenv("PYTHONHOME", raising=False)
    monkeypatch.setenv("BRIDGE_TEST_PROCESS_TOKEN", "a" * 32)
    report = temporary / script.REPORT_NAME
    assert script.owned_profile(report) == "a" * 32
    if fault == "relative":
        report = Path(script.REPORT_NAME)
    elif fault == "wrong_name":
        report = temporary / "different.json"
    elif fault == "public_parent":
        temporary.chmod(0o755)
    elif fault == "token":
        monkeypatch.setenv("BRIDGE_TEST_PROCESS_TOKEN", "not a runner token")
    elif fault == "pythonpath":
        monkeypatch.setenv("PYTHONPATH", "/unrelated")
    elif fault == "working":
        monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError):
        script.owned_profile(report)


def test_registered_geometry_fixture_materializes_only_before_pending_state():
    tree = ast.parse((ROOT / "scripts" / "blender_geometry_preview_smoke.py").read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    updates = sorted(
        node.lineno for node in calls
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "layer" and node.func.attr == "update"
    )
    plan_setup = min(
        node.lineno for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "dispatch"
        and node.args and isinstance(node.args[0], ast.Constant)
        and node.args[0].value in {"task.plan.set", "task.plan.enforce"}
    )
    action_setup = next(
        node.lineno for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "new"
        and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "actions"
    )
    pending_base = next(
        node.lineno for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "hide_set"
    )
    assert updates and updates[0] < action_setup < plan_setup
    assert all(line < pending_base for line in updates)


def test_public_native_save_fixture_has_no_child_launcher_or_held_context_paths():
    source = (ROOT / "scripts" / "blender_native_save_smoke.py").read_text()
    assert "subprocess" not in source and "Popen" not in source
    assert "frame_set" not in source and "keyframe_insert" not in source and "libraries.write" not in source


def test_native_save_setup_inventory_records_all_families_and_exact_missing_fields(monkeypatch):
    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")

    class Image:
        bl_rna = NS(identifier="Image", properties={name: object() for name in (
            "name", "users", "use_fake_user", "source", "type", "packed_file", "has_data", "is_dirty")})
        name, users, use_fake_user = "Viewer diagnostic", 0, False
        source, type, packed_file, has_data, is_dirty = "VIEWER", "COMPOSITING", None, False, False

        def as_pointer(self):
            return 42

        @property
        def pixels(self):
            pytest.fail("Setup diagnostics must not prime or copy pixel buffers")

    data = NS(bl_rna=NS(properties=[NS(identifier=name, type="COLLECTION") for name in (
        "images", "palettes", "unreviewed_family")]), images=[Image()], palettes=[], unreviewed_family=[])
    result = script.data_inventory(data)
    assert set(result) == {"images", "palettes", "unreviewed_family"}
    image = result["images"]["ids"][0]
    assert result["images"]["count"] == 1 and result["palettes"]["count"] == 0
    assert "is_runtime_data" in image["absent_descriptors"] and "is_runtime_data" not in image["fields"]
    assert image["image"]["source"] == "VIEWER" and image["image"]["packed_file"] is None
    assert "filepath" in image["image_absent_descriptors"]


def test_native_save_factory_cleanup_is_attested_named_and_before_artist_asset(monkeypatch):
    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")
    removed = []

    class Owners(list):
        def remove(self, owner, *, do_unlink):
            assert do_unlink is True
            removed.append(owner.name)
            super().remove(owner)

    def owner(name, **extra):
        fields = dict(name=name, library=None, override_library=None, **extra)
        return NS(**fields, as_pointer=lambda: 7,
                  bl_rna=NS(identifier="FixtureID", properties={key: object() for key in fields}))

    data = NS(**{family: Owners([owner(family)]) for family in script.FACTORY_FAMILIES},
              images=Owners([owner("viewer", source="VIEWER"), owner("authored", source="FILE")]),
              scenes=[owner("scene")], screens=[owner("screen")], window_managers=[owner("wm")])
    with pytest.raises(AssertionError, match="factory"):
        script.clean_factory_data(data, attested=False)
    assert not removed
    script.clean_factory_data(data, attested=True)
    assert removed == [*script.FACTORY_FAMILIES, "viewer"]
    assert [image.name for image in data.images] == ["authored"]
    assert [data.scenes[0].name, data.screens[0].name, data.window_managers[0].name] == ["scene", "screen", "wm"]
    tree = ast.parse(Path(script.__file__).read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    cleanup = next(node.lineno for node in calls if node.func.id == "clean_factory_data")
    create = next(node.lineno for node in calls if node.func.id == "fixture")
    assert cleanup < create
    remainder = script.unsupported_remainders({"palettes": {"count": 1}, "unknown": {"count": 2},
                                              "images": {"count": 1}, "scenes": {"count": 1}}, ("scenes", "images"), ())
    assert set(remainder) == {"palettes", "unknown", "images"}


def test_native_save_fixture_persists_structured_error_context_before_expected_code_assertion(
    addon_package, monkeypatch, tmp_path
):
    import json

    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")
    errors = importlib.import_module(f"{addon_package}.errors")
    error = errors.BridgeError("NOT_IMPLEMENTED", "Narrow profile refusal", {"reason": "UNSUPPORTED_ID_FAMILY:palettes"})
    report, proof = tmp_path / "failure.json", {"stage": "dispatch:project.native_save_preview"}
    script.persist_failure(proof, report, error, bridge_error_type=errors.BridgeError)
    row = json.loads(report.read_text())["failures"][0]
    assert row["stage"] == proof["stage"] and row["bridge_error"] == error.to_dict()
    source = Path(script.__file__).read_text()
    assert source.index("persist_failure(proof, report, error") < source.index("assert error.code == code")


def test_native_save_class_census_is_flushed_before_asset_or_profile_and_excludes_value_reflection():
    source = (ROOT / "scripts" / "blender_native_save_smoke.py").read_text()
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    census = next(node.lineno for node in calls if node.func.id == "schema_census")
    asset = next(node.lineno for node in calls if node.func.id == "fixture")
    assert census < asset
    census_text = source[source.index('proof["schema_census"] = schema_census'):source.index('proof["stage"] = "artist_asset_creation"')]
    assert census_text.index("report.write_text") < census_text.index('assert not proof["schema_census"]["mismatches"]')
    profile = ast.parse((ROOT / "addon/blender_codex_bridge/native_save_profile.py").read_text())
    helpers = [node for node in profile.body if isinstance(node, ast.FunctionDef)
               and node.name in {"schema_census", "descriptor_metadata"}]
    assert len(helpers) == 2
    assert not {node.attr for helper in helpers for node in ast.walk(helper) if isinstance(node, ast.Attribute)} & {
        "fixed_type", "default", "default_array", "enum_items", "enum_items_static", "pixels", "node_tree"}


@pytest.mark.parametrize("rigid_present,sequencer_present", [(False, False), (True, False), (False, True), (True, True)])
def test_native_save_scene_cache_guard_distinguishes_absence_from_allocated_empty_container(
    addon_package, rigid_present, sequencer_present
):
    from test_native_save import _profile_data

    profile = importlib.import_module(f"{addon_package}.native_save_profile")

    class Pointee:
        def __getattribute__(self, _name):
            pytest.fail("The production guard must not inspect or ensure an unsupported cache")

        def __bool__(self):
            pytest.fail("Allocated-empty cache must not be treated as a false/absent pointer")

    data = _profile_data(profile)
    data.scenes[0].rigidbody_world = Pointee() if rigid_present else None
    data.scenes[0].sequence_editor = Pointee() if sequencer_present else None
    if rigid_present or sequencer_present:
        with pytest.raises(profile.ProfileRefused, match=r"^SCENE_CACHE_OR_SEQUENCER_UNSUPPORTED$"):
            profile.capture(data)
    else:
        assert profile.capture(data).raw


def _owned_scene_diagnostic_model(addon_package, monkeypatch, *, editor_present=True, nonempty=False,
                                  unknown=False, rigid=False):
    from test_native_save import _profile_data

    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    data = _profile_data(profile)
    scene = data.scenes[0]

    class Properties(dict):
        def __iter__(self):
            return iter(self.values())

    class Editor:
        bl_rna = NS(identifier="SequenceEditor", properties=Properties({
            **{name: NS(identifier=name, type="COLLECTION", is_runtime=False)
               for name in ("sequences", "sequences_all", "meta_stack", "channels")},
            "active_strip": NS(identifier="active_strip", type="POINTER", is_runtime=False)}))
        sequences = [object()] if nonempty else []
        sequences_all, meta_stack, channels, active_strip = [], [], [], None

        def as_pointer(self):
            return 201

        @property
        def future_container(self):
            pytest.fail("Unknown VSE collection must not be traversed")

    editor = Editor()
    if unknown:
        editor.bl_rna = NS(identifier="SequenceEditor", properties=Properties({
            **editor.bl_rna.properties,
            "future_container": NS(identifier="future_container", type="COLLECTION", is_runtime=False)}))
    scene.sequence_editor = editor if editor_present else None
    scene.rigidbody_world = NS(bl_rna=NS(identifier="RigidBodyWorld"), as_pointer=lambda: 202) if rigid else None
    calls = []

    def clear():
        calls.append("clear")
        scene.sequence_editor = None

    scene.sequence_editor_clear = clear
    scene.sequence_editor_create = lambda: pytest.fail("Diagnostic must not ensure a sequence editor")
    scene.bl_rna.functions = {"sequence_editor_clear": NS(identifier="sequence_editor_clear")}
    return script, data, calls


@pytest.mark.parametrize("rigid,editor", [(False, False), (True, False), (False, True), (True, True)])
def test_owned_scene_diagnostics_record_both_pointer_states_without_ensuring(addon_package, monkeypatch, rigid, editor):
    script, data, calls = _owned_scene_diagnostic_model(addon_package, monkeypatch, rigid=rigid, editor_present=editor)
    row = script.scene_value_snapshot(data)["scenes"][0]
    assert row["rigidbody_world"]["present"] is rigid and row["sequence_editor"]["present"] is editor
    if editor:
        assert row["sequence_editor"]["empty_candidate"] is True
        assert row["sequence_editor"]["collections"]["sequences"]["count"] == 0
    assert not calls


@pytest.mark.parametrize("fault", ["nonempty", "unknown", "rigid", "unattested", "incomplete", "other_violation", "stale"])
def test_owned_sequence_cleanup_refuses_nonempty_unknown_cache_or_unqualified_preflight(
    addon_package, monkeypatch, fault
):
    script, data, calls = _owned_scene_diagnostic_model(
        addon_package, monkeypatch, nonempty=fault == "nonempty", unknown=fault == "unknown", rigid=fault == "rigid")
    before = data.scenes[0].sequence_editor
    preflight = script.value_preflight(data)
    if fault == "incomplete":
        preflight["complete"] = False
    elif fault == "other_violation":
        preflight["violations"].append({"code": "OBJECT_PROFILE_UNSUPPORTED"})
    elif fault == "stale":
        preflight["scene_values"]["scenes"][0]["sequence_editor"]["pointer"] += 1
    with pytest.raises(AssertionError):
        script.clear_owned_empty_sequence_editors(data, attested=fault != "unattested", preflight=preflight)
    assert not calls and data.scenes[0].sequence_editor is before


def test_owned_sequence_cleanup_only_clears_empty_attested_editor_after_complete_batch(addon_package, monkeypatch):
    script, data, calls = _owned_scene_diagnostic_model(addon_package, monkeypatch)
    preflight = script.value_preflight(data)
    assert preflight["complete"] and {row["code"] for row in preflight["violations"]} == {"SCENE_SEQUENCE_EDITOR_PRESENT"}
    assert set(preflight["observations"]) == {
        "scenes", "collections", "objects", "meshes", "armatures", "actions", "materials", "worlds", "images", "cameras", "lights"}
    result = script.clear_owned_empty_sequence_editors(data, attested=True, preflight=preflight)
    assert calls == ["clear"] and data.scenes[0].sequence_editor is None
    assert result["cleared"][0]["before_pointer"] == 201
    assert result["after"]["scenes"][0]["sequence_editor"]["present"] is False
    assert script.value_preflight(data)["violations"] == []


def test_owned_value_preflight_reports_multiple_categories_without_decoding_invalid_images(addon_package, monkeypatch):
    from test_native_save import _profile_id

    script, data, calls = _owned_scene_diagnostic_model(addon_package, monkeypatch)
    data.meshes = [_profile_id("Mesh", "Editing mesh", is_editmode=True, shape_keys=None,
                               vertices=[], loops=[], edges=[], polygons=[], uv_layers=[], materials=[])]

    class NoDecode:
        def __len__(self):
            pytest.fail("Unsupported image must not trigger a source decode or pixel read")

    data.images = [_profile_id("Image", "Dirty image", source="GENERATED", is_dirty=True, has_data=False,
                              packed_file=None, channels=4, size=(2, 2), pixels=NoDecode(), filepath="",
                              colorspace_settings=NS(name="sRGB"), alpha_mode="STRAIGHT")]
    result = script.value_preflight(data)
    codes = {row["code"] for row in result["violations"]}
    assert result["complete"] and {
        "SCENE_SEQUENCE_EDITOR_PRESENT", "MESH_EDIT_OR_SHAPE_KEYS_UNSUPPORTED",
        "PACKED_CLEAN_LOADED_FILE_IMAGE_REQUIRED"} <= codes
    with pytest.raises(AssertionError, match="Other profile violations"):
        script.clear_owned_empty_sequence_editors(data, attested=True, preflight=result)
    assert not calls and data.scenes[0].sequence_editor is not None


def test_owned_value_diagnostics_finish_before_pending_raw_baseline_and_flush_before_clear():
    source = (ROOT / "scripts/blender_native_save_smoke.py").read_text()
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    baseline = next(node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                            and target.slice.value == "raw_before_entry" for target in node.targets))
    assert all(node.lineno < baseline for node in calls if node.func.id in {"scene_value_snapshot", "value_preflight"})
    preclear = source[source.index('before_clear = value_preflight'):source.index('proof["value_preflights"]["after_owned_clear"] =')]
    assert preclear.index("report.write_text") < preclear.index("clear_owned_empty_sequence_editors")
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name in {"scene_value_snapshot", "value_preflight"}]
    assert len(helpers) == 2
    forbidden = {"context", "evaluated_get", "evaluated_depsgraph_get", "sequence_editor_create"}
    assert not {node.attr for helper in helpers for node in ast.walk(helper) if isinstance(node, ast.Attribute)} & forbidden
    updates = [node for helper in helpers for node in ast.walk(helper) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == "update"]
    assert all(isinstance(node.func.value, ast.Name) and node.func.value.id == "row" for node in updates)


def _factory_channel_model(monkeypatch, build_hash, *, poison_values=False):
    """Exact public fields from both pinned rna_sequencer.cc definitions only."""
    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")

    class Properties(dict):
        def __iter__(self):
            return iter(self.values())

    def descriptor(name, kind, readonly):
        return NS(identifier=name, type=kind, is_runtime=False, is_readonly=readonly,
                  array_length=0, bl_rna=NS(properties={"array_length": object()} if kind in {"INT", "BOOLEAN"} else {}))

    fields = {"rna_type": descriptor("rna_type", "POINTER", True),
              "name": descriptor("name", "STRING", False),
              "lock": descriptor("lock", "BOOLEAN", False), "mute": descriptor("mute", "BOOLEAN", False)}
    if build_hash == "d13f752e3b9c":
        fields["number"] = descriptor("number", "INT", True)

    class Channel:
        def __init__(self, position):
            self.position = position
            self.bl_rna = NS(identifier="SequenceTimelineChannel", properties=Properties(fields), functions=[])
            self.values = {"name": f"Channel {position}", "lock": False, "mute": False, "number": position}

        def _value(self, name):
            if poison_values:
                pytest.fail("All channel metadata must pass before the first public value read")
            return self.values[name]

        def as_pointer(self):
            return 1000 + self.position

        @property
        def name(self):
            return self._value("name")

        @property
        def lock(self):
            return self._value("lock")

        @property
        def mute(self):
            return self._value("mute")

        @property
        def number(self):
            assert build_hash == "d13f752e3b9c", "Blender4.5 has no public channel-number descriptor"
            return self._value("number")

        @property
        def index(self):
            pytest.fail("Never read or infer hidden channel index storage")

        @property
        def rna_type(self):
            pytest.fail("Channel schema screening must not follow a metadata pointee")

    channels = [Channel(position) for position in range(129)]
    editor = NS(channels=channels, bl_rna=NS(identifier="SequenceEditor", properties=Properties({
        "channels": descriptor("channels", "COLLECTION", True)})))
    return script, editor


@pytest.mark.parametrize("build_hash", ["62c1db4208e8", "d13f752e3b9c"])
def test_owned_default_channel_snapshot_uses_complete_ordered_public_state(monkeypatch, build_hash):
    script, editor = _factory_channel_model(monkeypatch, build_hash)
    result = script.default_channel_snapshot(editor, build_hash=build_hash)
    assert result["default_match"] and len(result["rows"]) == result["count"] == 129
    assert result["index_descriptor_present"] is False
    assert result["number_descriptor_present"] is (build_hash == "d13f752e3b9c")
    assert [row["position"] for row in result["rows"]] == list(range(129))
    assert [row["name"] for row in result["rows"]] == [f"Channel {index}" for index in range(129)]
    assert all(row["lock"] is False and row["mute"] is False for row in result["rows"])
    if build_hash == "d13f752e3b9c":
        assert [row["number"] for row in result["rows"]] == list(range(129))
    else:
        assert all("number" not in row for row in result["rows"])
    assert len(result["fingerprint"]) == 64 and not result["errors"]


@pytest.mark.parametrize("fault", ["name", "localized_name", "lock", "mute", "falsey_non_bool", "order", "number"])
def test_owned_default_channel_snapshot_rejects_any_nondefault_public_field(monkeypatch, fault):
    script, editor = _factory_channel_model(monkeypatch, "d13f752e3b9c")
    if fault == "order":
        editor.channels[127], editor.channels[128] = editor.channels[128], editor.channels[127]
    else:
        field, value = {"name": ("name", "Authored channel"), "localized_name": ("name", "Kanal 128"),
                        "lock": ("lock", True), "mute": ("mute", True),
                        "falsey_non_bool": ("mute", 0), "number": ("number", 127)}[fault]
        editor.channels[-1].values[field] = value
    result = script.default_channel_snapshot(editor, build_hash="d13f752e3b9c")
    assert not result["default_match"] and result["errors"]


@pytest.mark.parametrize("fault", ["class", "extra", "runtime", "wrong_type", "readonly_number", "missing_number", "hidden_index", "function", "array_shape"])
def test_owned_default_channel_snapshot_screens_all_metadata_before_any_values(monkeypatch, fault):
    script, editor = _factory_channel_model(monkeypatch, "d13f752e3b9c", poison_values=True)
    channel = editor.channels[-1]
    if fault == "class":
        channel.bl_rna.identifier = "UnreviewedChannel"
    elif fault == "function":
        channel.bl_rna.functions = [NS(identifier="unreviewed_function")]
    elif fault == "missing_number":
        channel.bl_rna.properties.pop("number")
    elif fault == "array_shape":
        channel.bl_rna.properties["lock"].array_length = 1
    elif fault in {"extra", "hidden_index"}:
        field = "custom_state" if fault == "extra" else "index"
        channel.bl_rna.properties[field] = NS(identifier=field, type="INT", is_runtime=False, is_readonly=True)
    elif fault == "runtime":
        channel.bl_rna.properties["name"] = NS(identifier="name", type="STRING", is_runtime=True, is_readonly=False)
    elif fault == "wrong_type":
        channel.bl_rna.properties["lock"] = NS(identifier="lock", type="INT", is_runtime=False, is_readonly=False)
    else:
        channel.bl_rna.properties["number"] = NS(identifier="number", type="INT", is_runtime=False, is_readonly=False)
    result = script.default_channel_snapshot(editor, build_hash="d13f752e3b9c")
    assert not result["default_match"] and result["errors"]
    assert result["index_descriptor_present"] is None and result["number_descriptor_present"] is None


@pytest.mark.parametrize("count", [0, 128, 130, 1000000])
def test_owned_default_channel_snapshot_refuses_wrong_counts_before_iteration(monkeypatch, count):
    script, editor = _factory_channel_model(monkeypatch, "62c1db4208e8")

    class CountOnly:
        def __len__(self):
            return count

        def __iter__(self):
            pytest.fail("Noncanonical channel count must refuse before traversal")

    editor.channels = CountOnly()
    result = script.default_channel_snapshot(editor, build_hash="62c1db4208e8")
    assert not result["default_match"] and result["errors"]


@pytest.mark.parametrize("actual_count", [128, 130])
def test_owned_default_channel_snapshot_bounds_partial_or_growing_iteration(monkeypatch, actual_count):
    script, editor = _factory_channel_model(monkeypatch, "62c1db4208e8")
    original = list(editor.channels)

    class Unstable:
        def __len__(self):
            return 129

        def __iter__(self):
            yield from original[:actual_count]
            if actual_count > 129:
                yield original[-1]
                pytest.fail("Traversal must stop immediately at the first excess channel")

    editor.channels = Unstable()
    result = script.default_channel_snapshot(editor, build_hash="62c1db4208e8")
    assert not result["default_match"] and result["errors"]


@pytest.mark.parametrize("build_hash", ["62c1db4208e8", "d13f752e3b9c"])
def test_owned_clear_accepts_only_complete_canonical_factory_channels(addon_package, monkeypatch, build_hash):
    script, data, calls = _owned_scene_diagnostic_model(addon_package, monkeypatch)
    _script, channels = _factory_channel_model(monkeypatch, build_hash)
    data.scenes[0].sequence_editor.channels = channels.channels
    preflight = script.value_preflight(data, build_hash=build_hash)
    proof = preflight["scene_values"]["scenes"][0]["sequence_editor"]["channel_defaults"]
    assert proof["default_match"] and {row["code"] for row in preflight["violations"]} == {"SCENE_SEQUENCE_EDITOR_PRESENT"}
    result = script.clear_owned_empty_sequence_editors(data, attested=True, preflight=preflight, build_hash=build_hash)
    assert calls == ["clear"] and data.scenes[0].sequence_editor is None
    assert result["cleared"][0]["owned_default_channel_records_deleted"] == 129
    assert result["cleared"][0]["channel_fingerprint"] == proof["fingerprint"]


@pytest.mark.parametrize("fault", ["nondefault", "nonempty", "unknown", "rigid", "missing_active", "active", "stale_channel", "unattested"])
def test_owned_clear_retains_every_noncanonical_or_unqualified_channel_layout(addon_package, monkeypatch, fault):
    build_hash = "d13f752e3b9c"
    script, data, calls = _owned_scene_diagnostic_model(
        addon_package, monkeypatch, nonempty=fault == "nonempty", unknown=fault == "unknown", rigid=fault == "rigid")
    _script, channels = _factory_channel_model(monkeypatch, build_hash)
    editor = data.scenes[0].sequence_editor
    editor.channels = channels.channels
    if fault == "nondefault":
        editor.channels[-1].values["lock"] = True
    elif fault == "missing_active":
        editor.bl_rna.properties.pop("active_strip")
    elif fault == "active":
        editor.active_strip = NS(bl_rna=NS(identifier="Strip"), as_pointer=lambda: 999)
    preflight = script.value_preflight(data, build_hash=build_hash)
    if fault == "stale_channel":
        editor.channels[-1].values["name"] = "Manual edit after preflight"
    with pytest.raises(AssertionError):
        script.clear_owned_empty_sequence_editors(data, attested=fault != "unattested", preflight=preflight, build_hash=build_hash)
    assert not calls and data.scenes[0].sequence_editor is editor


def test_owned_channel_unknown_build_or_unexposed_number_never_adopts_a_layout(monkeypatch):
    script, editor = _factory_channel_model(monkeypatch, "62c1db4208e8", poison_values=True)
    result = script.default_channel_snapshot(editor, build_hash="unqualified")
    assert not result["default_match"] and result["errors"]
    assert result["index_descriptor_present"] is None and result["number_descriptor_present"] is None
    editor.channels[-1].bl_rna.properties["number"] = NS(identifier="number", type="INT", is_runtime=False, is_readonly=True)
    result = script.default_channel_snapshot(editor, build_hash="62c1db4208e8")
    assert not result["default_match"] and result["errors"]


def test_history_native_fixture_is_opt_in_interactive_and_autoexec_disabled(monkeypatch, tmp_path):
    import json
    import subprocess

    runner = importlib.import_module("scripts.run_blender_checks")
    case = "executor_history_containment"
    assert case in runner.OPT_IN_CASES & runner.INTERACTIVE_CASES
    monkeypatch.setattr(runner.sys, "platform", "linux")

    def run(command, **kwargs):
        assert "--background" not in command and "--disable-autoexec" in command
        assert command.index("--factory-startup") < command.index("--python")
        assert command[command.index("--python")+1].endswith("blender_executor_history_containment_smoke.py")
        kwargs["stdout"].write((runner.CASES[case][1]+json.dumps({"blender_version": "4.5.14"})).encode())
        return NS(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert runner.run_case(Path("blender"), case, tmp_path, 20)["status"] == "passed"


def test_history_native_observer_copies_python_call_facts_without_native_or_history_work():
    script = importlib.import_module("scripts.blender_executor_history_containment_smoke")
    fixture = script.Fixture.__new__(script.Fixture)
    request_code, native_code = object(), object()
    fixture.code_names = {request_code: "request", native_code: "_snapshot"}
    fixture.rows, fixture.outside = {}, {}
    fixture.current, fixture.profile_failures = None, 0
    request = NS(id="observed", method="fixture.history.write")
    frame = NS(f_code=request_code, f_locals={"request": request})
    fixture.observe_profile(frame, "call", None)
    fixture.observe_profile(NS(f_code=native_code), "call", None)
    fixture.observe_profile(frame, "return", None)
    assert fixture.rows["observed"]["calls"] == {"_snapshot": 1}
    assert fixture.current is None and fixture.profile_failures == 0
    fixture.observe_profile(NS(f_code=object()), "call", None)
    assert fixture.outside == {} and fixture.profile_failures == 0


@pytest.mark.parametrize("name,expected", [
    ("blender_rigid_timer_probe_smoke.py", [("heartbeat", {"first_interval": .01}), ("tick", {"first_interval": 1.})]),
    ("blender_scene_job_kernel_smoke.py", [("setup", {"first_interval": 1.})]),
    ("blender_rigid_evaluation_jobs_smoke.py", [("setup", {"first_interval": 1.})]),
])
def test_explicit_fixture_entrypoint_schedules_only_its_own_timers(fixture_imports, name, expected):
    runpy.run_path(str(ROOT / "scripts" / name), run_name="__main__")
    assert fixture_imports.timers == expected and fixture_imports.events == []


@pytest.mark.parametrize("script", ["blender_artist_quaternion_storage_smoke.py", "blender_artist_quaternion_smoke.py",
                                  "blender_uv_edit_storage_smoke.py", "blender_uv_edit_boundary_probe.py", "blender_uv_edit_guard_smoke.py"])
def test_owned_background_entry_never_acquires_process_exit(fixture_imports, monkeypatch, script):
    def forbidden_exit(_status):
        pytest.fail("An unowned invocation must not terminate its Blender process")

    monkeypatch.setattr(os, "_exit", forbidden_exit)
    with pytest.raises(AssertionError, match="Use the isolated background runner"):
        runpy.run_path(str(ROOT / "scripts" / script), run_name="__main__")
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_isolated_preview_entry_refuses_unowned_process_before_exit_authority(fixture_imports, monkeypatch):
    monkeypatch.setattr(os, "_exit", lambda _status: pytest.fail("Unowned preview acquired process-exit authority"))
    monkeypatch.setattr(sys, "argv", ["blender"])
    with pytest.raises(AssertionError, match="Use the phased isolated runner"):
        runpy.run_path(str(ROOT / "scripts/blender_isolated_asset_preview_probe_smoke.py"), run_name="__main__")
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_large_surface_entry_refuses_unowned_ui_before_exit_authority(fixture_imports, monkeypatch):
    monkeypatch.setattr(os, "_exit", lambda _status: pytest.fail("Unowned entry acquired process-exit authority"))
    with pytest.raises(AssertionError, match="Use the isolated private interactive runner"):
        runpy.run_path(str(ROOT / "scripts/blender_large_surface_paint_smoke.py"), run_name="__main__")
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_animation_intent_entry_refuses_unowned_ui_before_exit_authority(fixture_imports, monkeypatch):
    monkeypatch.setattr(os, "_exit", lambda _status: pytest.fail("Unowned curve fixture acquired process-exit authority"))
    with pytest.raises(AssertionError, match="Use the isolated private interactive runner"):
        runpy.run_path(str(ROOT / "scripts/blender_animation_intent_smoke.py"), run_name="__main__")
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_animation_intent_direct_main_rechecks_ownership_before_scheduling_or_exit(fixture_imports, monkeypatch):
    script = importlib.import_module("scripts.blender_animation_intent_smoke")
    monkeypatch.setattr(os, "_exit", lambda _status: pytest.fail("Direct unowned main acquired process-exit authority"))
    with pytest.raises(AssertionError, match="Use the isolated private interactive runner"):
        script.main()
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("fault", [None, "proof", "stdout", "stderr"])
def test_animation_intent_owned_finish_always_exits_after_io_failure(fixture_imports, monkeypatch, fault):
    script = importlib.import_module("scripts.blender_animation_intent_smoke")
    sidebar = importlib.import_module("scripts.blender_artist_sidebar_smoke")
    observed = []
    class OwnedExit(BaseException):
        pass
    def exit_owned(status):
        observed.append(status)
        raise OwnedExit
    def stream(name):
        def flush():
            if fault == name:
                raise OSError("Private controlled stdio flush failure")
        return NS(write=lambda *_: None, flush=flush)
    fixture = script.Fixture.__new__(script.Fixture)
    fixture.data = {"calls": [], "source_sha256": {}}
    fixture.path = NS(read_bytes=lambda: b"owned fixture proof")
    fixture.started = 0.
    def flush():
        if fault == "proof":
            raise OSError("Private controlled proof flush failure")
    fixture.flush = flush
    monkeypatch.setattr(sidebar, "owned_process_exit", exit_owned)
    monkeypatch.setattr(script.bpy.app, "version_string", "Portable fixture model", raising=False)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", stream("stdout"))
        patch.setattr(sys, "stderr", stream("stderr"))
        with pytest.raises(OwnedExit):
            fixture.finish(0)
    assert observed == [0 if fault is None else 1]
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("alias_matches", [True, False])
def test_animation_intent_native_shaped_snapshot_has_four_field_bits_and_checks_alias_before_freeze(
    fixture_imports, alias_matches,
):
    script = importlib.import_module("scripts.blender_animation_intent_smoke")

    def prop(name, kind):
        return NS(identifier=name, is_readonly=False, is_runtime=False, is_registered=False, type=kind)

    point_fields = ("co", "co_ui", "handle_left", "handle_right")
    point = NS(co=[11., 10.], co_ui=[11., 10. if alias_matches else 12.],
               handle_left=[10., -0.], handle_right=[14., 10.], as_pointer=lambda: 71,
               bl_rna=NS(identifier="Keyframe", properties=[prop(name, "FLOAT") for name in point_fields]))
    curve = NS(data_path="location", array_index=0, keyframe_points=[point], sampled_points=[], modifiers=[],
               as_pointer=lambda: 70, bl_rna=NS(identifier="FCurve", properties=[prop("data_path", "STRING"), prop("array_index", "INT")]))
    if alias_matches:
        row = script.curve_row(curve)
        snapshot, = row["points"]
        assert set(snapshot["rna"]) == set(snapshot["float32_bits"]) == set(point_fields)
        assert snapshot["float32_bits"]["co"] == snapshot["float32_bits"]["co_ui"] == ["00003041", "00002041"]
        assert snapshot["float32_bits"]["handle_left"][1] == "00000080"
        before = {"actions": [{"identity": {"pointer": 7}, "layers": [{"strips": [{"bags": [{"curves": [row]}]}]}]}]}
        predicted = script.predict(before, 7, {"keyframes": [{"frame": 11., "co": [11., 13.]}]})
        expected = script.chosen_curve(predicted, 7)["points"][0]
        assert set(expected["rna"]) == set(expected["float32_bits"]) == set(point_fields)
        assert expected["float32_bits"]["co"] == expected["float32_bits"]["co_ui"] == ["00003041", "00005041"]
    else:
        with pytest.raises(AssertionError, match="Native co_ui read alias differs before freezing"):
            script.curve_row(curve)
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_animation_intent_oracle_predicts_whole_state_without_readback(fixture_imports):
    import copy
    import struct

    script = importlib.import_module("scripts.blender_animation_intent_smoke")
    curve = {"identity": {"pointer": 70},
             "rna": {"data_path": "location", "array_index": 0, "extrapolation": "CONSTANT"},
             "points": [{"identity": {"pointer": 71},
                         "rna": {"co": [11., 10.], "co_ui": [11., 10.], "handle_left": [10., 10.], "handle_right": [14., 10.],
                                  "interpolation": "BEZIER", "easing": "AUTO"},
                         "float32_bits": {"co": ["00003041", "00002041"], "co_ui": ["00003041", "00002041"],
                                          "handle_left": ["00002041", "00002041"], "handle_right": ["00006041", "00002041"]}}]}
    before = {"actions": [{"identity": {"pointer": 7}, "layers": [{"strips": [{"bags": [{"curves": [curve]}]}]}]}],
              "protected": {"curve": [1., -0.]}, "context": {"frame": 1}}
    original = copy.deepcopy(before)
    request = {"keyframes": [{"frame": 11., "co": [11., .1], "handle_left": [10., -0.],
                             "handle_right": [14., .25]}]}
    result = script.predict(before, 7, request)
    observed = script.chosen_curve(result, 7)
    point = observed["points"][0]
    assert observed["rna"] == curve["rna"] and observed["identity"] == curve["identity"]
    assert point["identity"] == curve["points"][0]["identity"]
    assert point["rna"]["co"] == point["rna"]["co_ui"] == [11., struct.unpack("<f", struct.pack("<f", .1))[0]]
    assert point["rna"]["co"] is not point["rna"]["co_ui"]
    assert point["float32_bits"]["co"] == point["float32_bits"]["co_ui"] == ["00003041", "cdcccc3d"]
    assert point["rna"]["handle_right"] == [14., .25]
    assert point["float32_bits"]["handle_left"][1] == "00000080"
    assert result["protected"] == before["protected"] and result["context"] == before["context"]
    assert script.same(before, original) and not script.same(before, result)
    assert not script.same(-0., 0.) and not script.same(True, 1)
    assert script.same(result, script.predict(result, 7, request))
    handles_only = script.predict(before, 7, {"keyframes": [{"frame": 11., "handle_left": [10., -0.]}]})
    handle_point = script.chosen_curve(handles_only, 7)["points"][0]
    assert handle_point["rna"]["co"] == handle_point["rna"]["co_ui"] == [11., 10.]
    assert handle_point["float32_bits"]["co"] == curve["points"][0]["float32_bits"]["co"]
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("curve_request", [
    {"extrapolation": "CONSTANT"},
    {"keyframes": [{"frame": -0., "interpolation": "BEZIER"}]},
    {"keyframes": [{"frame": -0., "handle_left_type": "FREE"}]},
    {"keyframes": [{"frame": -0., "co": [0., 2.]}]},
    {"keyframes": [{"frame": -0., "co": [1., 2.]}]},
])
def test_animation_intent_oracle_refuses_full_curve_fields_and_time_bit_changes(fixture_imports, curve_request):
    script = importlib.import_module("scripts.blender_animation_intent_smoke")
    point = {"rna": {"co": [-0., 1.], "co_ui": [-0., 1.]},
             "float32_bits": {"co": ["00000080", "0000803f"], "co_ui": ["00000080", "0000803f"]}}
    curve = {"rna": {"data_path": "location", "array_index": 0}, "points": [point]}
    before = {"actions": [{"identity": {"pointer": 7}, "layers": [{"strips": [{"bags": [{"curves": [curve]}]}]}]}]}
    with pytest.raises(AssertionError):
        script.predict(before, 7, curve_request)
    assert point["rna"]["co"] == [-0., 1.] and point["float32_bits"]["co"][0] == "00000080"
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("failure", [False, True])
def test_animation_intent_checkpoint_observer_calls_original_once_and_never_fakes_completion(fixture_imports, failure):
    script = importlib.import_module("scripts.blender_animation_intent_smoke")
    calls, blender, guard = [], object(), object()

    def original(actual_blender, label, **kwargs):
        calls.append((actual_blender, label, kwargs))
        if failure:
            raise RuntimeError("Actual snapshot refused")
        return "real-snapshot-token"

    fixture = script.Fixture.__new__(script.Fixture)
    fixture.runtime = NS(checkpoints=NS(_snapshot=original))
    fixture.label, fixture.data = "owned-call", {"native_snapshot_receipts": []}
    fixture.observe_checkpoints()
    if failure:
        with pytest.raises(RuntimeError, match="Actual snapshot refused"):
            fixture.runtime.checkpoints._snapshot(blender, "before", guard=guard)
    else:
        assert fixture.runtime.checkpoints._snapshot(blender, "before", guard=guard) == "real-snapshot-token"
    assert calls == [(blender, "before", {"guard": guard})]
    row, = fixture.data["native_snapshot_receipts"]
    assert row == {"call": "owned-call", "label": "before", "completed": not failure,
                   **({} if failure else {"returned": "real-snapshot-token"})}
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_animation_intent_source_excludes_held_native_paths_and_production_provider_replacement():
    tree = ast.parse((ROOT / "scripts/blender_animation_intent_smoke.py").read_text())
    forbidden_calls = {"frame_set", "keyframe_insert", "save_as_mainfile", "save_mainfile", "save_userpref",
                       "undo", "undo_redo", "undo_history"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls
                if node.func.attr == "update":
                    assert isinstance(node.func.value, ast.Name) and node.func.value.id in {"result", "row"}
            if isinstance(node.func, ast.Name):
                assert node.func.id != "PermissionManager"
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for field in ast.walk(target):
                    if isinstance(field, ast.Attribute):
                        assert field.attr not in {"_write", "_update", "_read", "_source", "permissions", "ui_type"}


@pytest.mark.parametrize("first_value,expected", [(0., (0., 20., 0.)), (20., (20., 40., 0.)), (-2.5, (-2.5, 17.5, 0.))])
def test_animation_intent_factory_seeds_first_key_transform_before_binding(
    fixture_imports, monkeypatch, first_value, expected,
):
    script = importlib.import_module("scripts.blender_animation_intent_smoke")
    events, curves = [], []

    class Actor:
        def __init__(self):
            self._location = (0., 0., 0.)
            self.animation_data = NS(action=None, action_slot=None)

        @property
        def location(self):
            return self._location

        @location.setter
        def location(self, value):
            self._location = tuple(value)
            events.append(("location", tuple(value)))

        def animation_data_create(self):
            assert self.location == expected
            assert len(curves) == 2 and all(len(curve.keyframe_points) == 2 for curve in curves)
            events.append(("binding", None))
            return self.animation_data

    class Points(list):
        def add(self, count):
            self.extend(NS() for _ in range(count))

    def curve_new(*, data_path, index):
        assert data_path == "location" and index == len(curves)
        curve = NS(keyframe_points=Points(), update=lambda: pytest.fail("Raw setup must never issue FCurve.update"))
        curves.append(curve)
        return curve

    actor, slot = Actor(), NS()
    bag = NS(fcurves=NS(new=curve_new))
    strip = NS(channelbag=lambda actual_slot, ensure: bag if actual_slot is slot and ensure else pytest.fail("Wrong raw slot"))
    layer = NS(strips=NS(new=lambda **kwargs: strip if kwargs == {"type": "KEYFRAME"} else pytest.fail("Wrong strip")))
    action = NS(slots=NS(new=lambda *args: slot if args == ("OBJECT", "Actor") else pytest.fail("Wrong actor slot")),
                layers=NS(new=lambda name: layer if name == "Raw Owned Layer" else pytest.fail("Wrong layer")))

    def object_new(name, data):
        assert (name, data) == ("Actor", None)
        events.append(("new_object", None))
        return actor

    def action_new(name):
        assert name == "Motion" and actor.location == expected
        events.append(("new_action", None))
        return action

    scene = NS(frame_current=1, frame_subframe=0., collection=NS(objects=NS(link=lambda owner: events.append(("link", owner)))))
    monkeypatch.setattr(script.bpy, "context", NS(scene=scene), raising=False)
    monkeypatch.setattr(script.bpy, "data", NS(objects=NS(new=object_new), actions=NS(new=action_new)), raising=False)
    assert script.make_actor("Actor", "Motion", ((1., first_value), (11., first_value+10.))) == (action, actor)
    assert actor.location == expected and actor.animation_data.action is action and actor.animation_data.action_slot is slot
    assert [name for name, _ in events] == ["new_object", "location", "link", "new_action", "binding"]
    assert tuple(curve.keyframe_points[0].co[1] for curve in curves) == expected[:2]
    assert [scene.frame_current, scene.frame_subframe] == [1, 0.]
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("frame,subframe,first_key", [(2, 0., 1.), (1, .25, 1.), (1, 0., 2.)])
def test_animation_intent_factory_refuses_other_time_before_allocation(fixture_imports, monkeypatch, frame, subframe, first_key):
    script = importlib.import_module("scripts.blender_animation_intent_smoke")
    scene = NS(frame_current=frame, frame_subframe=subframe)
    monkeypatch.setattr(script.bpy, "context", NS(scene=scene), raising=False)
    monkeypatch.setattr(script.bpy, "data", NS(objects=NS(new=lambda *_args: pytest.fail("Time refused before allocation"))), raising=False)
    with pytest.raises(AssertionError, match="factory frame one"):
        script.make_actor("Actor", "Motion", ((first_key, 0.), (11., 10.)))
    assert [scene.frame_current, scene.frame_subframe] == [frame, subframe]
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_large_surface_independent_sample_oracle_and_packed_digest(fixture_imports):
    import hashlib
    import struct
    from array import array

    script = importlib.import_module("scripts.blender_large_surface_paint_smoke")
    assert script.SIZE == 4096
    assert script.stencil_rgba(63) == (0., .25, .5, 1.)
    assert script.stencil_rgba(64) == (1., .25, .5, 1.)
    assert script.oracle_rgba(2016, 2048) == (.5625, .375, .25, 1.)
    assert script.oracle_rgba(2048, 2048) == script.SOURCE  # Zero stencil stripe on the triangulation seam.
    assert script.oracle_rgba(2016, 2304) == script.SOURCE  # Beyond the hard capsule.
    assert script.oracle_rgba(0, 4095) == script.SOURCE
    raw = array("f", [-0., 1., .5, -1.])
    assert script.digest(raw) == hashlib.sha256(struct.pack("<4f", -0., 1., .5, -1.)).hexdigest()
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("outcome", ["enabled", "cancelled", "missing_entry", "missing_preferences", "auto_start"])
def test_large_surface_setup_requires_normal_enable_and_live_preferences(fixture_imports, monkeypatch, outcome):
    script = importlib.import_module("scripts.blender_large_surface_paint_smoke")
    events, addons = [], {}
    prefs = NS(auto_start=outcome == "auto_start")

    def enable(*, module):
        assert module == "blender_codex_bridge"
        events.append("normal_addon_enable")
        assert not addons
        if outcome == "cancelled":
            return {"CANCELLED"}
        if outcome != "missing_entry":
            addons[module] = NS(preferences=prefs)
        return {"FINISHED"}

    def live_preferences():
        events.append("live_preferences")
        assert "blender_codex_bridge" in addons, "Direct registration provides no enabled entry"
        return None if outcome == "missing_preferences" else addons["blender_codex_bridge"].preferences

    preferences = ModuleType("blender_codex_bridge.preferences")
    preferences.get_preferences = live_preferences
    monkeypatch.setitem(sys.modules, preferences.__name__, preferences)
    monkeypatch.setattr(script.bpy, "context", NS(preferences=NS(addons=addons)), raising=False)
    monkeypatch.setattr(script.bpy.ops, "preferences", NS(addon_enable=enable), raising=False)
    if outcome == "enabled":
        assert script.enable_fixture_addon() is prefs
    else:
        with pytest.raises(AssertionError):
            script.enable_fixture_addon()
    assert events == (["normal_addon_enable"] if outcome in {"cancelled", "missing_entry"}
                      else ["normal_addon_enable", "live_preferences"])
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("exit_status", [0, 1])
def test_large_surface_periodic_proof_keeps_all_rows_and_flushes_final_immediately(
    fixture_imports, monkeypatch, exit_status,
):
    import hashlib
    import json

    script = importlib.import_module("scripts.blender_large_surface_paint_smoke")
    clock, exits = NS(now=0.), []
    monkeypatch.setattr(script, "time", NS(perf_counter=lambda: clock.now))

    class Sink:
        def __init__(self):
            self.writes = []

        def exists(self):
            return False

        def write_bytes(self, raw):
            self.writes.append((clock.now, bytes(raw)))
            return len(raw)

    main, summary = Sink(), Sink()
    fixture = script.Fixture.__new__(script.Fixture)
    fixture.proof_snapshots = script.ProofSnapshots(main, summary)
    fixture.events, fixture.controls = script.queue.Queue(), script.queue.Queue()
    fixture.done = NS(is_set=lambda: False)
    fixture.originals = []
    fixture.phase = "normal"
    fixture.started = fixture.last_tick = fixture.last_memory = 0.
    fixture.memory = lambda _label: None
    fixture.data = {"calls": [], "jobs": [], "controls": [], "completed": False,
                    "timer_gaps": {"count": 0, "sum_seconds": 0., "largest": []}}
    fixture.flush()
    rows = []
    for index in range(1, 302):
        clock.now = index / 100
        row = {"kind": "call", "id": index, "raw_result": {"unchanged": [index, -0.]}}
        rows.append(row)
        fixture.events.put(row)
        assert fixture.tick() == .01  # Control/timer processing keeps its original cadence.
    assert [at for at, _raw in main.writes] == [0., 1., 2., 3.]
    assert fixture.data["calls"] == rows
    assert fixture.proof_snapshots.metrics["largest_periodic_request_age_seconds"] <= 1.
    # Native-helper/control callers use this unchanged immediate default.
    fixture.data["critical_control"] = {"retained": True}
    fixture.flush()
    assert main.writes[-1][0] == 3.01
    fixture.data["completed"] = exit_status == 0
    if exit_status:
        fixture.data["failure"] = "Retained modeled fixture failure"
    fixture.flush()  # Final success/failure evidence before the existing marker.
    marker_hash = hashlib.sha256(main.writes[-1][1]).hexdigest()
    exit_module = ModuleType("blender_artist_sidebar_smoke")
    exit_module.owned_process_exit = exits.append
    monkeypatch.setitem(sys.modules, exit_module.__name__, exit_module)
    fixture.finish(exit_status)
    assert exits == [exit_status]
    assert hashlib.sha256(main.writes[-1][1]).hexdigest() == marker_hash
    final = json.loads(main.writes[-1][1])
    assert final["calls"] == rows and len(final["calls"]) == 301
    assert final["critical_control"] == {"retained": True}
    assert final.get("failure") == ("Retained modeled fixture failure" if exit_status else None)
    metrics = json.loads(summary.writes[-1][1])
    assert metrics["snapshot_count"] == len(main.writes) == 7
    assert metrics["periodic_snapshot_count"] == 3 and metrics["immediate_snapshot_count"] == 4
    assert metrics["periodic_requests"] == 301 and metrics["coalesced_periodic_requests"] == 298
    assert metrics["bytes_written"] == metrics["bytes_serialized"] == sum(len(raw) for _at, raw in main.writes)
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_large_surface_proof_io_records_actual_cost_and_timer_delay(fixture_imports, monkeypatch):
    import json

    script = importlib.import_module("scripts.blender_large_surface_paint_smoke")
    clock = NS(now=0.)
    monkeypatch.setattr(script, "time", NS(perf_counter=lambda: clock.now))
    original_canonical = script.canonical

    def measured_canonical(data):
        raw = original_canonical(data)
        clock.now += .005
        return raw

    monkeypatch.setattr(script, "canonical", measured_canonical)

    class Sink:
        def __init__(self):
            self.writes = []

        def exists(self):
            return False

        def write_bytes(self, raw):
            self.writes.append(bytes(raw))
            clock.now += .002
            return len(raw)

    main, summary = Sink(), Sink()
    snapshots = script.ProofSnapshots(main, summary)
    snapshots.flush({"calls": [{"id": 1}]})
    clock.now = .99
    snapshots.flush({"calls": [{"id": 1}, {"id": 2}]}, periodic=True)
    assert len(main.writes) == 1
    clock.now = 2.5  # A blocked native interval is exposed, never reported as a 1s guarantee.
    snapshots.flush({"calls": [{"id": 1}, {"id": 2}]}, periodic=True)
    snapshots.finish()
    metrics = json.loads(summary.writes[-1])
    assert metrics["snapshot_count"] == metrics["snapshot_attempts"] == 2
    assert metrics["serialization_seconds"] == pytest.approx(.010)
    assert metrics["write_seconds"] == pytest.approx(.004)
    assert metrics["bytes_written"] == sum(map(len, main.writes))
    assert metrics["largest_periodic_request_age_seconds"] == pytest.approx(2.493)
    assert json.loads(main.writes[-1])["calls"] == [{"id": 1}, {"id": 2}]
def test_uv_guard_fixture_oracle_rounds_requested_f32_and_preserves_other_fields(fixture_imports):
    script = importlib.import_module("scripts.blender_uv_edit_guard_smoke")
    before = {"Primary": [
        {"face": 0, "corner": 0, "uv": [0., -0.], "float32_le": script.bits((0., -0.)), "pin_uv": False},
        {"face": 0, "corner": 1, "uv": [.25, .5], "float32_le": script.bits((.25, .5)), "pin_uv": True}],
        "Protected": [{"face": 0, "corner": 0, "uv": [.5, .75], "float32_le": script.bits((.5, .75)), "pin_uv": True}]}
    params = {"uv_layer": "Primary", "updates": [{"face_index": 0, "corner_index": 0, "uv": [-0., .1]}]}
    output = script.expected_maps(before, "coordinates_set", params)
    assert output["Primary"][0]["float32_le"] == ["00000080", "cdcccc3d"]
    assert output["Primary"][1] == before["Primary"][1] and output["Protected"] == before["Protected"]
    transformed = script.expected_maps(before, "transform", {"uv_layer": "Primary", "offset": [.1, .2]})
    assert transformed["Primary"][0]["float32_le"] == ["cdcccc3d", "cdcc4c3e"]
    assert transformed["Primary"][1] == before["Primary"][1]
    pinned = script.expected_maps(before, "pin", {"uv_layer": "Primary", "corners": [{"face_index": 0, "corner_index": 0}], "pinned": True})
    assert pinned["Primary"][0]["pin_uv"] is True
    assert pinned["Primary"][0]["float32_le"] == before["Primary"][0]["float32_le"]
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_uv_guard_fixture_unknown_setter_model_releases_leaf_before_fault(fixture_imports):
    script = importlib.import_module("scripts.blender_uv_edit_guard_smoke")
    fixture = NS(mode="unknown_setter", armed=True, restoring=False, snapshot_reads=7, trace=[])
    target = NS(uv=(0., 0.))
    setter = script.Setter(fixture, target, (0, 0, 0, 0), "uv")
    with pytest.raises(RuntimeError, match="same-field unknown setter"):
        setter.uv = (.1, .2)
    assert setter.target is None and target.uv == (.9375, -.3125)
    assert fixture.trace[0]["snapshots_since_resolve"] == 0
    assert fixture.trace[0]["delegate_calls"] == 1 and fixture.trace[0]["completed"]
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("profile", ["leaf", "no_leaf", "multiple", "nested", "linked", "override", "readonly", "full"])
def test_uv_guard_fixture_links_both_meshes_only_to_existing_direct_local_leaf(fixture_imports, profile):
    script = importlib.import_module("scripts.blender_uv_edit_guard_smoke")
    links = []

    class Members:
        def __len__(self):
            return 255 if profile == "full" else 3

        def link(self, obj):
            links.append(obj)

    def forbidden_master_link(_obj):
        pytest.fail("Fixture must not link a UV owner to the non-leaf factory master")

    master = NS(objects=NS(link=forbidden_master_link))
    leaf = NS(children=[object()] if profile == "nested" else [], objects=Members(),
              library=object() if profile == "linked" else None,
              override_library=object() if profile == "override" else None,
              is_editable=profile != "readonly")
    master.children = [] if profile == "no_leaf" else [leaf, object()] if profile == "multiple" else [leaf]
    work, peer = object(), object()
    if profile == "leaf":
        assert script.link_fixture_meshes(NS(collection=master), work, peer) is leaf
        assert links == [work, peer] and master.children == [leaf] and leaf.children == []
    else:
        with pytest.raises(AssertionError):
            script.link_fixture_meshes(NS(collection=master), work, peer)
        assert not links
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("create_entry", [True, False])
def test_uv_guard_fixture_uses_normal_addon_enable_before_live_preferences(fixture_imports, monkeypatch, create_entry):
    script = importlib.import_module("scripts.blender_uv_edit_guard_smoke")
    events, entries = [], {}
    prefs, runtime = NS(auto_start=False), object()
    preferences = ModuleType("blender_codex_bridge.preferences")

    def get_preferences():
        events.append("preferences")
        addon = entries.get("blender_codex_bridge")
        return None if addon is None else addon.preferences

    preferences.get_preferences = get_preferences
    monkeypatch.setitem(sys.modules, preferences.__name__, preferences)
    monkeypatch.setattr(sys.modules["blender_codex_bridge.runtime"], "get_runtime", lambda: events.append("runtime") or runtime)

    def enable(*, module):
        assert module == "blender_codex_bridge"
        events.append("enable")
        if create_entry:
            entries[module] = NS(preferences=prefs)
        return {"FINISHED"}

    monkeypatch.setattr(script.bpy, "context", NS(preferences=NS(addons=entries)), raising=False)
    monkeypatch.setattr(script.bpy.ops, "preferences", NS(addon_enable=enable), raising=False)
    if create_entry:
        assert script.enable_addon() == (runtime, prefs)
        assert events == ["enable", "preferences", "runtime"]
    else:
        with pytest.raises(AssertionError, match="Enabled add-on entry is missing"):
            script.enable_addon()
        assert events == ["enable"]
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("global_selection,empty_secondary_pin", [(False, False), (True, False), (True, True)])
def test_uv_object_reader_copies_each_property_before_native_handle_invalidation(
    fixture_imports, monkeypatch, global_selection, empty_secondary_pin,
):
    script = importlib.import_module("scripts.blender_uv_edit_storage_smoke")
    events = []
    mesh = NS(generation=0)

    def descriptor(kind, *, length=0, fixed=None):
        return NS(type=kind, array_length=length, is_runtime=False, is_registered=False,
                  fixed_type=NS(identifier=fixed))

    class Float2AttributeValue:
        bl_rna = NS(properties={"vector": descriptor("FLOAT", length=2)})

        def __init__(self, generation, field, index, value):
            self.generation, self.field, self.index, self.raw = generation, field, index, value

        @property
        def vector(self):
            assert self.generation == mesh.generation, "UV collection survived a later allocating getter"
            events.append(("copy", self.field, self.index))
            return self.raw

    class BoolAttributeValue(Float2AttributeValue):
        bl_rna = NS(properties={"value": descriptor("BOOLEAN")})

        @property
        def value(self):
            assert self.generation == mesh.generation, "Boolean collection survived a later allocating getter"
            events.append(("copy", self.field, self.index))
            return self.raw

    buffers = {name: {"uv": [(index * .25, -0. if index == 0 else .5) for index in range(8)],
                      "pin": [index % 3 == 0 for index in range(8)],
                      "vertex_selection": [index % 2 == 0 for index in range(8)],
                      "edge_selection": [index % 2 == 1 for index in range(8)]} for name in script.MAPS}
    if empty_secondary_pin:
        buffers[script.MAPS[1]]["pin"] = []

    class MeshUVLoopLayer:
        bl_rna = NS(properties={field: descriptor("COLLECTION", fixed="Float2AttributeValue" if field == "uv" else "BoolAttributeValue")
                                for field in ("uv", "pin", "vertex_selection", "edge_selection")})

        def __init__(self, name):
            self.name, self.generation = name, mesh.generation

        def __getattr__(self, field):
            assert self.generation == mesh.generation, "UV-layer handle survived a materializing getter"
            assert field in buffers[self.name]
            events.append(("getter", self.name, field))
            mesh.generation += 1
            kind = Float2AttributeValue if field == "uv" else BoolAttributeValue
            return [kind(mesh.generation, field, index, value) for index, value in enumerate(buffers[self.name][field])]

    def fresh_layer(name):
        events.append(("fresh_layer", name))
        return MeshUVLoopLayer(name)

    monkeypatch.setattr(script.bpy, "types", NS(MeshUVLoopLayer=MeshUVLoopLayer,
                        Float2AttributeValue=Float2AttributeValue, BoolAttributeValue=BoolAttributeValue), raising=False)
    mesh.uv_layers = NS(get=fresh_layer)
    mesh.loops = [NS(vertex_index=index % 6, edge_index=index % 7) for index in range(8)]
    mesh.polygons = [NS(index=0, loop_indices=range(4)), NS(index=1, loop_indices=range(4, 8))]
    proof = object.__new__(script.Proof)
    proof.work, proof.global_selection = NS(data=mesh), global_selection
    proof.data = {"object_property_copies": []}
    proof.access, proof.flush = lambda _label, callback: callback(), lambda: None
    result = proof.read_maps("mock_object", edit=False)
    fields = ("uv", "pin") if global_selection else ("uv", "pin", "vertex_selection", "edge_selection")
    assert [event for event in events if event[0] == "getter"] == [
        ("getter", name, field) for name in script.MAPS for field in fields]
    assert len([event for event in events if event[0] == "fresh_layer"]) == len(fields) * 2
    cursor = 0
    for name in script.MAPS:
        for field in fields:
            assert events[cursor:cursor + 2] == [("fresh_layer", name), ("getter", name, field)]
            cursor += 2
            for index in range(len(buffers[name][field])):
                assert events[cursor] == ("copy", field, index)
                cursor += 1
    assert cursor == len(events)
    for name in script.MAPS:
        assert len(result[name]) == 8
        for index, corner in enumerate(result[name]):
            assert corner["uv"] == list(buffers[name]["uv"][index])
            assert corner["float32_le"] == script.pair_bits(buffers[name]["uv"][index])
            assert corner["pin_uv"] is (buffers[name]["pin"][index] if buffers[name]["pin"] else None)
            assert ("select" in corner) is (not global_selection)
    assert result[script.MAPS[0]][0]["float32_le"][1] == "00000080"
    copied = proof.data["object_property_copies"]
    assert len(copied) == len(fields) * 2
    assert all(row["raw_length"] == len(row["plain_values"]) and row["mesh_loop_count"] == 8 for row in copied)
    if empty_secondary_pin:
        assert next(row for row in copied if row["map"] == script.MAPS[1] and row["property"] == "pin")["plain_values"] == []


@pytest.mark.parametrize("malformed", ["runtime_descriptor", "wrong_pin_item_type"])
def test_uv_object_reader_refuses_malformed_descriptors_or_item_types_before_value_read(
    fixture_imports, monkeypatch, malformed,
):
    script = importlib.import_module("scripts.blender_uv_edit_storage_smoke")
    reads = []
    boolean = NS(type="BOOLEAN", array_length=0, is_runtime=False, is_registered=False)

    class BoolAttributeValue:
        bl_rna = NS(properties={"value": boolean})

        @property
        def value(self):
            reads.append("value")
            pytest.fail("Malformed native data must be refused before reading a value")

    class Float2AttributeValue:
        pass

    class MeshUVLoopLayer:
        bl_rna = NS(properties={"pin": NS(type="COLLECTION", is_runtime=malformed == "runtime_descriptor",
            is_registered=False, fixed_type=NS(identifier="BoolAttributeValue"))})

        @property
        def pin(self):
            reads.append("pin_getter")
            return [Float2AttributeValue()]

    monkeypatch.setattr(script.bpy, "types", NS(MeshUVLoopLayer=MeshUVLoopLayer,
                        BoolAttributeValue=BoolAttributeValue), raising=False)
    mesh = NS(uv_layers=NS(get=lambda _name: MeshUVLoopLayer()))
    with pytest.raises(AssertionError):
        script.copy_object_uv_property(mesh, script.MAPS[0], "pin")
    assert reads == ([] if malformed == "runtime_descriptor" else ["pin_getter"])


@pytest.fixture
def scene_worker(fixture_imports, monkeypatch):
    script = importlib.import_module("scripts.blender_scene_job_kernel_smoke")

    def run(*, retire_at="stop", drift=None):
        state = NS(case=None, terminal=False, progressed=False, pending_stop=None, polls_left=0,
                   body_a_x=0., resumes=[], waits=[], observations=[], recorded={}, requests=[],
                   stopped_observations=0, final_verified=False, clients_closed=0, sleeps=[])

        def stop():
            state.pending_stop = state.case
            state.terminal = retire_at == "stop"
            state.polls_left = 1

        def summary():
            if state.pending_stop and not state.terminal:
                if state.polls_left:
                    state.polls_left -= 1
                else:
                    state.terminal = True
            value = {"job_id": state.case, "terminal": state.terminal,
                     "state": "SUCCEEDED" if state.case == "complete" and state.terminal else
                              "FAILED" if state.terminal else "RUNNING",
                     "revision": int(state.progressed)+int(state.terminal)}
            if state.pending_stop:
                value["error"] = {"code": {"cancel": "TIMEOUT", "permission": "PERMISSION_DENIED",
                    "disconnect": "TIMEOUT", "external_edit": "INVALID_ARGUMENT"}[state.case],
                    "context": {"connection_disconnected": state.case == "disconnect"}}
            return value

        class Client:
            def __init__(self, port):
                assert port == 12345

            def call(self, method, **params):
                if method == script.START:
                    assert params == {"case": state.case}
                    return {"accepted": True, "job_id": state.case, "terminal": False}
                if method == script.INSPECT:
                    assert params == {"job_id": state.case}
                    return summary()
                if method == "bridge.status":
                    return {}
                assert method == "jobs.cancel" and params == {"job_id": state.case}
                stop()
                return {"cancel_requested": True}

            def request(self, method):
                assert method in {script.FOREIGN, script.EVALUATE}
                state.requests.append((state.case, method))
                return {"ok": False, "error": {"code": "OPERATION_FAILED",
                    "context": {"reason": "SCENE_JOB_RESERVATION_BLOCKED"}}}

            def close(self):
                state.clients_closed += 1
                if state.case == "disconnect" and not state.terminal:
                    stop()

        def control(action, **params):
            if action == "prepare_case":
                state.case, state.terminal, state.progressed = params["case"], False, False
                state.pending_stop, state.body_a_x, state.stopped_observations = None, 0., 0
            elif action == "resume":
                assert not state.pending_stop, "A stopped owner has no later timer turn"
                state.resumes.append(state.case)
                state.progressed = True
                state.terminal = state.case == "complete"
            elif action == "observe":
                assert params == {"case": state.case}
                value = {"last_domain_phase": "frame_2_set" if state.progressed else None,
                         "domain_phase_count": int(state.progressed), "native_call_count": 33,
                         "undo_push_count": 1, "checkpoint_stamp_count": 3,
                         "scene_marker": "owned-before", "frame": [2, 0.],
                         "caller_context_restored": False, "body_a_x": state.body_a_x}
                if state.pending_stop:
                    state.stopped_observations += 1
                    if state.case == "external_edit" and drift:
                        when = 2 if drift == "late_native_call_count" else 1
                        if state.stopped_observations == when:
                            field = "native_call_count" if drift == "late_native_call_count" else drift
                            value[field] = {"scene_marker": "foreign", "frame": [3, 0.],
                                "caller_context_restored": True, "body_a_x": .25}.get(field, 999)
                state.observations.append((state.case, bool(state.pending_stop), value.copy()))
                return value
            elif action in {"deny_animation", "external_edit"}:
                if action == "external_edit":
                    state.body_a_x += .125
                stop()
            elif action == "allow_animation":
                assert state.terminal
            elif action == "record_terminal":
                assert params["case"] == state.case and params["terminal"]["terminal"]
                state.recorded[state.case] = params["terminal"]
            else:
                assert action == "final_verify" and len(state.recorded) == 5
                state.final_verified = True

        def wait(timeout):
            assert timeout == 10 and state.resumes[-1] == state.case
            assert not state.pending_stop, "A retired owner cannot signal TURN_DONE"
            state.waits.append(state.case)
            return True

        clock = iter(range(1000))
        monkeypatch.setattr(script, "Client", Client)
        monkeypatch.setattr(script, "control", control)
        monkeypatch.setattr(script, "TURN_DONE", NS(wait=wait))
        monkeypatch.setattr(script, "DONE", threading.Event())
        monkeypatch.setattr(script, "RESULT", {})
        monkeypatch.setattr(script, "time", NS(perf_counter=lambda: 0.,
                            monotonic=lambda: next(clock), sleep=state.sleeps.append))
        script.scenario(12345)
        assert script.DONE.is_set()
        return state, script.RESULT

    return run


@pytest.mark.parametrize("retire_at", ["stop", "poll"])
def test_scene_worker_polls_all_stopped_owners_without_resuming(scene_worker, retire_at):
    state, result = scene_worker(retire_at=retire_at)
    assert "failure" not in result, result.get("failure")
    cases = ["complete", "cancel", "permission", "disconnect", "external_edit"]
    assert state.resumes == state.waits == cases
    assert list(result["terminal_outcomes"]) == list(state.recorded) == cases
    assert state.final_verified and state.clients_closed == 2
    assert len(result["entry_refusals"]) == len(state.requests) == 10
    for case in cases[1:]:
        observations = [row for name, stopped, row in state.observations if name == case and stopped]
        assert len(observations) == 2  # Immediate and delayed no-tail assertions both ran.
        assert all(row["native_call_count"] == 33 for row in observations)
        assert all(row["caller_context_restored"] is False for row in observations)
    assert state.recorded["external_edit"]["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("drift", [
    "domain_phase_count", "native_call_count", "undo_push_count", "checkpoint_stamp_count",
    "scene_marker", "frame", "caller_context_restored", "body_a_x", "late_native_call_count",
])
def test_scene_worker_keeps_stopped_evidence_assertions(scene_worker, drift):
    state, result = scene_worker(drift=drift)
    assert "AssertionError" in result.get("failure", ""), result
    assert "external_edit" not in state.recorded and not state.final_verified
    assert state.resumes == ["complete", "cancel", "permission", "disconnect", "external_edit"]


_WEIGHT_OBSERVER_CHILD = "_bcb_weight_observer_test_child"
_WEIGHT_OBSERVER_CHILD_ENV = "BCB_WEIGHT_OBSERVER_TEST_CHILD"
_WEIGHT_OBSERVER_MARKER = "BCB_WEIGHT_OBSERVER_TEST_OK "
_WEIGHT_OBSERVER_BOOTSTRAP = r"""
import json
import os
import sys
from pathlib import Path

root, nodeid = Path(sys.argv[1]).resolve(strict=True), sys.argv[2]
target = root / 'tests' / 'test_research_fixture_imports.py'
assert sys.getprofile() is None and sys.gettrace() is None
assert not any(key.startswith(('COV_CORE_', 'COVERAGE_', 'PYTEST_')) for key in os.environ
               if key != 'PYTEST_DISABLE_PLUGIN_AUTOLOAD')
assert os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'
assert os.environ['BCB_WEIGHT_OBSERVER_TEST_CHILD'] == '1'
assert nodeid.startswith('tests/test_research_fixture_imports.py::test_weight_observer_')
sys._bcb_weight_observer_test_child = (str(target), nodeid)
sys.path[:0] = [str(root), str(root / 'tests')]
import pytest

class ExactCase:
    def __init__(self):
        self.calls = []
    def pytest_collection_finish(self, session):
        assert [item.nodeid for item in session.items] == [nodeid]
    def pytest_runtest_logreport(self, report):
        if report.when == 'call':
            self.calls.append((report.nodeid, report.outcome))

exact = ExactCase()
# The owned child needs only builtin fixtures. Do not autoload coverage/timeout
# or inherit the repository's plugin-specific configuration in this child.
status = pytest.main(['-c', os.devnull, '--rootdir', str(root), '-q',
                      '-p', 'no:cacheprovider', nodeid], plugins=[exact])
assert status == 0 and exact.calls == [(nodeid, 'passed')], (status, exact.calls)
assert sys.getprofile() is None and sys.gettrace() is None
print('BCB_WEIGHT_OBSERVER_TEST_OK ' + json.dumps({'nodeid': nodeid, 'passed': 1,
      'profile_clear': True, 'trace_clear': True}), flush=True)
"""


def _isolated_weight_observer_test(case):
    """Keep the parent's collector; run each unchanged instrumentation case once."""
    signature = inspect.signature(case)
    assert tuple(signature.parameters)[:2] == ("fixture_imports", "addon_package")
    parameters = tuple(signature.parameters.values())[2:]
    assert {parameter.name for parameter in parameters} <= {"drift", "hook"}

    def isolated(request, **arguments):
        nodeid = request.node.nodeid
        expected = (str(Path(__file__).resolve()), nodeid)
        child = getattr(sys, _WEIGHT_OBSERVER_CHILD, None)
        child_environment = os.environ.get(_WEIGHT_OBSERVER_CHILD_ENV)
        if child is not None or child_environment is not None:
            assert child_environment == "1" and child == expected, "An observer child cannot relaunch or select another case"
            return case(request.getfixturevalue("fixture_imports"),
                        request.getfixturevalue("addon_package"), **arguments)
        assert nodeid.split("[", 1)[0] == "tests/test_research_fixture_imports.py::" + case.__name__
        profile, trace = sys.getprofile(), sys.gettrace()
        environment = {key: os.environ[key] for key in (
            "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
            "LANG", "LC_ALL", "LC_CTYPE", "TZ", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
        ) if key in os.environ}
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        environment[_WEIGHT_OBSERVER_CHILD_ENV] = "1"
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", _WEIGHT_OBSERVER_BOOTSTRAP, str(ROOT), nodeid],
                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30,
            )
        finally:
            # Never pause, replace or clear a foreign hook, including coverage's
            # CTracer. The real parent collector must survive child failure too.
            assert sys.getprofile() is profile and sys.gettrace() is trace
        assert result.returncode == 0, (result.stdout[-8192:], result.stderr[-8192:])
        markers = [line[len(_WEIGHT_OBSERVER_MARKER):] for line in result.stdout.splitlines()
                   if line.startswith(_WEIGHT_OBSERVER_MARKER)]
        assert len(markers) == 1
        assert json.loads(markers[0]) == {"nodeid": nodeid, "passed": 1,
                                         "profile_clear": True, "trace_clear": True}
        request.node.user_properties.extend([
            ("observer_parent_profile_type", type(profile).__name__),
            ("observer_parent_trace_type", type(trace).__name__),
            ("observer_parent_hooks_unchanged", True),
            ("observer_exact_child_passed", nodeid),
        ])

    # Parent fixture setup must not install the helper's Thread/Path guards before
    # subprocess communication. Only the selected child requests those fixtures.
    isolated.__name__, isolated.__qualname__ = case.__name__, case.__qualname__
    isolated.__module__, isolated.__doc__ = case.__module__, case.__doc__
    isolated.__signature__ = inspect.Signature([
        inspect.Parameter("request", inspect.Parameter.POSITIONAL_OR_KEYWORD), *parameters])
    return isolated


def weight_boundary_model(fixture_imports, addon_package, *, method="append", arguments=(7,)):
    """Actual CPython C callable + unchanged production wrapper; no Blender proof."""
    script = importlib.import_module("scripts.blender_weight_edit_guard_smoke")
    guard = importlib.import_module(f"{addon_package}.weight_edit_guard")
    values, events = [], []
    leaf = guard._NativeLeaf(arguments)
    leaf.method = getattr(values, method)
    observer = script.WriteBoundaryObserver(guard._NativeLeaf, type(leaf.method), arguments,
                                            lambda: events.append(tuple(values)))
    return NS(script=script, values=values, events=events, leaf=leaf, observer=observer)


@_isolated_weight_observer_test
def test_weight_observer_measures_completed_wrapper_after_actual_C_storage_and_release(fixture_imports, addon_package):
    case = weight_boundary_model(fixture_imports, addon_package)
    with case.observer:
        case.leaf()
    assert case.events == [(7,)] and case.values == [7]
    assert case.leaf.method is None
    assert case.observer.record["wrapper_calls"] == case.observer.record["wrapper_returns"] == 1
    assert case.observer.record["wrapper_exceptions"] == 0
    assert case.observer.record["external_event_triggered"] is True
    assert case.observer.record["leaf_released_before_external_event"] is True
    assert case.observer.record["observed_C_return_events"] is False
    assert sys.getprofile() is None and sys.gettrace() is None


@_isolated_weight_observer_test
def test_weight_observer_disarms_hooks_before_external_action_and_never_reenters(fixture_imports, addon_package):
    case = weight_boundary_model(fixture_imports, addon_package)

    def external():
        assert sys.getprofile() is None and sys.gettrace() is None
        assert case.leaf.method is None
        case.events.append(tuple(case.values))
        case.leaf.method = case.values.append
        case.leaf()

    case.observer.action = external
    with case.observer:
        case.leaf()
    assert case.events == [(7,)] and case.values == [7, 7]
    assert case.observer.record["wrapper_calls"] == case.observer.record["wrapper_returns"] == 1
    assert sys.getprofile() is None and sys.gettrace() is None


@_isolated_weight_observer_test
def test_weight_observer_does_not_admit_exceptional_native_wrapper_completion(fixture_imports, addon_package):
    case = weight_boundary_model(fixture_imports, addon_package, method="index", arguments=(99,))
    with pytest.raises(ValueError), case.observer:
        case.leaf()
    assert not case.observer.completed and case.events == [] and case.values == []
    assert case.observer.record["wrapper_exceptions"] == 1
    assert case.observer.record["external_event_triggered"] is False
    assert case.leaf.method is None and sys.getprofile() is None and sys.gettrace() is None


@_isolated_weight_observer_test
def test_weight_observer_ignores_genuine_C_calls_outside_original_wrapper(fixture_imports, addon_package):
    case = weight_boundary_model(fixture_imports, addon_package)
    with case.observer:
        case.values.append(7)
    assert not case.observer.entered and not case.observer.completed and case.events == []
    assert case.observer.record["wrapper_calls"] == case.observer.record["wrapper_returns"] == 0
    assert sys.getprofile() is None and sys.gettrace() is None


@pytest.mark.parametrize("drift", ["arguments", "method_type"])
@_isolated_weight_observer_test
def test_weight_observer_refuses_changed_arguments_or_callable_before_execution(fixture_imports, addon_package, drift):
    case = weight_boundary_model(fixture_imports, addon_package)
    if drift == "arguments":
        case.leaf.arguments = (8,)
    else:
        case.leaf.method = lambda _value: pytest.fail("An unknown callable entered")
    with pytest.raises(AssertionError), case.observer:
        case.leaf()
    assert not case.observer.completed and case.events == [] and case.values == []
    assert sys.getprofile() is None and sys.gettrace() is None


@_isolated_weight_observer_test
def test_weight_observer_external_failure_retains_actual_applied_C_state_and_restores_hooks(fixture_imports, addon_package):
    case = weight_boundary_model(fixture_imports, addon_package)

    def external():
        assert case.values == [7] and case.leaf.method is None
        raise case.script.InjectedAfterWeightWrite("Owned model failure")

    case.observer.action = external
    with pytest.raises(case.script.InjectedAfterWeightWrite), case.observer:
        case.leaf()
    assert case.values == [7] and case.leaf.method is None and case.observer.completed
    assert case.observer.record["wrapper_exceptions"] == 0
    assert sys.getprofile() is None and sys.gettrace() is None


@pytest.mark.parametrize("hook", ["profile", "trace"])
@_isolated_weight_observer_test
def test_weight_observer_refuses_occupied_hook_without_replacing_it(fixture_imports, addon_package, hook):
    case = weight_boundary_model(fixture_imports, addon_package)
    getter, setter = (sys.getprofile, sys.setprofile) if hook == "profile" else (sys.gettrace, sys.settrace)
    previous = getter()

    def occupied(*_args):
        return None

    setter(occupied)
    try:
        with pytest.raises(RuntimeError, match="unused profiling/trace boundary"), case.observer:
            pytest.fail("Observer replaced an occupied hook")
        assert getter() is occupied and case.events == []
    finally:
        setter(previous)
    assert sys.getprofile() is None and sys.gettrace() is None


def test_weight_diagnostics_retain_exact_changed_F32_and_header_paths_without_mutating_inputs(fixture_imports):
    script = importlib.import_module("scripts.blender_weight_edit_guard_smoke")
    before = {"object": ["Object", "Target", 100, 200, 1, False, False],
              "memberships": [[[0, "0000803e"], [1, "0000803e"]]]}
    after = {"object": ["Object", "Target", 100, 200, 1, False, True],
             "memberships": [[[0, "0000003f"], [1, "0000803e"]]]}
    result = script.field_differences(before, after)
    assert result == {"entries": [
        {"path": "$.memberships[0][0][1]", "before": "0000803e", "after": "0000003f"},
        {"path": "$.object[6]", "before": False, "after": True}], "truncated": False}
    assert before["memberships"][0][0][1] == "0000803e" and before["object"][6] is False
    assert script.nonmemberships(before) != script.nonmemberships(after)
    assert script.nonmemberships(before) == {"object": before["object"]}


def test_weight_diagnostics_bound_only_the_diff_list_and_retain_complete_shape_changes(fixture_imports):
    script = importlib.import_module("scripts.blender_weight_edit_guard_smoke")
    before, after = {"rows": [0, 0, 0]}, {"rows": [1, 2, 3]}
    result = script.field_differences(before, after, limit=2)
    assert result == {"entries": [{"path": "$.rows[0]", "before": 0, "after": 1},
                                  {"path": "$.rows[1]", "before": 0, "after": 2}], "truncated": True}
    assert before == {"rows": [0, 0, 0]} and after == {"rows": [1, 2, 3]}
    assert script.field_differences({"roles": []}, {"roles": [1]}) == {
        "entries": [{"path": "$.roles", "before": [], "after": [1]}], "truncated": False}
    assert script.field_differences(before, before) == {"entries": [], "truncated": False}


@pytest.mark.parametrize("limit", [True, False, 0, -1, 129, 2., None])
def test_weight_diagnostics_reject_invalid_diff_budgets(fixture_imports, limit):
    script = importlib.import_module("scripts.blender_weight_edit_guard_smoke")
    with pytest.raises(AssertionError):
        script.field_differences({"users": 1}, {"users": 2}, limit=limit)


def test_populated_geometry_fixture_captures_real_data_before_pending_raw_setup():
    tree = ast.parse((ROOT / "scripts" / "blender_geometry_preview_smoke.py").read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    direct = {node.args[0].value: node.lineno for node in calls
              if isinstance(node.func, ast.Attribute) and node.func.attr == "dispatch"
              and node.args and isinstance(node.args[0], ast.Constant)
              and node.args[0].value in {"task.plan.set", "task.plan.capture", "task.plan.enforce"}}
    pending = next(node.lineno for node in calls
                   if isinstance(node.func, ast.Attribute) and node.func.attr == "hide_set")
    assert direct["task.plan.set"] < direct["task.plan.capture"] < direct["task.plan.enforce"] < pending
    source = ast.unparse(tree)
    assert "CAPTURE_FIELDS = ('mesh_geometry', 'material_slots', 'animation')" in source
    assert "protected_mesh.from_pydata" in source and "protected_mesh.materials.append(material)" in source
    assert "evidence_cache[store.baseline['snapshot_id']]" in source
    assert "actual is cached_record and actual == cached_value" in source
    assert "if cached or actual is not None:" in source
    assert "compare_data('after_image_data_compare', 'unchanged_within_scope')" in source
    assert "negative_protected_controls()" in source
    assert "'material_slots'" in source and "slot.link" in source
    assert not any(isinstance(node, ast.Attribute) and node.attr in {"ui_type", "keyframe_insert"}
                   for node in ast.walk(tree))


@pytest.fixture
def populated_geometry_helpers():
    tree = ast.parse((ROOT / "scripts" / "blender_geometry_preview_smoke.py").read_text())
    wanted = {"digest", "selected_authored", "raw_diagnostic", "checked_observation"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    assert {node.name for node in nodes} == wanted
    import hashlib
    import json
    namespace = {"hashlib": hashlib, "json": json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "owned-geometry-oracle", "exec"), namespace)
    value = {"target": {"vertices": ["target-f32"], "channels": ["static"]},
             "protected": {"identity": ["protected", 1], "mesh": {"vertices": ["protected-f32"]},
                           "visibility": {"hide_viewport": False}},
             "actor": {"identity": ["actor", 2], "channels": {"location": ["pending-raw"]}},
             "action": {"keys": ["authored-key"]}, "material": {"binding": 3},
             "raw_selected": ["selected-hidden"], "frame": [1, 0.]}
    return NS(**namespace, value=value)


def test_populated_geometry_oracle_distinguishes_authored_scope_from_idle_raw_state(populated_geometry_helpers):
    from copy import deepcopy
    case = populated_geometry_helpers
    after = deepcopy(case.value)
    after["actor"]["channels"]["location"] = ["evaluated-raw"]
    after["raw_selected"] = []
    proof = {}
    row = case.checked_observation(proof, "generic_compare", case.value, after)
    assert row["selected_authored_equal"] and not row["raw_equal"]
    assert row["raw_preservation_required"] is False
    assert proof["api_observations"][0]["raw_before"] != proof["api_observations"][0]["raw_after"]


@pytest.mark.parametrize("field", ["target", "protected", "action", "material"])
def test_populated_geometry_oracle_cannot_pass_a_changed_requested_field(populated_geometry_helpers, field):
    from copy import deepcopy
    case = populated_geometry_helpers
    after = deepcopy(case.value)
    if field == "protected":
        after[field]["mesh"]["vertices"] = ["manual-vertex"]
    else:
        after[field] = {"changed": True}
    proof = {}
    with pytest.raises(AssertionError, match="requested authored field"):
        case.checked_observation(proof, "compare_changed", case.value, after)
    assert proof["api_observations"][0]["selected_authored_equal"] is False
    assert proof["api_observations"][0]["selected_before_sha256"] != proof["api_observations"][0]["selected_after_sha256"]


def test_populated_geometry_oracle_still_requires_immediate_geometry_raw_preservation(populated_geometry_helpers):
    from copy import deepcopy
    case = populated_geometry_helpers
    after = deepcopy(case.value)
    after["raw_selected"] = []
    proof = {}
    with pytest.raises(AssertionError, match="immediate geometry-call raw diagnostic"):
        case.checked_observation(proof, "registered_start", case.value, after, raw_required=True)
    assert proof["api_observations"][0]["raw_preservation_required"] is True


def test_populated_geometry_manual_controls_never_replace_baseline_or_run_an_inverse():
    tree = ast.parse((ROOT / "scripts" / "blender_geometry_preview_smoke.py").read_text())
    controls = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "negative_protected_controls")
    source = ast.unparse(controls)
    assert "co.x = 4.125" in source and "co.y = 21.0" in source
    assert "compare_data('manual_vertex_compare', 'changed')" in source
    assert "compare_data('manual_key_compare', 'changed')" in source
    assert "'scene.snapshot'" in source and "old_id not in evidence_cache" in source
    assert "'evicted_evidence_compare'" in source and "'INVALID_ARGUMENT'" in source
    assert not any(isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Attribute) and target.attr in {"baseline", "protection"}
        for target in node.targets) for node in ast.walk(controls))
    assert not any(isinstance(node, ast.Attribute) and node.attr in {
        "undo", "undo_last", "restore_last", "restore_operation", "frame_set"}
        for node in ast.walk(controls))


@pytest.mark.parametrize("width,height", [(1, 1), (3, 5), (257, 2)])
def test_large_native_save_png_streams_complete_rgba8_without_compression(monkeypatch, tmp_path, width, height):
    import struct
    import zlib

    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")
    path = tmp_path / "owned color.png"
    facts = script.write_large_png(path, width=width, height=height)
    raw = path.read_bytes()
    assert facts == {"bytes": len(raw), "sha256": script.hashlib.sha256(raw).hexdigest()}
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    offset, payloads, tags = 8, [], []
    while offset < len(raw):
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        tag = raw[offset + 4:offset + 8]
        payload = raw[offset + 8:offset + 8 + length]
        checksum = struct.unpack(">I", raw[offset + 8 + length:offset + 12 + length])[0]
        assert checksum == zlib.crc32(tag + payload) & 0xffffffff
        tags.append(tag)
        if tag == b"IHDR":
            assert struct.unpack(">IIBBBBB", payload) == (width, height, 8, 6, 0, 0, 0)
        if tag == b"IDAT":
            payloads.append(payload)
        offset += length + 12
    assert offset == len(raw) and tags[0] == b"IHDR" and tags[-1] == b"IEND"
    decoded = zlib.decompress(b"".join(payloads))
    assert len(decoded) == height * (1 + width * 4)
    for y in range(height):
        row = decoded[y * (1 + width * 4):(y + 1) * (1 + width * 4)]
        assert row[0] == 0
        for x in range(width):
            assert tuple(row[1 + x * 4:5 + x * 4]) == (
                x & 255, y & 255, (((x & 255) // 4) + y) & 255, (0, 64, 128, 255)[(x + y) & 3])


def test_large_native_save_png_refuses_existing_or_aliased_file(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")
    target = tmp_path / "existing.png"
    target.write_bytes(b"preserve")
    with pytest.raises(AssertionError):
        script.write_large_png(target, width=1, height=1)
    alias = tmp_path / "alias.png"
    alias.symlink_to(target)
    with pytest.raises(AssertionError):
        script.write_large_png(alias, width=1, height=1)
    assert target.read_bytes() == b"preserve"


def test_large_native_save_mode_uses_real_worker_and_registered_main_thread_timers():
    source = (ROOT / "scripts/blender_native_save_smoke.py").read_text()
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    main = ast.get_source_segment(source, functions["large_save_main"])
    worker = ast.get_source_segment(source, functions["large_save_worker"])
    assert 'threading.Thread(target=large_save_worker' in main
    assert 'bpy.app.timers.register(poll' in main and 'controller.observe()' in main
    assert '"127.0.0.1"' in ast.get_source_segment(source, next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LargeSaveClient"))
    forbidden = {"bpy", "runtime", "dispatch", "execute_request"}
    assert not ({node.id for node in ast.walk(functions["large_save_worker"]) if isinstance(node, ast.Name)} & forbidden)
    assert '.tick(' not in main + worker and '.dispatch(' not in main + worker
    assert 'checkpoint.list' in worker and 'jobs.inspect' in worker
    assert worker.index('"permission_denial"') < worker.index('control("arm")')
    assert 'declared_authored_projection_preserved' in main
    assert 'clear_owned_empty_sequence_editors' not in main + worker


def test_large_native_save_source_fingerprints_match_isolated_runner(monkeypatch):
    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")
    runner = importlib.import_module("scripts.run_blender_checks")
    assert script.LARGE_SOURCES == runner.NATIVE_SAVE_LARGE_SOURCES
    assert len(script.large_source_fingerprints()) == 21


def test_large_native_save_diagnostics_survive_product_record_removal(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")
    observed = {"worker_receipt": None}
    reader = NS(evidence=lambda: dict(observed))
    job = NS(job_id="job_" + "1" * 32)
    record = NS(job=job, origin=NS(resource_checks=({"actual": "resource facts"},)), reader=reader,
                native_started=True, native_returned=False, native_completed=False, native_interval_ms=None)
    jobs = NS(_save_records={1: record}, _save_retained={})
    controller = script.LargeSaveController(tmp_path, NS(jobs=jobs), {})
    controller.observe()
    # Product completion removes active records before the next fixture control.
    jobs._save_records.clear()
    observed["worker_receipt"] = {"status": "succeeded", "process_id": 42}
    controller.observe()
    diagnostic = controller.control("records", {"job_id": job.job_id})
    assert diagnostic["source_resources"] == [{"actual": "resource facts"}]
    assert diagnostic["reader_evidence"]["worker_receipt"] == {"status": "succeeded", "process_id": 42}
    # A different reader must never be silently adopted for the existing job.
    record.reader = NS(evidence=lambda: {})
    jobs._save_retained[job.job_id] = record
    with pytest.raises(AssertionError):
        controller.observe()


def test_large_native_save_manual_restore_preserves_intervening_owned_edit(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "bpy", ModuleType("bpy"))
    script = importlib.import_module("scripts.blender_native_save_smoke")
    jobs = NS(_save_records={}, _save_retained={})
    controller = script.LargeSaveController(tmp_path, NS(jobs=jobs), {})
    coordinate = NS(x=0.)
    controller.obj = NS(data=NS(vertices=[NS(co=coordinate)]))
    assert controller.control("manual_change", {}) == .125
    coordinate.x = .25
    with pytest.raises(AssertionError):
        controller.control("manual_restore", {})
    assert coordinate.x == .25
    coordinate.x = .125
    assert controller.control("manual_restore", {}) == {"restored": True}
    assert coordinate.x == 0.
def test_glb_fixture_import_has_no_native_or_product_imports(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    tree = ast.parse(Path(script.__file__).read_text())
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
        ("bpy", "blender_codex_bridge", "scripts")) for node in imports)
    assert not any(isinstance(node, ast.Import) and any(alias.name == "bpy" for alias in node.names)
                   for node in imports)
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_glb_fixture_direct_main_rejects_unowned_launch_before_work(fixture_imports, monkeypatch):
    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    monkeypatch.setattr(sys, "argv", ["blender", "--factory-startup"])
    with pytest.raises(AssertionError, match="isolated private interactive runner"):
        script.main()
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_glb_fixture_source_is_real_plan_with_shared_mesh_and_signed_zero(fixture_imports, addon_package):
    import struct

    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    planner = importlib.import_module(addon_package + ".asset_glb_import_plan")
    plan = planner.plan_glb(script.source_glb())
    assert len(plan.meshes) == 1 and len(plan.meshes[0].primitives) == 2
    assert [node.mesh_index for node in plan.nodes] == [0, 0, None]
    assert len(plan.materials) == 2 and all(m.alpha_mode == "OPAQUE" for m in plan.materials)
    assert [p.material_index for p in plan.meshes[0].primitives] == [1, 0]
    assert all(p.normals is None and p.texcoords is None for p in plan.meshes[0].primitives)
    assert [struct.pack("<f", v).hex() for v in plan.meshes[0].primitives[0].positions[0]] == [
        "00000080", "00000080", "00000000"]
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("method,elapsed", [("timer_short", .099), ("timer_long", .499)])
def test_glb_fixture_refuses_a_deferred_observation_before_its_actual_deadline(
    fixture_imports, monkeypatch, method, elapsed,
):
    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    fixture = script.Fixture.__new__(script.Fixture)
    fixture.returned_at = 10.
    failures, observations = [], []
    fixture.finish = lambda status, failure: failures.append((status, failure))
    fixture.observation = lambda *_args: observations.append(True)
    monkeypatch.setattr(script.time, "monotonic", lambda: 10. + elapsed)
    getattr(fixture, method)()
    assert len(failures) == 1 and failures[0][0] == 1 and observations == []
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("fault", ["source_drift", "write", "read", "print"])
def test_glb_fixture_finish_failure_retains_false_completion_and_exits_nonzero(
    fixture_imports, monkeypatch, fault,
):
    import copy

    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    helper = ModuleType("scripts.blender_artist_sidebar_smoke")

    def exit_process(status):
        raise SystemExit(status)

    helper.owned_process_exit = exit_process
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    fixture = script.Fixture.__new__(script.Fixture)
    fixture.started, fixture.root = 0., ROOT
    fixture.data = {"source_sha256": {"fixture": "a" * 64}, "schema": script.SCHEMA,
                    "profile": script.PROFILE, "completed": False, "version": [4, 5, 14],
                    "blender_version": "4.5.14 LTS", "build_hash": "62c1db4208e8",
                    "process_instance": "0" * 32, "process_id": 123,
                    "binary": {"path": "/owned/model", "sha256": "b" * 64}}
    writes = []

    def flush():
        writes.append(copy.deepcopy(fixture.data))
        if fault == "write" and len(writes) == 1:
            raise OSError("owned proof write failure")

    def read():
        if fault == "read":
            raise OSError("owned proof read failure")
        return b"synthetic finish-only proof; no native acceptance"

    fixture.flush, fixture.path = flush, NS(read_bytes=read)
    monkeypatch.setattr(script, "source_hashes", lambda _root:
                        {} if fault == "source_drift" else fixture.data["source_sha256"])
    if fault == "print":
        def failed_print(*_args, **_kwargs):
            raise OSError("owned marker write failure")
        monkeypatch.setattr(script, "print", failed_print, raising=False)
    with pytest.raises(SystemExit) as result:
        fixture.finish(0)
    assert result.value.code == 1
    assert fixture.data["completed"] is False and "finish_failure" in fixture.data
    assert writes[-1]["completed"] is False
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_glb_fixture_finish_does_not_overwrite_first_failure(fixture_imports, monkeypatch):
    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    helper = ModuleType("scripts.blender_artist_sidebar_smoke")
    helper.owned_process_exit = lambda status: (_ for _ in ()).throw(SystemExit(status))
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    fixture = script.Fixture.__new__(script.Fixture)
    fixture.started, fixture.root = 0., ROOT
    fixture.data = {"source_sha256": {"fixture": "a" * 64}}
    fixture.flush = lambda: None
    monkeypatch.setattr(script, "source_hashes", lambda _root: {})
    with pytest.raises(SystemExit) as result:
        fixture.finish(1, "first native failure")
    assert result.value.code == 1 and fixture.data["failure"] == "first native failure"
    assert "Source changed" in fixture.data["finish_failure"]
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_glb_fixture_records_bootstrap_refusal_before_rethrow(fixture_imports):
    import copy

    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    errors = importlib.import_module("blender_codex_bridge.errors")
    fixture = script.Fixture.__new__(script.Fixture)
    fixture.data = {"cases": []}
    writes = []
    fixture.flush = lambda: writes.append(copy.deepcopy(fixture.data))

    def refused(_name, _result):
        raise errors.BridgeError("NOT_IMPLEMENTED", "Actual binding refused",
                                 {"reason": "NATIVE_USED_FIELD_MISMATCH"})

    fixture.construct_case = refused  # Model only the outer report helper, never a native success.
    with pytest.raises(errors.BridgeError):
        fixture.run_case("success")
    assert writes[0] == {"cases": [{"name": "success", "phase": "bootstrap"}]}
    row = writes[-1]["cases"][0]
    assert row["status"] == "FAILED" and row["phase"] == "bootstrap"
    assert row["error"]["context"]["reason"] == "NATIVE_USED_FIELD_MISMATCH"
    assert "first_failure" in row
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_glb_fixture_retains_complete_rows_before_independent_oracle_refusal(fixture_imports):
    import copy

    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    fixture = script.Fixture.__new__(script.Fixture)
    result, writes = {"name": "success"}, []
    rows = {"mesh:0": {"coordinates": [["00000080", "00000080", "00000000"]]}}
    fixture.flush = lambda: writes.append(copy.deepcopy(result))

    def refused(_rows):
        raise AssertionError("first native conformance mismatch")

    fixture.verify_success = refused
    with pytest.raises(AssertionError, match="first native conformance mismatch"):
        fixture.verify_rows(result, rows)
    assert writes == [{"name": "success", "phase": "independent_verify", "owned_rows": rows}]
    assert fixture_imports.timers == [] and fixture_imports.events == []


@pytest.mark.parametrize("value", [False, True, 0, 1])
def test_glb_fixture_independently_preserves_boolean_socket_type(fixture_imports, value):
    from types import SimpleNamespace as NS

    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    socket = NS(type="BOOLEAN", identifier="Thin Wall", default_value=value)
    principled = NS(bl_idname="ShaderNodeBsdfPrincipled", name="Principled", location=[0., 0.],
                    width=240., mute=False, inputs=[socket])
    output = NS(bl_idname="ShaderNodeOutputMaterial", name="Output", location=[300., 0.],
                width=140., mute=False, inputs=[], is_active_output=True, target="ALL")
    link = NS(from_node=principled, from_socket=NS(identifier="BSDF"),
              to_node=output, to_socket=NS(identifier="Surface"))
    tree = NS(library=None, override_library=None, name="Shader Nodetree", session_uid=10,
              as_pointer=lambda: 1000, users=1, use_fake_user=False,
              bl_rna=NS(identifier="ShaderNodeTree"), nodes=[principled, output], links=[link])
    if type(value) is bool:
        row = script.tree_row(tree)
        assert row["nodes"][0]["inputs"] == [{"identifier": "Thin Wall", "type": "BOOLEAN", "default": [value]}]
    else:
        with pytest.raises(AssertionError):
            script.tree_row(tree)
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_glb_fixture_retains_the_actual_failed_deferred_snapshot(fixture_imports):
    import copy

    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    fixture = script.Fixture.__new__(script.Fixture)
    fixture.data, writes = {"observations": []}, []
    fixture.before_sentinel = {"coordinate": "00000000"}
    fixture.sentinel = lambda: {"coordinate": "00000080"}
    fixture.controllers = [(None, NS(environment=lambda _owned: {"frame": 1}), "stage")]
    fixture.owned = lambda *_args: {"mesh": {"coordinates": ["00000000"]}}
    fixture.frozen = {"sentinel": fixture.before_sentinel, "environment": {"frame": 1},
                      "owned": [{"mesh": {"coordinates": ["00000000"]}}]}
    fixture.flush = lambda: writes.append(copy.deepcopy(fixture.data))
    with pytest.raises(AssertionError, match="Declared data/context changed"):
        fixture.observation("timer_0_1", .1)
    sample = writes[-1]["observations"][0]
    assert sample["preserved"] is False and sample["phase"] == "timer_0_1"
    assert sample["snapshot"]["sentinel"] == {"coordinate": "00000080"}
    assert fixture_imports.timers == [] and fixture_imports.events == []


def test_glb_structural_literal_asset_independently_decodes_required_domains(fixture_imports, addon_package):
    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    planner = importlib.import_module(addon_package + ".asset_glb_import_plan")
    plan = planner.plan_glb(script.structure_source_glb())
    assert len(plan.meshes) == 1 and len(plan.materials) == 1 and len(plan.nodes) == 3
    first, second = plan.meshes[0].primitives
    assert first.material_index == second.material_index == 0
    assert first.normals is not None and second.normals is None
    assert first.texcoords is not None and second.texcoords is not None
    assert [node.mesh_index for node in plan.nodes] == [None, 0, 0]
    assert [node.parent_index for node in plan.nodes] == [None, 0, 0]
    for index, node in enumerate(plan.nodes):
        assert node.local_matrix == script.STRUCTURE_BASIS[index]
        assert node.world_matrix == script.STRUCTURE_WORLDS[index]
    assert fixture_imports.events == [] and fixture_imports.timers == []


@pytest.mark.parametrize("method,elapsed", [("timer_short", .099), ("timer_middle", .299), ("timer_long", .499)])
def test_glb_structure_requires_each_real_timer_deadline(fixture_imports, monkeypatch, method, elapsed):
    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    fixture = script.StructureFixture.__new__(script.StructureFixture)
    fixture.returned_at = 10.
    failed, observed = [], []
    fixture.finish = lambda *args: failed.append(args)
    fixture.observation = lambda *args: observed.append(args)
    monkeypatch.setattr(script.time, "monotonic", lambda: 10. + elapsed)
    getattr(fixture, method)()
    assert len(failed) == 1 and failed[0][0] == 1 and not observed
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_structure_pure_oracle_rejects_status_only_fake_success(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    with pytest.raises((AssertionError, KeyError)):
        script.validate_structure_transcript({"completed": True, "cases": [
            {"name": "success", "status": "CONSTRUCTED"}]})
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_structure_source_has_no_forbidden_context_or_importer_fallback(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    tree = ast.parse(Path(script.__file__).read_text())
    assert not any(isinstance(node, ast.Attribute) and node.attr in {
        "keyframe_insert", "ui_type", "gltf", "gltf2", "update_tag", "evaluated_depsgraph_get"}
        for node in ast.walk(tree))
    assert script.STRUCTURE_SCHEMA != script.SCHEMA and script.STRUCTURE_PROFILE != script.PROFILE
    assert script.STRUCTURE_MARKER != script.MARKER
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_structure_digest_refuses_fifo_symlink_and_replacement(tmp_path, fixture_imports, monkeypatch):
    script = importlib.import_module("scripts.blender_glb_stage_smoke")
    path = tmp_path / "ordinary"
    with path.open("wb") as stream:
        stream.write(b"source witness")
    link = tmp_path / "symlink"
    link.symlink_to(path)
    with pytest.raises(AssertionError):
        script.file_digest(link)
    fifo = tmp_path / "pipe"
    script.os.mkfifo(fifo)
    with pytest.raises(AssertionError):
        script.file_digest(fifo)
    original = script.os.read
    fired = []
    def replaced(descriptor, count):
        raw = original(descriptor, count)
        if not fired:
            fired.append(True)
            other = tmp_path / "replacement"
            with other.open("wb") as stream:
                stream.write(b"same size data")
            script.os.replace(other, path)
        return raw
    monkeypatch.setattr(script.os, "read", replaced)
    with pytest.raises(AssertionError):
        script.file_digest(path)


@pytest.mark.parametrize("raw", [b"[]", b"true", b"1", b'"truthy"', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_glb_runtime_strict_json_is_cold_and_rejects_nonobject_duplicate_nonfinite(fixture_imports, raw):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    with pytest.raises((AssertionError, ValueError)):
        script.decode(raw)
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_runtime_json_depth_and_size_are_bounded(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    for raw in [b'{"x":'+b'['*49+b'0'+b']'*49+b'}', b'x'*(script.MAX_EVIDENCE+1)]:
        with pytest.raises((AssertionError, ValueError)):
            script.decode(raw)
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_runtime_status_only_marker_cannot_qualify_a_transcript(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    with pytest.raises((AssertionError, KeyError)):
        script.validate_runtime_transcript({"schema": script.SCHEMA, "profile": script.PROFILE, "completed": True,
            "cases": [{"id": value, "status": "VERIFIED"} for value in script.SCENARIOS]})
    assert len(script.SCENARIOS) == 17 and len(set(script.SCENARIOS)) == 17
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_runtime_literal_asset_is_independent_and_keeps_uv_normal_auto_trs(fixture_imports, addon_package):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    planner = importlib.import_module(addon_package+".asset_glb_import_plan")
    plan = planner.plan_glb(script.literal_source())
    assert len(plan.nodes) == 3 and len(plan.meshes) == 1 and len(plan.materials) == 1
    assert list(plan.required_accepted_losses) == script.LOSSES
    assert plan.summary()["normal_conversion"]["authored_normal_corners"] == 3
    assert plan.summary()["normal_conversion"]["geometric_auto_corners"] == 3
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_runtime_fixture_has_no_private_controller_or_manual_tick_fallback(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    tree = ast.parse(inspect.getsource(script))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    names = {node.func.attr for node in calls if isinstance(node.func, ast.Attribute)}
    assert not {"tick", "advance", "perform", "keyframe_insert"} & names
    assert "PrivateGLBController" not in inspect.getsource(script)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            assert not any(isinstance(target, ast.Attribute) and target.attr in {"ui_type", "type"} for target in targets)
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_runtime_tcp_abort_closes_real_owner_socket_and_reconnects():
    """Ordinary loopback TCP behavior only; no modeled native acceptance."""
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.settimeout(2.)
    client = script.TCPClient(listener.getsockname()[1], [])
    first, address = listener.accept()
    first.settimeout(2.)
    old_instance = client.connection_instance
    try:
        assert address[0] == "127.0.0.1" and client.socket.fileno() >= 0
        client.socket.sendall(b"owned socket")
        assert first.recv(64) == b"owned socket"
        client.abort()
        assert client.socket.fileno() == -1 and first.recv(1) == b""
        client.reconnect()
        second, address = listener.accept()
        try:
            second.settimeout(2.)
            assert address[0] == "127.0.0.1" and client.connection_instance != old_instance
            client.socket.sendall(b"new owner")
            assert second.recv(64) == b"new owner"
        finally:
            second.close()
    finally:
        client.close()
        first.close()
        listener.close()


def test_glb_runtime_reacquires_fixture_wrappers_without_reading_pre_undo_rna(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    fixture = object.__new__(script.RuntimeFixture)
    fixture.protected_names = {family: [family+" retained"] for family in ("objects", "meshes", "materials", "armatures", "actions", "scenes", "images", "cameras", "lights", "worlds", "collections")}
    groups = {family: {names[0]: NS(fresh=True)} for family, names in fixture.protected_names.items()}
    fields = {"destination": "scenes", "sentinel_mesh": "meshes", "sentinel_material": "materials", "sentinel": "objects",
        "sentinel_shared": "objects", "rig": "armatures", "rig_object": "objects", "action": "actions", "populated_scene": "scenes",
        "active_empty": "objects", "protected_image": "images", "other_collection": "collections"}
    fixture.fixture_names = {field: family+" retained" for field, family in fields.items()}
    for kind in ("scene_identity", "master_identity", "context"):
        groups["scenes"]["Runtime Fixture "+kind] = NS(fresh=True)
    for kind, family, suffix in (("collection", "collections", ""), ("mesh", "meshes", ".M0"), ("material", "materials", ".P0"), ("object", "objects", ".O0")):
        groups[family]["Runtime Collision "+kind+suffix] = NS(fresh=True)
    class InvalidRNA:
        def __getattribute__(self, field):
            pytest.fail("Read an RNA wrapper retained before undo/load: "+field)
    fixture.protected_ids = InvalidRNA()
    for field in fields:
        setattr(fixture, field, InvalidRNA())
    preferences = NS(fresh=True)
    fixture.bpy = NS(data=NS(**groups), context=NS(preferences=NS(addons={"blender_codex_bridge": NS(preferences=preferences)})))
    observed = []
    fixture.fresh_observer = lambda: observed.append("new binding")
    fixture.reacquire_after_invalidation()
    assert observed == ["new binding"] and fixture.prefs is preferences
    assert all(getattr(fixture, field) is groups[family][fixture.fixture_names[field]] for field, family in fields.items())
    assert all(ref.fresh is True for refs in fixture.protected_ids.values() for ref in refs)
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_runtime_logical_comparison_preserves_authored_bits_and_only_ignores_derived_matrices(fixture_imports):
    import copy

    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    value = {"protected": {"objects": [{"channels": {"location": ["00000000", "80000000", "3f800000"]},
        "basis": ["3f800000"], "parent_inverse": ["3f800000"], "local": ["3f800000"], "world": ["3f800000"],
        "pose_bones": [{"basis": ["3f800000"], "matrix": ["3f800000"]}]}]}, "owned": {}}
    cached = copy.deepcopy(value)
    cached["protected"]["objects"][0]["world"] = ["00000000"]
    cached["protected"]["objects"][0]["pose_bones"][0]["matrix"] = ["00000000"]
    assert script.logical_snapshot(cached) == script.logical_snapshot(value)
    for field in ("channels", "basis", "parent_inverse"):
        changed = copy.deepcopy(cached)
        changed["protected"]["objects"][0][field] = []
        assert script.logical_snapshot(changed) != script.logical_snapshot(value)
    assert value["protected"]["objects"][0]["world"] == ["3f800000"]
    assert fixture_imports.events == [] and fixture_imports.timers == []


def test_glb_runtime_shared_json_roundtrip_is_exact_and_keeps_large_prefixes_bounded():
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    source = {"records": [{"prefix": [{"index": index, "component": ["00000000", "0000803f"],
            "operation": "WRITE_NORMALS", "role": "mesh:0", "entry": "Mesh.normals_split_custom_set",
            "entered": True, "returned": True, "post_return_stop_checked": True,
            "started_monotonic": 1., "returned_monotonic": 1.001, "seconds": .001}
                                  for index in range(count)], "response_id": str(count)} for count in range(64)],
              "literal_ref_key": {"ref": "not a table reference"}, "negative_zero": -0.0}
    packed = script.encode(script.pack_proof(source))
    decoded = script.decode(packed)
    assert decoded == source and script.encode(decoded) == script.encode(source)
    assert len(packed) < len(script.encode(source))


@pytest.mark.parametrize("fault", ["hash", "reference", "node_kind", "object_duplicate", "branch_budget", "nonfinite", "extra"])
def test_glb_runtime_shared_json_never_trusts_hashes_refs_or_shapes(fault):
    import hashlib

    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    packed = script.pack_proof({"value": [1, 2]})
    if fault == "hash":
        packed["table"][next(iter(packed["table"]))]["extra"] = True
    elif fault == "reference":
        packed["root"] = {"ref": "0"*64}
    elif fault == "extra":
        packed["extra"] = True
    else:
        node = {"node_kind": {"kind": "UNKNOWN"},
            "object_duplicate": {"kind": "object", "pairs": [["x", 1], ["x", 2]]},
            "branch_budget": {"kind": "branch", "children": []},
            "nonfinite": {"kind": "object", "pairs": [["x", float("nan")]]}}[fault]
        if fault == "nonfinite":
            with pytest.raises((AssertionError, ValueError)):
                script.encode(script.pack_proof(node))
            return
        key = hashlib.sha256(json.dumps(node, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        packed["table"][key] = node
        packed["root"] = {"ref": key}
    with pytest.raises((AssertionError, ValueError, KeyError)):
        script.unpack_proof(packed)


def test_glb_runtime_bounded_file_refuses_fifo_symlink_and_descriptor_replacement(tmp_path, monkeypatch):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    original = tmp_path / "report.json"
    original.write_bytes(b'{"actual":true}')
    symlink = tmp_path / "link.json"
    symlink.symlink_to(original)
    fifo = tmp_path / "pipe.json"
    os.mkfifo(fifo)
    for path in (symlink, fifo):
        with pytest.raises(AssertionError):
            script.bounded_file(path)
    assert script.bounded_file(original) == b'{"actual":true}'
    original_os = script.os
    changed = False
    def read(descriptor, count):
        nonlocal changed
        result = original_os.read(descriptor, count)
        if not changed:
            changed = True
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(b'{"actual":true}')
            replacement.replace(original)
        return result
    proxy = NS(**{name: getattr(original_os, name) for name in ("open", "close", "fstat", "O_RDONLY", "O_NOFOLLOW", "O_NONBLOCK")}, read=read)
    monkeypatch.setattr(script, "os", proxy)
    with pytest.raises(AssertionError):
        script.bounded_file(original)


def test_glb_runtime_standalone_entry_resolves_owned_helper_without_repository_path_or_module_cache(tmp_path):
    bootstrap = r"""
import json
import runpy
import sys
from pathlib import Path

target = Path(sys.argv[1]).resolve(strict=True)
root = target.parents[1]
assert root not in {Path(item).resolve() for item in sys.path}
assert not any(name == 'scripts' or name.startswith('scripts.') for name in sys.modules)
assert 'bpy' not in sys.modules
before_path = tuple(sys.path)
runpy.run_path(str(target), run_name='_cold_glb_runtime_fixture')
assert tuple(sys.path) == before_path
assert not any(name == 'scripts' or name.startswith('scripts.') for name in sys.modules)
assert 'bpy' not in sys.modules
try:
    runpy.run_path(str(target), run_name='__main__')
except AssertionError as error:
    assert str(error) == 'Use the isolated private interactive runner', str(error)
else:
    raise AssertionError('Unowned standalone invocation passed the canonical ownership check')
helper = sys.modules['scripts.blender_glb_stage_smoke']
assert Path(helper.__file__).resolve(strict=True) == root / 'scripts/blender_glb_stage_smoke.py'
assert 'bpy' not in sys.modules
assert not any(name == 'blender_codex_bridge' or name.startswith('blender_codex_bridge.')
               for name in sys.modules)
print(json.dumps({'canonical_helper_resolved': True, 'unowned_entry_refused': True,
                  'bpy_unloaded': True, 'product_unloaded': True}))
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", bootstrap,
        str(ROOT / "scripts/blender_glb_stage_runtime_smoke.py")], cwd=tmp_path,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (result.stdout[-4096:], result.stderr[-4096:])
    assert json.loads(result.stdout) == {"canonical_helper_resolved": True, "unowned_entry_refused": True,
        "bpy_unloaded": True, "product_unloaded": True}


@pytest.mark.parametrize("outcome", ["enabled", "cancelled", "missing_entry", "missing_preferences", "auto_start"])
def test_glb_runtime_setup_requires_canonical_enable_before_live_preferences_and_product_work(
    fixture_imports, addon_package, monkeypatch, outcome
):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    module = sys.modules["blender_codex_bridge.permissions"]
    monkeypatch.setattr(module, "PREFERENCE_PROPERTIES", permissions.PREFERENCE_PROPERTIES, raising=False)
    events, addons = [], {}
    prefs = NS(auto_start=outcome == "auto_start")

    class Preferences:
        use_preferences_save = True
        @property
        def addons(self):
            assert events == ["canonical_addon_enable"]
            events.append("live_addons")
            return addons

    preferences = Preferences()
    def enable(*, module):
        assert module == "blender_codex_bridge" and preferences.use_preferences_save is False
        assert events == [] and addons == {}
        events.append("canonical_addon_enable")
        if outcome == "cancelled":
            return {"CANCELLED"}
        if outcome != "missing_entry":
            addons[module] = NS(preferences=None if outcome == "missing_preferences" else prefs)
        return {"FINISHED"}

    product = object()
    def get_runtime():
        assert events == ["canonical_addon_enable", "live_addons"]
        assert addons["blender_codex_bridge"].preferences is prefs and prefs.auto_start is False
        events.append("get_runtime")
        return product

    class FirstAuthoringBoundary(Exception):
        pass

    class Folder:
        def __truediv__(self, name):
            assert name == "approved GLB source"
            def mkdir(*, mode):
                assert mode == 0o700 and events == ["canonical_addon_enable", "live_addons", "get_runtime"]
                events.append("first_authoring_boundary")
                raise FirstAuthoringBoundary
            return NS(mkdir=mkdir)

    monkeypatch.setattr(sys.modules["blender_codex_bridge.runtime"], "get_runtime", get_runtime)
    fixture = script.RuntimeFixture.__new__(script.RuntimeFixture)
    fixture.bpy = NS(context=NS(preferences=preferences), ops=NS(preferences=NS(addon_enable=enable)))
    fixture.folder = Folder()
    if outcome == "enabled":
        with pytest.raises(FirstAuthoringBoundary):
            fixture.setup()
        assert fixture.runtime is product and fixture.prefs is prefs
        assert events == ["canonical_addon_enable", "live_addons", "get_runtime", "first_authoring_boundary"]
        for grant in script.CREATE_GRANTS:
            assert getattr(prefs, permissions.PREFERENCE_PROPERTIES[permissions.Permission(grant)]) is True
        assert prefs.allow_execute_python is prefs.allow_delete_objects is prefs.allow_save_project is False
    else:
        with pytest.raises(AssertionError):
            fixture.setup()
        assert events == (["canonical_addon_enable"] if outcome == "cancelled" else
                          ["canonical_addon_enable", "live_addons"])
        assert "runtime" not in vars(fixture)
        assert set(vars(prefs)) == {"auto_start"}
    assert preferences.use_preferences_save is False
    assert fixture_imports.events == [] and fixture_imports.timers == []


@pytest.mark.parametrize("change", [None, "missing", "extra", "name", "index", "lock", "weight", "second_group_weight", "missing_vertex", "bool_index", "float_index", "int_lock", "bool_membership_index"])
def test_glb_runtime_shared_mesh_groups_require_both_complete_definitions(fixture_imports, change):
    import copy
    import importlib
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    helper = importlib.import_module("scripts.blender_glb_stage_smoke")
    groups = {"object_identity": {"uid": 41, "pointer": 410}, "groups": [
        {"index": 0, "name": "Runtime Protected Group", "lock_weight": False},
        {"index": 1, "name": "Runtime Shared Group", "lock_weight": False}],
        "memberships": [[[0, helper.numeric((weight,))[0]]] for weight in (.25, .75, .75)]}
    if change == "missing":
        groups["groups"].pop()
    elif change == "extra":
        groups["groups"].append({"index": 2, "name": "Extra", "lock_weight": False})
    elif change in {"name", "index", "lock"}:
        groups["groups"][1][{"name": "name", "index": "index", "lock": "lock_weight"}[change]] = {
            "name": "Renamed", "index": 0, "lock": True}[change]
    elif change == "weight":
        groups["memberships"][0][0][1] = helper.numeric((.5,))[0]
    elif change == "second_group_weight":
        groups["memberships"][0].append([1, helper.numeric((.5,))[0]])
    elif change == "missing_vertex":
        groups["memberships"].pop()
    if change == "bool_index":
        groups["groups"][0]["index"] = False
    elif change == "float_index":
        groups["groups"][0]["index"] = 0.
    elif change == "int_lock":
        groups["groups"][0]["lock_weight"] = 0
    elif change == "bool_membership_index":
        groups["memberships"][0][0][0] = False
    before = copy.deepcopy(groups)
    if change is None:
        script.assert_shared_group_fixture(groups)
    else:
        with pytest.raises(AssertionError):
            script.assert_shared_group_fixture(groups)
    assert groups == before
    assert fixture_imports.events == [] and fixture_imports.timers == []


@pytest.mark.parametrize("event", ["c_call", "c_return", "c_exception"])
def test_glb_runtime_profile_ignores_c_events_before_frame_or_thread_access(fixture_imports, monkeypatch, event):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    class ForeignFrame:
        def __getattribute__(self, _name):
            pytest.fail("C event accessed frame data")
    monkeypatch.setattr(script.threading, "current_thread", lambda: pytest.fail("C event dispatched thread"))
    fixture = object.__new__(script.RuntimeFixture)
    assert fixture.profile(ForeignFrame(), event, object()) is None


def test_glb_runtime_profile_retains_python_request_and_native_evidence_trace(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    fixture = object.__new__(script.RuntimeFixture)
    fixture.current_requests, fixture.watch = [], None
    fixture.request_lifetimes, fixture.start_acceptances, fixture.request_access = {}, {}, {}
    fixture.pending_request_gates = {}
    fixture.request_read_effects, fixture.marker_entries, fixture.histories = {}, {}, {}
    fixture.data = {"executor_history_frames": []}
    request = NS(id="preview-model", method="asset.glb_stage_preview", _lifecycle=object())
    def frame(path, name, **values):
        return NS(f_code=NS(co_filename="/owned/addon/blender_codex_bridge/" + path, co_name=name), f_locals=values)
    fixture.profile(frame("server.py", "submit", request=request), "return", None)
    assert fixture.request_lifetimes == {request.id: request._lifecycle}
    invocation = frame("executor.py", "_invoke_owned", request=request, undo_boundary=True, handler_entered=True, history_record=None)
    fixture.profile(invocation, "call", None)
    assert fixture.current_requests == [request.id]
    cell = {"kind": "VERTEX_GROUP_READ", "attempts_entered": 1}
    fixture.profile(frame("glb_stage_protected_mesh.py", "enter", cell=cell), "call", None)
    fixture.profile(frame("checkpoints.py", "capture_job_markers"), "call", None)
    counts = {"get:data": {"entered": 2, "returned": 1}}
    snapshots = []
    def snapshot():
        snapshots.append("snapshot")
        return counts
    fixture.profile(frame("glb_stage_profile.py", "_access", self=NS(_runtime_gate=NS(snapshot=snapshot))), "return", None)
    fixture.profile(invocation, "return", {"preview_id": "pure-model"})
    assert fixture.current_requests == []
    assert snapshots == ["snapshot"] and fixture.request_access == {request.id: counts}
    assert fixture.request_read_effects == {request.id: [cell]}
    assert fixture.request_read_effects[request.id][0] is not cell
    assert fixture.marker_entries == {request.id: 1}
    history = fixture.histories[request.id]
    assert history["request_id"] == request.id and history["method"] == request.method
    assert history["checkpoint_entered"] is True and history["handler_entered"] is True
    assert history["raw_history"] is None and history["accepted_result"] is None
    assert fixture.data["executor_history_frames"] == [history]


def test_glb_runtime_profile_retains_worker_lifecycle_before_main_thread_filter(fixture_imports, monkeypatch):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    fixture = object.__new__(script.RuntimeFixture)
    fixture.request_lifetimes = {}
    request = NS(id="worker-submit", _lifecycle=object())
    frame = NS(f_code=NS(co_filename="/owned/blender_codex_bridge/server.py", co_name="submit"), f_locals={"request": request})
    monkeypatch.setattr(script.threading, "current_thread", lambda: object())
    fixture.profile(frame, "return", None)
    assert fixture.request_lifetimes == {request.id: request._lifecycle}


def glb_runtime_shader_fixture(*, world=False, packed=False):
    """Independent fixed raw RNA shape, with no actual Blender construction."""
    def identity(name, uid, cls):
        return dict(library=None, override_library=None, name=name, session_uid=uid,
                    as_pointer=lambda: uid * 10, users=1, use_fake_user=False, bl_rna=NS(identifier=cls))
    image = NS(**identity("Packed", 30, "Image")) if packed else None
    source = NS(bl_idname="ShaderNodeBackground" if world else "ShaderNodeBsdfPrincipled", name="Source",
                location=[-0., 0.], width=240., mute=False,
                inputs=[NS(type="BOOLEAN", identifier="Boolean", default_value=True),
                        NS(type="VALUE", identifier="Float", default_value=-0.),
                        NS(type="RGBA", identifier="Color", default_value=[1., 0., 0., 1.])])
    output = NS(bl_idname="ShaderNodeOutputWorld" if world else "ShaderNodeOutputMaterial", name="Output",
                location=[300., 0.], width=140., mute=False, inputs=[], is_active_output=True, target="ALL")
    nodes = [source, output]
    links = [NS(from_node=source, from_socket=NS(identifier="Background" if world else "BSDF"),
                to_node=output, to_socket=NS(identifier="Surface"))]
    if packed:
        texture = NS(bl_idname="ShaderNodeTexImage", name="Packed texture", location=[-300., 0.], width=220., mute=False,
                     inputs=[NS(type="VECTOR", identifier="Vector", default_value=[0., -0., 0.])], image=image,
                     interpolation="Linear", projection="FLAT", projection_blend=0., extension="REPEAT")
        nodes.append(texture)
        links.append(NS(from_node=texture, from_socket=NS(identifier="Color"),
                        to_node=source, to_socket=NS(identifier="Base Color")))
    tree = NS(**identity("Tree", 20, "ShaderNodeTree"), nodes=nodes, links=links)
    material = NS(**identity("Material", 10, "Material"), diffuse_color=[.5, .5, .5, 1.],
                  use_backface_culling=False, use_nodes=True, node_tree=tree)
    return NS(tree=tree, material=material, image=image, source=source, output=output)


@pytest.mark.parametrize("world,packed", [(False, False), (False, True), (True, False)])
def test_glb_runtime_protected_tree_oracle_observes_each_exact_fixture_graph(fixture_imports, world, packed):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    model = glb_runtime_shader_fixture(world=world, packed=packed)
    row = script.protected_tree_row(model.tree, image=model.image, world=world)
    assert len(row["nodes"]) == (3 if packed else 2) and len(row["links"]) == (2 if packed else 1)
    source = next(node for node in row["nodes"] if node["name"] == "Source")
    assert source["location"] == ["00000080", "00000000"]
    assert source["inputs"][0]["default"] == [True]
    assert source["inputs"][1]["default"] == ["00000080"]
    assert next(node for node in row["nodes"] if node["name"] == "Output")["active_output"] is True
    if packed:
        texture = next(node for node in row["nodes"] if node["type"] == "ShaderNodeTexImage")
        assert texture["image"]["uid"] == 30
        assert (texture["interpolation"], texture["projection"], texture["projection_blend"], texture["extension"]) == (
            "Linear", "FLAT", "00000000", "REPEAT")
        assert script.protected_material_row(model.material, image=model.image)["tree"] == row


@pytest.mark.parametrize("fault", ["extra_node", "missing_node", "duplicate_kind", "extra_link", "missing_link", "wrong_socket", "wrong_target", "other_image", "wrong_profile", "boolean_as_integer"])
def test_glb_runtime_protected_tree_oracle_rejects_unexpected_graphs_and_bindings(fixture_imports, fault):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    model = glb_runtime_shader_fixture(packed=True)
    world = False
    if fault == "extra_node":
        model.tree.nodes.append(model.source)
    elif fault == "missing_node":
        model.tree.nodes.pop()
    elif fault == "duplicate_kind":
        model.tree.nodes[0] = model.output
    elif fault == "extra_link":
        model.tree.links.append(model.tree.links[0])
    elif fault == "missing_link":
        model.tree.links.pop()
    elif fault == "wrong_socket":
        model.tree.links[-1].from_socket.identifier = "Alpha"
    elif fault == "wrong_target":
        model.tree.links[-1].to_socket.identifier = "Roughness"
    elif fault == "other_image":
        model.tree.nodes[-1].image = NS(session_uid=30)
    elif fault == "wrong_profile":
        world = True
    else:
        model.source.inputs[0].default_value = 1
    with pytest.raises(AssertionError):
        script.protected_tree_row(model.tree, image=model.image, world=world)


def test_glb_runtime_protected_tree_oracle_keeps_binding_and_authored_socket_bits(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    model = glb_runtime_shader_fixture(packed=True)
    baseline = script.protected_tree_row(model.tree, image=model.image)
    for owner, field, changed in ((model.source.inputs[1], "default_value", 0.),
                                  (model.output, "is_active_output", False),
                                  (model.output, "target", "CYCLES"),
                                  (model.tree.nodes[-1], "projection_blend", .5),
                                  (model.tree.nodes[-1], "extension", "CLIP"),
                                  (model.tree.nodes[-1], "interpolation", "Closest")):
        original = getattr(owner, field)
        setattr(owner, field, changed)
        assert script.protected_tree_row(model.tree, image=model.image) != baseline
        setattr(owner, field, original)
    assert script.protected_tree_row(model.tree, image=model.image) == baseline


def glb_runtime_profile_model(script):
    fixture = object.__new__(script.RuntimeFixture)
    fixture.current_requests, fixture.watch, fixture.pending_request_gates = [], None, {}
    fixture.request_lifetimes, fixture.start_acceptances, fixture.request_access = {}, {}, {}
    fixture.request_read_effects, fixture.marker_entries, fixture.histories = {}, {}, {}
    fixture.data = {"executor_history_frames": []}
    return fixture


def glb_runtime_profile_frame(path, name, **values):
    return NS(f_code=NS(co_filename="/owned/blender_codex_bridge/" + path, co_name=name), f_locals=values)


class GLBProfileCounterGate:
    def __init__(self):
        self.counts, self.snapshots = {"get:data": {"entered": 0, "returned": 0}}, 0
    def snapshot(self):
        self.snapshots += 1
        return {key: dict(value) for key, value in self.counts.items()}


@pytest.mark.parametrize("terminal", ["success", "native_error", "timeout", "disconnected", "undelivered", "cancelled"])
def test_glb_runtime_profile_materializes_one_terminal_snapshot_without_caller_delivery(fixture_imports, terminal):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    fixture, gate = glb_runtime_profile_model(script), GLBProfileCounterGate()
    request = NS(id=terminal, method="asset.glb_stage_preview")
    invocation = glb_runtime_profile_frame("executor.py", "_invoke_owned", request=request)
    access = glb_runtime_profile_frame("glb_stage_profile.py", "_access", self=NS(_runtime_gate=gate))
    fixture.profile(invocation, "call", None)
    for index in range(1000):
        gate.counts["get:data"]["entered"] += 1
        if terminal != "native_error" or index < 999:
            gate.counts["get:data"]["returned"] += 1
        fixture.profile(access, "return", None)
    assert gate.snapshots == 0 and fixture.request_access == {}
    fixture.profile(invocation, "return", {} if terminal == "success" else None)
    assert gate.snapshots == 1
    assert fixture.request_access == {terminal: {"get:data": {"entered": 1000, "returned": 999 if terminal == "native_error" else 1000}}}
    assert fixture.pending_request_gates == {} and fixture.current_requests == []


def test_glb_runtime_profile_freezes_shared_gate_ancestor_before_nested_request(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    fixture, gate = glb_runtime_profile_model(script), GLBProfileCounterGate()
    outer = glb_runtime_profile_frame("executor.py", "_invoke_owned", request=NS(id="outer", method="asset.glb_stage_preview"))
    nested = glb_runtime_profile_frame("executor.py", "_invoke_owned", request=NS(id="nested", method="asset.glb_stage_preview"))
    access = glb_runtime_profile_frame("glb_stage_profile.py", "_access", self=NS(_runtime_gate=gate))
    fixture.profile(outer, "call", None)
    gate.counts["get:data"].update(entered=1, returned=1)
    fixture.profile(access, "return", None)
    fixture.profile(nested, "call", None)
    assert fixture.request_access["outer"] == {"get:data": {"entered": 1, "returned": 1}}
    gate.counts["get:data"].update(entered=3, returned=3)
    fixture.profile(access, "return", None)
    fixture.profile(nested, "return", None)
    fixture.profile(outer, "return", None)
    assert fixture.request_access == {"outer": {"get:data": {"entered": 1, "returned": 1}},
                                      "nested": {"get:data": {"entered": 3, "returned": 3}}}
    assert gate.snapshots == 2 and fixture.pending_request_gates == {} and fixture.current_requests == []


@pytest.mark.parametrize("native_returned", [True, False])
def test_glb_runtime_profile_refreshes_inflight_ancestor_after_nested_request(fixture_imports, native_returned):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    fixture, gate = glb_runtime_profile_model(script), GLBProfileCounterGate()
    outer = glb_runtime_profile_frame("executor.py", "_invoke_owned", request=NS(id="outer", method="asset.glb_stage_preview"))
    nested = glb_runtime_profile_frame("executor.py", "_invoke_owned", request=NS(id="nested", method="asset.glb_stage_preview"))
    access = glb_runtime_profile_frame("glb_stage_profile.py", "_access", self=NS(_runtime_gate=gate))
    fixture.profile(outer, "call", None)
    gate.counts["get:data"].update(entered=1, returned=1)
    fixture.profile(access, "return", None)
    gate.counts["get:data"].update(entered=2, returned=1)  # Outer native call is in flight.
    fixture.profile(nested, "call", None)
    gate.counts["get:data"].update(entered=3, returned=2)
    fixture.profile(access, "return", None)
    fixture.profile(nested, "return", None)
    gate.counts["get:data"]["returned"] += int(native_returned)
    fixture.profile(access, "return", object() if native_returned else None)
    fixture.profile(outer, "return", None)
    assert fixture.request_access["outer"] == {"get:data": {"entered": 3, "returned": 3 if native_returned else 2}}
    assert fixture.request_access["nested"] == {"get:data": {"entered": 3, "returned": 2}}
    assert fixture.pending_request_gates == {} and fixture.current_requests == []


def test_glb_runtime_profile_preserves_last_gate_and_absent_receipts(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    fixture = glb_runtime_profile_model(script)
    first, last = GLBProfileCounterGate(), GLBProfileCounterGate()
    request = glb_runtime_profile_frame("executor.py", "_invoke_owned", request=NS(id="two-gates", method="asset.glb_stage_preview"))
    fixture.profile(request, "call", None)
    for gate, count in ((first, 10), (last, 20)):
        gate.counts["get:data"].update(entered=count, returned=count)
        fixture.profile(glb_runtime_profile_frame("glb_stage_profile.py", "_access", self=NS(_runtime_gate=gate)), "return", None)
    fixture.profile(request, "return", None)
    assert first.snapshots == 0 and last.snapshots == 1
    assert fixture.request_access == {"two-gates": {"get:data": {"entered": 20, "returned": 20}}}
    no_access = glb_runtime_profile_frame("executor.py", "_invoke_owned", request=NS(id="no-access", method="asset.glb_stage_inspect"))
    fixture.profile(no_access, "call", None)
    fixture.profile(no_access, "return", None)
    assert "no-access" not in fixture.request_access and fixture.pending_request_gates == {}


def test_glb_runtime_profile_releases_pending_gate_and_stack_when_cached_snapshot_fails(fixture_imports):
    script = importlib.import_module("scripts.blender_glb_stage_runtime_smoke")
    fixture = glb_runtime_profile_model(script)
    request = glb_runtime_profile_frame("executor.py", "_invoke_owned", request=NS(id="snapshot-error", method="asset.glb_stage_preview"))
    def failed():
        raise MemoryError("bounded reporting allocation failed")
    gate = NS(snapshot=failed)
    fixture.profile(request, "call", None)
    fixture.profile(glb_runtime_profile_frame("glb_stage_profile.py", "_access", self=NS(_runtime_gate=gate)), "return", None)
    with pytest.raises(MemoryError):
        fixture.profile(request, "return", None)
    assert fixture.pending_request_gates == {} and fixture.current_requests == []
