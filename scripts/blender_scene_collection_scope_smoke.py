"""Native collection admission evidence; run only through the isolated runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

from blender_codex_bridge.tools import _scene_collection_scope as scope  # noqa: E402


def runtime_fields(owner):
    result = []
    for prop in owner.bl_rna.properties:
        if prop.is_runtime:
            result.append({"name": prop.identifier, "kind": prop.type,
                           "readonly": prop.is_readonly, "registered": prop.is_registered,
                           "array_length": getattr(prop, "array_length", 0),
                           "fixed_type": getattr(getattr(prop, "fixed_type", None), "identifier", None)})
    return result


def denial(scene, collection, **kwargs):
    try:
        scope.snapshot(bpy, scene, collection, operation="collection.rename", **kwargs)
    except scope.BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
        return error.message
    raise AssertionError("Unsupported collection scope was admitted")


def controlled_getter(calls):
    def get(_self):
        calls.append("read")
        return 7.0
    return get


def main():
    scene, root = bpy.context.scene, bpy.context.scene.collection
    runtime = {"Scene": runtime_fields(scene), "ViewLayer": runtime_fields(bpy.context.view_layer),
               "LayerCollection": runtime_fields(bpy.context.view_layer.layer_collection),
               "Collection": runtime_fields(root)}
    print("SCENE_COLLECTION_RUNTIME_FIELDS " + json.dumps(runtime, sort_keys=True))
    context = (scene.as_pointer(), bpy.context.view_layer.as_pointer(), bpy.context.mode,
               tuple(obj.as_pointer() for obj in bpy.context.selected_objects),
               bpy.context.view_layer.objects.active.as_pointer() if bpy.context.view_layer.objects.active else None)
    # Baseline must work without an update() or frame evaluation to synchronize
    # Blender 5.2's lazily materialized LayerCollection tree.
    assert dict(scope.snapshot(bpy, scene, root, operation="collection.create"))["target"][0] == root.as_pointer()
    parent = bpy.data.collections.new("Owned Scope Parent")
    child = bpy.data.collections.new("Owned Scope Child")
    root.children.link(parent)
    parent.children.link(child)
    parent_profile = scope.snapshot(bpy, scene, parent, operation="collection.create")
    child_profile = scope.snapshot(bpy, scene, child, operation="collection.rename", expected_name=child.name)
    child.name = "Owned Scope Renamed"
    assert scope.snapshot(bpy, scene, child, operation="collection.rename", expected_name=child.name) == child_profile
    extra = bpy.data.collections.new("Owned Scope Child For Publication")
    extra_token = (extra.as_pointer(), extra.session_uid)
    unlinked = scope.snapshot(bpy, scene, extra, operation="collection.create", allow_unlinked=True)
    assert dict(unlinked)["children"] == dict(unlinked)["objects"] == ()
    parent.children.link(extra)
    parent_after = scope.snapshot(bpy, scene, parent, operation="collection.create")
    assert dict(parent_after)["children"] == tuple(sorted((*dict(parent_profile)["children"], extra_token)))
    if hasattr(scope, "without_owned_child"):
        assert scope.without_owned_child(parent_after, extra_token) == parent_profile
    second_layer = scene.view_layers.new("Owned Collection Scope Layer")
    assert second_layer is not None
    scope.snapshot(bpy, scene, child, operation="collection.rename", expected_name=child.name)

    unsupported = []
    external = bpy.data.objects.new("Owned External Collection Instance", None)
    scene.collection.objects.link(external)
    external.instance_type = "COLLECTION"
    external.instance_collection = child
    unsupported.append(denial(scene, child))
    external.instance_collection = None
    external.instance_type = "NONE"
    other_parent = bpy.data.collections.new("Owned Other Parent")
    root.children.link(other_parent)
    other_parent.children.link(child)
    unsupported.append(denial(scene, child))
    other_parent.children.unlink(child)
    parent["extra_child_reference"] = child
    unsupported.append(denial(scene, child))
    del parent["extra_child_reference"]
    scene["extra_child_reference"] = child
    unsupported.append(denial(scene, child))
    del scene["extra_child_reference"]

    getter_controls = []
    for owner_class, owner in ((bpy.types.Collection, child), (bpy.types.Scene, scene)):
        calls = []
        owner_class.bcb_scope_getter = bpy.props.FloatProperty(get=controlled_getter(calls))
        try:
            descriptor = owner.bl_rna.properties.get("bcb_scope_getter")
            assert descriptor is not None and descriptor.is_runtime, "Getter control was not registered RNA"
            assert owner.bcb_scope_getter == 7.0 and calls == ["read"]
            calls.clear()
            unsupported.append(denial(scene, child))
            assert calls == [], "Admission invoked a runtime getter"
            getter_controls.append({"owner": owner_class.__name__, "registered": True, "admission_calls": len(calls)})
        finally:
            delattr(owner_class, "bcb_scope_getter")
    assert context == (scene.as_pointer(), bpy.context.view_layer.as_pointer(), bpy.context.mode,
                       tuple(obj.as_pointer() for obj in bpy.context.selected_objects),
                       bpy.context.view_layer.objects.active.as_pointer() if bpy.context.view_layer.objects.active else None)
    print("BLENDER_SCENE_COLLECTION_SCOPE_OK " + json.dumps({"blender_version": bpy.app.version_string,
          "build_hash": bpy.app.build_hash.decode(), "runtime_fields": runtime, "getter_controls": getter_controls,
          "unsupported_count": len(unsupported), "no_forced_layer_update": True,
          "context_preserved": True, "project_saved": False}, sort_keys=True))


if __name__ == "__main__":
    main()
