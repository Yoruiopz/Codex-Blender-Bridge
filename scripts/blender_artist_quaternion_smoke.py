"""Bounded registered quaternion workflow; run only in the isolated background runner.

Raw setup and labeled refusal controls own this disposable factory scene. Artist
edits use registered tools. Immediate reads delegate the real assignment once;
one explicitly labeled post-assignment failure measures compensation, not undo,
durable recovery, evaluated orientation, appearance or artistic completion.
The separately measured native checkpoint ParticleEdit weak role has one exact
receipt-gated Scene-to-protected-Cube edge exception; raw counts remain retained.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import sys
import traceback
from dataclasses import asdict, replace
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

WORK = "Registered Quaternion Prop"
STEP = "rotate"
CORE = ("location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
MIN_NORMAL = float.fromhex("0x1p-126")
MAX_CHECKPOINT_RECEIPTS = 64


def channels(obj: Any) -> dict[str, Any]:
    return {name: str(getattr(obj, name)) if name == "rotation_mode" else [float(value) for value in getattr(obj, name)]
            for name in CORE}


def bits(values: dict[str, Any]) -> dict[str, Any]:
    return {name: value if name == "rotation_mode" else [struct.pack("<f", item).hex() for item in value]
            for name, value in values.items()}


def double_bits(values: list[float] | tuple[float, ...]) -> list[str]:
    return [struct.pack("<d", value).hex() for value in values]


def independent_expected(before: dict[str, Any], requested: list[float] | tuple[float, ...]) -> tuple[dict[str, Any], dict[str, float]]:
    """Freeze the independent six-channel prediction before registered entry."""
    assert len(requested) == 4 and all(type(value) is float and math.isfinite(value) for value in requested)
    assert all(value == 0. or MIN_NORMAL <= abs(value) <= 1. for value in requested)
    rounded = [struct.unpack("<f", struct.pack("<f", value))[0] for value in requested]
    assert all(value == 0. or MIN_NORMAL <= abs(value) <= 1. for value in rounded)
    norms = {"requested_norm": math.sqrt(sum(value * value for value in requested)),
             "float32_norm": math.sqrt(sum(value * value for value in rounded))}
    assert all(abs(value - 1.) <= 1e-6 for value in norms.values())
    expected = copy.deepcopy(before)
    assert expected["rotation_mode"] == "QUATERNION"
    expected["rotation_quaternion"] = rounded
    return expected, norms


def requests() -> tuple[tuple[str, tuple[float, ...]], ...]:
    half = math.sqrt(.5)
    normalizer = math.sqrt(.1**2 + .2**2 + .3**2 + .4**2)
    return (("identity_signed_zero", (1., -0., 0., -0.)),
            ("quarter_x", (half, half, -0., 0.)),
            ("quarter_y", (half, 0., half, -0.)),
            ("quarter_z", (half, -0., 0., half)),
            ("negative_quarter_y", (-half, -0., -half, 0.)),
            ("general_exact_unit", (.5, -.5, .5, -.5)),
            ("general_stdlib_normalized_seed", tuple(value / normalizer for value in (.1, .2, .3, .4))))


def checkpoint_role_phase(roles: dict[str, Any], origin: dict[str, Any], protected: dict[str, Any]) -> int:
    """Qualify only the frozen factory Cube's two literal native weak-role states."""
    phase_fields = {"scene_self_references", "particle_object"}
    assert {key: value for key, value in roles.items() if key not in phase_fields} == {
        key: value for key, value in origin.items() if key not in phase_fields}, "Checkpoint role owners/settings changed"
    assert roles["active_object"] == protected and protected is not None
    assert type(roles["scene_self_references"]) is int
    if roles["scene_self_references"] == 0 and roles["particle_object"] is None:
        return 0
    assert roles["scene_self_references"] == 1 and roles["particle_object"] == protected, "Unqualified native weak role"
    return 1


