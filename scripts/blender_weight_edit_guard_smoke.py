"""Opt-in registered direct-weight native fixture; root qualifies each source.

Launch through run_blender_checks.py. The production reader is never replaced.
A pending native gate is a failed fixture, not a success or accepted limitation.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import time
import traceback
from pathlib import Path
from types import WrapperDescriptorType

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]


def bits(value):
    return struct.pack("<f", value).hex()


def id_facts(owner):
    return [owner.bl_rna.identifier, owner.name, int(owner.as_pointer()), int(owner.session_uid),
            int(owner.users), bool(owner.use_fake_user), bool(owner.use_extra_user),
            owner.library is not None, owner.override_library is not None]


def snapshot(obj):
    # Independent bounded authored projection. This is not a raw Main/cache proof.
    mapping = bpy.data.user_map(subset={obj, obj.data})
    return {"object": id_facts(obj), "mesh": id_facts(obj.data),
            "consumers": [[id_facts(owner), sorted(id_facts(x) for x in mapping.get(owner, set()))]
                          for owner in (obj, obj.data)],
            "groups": [[g.name, g.index, int(g.as_pointer()), bool(g.lock_weight)] for g in obj.vertex_groups],
            "memberships": [sorted([[g.group, bits(g.weight)] for g in v.groups]) for v in obj.data.vertices],
            "positions": [[bits(x) for x in v.co] for v in obj.data.vertices],
            "edges": [list(e.vertices) for e in obj.data.edges],
            "polygons": [list(p.vertices) for p in obj.data.polygons],
            "transforms": [[bits(x) for x in getattr(obj, field)] for field in
                           ("location", "rotation_euler", "scale", "delta_location", "delta_rotation_euler", "delta_scale")],
            "materials": [id_facts(x) if x is not None else None for x in obj.data.materials]}


def field_differences(before, after, *, limit=128):
    """Bounded diagnostic paths; full original projections remain in the report."""
    assert type(limit) is int and 1 <= limit <= 128
    entries, truncated = [], False

    def visit(left, right, path):
        nonlocal truncated
        if left == right:
            return
        if len(entries) >= limit:
            truncated = True
            return
        if type(left) is dict and type(right) is dict and set(left) == set(right):
            for key in sorted(left):
                visit(left[key], right[key], path + "." + key)
        elif type(left) is list and type(right) is list and len(left) == len(right):
            for index, (a, b) in enumerate(zip(left, right, strict=True)):
                visit(a, b, path + "[" + str(index) + "]")
        else:
            entries.append({"path": path, "before": left, "after": right})

    visit(before, after, "$")
    return {"entries": entries, "truncated": truncated}


def nonmemberships(value):
    return {key: item for key, item in value.items() if key != "memberships"}


def preparation_snapshot(obj):
    scene = bpy.context.scene
    mapping = bpy.data.user_map(subset={scene})
    return {"target": snapshot(obj), "scene_header": id_facts(scene),
            "scene_consumers": sorted(id_facts(x) for x in mapping.get(scene, set())),
            "scene_self_references": int(scene.user_of_id(scene)),
            "window_manager_roles": [
                {"header": id_facts(wm), "scene_reference_count": int(wm.user_of_id(scene)),
                 "windows": [{"pointer": int(window.as_pointer()), "scene_header": id_facts(window.scene),
                              "workspace_pointer": int(window.workspace.as_pointer()),
                              "screen_pointer": int(window.screen.as_pointer())} for window in wm.windows]}
                for wm in bpy.data.window_managers]}


class WriteBoundaryObserver:
    """One external event after an unchanged genuine native-call wrapper.

    Blender bpy_func is a custom tp_call, not PyCFunctionObject; profile C-return
    events do not qualify its execution. Exact wrapper completion plus independent
    complete Float32 state is the evidence here. No native callable is replaced.
    """

    def __init__(self, leaf_type, method_type, expected_arguments, action):
        self.leaf_type, self.method_type = leaf_type, method_type
        self.code = vars(leaf_type)["__call__"].__code__
        self.slot = vars(method_type).get("__call__")
        assert type(self.slot) is WrapperDescriptorType and self.slot.__objclass__ is method_type
        self.expected_arguments, self.action = expected_arguments, action
        self.armed, self.entered, self.failed, self.completed = True, False, False, False
        self.frame_id = None
        self.record = {"wrapper_calls": 0, "wrapper_returns": 0, "wrapper_exceptions": 0,
                       "observed_C_return_events": False, "native_callable_replaced": False,
                       "external_event_triggered": False, "leaf_released_before_external_event": False}
        self.previous_profile = self.previous_trace = None

    def __enter__(self):
        self.previous_profile, self.previous_trace = sys.getprofile(), sys.gettrace()
        if self.previous_profile is not None or self.previous_trace is not None:
            raise RuntimeError("The owned fixture requires an unused profiling/trace boundary")
        sys.settrace(self.trace)
        sys.setprofile(self.profile)
        return self

    def __exit__(self, *_exception):
        sys.setprofile(self.previous_profile)
        sys.settrace(self.previous_trace)

    def trace(self, frame, event, _argument):
        if frame.f_code is self.code:
            if event == "exception":
                self.failed = True
                self.record["wrapper_exceptions"] += 1
            return self.trace
        return None

    def profile(self, frame, event, _argument):
        if not self.armed or frame.f_code is not self.code:
            return
        if event == "call":
            assert not self.entered and vars(self.leaf_type)["__call__"].__code__ is self.code
            leaf = frame.f_locals["self"]
            method = leaf.method
            assert type(leaf) is self.leaf_type and type(method) is self.method_type
            assert vars(type(method)).get("__call__") is self.slot
            assert leaf.arguments == self.expected_arguments
            self.frame_id, self.entered = id(frame), True
            self.record.update(wrapper_calls=1, native_method_identity=id(method),
                               native_method_type=self.method_type.__name__, native_call_slot_identity=id(self.slot),
                               arguments=leaf.arguments)
            method = leaf = None
        elif event == "return":
            assert self.entered and id(frame) == self.frame_id
            self.record["wrapper_returns"] += 1
            if self.failed:
                return
            leaf = frame.f_locals["self"]
            assert leaf.method is None and frame.f_locals.get("method") is None
            self.record["leaf_released_before_external_event"] = True
            leaf = None
            self.armed, self.completed = False, True
            # The action is a declared external failure/manual event; it must not
            # run with this observer or a retained native method/owner handle.
            sys.setprofile(self.previous_profile)
            sys.settrace(self.previous_trace)
            self.record["external_event_triggered"] = True
            self.action()


class InjectedAfterWeightWrite(RuntimeError):
    """Declared fixture failure after the first measured native write."""


def adverse_case(runtime, prefs, obj, native_leaf_type, case, row):
    from blender_codex_bridge.errors import BridgeError

    assert case in {"after_write_failure", "permission_revoked", "foreign_membership"}
    original_permission = prefs.allow_edit_mesh
    assert original_permission is True
    target_weight = .625 if case == "foreign_membership" else .75
    before, at_boundary = snapshot(obj), []
    row.update(before=before, boundary_observations=at_boundary, verification_completed=False)
    expected = json.loads(json.dumps(before))
    assert before["memberships"][0][0][1] != bits(target_weight)
    expected["memberships"][0][0][1] = bits(target_weight)
    row["independent_expected_first_write"] = expected
    arguments = ((0,), target_weight, "REPLACE")
    method = obj.vertex_groups["A"].add
    method_type = type(method)
    method = None

    def external_event():
        observed = snapshot(obj)
        # Retain the complete observation BEFORE asserting or injecting an event.
        at_boundary.append(observed)
        row["first_write_difference"] = field_differences(expected, observed)
        assert observed == expected  # Independent proof of the first actual native write.
        if case == "after_write_failure":
            raise InjectedAfterWeightWrite("Owned fixture injected failure after native wrapper completion")
        if case == "permission_revoked":
            prefs.allow_edit_mesh = False
        else:
            # This separate manual event is outside the tool's owned A membership.
            obj.vertex_groups["B"].add((2,), .375, "REPLACE")

    observer = WriteBoundaryObserver(native_leaf_type, method_type, arguments, external_event)
    row["observer"] = observer.record
    failure = None
    started = time.monotonic()
    try:
        with observer:
            try:
                runtime.dispatch("weights.assign", {"object_name": obj.name, "group_name": "A",
                    "vertex_indices": [0, 1], "weight": target_weight})
            except BridgeError as error:
                failure = error
    finally:
        prefs.allow_edit_mesh = original_permission  # Actual local grant, not a replacement provider.
        row["elapsed_seconds"] = time.monotonic() - started
        row["after"] = snapshot(obj)
        row["before_after_difference"] = field_differences(before, row["after"])
        row["operation_history"] = runtime.state.history(1)
        if failure is not None:
            row.update(structured_error=failure.to_dict(), recovery_evidence=failure.context.get("recovery_evidence"))
    assert sys.getprofile() is None and sys.gettrace() is None
    assert observer.completed and observer.record["wrapper_calls"] == observer.record["wrapper_returns"] == 1
    assert observer.record["wrapper_exceptions"] == 0 and len(at_boundary) == 1
    assert failure is not None, "The adverse event did not stop its original registered call"
    evidence = failure.context["recovery_evidence"]
    assert evidence["owned_membership_attempts"] == 1
    after = row["after"]
    if case == "after_write_failure":
        assert after == before and failure.code == "OPERATION_FAILED"
        assert evidence["owned_membership_verified"] == evidence["restored_memberships"] == 1
        assert evidence["restoration_attempts"] == 1 and evidence["rollback_verified"] is True
        assert evidence["state_known"] is True and evidence["retained_partial"] is False
    else:
        if case == "foreign_membership":
            final_expected = json.loads(json.dumps(expected))
            final_expected["memberships"][2][1][1] = bits(.375)
            assert evidence["restoration_refused"] == "UNKNOWN_WRITE_RESULT"
            assert evidence["owned_membership_verified"] == 0
        else:
            final_expected = expected
            assert failure.code == "PERMISSION_DENIED" and evidence["restoration_refused"] == "AUTHORITY_LOST"
            # _member's provider-free _read verifies its complete first prefix.
            # The next _live calls the real permission provider and then stops.
            assert evidence["owned_membership_verified"] == 1
        row["independent_expected_final"] = final_expected
        row["final_expected_difference"] = field_differences(final_expected, after)
        assert after == final_expected
        assert evidence["restored_memberships"] == evidence["restoration_attempts"] == 0
        assert evidence["rollback_verified"] is False
        assert evidence["state_known"] is False and evidence["retained_partial"] is True
        assert evidence["observed_sha256"] is None
    history = row["operation_history"]
    assert len(history) == 1 and history[0]["tool"] == "weights.assign" and history[0]["success"] is False
    assert history[0]["recovery_evidence"] == evidence
    row.update(verification_completed=True, independent_Float32_memberships_and_consumers_verified=True,
               native_COW_notifier_effects_excluded=True)


def main():
    from blender_artist_quaternion_storage_smoke import owned_profile
    folder, process, attestation = owned_profile()
    from blender_artist_sidebar_smoke import owned_process_exit
    from blender_codex_bridge.errors import BridgeError
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime

    status, original_permissions = 1, None
    report = {"process_instance": process, "blender_version": bpy.app.version_string,
              "build_hash": bpy.app.build_hash.decode("ascii"), "profile": attestation,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "native_profile_qualified": False, "completed": False,
              "registered_methods": ["weights.assign", "weights.normalize"],
              "id_fact_fields": ["RNA_type", "name", "pointer", "session_UID", "users", "fake_user", "extra_user", "linked", "override"],
              "checkpoint_replaced": False, "production_reader_replaced": False,
              "project_saved": False, "windows_qualified": False, "cases": [],
              "native_recovery_qualified": False, "native_undo_qualified": False,
              "durable_backup_qualified": False, "cancel_disconnect_qualified": False,
              "limits": ["Explicit genuine native setup checkpoint precedes frozen weight intent; cold-context expanded preservation remains unqualified.",
                         "Exact original Object/Mesh/group identities, complete F32 memberships and declared consumers only.",
                         "Wrapper completion plus independent stored state, not direct native C-return profiling.",
                         "Injected external events are not passive native/provider-purity evidence.",
                         "Native method COW/dependency tags/notifiers, hidden caches and complete Main effects are not measured.",
                         "No manual native undo, transport cancellation/disconnect, rig deformation or constrained-memory qualification."]}
    path = folder / "weight-edit-guard-evidence.json"
    try:
        assert bpy.ops.preferences.addon_enable(module="blender_codex_bridge") == {"FINISHED"}
        prefs, runtime = get_preferences(), get_runtime()
        assert prefs is not None and prefs.auto_start is False
        original_permissions = {name: getattr(prefs, name) for name in ("allow_inspect_scene", "allow_edit_mesh")}
        prefs.allow_inspect_scene = prefs.allow_edit_mesh = True
        runtime.dispatch("toolsets.enable", {"name": "weights"})
        mesh = bpy.data.meshes.new("Owned Direct Weight Mesh")
        mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("Owned Direct Weight Target", mesh)
        bpy.context.scene.collection.children[0].objects.link(obj)
        for name, weight in (("A", .25), ("B", .25), ("Locked", .125)):
            group = obj.vertex_groups.new(name=name)
            group.add((0, 1, 2), weight, "REPLACE")
            group.lock_weight = name == "Locked"
        # Explicit native preparation precedes every frozen weight-call oracle.
        # It can synchronize the disposable context; cold-context preservation is
        # NOT qualified by the later warm calls. No after-tool baseline is adopted.
        preparation = {"phase": "DECLARED_GENUINE_NATIVE_CHECKPOINT_PREPARATION",
                       "before": preparation_snapshot(obj), "original_weight_intent_captured": False,
                       "cold_context_weight_preservation_qualified": False,
                       "known_source_effects": [
                           "core.checkpoint_create invokes the genuine CheckpointManager.create/_snapshot.",
                           "_snapshot stamps a Scene marker and calls genuine bpy.ops.ed.undo_push.",
                           "ED_undo_push tags the project modified and pushes the native undo stack.",
                           "BKE_undosys_step_push_with_type can create library-override operations and encode Main.",
                           "These are preparation effects, not a complete native side-effect inventory or weight-call preservation proof."]}
        report["preparation"] = preparation
        preparation["checkpoint"] = runtime.dispatch("checkpoint.create", {"description": "Direct-weight fixture preparation"})
        preparation["after"] = preparation_snapshot(obj)
        preparation["difference"] = field_differences(preparation["before"], preparation["after"])
        # Only the explicitly completed preparation establishes the fixture's
        # original request state. Every subsequent weight-call comparison is exact.
        before = snapshot(obj)
        request = {"object_name": obj.name, "group_name": "A", "vertex_indices": [0, 1], "weight": .5}
        started = time.monotonic()
        assign_row = {"case": "assign", "before": before, "verification_completed": False}
        report["cases"].append(assign_row)
        result = runtime.dispatch("weights.assign", request)
        after = snapshot(obj)
        assign_row.update(after=after, elapsed_seconds=time.monotonic() - started,
                          recovery_evidence=result["recovery_evidence"],
                          nonmembership_difference=field_differences(nonmemberships(before), nonmemberships(after)))
        assert after["memberships"] == [[[0, bits(.5)], [1, bits(.25)], [2, bits(.125)]],
                                         [[0, bits(.5)], [1, bits(.25)], [2, bits(.125)]],
                                         before["memberships"][2]]
        assert nonmemberships(before) == nonmemberships(after)
        assert result["recovery_evidence"]["owned_membership_verified"] == 2
        assign_row["verification_completed"] = True
        normalize_before = snapshot(obj)
        normalize_row = {"case": "normalize", "before": normalize_before, "verification_completed": False}
        report["cases"].append(normalize_row)
        normalized = runtime.dispatch("weights.normalize", {"object_name": obj.name,
            "group_names": ["A", "B"], "vertex_indices": [0, 1]})
        observed = snapshot(obj)
        normalize_row.update(after=observed, recovery_evidence=normalized["recovery_evidence"],
                             nonmembership_difference=field_differences(nonmemberships(normalize_before), nonmemberships(observed)))
        assert observed["memberships"] == [
            [[0, bits(7 / 12)], [1, bits(7 / 24)], [2, bits(.125)]]] * 2 + [normalize_before["memberships"][2]]
        assert nonmemberships(normalize_before) == nonmemberships(observed)
        normalize_row["verification_completed"] = True
        prefs.allow_edit_mesh = False
        denied_before = snapshot(obj)
        denied_row = {"case": "denied", "before": denied_before, "verification_completed": False}
        report["cases"].append(denied_row)
        denied_error = None
        try:
            runtime.dispatch("weights.assign", request)
        except BridgeError as error:
            denied_error = error
            denied_row["structured_error"] = error.to_dict()
        denied_row["after"] = snapshot(obj)
        denied_row["difference"] = field_differences(denied_before, denied_row["after"])
        assert denied_error is not None and denied_error.code == "PERMISSION_DENIED"
        assert denied_row["after"] == denied_before
        denied_row["verification_completed"] = True
        prefs.allow_edit_mesh = True
        from blender_codex_bridge.weight_edit_guard import _NativeLeaf
        original_edit_permission = prefs.allow_edit_mesh
        try:
            for case in ("after_write_failure", "permission_revoked", "foreign_membership"):
                row = {"case": case, "verification_completed": False}
                report["cases"].append(row)
                adverse_case(runtime, prefs, obj, _NativeLeaf, case, row)
        finally:
            prefs.allow_edit_mesh = original_edit_permission
        report.update(registered_membership_cases_completed=True, completed=True)
        status = 0
    except Exception as error:
        if isinstance(error, BridgeError):
            report["structured_error"] = error.to_dict()
        report["failure"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        if original_permissions is not None:
            for name, value in original_permissions.items():
                setattr(prefs, name, value)
        raw = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        with path.open("xb") as stream:
            stream.write(raw)
        if status == 0:
            print("BLENDER_WEIGHT_EDIT_GUARD_OK " + json.dumps({
                "blender_version": bpy.app.version_string, "evidence_file": str(path),
                "evidence_sha256": hashlib.sha256(raw).hexdigest(), "cases": len(report["cases"]),
                "native_profile_qualified": False, "complete_workflow_qualified": False}), flush=True)
        owned_process_exit(status)


if __name__ == "__main__":
    main()
