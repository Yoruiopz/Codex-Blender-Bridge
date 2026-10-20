"""Versioned texture refresh/relocation with protected pixels and measured native recovery."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import traceback
import zlib
from array import array
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))


def png(path, palette, size=64):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = [b"\0" + b"".join(bytes(palette[(x // 8 + y // 8) % 2]) for x in range(size)) for y in range(size)]
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def pixels(image):
    assert image.has_data
    values = array("f", [0]) * len(image.pixels)
    image.pixels.foreach_get(values)
    return hashlib.sha256(values.tobytes()).hexdigest()


def reload_diagnostic(directory):
    """Observe native reload recovery; this is not a bridge tool or permission bypass."""
    path = directory / "native-reload-probe.png"
    png(path, [(255, 0, 0, 255)] * 2, size=4)
    image = bpy.data.images.load(str(path), check_existing=False)
    image.name, image.use_fake_user = "Native Reload Probe", True
    before = list(image.pixels[:4])
    bpy.ops.ed.undo_push(message="Diagnostic before native image reload")
    png(path, [(0, 0, 255, 255)] * 2, size=4)
    image.reload()
    after = list(image.pixels[:4])
    bpy.ops.ed.undo_push(message="Diagnostic after native image reload")
    bpy.ops.ed.undo()
    recovered = list(bpy.data.images["Native Reload Probe"].pixels[:4])
    assert before != after
    # Report the observed result rather than asserting that every future Blender
    # version must retain this limitation. Versioned refresh is verified separately.
    return {"before_rgba": before, "reloaded_rgba": after, "after_native_undo_rgba": recovered,
            "buffer_restored_by_native_undo": recovered == before,
            "in_place_bridge_reload_implemented": False}


def run():
    try:
        bpy.context.preferences.use_preferences_save = False
        directory = Path(tempfile.gettempdir()) / "texture-versions"
        directory.mkdir()
        diagnostic = reload_diagnostic(directory)
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime
        from blender_codex_bridge.tools import images

        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = False
        prefs.allow_external_files = True
        for toolset in ("materials", "nodes", "objects", "interaction"):
            runtime.registry.enable_toolset(toolset)
        source, relocated = directory / "source.png", directory / "relocated.png"
        warm = [(230, 100, 20, 255), (250, 180, 45, 255)]
        cool = [(20, 75, 170, 255), (45, 150, 230, 255)]
        green = [(15, 95, 35, 255), (90, 210, 65, 255)]
        png(source, warm)
        png(relocated, green)
        prefs.texture_directory = str(directory)
        original = runtime.dispatch("image.load", {"filepath": str(source), "new_name": "Original Albedo", "alpha_mode": "PREMUL"})
        assert original["loaded"]
        old = bpy.data.images["Original Albedo"]
        original_pixels = pixels(old)
        cube = bpy.data.objects["Cube"]
        cube.name = "Revision Prop"
        base = cube.active_material
        base.name = "Source Surface"
        group = bpy.data.node_groups.new("Source Finish", "ShaderNodeTree")
        group.interface.new_socket(name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
        texture = group.nodes.new("ShaderNodeTexImage")
        texture.name, texture.image, texture.interpolation = "Albedo", old, "Closest"
        bsdf = group.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Roughness"].default_value = .55
        out = group.nodes.new("NodeGroupOutput")
        group.links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
        group.links.new(bsdf.outputs["BSDF"], out.inputs["Shader"])
        base.node_tree.nodes.clear()
        instance = base.node_tree.nodes.new("ShaderNodeGroup")
        instance.name, instance.node_tree = "Finish", group
        output = base.node_tree.nodes.new("ShaderNodeOutputMaterial")
        base.node_tree.links.new(instance.outputs["Shader"], output.inputs["Surface"])
        protected = cube.copy()
        protected.name, protected.location.x = "Protected Prop", 4
        bpy.context.scene.collection.objects.link(protected)
        copy = base.copy()
        copy.name = "Working Surface"
        cube.material_slots[0].link, cube.material_slots[0].material = "OBJECT", copy
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_rotation = Vector((5, -6, 4)).to_track_quat("Z", "Y")
                area.spaces.active.region_3d.view_distance = 5.5

        def call(method, **params):
            return runtime.dispatch(method, params)

        def refresh(name, **params):
            return call("nodes.refresh_image", material_name="Working Surface", node_name="Albedo",
                        group_path=["Finish"], new_image_name=name, **params)

        def current_node():
            return bpy.data.materials["Working Surface"].node_tree.nodes["Finish"].node_tree.nodes["Albedo"]

        def graph(material, nested=True):
            result = call("nodes.inspect", material_name=material,
                          **({"group_path": ["Finish"]} if nested else {}),
                          max_nodes=100, max_sockets_per_direction=64)
            assert not result["truncated"]
            return {"nodes": [{key: value for key, value in node.items() if key not in {"location", "dimensions"}}
                              for node in result["nodes"]], "links": result["links"]}

        def undo():
            result = call("checkpoint.undo_last", confirm_global_undo=True, restore_snapshot=True)
            assert result["snapshot_marker_verified"], result

        def capture(name="Revision Prop"):
            regions = [area.spaces.active.region_3d for area in bpy.context.screen.areas if area.type == "VIEW_3D"]
            before = [region.view_location.copy() for region in regions]
            try:
                for region in regions:
                    region.view_location = bpy.data.objects[name].matrix_world.translation
                return call("viewport.capture", object_name=name, view="current", shading="material",
                            resolution=[640, 480], include_overlays=False)["path"]
            finally:
                for region, value in zip(regions, before, strict=True):
                    region.view_location = value

        def unchanged():
            assert graph("Source Surface") == protected_graph
            assert pixels(bpy.data.images["Original Albedo"]) == original_pixels
            result = call("scene.compare", snapshot_id=baseline["snapshot_id"])
            assert result["coverage_complete"] and result["status"] == "unchanged_within_scope", result

        def denied(code, **params):
            count, previous = len(bpy.data.images), current_node().image.name
            try:
                refresh("Denied Version", **params)
            except BridgeError as error:
                assert error.code == code, error.to_dict()
            else:
                raise AssertionError("Expected revision denial")
            assert len(bpy.data.images) == count and current_node().image.name == previous

        call("selection.inspect")
        denied("INVALID_ARGUMENT")  # Copying a material did not isolate its child group.
        call("shader_group.copy_for_node", material_name="Working Surface", node_name="Finish", new_name="Working Finish")
        protected_graph = graph("Source Surface")
        baseline = call("scene.snapshot", object_names=["Protected Prop"])
        selection = sorted(obj.name for obj in bpy.context.selected_objects)
        active = bpy.context.view_layer.objects.active.name
        captures = {"before": capture(), "protected_before": capture("Protected Prop")}
        for permission in ("allow_external_files", "allow_edit_materials"):
            setattr(prefs, permission, False)
            denied("PERMISSION_DENIED")
            setattr(prefs, permission, True)
        for flag, code in (("paused", "AGENT_PAUSED"), ("emergency_stopped", "EMERGENCY_STOPPED")):
            getattr(runtime.state, "set_" + flag)(True)
            denied(code)
            getattr(runtime.state, "set_" + flag)(False)
            runtime.state.set_paused(False)
        outside = Path(tempfile.gettempdir()) / "outside.png"
        png(outside, cool)
        denied("PERMISSION_DENIED", filepath=str(outside))
        call("context.set_mode", object_name="Revision Prop", mode="EDIT")
        denied("NOT_IMPLEMENTED")
        call("context.set_mode", object_name="Revision Prop", mode="OBJECT")
        # Mode-selection is an intentional fixture action, not a texture side effect.
        call("selection.set", object_names=selection, active_object=active)
        animated_tree = current_node().id_data
        animated_tree.animation_data_create().action = bpy.data.actions.new("Image Animation Guard")
        denied("NOT_IMPLEMENTED")
        action = animated_tree.animation_data.action
        animated_tree.animation_data.action = None
        bpy.data.actions.remove(action)
        runtime.checkpoints.clear()
        for alpha_mode in ("STRAIGHT", "PREMUL", "CHANNEL_PACKED", "NONE"):
            alpha_image = call("image.load", filepath=str(source), new_name="Alpha Probe", alpha_mode=alpha_mode)
            assert alpha_image["image"]["has_data"] and alpha_image["image"]["alpha_mode"] == alpha_mode
            undo()
            assert bpy.data.images.get("Alpha Probe") is None
        # External fixture change, not a bridge write: the original cached buffer must survive.
        png(source, cool)
        source_bytes = source.read_bytes()
        result = refresh("Refreshed Albedo")
        assert result["revision_mode"] == "new_image_for_node" and not result["previous_buffer_reloaded"]
        assert current_node().image.name == "Refreshed Albedo" and pixels(current_node().image) != original_pixels
        assert current_node().image.alpha_mode == "PREMUL" and current_node().interpolation == "Closest"
        assert source.read_bytes() == source_bytes
        unchanged()
        captures["refreshed"] = capture()
        undo()
        assert current_node().image.name == "Original Albedo" and bpy.data.images.get("Refreshed Albedo") is None
        assert pixels(current_node().image) == original_pixels
        captures["recovered"] = capture()
        result = refresh("Relocated Albedo", filepath=str(relocated))
        assert Path(current_node().image.filepath) == relocated
        unchanged()
        captures["relocated"] = capture()
        undo()

        # Repair an unloaded missing path without ever reading the old source/buffer.
        missing = bpy.data.images.new("Missing Source", 1, 1)
        missing.filepath, missing.source = str(directory / "missing.png"), "FILE"
        root = bpy.data.materials["Working Surface"].node_tree
        missing_node = root.nodes.new("ShaderNodeTexImage")
        missing_node.name, missing_node.image = "Missing", missing
        assert not missing.has_data
        runtime.checkpoints.clear()
        repaired = call("nodes.refresh_image", material_name="Working Surface", node_name="Missing",
                        new_image_name="Repaired Source", filepath=str(relocated))
        assert repaired["previous_image"]["loaded_size"] is None and not missing.has_data
        undo()
        assert bpy.data.materials["Working Surface"].node_tree.nodes["Missing"].image.name == "Missing Source"
        # Explicit revisions of dirty generated and packed FILE sources retain their data.
        for kind in ("generated", "packed"):
            if kind == "generated":
                retained = bpy.data.images.new("Dirty Generated", 8, 8)
                retained.pixels.foreach_set([.2, .4, .6, 1.] * 64)
                retained.update()
                assert retained.is_dirty
            else:
                retained = bpy.data.images.load(str(source), check_existing=False)
                retained.name = "Packed Original"
                retained.pack()
                assert retained.packed_file is not None
                # Fixture setup: packing invalidates its cache too; explicitly
                # materialize the known local packed source before measuring it.
                assert tuple(retained.size) == (64, 64)
            retained_name, retained_pixels = retained.name, pixels(retained)
            packed_bytes = bytes(retained.packed_file.data) if retained.packed_file else None
            root = bpy.data.materials["Working Surface"].node_tree
            probe = root.nodes.new("ShaderNodeTexImage")
            probe.name, probe.image = "Retained Probe", retained
            runtime.checkpoints.clear()
            revision = call("nodes.refresh_image", material_name="Working Surface", node_name="Retained Probe",
                            new_image_name="Retained Revision", filepath=str(relocated))
            assert not revision["image"]["packed"] and pixels(retained) == retained_pixels
            if packed_bytes is not None:
                assert bytes(retained.packed_file.data) == packed_bytes
            else:
                assert retained.is_dirty
            undo()
            retained = bpy.data.images[retained_name]
            assert bpy.data.materials["Working Surface"].node_tree.nodes["Retained Probe"].image == retained
            assert pixels(retained) == retained_pixels
            # Fixture-only unused probe removal avoids name ambiguity in the next case.
            bpy.data.materials["Working Surface"].node_tree.nodes.remove(
                bpy.data.materials["Working Surface"].node_tree.nodes["Retained Probe"])
        # The fixture-only root probe is unrelated to the connected nested material.
        root_before = graph("Working Surface", nested=False)
        nested_before = graph("Working Surface")
        for persistent in (False, True):
            original_bind = images.set_node_image
            def fault(context, params, persistent=persistent, original_bind=original_bind):
                original_bind(context, params)
                if persistent:
                    tree = bpy.data.materials["Working Surface"].node_tree
                    tree.nodes.new("ShaderNodeTexImage").image = bpy.data.images[params["image_name"]]
                raise RuntimeError("Injected post-binding failure")
            images.set_node_image = fault
            try:
                refresh("Failed Version")
            except BridgeError as error:
                assert error.context["rollback_verified"] is not persistent
                assert error.context["possible_mutation"] is persistent
                assert error.context["undo_boundary_finalized"]
            else:
                raise AssertionError("Expected native failure")
            finally:
                images.set_node_image = original_bind
            assert current_node().image.name == "Original Albedo"
            undo()
            assert bpy.data.images.get("Failed Version") is None
            assert graph("Working Surface", nested=False) == root_before
            assert graph("Working Surface") == nested_before
            unchanged()
        captures["protected_after"] = capture("Protected Prop")
        captures["final_recovered"] = capture()
        unchanged()
        assert sorted(obj.name for obj in bpy.context.selected_objects) == selection
        assert bpy.context.view_layer.objects.active.name == active and bpy.context.mode == "OBJECT"
        assert bpy.context.preferences.edit.undo_steps == 32
        assert source.read_bytes() == source_bytes
        print("BLENDER_IMAGE_REVISIONS_OK " + json.dumps({"blender": bpy.app.version_string,
            "native_reload_diagnostic": diagnostic,
            "nested_refresh_and_relocation_verified": True, "missing_unloaded_source_repaired": True,
            "original_cached_pixels_retained_and_recovered": True,
            "generated_dirty_and_packed_source_retained": True,
            "scope_permissions_pause_stop_verified": True,
            "partial_failure_measured_cleanup_and_native_recovery": True,
            "protected_pixels_and_graph_unchanged": True, "captures": captures,
            "project_saved": False, "user_preferences_saved": False,
            "in_place_reload_recovery_implemented": False,
            "visual_review_required": True, "full_artist_acceptance_verified": False}), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1)
