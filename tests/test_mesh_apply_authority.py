"""Mesh application requires geometry authority through its last native poll."""
from __future__ import annotations

import importlib
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest
import test_object_rna_mutation as object_tests

from mcp_server.tools.catalog import load_object_definitions
from mcp_server.tools.modifiers import load_definitions as load_modifier_definitions


@pytest.fixture(params=("modifier.apply", "transform.apply"))
def apply_case(request, addon_package, monkeypatch):
    case = object_tests.env.__wrapped__(addon_package, monkeypatch)
    object_tests._mesh(case)
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    domain = "modifiers" if request.param == "modifier.apply" else "transforms"
    module = importlib.import_module(f"{addon_package}.tools.{domain}")
    registry = registry_module.ToolRegistry(enabled_toolsets=("objects", "modifiers"))
    module.register_tools(registry)
    case.context.registry = registry
    case.method, case.domain, case.handler = request.param, module, registry.get(request.param).handler
    case.params = {"object_name": case.obj.name}
    case.grants["EDIT_MESH"] = True
    case.obj.scale = (2., 3., 4.)
    case.obj.dimensions = (2., 3., 4.)
    case.obj.matrix_world = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))
    case.owned = case.obj.modifiers.new(name="Owned Triangulate", type="TRIANGULATE")
    if request.param == "modifier.apply":
        case.params["modifier_name"] = case.owned.name
        monkeypatch.setattr(module, "_object", lambda _: case.obj)
        monkeypatch.setattr(module, "clear_selection_references", lambda _: None)
    else:
        monkeypatch.setattr(module, "get_object", lambda *_args, **_kwargs: case.obj)
    monkeypatch.setattr(module, "require_blender", lambda: case.bpy)
    case.calls, case.polls, case.override_depth = [], [], [0]
    case.on_poll = [None]
    case.poll_result = True
    # A context override must not become the persistent selection CAS baseline.
    case.bpy.context.selected_objects = []

    @contextmanager
    def override(**values):
        original = case.bpy.context.selected_objects
        case.bpy.context.selected_objects = values["selected_objects"]
        case.override_depth[0] += 1
        try:
            yield
        finally:
            case.override_depth[0] -= 1
            case.bpy.context.selected_objects = original

    class Operator:
        def poll(self):
            assert case.override_depth[0] == 1
            case.polls.append(True)
            if case.on_poll[0] is not None:
                case.on_poll[0]()
            return case.poll_result

        def __call__(self, **params):
            assert case.override_depth[0] == 1
            case.calls.append(params)
            if case.method == "modifier.apply":
                case.obj.modifiers.remove(case.owned)
            else:
                case.obj.scale = (1., 1., 1.)
            return {"FINISHED"}

    case.bpy.context.temp_override = override
    operator_name = "modifier_apply" if case.method == "modifier.apply" else "transform_apply"
    case.bpy.ops = NS(object=NS(**{operator_name: Operator()}))
    return case


def test_application_metadata_requires_geometry_permission_in_both_registries(addon_package):
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry()
    for domain in ("modifiers", "transforms"):
        importlib.import_module(f"{addon_package}.tools.{domain}").register_tools(registry)
    definitions = {item.name: item for item in (*load_object_definitions(), *load_modifier_definitions())}
    for method in ("modifier.apply", "transform.apply"):
        assert set(registry.get(method).permissions) == {"TRANSFORM_OBJECTS", "EDIT_MESH"}
        assert set(definitions[method].required_permissions) == {"TRANSFORM_OBJECTS", "EDIT_MESH"}
        assert registry.get(method).modifies and registry.get(method).automatic_checkpoint
    for method in ("modifier.add", "modifier.set", "modifier.remove", "transform.set", "transform.scale"):
        assert set(registry.get(method).permissions) == {"TRANSFORM_OBJECTS"}
        assert set(definitions[method].required_permissions) == {"TRANSFORM_OBJECTS"}


@pytest.mark.parametrize("registered", (False, True))
@pytest.mark.parametrize("permission", ("TRANSFORM_OBJECTS", "EDIT_MESH"))
def test_missing_application_permission_never_reaches_poll_or_operator(apply_case, registered, permission):
    case = apply_case
    if not registered:
        case.context.registry = None
    case.grants[permission] = False
    before = case.module._object_state(case.obj)
    with pytest.raises(case.module.BridgeError) as caught:
        case.handler(case.context, case.params)
    assert caught.value.code == "PERMISSION_DENIED"
    assert not case.calls and not case.polls
    assert case.module._object_state(case.obj) == before
    assert case.bpy.context.selected_objects == []


