"""Bounded native proof of explicit artist target-channel verification.

Run only through the isolated native runner in a disposable background process.
Raw APIs construct the provided asset, inject labeled manual/control conditions,
and observe native state. Artist edits use registered plan/reference/preview/apply
calls. This fixture has no render, save, actual global undo or delivery claim.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
sys.path.insert(0, str(ROOT / "scripts"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402

METHOD = "task.plan.verify_transform"
WORK = "Artist Target Verification Prop"
PROTECTED = "Artist Target Protected Peer"
STEP = "revise"
CORE = ("location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
SCOPE = "authored_core_transform_channels"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def channels(obj: Any) -> dict[str, Any]:
    return {field: str(getattr(obj, field)) if field == "rotation_mode" else [float(item) for item in getattr(obj, field)]
            for field in CORE}


def float32(value: float) -> float:
    assert math.isfinite(value)
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(values: dict[str, Any]) -> dict[str, Any]:
    return {field: value if field == "rotation_mode" else [struct.pack("<f", item).hex() for item in value]
            for field, value in values.items()}


def expected_channels(before: dict[str, Any], requested: dict[str, Any]) -> dict[str, Any]:
    """Independent assignment oracle, fixed before calling the bridge apply."""
    result = copy.deepcopy(before)
    if "rotation_mode" in requested:
        assert requested["rotation_mode"] == before["rotation_mode"], "Mode conversion is intentionally unqualified"
    for field in ("location", "rotation", "scale"):
        if field in requested:
            result["rotation_euler" if field == "rotation" else field] = [float32(item) for item in requested[field]]
    return result


def custom(owner: Any) -> dict[str, Any]:
    names = list(owner.keys())
    assert len(names) <= 64
    result = {}
    for name in sorted(names):
        value = owner[name]
        assert value is None or type(value) in (str, bool, int, float), "Provided fixture custom data must remain plain scalar"
        if type(value) is float:
            assert math.isfinite(value)
        result[name] = value
    return result


def token(owner: Any) -> dict[str, Any] | None:
    return None if owner is None else {"name": owner.name, "pointer": owner.as_pointer(), "session_uid": owner.session_uid}


def stored_context(scene: Any, layer: Any) -> dict[str, Any]:
    # Stored flags are always first: no selected_objects or context.view_layer getter.
    flags = [[obj.name, bool(obj.select_get(view_layer=layer))] for obj in layer.objects]
    active = layer.objects.active
    return {"selection_flags": flags, "active": None if active is None else active.name,
            "mode": None if active is None else active.mode, "scene": token(scene),
            "layer": {"name": layer.name, "pointer": layer.as_pointer()},
            "frame": scene.frame_current, "subframe": scene.frame_subframe}


def object_state(obj: Any) -> dict[str, Any]:
    from native_character_evidence import animation, rest, rna

    result = {"identity": token(obj), "type": obj.type, "core_channels": channels(obj),
              "delta_location": list(obj.delta_location), "delta_rotation_euler": list(obj.delta_rotation_euler),
              "delta_rotation_quaternion": list(obj.delta_rotation_quaternion), "delta_scale": list(obj.delta_scale),
              "parent": token(obj.parent), "parent_type": obj.parent_type, "parent_bone": obj.parent_bone,
              "matrix_parent_inverse": [list(row) for row in obj.matrix_parent_inverse],
              "visibility": [obj.hide_viewport, obj.hide_render, obj.hide_select],
              "collections": [token(collection) for collection in obj.users_collection],
              "custom": custom(obj), "animation": animation(obj),
              "constraints": [{"type": constraint.type, "settings": rna(constraint)} for constraint in obj.constraints],
              "data": token(obj.data)}
    if obj.type == "MESH":
        result["mesh"] = rest(obj)
        result["mesh_custom"] = custom(obj.data)
        result["material_identities"] = [token(material) for material in obj.data.materials]
    return result


def object_schema(obj: Any) -> dict[str, Any]:
    """Retain bounded native descriptors before qualifying the first profile."""
    canonical = bpy.types.Object.bl_rna
    actual = obj.bl_rna
    properties = {}
    for name in ("name", "session_uid", *CORE):
        prop = canonical.properties.get(name)
        properties[name] = None if prop is None else {
            "identifier": prop.identifier, "type": prop.type,
            **{field: getattr(prop, field, None) for field in (
                "array_length", "is_array", "is_readonly", "is_runtime", "is_registered", "is_registered_optional",
                "hard_min", "hard_max")}}
    return {"object_python_type": type(obj).__module__ + "." + type(obj).__name__,
            "exact_native_object_type": type(obj) is bpy.types.Object,
            "canonical_identifier": canonical.identifier, "actual_identifier": actual.identifier,
            "canonical_pointer": canonical.as_pointer(), "actual_pointer": actual.as_pointer(),
            "properties": properties}


def checkpoint_state(runtime: Any) -> dict[str, Any]:
    manager = runtime.checkpoints
    return {"checkpoints": manager.list(50), "sequence": manager._sequence,
            "undo_steps": [asdict(step) for step in manager._undo_steps],
            "pending": None if manager._pending is None else asdict(manager._pending),
            "editor_session": None if manager._editor_session is None else asdict(manager._editor_session),
            "window_position": manager._window.position, "window_has_redo": manager._window._has_redo,
            "window_targets": {name: asdict(boundary) for name, boundary in manager._window._targets.items()},
            "expired_operations": manager._expired_operations,
            "native_push_pending_keys": sorted(manager._native_push_pending),
            "owned_pending": sorted((key, record.state) for key, record in manager._owned_pending.items()),
            "owned_claim": None if manager._owned_claim is None else id(manager._owned_claim)}


def native_state(runtime: Any, scene: Any, layer: Any, checkpoint_calls: list[str]) -> dict[str, Any]:
    # Read stored selection flags before the inventory/geometry observers.
    context = stored_context(scene, layer)
    objects = list(bpy.data.objects)
    assert len(objects) <= 16
    scenes = list(bpy.data.scenes)
    assert len(scenes) <= 4
    result = {"context": context, "objects": {obj.name: object_state(obj) for obj in objects},
              "scene_custom": {item.name: custom(item) for item in scenes},
              "checkpoints": checkpoint_state(runtime), "checkpoint_calls": list(checkpoint_calls),
              "history": runtime.state.history(100),
              "pause_stop": {field: runtime.state.snapshot()[field] for field in ("paused", "emergency_stopped")}}
    assert result["context"] == stored_context(scene, layer), "Fixture observation changed stored context"
    return result


def journal_state(store: Any) -> dict[str, Any]:
    """Retain bounded provenance and full-content hashes without repeating maps."""
    evidence = store.inspect()["step_evidence"]
    receipts = []
    for receipt in evidence["receipts"]:
        row = {key: copy.deepcopy(value) for key, value in receipt.items()
               if key not in {"target_expectation", "target_observation"}}
        row["target_expectation_sha256"] = digest(receipt.get("target_expectation"))
        observation = receipt.get("target_observation")
        row["target_observation_sha256"] = digest(observation)
        row["target_observation"] = (None if observation is None else {
            field: observation[field] for field in ("observation_id", "status", "scope", "validity", "current_scene_verified")})
        receipts.append(row)
    return {key: copy.deepcopy(value) for key, value in evidence.items() if key != "receipts"} | {"receipts": receipts}


class Proof:
    def __init__(self, runtime: Any, scene: Any, layer: Any, folder: Path, checkpoint_calls: list[str], reader_calls: list[str]):
        self.runtime, self.scene, self.layer, self.folder = runtime, scene, layer, folder
        self.checkpoint_calls, self.reader_calls = checkpoint_calls, reader_calls
        self.data: dict[str, Any] = {
            "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "process_id": os.getpid(), "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
            "artist_edits": "registered runtime.dispatch plan/reference/preview/apply only",
            "manual_injections": "labeled raw fixture-only native starting modes, manual drift/rename/replacement and readonly control conditions",
            "observation_scope": "provided Mesh/Empty target and protected peer: core/delta channels, hierarchy, identity, geometry/UV/materials/custom data, context, checkpoint and history",
            "reader_counter_scope": "outer read_target helper invocation only; no per-property getter counts inferred",
            "audit_history_contract": "success preserves complete history; each refusal prepends exactly one failed-method audit and preserves every prior record within the observed non-full bounded capacity",
            "calls": [], "profiles": [], "readonly_cases": [], "injections": [], "completed": False,
            "limits": {"visual_verification": False, "evaluated_transform_verification": False,
                       "native_undo": False, "native_history_eviction": False, "durable_recovery": False,
                       "project_saved": False, "full_artist_acceptance": False, "Windows_qualified": False},
        }
        self.flush()

    def flush(self) -> None:
        raw = (json.dumps(self.data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        assert len(raw) < 8 * 1024 * 1024, "Bounded artist-target evidence exceeded 8 MiB"
        (self.folder / "artist-target-evidence.json").write_bytes(raw)

    def call(self, method: str, params: dict[str, Any]) -> Any:
        row = {"method": method, "params": copy.deepcopy(params)}
        self.data["calls"].append(row)
        self.flush()
        try:
            result = self.runtime.dispatch(method, params)
        except BridgeError as error:
            row["error"] = error.to_dict()
            self.flush()
            raise
        row["result"] = result
        self.flush()
        return result

    def inject(self, label: str, detail: Any) -> None:
        self.data["injections"].append({"label": label, "detail": detail})
        self.flush()

    def readonly(self, label: str, params: dict[str, Any], *, status: str | None = None,
                 error_code: str | None = None, reads: int = 1, invoke: Any = None) -> dict[str, Any]:
        from blender_codex_bridge.task_plans import get_task_plans

        store = get_task_plans(self.runtime.state)
        before_journal = journal_state(store)
        row = {"label": label, "params": copy.deepcopy(params), "native_before": native_state(
            self.runtime, self.scene, self.layer, self.checkpoint_calls),
            "journal_before": before_journal, "target_reader_calls_before": len(self.reader_calls),
            "history_capacity_before": self.runtime.state._history.maxlen}
        self.data["readonly_cases"].append(row)
        self.flush()
        try:
            response = self.runtime.dispatch(METHOD, params) if invoke is None else invoke(params)
            if hasattr(response, "ok"):
                row["executor_response"] = response.to_dict()
                if response.ok:
                    row["result"] = response.result
                else:
                    row["error"] = response.error
            else:
                row["result"] = response
        except BridgeError as error:
            row["error"] = error.to_dict()
        row["native_after"] = native_state(self.runtime, self.scene, self.layer, self.checkpoint_calls)
        row["journal_after"] = journal_state(store)
        row["target_reader_calls_after"] = len(self.reader_calls)
        row["history_capacity_after"] = self.runtime.state._history.maxlen
        before_history, after_history = row["native_before"]["history"], row["native_after"]["history"]
        row["audit_history"] = {"expected_failed_audits": 0 if error_code is None else 1,
                                "before_records": len(before_history), "after_records": len(after_history),
                                "validated": False}
        self.flush()  # Retain complete observations before any result assertion.
        assert {key: value for key, value in row["native_after"].items() if key != "history"} == {
            key: value for key, value in row["native_before"].items() if key != "history"
        }, (label, "Readonly native/context/checkpoint preservation failed")
        capacity = row["history_capacity_before"]
        assert type(capacity) is int and 1 <= capacity <= 100
        assert row["history_capacity_after"] == capacity
        assert len(before_history) <= capacity and len(after_history) <= capacity
        assert len(self.reader_calls) - row["target_reader_calls_before"] == reads, (label, "Unexpected target-reader invocation")
        if error_code is not None:
            assert row.get("error", {}).get("code") == error_code, (label, row.get("error"))
            # Executor failures are audited even for record_history=False tools.
            # This fixture deliberately stays below capacity: every old record
            # must survive exactly; it does not qualify history eviction.
            assert len(before_history) < capacity, (label, "Fixture audit history reached capacity")
            assert len(after_history) == len(before_history) + 1
            assert after_history[1:] == before_history, (label, "Refusal changed a previous audit record")
            record = after_history[0]
            assert set(record) == {"operation_id", "tool", "timestamp", "description", "success", "duration_ms",
                                   "affected_objects", "error_code", "job_evidence", "external_effects", "recovery_evidence"}
            assert record["tool"] == METHOD and record["success"] is False and record["error_code"] == error_code
            assert record["affected_objects"] == []
            assert record["job_evidence"] is record["external_effects"] is record["recovery_evidence"] is None
            assert record["description"] == row["error"]["message"][:240]
            operation_id = record["operation_id"]
            assert (isinstance(operation_id, str) and operation_id.startswith("op_") and len(operation_id) == 13
                    and all(character in "0123456789abcdef" for character in operation_id[3:]))
            assert operation_id not in {previous["operation_id"] for previous in before_history}
            assert isinstance(record["timestamp"], str) and record["timestamp"]
            assert type(record["duration_ms"]) in {int, float} and math.isfinite(record["duration_ms"]) and record["duration_ms"] >= 0
            row["audit_history"].update(validated=True, operation_id=operation_id, prior_records_preserved=True)
            self.flush()
            before = [receipt["target_observation_sha256"] for receipt in before_journal["receipts"]]
            after = [receipt["target_observation_sha256"] for receipt in row["journal_after"]["receipts"]]
            assert before == after, (label, "Refusal attached or changed a target observation")
            return row
        assert "error" not in row, (label, row.get("error"))
        assert after_history == before_history, (label, "Successful readonly verification changed audit history")
        row["audit_history"].update(validated=True, prior_records_preserved=True)
        self.flush()
        result = row["result"]
        observation = result["target_observation"]
        assert result["scope"] == observation["scope"] == SCOPE
        assert result["step_id"] == STEP and result["receipt_id"] == params["receipt_id"]
        assert observation["status"] == status
        assert observation["observation_id"] and result["operation_id"]
        assert result["user_goal_verified"] is observation["user_goal_verified"] is False
        assert result["current_scene_verified"] is False
        assert store.require_plan()["steps"][0]["status"] == "pending"
        retained = next(receipt for receipt in row["journal_after"]["receipts"] if receipt["receipt_id"] == params["receipt_id"])
        assert retained["target_observation"]["observation_id"] == observation["observation_id"]
        assert retained["target_observation"]["current_scene_verified"] is False
        return row


def provided_asset(scene: Any, layer: Any) -> tuple[Any, Any]:
    mesh = bpy.data.meshes.new("Artist Target Given Geometry")
    mesh.from_pydata([(0., 0., 0.), (.7, 0., 0.), (0., .6, 0.)], [], [(0, 1, 2)])
    mesh.update()
    work = bpy.data.objects.new(WORK, mesh)
    scene.collection.objects.link(work)
    uv = mesh.uv_layers.new(name="Given UV")
    for value, coordinate in zip(uv.data, ((0., 0.), (1., 0.), (0., 1.)), strict=True):
        value.uv = coordinate
    attribute = mesh.attributes.new("Given Protected Attribute", "FLOAT", "POINT")
    for index, value in enumerate(attribute.data):
        value.value = .125 * index
    material = bpy.data.materials.new("Artist Target Given Blue")
    material.use_nodes = True
    material.diffuse_color = (.1, .3, .7, 1.)
    material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (.1, .3, .7, 1.)
    mesh.materials.append(material)
    protected = bpy.data.objects["Cube"]
    protected.name = PROTECTED
    protected["provided_protected_tag"] = "Keep native channels, geometry, UVs and materials"
    work["provided_working_tag"] = "Transform core channels only"
    layer.update()
    for obj in layer.objects:
        obj.select_set(False, view_layer=layer)
    work.select_set(True, view_layer=layer)
    layer.objects.active = work
    layer.update()
    assert stored_context(scene, layer) == stored_context(scene, layer)
    return work, protected


def seed_profile(work: Any, mode: str, index: int) -> dict[str, Any]:
    """Labeled provided starting values, not a bridge artist operation."""
    work.rotation_mode = mode
    work.location = (.03125 * index, -.0625, .125)
    work.scale = (1., 1.25, .75)
    work.rotation_euler = (.0625, -.125, .25)
    work.rotation_quaternion = (math.cos(.125), math.sin(.125), 0., -0.)
    work.rotation_axis_angle = (.5, 0., 1., -0.)
    return channels(work)


def main() -> None:
    from blender_codex_bridge import artist_target_intent as intent_module
    from blender_codex_bridge.command_queue import QueuedRequest
    from blender_codex_bridge.protocol import Request
    from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime
    from blender_codex_bridge.runtime import _before_external_undo_redo
    from blender_codex_bridge.task_plans import get_task_plans
    from native_character_evidence import rest

    assert bpy.app.background, "Use the isolated background native runner"
    bpy.context.preferences.use_preferences_save = False
    scene, layer = bpy.context.scene, bpy.context.scene.view_layers[0]
    folder = Path(tempfile.gettempdir()) / "artist-target-evidence"
    folder.mkdir()
    blender_codex_bridge.register()
    proof = None
    original_reader = intent_module.read_target
    original_before = original_after = None
    try:
        runtime = get_runtime()
        grants = {permission.value: permission not in {Permission.EXECUTE_PYTHON, Permission.SAVE_PROJECT} for permission in Permission}
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        runtime.registry.enable_toolset("objects")
        checkpoint_calls: list[str] = []
        original_before, original_after = runtime.checkpoints.before_modification, runtime.checkpoints.after_modification

        def before(method: str, **kwargs: Any) -> Any:
            checkpoint_calls.append("before:" + method)
            return original_before(method, **kwargs)

        def after(method: str, **kwargs: Any) -> Any:
            checkpoint_calls.append("after:" + method)
            return original_after(method, **kwargs)

        runtime.checkpoints.before_modification, runtime.checkpoints.after_modification = before, after
        reader_calls: list[str] = []

        def observed_reader(*args: Any, **kwargs: Any) -> Any:
            reader_calls.append("read_target")
            return original_reader(*args, **kwargs)

        intent_module.read_target = observed_reader
        work, protected = provided_asset(scene, layer)
        proof = Proof(runtime, scene, layer, folder, checkpoint_calls, reader_calls)
        proof.data["permissions"] = dict(grants)
        proof.data["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), ROOT / "addon/blender_codex_bridge/artist_target_intent.py",
                         ROOT / "addon/blender_codex_bridge/artist_step_evidence.py",
                         ROOT / "addon/blender_codex_bridge/tools/artist_target_verify.py",
                         ROOT / "addon/blender_codex_bridge/tools/artist_loop.py",
                         ROOT / "addon/blender_codex_bridge/executor.py", ROOT / "addon/blender_codex_bridge/state.py")}
        protected_before, working_rest = object_state(protected), rest(work)
        proof.data["provided_object_schema"] = object_schema(work)
        proof.data["provided_protected_baseline"] = protected_before
        proof.data["provided_working_rest"] = working_rest
        proof.flush()
        plan = proof.call("task.plan.set", {"goal": "Place the named prop and verify its intended core channels while preserving the peer",
            "steps": [{"id": STEP, "description": "Preview, place and independently verify target core channels"}],
            "protected_objects": [protected.name]})
        revision = plan["plan"]["revision"]
        proof.call("task.plan.enforce", {"enabled": True, "expected_revision": revision})
        store = get_task_plans(runtime.state)

        def current_params(receipt: str) -> dict[str, Any]:
            return {"step_id": STEP, "receipt_id": receipt, "expected_revision": store.require_plan()["revision"]}

        def apply(label: str, requested: dict[str, Any], *, qualified: bool = True) -> tuple[str, dict[str, Any] | None]:
            before_channels = channels(work)
            expected = expected_channels(before_channels, requested) if qualified else None
            row = {"label": label, "requested": copy.deepcopy(requested), "before": before_channels,
                   "independent_expected": expected, "independent_expected_float32_le": None if expected is None else bits(expected)}
            proof.data["profiles"].append(row)
            proof.flush()  # The independent expectation is fixed before any apply.
            reference = proof.call("task.reference.resolve", {"source": "objects", "object_names": [work.name]})
            preview = proof.call("task.plan.preview_transform", {"reference_id": reference["reference_id"],
                "expected_revision": store.require_plan()["revision"], "step_id": STEP, **requested})
            result = proof.call("task.plan.apply_preview", {"preview_id": preview["preview_id"],
                "expected_revision": store.require_plan()["revision"]})
            row.update(after=channels(work), after_float32_le=bits(channels(work)), preview=preview,
                       receipt_id=result["step_receipt_id"], operation_id=result["operation"]["operation_id"])
            proof.flush()
            assert object_state(protected) == protected_before and rest(work) == working_rest
            if expected is not None:
                assert bits(channels(work)) == bits(expected), (label, "Actual native assignment differs from independent pre-apply Float32 intent")
            return result["step_receipt_id"], expected

        latest_receipt = ""
        oldest_receipt = ""
        for index, mode in enumerate(("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"), 1):
            proof.inject("provided_starting_profile_" + mode, seed_profile(work, mode, index))
            requested = {"location": [.1 * index, -0., -.3], "rotation": [math.pi / 7., -math.pi / 9., .625],
                         "scale": [-1.25, .5, 2.75]}
            if mode == "ZYX":
                requested["rotation_mode"] = mode
            latest_receipt, expected = apply("same_mode_" + mode, requested)
            oldest_receipt = oldest_receipt or latest_receipt
            row = proof.readonly("qualified_" + mode, current_params(latest_receipt), status="channels_match")
            assert row["result"]["target_observation"]["expected_float32_le"] == bits(expected)
            assert row["result"]["target_observation"]["observed_float32_le"] == bits(expected)
            assert row["result"]["target_observation"]["differences"] == []
        for index, mode in enumerate(("QUATERNION", "AXIS_ANGLE"), 7):
            proof.inject("provided_starting_profile_" + mode, seed_profile(work, mode, index))
            latest_receipt, expected = apply("position_only_" + mode,
                {"location": [.2, .3, -.4], "scale": [1.25, -.75, 2.]})
            row = proof.readonly("qualified_" + mode, current_params(latest_receipt), status="channels_match")
            assert row["result"]["target_observation"]["expected_float32_le"] == bits(expected)
            assert row["result"]["target_observation"]["observed_float32_le"] == bits(expected)
        proof.readonly("older_retained_receipt", current_params(oldest_receipt), error_code="INVALID_ARGUMENT", reads=0)

        # These raw changes represent explicit mixed-editor observations, not an
        # undocumented bridge write or a repair hidden inside the verifier.
        unchanged = channels(work)
        work.location.y += .125
        proof.inject("manual_target_core_drift", {"before": unchanged, "after": channels(work)})
        mismatch = proof.readonly("manual_core_drift", current_params(latest_receipt), status="channels_differ")
        assert mismatch["result"]["target_observation"]["differences"]
        work.location = unchanged["location"]
        proof.inject("manual_target_core_restore", channels(work))
        proof.readonly("restored_manual_core", current_params(latest_receipt), status="channels_match")

        work.name = WORK + " Renamed"
        layer.update()
        proof.inject("manual_target_rename_missing_exact_name", token(work))
        proof.readonly("target_missing_exact_name", current_params(latest_receipt), status="target_missing")
        replacement = bpy.data.objects.new(WORK, None)
        scene.collection.objects.link(replacement)
        layer.update()
        proof.inject("provided_replacement_at_frozen_name", token(replacement))
        proof.readonly("target_replaced_exact_name", current_params(latest_receipt), status="target_replaced")
        bpy.data.objects.remove(replacement, do_unlink=True)  # Known fixture-owned replacement only.
        work.name = WORK
        layer.update()
        proof.inject("manual_target_name_restored", token(work))
        proof.readonly("restored_target_identity", current_params(latest_receipt), status="channels_match")

        grants[Permission.INSPECT_SCENE.value] = False
        try:
            proof.readonly("inspect_permission_denied", current_params(latest_receipt), error_code="PERMISSION_DENIED", reads=0)
        finally:
            grants[Permission.INSPECT_SCENE.value] = True
        grants[Permission.TRANSFORM_OBJECTS.value] = False
        try:
            proof.readonly("inspection_without_transform_grant", current_params(latest_receipt), status="channels_match")
            runtime.state.set_paused(True)
            proof.readonly("paused_inspection", current_params(latest_receipt), status="channels_match")
            runtime.state.set_emergency_stopped(True)
            proof.readonly("emergency_stopped_inspection", current_params(latest_receipt), status="channels_match")
        finally:
            runtime.state.set_emergency_stopped(False)
            runtime.state.set_paused(False)
            grants[Permission.TRANSFORM_OBJECTS.value] = True

        # Current readonly plan corrections are compatible before entry, while a
        # correction inside this NEW verifier's permission provider invalidates
        # its frozen provenance. No timeline/keyframe audit is performed here.
        fired: list[bool] = []

        def correction_provider() -> dict[str, bool]:
            if not fired:
                fired.append(True)
                updated = runtime.dispatch("task.plan.update", {"step_id": STEP,
                    "expected_revision": store.require_plan()["revision"], "note": "Fixture provider corrected the plan note"})
                proof.inject("typed_plan_note_changed_inside_verify_provider", {"revision": updated["plan"]["revision"]})
            return grants

        manager._source = correction_provider
        try:
            proof.readonly("provider_plan_revision_drift", current_params(latest_receipt), error_code="INVALID_ARGUMENT", reads=0)
            assert fired
        finally:
            manager._source = lambda: grants
        proof.readonly("corrected_plan_before_invocation", current_params(latest_receipt), status="channels_match")

        for fault in ("cancel", "disconnect"):
            parameters = current_params(latest_receipt)
            lifetime = RequestLifetime.local()
            connection = ConnectionLifetime()
            lifetime.connection = connection
            request = Request(id="artist-target-readonly-" + fault, method=METHOD, params=parameters, _lifecycle=lifetime)
            queued = QueuedRequest(request)
            assert queued.try_start()
            interrupted: list[bool] = []

            def interrupt_provider(fault: str = fault, interrupted: list[bool] = interrupted,
                                   queued: Any = queued, connection: Any = connection) -> dict[str, bool]:
                if not interrupted:
                    interrupted.append(True)
                    if fault == "cancel":
                        queued.cancel_pending(BridgeError("TIMEOUT", "Fixture caller canceled this new readonly verification"))
                    else:
                        connection.disconnected.set()
                return grants

            manager._source = interrupt_provider
            try:
                proof.readonly("readonly_" + fault, parameters, error_code="TIMEOUT", reads=0,
                    invoke=lambda _params, request=request, queued=queued: runtime.executor.execute_request(
                        request, check_cancelled=queued.check_active))
                assert interrupted
            finally:
                manager._source = lambda: grants

        proof.call("transform.set", {"object_name": work.name, "location": [.7, .8, .9]})
        proof.readonly("intervening_tracked_writer", current_params(latest_receipt), error_code="INVALID_ARGUMENT", reads=0)
        latest_receipt, _expected = apply("new_current_receipt_after_writer", {"location": [.4, .5, .6]})
        proof.readonly("new_current_receipt", current_params(latest_receipt), status="channels_match")
        _before_external_undo_redo(None)
        proof.inject("real_generation_invalidation_callback_without_native_undo", {"generation": store.protection_generation})
        proof.readonly("historical_generation_receipt", current_params(latest_receipt), error_code="INVALID_ARGUMENT", reads=0)
        historical = proof.call("task.plan.inspect", {})["step_evidence"]
        receipt = next(item for item in historical["receipts"] if item["receipt_id"] == latest_receipt)
        assert receipt["history_state"] == "historical_after_generation_change"
        assert receipt["target_observation"]["validity"] == "stale"
        assert receipt["target_observation"]["current_scene_verified"] is False

        proof.inject("provided_mode_conversion_start", seed_profile(work, "QUATERNION", 9))
        converted, _ = apply("mode_conversion_compatibility", {"location": [.4, .5, .6], "rotation_mode": "XYZ"}, qualified=False)
        assert work.rotation_mode == "XYZ"
        proof.readonly("mode_conversion_verification_unavailable", current_params(converted), error_code="NOT_IMPLEMENTED", reads=0)
        proof.inject("provided_subnormal_request_start", seed_profile(work, "XYZ", 10))
        subnormal, _ = apply("subnormal_compatibility", {"location": [1e-40, 0., 0.]}, qualified=False)
        proof.readonly("subnormal_verification_unavailable", current_params(subnormal), error_code="NOT_IMPLEMENTED", reads=0)

        assert object_state(protected) == protected_before and rest(work) == working_rest
        final = proof.call("task.plan.inspect", {})
        assert final["protected_scope_enforced"] and final["plan"]["steps"][0]["status"] == "pending"
        assert final["step_evidence"]["scope"] == "protected_objects_only"
        assert final["step_evidence"]["user_goal_verified"] is False
        proof.data["final_plan_inspection"] = final
        proof.data["completed"] = True
        proof.flush()
        evidence = folder / "artist-target-evidence.json"
        successes = [row for row in proof.data["readonly_cases"] if "result" in row]
        refusals = [row for row in proof.data["readonly_cases"] if "error" in row]
        print("BLENDER_ARTIST_TARGET_VERIFICATION_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "evidence_file": str(evidence),
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "qualified_core_profiles": 8, "readonly_successes": len(successes), "typed_refusals": len(refusals),
            "target_reader_invocations": len(reader_calls), "all_readonly_native_context_checkpoint_equal": True,
            "successful_readonly_history_equal": True, "each_refusal_appends_exactly_one_failed_method_audit": True,
            "all_prior_audit_records_preserved": True, "refusal_audits_have_no_affected_objects_or_effect_metadata": True,
            "all_same_mode_assignments_match_independent_float32_bits": True,
            "complete_declared_protected_scope_preserved": True, "mode_conversion_apply_compatibility_preserved": True,
            "step_not_automatically_completed": True, **proof.data["limits"]}, allow_nan=False), flush=True)
    except BaseException as error:
        if proof is not None:
            proof.data["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
            proof.flush()
        raise
    finally:
        intent_module.read_target = original_reader
        if original_before is not None:
            runtime.checkpoints.before_modification = original_before
        if original_after is not None:
            runtime.checkpoints.after_modification = original_after
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
