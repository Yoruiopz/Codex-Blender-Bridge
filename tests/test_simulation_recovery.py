"""Cache failures must retain their cause when independent context recovery fails."""

from __future__ import annotations

import importlib
from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest


class Item(NS):
    __hash__ = object.__hash__


class NamedList(list):
    def get(self, name):
        return next((value for value in self if value.name == name), None)


@pytest.fixture
def cache_fixture(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.simulation")
    errors = importlib.import_module(f"{addon_package}.errors")
    point_cache = NS(frame_start=1, frame_end=10, use_external=False, use_disk_cache=False,
                     is_baked=False)
    modifier = NS(name="Cloth", type="CLOTH", point_cache=point_cache, settings=NS(quality=3))
    mesh = NS(name="Cloth Mesh", users=1, vertices=[None] * 4)
    obj = Item(name="Cloth", type="MESH", mode="OBJECT", data=mesh,
               modifiers=NamedList([modifier]),
             hide_get=lambda: False, visible_get=lambda: True)
    collection = Item(name="Root", users=0, use_fake_user=False, children=[], objects={obj.name: obj},
                      user_of_id=lambda value: 1)
    layer = Item(objects={obj.name: obj})
    scene = Item(name="Scene", frame_current=7, frame_subframe=0.25,
                 collection=collection, view_layers=[layer], user_of_id=lambda value: 2)
    obj.users_scene, obj.users_collection = (scene,), (collection,)

    def restore(frame, *, subframe):
        scene.frame_current, scene.frame_subframe = frame, subframe

    scene.frame_set = restore

    class Operator:
        fail = False
        calls = 0
        error = RuntimeError("native bake failure")

        @staticmethod
        def poll():
            return True

        def __call__(self, **kwargs):
            self.calls += 1
            scene.frame_current, scene.frame_subframe = 3, 0.0
            if self.fail:
                raise self.error
            point_cache.is_baked = bool(kwargs.get("bake"))
            return {"FINISHED"}

    operator = Operator()
    bpy = NS(data=NS(filepath="", objects={obj.name: obj}, meshes={mesh.name: mesh},
                     user_map=lambda **kwargs: {obj: {scene}}),
             context=NS(mode="OBJECT", scene=scene, view_layer=layer,
                        temp_override=lambda **kwargs: nullcontext()),
             ops=NS(ptcache=NS(bake=operator, free_bake=operator)))
    monkeypatch.setattr(module, "_object", lambda *args: obj)
    monkeypatch.setattr(module, "_modifier", lambda *args: modifier)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_snapshot", lambda *args: {"object": obj.name})
    return NS(module=module, scene=scene, cache=point_cache, operator=operator,
              obj=obj, modifier=modifier, collection=collection, bpy=bpy,
              errors=errors, frame_set=restore)


def test_cache_restores_complete_frame_context(cache_fixture):
    case = cache_fixture
    result = case.module.cache(None, {"operation": "BAKE", "frame_start": 2, "frame_end": 4})
    assert result["frame_restored"] and result["frame_recovery"]["verified"]
    assert (case.scene.frame_current, case.scene.frame_subframe) == (7, 0.25)
    assert case.cache.is_baked
    assert result["verification_required"]
    assert result["cache_coverage"].startswith("NOT_ASSESSED")


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


def test_fractional_caller_time_reaches_operator_unchanged(cache_fixture):
    case = cache_fixture
    observed = []
    case.operator.poll = lambda: observed.append((case.scene.frame_current, case.scene.frame_subframe)) or True
    case.module.cache(None, {"operation": "BAKE"})
    assert observed == [(7, .25)]
    assert (case.scene.frame_current, case.scene.frame_subframe) == (7, .25)


@pytest.mark.parametrize("kind", ["permission", "cancellation"])
def test_live_denial_after_poll_prevents_operator_and_compensation(cache_fixture, kind):
    case = cache_fixture
    stopped = False
    code = "PERMISSION_DENIED" if kind == "permission" else "TIMEOUT"

    def gate(*args):
        if stopped:
            raise case.errors.BridgeError(getattr(case.errors.ErrorCode, code), "late stop")

    context = NS(registry=NS(prepare=gate)) if kind == "permission" else NS(check_cancelled=gate)

    def poll():
        nonlocal stopped
        stopped = True
        return True

    case.operator.poll = poll
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(context, {"operation": "BAKE", "frame_start": 2, "frame_end": 4})
    error = caught.value
    assert error.code == code and case.operator.calls == 0
    assert error.context["execution_started"] and not error.context["cache_operation_started"]
    assert not error.context["range_recovery"]["attempted"]
    assert not error.context["frame_recovery"]["attempted"]
    assert (case.cache.frame_start, case.cache.frame_end) == (2, 4)
    assert (case.scene.frame_current, case.scene.frame_subframe) == (7, .25)


def test_cancel_before_any_write_is_reported_unstarted(cache_fixture):
    case = cache_fixture

    def cancel():
        raise case.errors.BridgeError(case.errors.ErrorCode.TIMEOUT, "cancelled before mutation")

    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(NS(check_cancelled=cancel), {"operation": "BAKE"})
    assert caught.value.context["execution_started"] is False
    assert caught.value.context["possible_mutation"] is False
    assert case.operator.calls == 0


@pytest.mark.parametrize("change", ["mesh", "cache", "collection", "incoming_user", "disk"])
def test_live_scope_changes_after_poll_are_rejected(cache_fixture, change):
    case = cache_fixture

    def poll():
        if change == "mesh":
            case.obj.data = NS(name="New Mesh", users=1, vertices=[None] * 4)
        elif change == "cache":
            case.modifier.point_cache = NS(**vars(case.cache))
        elif change == "collection":
            case.collection.users = 2
        elif change == "incoming_user":
            external = Item(name="External Consumer")
            case.bpy.data.user_map = lambda **kwargs: {case.obj: {case.scene, external}}
        else:
            case.cache.use_disk_cache = True
        return True

    case.operator.poll = poll
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(None, {"operation": "BAKE"})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert not caught.value.context["cache_operation_started"] and case.operator.calls == 0
    assert not caught.value.context["range_recovery"]["attempted"]
    assert not caught.value.context["frame_recovery"]["attempted"]


def test_newer_range_is_retained_on_late_failure(cache_fixture):
    case = cache_fixture

    def poll():
        case.cache.frame_start = 9
        return True

    case.operator.poll = poll
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(None, {"operation": "BAKE", "frame_start": 2, "frame_end": 4})
    assert case.operator.calls == 0
    assert case.cache.frame_start == 9
    assert not caught.value.context["range_recovery"]["attempted"]
    assert not caught.value.context["range_recovery"]["verified"]


def test_recovery_does_not_overwrite_frame_changed_by_final_gate(cache_fixture):
    case = cache_fixture
    changed = False

    def prepare(*args):
        nonlocal changed
        if case.operator.calls and case.scene.frame_current == 3 and not changed:
            # First post-native gate passes; only the recovery boundary changes time.
            changed = True
        elif changed and case.scene.frame_current == 3:
            case.scene.frame_current = 9

    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(NS(registry=NS(prepare=prepare)), {"operation": "BAKE"})
    assert case.scene.frame_current == 9 and case.cache.is_baked
    assert caught.value.context["cache_operation_verified"]
    assert not caught.value.context["frame_recovery"]["attempted"]


def test_frame_handler_replacing_target_is_reported_after_restore(cache_fixture):
    case = cache_fixture

    def restore(frame, *, subframe):
        case.frame_set(frame, subframe=subframe)
        case.obj.data = NS(name="Replacement", users=1, vertices=[None] * 4)

    case.scene.frame_set = restore
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(None, {"operation": "BAKE"})
    assert caught.value.context["frame_recovery"]["attempted"]
    assert not caught.value.context["frame_recovery"]["verified"]
    assert caught.value.context["cache_operation_verified"]
    assert (case.scene.frame_current, case.scene.frame_subframe) == (7, .25)


def test_unstarted_free_failure_does_not_write_range_or_frame(cache_fixture):
    case = cache_fixture
    case.operator.poll = lambda: False
    writes = []
    case.scene.frame_set = lambda *args, **kwargs: writes.append((args, kwargs))
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(None, {"operation": "FREE"})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert caught.value.context["execution_started"] is False
    assert not caught.value.context["range_recovery"]["attempted"]
    assert caught.value.context["frame_recovery"] == {"attempted": False, "verified": True}
    assert not writes and case.operator.calls == 0


def test_new_bake_before_range_write_is_not_modified(cache_fixture):
    case = cache_fixture
    calls = 0

    def prepare(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            case.cache.is_baked = True

    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(NS(registry=NS(prepare=prepare)),
                          {"operation": "BAKE", "frame_start": 2, "frame_end": 4})
    assert case.operator.calls == 0
    assert (case.cache.frame_start, case.cache.frame_end) == (1, 10)
    assert caught.value.context["execution_started"] is False