@pytest.mark.parametrize("registered", (False, True))
def test_geometry_permission_revoked_in_native_poll_prevents_application(apply_case, registered):
    case = apply_case
    if not registered:
        case.context.registry = None
    before = case.module._object_state(case.obj)
    case.on_poll[0] = lambda: case.grants.update(EDIT_MESH=False)
    with pytest.raises(case.module.BridgeError) as caught:
        case.handler(case.context, case.params)
    assert caught.value.code == "PERMISSION_DENIED"
    assert case.polls and not case.calls
    assert case.module._object_state(case.obj) == before
    assert case.bpy.context.selected_objects == [] and case.override_depth == [0]


@pytest.mark.parametrize("registered", (False, True))
@pytest.mark.parametrize("change", ("mesh", "selection", "scene"))
def test_provider_edit_after_poll_is_preserved_and_refuses_application(apply_case, registered, change):
    case = apply_case
    if not registered:
        case.context.registry = None
    armed, fired = [], []
    case.on_poll[0] = lambda: armed.append(True)

    def manual():
        if armed and not fired:
            fired.append(True)
            if change == "mesh":
                case.obj.data.name = "Manual Mesh After Poll"
            elif change == "selection":
                case.bpy.context.selected_objects = [case.obj]
            else:
                case.bpy.context.scene = object_tests.RNA(name="Manual Scene", frame_current=1, frame_subframe=0.)

    case.provider[0] = manual
    with pytest.raises(case.module.BridgeError) as caught:
        case.handler(case.context, case.params)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert fired and case.polls and not case.calls
    assert case.obj.data.name == ("Manual Mesh After Poll" if change == "mesh" else "Mesh")
    assert case.obj.modifiers.get(case.owned.name) is case.owned
    assert case.obj.scale == (2., 3., 4.)
    assert case.bpy.context.selected_objects == ([case.obj] if change == "selection" else [])
    if change == "scene":
        assert case.bpy.context.scene.name == "Manual Scene"
    assert case.override_depth == [0]


@pytest.mark.parametrize("registered", (False, True))
def test_failed_native_poll_leaves_geometry_and_context_unchanged(apply_case, registered):
    case = apply_case
    if not registered:
        case.context.registry = None
    case.poll_result = False
    before = case.module._object_state(case.obj)
    with pytest.raises(case.module.BridgeError) as caught:
        case.handler(case.context, case.params)
    assert caught.value.code == "BLENDER_CONTEXT_ERROR"
    assert len(case.polls) == 1 and not case.calls
    assert case.module._object_state(case.obj) == before
    assert case.bpy.context.selected_objects == [] and case.override_depth == [0]


def test_direct_application_requires_one_coherent_grant_set(apply_case):
    case = apply_case
    case.context.registry = None
    manager_module = importlib.import_module(f"{case.module.__package__.split('.tools')[0]}.permissions")
    snapshots = []

    def alternating_grants():
        snapshots.append(True)
        return {"TRANSFORM_OBJECTS": len(snapshots) % 2 == 1, "EDIT_MESH": len(snapshots) % 2 == 0}

    case.context.permissions = manager_module.PermissionManager(alternating_grants)
    before = case.module._object_state(case.obj)
    with pytest.raises(case.module.BridgeError) as caught:
        case.handler(case.context, case.params)
    assert caught.value.code == "PERMISSION_DENIED"
    assert len(snapshots) == 1 and not case.polls and not case.calls
    assert case.module._object_state(case.obj) == before


@pytest.mark.parametrize("registered", (False, True))
def test_authorized_native_application_preserves_persistent_selection(apply_case, registered):
    case = apply_case
    if not registered:
        case.context.registry = None
    mesh = case.obj.data
    result = case.handler(case.context, case.params)
    assert result["verified"] and not result["mesh_rollback_available"]
    assert len(case.calls) == 1 and len(case.polls) == 1
    assert case.obj.data is mesh and mesh.name == "Mesh"
    assert case.bpy.context.selected_objects == [] and case.override_depth == [0]
