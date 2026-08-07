from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest

from mcp_server.tools.rigging import (
    RIGGING_TOOL_NAMES,
    RiggingTools,
    load_rigging_definitions,
)


class RecordingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, values))
        return {"method": name, "params": values}


def test_rigging_addon_registry_metadata(addon_package: str) -> None:
    rigging = importlib.import_module(f"{addon_package}.tools.rigging")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry()

    rigging.register_tools(registry)

    assert registry.list_tools() == tuple(sorted(RIGGING_TOOL_NAMES))
    assert registry.get("rig.inspect").permissions == frozenset(
        {permissions.Permission.INSPECT_SCENE}
    )
    assert registry.get("rig.create").permissions == frozenset(
        {
            permissions.Permission.EDIT_ANIMATION,
            permissions.Permission.TRANSFORM_OBJECTS,
        }
    )
    assert registry.get("rig.bone_remove").permissions == frozenset(
        {
            permissions.Permission.DELETE_OBJECTS,
            permissions.Permission.EDIT_ANIMATION,
        }
    )
    for name in RIGGING_TOOL_NAMES[1:]:
        spec = registry.get(name)
        assert spec.toolset == "rigging"
        assert spec.modifies is True


def test_rigging_mcp_definitions_match_addon_contract() -> None:
    definitions = load_rigging_definitions()

    assert tuple(item.name for item in definitions) == RIGGING_TOOL_NAMES
    assert all(item.toolset == "rigging" for item in definitions)
    assert definitions[0].required_permissions == ("INSPECT_SCENE",)
    remove = next(item for item in definitions if item.name == "rig.bone_remove")
    assert set(remove.required_permissions) == {"DELETE_OBJECTS", "EDIT_ANIMATION"}
    assert all(item.modifying for item in definitions[1:])


def test_rigging_wrapper_omits_unsupplied_optional_updates() -> None:
    registry = RecordingRegistry()
    tools = RiggingTools(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        tools.rig_bone_update(
            "CharacterRig",
            "Forearm.L",
            parent_name="UpperArm.L",
            use_connect=True,
        )
    )

    assert result["method"] == "rig.bone_update"
    assert registry.calls == [
        (
            "rig.bone_update",
            {
                "object_name": "CharacterRig",
                "bone_name": "Forearm.L",
                "parent_name": "UpperArm.L",
                "clear_parent": False,
                "use_connect": True,
            },
        )
    ]


def test_rigging_wrapper_requires_named_mesh_and_armature() -> None:
    registry = RecordingRegistry()
    tools = RiggingTools(registry)  # type: ignore[arg-type]

    asyncio.run(tools.rig_bind_mesh("Body", "CharacterRig", method="EMPTY_GROUPS"))

    assert registry.calls == [
        (
            "rig.bind_mesh",
            {
                "mesh_object": "Body",
                "armature_object": "CharacterRig",
                "method": "EMPTY_GROUPS",
                "parent": True,
            },
        )
    ]


def test_rigging_numeric_validators_reject_non_finite_and_unbounded(
    addon_package: str,
) -> None:
    rigging = importlib.import_module(f"{addon_package}.tools.rigging")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError):
        rigging._bounded_vector3((0.0, float("inf"), 0.0), "head")
    with pytest.raises(errors.BridgeError):
        rigging._bounded_sequence((1.0, 0.0, 0.0, 1_000_001.0), "quaternion", 4)
    with pytest.raises(errors.BridgeError):
        rigging._required_name({"bone_name": "Bone\nInjected"}, "bone_name")
