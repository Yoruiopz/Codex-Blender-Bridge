"""Owned UV-image mask sampling, explicit sculpting and retained native evidence.

Run only through the isolated native runner. Raw native setup/provider actions
and fixture-only renders are labeled separately from registered bridge calls.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
from array import array
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402

METHOD = "mesh.sculpt_mask_sample"
UV_NAME = "Explicit Mask UV"
RGBA_2X2 = ((0., .25, .5, 1.), (1., .5, .25, .75),
            (.25, .75, 1., .5), (.75, 1., 0., .25))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(owner):
    return None if owner is None else [int(owner.as_pointer()), owner.name]


def float_digest(values):
    return hashlib.sha256(b"".join(struct.pack("<f", value) for value in values)).hexdigest()


def input_digests(state, params):
    """Serialize independent native projections using the documented byte formats."""
    mesh = state["objects"][params["object_name"]]["mesh"]
    image = state["generated_images"][params["image_name"]]
    uv = next(layer for layer in mesh["uv"] if layer["name"] == params["uv_layer"])
    topology = bytearray(struct.pack("<IIII", len(mesh["coordinates"]), len(mesh["edges"]),
                                     len(mesh["loops"]), len(mesh["polygons"])))
    for edge in mesh["edges"]:
        topology.extend(struct.pack("<II", *edge[0]))
    for index in mesh["loops"]:
        topology.extend(struct.pack("<I", index))
    for face in mesh["polygons"]:
        topology.extend(struct.pack("<II", *face[:2]))
    return {"image_pixels_sha256_float32_le": float_digest(image["pixels"]),
            "channel_sha256_float32_le": float_digest(image["pixels"]["RGBA".index(params["channel"])::4]),
            "uv_sha256_float32_le": float_digest(value for item in uv["values"] for value in item),
            "geometry_sha256_float32_le": float_digest(value for vertex in mesh["coordinates"] for value in vertex),
            "topology_sha256": hashlib.sha256(topology).hexdigest()}


def image_values(image):
    values = array("f", [0.]) * len(image.pixels)
    image.pixels.foreach_get(values)
    return {"identity": identity(image), "source": image.source, "type": image.type,
            "size": list(image.size), "channels": image.channels, "is_float": image.is_float,
            "has_data": image.has_data, "alpha_mode": image.alpha_mode,
            "colorspace": image.colorspace_settings.name, "is_dirty": image.is_dirty,
            "use_fake_user": image.use_fake_user, "filepath": image.filepath,
            "pixels": list(values)}


def mesh_values(mesh):
    return {"identity": identity(mesh), "users": mesh.users,
            "coordinates": [list(vertex.co) for vertex in mesh.vertices],
            "vertex_flags": [[vertex.select, vertex.hide] for vertex in mesh.vertices],
            "edges": [[list(edge.vertices), edge.select, edge.hide] for edge in mesh.edges],
            "loops": [loop.vertex_index for loop in mesh.loops],
            "polygons": [[face.loop_start, face.loop_total, face.material_index, face.use_smooth,
                          face.select, face.hide] for face in mesh.polygons],
            "uv": [{"name": uv.name, "render": uv.active_render,
                    "values": [list(item.uv) for item in uv.data],
                    "pins": [item.pin_uv for item in uv.data]} for uv in mesh.uv_layers],
            "active_uv": mesh.uv_layers.active_index,
            "color_attributes": [{"name": attr.name, "domain": attr.domain, "type": attr.data_type,
                                  "values": [list(item.color) for item in attr.data]}
                                 for attr in mesh.color_attributes],
            "attributes": [[attr.name, attr.domain, attr.data_type, len(attr.data)] for attr in mesh.attributes],
            "color_roles": [mesh.color_attributes.active_color_index, mesh.color_attributes.render_color_index],
            "materials": [identity(material) for material in mesh.materials]}


def material_values(material):
    tree = material.node_tree
    return {"identity": identity(material), "diffuse": list(material.diffuse_color),
            "use_nodes": material.use_nodes,
            "nodes": [] if tree is None else [
                {"identity": identity(node), "type": node.bl_idname,
                 "location": list(node.location),
                 "inputs": [[socket.identifier, list(socket.default_value) if hasattr(socket.default_value, "__len__")
                             and not isinstance(socket.default_value, str) else socket.default_value]
                            for socket in node.inputs if hasattr(socket, "default_value")
                            and socket.type in {"VALUE", "INT", "BOOLEAN", "VECTOR", "RGBA", "STRING"}]}
                for node in tree.nodes],
            "links": [] if tree is None else [[link.from_node.name, link.from_socket.identifier,
                                                link.to_node.name, link.to_socket.identifier] for link in tree.links]}


def snapshot(runtime):
    # Read raw stored selection before any global context getter. In particular,
    # selected_objects may normalize inconsistent native selection and hide the
    # very effect this independent projection is meant to detect. The isolated
    # factory fixture has one stored Scene/ViewLayer; no contextual lookup is
    # needed to inspect their explicit selection flags.
    assert len(bpy.data.scenes) == 1
    scene = bpy.data.scenes[0]
    assert len(scene.view_layers) == 1
    layer = scene.view_layers[0]
    assert len(layer.objects) <= 256
    stored_selection = [[identity(obj), bool(obj.select_get(view_layer=layer))]
                        for obj in sorted(layer.objects, key=lambda owner: owner.name)]
    selected = sorted([owner for owner, selected in stored_selection if selected])
    context = bpy.context
    return {
        "objects": {obj.name: {"identity": identity(obj), "data": identity(obj.data),
                               "parent": identity(obj.parent), "mode": obj.mode,
                               "location": list(obj.location), "rotation": list(obj.rotation_euler),
                               "scale": list(obj.scale), "matrix": [list(row) for row in obj.matrix_world],
                               "hidden": [obj.hide_viewport, obj.hide_render, obj.hide_get(view_layer=layer)],
                               "modifiers": [[modifier.name, modifier.type] for modifier in obj.modifiers],
                               "mesh": mesh_values(obj.data) if obj.type == "MESH" else None}
                    for obj in sorted(bpy.data.objects, key=lambda owner: owner.name)},
        "generated_images": {image.name: image_values(image) for image in sorted(bpy.data.images, key=lambda owner: owner.name)
                             if image.source == "GENERATED"},
        "materials": {material.name: material_values(material) for material in sorted(bpy.data.materials, key=lambda owner: owner.name)},
        "context": {"scene": identity(context.scene), "view_layer": identity(layer),
                    "window": None if context.window is None else int(context.window.as_pointer()),
                    "mode": context.mode, "active": identity(layer.objects.active),
                    "selected": selected, "raw_stored_selection_flags": stored_selection,
                    "frame": [scene.frame_current, float(scene.frame_subframe)],
                    "camera": identity(scene.camera)},
        "bookkeeping": {"marker": scene.get("_codex_bridge_undo_marker"),
                        "checkpoints": runtime.checkpoints.list(200)},
    }


def settle_alias_setup(proof, alias):
    """Measure an owned raw-link observer control before any bridge dispatch.

    This brackets full fixture snapshots, not individual native getters. A
    membership change during A-to-B observation must not be attributed to the
    absent typed call, nor to a particular getter without narrower evidence.
    """
    path = Path(tempfile.gettempdir())/"sculpt-mask-alias-setup-control.json"
    history_before = proof.runtime.state.history(50)
    providers_before = proof.total_permission_provider_calls
    first = snapshot(proof.runtime)
    second = snapshot(proof.runtime)
    history_after = proof.runtime.state.history(50)
    providers_after = proof.total_permission_provider_calls
    alias_id = identity(alias)
    first_flags = first["context"]["raw_stored_selection_flags"]
    second_flags = second["context"]["raw_stored_selection_flags"]
    first_has_alias = any(owner == alias_id for owner, _selected in first_flags)
    second_has_alias = any(owner == alias_id for owner, _selected in second_flags)
    alias_realized = not first_has_alias and second_has_alias
    observation = "ALIAS_MEMBERSHIP_REALIZED_DURING_FULL_SNAPSHOT_OBSERVATION" if alias_realized else (
        "ALIAS_ALREADY_PRESENT_AT_FIRST_SNAPSHOT" if first_has_alias and second_has_alias else
        "NO_ALIAS_MEMBERSHIP_REALIZATION_OBSERVED")
    control = {
        "label": "No-bridge raw alias setup snapshot control", "status": "VERDICT_PENDING",
        "fixture_setup_raw_native": True, "bridge_dispatch_invoked": False,
        "typed_handler_invoked": False, "individual_getter_attribution": False,
        "observation_scope": "Full snapshot A-to-B interval; no specific native getter is identified.",
        "alias": alias_id, "before": first, "after": second,
        "history_before": history_before, "history_after": history_after,
        "history_count_before": len(history_before), "history_count_after": len(history_after),
        "permission_provider_count_before": providers_before,
        "permission_provider_count_after": providers_after,
        "raw_flag_membership_before": first_flags, "raw_flag_membership_after": second_flags,
        "first_snapshot_has_alias": first_has_alias, "second_snapshot_has_alias": second_has_alias,
        "alias_membership_realized_without_bridge_call": alias_realized,
        "attribution_status": "NO_BRIDGE_FULL_SNAPSHOT_INTERVAL_REPRODUCED_MEMBERSHIP_DELTA" if alias_realized else "INCONCLUSIVE_NO_MEMBERSHIP_DELTA",
        "observation": observation, "release_acceptance": False,
    }
    # Preserve complete raw A/B endpoints before any control verdict can fail.
    path.write_text(json.dumps(control, indent=2, allow_nan=False)+"\n")
    assert canonical(history_before) == canonical(history_after)
    assert providers_before == providers_after
    def without_raw_flags(value):
        return {**value, "context": {key: item for key, item in value["context"].items()
                                     if key != "raw_stored_selection_flags"}}
    assert canonical(without_raw_flags(first)) == canonical(without_raw_flags(second)), "No-bridge observer changed more than raw membership"
    expected = sorted([*first_flags, [alias_id, False]], key=lambda row: row[0][1]) if not first_has_alias else first_flags
    if alias_realized:
        assert canonical(second_flags) == canonical(expected), "Only the unselected raw-linked alias may be realized"
    else:
        assert canonical(first_flags) == canonical(second_flags), "Unexpected raw selection change without a bridge call"
    assert alias_realized, "Inconclusive no-bridge observation; preserve raw evidence without attributing the prior delta"
    control["only_alias_entry_realized"] = alias_realized
    control["unchanged_other_native_projection_and_history"] = True
    # Explicit raw setup settlement belongs to this disposable fixture. It is
    # neither a bridge operation nor a claimed restoration/undo mechanism.
    bpy.data.scenes[0].view_layers[0].update()
    stable_first = snapshot(proof.runtime)
    stable_second = snapshot(proof.runtime)
    settled_history = proof.runtime.state.history(50)
    settled_providers = proof.total_permission_provider_calls
    control.update({"status": "SETTLEMENT_VERDICT_PENDING", "owned_fixture_stored_layer_update": True,
                    "stable_before": stable_first, "stable_after": stable_second,
                    "settled_history": settled_history, "settled_history_count": len(settled_history),
                    "settled_permission_provider_count": settled_providers})
    path.write_text(json.dumps(control, indent=2, allow_nan=False)+"\n")
    assert canonical(stable_first) == canonical(stable_second), "Owned raw setup must be stable before typed sampling"
    assert canonical(history_before) == canonical(settled_history) and providers_before == settled_providers
    assert canonical(without_raw_flags(first)) == canonical(without_raw_flags(stable_first)), "Setup settlement changed protected native data"
    assert canonical(stable_first["context"]["raw_stored_selection_flags"]) == canonical(expected)
    control.update({"status": "BOUNDED_FIXTURE_CONTROL_PASS", "two_settled_snapshots_equal": True,
                    "bridge_permission_providers_invoked": False, "production_readonly_acceptance": False,
                    "native_undo_verified": False, "durable_recovery_verified": False})
    raw = (json.dumps(control, indent=2, allow_nan=False)+"\n").encode()
    path.write_bytes(raw)
    return {"evidence_file": str(path), "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            "observation": observation, "alias_membership_realized_without_bridge_call": alias_realized,
            "two_settled_snapshots_equal": True, "observations": control}


def make_image(name, width, height, values):
    image = bpy.data.images.new(name, width=width, height=height, alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "CHANNEL_PACKED"
    image.pixels.foreach_set(array("f", values))
    image.update()
    assert image.source == "GENERATED" and image.type == "UV_TEST" and image.has_data
    return image


def make_meshes():
    mesh = bpy.data.meshes.new("Mask Seam Mesh")
    mesh.from_pydata([(-1., -1., 0.), (1., -1., 0.), (1., 1., 0.), (-1., 1., 0.)], [], [(0, 1, 2), (0, 2, 3)])
    mesh.update()
    uv = mesh.uv_layers.new(name=UV_NAME)
    for item, value in zip(uv.data, ((.25, .25), (.75, .25), (.5, .5), (.75, .75), (.5, .5), (0., 1.)), strict=True):
        item.uv = value
    target = bpy.data.objects.new("Mask Seam", mesh)
    bpy.context.scene.collection.objects.link(target)
    grid = bpy.data.meshes.new("Painted Mask Grid Mesh")
    grid.from_pydata([(x, y, 0.) for y in (-1., 0., 1.) for x in (-1., 0., 1.)], [],
                     [(y*3+x, y*3+x+1, (y+1)*3+x+1, (y+1)*3+x) for y in range(2) for x in range(2)])
    grid.update()
    grid_uv = grid.uv_layers.new(name=UV_NAME)
    for loop, item in zip(grid.loops, grid_uv.data, strict=True):
        co = grid.vertices[loop.vertex_index].co
        item.uv = ((co.x+1.)/2., (co.y+1.)/2.)
    obj = bpy.data.objects.new("Painted Mask Grid", grid)
    bpy.context.scene.collection.objects.link(obj)
    protected = bpy.data.objects.new("Protected Mask Grid", grid.copy())
    protected.location.x = 6.
    bpy.context.scene.collection.objects.link(protected)
    material = bpy.data.materials.new("Protected Mask Material")
    material.use_nodes = True
    material.node_tree.nodes.clear()
    emission = material.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (.06, .25, .6, 1.)
    output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(emission.outputs[0], output.inputs["Surface"])
    grid.materials.append(material)
    protected.data.materials.append(material)
    bpy.context.view_layer.update()
    return target, obj, protected


class Proof:
    def __init__(self, runtime, grants):
        self.runtime, self.grants, self.rows = runtime, grants, []
        self.counting = False
        self.calls = 0
        self.trigger_at = None
        self.action = None
        self.provider_before = self.provider_after = None
        self.target = self.image = None
        self.total_permission_provider_calls = 0

    def permission_values(self):
        self.total_permission_provider_calls += 1
        if self.counting:
            self.calls += 1
            if self.trigger_at == self.calls:
                self.provider_before = snapshot(self.runtime)
                if self.action == "PIXELS":
                    pixels = array("f", self.image.pixels)
                    pixels[0] = .875
                    self.image.pixels.foreach_set(pixels)
                    self.image.update()
                elif self.action == "UV":
                    self.target.data.uv_layers[UV_NAME].data[0].uv = (.5, .25)
                elif self.action == "COORDINATE":
                    self.target.data.vertices[3].co.x += .125
                elif self.action == "CONTEXT":
                    bpy.context.scene.frame_set(24, subframe=.25)
                else:
                    raise AssertionError("Unknown owned provider action")
                self.provider_after = snapshot(self.runtime)
        return self.grants

    def sample(self, label, request, expected=None, *, error=None, trigger_at=None, action=None):
        self.calls, self.trigger_at, self.action = 0, trigger_at, action
        self.provider_before = self.provider_after = None
        before = snapshot(self.runtime)
        history_before = self.runtime.state.history(50)
        result = failure = None
        self.counting = True
        try:
            result = self.runtime.dispatch(METHOD, request)
        except BridgeError as caught:
            failure = caught.to_dict()
        finally:
            self.counting = False
        after = snapshot(self.runtime)
        history_after = self.runtime.state.history(50)
        row = {"label": label, "method": METHOD, "request": request, "expected_mask_weights": expected,
               "expected_error": error, "result": result, "error": failure,
               "before": before, "provider_before": self.provider_before, "provider_after": self.provider_after,
               "after": after, "provider_action": action, "permission_provider_calls": self.calls,
               "learned_trigger_ordinal": trigger_at, "history_receipt": history_after[0],
               "native_undo_verified": False, "durable_recovery_verified": False}
        (Path(tempfile.gettempdir())/"sculpt-mask-current-case.json").write_text(json.dumps(row, indent=2, allow_nan=False)+"\n")
        assert (None if failure is None else failure["code"]) == error, (label, failure, error)
        assert (result is None) == (error is not None), label
        assert len(history_before) < 49 and len(history_after) == len(history_before)+1
        assert history_after[1:] == history_before
        assert history_after[0]["tool"] == METHOD and history_after[0]["success"] == (error is None)
        reference = self.provider_after if action is not None else before
        if action is not None:
            assert self.provider_before is not None and self.provider_after is not None and self.calls == trigger_at
            assert canonical(self.provider_before) != canonical(self.provider_after), "Provider arm must change measured input"
        assert canonical(reference) == canonical(after), (label, "Bridge changed declared native state or checkpoints")
        if result is not None:
            assert result["vertex_indices"] == request["vertex_indices"]
            assert len(result["mask_weights"]) == len(expected)
            assert all(abs(actual-wanted) < 1e-7 for actual, wanted in zip(result["mask_weights"], expected, strict=True))
            assert result["snapshot_only"] is True and result["live_image_binding"] is False
            assert not result["geometry_modified"] and not result["image_modified"] and not result["scene_evaluated"]
            assert result["sampling"]["filter"] == "BILINEAR_PIXEL_CENTRE"
            assert result["sampling"]["edge_mode"] == "CLAMP" and result["sampling"]["color_alpha_transform"] is False
            independently_read_digests = input_digests(before, request)
            for key, wanted in independently_read_digests.items():
                assert result["input_evidence"][key] == wanted, (label, key)
            row["independent_input_digests"] = independently_read_digests
        row["complete_declared_native_projection_preserved"] = True
        self.rows.append(row)
        return result, self.calls


def request(obj, image, *, channel="R", invert=False, reduction="MEAN", vertices=None):
    return {"object_name": obj.name, "uv_layer": UV_NAME,
            "vertex_indices": [3, 0, 2, 1] if vertices is None else vertices,
            "image_name": image.name, "channel": channel, "invert": invert, "corner_reduction": reduction}


def analytical_cases(proof, seam, image, other):
    # Independent analytical values for [vertex3, seam vertex0, vertex2, vertex1].
    # Pixel-centre UVs address exact pixels; vertex2 is the four-pixel average.
    channels = {"R": (.25, (0., .75), .5, 1.),
                "G": (.75, (.25, 1.), .625, .5),
                "B": (1., (.5, 0.), .4375, .25),
                "A": (.5, (1., .25), .625, .75)}
    for channel, (edge, split, centre, bottom) in channels.items():
        for invert in (False, True):
            values = [1.-value for value in split] if invert else list(split)
            rest = [1.-value for value in (edge, centre, bottom)] if invert else [edge, centre, bottom]
            for reduction in ("MIN", "MAX", "MEAN"):
                reduced = min(values) if reduction == "MIN" else max(values) if reduction == "MAX" else sum(values)/2.
                expected = [rest[0], reduced, rest[1], rest[2]]
                result, _ = proof.sample(f"2x2 {channel} invert={invert} {reduction}",
                                         request(seam, image, channel=channel, invert=invert, reduction=reduction), expected)
                assert result["corner_counts"] == [1, 2, 2, 1] and result["seam_vertices"] == [0]
    # The same stored UVs on a 3x2 image exercise non-centre bilinear interpolation.
    # R bottom=[0,.5,1], top=[1,.25,0] yields .125/.0625 at the seam.
    proof.sample("3x2 independent bilinear", request(seam, other), [1., .09375, .375, .875])


def stale_cases(proof, seam, image):
    wanted = [.25, .375, .5, 1.]
    for action in ("PIXELS", "UV", "COORDINATE", "CONTEXT"):
        params = request(seam, image)
        _, learned = proof.sample("Provider control "+action, params, wanted)
        original_pixels = array("f", image.pixels)
        original_uv = [tuple(item.uv) for item in seam.data.uv_layers[UV_NAME].data]
        original_coordinate = tuple(seam.data.vertices[3].co)
        original_frame = (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe)
        proof.target, proof.image = seam, image
        proof.sample("Late provider "+action, params, error="OPERATION_FAILED", trigger_at=learned, action=action)
        # Owned fixture reset only, after raw provider/after endpoints were retained.
        # This is not bridge recovery, global undo or a durable backup.
        image.pixels.foreach_set(original_pixels)
        image.update()
        for item, value in zip(seam.data.uv_layers[UV_NAME].data, original_uv, strict=True):
            item.uv = value
        seam.data.vertices[3].co = original_coordinate
        bpy.context.scene.frame_set(original_frame[0], subframe=original_frame[1])


def render_capture(folder, filename):
    scene = bpy.context.scene
    scene.render.filepath = str(folder/filename)
    bpy.ops.render.render(write_still=True)
    # Reading this owned fixture PNG is separate from the generated-image tool.
    image = bpy.data.images.load(scene.render.filepath, check_existing=False)
    return {"path": scene.render.filepath,
            "sha256": hashlib.sha256(Path(scene.render.filepath).read_bytes()).hexdigest()}, tuple(image.pixels)


def artist_workflow(proof, obj, protected):
    from mathutils import Vector

    call = proof.runtime.dispatch
    created = call("image.create", {"new_name": "Painted Sculpt Source", "width": 2, "height": 2,
                                     "role": "DATA", "color": [0., 0., 0., 1.]})
    source = bpy.data.images["Painted Sculpt Source"]
    before_source = image_values(source)
    painted = call("image.paint_version", {"image_name": source.name, "new_name": "Painted Sculpt Mask",
                                             "strokes": [{"points": [[.25, .25]], "radius_pixels": .5,
                                                          "hardness": 1., "opacity": 1., "color": [1., 0., 0., 1.]}]})
    mask = bpy.data.images["Painted Sculpt Mask"]
    assert image_values(source) == before_source
    assert list(mask.pixels)[::4] == [1., 0., 0., 0.]
    expected = [1., .5, 0., .5, .25, 0., 0., 0., 0.]
    sampled, _ = proof.sample("Painted image to sculpt snapshot", request(obj, mask, reduction="MAX", vertices=list(range(9))), expected)
    folder = Path(tempfile.gettempdir())/"sculpt-mask-evidence"
    folder.mkdir()
    scene, camera = bpy.context.scene, bpy.data.objects["Camera"]
    camera.location = (3., -4., 5.)
    camera.rotation_euler = (Vector((0., 0., .2))-camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type, camera.data.ortho_scale = "ORTHO", 3.6
    scene.camera = camera
    scene.render.engine = "CYCLES"
    scene.cycles.device, scene.cycles.samples = "CPU", 4
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = 96
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    bpy.data.objects["Cube"].hide_render = True
    bpy.data.objects["Mask Seam"].hide_render = True
    before_capture, before_pixels = render_capture(folder, "sculpt-mask-before.png")
    before = snapshot(proof.runtime)
    params = {"object_name": obj.name, "vertex_indices": sampled["vertex_indices"], "mask_weights": sampled["mask_weights"],
              "strokes": [{"center": [0., 0., 0.], "radius": 10., "direction": [0., 0., 1.],
                           "strength": .5, "falloff": "CONSTANT"}]}
    result = call("mesh.sculpt_brush", params)
    after = snapshot(proof.runtime)
    assert result["changed_vertices"] == 4
    original = before["objects"][obj.name]["mesh"]["coordinates"]
    for index, (vertex, weight) in enumerate(zip(obj.data.vertices, expected, strict=True)):
        assert list(vertex.co) == [*original[index][:2], weight*.5], (index, list(vertex.co), weight)
    protected_before = before["objects"][protected.name]
    assert canonical(protected_before) == canonical(after["objects"][protected.name])
    assert canonical(before["generated_images"]) == canonical(after["generated_images"])
    assert canonical(before["materials"]) == canonical(after["materials"])
    assert canonical(before["context"]) == canonical(after["context"])
    projected_before, projected_after = json.loads(canonical(before)), json.loads(canonical(after))
    projected_before.pop("bookkeeping")
    projected_after.pop("bookkeeping")
    projected_before["objects"][obj.name]["mesh"].pop("coordinates")
    projected_after["objects"][obj.name]["mesh"].pop("coordinates")
    assert canonical(projected_before) == canonical(projected_after)
    after_capture, after_pixels = render_capture(folder, "sculpt-mask-after.png")
    changed = sum(before_pixels[index:index+4] != after_pixels[index:index+4] for index in range(0, len(before_pixels), 4))
    assert changed > 20 and before_capture["sha256"] != after_capture["sha256"]
    return {"typed_image_create": created, "typed_image_paint_version": painted,
            "sampled_mask": sampled, "typed_sculpt_request": params, "typed_sculpt_result": result,
            "before": before, "after": after, "expected_weights": expected,
            "expected_z": [weight*.5 for weight in expected], "zero_mask_vertices": [2, 5, 6, 7, 8],
            "captures": {"before": before_capture, "after": after_capture, "changed_rgba_pixels": changed},
            "fixture_native_render": True, "source_image_unchanged_by_paint": True,
            "protected_geometry_uv_materials_context_images_verified": True,
            "native_undo_verified": False, "durable_recovery_verified": False}


def main():
    assert bpy.app.background, "Run only through the isolated native runner"
    bpy.context.preferences.use_preferences_save = False
    blender_codex_bridge.register()
    runtime = get_runtime()
    grants = {permission.value: permission in {Permission.INSPECT_SCENE, Permission.EDIT_MESH, Permission.EDIT_MATERIALS}
              for permission in Permission}
    proof = Proof(runtime, grants)
    manager = PermissionManager(proof.permission_values)
    runtime.permissions = runtime.executor.permissions = manager
    runtime.registry.enable_toolset("mesh")
    runtime.registry.enable_toolset("materials")
    seam, grid, protected = make_meshes()
    image = make_image("Analytical 2x2 Mask", 2, 2, [value for pixel in RGBA_2X2 for value in pixel])
    other = make_image("Analytical 3x2 Mask", 3, 2, [value for red in (0., .5, 1., 1., .25, 0.) for value in (red, .25, .5, 1.)])
    bpy.context.scene.frame_set(23, subframe=.125)
    analytical_cases(proof, seam, image, other)
    alias = bpy.data.objects.new("Shared Read-Only Mask Alias", seam.data)
    alias.hide_render = True
    bpy.context.scene.collection.objects.link(alias)
    alias_setup_control = settle_alias_setup(proof, alias)
    proof.sample("Shared base mesh read-only", request(seam, image), [.25, .375, .5, 1.])
    runtime.state.set_paused(True)
    proof.sample("Paused read-only sampling", request(seam, image), [.25, .375, .5, 1.])
    runtime.state.set_paused(False)
    grants[Permission.INSPECT_SCENE.value] = False
    proof.sample("Inspection permission denied", request(seam, image), error="PERMISSION_DENIED")
    grants[Permission.INSPECT_SCENE.value] = True
    original_uv = tuple(seam.data.uv_layers[UV_NAME].data[0].uv)
    seam.data.uv_layers[UV_NAME].data[0].uv = (-.25, .25)
    proof.sample("Unsupported out-of-range UV", request(seam, image), error="NOT_IMPLEMENTED")
    seam.data.uv_layers[UV_NAME].data[0].uv = original_uv
    stale_cases(proof, seam, image)
    workflow = artist_workflow(proof, grid, protected)
    evidence = {"blender_version": bpy.app.version_string,
                "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "fixture_setup_raw_native": True, "fixture_provider_actions_raw_native": True,
                "fixture_resets_after_retained_stale_endpoints_are_not_bridge_recovery": True,
                "alias_setup_snapshot_control": alias_setup_control,
                "sample_rows": proof.rows, "artist_workflow": workflow,
                "native_undo_verified": False, "durable_recovery_verified": False,
                "full_artist_quality_accepted": False, "four_k_qualified": False,
                "project_saved": False, "windows_qualified": False, "release_acceptance": False}
    path = Path(tempfile.gettempdir())/"sculpt-mask-evidence.json"
    raw = (json.dumps(evidence, indent=2, allow_nan=False)+"\n").encode()
    path.write_bytes(raw)
    print("BLENDER_SCULPT_MASK_OK "+canonical({
        "blender_version": bpy.app.version_string, "evidence_file": str(path),
        "evidence_sha256": hashlib.sha256(raw).hexdigest(), "sample_case_count": len(proof.rows),
        "analytical_2x2_cases": 24, "analytical_3x2_cases": 1, "late_provider_refusals": 4,
        "alias_setup_snapshot_control": {key: value for key, value in alias_setup_control.items() if key != "observations"},
        "complete_declared_native_projection_preserved": True,
        "typed_paint_sample_sculpt_verified": True, "zero_mask_and_protected_vertices_verified": True,
        "captures": workflow["captures"], "native_undo_verified": False,
        "durable_recovery_verified": False, "full_artist_quality_accepted": False,
        "four_k_qualified": False, "project_saved": False, "release_acceptance": False,
    }), flush=True)
    blender_codex_bridge.unregister()


if __name__ == "__main__":
    main()
