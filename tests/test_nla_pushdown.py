from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
from nla_test_support import make_env


@pytest.fixture
def fixture(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.animation_layers")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    env = make_env(mod, monkeypatch, permissions)
    action = env.action()
    env.data.action = action
    env.tracks.fail_strip = True
    return mod, env.data, action, env


def test_pushdown_failure_restores_active_action_and_removes_new_track(fixture):
    mod, data, action, env = fixture
    with pytest.raises(Exception) as caught:
        mod.nla_push_down(env.context, {"track_name": "Motion", "strip_name": "Walk"})
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_performed"]
    assert data.action is action and not data.nla_tracks


@pytest.mark.parametrize(
    "key,value",
    [("action_blend_type", "ADD"), ("action_influence", 0.5), ("action_extrapolation", "NOTHING")],
)
def test_pushdown_rejects_unsupported_blending_before_mutation(fixture, key, value):
    mod, data, action, env = fixture
    setattr(data, key, value)
    with pytest.raises(Exception) as caught:
        mod.nla_push_down(env.context, {"track_name": "Motion", "strip_name": "Walk"})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert data.action is action and not data.nla_tracks


@pytest.mark.parametrize("frames", [(1.0, 1.0), (1.5, 11.0), (0.0, float("inf")), (0.0, 100001.0)])
def test_pushdown_rejects_unsupported_frame_ranges(fixture, frames):
    mod, data, action, env = fixture
    action.frame_range = frames
    with pytest.raises(Exception) as caught:
        mod.nla_push_down(env.context, {"track_name": "Motion", "strip_name": "Walk"})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert data.action is action and not data.nla_tracks


@pytest.mark.parametrize("condition", ["missing", "disabled", "drivers", "name"])
def test_pushdown_preflight_does_not_create_tracks(fixture, condition):
    mod, data, action, env = fixture
    name = "Motion"
    if condition == "missing":
        data.action = None
    elif condition == "disabled":
        data.use_nla = False
    elif condition == "drivers":
        data.drivers = [NS()]
    else:
        name = "界" * 22
    with pytest.raises(Exception) as caught:
        mod.nla_push_down(env.context, {"track_name": name, "strip_name": "Walk"})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert not data.nla_tracks
    assert data.action is (None if condition == "missing" else action)
