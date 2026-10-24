"""Native runtime-property denial controls for rigid cache inspection and writes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "addon"))

from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.state import BridgeState  # noqa: E402
from blender_codex_bridge.tool_registry import ToolContext, ToolRegistry  # noqa: E402
from blender_codex_bridge.tools import rigid_body  # noqa: E402

from scripts.blender_rigid_evaluation_dependencies_smoke import handlers  # noqa: E402
from scripts.blender_rigid_lifecycle_probe_smoke import cache_state, context_state, make_scene  # noqa: E402

MARKER = "BLENDER_RIGID_RUNTIME_GETTERS_OK "
PROPERTY = "bridge_owned_rigid_getter_probe"


def descriptor(prop):
    return {"name": prop.identifier, "type": prop.type, "runtime": bool(prop.is_runtime),
            "readonly": bool(prop.is_readonly), "registered": bool(prop.is_registered),
            "fixed_type": getattr(getattr(prop, "fixed_type", None), "identifier", None)}


def main():
    bpy.context.preferences.use_preferences_save = False
    scene, bodies, sentinel = make_scene("Owned Runtime Getter Scope", (0., 0., -9.81))
    scene.frame_set(7, subframe=.25)
    body = bodies[0]
    attribute = body.data.attributes.new("Owned Runtime Getter Attribute", "FLOAT", "POINT")
    vertex_group = body.vertex_groups.new(name="Owned Runtime Getter Group")
    vertex_group.add([0], .5, "REPLACE")
    material = bpy.data.materials.new("Owned Runtime Getter Material")
    body.data.materials.append(material)
    owners = [body, body.data, scene.rigidbody_world.collection, scene.rigidbody_world,
              body.rigid_body, scene.unit_settings, scene.rigidbody_world.effector_weights,
              body.data.vertices[0], body.data.edges[0], body.data.loops[0],
              body.data.polygons[0], attribute.data[0], vertex_group, body.material_slots[0]]
    inventory = {owner.bl_rna.identifier: [descriptor(prop) for prop in owner.bl_rna.properties
                                         if prop.is_runtime and not prop.is_readonly]
                 for owner in owners}
    print("RIGID_RUNTIME_GETTER_BASELINE_DESCRIPTORS " + json.dumps(inventory), flush=True)
    registry = ToolRegistry(enabled_toolsets=("simulation",))
    rigid_body.register(registry)
    grants = {permission.value: permission != Permission.EXECUTE_PYTHON for permission in Permission}
    inspect_grants = {permission.value: permission == Permission.INSPECT_SCENE for permission in Permission}
    context = ToolContext(state=BridgeState(), permissions=PermissionManager(lambda: grants),
                          registry=registry, checkpoints=None)
    params = {"scene_name": scene.name, "body_names": sorted(obj.name for obj in bodies),
              "constraint_names": [], "operation": "BAKE", "frame_start": 1, "frame_end": 3}
    calls, writes, results, unsupported = {}, [], [], []
    originals = {name: getattr(rigid_body._Boundary, name)
                 for name in ("frame", "reset", "range_field", "native")}

    def no_owned_write(self, *args, **kwargs):
        writes.append({"args": str(args), "kwargs": str(kwargs)})
        raise AssertionError("A runtime-property denial reached an owned cache/frame write")

    def frozen():
        return {"context": context_state(), "cache": cache_state(scene.rigidbody_world.point_cache),
                "time_scale": scene.rigidbody_world.time_scale, "handlers": handlers(),
                "geometry": [[tuple(vertex.co) for vertex in obj.data.vertices] for obj in bodies],
                "transforms": [(tuple(obj.location), tuple(obj.rotation_euler), tuple(obj.scale)) for obj in bodies],
                "counters": dict(calls)}

    def expect_denial(label, call):
        before = frozen()
        try:
            call()
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED", error.to_dict()
            result = {"case": label, "error": error.to_dict(), "owned_write_entries": len(writes),
                      "getter_delta": 0, "context_cache_geometry_handlers_preserved": True}
        else:
            raise AssertionError("Rigid cache admission unexpectedly accepted: " + label)
        assert not writes and frozen() == before
        return result

    def install(cls, label):
        assert not hasattr(cls, PROPERTY)

        def getter(self):
            calls[label] = calls.get(label, 0)+1
            return .375

        def setter(self, value):
            raise AssertionError("The runtime getter probe must never be assigned")

        setattr(cls, PROPERTY, bpy.props.FloatProperty(get=getter, set=setter))

    try:
        for owner in owners:
            label = owner.bl_rna.identifier
            cls = getattr(bpy.types, label)
            healthy = rigid_body.cache_preview(context, params)
            proposal = {**params, "expected_fingerprint": healthy["expected_fingerprint"]}
            try:
                install(cls, label)
            except (AttributeError, RuntimeError, TypeError) as error:
                unsupported.append({"rna": label, "registration_error": type(error).__name__, "message": str(error)})
                if hasattr(cls, PROPERTY):
                    delattr(cls, PROPERTY)
                continue
            try:
                prop = owner.bl_rna.properties.get(PROPERTY)
                print("RIGID_RUNTIME_GETTER_REGISTRATION " + json.dumps({"rna": label,
                      "descriptor": None if prop is None else descriptor(prop)}), flush=True)
                if prop is None:
                    unsupported.append({"rna": label, "registration_error": "NO_RNA_DESCRIPTOR",
                                        "message": "Class assignment did not create an RNA property; no native getter coverage claimed."})
                    continue
                assert prop.is_runtime and not prop.is_readonly
                before = calls.get(label, 0)
                assert getattr(owner, PROPERTY) == .375
                assert calls.get(label, 0) == before+1
                for name in originals:
                    setattr(rigid_body._Boundary, name, no_owned_write)
                context.permissions = PermissionManager(lambda: inspect_grants)
                preview_denial = expect_denial(label+"_inspect_only_preview", lambda: rigid_body.cache_preview(context, params))
                context.permissions = PermissionManager(lambda: grants)
                execute_denial = expect_denial(label+"_execute", lambda proposal=proposal: rigid_body.cache(context, proposal))
                results.append({"rna": label, "descriptor": descriptor(prop), "explicit_getter_control_delta": 1,
                                "preview": preview_denial, "execute": execute_denial})
            finally:
                for name, original in originals.items():
                    setattr(rigid_body._Boundary, name, original)
                context.permissions = PermissionManager(lambda: grants)
                delattr(cls, PROPERTY)
        assert {"Object", "Mesh", "Collection"} <= {item["rna"] for item in results}
        late_results = []
        for owner in owners:
            label = owner.bl_rna.identifier
            if label not in {item["rna"] for item in results}:
                continue
            cls = getattr(bpy.types, label)
            healthy = rigid_body.cache_preview(context, params)
            proposal = {**params, "expected_fingerprint": healthy["expected_fingerprint"]}
            provider_calls = [0]

            def late_provider(provider_calls=provider_calls, cls=cls, label=label):
                provider_calls[0] += 1
                if provider_calls[0] == 3:
                    install(cls, label+"_late")
                return grants

            context.permissions = PermissionManager(late_provider)
            for name in originals:
                setattr(rigid_body._Boundary, name, no_owned_write)
            try:
                denial = expect_denial(label+"_late_provider_execute", lambda proposal=proposal: rigid_body.cache(context, proposal))
                assert provider_calls[0] >= 3 and hasattr(cls, PROPERTY)
                denial.update(provider_calls=provider_calls[0], getter_registered_after_initial_capture=True)
                late_results.append(denial)
            finally:
                for name, original in originals.items():
                    setattr(rigid_body._Boundary, name, original)
                context.permissions = PermissionManager(lambda: grants)
                if hasattr(cls, PROPERTY):
                    delattr(cls, PROPERTY)
        healthy = rigid_body.cache_preview(context, params)
        assert len(healthy["expected_fingerprint"]) == 64
        assert bpy.context.view_layer.objects.active is sentinel
        ui_counter = [0]
        ui_field = "active_selection_set"
        original_ui = bpy.types.Object.bl_rna.properties[ui_field]
        ui_metadata = {"name": original_ui.name, "description": original_ui.description,
                       "default": original_ui.default}
        assert ui_metadata["default"] == 0 and all(ui_field not in list(obj.keys()) for obj in bodies)

        def ui_getter(self):
            ui_counter[0] += 1
            return 0

        def ui_setter(self, value):
            raise AssertionError("The ignored runtime UI index must never be assigned")

        def replace_ui(kind="INT"):
            if hasattr(bpy.types.Object, ui_field):
                delattr(bpy.types.Object, ui_field)
            factory = bpy.props.IntProperty if kind == "INT" else bpy.props.FloatProperty
            setattr(bpy.types.Object, ui_field, factory(**ui_metadata, get=ui_getter, set=ui_setter,
                                                       override={"LIBRARY_OVERRIDABLE"}))

        ui_result = {}
        try:
            replace_ui()
            assert getattr(body, ui_field) == 0 and ui_counter[0] == 1
            ui_before = ui_counter[0]
            preview = rigid_body.cache_preview(context, params)
            assert len(preview["expected_fingerprint"]) == 64 and ui_counter[0] == ui_before
            invalidate_params = {key: value for key, value in params.items() if key not in {"frame_start", "frame_end"}}
            invalidate_params["operation"] = "INVALIDATE"
            invalidate_preview = rigid_body.cache_preview(context, invalidate_params)
            result = rigid_body.cache(context, {**invalidate_params,
                                      "expected_fingerprint": invalidate_preview["expected_fingerprint"]})
            assert result["completed"] and result["frame_recovery"]["verified"] and ui_counter[0] == ui_before
            body[ui_field] = 0
            try:
                stored_denial = expect_denial("stored_ui_zero", lambda: rigid_body.cache_preview(context, params))
            finally:
                del body[ui_field]
            replace_ui("FLOAT")
            wrong_descriptor = expect_denial("wrong_ui_descriptor", lambda: rigid_body.cache_preview(context, params))
            assert ui_counter[0] == ui_before
            ui_result = {"explicit_getter_control_delta": 1, "preview_getter_delta": 0,
                         "invalidate_getter_delta": 0, "invalidate_completed": result["completed"],
                         "frame_recovery_verified": result["frame_recovery"]["verified"],
                         "stored_zero_denial": stored_denial, "wrong_descriptor_denial": wrong_descriptor}
        finally:
            if hasattr(bpy.types.Object, ui_field):
                delattr(bpy.types.Object, ui_field)
            setattr(bpy.types.Object, ui_field, bpy.props.IntProperty(**ui_metadata, override={"LIBRARY_OVERRIDABLE"}))
        print(MARKER + json.dumps({"blender_version": bpy.app.version_string,
              "baseline_runtime_descriptors": inventory, "admission_denials": results,
              "late_provider_denials": late_results, "registration_unsupported": unsupported,
              "ignored_ui_index_control": ui_result,
              "owned_write_entries": writes, "all_probe_properties_removed": True,
              "ordinary_bundled_registration_preserved": True, "project_saved": False}), flush=True)
    finally:
        for name, original in originals.items():
            setattr(rigid_body._Boundary, name, original)
        for owner in owners:
            cls = getattr(bpy.types, owner.bl_rna.identifier)
            if hasattr(cls, PROPERTY):
                delattr(cls, PROPERTY)


if __name__ == "__main__":
    main()
