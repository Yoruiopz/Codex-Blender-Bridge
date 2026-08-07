from __future__ import annotations

import asyncio
import importlib
import math
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.materials import (
    MATERIAL_TOOL_NAMES,
    MaterialTools,
)
from mcp_server.tools.materials import (
    load_definitions as load_material_definitions,
)
from mcp_server.tools.nodes import (
    NODE_TOOL_NAMES,
    NodeTools,
)
from mcp_server.tools.nodes import (
    load_definitions as load_node_definitions,
)


class RecordingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, method: str, values: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, values))
        return {"method": method, "params": values}


class FakeSocket:
    def __init__(
        self,
        name: str,
        default_value: Any,
        *,
        identifier: str | None = None,
        linked: bool = False,
    ) -> None:
        self.name = name
        self.identifier = identifier or name
        self.default_value = default_value
        self.type = "VALUE"
        self.bl_idname = "NodeSocketFloat"
        self.enabled = True
        self.is_linked = linked
        self.is_multi_input = False


class SocketList(list[FakeSocket]):
    def get(self, name: str) -> FakeSocket | None:
        return next((socket for socket in self if socket.name == name), None)


class NodeList(list[Any]):
    def get(self, name: str) -> Any | None:
        return next((node for node in self if node.name == name), None)


class MaterialCollection(list[Any]):
    def get(self, name: str) -> Any | None:
        return next((material for material in self if material.name == name), None)

    def keys(self) -> list[str]:
        return [material.name for material in self]


def make_node(name: str, inputs: list[FakeSocket] | None = None) -> Any:
    return SimpleNamespace(
        name=name,
        label="",
        type="BSDF_PRINCIPLED",
        bl_idname="ShaderNodeBsdfPrincipled",
        location=(0.0, 0.0),
        dimensions=(140.0, 100.0),
        mute=False,
        hide=False,
        inputs=SocketList(inputs or []),
        outputs=SocketList([FakeSocket("BSDF", 0.0)]),
    )


def test_addon_registry_declares_permissions_and_modification_metadata(
    addon_package: str,
) -> None:
    materials = importlib.import_module(f"{addon_package}.tools.materials")
    nodes = importlib.import_module(f"{addon_package}.tools.nodes")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    registry = registry_module.ToolRegistry(enabled_toolsets=("materials", "nodes"))

    materials.register_tools(registry)
    nodes.register_tools(registry)

    assert set(MATERIAL_TOOL_NAMES).issubset(registry.list_tools())
    assert set(NODE_TOOL_NAMES).issubset(registry.list_tools())
    assert registry.get("material.inspect").modifies is False
    assert registry.get("nodes.inspect").permissions == frozenset(
        {permissions.Permission.INSPECT_SCENE}
    )
    assert registry.get("material.set_principled").permissions == frozenset(
        {permissions.Permission.EDIT_MATERIALS}
    )
    assert registry.get("material.delete").permissions == frozenset(
        {
            permissions.Permission.EDIT_MATERIALS,
            permissions.Permission.DELETE_OBJECTS,
        }
    )
    assert all(
        registry.get(name).modifies
        for name in (*MATERIAL_TOOL_NAMES[1:], *NODE_TOOL_NAMES[1:])
    )


def test_lazy_mcp_definitions_are_complete_and_permissioned() -> None:
    material_definitions = load_material_definitions()
    node_definitions = load_node_definitions()

    assert tuple(item.name for item in material_definitions) == MATERIAL_TOOL_NAMES
    assert tuple(item.name for item in node_definitions) == NODE_TOOL_NAMES
    assert all(item.toolset == "materials" for item in material_definitions)
    assert all(item.toolset == "nodes" for item in node_definitions)
    assert next(
        item for item in material_definitions if item.name == "material.delete"
    ).required_permissions == ("EDIT_MATERIALS", "DELETE_OBJECTS")
    assert next(
        item for item in node_definitions if item.name == "nodes.inspect"
    ).required_permissions == ("INSPECT_SCENE",)


def test_material_and_node_wrappers_forward_exact_structured_params() -> None:
    registry = RecordingRegistry()
    material_tools = MaterialTools(registry)  # type: ignore[arg-type]
    node_tools = NodeTools(registry)  # type: ignore[arg-type]

    asyncio.run(
        material_tools.material_set_principled(
            "Paint",
            metallic=0.8,
            roughness=0.25,
        )
    )
    asyncio.run(
        node_tools.nodes_link(
            "Paint",
            "Texture",
            "Color",
            "Principled",
            "Base Color",
            replace_existing=True,
        )
    )

    assert registry.calls[0] == (
        "material.set_principled",
        {"material_name": "Paint", "metallic": 0.8, "roughness": 0.25},
    )
    assert registry.calls[1] == (
        "nodes.link",
        {
            "material_name": "Paint",
            "from_node": "Texture",
            "from_socket": "Color",
            "to_node": "Principled",
            "to_socket": "Base Color",
            "replace_existing": True,
        },
    )


