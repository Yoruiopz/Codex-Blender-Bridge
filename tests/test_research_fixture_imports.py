"""Importing native fixture helpers must never start their owned experiment."""

from __future__ import annotations

import ast
import importlib
import os
import runpy
import socket
import sys
import threading
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = (
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
    ("scripts.native_character_revision_evidence", "lbs_vertices"),
])
def test_importing_helper_fixture_does_not_start_experiment(fixture_imports, name, helper):
    imported = importlib.import_module(name)
    assert callable(getattr(imported, helper))
    assert fixture_imports.timers == [] and fixture_imports.events == []


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
