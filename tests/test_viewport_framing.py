from __future__ import annotations

import contextlib
import importlib
import itertools
import math
import struct
import sys
from types import SimpleNamespace as NS

import pytest


class Vector(list):
    def __add__(self, other):
        return Vector(a + b for a, b in zip(self, other, strict=True))

    def __sub__(self, other):
        return Vector(a - b for a, b in zip(self, other, strict=True))

    def __mul__(self, factor):
        return Vector(a * factor for a in self)

    def copy(self):
        return Vector(self)


class Quaternion(list):
    def copy(self):
        return Quaternion(self)

    def inverted(self):
        w, x, y, z = self
        return Quaternion((w, -x, -y, -z))

    def __matmul__(self, vector):
        w, x, y, z = self
        a, b, c = vector
        return Vector(
            (
                (1 - 2 * y * y - 2 * z * z) * a
                + (2 * x * y - 2 * z * w) * b
                + (2 * x * z + 2 * y * w) * c,
                (2 * x * y + 2 * z * w) * a
                + (1 - 2 * x * x - 2 * z * z) * b
                + (2 * y * z - 2 * x * w) * c,
                (2 * x * z - 2 * y * w) * a
                + (2 * y * z + 2 * x * w) * b
                + (1 - 2 * x * x - 2 * y * y) * c,
            )
        )


class Matrix:
    def __matmul__(self, vector):
        x, y, z = vector
        # Rotated, nonuniformly scaled, off-origin evaluated object.
        return Vector((3.5 - 2 * y, -1 + x, 2 + 0.5 * z))


class Object:
    def __init__(self, name, *, selected=True):
        self.name, self.type = name, "MESH"
        self.hidden, self.hide_render, self.selected = False, False, selected
        self.bound_box = tuple(itertools.product((-1.0, 1.0), repeat=3))
        self.matrix_world = Matrix()
        self.visible = True

    def hide_get(self):
        return self.hidden

    def hide_set(self, value):
        self.hidden = value
        if value:
            self.selected = False

    def select_get(self):
        return self.selected

    def select_set(self, value):
        self.selected = value

    def visible_get(self, **_kwargs):
        return self.visible

    def evaluated_get(self, _depsgraph):
        return self


class Objects(list):
    def __contains__(self, value):
        return (
            any(obj.name == value for obj in self)
            if isinstance(value, str)
            else super().__contains__(value)
        )


@pytest.fixture
def env(addon_package, monkeypatch, tmp_path):
    module = importlib.import_module(f"{addon_package}.viewport")
    monkeypatch.setitem(sys.modules, "mathutils", NS(Vector=Vector, Quaternion=Quaternion))
    target, peer = Object("SurfacePlane", selected=False), Object("ProtectedPeer")
    objects = Objects([target, peer])
    objects.active = peer
    image = NS(file_format="JPEG", color_mode="RGB")
    render = NS(
        filepath="original",
        resolution_x=123,
        resolution_y=456,
        resolution_percentage=50,
        use_border=True,
        use_crop_to_border=True,
        border_min_x=0.1,
        border_max_x=0.9,
        border_min_y=0.2,
        border_max_y=0.8,
        image_settings=image,
        engine="BLENDER_EEVEE_NEXT",
    )
    scene = NS(name="Scene", objects=objects, render=render)
    layer = NS(name="ViewLayer", objects=objects)
    rv3d = NS(
        view_distance=8.0,
        view_location=Vector((0.0, 0.0, 0.0)),
        view_rotation=Quaternion((1.0, 0.0, 0.0, 0.0)),
        view_perspective="PERSP",
        view_camera_offset=(0.2, -0.1),
        view_camera_zoom=12.0,
        lock_rotation=False,
        use_clip_planes=False,
    )
    space = NS(
        region_3d=rv3d,
        lens=50.0,
        clip_start=0.1,
        clip_end=1000.0,
        shading=NS(type="MATERIAL"),
        overlay=NS(show_overlays=True),
        local_view=None,
        region_quadviews=[],
        lock_object=None,
        lock_cursor=False,
    )
    area = NS(type="VIEW_3D", spaces=NS(active=space), regions=[NS(type="WINDOW")])
    screen = NS(areas=[area])
    window = NS(screen=screen, scene=scene, view_layer=layer)
    context = NS(
        scene=scene,
        view_layer=layer,
        mode="OBJECT",
        window_manager=NS(windows=[window]),
        evaluated_depsgraph_get=lambda: object(),
        temp_override=lambda **_kwargs: contextlib.nullcontext(),
    )
    observations = []

    def render_opengl(**_kwargs):
        observations.append((tuple(rv3d.view_location), rv3d.view_distance, rv3d.view_perspective))
        assert peer.hidden and not peer.selected and objects.active is peer
        assert context.mode == "OBJECT"
        space.lens = 70.0  # Exercise explicit restoration even if the render fails.
        if bpy.fail_render:
            raise RuntimeError("injected render failure")
        from pathlib import Path

        Path(render.filepath).write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + struct.pack(">II", render.resolution_x, render.resolution_y)
        )
        return {"FINISHED"}

    bpy = NS(
        context=context,
        app=NS(background=False),
        fail_render=False,
        ops=NS(render=NS(opengl=render_opengl), view3d=NS()),
    )
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(
        module, "get_object", lambda name: next(obj for obj in objects if obj.name == name)
    )
    monkeypatch.setattr(module, "_managed_capture_path", lambda: tmp_path / "viewport_test.png")
    return NS(
        module=module,
        bpy=bpy,
        target=target,
        peer=peer,
        objects=objects,
        space=space,
        rv3d=rv3d,
        scene=scene,
        observations=observations,
    )