def test_principled_settings_are_bounded_and_report_post_state(
    addon_package: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    materials = importlib.import_module(f"{addon_package}.tools.materials")
    node = make_node(
        "Principled",
        [
            FakeSocket("Base Color", [0.1, 0.1, 0.1, 1.0]),
            FakeSocket("Metallic", 0.0),
            FakeSocket("Roughness", 0.5),
            FakeSocket("IOR", 1.5),
            FakeSocket("Alpha", 1.0),
            FakeSocket("Emission Color", [0.0, 0.0, 0.0, 1.0]),
            FakeSocket("Emission Strength", 0.0),
            FakeSocket("Coat Weight", 0.0),
        ],
    )
    material = SimpleNamespace(
        name="Paint",
        use_nodes=True,
        node_tree=SimpleNamespace(nodes=NodeList([node])),
    )
    monkeypatch.setattr(materials, "_material_exact", lambda _: material)

    result = materials.set_principled(
        None,
        {
            "material_name": "Paint",
            "base_color": [0.2, 0.4, 0.6],
            "metallic": 0.75,
            "roughness": 0.2,
        },
    )

    assert node.inputs.get("Base Color").default_value == [0.2, 0.4, 0.6, 1.0]
    assert node.inputs.get("Metallic").default_value == 0.75
    assert result["changed"]["roughness"]["value"] == 0.2
    previous_color = list(node.inputs.get("Base Color").default_value)
    with pytest.raises(materials.BridgeError) as caught:
        materials.set_principled(
            None,
            {
                "material_name": "Paint",
                "base_color": [0.9, 0.8, 0.7],
                "metallic": math.inf,
            },
        )
    assert caught.value.code == "INVALID_ARGUMENT"
    assert node.inputs.get("Base Color").default_value == previous_color


def test_full_graph_inspection_is_bounded_and_reports_each_truncation(
    addon_package: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    nodes = importlib.import_module(f"{addon_package}.tools.nodes")
    first = make_node(
        "First",
        [FakeSocket("A", 0.0), FakeSocket("B", 1.0)],
    )
    second = make_node("Second")
    tree = SimpleNamespace(name="Paint NodeTree", nodes=NodeList([first, second]), links=[])
    material = SimpleNamespace(name="Paint", use_nodes=True, node_tree=tree)
    blender = SimpleNamespace(
        data=SimpleNamespace(materials=MaterialCollection([material]))
    )
    monkeypatch.setattr(nodes, "require_blender", lambda: blender)

    result = nodes.inspect_nodes(
        None,
        {
            "material_name": "Paint",
            "max_nodes": 1,
            "max_links": 1,
            "max_sockets_per_direction": 1,
        },
    )

    assert result["node_count"] == 2
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["input_count"] == 2
    assert result["truncated"] is True
    assert result["truncated_fields"] == {
        "nodes": True,
        "links": False,
        "socket_lists": True,
        "nodes_with_truncated_sockets": 1,
    }


def test_duplicate_socket_names_require_matching_index(addon_package: str) -> None:
    nodes = importlib.import_module(f"{addon_package}.tools.nodes")
    node = make_node(
        "Math",
        [
            FakeSocket("Value", 0.0, identifier="Value_001"),
            FakeSocket("Value", 1.0, identifier="Value_002"),
        ],
    )

    with pytest.raises(nodes.BridgeError) as caught:
        nodes._socket_exact(node, "input", "Value", None)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert caught.value.context["matching_indices"] == [0, 1]
    assert nodes._socket_exact(node, "input", "Value", 1) is node.inputs[1]


def test_socket_values_reject_non_finite_numbers_and_wrong_vector_length(
    addon_package: str,
) -> None:
    nodes = importlib.import_module(f"{addon_package}.tools.nodes")

    with pytest.raises(nodes.BridgeError, match="finite"):
        nodes._coerce_default_value(FakeSocket("Value", 0.0), float("nan"))
    with pytest.raises(nodes.BridgeError, match="length"):
        nodes._coerce_default_value(
            FakeSocket("Color", [0.0, 0.0, 0.0, 1.0]),
            [1.0, 0.5, 0.25],
        )


def test_exact_names_are_not_trimmed_and_blender_id_bytes_are_bounded(
    addon_package: str,
) -> None:
    materials = importlib.import_module(f"{addon_package}.tools.materials")
    nodes = importlib.import_module(f"{addon_package}.tools.nodes")

    assert materials._required_name({"material_name": " Paint "}, "material_name") == " Paint "
    assert nodes._required_string({"node_name": " Node "}, "node_name") == " Node "
    with pytest.raises(materials.BridgeError, match="UTF-8 bytes"):
        materials._required_name({"name": "é" * 32}, "name")
    with pytest.raises(nodes.BridgeError, match="UTF-8 bytes"):
        nodes._required_string({"name": "é" * 32}, "name")
