"""Native factory descriptor inventory and tiny EEVEE render-side-effect research."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge import render_scope_profile  # noqa: E402


def cycles_storage_diagnostic(scene):
    """Owned fixture writes only; never an admission/runtime-getter fallback."""
    rows = []
    for owner, field in ((scene, "samples"), (bpy.context.view_layer, "use_denoising")):
        before = render_scope_profile.snapshot(bpy, scene, checkpoint_static=False)
        keys_before = list(owner.keys())
        group = owner.cycles  # Explicitly owned manual diagnostic, outside tool admission.
        descriptor = group.bl_rna.properties.get(field)
        if descriptor is None:
            rows.append({"owner": owner.bl_rna.identifier, "field": field, "available": False})
            continue
        initial = getattr(group, field)
        after_getter = render_scope_profile.snapshot(bpy, scene, checkpoint_static=False)
        desired = not initial if type(initial) is bool else initial + 1
        try:
            setattr(group, field, desired)
            changed = render_scope_profile.snapshot(bpy, scene, checkpoint_static=False)
            rows.append(
                {
                    "owner": owner.bl_rna.identifier,
                    "field": field,
                    "available": True,
                    "initial": initial,
                    "desired": desired,
                    "observed": getattr(group, field),
                    "keys_before": keys_before,
                    "keys_after": list(owner.keys()),
                    "nested_keys": list(group.keys()),
                    "getter_changed_snapshot": before != after_getter,
                    "authored_write_changed_full_snapshot": after_getter != changed,
                    "snapshot_before_sha256": render_scope_profile.digest(after_getter),
                    "snapshot_changed_sha256": render_scope_profile.digest(changed),
                }
            )
        finally:
            setattr(group, field, initial)
        assert getattr(group, field) == initial
    return {
        "version": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode(),
        "research_only": True,
        "manual_owned_runtime_getters_used": True,
        "tool_admission_getter_fallback_added": False,
        "cycles_storage_diagnostic": rows,
    }


def cycles_pointer_diagnostic(scene):
    """Manual API characterization; this does not authorize a tool reader."""
    native = bpy.types.bpy_struct
    rows = []

    def constructor_matches(cls):
        base = bpy.types.PropertyGroup
        mro = type.__getattribute__(cls, "__mro__")
        if mro != (cls, base, native, object) or type(cls) is not type(base):
            return False
        if type.__getattribute__(type(cls), "__call__") is not type.__call__:
            return False
        for name in ("__new__", "__init__", "__getattribute__"):
            definitions = [type.__getattribute__(c, "__dict__")[name] for c in mro if name in type.__getattribute__(c, "__dict__")]
            native_definition = type.__getattribute__(native, "__dict__")[name]
            if definitions[0] is not native_definition:
                return False
        return all("__del__" not in type.__getattribute__(c, "__dict__") for c in mro)

    for owner, field in ((scene, "samples"), (bpy.context.view_layer, "use_denoising")):
        initially_set = native.is_property_set(owner, "cycles", ghost=False)
        uncoerced = native.path_resolve(owner, "cycles", False)
        set_after_uncoerced = native.is_property_set(owner, "cycles", ghost=False)
        group = native.path_resolve(owner, "cycles")
        cls = type(group)
        assert constructor_matches(cls)
        calls = []
        constructor_interference = []
        for name in ("__new__", "__init__", "__del__", "__getattribute__"):
            previous = type.__getattribute__(cls, "__dict__").get(name)

            def forbidden(*_args, callback_calls=calls, **_kwargs):
                callback_calls.append(True)
                raise AssertionError("Untrusted wrapper constructor ran")

            try:
                setattr(cls, name, forbidden)
                assert not constructor_matches(cls)
                constructor_interference.append({"field": name, "rejected_before_lookup": True})
            finally:
                if previous is None:
                    delattr(cls, name)
                else:
                    setattr(cls, name, previous)
        assert calls == [] and constructor_matches(cls)
        base = bpy.types.PropertyGroup
        slots = ("__new__", "__init__", "__del__", "__getattribute__")
        metadata = {}
        for name in slots:
            observed = type.__getattribute__(cls, name) if hasattr(base, name) or name != "__del__" else None
            expected = type.__getattribute__(base, name) if hasattr(base, name) else None
            metadata[name] = {
                "type": type(observed).__name__,
                "matches_native_base": observed is expected,
            }
        keys_before = list(native.keys(group))
        initial = getattr(group, field)
        desired = not initial if type(initial) is bool else initial + 1
        try:
            setattr(group, field, desired)
            keys_after = list(native.keys(group))
            raw = dict(native.items(group))
            rows.append(
                {
                    "owner": owner.bl_rna.identifier,
                    "field": field,
                    "initially_set": initially_set,
                    "set_after_uncoerced": set_after_uncoerced,
                    "set_after_coerced": native.is_property_set(owner, "cycles"),
                    "uncoerced_type": type(uncoerced).__name__,
                    "group_type": cls.__name__,
                    "group_mro": [c.__name__ for c in type.__getattribute__(cls, "__mro__")],
                    "metaclass": type(cls).__name__,
                    "metaclass_call_matches_type": type.__getattribute__(type(cls), "__call__") is type.__call__,
                    "constructor_slots": metadata,
                    "constructor_interference": constructor_interference,
                    "constructor_interference_python_calls": len(calls),
                    "keys_before": keys_before,
                    "keys_after": keys_after,
                    "raw_authored_value": raw.get(field),
                    "raw_authored_value_matches": raw.get(field) == desired,
                    "raw_group_subscription_supported": hasattr(native, "__getitem__"),
                }
            )
        finally:
            setattr(group, field, initial)
    return {
        "version": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode(),
        "research_only": True,
        "reader_implementation_added": False,
        "cycles_pointer_diagnostic": rows,
    }


def malformed_pointer_diagnostic(scene):
    """Temporary fixture schema only; bundled Cycles storage is untouched."""
    native = bpy.types.bpy_struct
    field = "bcb_owned_malformed_pointer_probe"

    class BCB_OwnedStorageProbe(bpy.types.PropertyGroup):
        pass

    assert scene.bl_rna.properties.get(field) is None
    bpy.utils.register_class(BCB_OwnedStorageProbe)
    try:
        setattr(bpy.types.Scene, field, bpy.props.PointerProperty(type=BCB_OwnedStorageProbe))
        initially_absent = not native.is_property_set(scene, field, ghost=False)
        group = native.path_resolve(scene, field)
        group["owned_sentinel"] = 41
        assert dict(native.items(group)) == {"owned_sentinel": 41}
        del group
        setattr(bpy.types.Scene, field, bpy.props.IntProperty())
        setattr(scene, field, 73)
        assert getattr(scene, field) == 73
        setattr(bpy.types.Scene, field, bpy.props.PointerProperty(type=BCB_OwnedStorageProbe))
        malformed_entry_reports_set = native.is_property_set(scene, field, ghost=False)
        repaired = native.path_resolve(scene, field)
        raw_after_resolution = dict(native.items(repaired))
        assert malformed_entry_reports_set and raw_after_resolution == {}
        del repaired
    finally:
        if scene.bl_rna.properties.get(field) is not None:
            native.property_unset(scene, field)
            delattr(bpy.types.Scene, field)
        bpy.utils.unregister_class(BCB_OwnedStorageProbe)
    ordinary_keys = list(scene.keys())
    cleanup_verified = scene.bl_rna.properties.get(field) is None and field not in ordinary_keys
    assert cleanup_verified
    return {
        "version": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode(),
        "research_only": True,
        "reader_implementation_added": False,
        "bundled_cycles_storage_touched": False,
        "temporary_pointer_initially_absent": initially_absent,
        "malformed_entry_reports_set": malformed_entry_reports_set,
        "path_resolution_repaired_malformed_storage": raw_after_resolution == {},
        "cleanup_verified": cleanup_verified,
    }


def main():
    blender_codex_bridge.register()
    try:
        scene = bpy.context.scene
        if os.environ.get("BLENDER_CODEX_MALFORMED_POINTER_DIAGNOSTIC") == "1":
            print("BLENDER_RENDER_SCOPE_PROBE_OK " + json.dumps(malformed_pointer_diagnostic(scene)))
            return
        if os.environ.get("BLENDER_CODEX_CYCLES_POINTER_DIAGNOSTIC") == "1":
            print("BLENDER_RENDER_SCOPE_PROBE_OK " + json.dumps(cycles_pointer_diagnostic(scene)))
            return
        if os.environ.get("BLENDER_CODEX_CYCLES_STORAGE_DIAGNOSTIC") == "1":
            print("BLENDER_RENDER_SCOPE_PROBE_OK " + json.dumps(cycles_storage_diagnostic(scene)))
            return

        def desc(owner):
            return {
                "kind": owner.bl_rna.identifier,
                "runtime": [
                    {
                        "name": p.identifier,
                        "kind": p.type,
                        "readonly": p.is_readonly,
                        "fixed": p.fixed_type.identifier
                        if p.type in {"POINTER", "COLLECTION"}
                        else None,
                        "default": getattr(p, "default", None)
                        if p.type not in {"POINTER", "COLLECTION", "ENUM"}
                        else None,
                    }
                    for p in owner.bl_rna.properties
                    if p.is_runtime
                ],
            }

        owners = [
            scene,
            scene.render,
            scene.render.image_settings,
            scene.view_settings,
            scene.display_settings,
            scene.eevee,
            scene.display,
            scene.tool_settings,
            scene.unit_settings,
        ]
        owners.extend([scene.eevee.ray_tracing_options, bpy.context.view_layer.eevee])
        extra_containers = []
        for obj in bpy.data.objects:
            owners.extend(obj.material_slots)
            owners.append(obj.light_linking)
            if obj.type == "MESH":
                group = obj.data.uv_layers
                extra_containers.append(
                    {
                        "kind": "uv_layers",
                        "python_type": type(group).__name__,
                        "owner_rna": getattr(getattr(group, "bl_rna", None), "identifier", None),
                        "active_index": group.active_index,
                        "schema": [
                            (
                                p.identifier,
                                p.type,
                                p.is_readonly,
                                p.is_runtime,
                                p.fixed_type.identifier
                                if p.type in {"POINTER", "COLLECTION"}
                                else None,
                            )
                            for p in bpy.types.UVLoopLayers.bl_rna.properties
                        ],
                    }
                )
                owners.extend(group)
        owners.append(scene.unit_settings)
        for obj in bpy.data.objects:
            owners.append(obj)
            if obj.data:
                owners.append(obj.data)
            if obj.type == "CAMERA":
                owners.append(obj.data.dof)
            if obj.type == "MESH":
                owners.extend(
                    [
                        *list(obj.data.vertices)[:1],
                        *list(obj.data.edges)[:1],
                        *list(obj.data.loops)[:1],
                        *list(obj.data.polygons)[:1],
                    ]
                )
                for attr in obj.data.attributes:
                    owners.append(attr)
                    owners.extend(list(attr.data)[:1])
        graph_inventory = []
        for owner in [
            *bpy.data.materials,
            *bpy.data.worlds,
            *bpy.data.lights,
            *bpy.data.linestyles,
        ]:
            owners.append(owner)
            tree = owner.node_tree
            graph_inventory.append(
                {
                    "owner": owner.name,
                    "nodes": [] if tree is None else [n.bl_rna.identifier for n in tree.nodes],
                }
            )
            if tree:
                owners.append(tree)
                for node in tree.nodes:
                    owners.append(node)
                    owners.extend(node.inputs)
                    owners.extend(node.outputs)
        for layer in scene.view_layers:
            owners.extend([layer, layer.layer_collection])
            owners.extend(layer.layer_collection.children)
        before = {
            p.identifier: len(getattr(bpy.data, p.identifier))
            for p in bpy.data.bl_rna.properties
            if p.type == "COLLECTION"
        }
        descriptor_inventory = [desc(o) for o in owners]
        nested_settings = [
            {
                "kind": o.bl_rna.identifier,
                "fields": [
                    (
                        p.identifier,
                        p.type,
                        p.is_readonly,
                        p.is_runtime,
                        p.fixed_type.identifier if p.type in {"POINTER", "COLLECTION"} else None,
                    )
                    for p in o.bl_rna.properties
                ],
            }
            for o in (scene.eevee.ray_tracing_options, bpy.context.view_layer.eevee)
        ]
        shader_pointer_fields = {
            o.bl_rna.identifier: [
                (p.identifier, p.fixed_type.identifier, p.is_readonly)
                for p in o.bl_rna.properties
                if p.type == "POINTER"
            ]
            for o in [*bpy.data.materials, *bpy.data.worlds, *bpy.data.lights]
        }
        principled_before = [
            {
                "owner": m.name,
                "node": n.name,
                "method": n.subsurface_method,
                "method_enum": [
                    (i.identifier, i.value)
                    for i in n.bl_rna.properties["subsurface_method"].enum_items
                ],
                "sockets": [
                    (
                        s.identifier,
                        s.enabled,
                        s.default_value
                        if isinstance(s.default_value, (int, float))
                        else tuple(s.default_value),
                    )
                    for s in n.inputs
                    if s.identifier in {"Subsurface IOR", "Subsurface Anisotropy"}
                ],
            }
            for m in bpy.data.materials
            if m.node_tree
            for n in m.node_tree.nodes
            if n.bl_rna.identifier == "ShaderNodeBsdfPrincipled"
        ]

        def refs():
            return {
                "users": scene.users,
                "fake": scene.use_fake_user,
                "extra": scene.use_extra_user,
                "self_original": scene.original == scene,
                "consumers": [
                    (o.bl_rna.identifier, o.name, o.user_of_id(scene))
                    for o in bpy.data.user_map(subset={scene}).get(scene, ())
                ],
            }

        native_scene_refs_before = refs()
        bpy.ops.ed.undo_push(message="Render factory ownership probe")
        native_scene_refs_after = refs()
        window_fields = [
            (
                p.identifier,
                p.type,
                p.fixed_type.identifier if p.type in {"POINTER", "COLLECTION"} else None,
            )
            for p in bpy.context.window.bl_rna.properties
        ]
        workspace_fields = [
            (
                p.identifier,
                p.type,
                p.fixed_type.identifier if p.type in {"POINTER", "COLLECTION"} else None,
            )
            for p in bpy.context.workspace.bl_rna.properties
        ]
        handler_inventory = {
            p: len(getattr(bpy.app.handlers, p))
            for p in dir(bpy.app.handlers)
            if (
                p.startswith("render_")
                or p.startswith("depsgraph_")
                or p.startswith("frame_change_")
            )
            and isinstance(getattr(bpy.app.handlers, p), list)
        }
        assert scene.render.engine in {"BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}
        scene.render.resolution_x = 16
        scene.render.resolution_y = 16
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(Path(bpy.app.tempdir) / "probe.png")
        result = bpy.ops.render.render(write_still=True)
        after = {
            p.identifier: len(getattr(bpy.data, p.identifier))
            for p in bpy.data.bl_rna.properties
            if p.type == "COLLECTION"
        }
        images = [
            {"name": i.name, "source": i.source, "type": i.type, "size": list(i.size)}
            for i in bpy.data.images
        ]
        assert result == {"FINISHED"} and Path(scene.render.filepath).is_file()
        print(
            "BLENDER_RENDER_SCOPE_PROBE_OK "
            + json.dumps(
                {
                    "version": bpy.app.version_string,
                    "descriptors": descriptor_inventory,
                    "handlers": handler_inventory,
                    "main_before": before,
                    "main_after": after,
                    "images_after": images,
                    "palette_names": [p.name for p in bpy.data.palettes],
                    "linestyle_names": [p.name for p in bpy.data.linestyles],
                    "scene_refs_before": native_scene_refs_before,
                    "scene_refs_after": native_scene_refs_after,
                    "window_fields": window_fields,
                    "workspace_fields": workspace_fields,
                    "graphs": graph_inventory,
                    "extra_containers": extra_containers,
                    "nested_settings": nested_settings,
                    "shader_pointer_fields": shader_pointer_fields,
                    "principled_before": principled_before,
                    "settings_pointer_fields": {
                        o.bl_rna.identifier: [
                            (p.identifier, p.fixed_type.identifier)
                            for p in o.bl_rna.properties
                            if p.type == "POINTER"
                        ]
                        for o in (
                            scene.render,
                            scene.render.image_settings,
                            scene.eevee,
                            scene.view_settings,
                            bpy.context.view_layer,
                        )
                    },
                    "render": list(result),
                }
            )
        )
    finally:
        blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