def snapshot(env):
    return (
        dict(vars(env.scene.render), image_settings=dict(vars(env.scene.render.image_settings))),
        dict(vars(env.rv3d)),
        env.space.lens,
        env.space.shading.type,
        env.space.overlay.show_overlays,
        [(obj.hidden, obj.hide_render, obj.selected) for obj in env.objects],
        env.objects.active,
        env.bpy.context.mode,
    )


@pytest.mark.parametrize("perspective", ["PERSP", "ORTHO"])
@pytest.mark.parametrize("resolution", [(768, 768), (1024, 256), (256, 1024)])
def test_fit_with_independent_native_viewplane_projection(addon_package, perspective, resolution):
    module = importlib.import_module(f"{addon_package}.viewport")
    corners = tuple(itertools.product((-3.0, 3.0), (-2.0, 2.0), (-1.0, 1.0)))
    width, height = resolution
    near, far, lens = 0.2, 500.0, 67.0
    distance = module._framing_distance(
        corners,
        perspective=perspective,
        lens=lens,
        clip_start=near,
        clip_end=far,
        width=width,
        height=height,
    )
    # Independently construct Blender's symmetric viewplane then a standard 4x4
    # frustum/orthographic matrix. Validate homogeneous clip coordinates, without
    # reusing the fitting helper's slopes, distance candidates, or margin math.
    scale = distance * 36.0 / lens if perspective == "ORTHO" else 36.0 * near / lens
    pixel_size = scale / max(width, height) * 2.0
    right, top = width * 0.5 * pixel_size, height * 0.5 * pixel_size
    if perspective == "PERSP":
        projection = (
            (near / right, 0, 0, 0),
            (0, near / top, 0, 0),
            (0, 0, -(far + near) / (far - near), -2 * far * near / (far - near)),
            (0, 0, -1, 0),
        )
    else:
        projection = ((1 / right, 0, 0, 0), (0, 1 / top, 0, 0), (0, 0, -2 / far, 0), (0, 0, 0, 1))
    ndcs = []
    for x, y, z in corners:
        point = (x, y, z - distance if perspective == "PERSP" else z, 1)
        clip = [sum(a * b for a, b in zip(row, point, strict=True)) for row in projection]
        ndc = [value / clip[3] for value in clip[:3]]
        assert abs(ndc[0]) <= 0.90000001 and abs(ndc[1]) <= 0.90000001
        assert -1 < ndc[2] < 1
        ndcs.append(ndc)
    assert max(abs(value) for ndc in ndcs for value in ndc[:2]) == pytest.approx(0.9)


@pytest.mark.parametrize("perspective", ["PERSP", "ORTHO"])
def test_unfittable_clipping_is_explicit(addon_package, perspective):
    module = importlib.import_module(f"{addon_package}.viewport")
    corners = tuple(itertools.product((-100.0, 100.0), repeat=3))
    with pytest.raises(module.BridgeError, match="clipping range"):
        module._framing_distance(
            corners,
            perspective=perspective,
            lens=100.0,
            clip_start=0.1,
            clip_end=10.0,
            width=768,
            height=768,
        )


