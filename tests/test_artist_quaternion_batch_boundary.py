"""Quaternion batch refusal is structural and precedes every child callback.

No native state or provider mutation is reproduced here. Actual batch entry
permissions retain their usual authority; no child is admitted for this field.
"""
from __future__ import annotations

import importlib
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def quaternion_batch(addon_package, monkeypatch):
    batch = importlib.import_module(f"{addon_package}.tools.batch")
    transforms = importlib.import_module(f"{addon_package}.tools.transforms")
    admission = importlib.import_module(f"{addon_package}.tools._artist_checkpoint_admission")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state")
    registry = registry_module.ToolRegistry(enabled_toolsets=("batch", "objects"))
    transforms.register_tools(registry)
    batch.register_tools(registry)
    calls = []
    def forbidden(label):
        def fail(*_args, **_kwargs):
            calls.append(label)
            raise AssertionError("Quaternion batch entered a child effect: " + label)
        return fail
    monkeypatch.setattr(admission, "require_blender", forbidden("native capture"))
    monkeypatch.setattr(transforms, "require_blender", forbidden("handler native access"))
    # Child transform.set declares TRANSFORM_OBJECTS. Outer batch declares no
    # grant, so this detects a child provider without replacing native guards.
    manager = permissions.PermissionManager(forbidden("child grant provider"))
    context = registry_module.ToolContext(state.BridgeState(), manager, registry,
        NS(before_modification=forbidden("checkpoint before"), after_modification=forbidden("checkpoint after")))
    registry.register("object.read_marker", forbidden("preceding child handler"), toolset="objects")
    return NS(batch=batch, registry=registry, context=context, calls=calls, error=transforms.BridgeError)


@pytest.mark.parametrize("method", ["batch.plan", "batch.execute"])
@pytest.mark.parametrize("value", [[1., -0., 0., 0.], None, [], "not a quaternion"])
@pytest.mark.parametrize("preceding_child", [False, True])
def test_registered_batch_rejects_new_field_presence_before_any_child_effect(quaternion_batch, method, value, preceding_child):
    case = quaternion_batch
    steps = [{"method": "object.read_marker"}] if preceding_child else []
    steps.append({"method": "transform.set", "params": {"object_name": "Working", "rotation_quaternion": value}})
    params = {"steps": steps}
    before = deepcopy(params)
    with pytest.raises(case.error) as caught:
        case.registry.dispatch(method, params, case.context)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context["execution_started"] is False
    assert caught.value.context["checkpoint_batch_composition_reviewed"] is False
    assert caught.value.context["step_index"] == int(preceding_child)
    assert caught.value.context["parameter"] == "rotation_quaternion"
    assert case.calls == [] and case.context.checkpoint_admission is None
    assert case.context.state.history() == [] and params == before


@pytest.mark.parametrize("method", ["batch.plan", "batch.execute"])
def test_disabled_outer_batch_keeps_normal_entry_precedence(quaternion_batch, method):
    case = quaternion_batch
    case.registry.disable_toolset("batch")
    params = {"steps": [{"method": "transform.set", "params": {"rotation_quaternion": [1., 0., 0., 0.]}}]}
    with pytest.raises(case.error) as caught:
        case.registry.dispatch(method, params, case.context)
    assert caught.value.code == "TOOLSET_DISABLED" and case.calls == []


@pytest.mark.parametrize("field,value", [("location", [1., 2., 3.]), ("rotation", [.1, .2, .3]), ("scale", [2., 2., 2.])])
def test_existing_transform_requests_remain_structurally_batch_supported(quaternion_batch, field, value):
    case = quaternion_batch
    params = {"steps": [{"method": "transform.set", "params": {"object_name": "Working", field: value}}]}
    prepared = case.batch._shape(case.context, params)
    assert len(prepared) == 1 and prepared[0][1] is case.registry.get("transform.set")
    assert prepared[0][2] is params["steps"][0]["params"]
    assert case.calls == []
