from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.interaction import InteractionTools, load_definitions


@pytest.mark.parametrize("handler", ["set_selection", "set_mode", "select_components"])
def test_mutating_interaction_rejects_unknown_parameters(addon_package: str, handler: str) -> None:
    module = importlib.import_module(f"{addon_package}.tools.interaction")
    with pytest.raises(Exception) as caught:
        getattr(module, handler)(None, {"unrecognized": True})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert "Unknown parameters" in caught.value.message


@pytest.mark.parametrize(
    "names",
    [None, "Cube", ["Cube", "Cube"], [""], [False], ["x" * 257], [str(i) for i in range(201)]],
)
def test_object_names_are_bounded_and_typed(addon_package: str, names: Any) -> None:
    module = importlib.import_module(f"{addon_package}.tools.interaction")
    with pytest.raises(Exception) as caught:
        module._names(names)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("indices", [None, "1", [True], [-1], [1.0], [1, 1], list(range(20_001))])
def test_component_indices_are_bounded_and_typed(addon_package: str, indices: Any) -> None:
    module = importlib.import_module(f"{addon_package}.tools.interaction")
    with pytest.raises(Exception) as caught:
        module._indices(indices)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_selection_prevalidation_never_mutates_on_missing_target(
    addon_package: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.interaction")
    errors = importlib.import_module(f"{addon_package}.errors")
    changed: list[bool] = []
    cube = SimpleNamespace(
        name="Cube", select_set=changed.append, hide_select=False, visible_get=lambda: True
    )
    bpy = SimpleNamespace(
        context=SimpleNamespace(
            mode="OBJECT",
            selected_objects=[cube],
            view_layer=SimpleNamespace(objects=SimpleNamespace(active=cube)),
        )
    )
    monkeypatch.setattr(module, "require_blender", lambda: bpy)

    def resolve(_: Any, name: str) -> Any:
        if name == "Cube":
            return cube
        raise errors.BridgeError(errors.ErrorCode.OBJECT_NOT_FOUND, "Missing target")

    monkeypatch.setattr(module, "_in_view_layer", resolve)
    with pytest.raises(Exception, match="Missing target"):
        module.set_selection(object(), {"object_names": ["Cube", "Missing"]})
    assert changed == []


def test_selection_rejects_active_object_outside_result_before_mutation(
    addon_package: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.interaction")
    cube = SimpleNamespace(name="Cube", hide_select=False, visible_get=lambda: True)
    bpy = SimpleNamespace(
        context=SimpleNamespace(
            mode="OBJECT",
            selected_objects=[cube],
            view_layer=SimpleNamespace(objects=SimpleNamespace(active=cube)),
        )
    )
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_in_view_layer", lambda *_: cube)
    with pytest.raises(Exception, match="resulting selection"):
        module.set_selection(object(), {"object_names": ["Cube"], "active_object": "Other"})


def test_mode_requires_live_domain_permission_before_changes(
    addon_package: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.interaction")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    cube = SimpleNamespace(
        name="Cube",
        type="MESH",
        mode="OBJECT",
        hide_select=False,
        visible_get=lambda: True,
        is_editable=True,
        data=SimpleNamespace(is_editable=True),
    )
    bpy = SimpleNamespace(
        context=SimpleNamespace(
            selected_objects=[cube],
            objects_in_mode=[],
            view_layer=SimpleNamespace(objects=SimpleNamespace(active=cube)),
        )
    )
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "_in_view_layer", lambda *_: cube)
    permission_manager = permissions.PermissionManager(lambda: {"TRANSFORM_OBJECTS": True})
    context = SimpleNamespace(require=lambda *required: permission_manager.require(required))
    with pytest.raises(Exception) as caught:
        module.set_mode(context, {"object_name": "Cube", "mode": "EDIT"})
    assert caught.value.code == "PERMISSION_DENIED"
    assert caught.value.context["missing_permissions"] == ["EDIT_MESH"]


def test_interaction_registry_metadata_and_permission_checks(addon_package: str) -> None:
    module = importlib.import_module(f"{addon_package}.tools.interaction")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    state = importlib.import_module(f"{addon_package}.state")
    registry = registry_module.ToolRegistry(enabled_toolsets=("interaction",))
    module.register_tools(registry)
    denied = permissions.PermissionManager(lambda: {})
    context = registry_module.ToolContext(state.BridgeState(), denied, registry, None)
    expected = {
        "selection.set": {"TRANSFORM_OBJECTS"},
        "context.set_mode": {"TRANSFORM_OBJECTS"},
        "mesh.select_components": {"EDIT_MESH"},
        "mesh.components_inspect": {"INSPECT_SCENE"},
    }
    for name, required in expected.items():
        spec = registry.get(name)
        assert spec.modifies == (name != "mesh.components_inspect")
        assert spec.automatic_checkpoint
        assert spec.toolset == "interaction"
        assert {permission.value for permission in spec.permissions} == required
        with pytest.raises(Exception) as caught:
            registry.prepare(name, context)
        assert caught.value.code == "PERMISSION_DENIED"
    assert {definition.name for definition in load_definitions()} == set(expected)


def test_interaction_wrappers_forward_exact_arguments() -> None:
    calls: list[tuple[str, Any]] = []

    class Registry:
        async def call(self, name: str, values: Any) -> Any:
            calls.append((name, values))
            return values

    tools = InteractionTools(Registry())  # type: ignore[arg-type]
    asyncio.run(tools.selection_set(["Cube"], active_object="Cube"))
    asyncio.run(tools.context_set_mode("Cube", "EDIT"))
    asyncio.run(
        tools.mesh_select_components(
            "Cube", "FACE", [2], operation="ADD", selection_id="sel_current"
        )
    )
    asyncio.run(
        tools.mesh_components_inspect("Cube", "EDGE", offset=10, max_items=5, selected_only=True)
    )
    assert calls == [
        (
            "selection.set",
            {"object_names": ["Cube"], "operation": "REPLACE", "active_object": "Cube"},
        ),
        ("context.set_mode", {"object_name": "Cube", "mode": "EDIT"}),
        (
            "mesh.select_components",
            {
                "object_name": "Cube",
                "element_type": "FACE",
                "indices": [2],
                "operation": "ADD",
                "selection_id": "sel_current",
            },
        ),
        (
            "mesh.components_inspect",
            {
                "object_name": "Cube",
                "element_type": "EDGE",
                "offset": 10,
                "max_items": 5,
                "selected_only": True,
            },
        ),
    ]
    assert {binding.name for binding in tools.bindings()} == {name for name, _ in calls}


@pytest.mark.parametrize(
    "change",
    [
        {"max_items": 257},
        {"max_items": 0},
        {"offset": -1},
        {"offset": 200_001},
        {"selected_only": 1},
    ],
)
def test_inspection_prevalidation_rejects_unbounded_requests(
    addon_package: str, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.interaction")
    monkeypatch.setattr(
        module, "require_blender", lambda: (_ for _ in ()).throw(AssertionError("must prevalidate"))
    )
    with pytest.raises(Exception) as caught:
        module.inspect_components(
            object(), {"object_name": "Cube", "element_type": "FACE", **change}
        )
    assert caught.value.code == "INVALID_ARGUMENT"