@pytest.mark.parametrize("view", ["current", "front", "back", "left", "right", "top", "bottom"])
@pytest.mark.parametrize("fail_render", [False, True])
def test_capture_frames_evaluated_bounds_and_restores_all_context(env, view, fail_render):
    before = snapshot(env)
    env.bpy.fail_render = fail_render
    params = {
        "object_name": "SurfacePlane",
        "frame_object": True,
        "view": view,
        "include_overlays": False,
        "resolution": [256, 1024],
    }
    if fail_render:
        with pytest.raises(env.module.BridgeError, match="failed to capture"):
            env.module.capture_viewport(params)
    else:
        result = env.module.capture_viewport(params)
        assert result["framing"] == {
            "object_name": "SurfacePlane",
            "projection": "persp" if view == "current" else "ortho",
            "bounds_source": "evaluated_object_bounding_box",
            "frame_fraction": 0.9,
        }
        assert result["frame_object"] and result["width"] == 256 and result["height"] == 1024
    assert env.observations[0][0] == (3.5, -1.0, 2.0)
    assert snapshot(env) == before


@pytest.mark.parametrize(
    "case",
    [
        "headless",
        "camera",
        "current_camera",
        "edit",
        "wrong_scene",
        "wrong_layer",
        "local",
        "quad",
        "lock_object",
        "lock_cursor",
        "lock_rotation",
        "clip_planes",
        "invisible",
        "empty",
        "invalid_bounds",
        "nonfinite",
        "zero_bounds",
        "clipping",
    ],
)
def test_unsupported_framing_refuses_before_temporary_writes(env, monkeypatch, case):
    view = "current"
    if case == "headless":
        env.bpy.app.background = True
    elif case == "camera":
        view = "camera"
    elif case == "current_camera":
        env.rv3d.view_perspective = "CAMERA"
    elif case == "edit":
        env.bpy.context.mode = "EDIT_MESH"
    elif case == "wrong_scene":
        env.bpy.context.window_manager.windows[0].scene = object()
    elif case == "wrong_layer":
        env.bpy.context.window_manager.windows[0].view_layer = object()
    elif case == "local":
        env.space.local_view = object()
    elif case == "quad":
        env.space.region_quadviews = [env.rv3d]
    elif case == "lock_object":
        env.space.lock_object = env.peer
    elif case == "lock_cursor":
        env.space.lock_cursor = True
    elif case == "lock_rotation":
        env.rv3d.lock_rotation = True
    elif case == "clip_planes":
        env.rv3d.use_clip_planes = True
    elif case == "invisible":
        env.target.visible = False
    elif case == "empty":
        env.target.type = "EMPTY"
    elif case == "invalid_bounds":
        env.target.bound_box = [(-1.0, -1.0, -1.0)] * 8
    elif case == "nonfinite":
        env.target.bound_box = [(math.nan, 0.0, 0.0)] * 8
    elif case == "zero_bounds":
        env.target.bound_box = [(0.0, 0.0, 0.0)] * 8
    elif case == "clipping":
        env.space.clip_end = 0.2
    before = snapshot(env)

    def unexpected_write(*_args, **_kwargs):
        raise AssertionError("temporary write before validated framing")

    monkeypatch.setattr(env.module, "_managed_capture_path", unexpected_write)
    monkeypatch.setattr(env.module, "_isolate_object", unexpected_write)
    with pytest.raises(env.module.BridgeError):
        env.module.capture_viewport(
            {"object_name": "SurfacePlane", "frame_object": True, "view": view}
        )
    assert not env.observations and snapshot(env) == before


@pytest.mark.parametrize("name", [None, "", "   "])
def test_framing_requires_nonempty_explicit_object(env, name):
    with pytest.raises(env.module.BridgeError, match="exact 'object_name'"):
        env.module.capture_viewport({"frame_object": True, "object_name": name})
    assert not env.observations


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_blender_framing_boolean_is_strict(env, value):
    with pytest.raises(env.module.BridgeError, match="must be a boolean"):
        env.module.capture_viewport({"frame_object": value})


def test_restore_framed_view_attempts_other_settings_after_one_failure(env, monkeypatch):
    state = dict(vars(env.rv3d), lens=env.space.lens)
    monkeypatch.setattr(
        env.module,
        "_restore_render_settings",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("restore failed")),
    )
    env.rv3d.view_distance = 99.0
    env.space.lens = 99.0
    assert not env.module._restore_framed_view(
        env.scene, env.space, env.rv3d, {}, state, "SOLID", False
    )
    assert env.rv3d.view_distance == 8.0 and env.space.lens == 50.0
    assert env.space.shading.type == "SOLID" and not env.space.overlay.show_overlays


