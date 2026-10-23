"""Bounded guarded surface publication and owned-cleanup native regression."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import surface_brushes  # noqa: E402


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(owner):
    return None if owner is None else [int(owner.as_pointer()), owner.name]


def mesh_values(mesh):
    """Read native state independently of the instrumented production helpers."""
    return {
        "identity": identity(mesh), "users": int(mesh.users),
        "coordinates": [list(vertex.co) for vertex in mesh.vertices],
        "vertices": [[bool(vertex.select), bool(vertex.hide)] for vertex in mesh.vertices],
        "edges": [[list(edge.vertices), bool(edge.select), bool(edge.hide)] for edge in mesh.edges],
        "loops": [int(loop.vertex_index) for loop in mesh.loops],
        "polygons": [[int(face.loop_start), int(face.loop_total), int(face.material_index),
                      bool(face.use_smooth), bool(face.select), bool(face.hide)] for face in mesh.polygons],
        "uv": [{"name": layer.name, "render": bool(layer.active_render),
                "values": [list(item.uv) for item in layer.data],
                "pins": [bool(item.pin_uv) for item in layer.data]} for layer in mesh.uv_layers],
        "uv_active": int(mesh.uv_layers.active_index),
        "colors": [{"name": attr.name, "identity": identity(attr), "domain": attr.domain,
                    "type": attr.data_type, "values": [list(item.color) for item in attr.data]}
                   for attr in mesh.color_attributes],
        "attributes": [{"name": attr.name, "identity": identity(attr), "domain": attr.domain,
                        "type": attr.data_type, "entries": len(attr.data),
                        "float_values": [float(item.value) for item in attr.data] if attr.data_type == "FLOAT" else None}
                       for attr in mesh.attributes],
        "color_roles": [int(mesh.color_attributes.active_color_index), int(mesh.color_attributes.render_color_index)],
    }


def object_values(obj):
    return {
        "identity": identity(obj), "data": identity(obj.data), "parent": identity(obj.parent),
        "location": list(obj.location), "rotation": list(obj.rotation_euler), "scale": list(obj.scale),
        "matrix": [list(row) for row in obj.matrix_world], "mode": obj.mode,
        "hidden": [bool(obj.hide_viewport), bool(obj.hide_render), bool(obj.hide_get())],
        "materials": [{"identity": identity(slot.material), "link": slot.link,
                       "diffuse": list(slot.material.diffuse_color) if slot.material is not None else None}
                      for slot in obj.material_slots],
        "mesh": mesh_values(obj.data) if obj.type == "MESH" else None,
    }


def snapshot(runtime):
    context, scene = bpy.context, bpy.context.scene
    return {
        "objects": {obj.name: object_values(obj) for obj in sorted(bpy.data.objects, key=lambda item: item.name)},
        "context": {"scene": identity(scene), "view_layer": [int(context.view_layer.as_pointer()), context.view_layer.name],
                    "window": None if context.window is None else int(context.window.as_pointer()),
                    "mode": context.mode, "active": identity(context.view_layer.objects.active),
                    "selected": sorted([identity(obj) for obj in context.selected_objects]),
                    "frame": [int(scene.frame_current), float(scene.frame_subframe)]},
        "bookkeeping": {"scene_marker": scene.get("_codex_bridge_undo_marker"),
                        "checkpoints": runtime.checkpoints.list(200)},
        "bridge_flags": {key: runtime.state.snapshot().get(key) for key in ("paused", "emergency_stopped")},
    }


def target_values(state, name):
    return state["objects"][name]["mesh"]


def paint_values(state, name):
    attrs = target_values(state, name)["colors"]
    found = [attr for attr in attrs if attr["name"] == "Paint"]
    return found[0]["values"] if found else None


def renamed_values(state, name):
    found = [attr for attr in target_values(state, name)["colors"] if attr["name"] == "Renamed"]
    return found[0]["values"] if found else None


def native_state(state):
    return {key: state[key] for key in ("objects", "context")}


def surrounding_state(state, target_name, method, *, provider_coordinates=False, shared_peer=None):
    """Exclude only requested domains and explicitly attributed provider effects."""
    result = copy.deepcopy(state)
    result.pop("bookkeeping")
    result.pop("bridge_flags")
    mesh = result["objects"][target_name]["mesh"]
    if method == "mesh.sculpt_brush" or provider_coordinates:
        mesh.pop("coordinates")
    if method == "color_attribute.create":
        mesh["colors"] = [attr for attr in mesh["colors"] if attr["name"] != "Paint"]
        for attr in mesh["colors"]:
            # CustomData layer wrappers are not durable IDs; adding a layer may
            # reallocate their addresses while retaining all stored values.
            attr.pop("identity")
    elif method == "color_attribute.rename":
        mesh["colors"] = [attr for attr in mesh["colors"] if attr["name"] not in {"Paint", "Renamed"}]
        for attr in mesh["colors"]:
            attr.pop("identity")
    elif method == "color_attribute.paint":
        for attr in mesh["colors"]:
            if attr["name"] == "Paint":
                attr.pop("values")
    elif method == "color_attribute.remove":
        for name in (target_name, shared_peer):
            if name is None:
                continue
            current = result["objects"][name]["mesh"]
            current["colors"] = [attr for attr in current["colors"] if attr["name"] != "Paint"]
            for attr in current["colors"]:
                attr.pop("identity")
            # Native removal may change active/render indices; they are reported,
            # not mistaken for geometry or unrelated-attribute preservation.
            current.pop("color_roles")
    if method in {"color_attribute.create", "color_attribute.rename", "color_attribute.remove"}:
        for name in (target_name, shared_peer):
            if name is None:
                continue
            current = result["objects"][name]["mesh"]
            current["attributes"] = [attr for attr in current["attributes"] if attr["name"] not in {"Paint", "Renamed"}]
            for attr in current["attributes"]:
                attr.pop("identity")
    return result


def make_pair(label, *, paint=True):
    mesh = bpy.data.meshes.new(label + " Mesh")
    mesh.from_pydata([(0., 0., 0.), (2., 0., 0.), (0., 2., 0.)], [], [(0, 1, 2)])
    mesh.update()
    uv = mesh.uv_layers.new(name="Protected UV")
    for item, value in zip(uv.data, ((0., 0.), (1., 0.), (0., 1.)), strict=True):
        item.uv = value
    guard = mesh.color_attributes.new(name="Protected Color", type="FLOAT_COLOR", domain="POINT")
    for item in guard.data:
        item.color = (.25, .5, .75, 1.)
    if paint:
        attr = mesh.color_attributes.new(name="Paint", type="FLOAT_COLOR", domain="POINT")
        for item in attr.data:
            item.color = (.125, .25, .5, 1.)
    material = bpy.data.materials.new(label + " Protected Material")
    material.diffuse_color = (.25, .5, .75, 1.)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(label, mesh)
    bpy.context.scene.collection.objects.link(obj)
    peer = bpy.data.objects.new(label + " Peer", mesh.copy())
    bpy.context.scene.collection.objects.link(peer)
    peer.location.x = 10.
    bpy.context.view_layer.update()
    return obj, peer


def allocation_defaults():
    """Retain actual native default pixels before any predicted-state assertion."""
    mesh = bpy.data.meshes.new("Owned Surface Defaults Mesh")
    mesh.from_pydata([(0., 0., 0.), (2., 0., 0.), (0., 2., 0.)], [], [(0, 1, 2)])
    mesh.update()
    obj = bpy.data.objects.new("Owned Surface Defaults", mesh)
    bpy.context.scene.collection.objects.link(obj)
    expected_rgba = [1., 1., 1., 1.]
    proof = {"blender_version": bpy.app.version_string, "fixture_setup_raw_native": True,
             "allocation_profile": "FLOAT_COLOR_WHITE_RGBA", "expected_rgba": expected_rgba,
             "project_saved": False, "release_acceptance": False, "mesh": identity(mesh), "attributes": []}
    path = Path(tempfile.gettempdir()) / "surface-color-allocation-defaults.json"
    for domain in ("POINT", "CORNER"):
        attr = mesh.color_attributes.new(name=domain + " Raw Defaults", type="FLOAT_COLOR", domain=domain)
        values = [list(item.color) for item in attr.data]
        proof["attributes"].append({"name": attr.name, "type": attr.data_type, "domain": attr.domain,
                                    "entries": len(attr.data), "values_before_assignment": values,
                                    "white_rgba_observed": values == [expected_rgba] * 3})
        # Flush after each allocation, before testing the observed values. A
        # later case failure must not erase evidence of the native defaults.
        path.write_text(json.dumps(proof, indent=2, allow_nan=False) + "\n")
    raw = path.read_bytes()
    print("BLENDER_SURFACE_ALLOCATION_DEFAULTS " + canonical({
        "evidence_file": str(path), "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "blender_version": bpy.app.version_string, "attributes": proof["attributes"],
    }), flush=True)
    assert all(item["type"] == "FLOAT_COLOR" and item["domain"] in {"POINT", "CORNER"}
               and item["entries"] == 3 and item["white_rgba_observed"] for item in proof["attributes"])
    return {"evidence_file": str(path), "evidence_sha256": hashlib.sha256(raw).hexdigest(), "observations": proof}


class PublicationProbe:
    """Observe final providers and enforce guarded publication and owned cleanup."""

    def __init__(self, runtime, grants):
        self.runtime, self.grants = runtime, grants
        self.phase = False
        self.read = False
        self.fired = False
        self.action = self.fault = None
        self.target = self.peer = None
        self.events = []
        self.control_provider_counts = {}
        self.provider_calls = self.phase_provider_calls = self.publication_number = 0
        self.publication_provider_counts = []
        self.trigger_ordinal = None
        self.trigger_publication = 1
        self.comparison_read_before_trigger = None
        self.scope_read = self.provider_before = self.provider_after = None
        self.fault_injected = False
        self.fault_state = self.primary_loss_error = None
        self.authority_regranted_before_raise = False

    def permission_values(self):
        if self.phase:
            self.provider_calls += 1
            self.phase_provider_calls += 1
            self.events.append(f"publication_{self.publication_number}_permission_provider_{self.phase_provider_calls}")
        if (self.phase and not self.fired and self.action is not None
                and self.publication_number == self.trigger_publication
                and self.phase_provider_calls == self.trigger_ordinal):
            self.fired = True
            self.comparison_read_before_trigger = self.read
            self.events.append("final_permission_provider_entered")
            self.provider_before = snapshot(self.runtime)
            if self.action == "PAUSE":
                self.runtime.state.set_paused(True)
            elif self.action == "COORDINATE":
                self.target.data.vertices[1].co.z = 2.
                self.target.data.update()
            elif self.action == "SHARE":
                self.peer.data = self.target.data
            elif self.action == "GENERIC_DESTINATION":
                name = "Renamed" if self.method == "color_attribute.rename" else "Paint"
                attr = self.target.data.attributes.new(name=name, type="FLOAT", domain="POINT")
                for item, value in zip(attr.data, (.125, .375, .625), strict=True):
                    item.value = value
            elif self.action == "CLEANUP_PIXELS":
                self.target.data.color_attributes["Paint"].data[0].color = (.75, .5, .25, 1.)
                self.target.data.update()
            elif self.action == "COLOR_ROLES":
                self.target.data.color_attributes.active_color_index = 1
                self.target.data.color_attributes.render_color_index = 1
            else:
                raise AssertionError("Unknown owned provider action")
            self.provider_after = snapshot(self.runtime)
            self.events.append("final_permission_provider_completed")
        return self.grants

    def install(self):
        self.original_publication = surface_brushes._publication
        self.original_preservation = surface_brushes._preservation
        self.original_gate = surface_brushes._gate

        def publication(*args, **kwargs):
            assert not self.phase, "The owned fixture does not permit nested publication"
            self.phase, self.read = True, False
            self.publication_number += 1
            self.phase_provider_calls = 0
            self.events.append("publication_entered")
            try:
                return self.original_publication(*args, **kwargs)
            finally:
                self.publication_provider_counts.append(self.phase_provider_calls)
                self.phase = False
                self.events.append("publication_exited")

        def preservation(*args, **kwargs):
            result = self.original_preservation(*args, **kwargs)
            if self.phase:
                self.scope_read = snapshot(self.runtime)
                self.read = True
                self.events.append("delegated_scope_read_completed")
            return result

        def gate(*args, **kwargs):
            result = self.original_gate(*args, **kwargs)
            if self.fault is None or self.fault_injected or self.phase or self.method != "color_attribute.create":
                return result
            attr = self.target.data.color_attributes.get("Paint")
            expected = [[.125, .25, .5, 1.]] * 3
            if attr is None or [list(item.color) for item in attr.data] != expected:
                return result
            # Production has independently verified/predicted this owned full
            # state before its post-initialization gate; no data reader is faked.
            self.fault_injected = True
            self.fault_state = snapshot(self.runtime)
            self.events.append("known_failure_after_initialized_pixels")
            if self.fault == "AUTHORITY_LOSS":
                self.grants[Permission.EDIT_MESH.value] = False
                try:
                    self.original_gate(*args, **kwargs)
                except BridgeError as error:
                    assert error.code == "PERMISSION_DENIED"
                    self.primary_loss_error = error.to_dict()
                    self.grants[Permission.EDIT_MESH.value] = True
                    self.authority_regranted_before_raise = True
                    self.events.append("real_edit_denial_then_fixture_regrant")
                    raise
                raise AssertionError("The native permission manager must deny the revoked grant")
            raise RuntimeError("Known fixture failure after verified initialized color pixels")

        surface_brushes._publication = publication
        surface_brushes._preservation = preservation
        surface_brushes._gate = gate

    def restore(self):
        surface_brushes._publication = self.original_publication
        surface_brushes._preservation = self.original_preservation
        surface_brushes._gate = self.original_gate

    def run(self, label, method, action=None, *, fault=None):
        self.phase = self.read = self.fired = False
        self.method, self.action, self.fault, self.events = method, action, fault, []
        self.provider_calls = self.phase_provider_calls = self.publication_number = 0
        self.publication_provider_counts = []
        self.trigger_publication = 2 if fault == "KNOWN_FAILURE" and action is not None else 1
        counts = self.control_provider_counts.get((method, fault)) if action is not None else None
        self.trigger_ordinal = counts[self.trigger_publication - 1] if counts is not None else None
        self.comparison_read_before_trigger = None
        if action is not None:
            assert self.trigger_ordinal is not None and self.trigger_ordinal >= 1
        self.scope_read = self.provider_before = self.provider_after = None
        self.fault_injected = False
        self.fault_state = self.primary_loss_error = None
        self.authority_regranted_before_raise = False
        self.target, self.peer = make_pair(label, paint=method != "color_attribute.create")
        if action == "COLOR_ROLES":
            attr = self.target.data.color_attributes.new(name="Protected Role Alternate", type="FLOAT_COLOR", domain="POINT")
            for item in attr.data:
                item.color = (.5, .25, .125, 1.)
            self.target.data.color_attributes.active_color_index = 0
            self.target.data.color_attributes.render_color_index = 0
        self.grants[Permission.EDIT_MESH.value] = True
        self.grants[Permission.DELETE_OBJECTS.value] = method == "color_attribute.remove" or fault is not None
        self.runtime.state.set_paused(False)
        request = {"object_name": self.target.name}
        if method == "mesh.sculpt_brush":
            request.update(vertex_indices=[0], strokes=[{"center": [0., 0., 0.], "radius": .5,
                           "direction": [0., 0., 1.], "strength": .5, "falloff": "CONSTANT"}])
        elif method == "color_attribute.create":
            request.update(attribute_name="Paint", initial_color=[.125, .25, .5, 1.])
        elif method == "color_attribute.paint":
            request.update(attribute_name="Paint", vertex_indices=[0], strokes=[{
                "center": [0., 0., 0.], "radius": .5, "color": [1., 0., .5, 1.],
                "opacity": .5, "falloff": "CONSTANT"}])
        elif method == "color_attribute.rename":
            request.update(attribute_name="Paint", new_name="Renamed", acknowledge_named_consumers=True)
        else:
            request.update(attribute_name="Paint", confirm_remove=True, acknowledge_named_consumers=True)
        before = snapshot(self.runtime)
        history_before = self.runtime.state.history(50)
        result = failure = None
        try:
            result = self.runtime.dispatch(method, request)
        except BridgeError as error:
            failure = error.to_dict()
        after = snapshot(self.runtime)
        history_after = self.runtime.state.history(50)
        # Keep the latest raw case even if a following guard assertion fails.
        # This bounded diagnostic is deliberately separate from an accepted run.
        diagnostic = {"label": label, "method": method, "provider_action": action, "fault": fault,
                      "guard_verdict_pending": True, "release_acceptance": False,
                      "before": before, "provider_before": self.provider_before,
                      "provider_after": self.provider_after, "after": after,
                      "result": result, "error": failure, "events": list(self.events),
                      "initialized_state_before_fault": self.fault_state}
        (Path(tempfile.gettempdir()) / "surface-publication-current-case.json").write_text(
            json.dumps(diagnostic, indent=2, allow_nan=False) + "\n")
        assert len(history_after) == len(history_before) + 1 and history_after[1:] == history_before
        receipt = history_after[0]
        assert receipt["tool"] == method and receipt["success"] == (failure is None)
        assert self.events[0] == "publication_entered"
        reference = self.provider_after if action is not None else before
        if action is not None:
            assert self.fired and self.events.count("final_permission_provider_entered") == 1
            assert self.provider_before is not None and self.provider_after is not None
            assert self.comparison_read_before_trigger is False
            assert failure is not None and result is None
            expected = {
                "PAUSE": {"AGENT_PAUSED"}, "COORDINATE": {"OPERATION_FAILED"},
                "SHARE": {"NOT_IMPLEMENTED"}, "CLEANUP_PIXELS": {"OPERATION_FAILED"},
                "COLOR_ROLES": {"OPERATION_FAILED"},
                "GENERIC_DESTINATION": {"INVALID_ARGUMENT", "OPERATION_FAILED"}
                if method == "color_attribute.rename" else {"INVALID_ARGUMENT"},
            }
            assert failure["code"] in expected[action], (label, failure)
            # Every domain and context endpoint must equal the provider's state,
            # including generic destinations, new consumers and edited pixels.
            assert native_state(after) == native_state(reference)
        elif fault == "AUTHORITY_LOSS":
            assert self.fault_injected and self.primary_loss_error is not None
            assert self.authority_regranted_before_raise and failure["code"] == "PERMISSION_DENIED"
            assert self.publication_number == 1, "Primary authority loss must skip cleanup entry"
            assert native_state(after) == native_state(self.fault_state)
        elif fault == "KNOWN_FAILURE":
            assert self.fault_injected and failure is not None and result is None
            assert self.publication_number == 2 and paint_values(after, self.target.name) is None
            self.control_provider_counts[(method, fault)] = list(self.publication_provider_counts)
            assert surrounding_state(before, self.target.name, method) == surrounding_state(after, self.target.name, method)
        else:
            assert not self.fired and failure is None
            assert "delegated_scope_read_completed" in self.events and self.provider_calls >= 1
            self.control_provider_counts[(method, None)] = list(self.publication_provider_counts)
            assert surrounding_state(before, self.target.name, method) == surrounding_state(after, self.target.name, method)
        if fault is not None:
            assert self.fault_injected and failure is not None
            recovery = failure["context"]
            assert recovery["execution_started"] and recovery["possible_mutation"]
            assert recovery["rollback_verified"] is False
            assert recovery["cleanup_last_verified_owned_state_available"]
            assert recovery["retained_attribute"] == ("Paint" if action is not None or fault == "AUTHORITY_LOSS" else None)
            assert recovery["cleanup_authority_loss_latched"] == (fault == "AUTHORITY_LOSS")
        if method == "mesh.sculpt_brush":
            endpoint = target_values(after, self.target.name)["coordinates"]
            previous = target_values(reference, self.target.name)["coordinates"]
            intended_output = endpoint == [[0., 0., .5], [2., 0., 0.], [0., 2., 0.]]
        elif method == "color_attribute.rename":
            endpoint = [paint_values(after, self.target.name), renamed_values(after, self.target.name)]
            previous = [paint_values(reference, self.target.name), renamed_values(reference, self.target.name)]
            intended_output = endpoint == [None, [[.125, .25, .5, 1.]] * 3]
        else:
            endpoint, previous = paint_values(after, self.target.name), paint_values(reference, self.target.name)
            intended_output = endpoint is None if method == "color_attribute.remove" else endpoint == (
                [[.125, .25, .5, 1.]] * 3 if method == "color_attribute.create" else
                [[.5625, .125, .5, 1.], [.125, .25, .5, 1.], [.125, .25, .5, 1.]])
        changed_after_provider = endpoint != previous
        if action is None and fault is None:
            assert changed_after_provider and intended_output
        if action == "SHARE":
            assert paint_values(after, self.peer.name) is not None
        if action == "GENERIC_DESTINATION":
            name = request.get("new_name", "Paint")
            matches = [attr for attr in target_values(after, self.target.name)["attributes"] if attr["name"] == name]
            assert len(matches) == 1 and matches[0]["type"] == "FLOAT" and matches[0]["float_values"] == [.125, .375, .625]
        if action == "CLEANUP_PIXELS":
            assert paint_values(after, self.target.name)[0] == [.75, .5, .25, 1.]
        if action == "COLOR_ROLES":
            assert target_values(after, self.target.name)["color_roles"] == [1, 1]
            assert paint_values(after, self.target.name) is None
        row = {
            "label": label, "method": method, "request": request, "provider_action": action, "fault": fault,
            "events": list(self.events), "provider_triggered_exactly_once": self.fired if action else False,
            "publication_provider_calls": self.provider_calls,
            "per_publication_provider_counts": list(self.publication_provider_counts),
            "learned_trigger_publication": self.trigger_publication, "learned_trigger_ordinal": self.trigger_ordinal,
            "comparison_read_before_trigger": self.comparison_read_before_trigger,
            "before": before, "scope_read": self.scope_read,
            "provider_before": self.provider_before, "provider_after": self.provider_after,
            "known_failure_after_verified_pixels": self.fault_injected,
            "verified_initialized_state_before_fault": self.fault_state,
            "real_primary_permission_loss": self.primary_loss_error,
            "fixture_regrant_before_primary_error_raise": self.authority_regranted_before_raise,
            "after": after, "result": result, "error": failure,
            "history_receipt": receipt, "history_before_count": len(history_before),
            "domain_endpoint_changed_after_provider": bool(changed_after_provider),
            "intended_output_present": bool(intended_output),
            "late_bridge_domain_effect_observed": bool(action and changed_after_provider),
            "guarded_refusal_observed": bool(action and failure is not None and not changed_after_provider),
            "provider_native_state_preserved_exactly": bool(action and native_state(after) == native_state(reference)),
            "new_shared_consumer_attribute_retained": None if action != "SHARE" else paint_values(after, self.peer.name) is not None,
            "owned_cleanup_removed_verified_allocation": bool(fault == "KNOWN_FAILURE" and action is None),
            "primary_authority_loss_retained_allocation": bool(fault == "AUTHORITY_LOSS"),
            "native_domain_write_count_measured": False,
            "production_guard_accepted": True,
        }
        self.runtime.state.set_paused(False)
        self.grants[Permission.EDIT_MESH.value] = True
        return row


def main():
    assert bpy.app.background, "Run only through the isolated native runner"
    bpy.context.preferences.use_preferences_save = False
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission in {Permission.EDIT_MESH, Permission.INSPECT_SCENE} for permission in Permission}
    probe = PublicationProbe(runtime, grants)
    manager = PermissionManager(probe.permission_values)
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("mesh")
    bpy.context.scene.frame_set(23, subframe=.125)
    defaults = allocation_defaults()
    rows = []
    probe.install()
    try:
        for label, method, action in (
            ("Control Sculpt", "mesh.sculpt_brush", None),
            ("Control Create", "color_attribute.create", None),
            ("Control Paint", "color_attribute.paint", None),
            ("Control Remove", "color_attribute.remove", None),
            ("Control Rename", "color_attribute.rename", None),
            ("Sculpt Late Pause", "mesh.sculpt_brush", "PAUSE"),
            ("Sculpt Late Coordinate", "mesh.sculpt_brush", "COORDINATE"),
            ("Paint Late Pause", "color_attribute.paint", "PAUSE"),
            ("Paint Late Coordinate", "color_attribute.paint", "COORDINATE"),
            ("Remove Late Sharing", "color_attribute.remove", "SHARE"),
            ("Create Generic Conflict", "color_attribute.create", "GENERIC_DESTINATION"),
            ("Rename Generic Conflict", "color_attribute.rename", "GENERIC_DESTINATION"),
            ("Create Role Change", "color_attribute.create", "COLOR_ROLES"),
        ):
            rows.append(probe.run(label, method, action))
        rows.append(probe.run("Known Failure Cleanup Control", "color_attribute.create", fault="KNOWN_FAILURE"))
        rows.append(probe.run("Cleanup Newer Pixels", "color_attribute.create", "CLEANUP_PIXELS", fault="KNOWN_FAILURE"))
        rows.append(probe.run("Primary Denial Regrant", "color_attribute.create", fault="AUTHORITY_LOSS"))
    finally:
        probe.restore()
        runtime.state.set_paused(False)
    evidence = {
        "blender_version": bpy.app.version_string, "research": False, "production_guard_accepted": True,
        "bounded_guard_regression": True, "release_acceptance": False,
        "fixture_setup_raw_native": True, "fixture_provider_actions_raw_native": True,
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "production_surface_source_sha256": hashlib.sha256((ROOT / "addon/blender_codex_bridge/tools/surface_brushes.py").read_bytes()).hexdigest(),
        "native_allocation_defaults": defaults,
        "rows": rows, "native_undo_verified": False, "durable_recovery_verified": False,
        "project_saved": False, "rendered": False, "windows_qualification": False,
        "appearance_or_full_artist_acceptance": False,
        "generic_attribute_value_coverage": "Complete FLOAT values and all attribute metadata; coordinates, UVs and FLOAT_COLOR values measured separately.",
        "unknown_partial_initialization_cleanup_accepted": False,
    }
    path = Path(tempfile.gettempdir()) / "surface-publication-probe-evidence.json"
    raw = (json.dumps(evidence, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    print("BLENDER_SURFACE_PUBLICATION_PROBE_OK " + canonical({
        "blender_version": bpy.app.version_string, "research": False, "production_guard_accepted": True,
        "bounded_guard_regression": True, "release_acceptance": False,
        "evidence_file": str(path), "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "case_count": len(rows), "provider_probes": sum(row["provider_action"] is not None for row in rows),
        "late_bridge_domain_effects_observed": sum(row["late_bridge_domain_effect_observed"] for row in rows),
        "guarded_refusals_observed": sum(row["guarded_refusal_observed"] for row in rows),
        "project_saved": False, "rendered": False, "native_domain_write_count_measured": False,
    }), flush=True)
    blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
