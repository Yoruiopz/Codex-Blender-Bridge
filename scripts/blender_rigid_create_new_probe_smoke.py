"""Tiny native CREATE_NEW allocation/removal research; no public setup API.

Run only through the isolated native runner. Fault/cancellation controls are
research-harness boundaries, not claims of bridge cancellation or native undo.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from addon.blender_codex_bridge.tools import _animation_scope as evidence  # noqa: E402
from addon.blender_codex_bridge.tools import _rigid_body_scope as cache_scope  # noqa: E402
from addon.blender_codex_bridge.tools._object_rna_mutation import _custom, object_state  # noqa: E402
from scripts.blender_rigid_lifecycle_probe_smoke import context_state, cube, plain_properties  # noqa: E402

MARKER = "BLENDER_RIGID_CREATE_NEW_PROBE_OK "
CHANNELS = ("location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle",
            "scale", "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale",
            "matrix_parent_inverse")


def plain(value):
    return json.loads(json.dumps(value))


def identity(owner):
    return None if owner is None else {"pointer": owner.as_pointer(), "session_uid": getattr(owner, "session_uid", None),
                                      "type": owner.bl_rna.identifier, "name": owner.name}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def differences(before, after, path="", result=None):
    result = [] if result is None else result
    if before == after:
        return result
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            differences(before.get(key), after.get(key), f"{path}/{key}", result)
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            differences(left, right, f"{path}/{index}", result)
    else:
        result.append({"path": path, "before": before, "after": after})
    return result


def collection_state(collection):
    consumers = bpy.data.user_map(subset={collection}).get(collection, ())
    return {"identity": identity(collection), "users": collection.users,
            "authored": plain(evidence.rna_state(collection)),
            "objects": sorted(obj.name for obj in collection.objects),
            "children": sorted(child.name for child in collection.children),
            "incoming": sorted(({"identity": identity(owner), "references": owner.user_of_id(collection)}
                               for owner in consumers), key=lambda row: row["identity"]["pointer"])}


def body_state(obj):
    state = dict(object_state(obj, exclude_object_rna=frozenset({"active_selection_set"})))
    consumers = bpy.data.user_map(subset={obj, obj.data})
    return plain({"authored": state,
        "channels": {field: evidence.value(getattr(obj, field)) for field in CHANNELS},
        "derived_matrices": {field: evidence.value(getattr(obj, field)) for field in ("matrix_world", "matrix_local", "matrix_basis", "dimensions")},
        "identity": identity(obj), "mesh_identity": identity(obj.data), "users": obj.users, "mesh_users": obj.data.users,
        "incoming": sorted((identity(owner) for owner in consumers.get(obj, ())), key=lambda row: row["pointer"]),
        "mesh_incoming": sorted((identity(owner) for owner in consumers.get(obj.data, ())), key=lambda row: row["pointer"]),
        "body": None if obj.rigid_body is None else plain_properties(obj.rigid_body),
        "body_pointer": None if obj.rigid_body is None else obj.rigid_body.as_pointer(),
        "constraint": obj.rigid_body_constraint is not None})


def state(scene, bodies, collections):
    world = scene.rigidbody_world
    return {"context": context_state(), "scene_identity": identity(scene), "scene_users": scene.users,
            "scene_authored": plain(evidence.rna_state(scene)),
            "root_collection": collection_state(scene.collection),
            "bodies": {obj.name: body_state(obj) for obj in bodies},
            "collections": {collection.name: collection_state(collection) for collection in collections},
            "main_ids": {family: sorted((identity(owner) for owner in getattr(bpy.data, family)), key=lambda row: row["pointer"])
                         for family in ("scenes", "objects", "meshes", "collections", "materials")},
            "materials": {material.name: {"properties": plain_properties(material), "custom": plain(_custom(material))}
                          for material in bpy.data.materials},
            "world": None if world is None else {"pointer": world.as_pointer(), "properties": plain_properties(world),
                "cache": plain_properties(world.point_cache), "body_collection": identity(world.collection),
                "constraint_collection": identity(world.constraints)}}


def authored_scope(snapshot):
    result = plain(snapshot)
    for body in result["bodies"].values():
        del body["derived_matrices"]
    return result


class InjectedFailure(Exception):
    pass


class BoundaryCancelled(Exception):
    pass


class Research:
    def __init__(self, label, frame, subframe, *, stop_after=None, cancel=False):
        self.scene = bpy.data.scenes.new(label)
        bpy.context.window.scene = self.scene
        self.scene.frame_start, self.scene.frame_end = 1, 3
        self.collections = [bpy.data.collections.new(label + " Bodies"), bpy.data.collections.new(label + " Constraints")]
        for collection in self.collections:
            self.scene.collection.children.link(collection)
        self.bodies = [cube(self.collections[0], label + f" Body {index}", location=(index*4., .25, index+3.), scale=(1.25, .8, 1.1))
                       for index in range(3)]
        for index, obj in enumerate(self.bodies):
            obj.rotation_euler = (.12, .23, .34)
            obj.rotation_quaternion = (.96, .11, .17, .19)
            obj.rotation_axis_angle = (.25, .2, .4, .8)
            obj.rotation_mode = ("XYZ", "QUATERNION", "AXIS_ANGLE")[index]
            obj.delta_location = (.13, .17, .19)
            obj.delta_rotation_euler = (.03, .05, .07)
            obj.delta_rotation_quaternion = (.99, .02, .03, .04)
            obj.delta_scale = (1.1, .9, 1.05)
            obj["owned_probe"] = index
            attribute = obj.data.attributes.new("owned_probe", "FLOAT", "POINT")
            for vertex_index, value in enumerate(attribute.data):
                value.value = index + vertex_index*.125
        self.sentinel = cube(self.scene.collection, label + " Protected Mesh Sentinel", location=(0., -5., 2.))
        material = bpy.data.materials.new(label + " Shared Protected Material")
        material.diffuse_color = (.125, .25, .5, .75)
        material["owned_material_probe"] = "preserve"
        for obj in (*self.bodies, self.sentinel):
            obj.data.materials.append(material)
        self.sentinel.select_set(True)
        bpy.context.view_layer.objects.active = self.sentinel
        self.scene.frame_set(frame, subframe=subframe)
        bpy.context.view_layer.update()
        bpy.context.evaluated_depsgraph_get().update()
        self.before = self.capture()
        assert self.scene.rigidbody_world is None
        assert all(obj.rigid_body is None and obj.rigid_body_constraint is None for obj in self.scene.objects)
        self.expected = self.before
        self.steps = []
        self.stop_after, self.cancel, self.cancelled = stop_after, cancel, False
        self.authority_epoch = "INITIAL_RESEARCH_OWNER"
        self.created = []

    def capture(self):
        return state(self.scene, (*self.bodies, self.sentinel), self.collections)

    def check(self, *, context_object=None):
        if self.cancelled:
            raise BoundaryCancelled("Harness owner canceled; further operation and compensation writes forbidden.")
        actual = self.capture()
        if context_object is not None:
            override = {"context_active": context_object.name, "context_object": context_object.name,
                        "context_selected": [context_object.name]}
            assert all(actual["context"][field] == value for field, value in override.items())
            # Actual view-layer active/selected state remains independently read
            # and compared. Only the three declared virtual override fields are
            # normalized for the pre-call comparison.
            for field in override:
                actual["context"][field] = self.expected["context"][field]
        assert actual == self.expected, ("Unexpected external state; no owned write allowed.", differences(self.expected, actual)[:12])

    def write(self, label, callback, *, inject=True):
        self.check()
        started = time.monotonic()
        result = callback()
        seconds = time.monotonic()-started
        actual = self.capture()
        # Only the measured physics/world pointer outputs and derived native
        # evaluation caches may be published by this research owner. Refuse
        # authored or membership/identity changes immediately, before any next
        # write or compensation; do not adopt a complete arbitrary snapshot.
        assert actual["context"] == self.before["context"]
        for field in ("scene_identity", "scene_users", "scene_authored", "root_collection"):
            assert actual[field] == self.before[field], (label, field)
        assert actual["main_ids"] == self.before["main_ids"]
        assert actual["materials"] == self.before["materials"]
        for name, body in actual["bodies"].items():
            for field in ("authored", "channels", "identity", "mesh_identity", "users", "mesh_users", "incoming", "mesh_incoming", "constraint"):
                assert body[field] == self.before["bodies"][name][field], (label, name, field)
            if name == self.sentinel.name:
                assert body["body"] is None and body["body_pointer"] is None
        for name, collection in actual["collections"].items():
            for field in ("identity", "authored", "objects", "children"):
                assert collection[field] == self.before["collections"][name][field], (label, name, field)
            bound = actual["world"] is not None and collection["identity"] in (
                actual["world"]["body_collection"], actual["world"]["constraint_collection"])
            assert collection["users"] == 1 + int(bound)
            assert len(collection["incoming"]) == 1
            assert collection["incoming"][0]["identity"] == identity(self.scene)
            assert collection["incoming"][0]["references"] == 2 + int(bound)
        self.steps.append({"stage": label, "seconds": seconds, "native_preemptible": False,
                           "authority_epoch": self.authority_epoch,
                           "result": result, "delta_from_previous": differences(self.expected, actual),
                           "physical_context_preserved": actual["context"] == self.before["context"]})
        self.expected = actual
        if inject and self.stop_after == label:
            if self.cancel:
                self.cancelled = True
                raise BoundaryCancelled("Injected harness cancellation after owned native effects.")
            raise InjectedFailure("Injected failure after " + label)

    def operator(self, label, operator, *, obj=None, **params):
        def execute():
            kwargs = {"scene": self.scene, "view_layer": bpy.context.view_layer}
            if obj is not None:
                kwargs.update(object=obj, active_object=obj, selected_objects=[obj], selected_editable_objects=[obj])
            with bpy.context.temp_override(**kwargs):
                self.check(context_object=obj)
                poll_started = time.monotonic()
                assert operator.poll()
                poll_seconds = time.monotonic()-poll_started
                self.check(context_object=obj)
                native_started = time.monotonic()
                result = operator("EXEC_DEFAULT", **params)
                native_seconds = time.monotonic()-native_started
                assert result == {"FINISHED"}, result
            return {"status": sorted(result), "native_seconds": native_seconds, "poll_seconds": poll_seconds}
        self.write(label, execute)

    def create(self):
        self.operator("world_add", bpy.ops.rigidbody.world_add)
        world = self.scene.rigidbody_world
        for field, value in (("time_scale", .75), ("substeps_per_frame", 1), ("solver_iterations", 4)):
            self.write("configure_" + field, lambda field=field, value=value: setattr(world, field, value))
        for field, value in (("frame_start", 1), ("frame_end", 3)):
            self.write("configure_cache_" + field, lambda field=field, value=value: setattr(world.point_cache, field, value))
        for field, collection in zip(("collection", "constraints"), self.collections, strict=True):
            if field == "collection":
                self.created = list(self.bodies)
            self.write("bind_" + field, lambda field=field, collection=collection: setattr(world, field, collection))
        for index, obj in enumerate(self.bodies):
            # Register attempted identity before the native call, so a failure
            # after its effects still has exact cleanup scope.
            self.operator(f"body_add_{index}", bpy.ops.rigidbody.object_add, obj=obj, type="PASSIVE" if index == 2 else "ACTIVE")
            self.write(f"box_{index}", lambda obj=obj: setattr(obj.rigid_body, "collision_shape", "BOX"))

    def recover(self):
        if self.cancelled:
            count = len(self.steps)
            try:
                self.write("forbidden_compensation", lambda: setattr(self.bodies[0], "location", (99., 99., 99.)))
            except BoundaryCancelled:
                pass
            else:
                raise AssertionError("Canceled owner performed compensation.")
            assert len(self.steps) == count
            return {"attempted": False, "reason": "HARNESS_OWNER_CANCELLED", "writes_after_cancellation": 0}
        if self.scene.rigidbody_world is not None:
            world = self.scene.rigidbody_world
            for field in ("constraints", "collection"):
                if getattr(world, field) is not None:
                    self.write("detach_" + field, lambda field=field: setattr(world, field, None))
            self.operator("world_remove", bpy.ops.rigidbody.world_remove)
        for index, obj in reversed(list(enumerate(self.created))):
            if obj.rigid_body is not None:
                self.operator(f"body_remove_{index}", bpy.ops.rigidbody.object_remove, obj=obj)
                if self.collections[0].objects.get(obj.name) != obj:
                    self.write(f"relink_{index}", lambda obj=obj: self.collections[0].objects.link(obj), inject=False)
                original = self.before["bodies"][obj.name]["channels"]
                for field in CHANNELS:
                    if plain(evidence.value(getattr(obj, field))) != original[field]:
                        self.write(f"restore_{index}_{field}", lambda obj=obj, field=field, original=original: setattr(obj, field, original[field]), inject=False)
        final = self.capture()
        return {"attempted": True, "exact_state_restored": final == self.before,
                "exact_authored_scope_restored": authored_scope(final) == authored_scope(self.before),
                "remaining_delta": differences(self.before, final)}

    def run(self):
        original_stop = self.stop_after
        primary = None
        try:
            self.create()
        except (InjectedFailure, BoundaryCancelled) as error:
            primary = {"type": type(error).__name__, "message": str(error)}
        after_create = self.expected
        cache_scope_complete = None
        if primary is None:
            cache_scope.snapshot(bpy, self.scene, {"body_names": [obj.name for obj in self.bodies], "constraint_names": []})
            cache_scope_complete = True
        try:
            recovery = self.recover()
        except (InjectedFailure, BoundaryCancelled) as error:
            recovery = {"attempted": True, "exact_authored_scope_restored": False,
                        "primary_error": {"type": type(error).__name__, "message": str(error)},
                        "retained_state_sha256": digest(self.expected)}
        retained = self.capture()
        count = len(self.steps)
        if self.cancelled:
            try:
                self.check()
            except BoundaryCancelled:
                pass
            else:
                raise AssertionError("Canceled harness owner retained authority.")
            assert len(self.steps) == count and retained == self.expected
        # This is an independent, explicitly authorized research-harness
        # cleanup, not continuation under the canceled/failed bridge owner.
        fresh_authority_cleanup = None
        if self.cancelled or "primary_error" in recovery:
            self.cancelled, self.stop_after = False, None
            self.authority_epoch = "FRESH_EXPLICIT_RESEARCH_CLEANUP_OWNER"
            fresh_authority_cleanup = self.recover()
            assert fresh_authority_cleanup["exact_authored_scope_restored"]
        else:
            assert recovery["exact_authored_scope_restored"]
        final = self.capture()
        return {"label": self.scene.name, "caller_frame": self.before["context"]["frame"],
                "caller_subframe": self.before["context"]["subframe"], "fault_stage": original_stop,
                "cancellation_control": self.cancel, "primary_error": primary,
                "before": self.before, "after_create": after_create, "retained_before_fresh_authority": retained, "final": final,
                "existing_cache_scope_admission_complete": cache_scope_complete,
                "fresh_authority_cleanup": fresh_authority_cleanup,
                "steps": self.steps, "recovery": recovery,
                "created_authored_delta": {obj.name: differences(self.before["bodies"][obj.name]["authored"],
                    after_create["bodies"][obj.name]["authored"]) for obj in self.bodies}}


def main():
    bpy.context.preferences.use_preferences_save = False
    cases = []
    for index, (stage, cancel) in enumerate(((None, False), ("world_add", False), ("bind_collection", False),
            ("bind_constraints", False), ("body_add_0", False), ("box_0", False),
            ("body_add_1", False), ("world_add", True), ("body_add_0", True),
            ("detach_collection", False), ("world_remove", False),
            ("body_remove_2", False), ("detach_collection", True), ("body_remove_2", True))):
        cases.append(Research(f"Owned Create New {index}", 7, .25, stop_after=stage, cancel=cancel).run())
    cases.append(Research("Owned Create New Integer", 1, 0.).run())
    path = Path(os.environ["TMPDIR"]) / "rigid-create-new-research.json"
    report = {"blender_version": bpy.app.version_string, "blender_build_hash": bpy.app.build_hash.decode(),
              "cases": cases, "public_setup_api_added": False, "release_readiness": "NOT_ASSESSED",
              "disk_cache_flags_touched": False, "cancellation_scope": "RESEARCH_HARNESS_BOUNDARIES_ONLY"}
    path.write_text(json.dumps(report, indent=2)+"\n")
    summary = {"blender_version": bpy.app.version_string, "evidence": str(path),
               "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
               "cases": [{"label": row["label"], "stage": row["fault_stage"], "cancel": row["cancellation_control"],
                          "recovery_attempted": row["recovery"]["attempted"],
                          "exact_state_restored": row["recovery"].get("exact_state_restored"),
                          "exact_authored_scope_restored": row["recovery"].get("exact_authored_scope_restored"),
                          "fresh_authority_cleanup_verified": None if row["fresh_authority_cleanup"] is None else row["fresh_authority_cleanup"]["exact_authored_scope_restored"],
                          "remaining_delta_count": len(row["recovery"].get("remaining_delta", [])),
                          "created_authored_delta_count": sum(len(delta) for delta in row["created_authored_delta"].values())}
                         for row in cases], "public_setup_api_added": False, "release_readiness": "NOT_ASSESSED"}
    print(MARKER + json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