def test_partial_isolation_failure_restores_framing_context(env, monkeypatch):
    failing_peer = Object("FailingPeer")
    env.objects.append(failing_peer)
    before = snapshot(env)

    def fail_on_hide(value):
        if value:
            raise RuntimeError("injected isolation failure")
        failing_peer.hidden = value

    monkeypatch.setattr(failing_peer, "hide_set", fail_on_hide)
    with pytest.raises(env.module.BridgeError, match="failed to capture"):
        env.module.capture_viewport({"object_name": "SurfacePlane", "frame_object": True})
    assert snapshot(env) == before and not env.observations


def test_render_configuration_failure_restores_framing_context(env, monkeypatch):
    before = snapshot(env)

    def fail_after_partial_configuration(scene, *_args):
        scene.render.filepath = "temporary"
        scene.render.resolution_x = 700
        raise RuntimeError("injected output configuration failure")

    monkeypatch.setattr(env.module, "_configure_output", fail_after_partial_configuration)
    with pytest.raises(env.module.BridgeError, match="failed to capture"):
        env.module.capture_viewport({"object_name": "SurfacePlane", "frame_object": True})
    assert snapshot(env) == before and not env.observations


def test_restore_failure_is_structured_and_still_restores_isolation(env, monkeypatch):
    before_objects = [(obj.hidden, obj.hide_render, obj.selected) for obj in env.objects]
    original_restore = env.module._restore_framed_view

    def incomplete_restore(*args):
        original_restore(*args)
        return False

    monkeypatch.setattr(env.module, "_restore_framed_view", incomplete_restore)
    with pytest.raises(env.module.BridgeError, match="fully restore temporary context") as failure:
        env.module.capture_viewport({"object_name": "SurfacePlane", "frame_object": True})
    assert failure.value.context == {"verification_required": True, "context_restored": False}
    assert [(obj.hidden, obj.hide_render, obj.selected) for obj in env.objects] == before_objects
    assert env.objects.active is env.peer and env.bpy.context.mode == "OBJECT"


def test_partial_isolation_rollback_failure_reports_reinspection(env, monkeypatch):
    # A peer is hidden successfully, then both a later hide and the peer's
    # rollback fail. The outer capture cannot receive the partial snapshot.
    failing_peer = Object("FailingPeer")
    env.objects.append(failing_peer)

    def fail_restore(value):
        if not value:
            raise RuntimeError("injected visibility rollback failure")
        env.peer.hidden = True
        env.peer.selected = False

    def fail_hide(value):
        if value:
            raise RuntimeError("injected isolation failure")

    monkeypatch.setattr(env.peer, "hide_set", fail_restore)
    monkeypatch.setattr(failing_peer, "hide_set", fail_hide)
    with pytest.raises(
        env.module.BridgeError, match="fully restore temporary isolation"
    ) as failure:
        env.module.capture_viewport({"object_name": "SurfacePlane", "frame_object": True})
    assert failure.value.context == {"verification_required": True, "context_restored": False}
    assert env.objects.active is env.peer and env.bpy.context.mode == "OBJECT"
    assert not env.observations


@pytest.mark.parametrize("flag", [None, False])
def test_legacy_capture_does_not_apply_framing_checks_or_move_view(env, monkeypatch, flag):
    env.bpy.context.mode = "EDIT_MESH"
    env.target.type = "EMPTY"
    before = snapshot(env)

    def unexpected_framing(*_args, **_kwargs):
        raise AssertionError("disabled framing must retain legacy context behavior")

    def legacy_capture(**_kwargs):
        from pathlib import Path

        assert tuple(env.rv3d.view_location) == (0.0, 0.0, 0.0)
        render = env.scene.render
        Path(render.filepath).write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + struct.pack(">II", render.resolution_x, render.resolution_y)
        )
        return {"FINISHED"}

    monkeypatch.setattr(env.module, "_prepare_object_framing", unexpected_framing)
    monkeypatch.setattr(env.bpy.ops.render, "opengl", legacy_capture)
    params = {"object_name": "SurfacePlane"}
    if flag is not None:
        params["frame_object"] = flag
    result = env.module.capture_viewport(params)
    assert not result["frame_object"] and result["framing"] is None
    assert snapshot(env) == before
