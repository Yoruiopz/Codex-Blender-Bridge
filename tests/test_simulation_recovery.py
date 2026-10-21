"""Cache failures must retain their cause when independent context recovery fails."""

from __future__ import annotations

import importlib
from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def cache_fixture(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.simulation")
    point_cache = NS(frame_start=1, frame_end=10, use_external=False, use_disk_cache=False,
                     is_baked=False)
    modifier = NS(point_cache=point_cache, settings=NS(quality=3))
    obj = NS(name="Cloth", data=NS(vertices=[None] * 4), modifiers=[modifier],
             hide_get=lambda: False, visible_get=lambda: True)
    scene = NS(frame_current=7, frame_subframe=0.25)

    def restore(frame, *, subframe):
        scene.frame_current, scene.frame_subframe = frame, subframe

    scene.frame_set = restore

    class Operator:
        fail = False
        error = RuntimeError("native bake failure")

        @staticmethod
        def poll():
            return True

        def __call__(self, **kwargs):
            scene.frame_current, scene.frame_subframe = 3, 0.0
            if self.fail:
                raise self.error
            point_cache.is_baked = bool(kwargs.get("bake"))
            return {"FINISHED"}

    operator = Operator()
    bpy = NS(context=NS(scene=scene, view_layer=NS(objects={"Cloth": obj}),
                        temp_override=lambda **kwargs: nullcontext()),
             ops=NS(ptcache=NS(bake=operator, free_bake=operator)))
    monkeypatch.setattr(module, "_object", lambda *args: obj)
    monkeypatch.setattr(module, "_modifier", lambda *args: modifier)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_snapshot", lambda *args: {"object": obj.name})
    return NS(module=module, scene=scene, cache=point_cache, operator=operator)


def test_cache_restores_complete_frame_context(cache_fixture):
    case = cache_fixture
    result = case.module.cache(None, {"operation": "BAKE", "frame_start": 2, "frame_end": 4})
    assert result["frame_restored"] and result["frame_recovery"]["verified"]
    assert (case.scene.frame_current, case.scene.frame_subframe) == (7, 0.25)
    assert case.cache.is_baked


def test_primary_bake_failure_survives_failed_frame_restoration(cache_fixture):
    case = cache_fixture
    case.operator.fail = True

    def fail_restore(*args, **kwargs):
        raise ValueError("frame handler failed")

    case.scene.frame_set = fail_restore
    with pytest.raises(Exception) as caught:
        case.module.cache(None, {"operation": "BAKE", "frame_start": 2, "frame_end": 4})
    error = caught.value
    assert error.code == "OPERATION_FAILED"
    assert error.__cause__ is case.operator.error
    assert error.context["primary_error_type"] == "RuntimeError"
    assert error.context["frame_recovery"] == {
        "attempted": True, "verified": False, "error_type": "ValueError"}
    assert error.context["range_recovery"] == {"attempted": True, "verified": True}
    assert (case.cache.frame_start, case.cache.frame_end) == (1, 10)


@pytest.mark.parametrize("raise_error", [True, False])
def test_successful_bake_does_not_hide_failed_or_incomplete_frame_restore(cache_fixture, raise_error):
    case = cache_fixture

    def fail_restore(*args, **kwargs):
        if raise_error:
            raise RuntimeError("frame handler failed")

    case.scene.frame_set = fail_restore
    with pytest.raises(Exception) as caught:
        case.module.cache(None, {"operation": "BAKE"})
    error = caught.value
    assert error.code == "OPERATION_FAILED"
    assert error.context["cache_operation_verified"]
    assert error.context["primary_error_type"] is None
    assert not error.context["frame_recovery"]["verified"]
    assert case.cache.is_baked


def test_primary_error_survives_failed_cache_range_restoration(cache_fixture):
    case = cache_fixture
    case.operator.fail = True

    class Cache:
        frame_start, frame_end = 1, 10
        use_external = use_disk_cache = is_baked = False

        def __setattr__(self, key, value):
            if key == "frame_start" and value == 1:
                raise RuntimeError("cache range restoration failure")
            super().__setattr__(key, value)

    replacement = Cache()
    case.module._modifier(None, None).point_cache = replacement
    with pytest.raises(Exception) as caught:
        case.module.cache(None, {"operation": "BAKE", "frame_start": 2, "frame_end": 4})
    error = caught.value
    assert error.code == "OPERATION_FAILED" and error.__cause__ is case.operator.error
    assert error.context["range_recovery"] == {
        "attempted": True, "verified": False, "error_type": "RuntimeError"}
    assert error.context["frame_recovery"]["verified"]
