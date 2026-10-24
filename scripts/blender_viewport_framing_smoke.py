"""Eight bounded exact-object captures in the runner's disposable desktop scene.

Run through run_blender_checks.py only. This fixture does not save a project or
preferences, launch Blender, fit manually, or require Pillow inside Blender.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import sys
import tempfile
import threading
import traceback
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

CASES = (
    ("front_landscape", "front", (768, 512), "PERSP"),
    ("back_portrait", "back", (512, 768), "ORTHO"),
    ("left_square", "left", (640, 640), "PERSP"),
    ("right_landscape", "right", (768, 512), "ORTHO"),
    ("top_portrait", "top", (512, 768), "PERSP"),
    ("bottom_square", "bottom", (640, 640), "ORTHO"),
    ("current_perspective_portrait", "current", (512, 768), "PERSP"),
    ("current_orthographic_landscape", "current", (768, 512), "ORTHO"),
)
# Independent standard Blender world directions; never read production axis quats.
AXIS_DIRECTIONS = {
    "front": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "back": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(block):
    return None if block is None else {"name": block.name, "pointer": block.as_pointer()}


def camera_state(camera):
    if camera is None:
        return None
    data = camera.data
    return {
        "object": identity(camera),
        "data": identity(data),
        **{
            name: getattr(data, name)
            for name in (
                "type",
                "lens",
                "sensor_fit",
                "sensor_width",
                "sensor_height",
                "ortho_scale",
                "clip_start",
                "clip_end",
                "shift_x",
                "shift_y",
            )
        },
    }


def context_state(scene, window, space, prefs):
    """Authoritative RNA, excluding draw caches and expected Render Result output."""
    region = space.region_3d
    render = scene.render
    sampling = {}
    for owner_name, names in (
        ("eevee", ("taa_samples", "taa_render_samples")),
        ("cycles", ("samples", "preview_samples")),
    ):
        owner = getattr(scene, owner_name, None)
        if owner is not None:
            sampling[owner_name] = {
                name: getattr(owner, name) for name in names if hasattr(owner, name)
            }
    return {
        "scene": identity(bpy.context.scene),
        "view_layer": {
            "name": bpy.context.view_layer.name,
            "pointer": bpy.context.view_layer.as_pointer(),
        },
        "window": window.as_pointer(),
        "window_scene": identity(window.scene),
        "window_view_layer": {
            "name": window.view_layer.name,
            "pointer": window.view_layer.as_pointer(),
        },
        "mode": bpy.context.mode,
        "active": identity(bpy.context.view_layer.objects.active),
        "selection": sorted(obj.name for obj in bpy.context.selected_objects),
        "view": {
            "distance": region.view_distance,
            "location": list(region.view_location),
            "rotation": list(region.view_rotation),
            "perspective": region.view_perspective,
            "camera_offset": list(region.view_camera_offset),
            "camera_zoom": region.view_camera_zoom,
            "lock_rotation": region.lock_rotation,
            "clip_planes_enabled": region.use_clip_planes,
        },
        "viewport": {
            "lens": space.lens,
            "clip_start": space.clip_start,
            "clip_end": space.clip_end,
            "camera": identity(space.camera),
            "lock_object": identity(space.lock_object),
            "lock_cursor": space.lock_cursor,
            "local_view": space.local_view is not None,
            "quad_view_count": len(space.region_quadviews),
            "overlays": space.overlay.show_overlays,
            "shading": {
                name: list(value) if name == "background_color" else value
                for name in (
                    "type",
                    "light",
                    "color_type",
                    "background_type",
                    "background_color",
                    "show_shadows",
                    "show_cavity",
                    "show_specular_highlight",
                )
                for value in (getattr(space.shading, name),)
            },
        },
        "render": {
            **{
                name: getattr(render, name)
                for name in (
                    "filepath",
                    "engine",
                    "resolution_x",
                    "resolution_y",
                    "resolution_percentage",
                    "use_border",
                    "use_crop_to_border",
                    "border_min_x",
                    "border_max_x",
                    "border_min_y",
                    "border_max_y",
                )
            },
            "image_format": render.image_settings.file_format,
            "color_mode": render.image_settings.color_mode,
            "sampling": sampling,
        },
        "objects": [
            {
                "object": identity(obj),
                "data": identity(obj.data),
                "type": obj.type,
                "matrix_world": [list(row) for row in obj.matrix_world],
                "hidden": obj.hide_get(),
                "hide_viewport": obj.hide_viewport,
                "hide_render": obj.hide_render,
                "selected": obj.select_get(),
                "materials": [identity(slot.material) for slot in obj.material_slots],
            }
            for obj in sorted(scene.objects, key=lambda obj: obj.name)
        ],
        "camera": camera_state(scene.camera),
        "datablocks": {
            name: [identity(block) for block in getattr(bpy.data, name)]
            for name in ("objects", "meshes", "cameras", "materials")
        },
        "consent": {
            name: getattr(prefs, name)
            for name in (
                "allow_execute_python",
                "allow_save_project",
                "allow_delete_objects",
                "allow_external_files",
            )
        },
        "preferences_auto_save": bpy.context.preferences.use_preferences_save,
    }


def assert_context_restored(before, after, label):
    """Keep every field exact except float32 quaternion accessor round trips."""
    expected = {
        **before,
        "view": {name: value for name, value in before["view"].items() if name != "rotation"},
    }
    actual = {
        **after,
        "view": {name: value for name, value in after["view"].items() if name != "rotation"},
    }
    assert expected == actual, label
    first, second = before["view"]["rotation"], after["view"]["rotation"]
    assert all(
        abs(sum(value * value for value in quat) - 1.0) < 2e-6 for quat in (first, second)
    ), label
    difference = min(
        max(abs(a - b) for a, b in zip(first, second, strict=True)),
        max(abs(a + b) for a, b in zip(first, second, strict=True)),
    )
    assert difference <= 2e-6, (label, first, second)
    return {
        "all_other_authoritative_fields_exact": True,
        "quaternion_component_equivalence_maximum_error": difference,
        "quaternion_component_tolerance": 2e-6,
    }


def measured_projection(scene, space, world_corners, requested_view, expected_directions):
    """Forward-project observed fitted RNA; do not call or repeat the fit solver."""
    assert threading.current_thread() is threading.main_thread()
    region = space.region_3d
    rotation = region.view_rotation.copy()
    location = region.view_location.copy()
    distance, perspective = region.view_distance, region.view_perspective
    width, height = scene.render.resolution_x, scene.render.resolution_y
    look, up = rotation @ Vector((0.0, 0.0, -1.0)), rotation @ Vector((0.0, 1.0, 0.0))
    expected_look, expected_up = expected_directions[:2]
    assert (look - Vector(expected_look)).length < 1e-5, (requested_view, list(look))
    assert (up - Vector(expected_up)).length < 1e-5, (requested_view, list(up))
    assert perspective == ("ORTHO" if requested_view != "current" else expected_directions[2])
    # Build a conventional world-to-view transform from the observed RNA. The
    # orthographic viewport has no distance translation. No view.update() call:
    # derived draw caches are outside the restoration contract being measured.
    view = rotation.inverted().to_matrix().to_4x4() @ Matrix.Translation(-location)
    if perspective == "PERSP":
        view = Matrix.Translation((0.0, 0.0, -distance)) @ view
    near, far, lens = space.clip_start, space.clip_end, space.lens
    # The exact-build source receipt qualifies this viewport-to-viewplane map:
    # default sensor 36mm, zoom 2, AUTO sensor fit, square viewport-render pixels.
    # Construct a standard clip matrix independently of the production solver.
    size = distance * 36.0 / lens if perspective == "ORTHO" else 36.0 * near / lens
    pixel_size = size * 2.0 / max(width, height)
    right, top = width * 0.5 * pixel_size, height * 0.5 * pixel_size
    if perspective == "PERSP":
        projection = Matrix(
            (
                (near / right, 0, 0, 0),
                (0, near / top, 0, 0),
                (0, 0, -(far + near) / (far - near), -2 * far * near / (far - near)),
                (0, 0, -1, 0),
            )
        )
    else:
        projection = Matrix(
            ((1 / right, 0, 0, 0), (0, 1 / top, 0, 0), (0, 0, -2 / far, 0), (0, 0, 0, 1))
        )
    ndc = []
    for corner in world_corners:
        clip = projection @ view @ Vector((*corner, 1.0))
        assert clip.w > 0
        point = [clip[axis] / clip.w for axis in range(3)]
        assert all(math.isfinite(value) for value in point)
        assert max(abs(point[0]), abs(point[1])) <= 0.9002, point
        assert -1 < point[2] < 1, point
        ndc.append(point)
    maximum_xy = max(abs(value) for point in ndc for value in point[:2])
    assert abs(maximum_xy - 0.9) < 0.002, maximum_xy
    bounds = [
        min(point[0] for point in ndc),
        min(point[1] for point in ndc),
        max(point[0] for point in ndc),
        max(point[1] for point in ndc),
    ]
    return {
        "observation": "actual_temporary_fitted_RNA_before_original_restoration",
        "orientation_verified_against_independent_world_vectors": True,
        "look_direction": list(look),
        "up_direction": list(up),
        "location": list(location),
        "rotation": list(rotation),
        "distance": distance,
        "perspective": perspective,
        "lens": lens,
        "clip_start": near,
        "clip_end": far,
        "resolution": [width, height],
        "world_corners": world_corners,
        "ndc_corners": ndc,
        "projection_matrix": [list(row) for row in projection],
        "view_matrix": [list(row) for row in view],
        "maximum_absolute_ndc_xy": maximum_xy,
        "ndc_bounds": bounds,
        "expected_red_mask_bounds_pixels_top_left": [
            (bounds[0] + 1) * width / 2,
            (1 - bounds[3]) * height / 2,
            (bounds[2] + 1) * width / 2,
            (1 - bounds[1]) * height / 2,
        ],
        "fixed_frame_fraction": 0.9,
    }


def run():
    runtime = None
    try:
        assert not bpy.app.background and not bpy.data.filepath, (
            "Use the isolated factory desktop runner."
        )
        assert {obj.name for obj in bpy.data.objects} == {"Cube", "Camera", "Light"}
        bpy.context.preferences.use_preferences_save = False
        bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
        from blender_codex_bridge import viewport
        from blender_codex_bridge.errors import BridgeError
        from blender_codex_bridge.preferences import get_preferences
        from blender_codex_bridge.runtime import get_runtime

        runtime, prefs = get_runtime(), get_preferences()
        prefs.allow_execute_python = prefs.allow_save_project = prefs.allow_delete_objects = (
            prefs.allow_external_files
        ) = False
        assert prefs.allow_viewport_capture
        scene = bpy.context.scene
        window, _screen, area, _region = viewport._view3d_context(bpy)
        assert window.scene == scene and window.view_layer == bpy.context.view_layer
        space = area.spaces.active
        evidence = Path(tempfile.gettempdir()) / "viewport-framing-evidence"
        evidence.mkdir(exist_ok=False)
        mesh = bpy.data.meshes.new("Framing Cuboid Mesh")
        mesh.from_pydata(
            [
                (-1, -1, -1),
                (-1, -1, 1),
                (-1, 1, -1),
                (-1, 1, 1),
                (1, -1, -1),
                (1, -1, 1),
                (1, 1, -1),
                (1, 1, 1),
            ],
            [],
            [(2, 6, 4, 0), (5, 7, 3, 1), (4, 5, 1, 0), (3, 7, 6, 2), (1, 3, 2, 0), (6, 7, 5, 4)],
        )
        mesh.update()
        target = bpy.data.objects.new("Off-origin Framing Cuboid", mesh)
        scene.collection.objects.link(target)
        target.location, target.rotation_euler, target.scale = (
            (6.5, -3.25, 1.75),
            (0.37, -0.49, 0.28),
            (1.8, 0.65, 1.15),
        )
        target.color = (1.0, 0.005, 0.005, 1.0)
        peer = bpy.data.objects["Cube"]
        peer.name = "Selected Preserved Peer"
        hidden_peer = peer.copy()
        hidden_peer.name = "Initially Hidden Preserved Peer"
        scene.collection.objects.link(hidden_peer)
        hidden_peer.hide_set(True)
        hidden_peer.hide_render = True
        for obj in scene.objects:
            obj.select_set(False)
        peer.select_set(True)
        bpy.context.view_layer.objects.active = peer
        scene.view_settings.view_transform = "Standard"
        space.shading.light, space.shading.color_type = "FLAT", "OBJECT"
        space.shading.background_type, space.shading.background_color = (
            "VIEWPORT",
            (0.01, 0.02, 0.04),
        )
        space.shading.show_shadows = space.shading.show_cavity = (
            space.shading.show_specular_highlight
        ) = False
        space.shading.type = "WIREFRAME"
        space.overlay.show_overlays = True
        scene.render.filepath = str(evidence / "original-output-never-written")
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = (
            713,
            331,
            37,
        )
        scene.render.use_border = scene.render.use_crop_to_border = True
        scene.render.border_min_x, scene.render.border_max_x = 0.12, 0.84
        scene.render.border_min_y, scene.render.border_max_y = 0.23, 0.91
        scene.render.image_settings.file_format, scene.render.image_settings.color_mode = (
            "TIFF",
            "RGB",
        )
        bpy.context.view_layer.update()
        evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
        world_corners = [
            list(evaluated.matrix_world @ Vector(corner)) for corner in evaluated.bound_box
        ]
        geometry_before = {
            "vertices": [list(vertex.co) for vertex in mesh.vertices],
            "polygons": [list(polygon.vertices) for polygon in mesh.polygons],
            "matrix_world": [list(row) for row in target.matrix_world],
        }
        original_restore, pending, observations = viewport._restore_framed_view, {}, []

        def observe_restore(*args):
            # Declared bounded measurement: only temporary view/lens/output RNA;
            # the eight evaluated world corners were measured before capture.
            try:
                observations.append(
                    measured_projection(
                        scene, space, world_corners, pending["view"], pending["directions"]
                    )
                )
            finally:
                restored = original_restore(*args)
            return restored

        captures = []
        viewport._restore_framed_view = observe_restore
        try:
            for index, (name, view, resolution, perspective) in enumerate(CASES):
                region = space.region_3d
                region.view_perspective = perspective
                region.view_rotation = Euler((0.7 + index * 0.03, -0.4, 1.2), "XYZ").to_quaternion()
                region.view_location, region.view_distance = (-0.25, 0.4, -0.1), 2.75 + index * 0.1
                region.view_camera_offset, region.view_camera_zoom = (0.13, -0.09), 7.25
                space.lens = 35.0 + index * 8.0
                space.clip_start, space.clip_end = 0.12, 1200.0
                expected = (
                    AXIS_DIRECTIONS[view]
                    if view != "current"
                    else (
                        list(region.view_rotation @ Vector((0.0, 0.0, -1.0))),
                        list(region.view_rotation @ Vector((0.0, 1.0, 0.0))),
                        perspective,
                    )
                )
                pending.update(view=view, directions=expected)
                before = context_state(scene, window, space, prefs)
                observed_before = len(observations)
                result = runtime.dispatch(
                    "viewport.capture",
                    {
                        "object_name": target.name,
                        "frame_object": True,
                        "view": view,
                        "shading": "solid",
                        "include_overlays": False,
                        "resolution": list(resolution),
                    },
                )
                after = context_state(scene, window, space, prefs)
                restoration = assert_context_restored(before, after, name)
                assert len(observations) == observed_before + 1, name
                assert result["frame_object"] and result["framing"]["object_name"] == target.name
                assert (
                    result["source"] == "viewport_opengl" and result["resolution_matches_request"]
                )
                assert result["effective_include_overlays"] is False
                image = evidence / f"{name}.png"
                shutil.copyfile(result["path"], image)
                receipt = evidence / f"{name}.json"
                receipt.write_text(
                    json.dumps(
                        {
                            "case": name,
                            "request": {"view": view, "resolution": resolution},
                            "product_capture": result,
                            "projection": observations[-1],
                            "before": before,
                            "after": after,
                            "restoration": restoration,
                            "authoritative_context_restored": True,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                captures.append(
                    {
                        "case": name,
                        "path": str(image),
                        "sha256": sha256(image),
                        "receipt": str(receipt),
                        "receipt_sha256": sha256(receipt),
                    }
                )
        finally:
            viewport._restore_framed_view = original_restore
        assert len(captures) == len(observations) == 8
        denials = []
        managed_capture_directory = Path(result["path"]).parent
        managed_capture_paths = sorted(
            str(path) for path in managed_capture_directory.glob("viewport_*.png")
        )

        def denied(label, view, expected_code):
            before = context_state(scene, window, space, prefs)
            try:
                runtime.dispatch(
                    "viewport.capture",
                    {
                        "object_name": target.name,
                        "frame_object": True,
                        "view": view,
                        "shading": "solid",
                        "resolution": [640, 640],
                    },
                )
            except BridgeError as error:
                assert error.code == expected_code, error.to_dict()
                after = context_state(scene, window, space, prefs)
                restoration = assert_context_restored(before, after, label)
                denials.append(
                    {
                        "case": label,
                        "error": error.to_dict(),
                        "before": before,
                        "after": after,
                        "restoration": restoration,
                        "context_preserved": True,
                    }
                )
            else:
                raise AssertionError(f"{label} was accepted")

        denied("explicit_camera", "camera", "INVALID_ARGUMENT")
        original_perspective = space.region_3d.view_perspective
        try:
            space.region_3d.view_perspective = "CAMERA"
            denied("current_camera", "current", "INVALID_ARGUMENT")
        finally:
            space.region_3d.view_perspective = original_perspective
        try:
            assert bpy.ops.object.mode_set(mode="EDIT") == {"FINISHED"}
            assert bpy.context.mode == "EDIT_MESH"
            denied("unsupported_edit_mode", "current", "BLENDER_CONTEXT_ERROR")
        finally:
            if bpy.context.mode != "OBJECT":
                assert bpy.ops.object.mode_set(mode="OBJECT") == {"FINISHED"}
        geometry_after = {
            "vertices": [list(vertex.co) for vertex in mesh.vertices],
            "polygons": [list(polygon.vertices) for polygon in mesh.polygons],
            "matrix_world": [list(row) for row in target.matrix_world],
        }
        assert geometry_after == geometry_before
        assert (
            sorted(str(path) for path in managed_capture_directory.glob("viewport_*.png"))
            == managed_capture_paths
        )
        assert not any(
            getattr(prefs, name)
            for name in (
                "allow_execute_python",
                "allow_save_project",
                "allow_delete_objects",
                "allow_external_files",
            )
        )
        assert not bpy.data.filepath and not bpy.context.preferences.use_preferences_save
        denial_receipt = evidence / "denials.json"
        denial_receipt.write_text(json.dumps(denials, indent=2) + "\n", encoding="utf-8")
        print(
            "BLENDER_VIEWPORT_FRAMING_OK "
            + json.dumps(
                {
                    "blender": bpy.app.version_string,
                    "capture_count": len(captures),
                    "captures": captures,
                    "denials": str(denial_receipt),
                    "denials_sha256": sha256(denial_receipt),
                    "all_capture_contexts_restored": True,
                    "axis_directions_and_up_verified": True,
                    "corner_projection_bounds_verified": True,
                    "geometry_unchanged": True,
                    "red_mask_pixel_validation": "separate_host_review_required",
                    "pillow_required_in_blender": False,
                    "project_saved": False,
                    "user_preferences_saved": False,
                }
            ),
            flush=True,
        )
    except Exception:
        traceback.print_exc()
    finally:
        if runtime is not None:
            runtime.emergency_stop()
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