def project_checkpoint_role(snapshot: dict[str, Any], origin: dict[str, Any], protected: dict[str, Any],
                            receipts: list[dict[str, Any]], calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Project one independently measured weak edge only with its actual completion receipt."""
    result = copy.deepcopy(snapshot)
    roles = result["checkpoint_roles"]
    initial = checkpoint_role_phase(origin, origin, protected)
    phase = checkpoint_role_phase(roles, origin, protected)
    witness = result.pop("checkpoint_role_completion_receipt_index")
    assert len(receipts) <= MAX_CHECKPOINT_RECEIPTS
    if initial == 0 and phase == 1:
        assert type(witness) is int and 0 <= witness < len(receipts), "Missing native checkpoint completion receipt"
        receipt = receipts[witness]
        assert receipt["kind"] == "before" and type(receipt["delegate_calls"]) is int and receipt["delegate_calls"] == 1
        assert receipt["returned"] is True and receipt["completed"] is True
        assert "exception" not in receipt
        assert type(receipt["call_index"]) is int and 0 <= receipt["call_index"] < len(calls)
        call = calls[receipt["call_index"]]
        assert receipt["method"] == call["method"] == "transform.set"
        assert receipt["call_label"] == call["label"] == "prearmed_direct_new_field"
        assert type(call["checkpoint_delegate_receipts_before"]) is int and type(call["checkpoint_delegate_receipts_after"]) is int
        assert 0 <= call["checkpoint_delegate_receipts_before"] <= witness < call["checkpoint_delegate_receipts_after"] <= len(receipts)
        assert checkpoint_role_phase(receipt["roles_before"], origin, protected) == 0
        assert checkpoint_role_phase(receipt["roles_after"], origin, protected) == 1
        assert receipt["roles_after"] == roles
    else:
        assert phase == initial and witness is None, "Unqualified reverse or unreceipted role phase"
    rows = [row for row in result["native_consumers"] if row["owner"] == protected]
    assert len(rows) == 1, "Protected Cube Object identity is not unique"
    edges = [edge for edge in rows[0]["consumers"] if edge["identity"] == origin["scene"]]
    assert len(edges) == 1 and type(edges[0]["references"]) is int
    assert edges[0]["references"] == 1 + phase, "Scene-to-Cube count exceeds exact membership plus measured weak role"
    edges[0]["references"] -= phase
    for field in ("scene_self_references", "particle_object"):
        roles.pop(field)
    return result


class Proof:
    def __init__(self, runtime: Any, scene: Any, layer: Any, work: Any, protected: Any, folder: Path,
                 attestation: dict[str, Any], process_token: str):
        from blender_artist_target_verification_smoke import (
            journal_state,
            native_state,
            stored_context,
            token,
        )
        from blender_codex_bridge.task_plans import get_task_plans

        self.runtime, self.scene, self.layer, self.work, self.protected = runtime, scene, layer, work, protected
        self.store, self.native_state, self.journal_state = get_task_plans(runtime.state), native_state, journal_state
        self.stored_context, self.token = stored_context, token
        self.path = folder / "artist-quaternion-evidence.json"
        assert not self.path.exists()
        self.checkpoint_calls: list[str] = []
        self.checkpoint_receipts: list[dict[str, Any]] = []
        self.assignment_rows: list[dict[str, Any]] = []
        self.fault_after_assignment = False
        self.data: dict[str, Any] = {
            "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "process_instance": process_token, "owned_profile_attestation": attestation,
            "calls": [], "vector_cases": [], "raw_controls": [], "lifetime_cases": [], "assignment_observations": self.assignment_rows,
            "checkpoint_delegate_receipts": self.checkpoint_receipts,
            "assignment_observer": "Delegate actual transforms.apply_assignments once; record immediate native reads; one labeled fault after real assignment",
            "comparison_scope": "Complete provided object channels/bits, Mesh rest data, hierarchy, native identities/consumers and stored context; exactly one measured Scene-to-frozen-active-Cube ParticleEdit weak edge requires successful actual native checkpoint completion; all raw counts/roles retained",
            "normal_write_comparison_excludes": ["checkpoint state", "checkpoint observer calls", "operation history", "Scene checkpoint custom markers", "runtime receipt journal"],
            "limits": {"visual_capture": False, "evaluated_orientation_verified": False, "artist_goal_verified": False,
                       "step_automatically_completed": False, "native_global_undo": False,
                       "durable_recovery": False, "history_eviction_qualified": False,
                       "public_save_or_protected_capture": False, "project_saved": False,
                       "generic_consumer_count_equality_claimed": False,
                       "full_artist_acceptance": False, "Windows_qualified": False, "release_acceptance": False},
            "termination": "Owned fixture os._exit after proof/stdio flush; no native save/quit callbacks or production cancellation claim",
            "completed": False,
        }
        self.flush()
        self.role_origin = self.checkpoint_roles()
        self.data["known_native_checkpoint_role_origin"] = self.role_origin
        self.data["known_native_checkpoint_role_exception"] = (
            "Only Scene.user_of_id(Scene) 0/ParticleEdit.object null to 1/frozen active protected Cube Object; "
            "only after actual before_modification returned True; subtract exactly one matching Scene-to-Cube Object edge; "
            "all other consumer counts and fixed role owners/settings remain literal")
        self.flush()
        self.role_phase_expected = checkpoint_role_phase(self.role_origin, self.role_origin, self.token(self.protected))
        self.role_transition_receipt: int | None = None

    def flush(self) -> None:
        raw = (json.dumps(self.data, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        assert len(raw) < 8 * 1024 * 1024, "Registered quaternion proof exceeded 8 MiB"
        self.path.write_bytes(raw)

    def control(self, label: str, detail: Any) -> None:
        self.data["raw_controls"].append({"label": label, "detail": detail})
        self.flush()

    def checkpoint_roles(self) -> dict[str, Any]:
        from blender_codex_bridge.tools._scene_checkpoint_roles import _pointer, _settings

        context = self.stored_context(self.scene, self.layer)
        settings = _pointer(bpy, self.scene, "tool_settings", "ToolSettings")
        particle = _pointer(bpy, settings, "particle_edit", "ParticleEdit")
        particle_object = _pointer(bpy, particle, "object", "Object")
        original = _pointer(bpy, self.scene, "original", "ID")
        brush = _pointer(bpy, particle, "brush", "ParticleBrush")
        assert brush is not None
        curve = _pointer(bpy, brush, "curve", "CurveMapping")
        assert curve is None, "A non-null particle brush curve is outside this fixture's literal reader"
        result = {"scene": self.token(self.scene), "scene_original": self.token(original),
                  "tool_settings_pointer": settings.as_pointer(), "particle_edit_pointer": particle.as_pointer(),
                  "active_object": self.token(self.layer.objects.active),
                  "scene_self_references": int(self.scene.user_of_id(self.scene)), "particle_object": self.token(particle_object),
                  "particle_settings": _settings(bpy, particle), "brush_pointer": brush.as_pointer(),
                  "brush_settings": _settings(bpy, brush), "brush_curve_pointer": None}
        assert context == self.stored_context(self.scene, self.layer)
        return result

    def checkpoint_delegate(self, kind: str, method: str, delegate: Any, kwargs: dict[str, Any]) -> Any:
        assert len(self.checkpoint_receipts) < MAX_CHECKPOINT_RECEIPTS
        roles_before = self.checkpoint_roles()
        assert checkpoint_role_phase(roles_before, self.role_origin, self.token(self.protected)) == self.role_phase_expected
        assert self.data["calls"]
        call_index = len(self.data["calls"]) - 1
        call = self.data["calls"][call_index]
        row = {"kind": kind, "method": method, "roles_before": roles_before, "delegate_calls": 0, "completed": False,
               "call_index": call_index, "call_label": call["label"]}
        index = len(self.checkpoint_receipts)
        self.checkpoint_receipts.append(row)
        self.flush()
        try:
            row["delegate_calls"] += 1
            result = delegate(method, **kwargs)
            row["returned"], row["completed"] = result, result is True
            return result
        except BaseException as error:
            row["exception"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            row["roles_after"] = self.checkpoint_roles()
            self.flush()  # Retain literal result and roles before qualifying any transition.
            after_phase = checkpoint_role_phase(row["roles_after"], self.role_origin, self.token(self.protected))
            if after_phase != self.role_phase_expected:
                assert self.role_phase_expected == 0 and after_phase == 1
                assert kind == "before" and row.get("returned") is True and row["completed"] is True
                assert method == call["method"] == "transform.set" and call["label"] == "prearmed_direct_new_field"
                assert "exception" not in row
                assert self.role_transition_receipt is None
                self.role_transition_receipt, self.role_phase_expected = index, 1

    def snapshot(self) -> dict[str, Any]:
        roles_before = self.checkpoint_roles()
        native = self.native_state(self.runtime, self.scene, self.layer, self.checkpoint_calls)
        objects = sorted(bpy.data.objects, key=lambda obj: obj.name)
        assert len(objects) <= 16
        owners = {self.work, self.work.data, self.protected, self.protected.data}
        consumers = bpy.data.user_map(subset=owners)
        result = {"native": native, "all_core_float32_le": {obj.name: bits(channels(obj)) for obj in objects},
                  "ownership": {obj.name: {"object": self.token(obj), "data": self.token(obj.data),
                      "editable": obj.is_editable, "library": self.token(obj.library), "override": self.token(obj.override_library),
                      "scene_owners": sorted(owner.name for owner in obj.users_scene),
                      "children": sorted(child.name for child in obj.children),
                      "rotation_locks": [list(obj.lock_rotation), obj.lock_rotation_w, obj.lock_rotations_4d],
                      "data_users": None if obj.data is None else obj.data.users,
                      "delta_float32_le": {name: [struct.pack("<f", value).hex() for value in getattr(obj, name)]
                          for name in ("delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale")}}
                      for obj in objects},
                  "native_consumers": [{"owner": self.token(owner), "consumers": sorted(
                      [{"identity": self.token(consumer), "references": consumer.user_of_id(owner)} for consumer in values],
                      key=lambda item: (item["identity"]["name"], item["identity"]["pointer"]))}
                      for owner, values in sorted(consumers.items(), key=lambda item: (item[0].name, item[0].as_pointer()))],
                  "journal": self.journal_state(self.store), "checkpoint_roles": self.checkpoint_roles(),
                  "checkpoint_role_completion_receipt_index": self.role_transition_receipt}
        assert native["context"] == self.stored_context(self.scene, self.layer)
        assert roles_before == result["checkpoint_roles"], "Read-only fixture observation changed literal checkpoint roles"
        assert checkpoint_role_phase(result["checkpoint_roles"], self.role_origin, self.token(self.protected)) == self.role_phase_expected
        return result

    def authored(self, snapshot: dict[str, Any], *, omit_work_quaternion: bool = False) -> dict[str, Any]:
        result = project_checkpoint_role(snapshot, self.role_origin, self.token(self.protected), self.checkpoint_receipts,
                                         self.data["calls"])
        result.pop("journal")
        for field in ("checkpoints", "checkpoint_calls", "history"):
            result["native"].pop(field)
        for values in result["native"]["scene_custom"].values():
            values.pop("_codex_bridge_undo_marker", None)
        if omit_work_quaternion:
            result["native"]["objects"][self.work.name]["core_channels"].pop("rotation_quaternion")
            result["all_core_float32_le"][self.work.name].pop("rotation_quaternion")
        return result

    def preview_cache_ids(self) -> list[str]:
        from blender_codex_bridge.tools.artist_loop import MAX_PREVIEWS

        assert len(self.store.previews) <= MAX_PREVIEWS
        return sorted(self.store.previews)

    def call(self, label: str, method: str, params: dict[str, Any], *, error_code: str | None = None,
             precheckpoint: bool = True, quaternion_write: bool = False, invoke: Any = None) -> dict[str, Any]:
        row = {"label": label, "method": method, "params": copy.deepcopy(params), "before": self.snapshot(),
               "assignment_observations_before": len(self.assignment_rows),
               "checkpoint_delegate_receipts_before": len(self.checkpoint_receipts),
               "preview_cache_ids_before": self.preview_cache_ids()}
        self.data["calls"].append(row)
        self.flush()
        try:
            response = self.runtime.dispatch(method, params) if invoke is None else invoke()
            if hasattr(response, "ok"):
                row["executor_response"] = response.to_dict()
                row["result" if response.ok else "error"] = response.result if response.ok else response.error
            else:
                row["result"] = response
        except BridgeError as error:
            row["error"] = error.to_dict()
        row["after"] = self.snapshot()
        row["checkpoint_delegate_receipts_after"] = len(self.checkpoint_receipts)
        row["preview_cache_ids_after"] = self.preview_cache_ids()
        row["assignment_observations_after"] = len(self.assignment_rows)
        before_history, after_history = row["before"]["native"]["history"], row["after"]["native"]["history"]
        before_ids = {record["operation_id"] for record in before_history}
        row["audit_observation"] = {"before_records": len(before_history), "after_records": len(after_history),
                                    "new_retained_operation_ids": [record["operation_id"] for record in after_history if record["operation_id"] not in before_ids],
                                    "scope": "Complete histories retained in raw before/after native snapshots; failed-operation audits may append; no history-equality/eviction claim"}
        self.flush()  # Retain complete observations before assertions.
        if error_code is None:
            assert "error" not in row, (label, row.get("error"))
        else:
            assert row.get("error", {}).get("code") == error_code, (label, row.get("error"))
        assert self.authored(row["before"], omit_work_quaternion=quaternion_write) == self.authored(
            row["after"], omit_work_quaternion=quaternion_write), (label, "Declared authored/context/identity preservation failed")
        if precheckpoint:
            for field in ("checkpoints", "checkpoint_calls", "scene_custom"):
                assert row["before"]["native"][field] == row["after"]["native"][field], (label, field)
            assert row["assignment_observations_before"] == row["assignment_observations_after"]
        return row

    def preview(self, label: str, requested: tuple[float, ...], *, linked: bool = True) -> dict[str, Any]:
        reference = self.call(label + "_reference", "task.reference.resolve", {"source": "objects", "object_names": [self.work.name]})["result"]
        params = {"reference_id": reference["reference_id"], "expected_revision": self.store.require_plan()["revision"],
                  "rotation_quaternion": list(requested)}
        if linked:
            params["step_id"] = STEP
        return self.call(label + "_preview", "task.plan.preview_transform", params)["result"]

    def direct(self, label: str, requested: tuple[float, ...]) -> dict[str, Any]:
        before = channels(self.work)
        expected, norms = independent_expected(before, requested)
        row = {"label": label, "kind": "direct_registered_set", "requested_wxyz": requested,
               "requested_float64_le": double_bits(requested), "before_channels": before,
               "expected_channels": expected, "expected_float32_le": bits(expected), "norms": norms}
        self.data["vector_cases"].append(row)
        self.flush()
        call = self.call(label, "transform.set", {"object_name": self.work.name, "rotation_quaternion": list(requested)},
                         precheckpoint=False, quaternion_write=True)
        row["after_channels"], row["after_float32_le"] = channels(self.work), bits(channels(self.work))
        observed = self.assignment_rows[call["assignment_observations_before"]:call["assignment_observations_after"]]
        row["immediate_observations"] = copy.deepcopy(observed)
        self.flush()
        assert len(observed) == 1 and observed[0]["immediate_float32_le"] == bits(expected)
        assert self.authored(observed[0]["before_state"], omit_work_quaternion=True) == self.authored(
            observed[0]["immediate_state"], omit_work_quaternion=True)
        assert row["after_float32_le"] == bits(expected)
        return row

    def workflow(self, label: str, requested: tuple[float, ...]) -> dict[str, Any]:
        before = channels(self.work)
        expected, norms = independent_expected(before, requested)
        row = {"label": label, "kind": "registered_artist_step", "requested_wxyz": requested,
               "requested_float64_le": double_bits(requested), "before_channels": before,
               "expected_channels": expected, "expected_float32_le": bits(expected), "norms": norms}
        self.data["vector_cases"].append(row)
        self.flush()  # Prediction precedes reference, preview, apply and verification.
        preview = self.preview(label, requested)
        canonical = copy.deepcopy(self.store.previews[preview["preview_id"]]["params"])
        row["preview"], row["canonical_request"] = preview, canonical
        row["canonical_requested_float64_le"] = double_bits(canonical["rotation_quaternion"])
        self.flush()
        assert set(canonical) == {"object_name", "rotation_quaternion"} and canonical["object_name"] == self.work.name
        assert row["canonical_requested_float64_le"] == row["requested_float64_le"]
        assert preview["target_expectation"]["expected_float32_le"] == bits(expected)
        assert preview["target_expectation"]["before_float32_le"] == bits(before)
        applied = self.call(label + "_apply", "task.plan.apply_preview", {"preview_id": preview["preview_id"],
            "expected_revision": self.store.require_plan()["revision"]}, precheckpoint=False, quaternion_write=True)
        row["applied"], row["after_channels"] = applied["result"], channels(self.work)
        row["after_float32_le"] = bits(row["after_channels"])
        observed = self.assignment_rows[applied["assignment_observations_before"]:applied["assignment_observations_after"]]
        row["immediate_observations"] = copy.deepcopy(observed)
        self.flush()
        assert len(observed) == 1 and observed[0]["immediate_float32_le"] == bits(expected)
        assert self.authored(observed[0]["before_state"], omit_work_quaternion=True) == self.authored(
            observed[0]["immediate_state"], omit_work_quaternion=True)
        assert row["after_float32_le"] == bits(expected)
        receipt = applied["result"]["step_receipt_id"]
        verified = self.call(label + "_verify", "task.plan.verify_transform", {"step_id": STEP, "receipt_id": receipt,
                             "expected_revision": self.store.require_plan()["revision"]})["result"]
        row["verification"] = verified
        self.flush()
        observation = verified["target_observation"]
        assert observation["status"] == "channels_match" and observation["expected_float32_le"] == bits(expected)
        assert observation["observed_float32_le"] == bits(expected) and observation["differences"] == []
        assert observation["user_goal_verified"] is False and verified["current_scene_verified"] is False
        assert self.store.require_plan()["steps"][0]["status"] == "pending"
        return row


def main() -> None:
    from blender_artist_quaternion_storage_smoke import owned_profile
    from blender_artist_target_verification_smoke import object_schema, object_state, stored_context
    from blender_codex_bridge.command_queue import QueuedRequest
    from blender_codex_bridge.protocol import Request
    from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime
    from blender_codex_bridge.tools import transforms

    folder, process_token, attestation = owned_profile()
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
    scene, layer = bpy.context.scene, bpy.context.scene.view_layers[0]
    mesh = bpy.data.meshes.new("Registered Quaternion Geometry")
    mesh.from_pydata([(0., 0., 0.), (.75, 0., 0.), (0., .5, 0.)], [], [(0, 1, 2)])
    mesh.update()
    work = bpy.data.objects.new(WORK, mesh)
    scene.collection.objects.link(work)
    work.rotation_mode = "QUATERNION"
    work.location, work.scale = (.125, -.25, .5), (1.25, .75, -1.)
    work.rotation_euler, work.rotation_axis_angle = (.125, -.25, .5), (.75, 0., 1., -0.)
    work.rotation_quaternion = (.5, .5, .5, .5)
    work.lock_rotation, work.lock_rotation_w, work.lock_rotations_4d = (False, False, False), False, False
    protected = bpy.data.objects["Cube"]
    layer.update()
    for obj in layer.objects:
        obj.select_set(False, view_layer=layer)
    protected.select_set(True, view_layer=layer)
    layer.objects.active = protected
    layer.update()
    settled = stored_context(scene, layer)
    assert settled == stored_context(scene, layer) and settled["active"] == protected.name
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission not in {Permission.EXECUTE_PYTHON, Permission.SAVE_PROJECT,
                                                   Permission.ACCESS_EXTERNAL_FILES} for permission in Permission}
    manager = PermissionManager(lambda: dict(grants))
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("objects")
    runtime.registry.enable_toolset("batch")
    proof = Proof(runtime, scene, layer, work, protected, folder, attestation, process_token)
    original_assignment = transforms.apply_assignments
    original_before, original_after = runtime.checkpoints.before_modification, runtime.checkpoints.after_modification

    def before(method: str, **kwargs: Any) -> Any:
        proof.checkpoint_calls.append("before:" + method)
        return proof.checkpoint_delegate("before", method, original_before, kwargs)

    def after(method: str, **kwargs: Any) -> Any:
        proof.checkpoint_calls.append("after:" + method)
        return proof.checkpoint_delegate("after", method, original_after, kwargs)

    def observe_assignment(obj: Any, assignments: Any, **kwargs: Any) -> Any:
        row = {"object": obj.name, "assignments": [{"field": item.name, "value": item.value} for item in assignments],
               "before_channels": channels(obj), "before_float32_le": bits(channels(obj)), "before_state": proof.snapshot(),
               "fault_requested": proof.fault_after_assignment}
        proof.assignment_rows.append(row)
        proof.flush()
        result = original_assignment(obj, assignments, **kwargs)
        row["immediate_channels"], row["immediate_float32_le"] = channels(obj), bits(channels(obj))
        row["immediate_state"] = proof.snapshot()
        proof.flush()
        if proof.fault_after_assignment:
            proof.fault_after_assignment = False
            row["injected_after_actual_assignment"] = True
            proof.flush()
            raise RuntimeError("Fixture-only post-assignment quaternion failure under live authority")
        return result

    transforms.apply_assignments = observe_assignment
    runtime.checkpoints.before_modification, runtime.checkpoints.after_modification = before, after
    try:
        proof.data["initial_state"], proof.data["provided_native_schema"] = proof.snapshot(), object_schema(work)
        protected_baseline = object_state(protected)
        proof.data["permissions"] = dict(grants)
        proof.data["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
            Path(__file__), ROOT / "scripts/blender_artist_quaternion_storage_smoke.py",
            ROOT / "scripts/blender_artist_target_verification_smoke.py", ROOT / "scripts/native_character_evidence.py",
            ROOT / "scripts/blender_artist_sidebar_smoke.py", ROOT / "addon/blender_codex_bridge/tools/transforms.py",
            ROOT / "addon/blender_codex_bridge/tools/artist_loop.py", ROOT / "addon/blender_codex_bridge/artist_target_intent.py",
            ROOT / "addon/blender_codex_bridge/tools/_artist_checkpoint_admission.py",
            ROOT / "addon/blender_codex_bridge/tools/_scene_checkpoint_roles.py",
            ROOT / "addon/blender_codex_bridge/tools/_scene_mutation.py", ROOT / "addon/blender_codex_bridge/checkpoints.py")}
        proof.flush()
        for method in ("batch.plan", "batch.execute"):
            refusal = proof.call("prearmed_" + method.replace(".", "_") + "_quaternion_refused", method,
                {"steps": [{"method": "transform.set", "params": {"object_name": work.name,
                 "rotation_quaternion": list(requests()[0][1])}}]}, error_code="NOT_IMPLEMENTED")
            context = refusal["error"]["context"]
            assert context["execution_started"] is False and context["checkpoint_batch_composition_reviewed"] is False
            assert context["method"] == "transform.set" and context["parameter"] == "rotation_quaternion" and context["step_index"] == 0
        proof.direct("prearmed_direct_new_field", requests()[0][1])
        grants[Permission.TRANSFORM_OBJECTS.value] = False
        try:
            proof.call("prearmed_permission_denied", "transform.set", {"object_name": work.name,
                       "rotation_quaternion": list(requests()[1][1])}, error_code="PERMISSION_DENIED")
        finally:
            grants[Permission.TRANSFORM_OBJECTS.value] = True
        invalid = (("wrong_length", [1., 0., 0.], "INVALID_ARGUMENT"),
                   ("bool_component", [True, 0., 0., 0.], "INVALID_ARGUMENT"),
                   ("nonunit", [.5, 0., 0., 0.], "INVALID_ARGUMENT"),
                   ("zero_norm", [0., 0., 0., 0.], "INVALID_ARGUMENT"),
                   ("subnormal", [1., 1e-40, 0., 0.], "NOT_IMPLEMENTED"),
                   ("component_range", [1.01, 0., 0., 0.], "NOT_IMPLEMENTED"))
        for label, value, code in invalid:
            proof.call("prearmed_" + label, "transform.set", {"object_name": work.name, "rotation_quaternion": value}, error_code=code)
        for field, value in (("rotation", [0., 0., 0.]), ("rotation_euler", [0., 0., 0.]),
                             ("rotation_mode", "QUATERNION"), ("rotation_mode", None)):
            proof.call("prearmed_mixed_" + field + "_" + str(value), "transform.set", {"object_name": work.name,
                       "rotation_quaternion": list(requests()[0][1]), field: value}, error_code="INVALID_ARGUMENT")
        before_mode_control = channels(work)
        work.rotation_mode = "XYZ"
        layer.update()
        proof.control("raw_wrong_mode_refusal_setup", {"rotation_mode": "XYZ"})
        try:
            proof.call("prearmed_wrong_mode", "transform.set", {"object_name": work.name,
                       "rotation_quaternion": list(requests()[0][1])}, error_code="NOT_IMPLEMENTED")
        finally:
            # Restore this fixture-owned profile control, including native mode
            # aliases, independently of any bridge compensation under test.
            for field in ("rotation_mode", "location", "rotation_euler", "rotation_axis_angle", "scale", "rotation_quaternion"):
                setattr(work, field, before_mode_control[field])
            layer.update()
            proof.control("raw_wrong_mode_control_restored", {"before_control_channels": before_mode_control,
                          "after_restoration_channels": channels(work), "after_restoration_float32_le": bits(channels(work))})
            assert bits(channels(work)) == bits(before_mode_control)
        for field, value in (("lock_rotation", (True, False, False)), ("lock_rotation_w", True), ("lock_rotations_4d", True)):
            setattr(work, field, value)
            proof.control("raw_lock_refusal_setup", {"field": field, "value": value})
            try:
                proof.call("prearmed_" + field, "transform.set", {"object_name": work.name,
                           "rotation_quaternion": list(requests()[0][1])}, error_code="NOT_IMPLEMENTED")
            finally:
                setattr(work, field, (False, False, False) if field == "lock_rotation" else False)
                proof.control("raw_lock_control_restored", {"field": field})
        shared = bpy.data.objects.new("Quaternion Shared Mesh Refusal Control", mesh)
        scene.collection.objects.link(shared)
        layer.update()
        proof.control("raw_shared_data_refusal_setup", {"object": shared.name, "data_users": mesh.users})
        try:
            proof.call("prearmed_shared_data", "transform.set", {"object_name": work.name,
                       "rotation_quaternion": list(requests()[0][1])}, error_code="NOT_IMPLEMENTED")
        finally:
            bpy.data.objects.remove(shared, do_unlink=True)
            layer.update()
            proof.control("raw_fixture_owned_shared_control_removed", {"data_users": mesh.users})
        proof.call("set_artist_plan", "task.plan.set", {"goal": "Set and verify bounded quaternion channels while preserving Cube",
                   "steps": [{"id": STEP, "description": "Preview and verify quaternion channel intent"}], "protected_objects": [protected.name]})
        proof.call("arm_artist_plan", "task.plan.enforce", {"enabled": True, "expected_revision": proof.store.require_plan()["revision"]})
        denied = proof.preview("armed_permission", requests()[2][1])
        grants[Permission.TRANSFORM_OBJECTS.value] = False
        try:
            proof.call("armed_apply_permission_denied", "task.plan.apply_preview", {"preview_id": denied["preview_id"],
                       "expected_revision": proof.store.require_plan()["revision"]}, error_code="PERMISSION_DENIED")
        finally:
            grants[Permission.TRANSFORM_OBJECTS.value] = True
        invalid_reference = proof.call("invalid_preview_reference", "task.reference.resolve", {
            "source": "objects", "object_names": [work.name]})["result"]
        for label, extra in (("nonunit", {"rotation_quaternion": [.5, 0., 0., 0.]}),
                             ("mixed_mode", {"rotation_quaternion": list(requests()[0][1]), "rotation_mode": "QUATERNION"})):
            proof.call("armed_preview_" + label, "task.plan.preview_transform", {
                "reference_id": invalid_reference["reference_id"], "expected_revision": proof.store.require_plan()["revision"],
                "step_id": STEP, **extra}, error_code="INVALID_ARGUMENT")
        for label, requested in requests():
            proof.workflow(label, requested)
        successful = [row for row in proof.data["vector_cases"] if row["kind"] == "registered_artist_step"]
        replay = successful[-1]["preview"]["preview_id"]
        proof.call("consumed_preview_replay", "task.plan.apply_preview", {"preview_id": replay,
                   "expected_revision": proof.store.require_plan()["revision"]}, error_code="INVALID_ARGUMENT")
        stale = proof.preview("stale_before_registered_writer", requests()[0][1])
        proof.direct("intervening_registered_writer", requests()[3][1])
        proof.call("stale_after_registered_writer", "task.plan.apply_preview", {"preview_id": stale["preview_id"],
                   "expected_revision": proof.store.require_plan()["revision"]}, error_code="INVALID_ARGUMENT")
        for fault in ("cancel", "disconnect"):
            preview = proof.preview("lifetime_" + fault, requests()[2][1])
            params = {"preview_id": preview["preview_id"], "expected_revision": proof.store.require_plan()["revision"]}
            lifetime, connection = RequestLifetime.local(), ConnectionLifetime()
            lifetime.connection = connection
            request = Request(id="quaternion-" + fault, method="task.plan.apply_preview", params=params, _lifecycle=lifetime)
            queued = QueuedRequest(request)
            assert queued.try_start()
            fired: list[bool] = []

            def lifetime_state(queued: Any = queued, lifetime: Any = lifetime,
                               connection: Any = connection, request: Any = request) -> dict[str, Any]:
                with queued._lock:
                    queued_flags = {"state": queued._state, "stop_requested": queued._stop_requested}
                return {"queued": {**queued_flags, "completed": queued.completed.is_set(),
                                   "response": None if queued.response is None else queued.response.to_dict(),
                                   "deadline": queued.deadline},
                        "request": {"id": request.id, "method": request.method,
                                    "delivered": lifetime.delivered.is_set(), "rejected": lifetime.rejected.is_set(),
                                    "deadline": lifetime.deadline if math.isfinite(lifetime.deadline) else None,
                                    "connection_disconnected": connection.disconnected.is_set()}}

            lifetime_row = {"kind": fault, "before": lifetime_state(),
                            "scope": "Actual running QueuedRequest cooperative boundary; executor called directly, no transport/handoff/completion claim"}
            proof.data["lifetime_cases"].append(lifetime_row)
            proof.flush()

            def interruption(fault: str = fault, fired: list[bool] = fired, queued: Any = queued,
                             connection: Any = connection, lifetime_row: dict[str, Any] = lifetime_row,
                             lifetime_state: Any = lifetime_state) -> dict[str, bool]:
                if not fired:
                    fired.append(True)
                    lifetime_row["provider_before"] = lifetime_state()
                    if fault == "cancel":
                        lifetime_row["cancel_pending_returned"] = queued.cancel_pending(
                            BridgeError("TIMEOUT", "Fixture canceled this bounded quaternion request"))
                    else:
                        connection.disconnected.set()
                    lifetime_row["provider_after"] = lifetime_state()
                    proof.flush()
                return dict(grants)

            manager._source = interruption
            try:
                proof.call("apply_" + fault + "_before_write", "task.plan.apply_preview", params, error_code="TIMEOUT",
                           invoke=lambda request=request, queued=queued: runtime.executor.execute_request(request, check_cancelled=queued.check_active))
                assert fired
            finally:
                manager._source = lambda: dict(grants)
                lifetime_row["after"], lifetime_row["provider_calls_fired"] = lifetime_state(), len(fired)
                proof.flush()
        no_step = proof.preview("no_step_canonical_origin", requests()[1][1], linked=False)
        cached = proof.store.previews[no_step["preview_id"]]
        mutation: list[dict[str, Any]] = []

        def mutate_cached_zero() -> dict[str, bool]:
            if not mutation:
                record = {"before": double_bits(cached["params"]["rotation_quaternion"])}
                cached["params"]["rotation_quaternion"][2] = 0.
                record["after"] = double_bits(cached["params"]["rotation_quaternion"])
                mutation.append(record)
                proof.control("fixture_only_no_step_cached_param_zero_sign_mutation_inside_apply_permission_source", record)
            return dict(grants)

        manager._source = mutate_cached_zero
        try:
            proof.call("no_step_canonical_zero_sign_refused", "task.plan.apply_preview", {"preview_id": no_step["preview_id"],
                       "expected_revision": proof.store.require_plan()["revision"]}, error_code="INVALID_ARGUMENT")
            assert mutation and no_step["preview_id"] in proof.store.previews
        finally:
            manager._source = lambda: dict(grants)
        identity_preview = proof.preview("no_step_intent_identity", requests()[1][1], linked=False)
        identity_cached = proof.store.previews[identity_preview["preview_id"]]
        original_intent = identity_cached["target_intent"]
        original_params = copy.deepcopy(identity_cached["params"])
        intent_mutation: list[dict[str, Any]] = []

        def replace_cached_intent() -> dict[str, bool]:
            if not intent_mutation:
                replacement = replace(original_intent)
                identity_cached["target_intent"] = replacement
                record = {"original_python_identity": id(original_intent), "replacement_python_identity": id(replacement),
                          "original_plain_value": asdict(original_intent), "replacement_plain_value": asdict(replacement),
                          "equal_value": replacement == original_intent, "same_identity": replacement is original_intent,
                          "canonical_params_before": original_params, "canonical_params_after": copy.deepcopy(identity_cached["params"]),
                          "canonical_q_before_float64_le": double_bits(original_params["rotation_quaternion"]),
                          "canonical_q_after_float64_le": double_bits(identity_cached["params"]["rotation_quaternion"])}
                intent_mutation.append(record)
                proof.control("fixture_only_no_step_equal_value_intent_identity_replaced_inside_apply_permission_source", record)
            return dict(grants)

        manager._source = replace_cached_intent
        try:
            proof.call("no_step_replaced_intent_identity_refused", "task.plan.apply_preview", {"preview_id": identity_preview["preview_id"],
                       "expected_revision": proof.store.require_plan()["revision"]}, error_code="INVALID_ARGUMENT")
            assert intent_mutation and identity_preview["preview_id"] in proof.store.previews
            assert intent_mutation[0]["equal_value"] is True and intent_mutation[0]["same_identity"] is False
            assert intent_mutation[0]["canonical_q_before_float64_le"] == intent_mutation[0]["canonical_q_after_float64_le"]
        finally:
            manager._source = lambda: dict(grants)
        proof.direct("prepare_signed_zero_compensation", requests()[1][1])
        requested = (math.sqrt(.5), math.sqrt(.5), 0., -0.)
        before_fault = channels(work)
        expected_fault, norms = independent_expected(before_fault, requested)
        preview = proof.preview("measured_compensation", requested)
        proof.data["measured_compensation"] = {"requested_wxyz": requested, "norms": norms,
            "before_channels": before_fault, "before_float32_le": bits(before_fault),
            "expected_immediate_channels": expected_fault, "expected_immediate_float32_le": bits(expected_fault),
            "scope": "One live-authority post-assignment failure; exact measured authored compensation only"}
        proof.flush()
        assert bits(before_fault) != bits(expected_fault) and before_fault == expected_fault
        proof.fault_after_assignment = True
        try:
            compensated = proof.call("post_assignment_signed_zero_failure", "task.plan.apply_preview", {"preview_id": preview["preview_id"],
                "expected_revision": proof.store.require_plan()["revision"]}, error_code="OPERATION_FAILED", precheckpoint=False)
        finally:
            proof.fault_after_assignment = False
        observed = proof.assignment_rows[compensated["assignment_observations_before"]:compensated["assignment_observations_after"]]
        proof.data["measured_compensation"].update(after_channels=channels(work), after_float32_le=bits(channels(work)),
                                                actual_error=compensated["error"], immediate_observations=copy.deepcopy(observed))
        proof.flush()
        assert len(observed) == 1 and observed[0]["injected_after_actual_assignment"]
        assert observed[0]["before_float32_le"] == bits(before_fault)
        assert observed[0]["immediate_float32_le"] == bits(expected_fault)
        assert proof.authored(observed[0]["before_state"], omit_work_quaternion=True) == proof.authored(
            observed[0]["immediate_state"], omit_work_quaternion=True)
        assert bits(channels(work)) == bits(before_fault) and compensated["error"]["context"]["rollback_verified"] is True
        assert object_state(protected) == protected_baseline
        final = proof.call("final_plan_inspection", "task.plan.inspect", {})["result"]
        proof.data["final_plan_inspection"] = final
        assert final["protected_scope_enforced"] and final["plan"]["steps"][0]["status"] == "pending"
        assert final["step_evidence"]["scope"] == "protected_objects_only" and final["step_evidence"]["user_goal_verified"] is False
        proof.data["final_state"] = proof.snapshot()
        assert proof.authored(proof.data["initial_state"], omit_work_quaternion=True) == proof.authored(
            proof.data["final_state"], omit_work_quaternion=True)
        proof.data["completed"] = True
        proof.flush()
        print("BLENDER_ARTIST_QUATERNION_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "evidence_file": str(proof.path),
            "evidence_sha256": hashlib.sha256(proof.path.read_bytes()).hexdigest(), "qualified_step_vectors": 7,
            "all_six_authored_core_bits_verified": True, "canonical_requested_double_bits_preserved": True,
            "immediate_native_reads_retained": True, "declared_protected_mesh_context_identity_preserved": True,
            "known_native_checkpoint_particle_role_single_edge_exception": True,
            "measured_signed_zero_compensation": True, **proof.data["limits"]}, allow_nan=False), flush=True)
    except BaseException as error:
        proof.data["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        proof.flush()
        raise
    finally:
        transforms.apply_assignments = original_assignment
        runtime.checkpoints.before_modification, runtime.checkpoints.after_modification = original_before, original_after


if __name__ == "__main__":
    from blender_artist_quaternion_storage_smoke import owned_profile

    owned_profile()
    from blender_artist_sidebar_smoke import owned_process_exit

    exit_code = 1
    try:
        main()
        exit_code = 0
    except BaseException:
        traceback.print_exc()
    finally:
        owned_process_exit(exit_code)
