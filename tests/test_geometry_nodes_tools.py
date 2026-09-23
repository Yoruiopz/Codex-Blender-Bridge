from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.geometry_nodes import (
    TOOL_DATA,
    TOOL_NAMES,
    GeometryNodeTools,
    load_definitions,
)


class NamedItems(list[Any]):
    def get(self, name: str) -> Any:
        return next((item for item in self if item.name == name), None)


class RecordingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, params: dict[str, Any]) -> Any:
        self.calls.append((name, params))
        return params


@pytest.fixture
def geometry(addon_package: str) -> Any:
    return importlib.import_module(f"{addon_package}.tools.geometry_nodes")


@pytest.mark.parametrize("handler", ["create_graph", "add_interface", "add_node", "set_node_properties", "set_node_input", "remove_node", "link_nodes", "unlink_nodes", "attach_graph"])
def test_graph_mutations_reject_unknown_parameters(geometry: Any, handler: str) -> None:
    with pytest.raises(Exception) as caught:
        getattr(geometry, handler)(None, {"unrecognized": True})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert "Unknown parameters" in caught.value.message


def fake_tree(**kwargs: Any) -> Any:
    values = {
        "name": "Procedural",
        "bl_idname": "GeometryNodeTree",
        "users": 0,
        "library": None,
        "override_library": None,
        "is_editable": True,
        "nodes": NamedItems(),
        "links": [],
        "interface": SimpleNamespace(items_tree=[]),
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def install_tree(geometry: Any, monkeypatch: pytest.MonkeyPatch, tree: Any) -> Any:
    blender = SimpleNamespace(data=SimpleNamespace(node_groups=NamedItems([tree])))
    monkeypatch.setattr(geometry, "require_blender", lambda: blender)
    monkeypatch.setattr(geometry, "_users", lambda _: [])
    return blender


def fake_node(name: str) -> Any:
    return SimpleNamespace(
        name=name,
        label="",
        type="MATH",
        bl_idname="ShaderNodeMath",
        location=(0, 0),
        dimensions=(100, 100),
        mute=False,
        hide=False,
        inputs=[],
        outputs=[],
        bl_rna=SimpleNamespace(properties={}),
    )


@pytest.mark.parametrize("node_type", ["GeometryNodeImportOBJ", "GeometryNodeImportPLY", "ShaderNodeScript"])
def test_unreviewed_file_and_script_nodes_are_rejected(geometry: Any, monkeypatch: pytest.MonkeyPatch, node_type: str) -> None:
    tree = fake_tree()
    install_tree(geometry, monkeypatch, tree)
    with pytest.raises(geometry.BridgeError) as caught:
        geometry.add_node(None, {"group_name": tree.name, "node_type": node_type})
    assert caught.value.code == "NOT_IMPLEMENTED"
    unsafe = fake_node("Unsafe")
    unsafe.bl_idname = node_type
    tree.nodes.append(unsafe)
    with pytest.raises(geometry.BridgeError) as caught:
        geometry._group({"group_name": tree.name}, modify=True)
    assert caught.value.code == "NOT_IMPLEMENTED"
    with pytest.raises(geometry.BridgeError) as caught:
        geometry.attach_graph(None, {"group_name": tree.name, "object_name": "Cube", "modifier_name": "Test"})
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_addon_and_mcp_metadata_match(addon_package: str, geometry: Any) -> None:
    module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = module.ToolRegistry(enabled_toolsets=("geometry_nodes",))
    geometry.register_tools(registry)
    definitions = load_definitions()
    assert tuple(item.name for item in definitions) == TOOL_NAMES
    assert set(registry.list_tools()) == set(TOOL_NAMES)
    for name, _, modifies, required in TOOL_DATA:
        spec = registry.get(name)
        assert spec.toolset == "geometry_nodes"
        assert spec.modifies is modifies
        assert {item.value for item in spec.permissions} == set(required)
        assert spec.automatic_checkpoint
    assert registry.get("geometry_nodes.attach").metadata(enabled=True)["required_permissions"] == [
        "EDIT_MESH",
        "TRANSFORM_OBJECTS",
    ]


def test_mcp_bindings_and_exact_parameter_forwarding() -> None:
    recording = RecordingRegistry()
    wrappers = GeometryNodeTools(recording)  # type: ignore[arg-type]
    assert tuple(item.name for item in wrappers.bindings()) == tuple(
        name for name in TOOL_NAMES if not name.startswith("geometry_nodes.zone_")
    )
    asyncio.run(wrappers.geometry_nodes_create("Graph", passthrough=False))
    asyncio.run(
        wrappers.geometry_nodes_node_set_input(
            "Graph", "Math", "Value", 3.0, socket_index=1, allow_shared=True
        )
    )
    asyncio.run(
        wrappers.geometry_nodes_attach("Graph", "Target", "Geometry", replace_existing_group=True)
    )
    assert recording.calls == [
        ("geometry_nodes.create", {"group_name": "Graph", "passthrough": False}),
        (
            "geometry_nodes.node_set_input",
            {
                "group_name": "Graph",
                "node_name": "Math",
                "socket_name": "Value",
                "value": 3.0,
                "socket_index": 1,
                "allow_shared": True,
            },
        ),
        (
            "geometry_nodes.attach",
            {
                "group_name": "Graph",
                "object_name": "Target",
                "modifier_name": "Geometry",
                "replace_existing_group": True,
            },
        ),
    ]


def test_dispatch_checks_live_permissions_before_blender(addon_package: str, geometry: Any) -> None:
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permission_module = importlib.import_module(f"{addon_package}.permissions")
    state_module = importlib.import_module(f"{addon_package}.state")
    registry = registry_module.ToolRegistry(enabled_toolsets=("geometry_nodes",))
    geometry.register_tools(registry)
    permissions = {"INSPECT_SCENE": True, "EDIT_MESH": True, "TRANSFORM_OBJECTS": False}
    context = registry_module.ToolContext(
        state_module.BridgeState(),
        permission_module.PermissionManager(lambda: permissions),
        registry,
        None,
    )
    with pytest.raises(geometry.BridgeError) as caught:
        registry.dispatch(
            "geometry_nodes.attach",
            {"group_name": "Graph", "object_name": "Target", "modifier_name": "GN"},
            context,
        )
    assert caught.value.code == "PERMISSION_DENIED"
    assert caught.value.context["missing_permissions"] == ["TRANSFORM_OBJECTS"]
    permissions["EDIT_MESH"] = False
    with pytest.raises(geometry.BridgeError) as caught:
        registry.dispatch("geometry_nodes.create", {"group_name": "Graph"}, context)
    assert caught.value.code == "PERMISSION_DENIED"


@pytest.mark.parametrize(
    "changes", [{"library": object()}, {"override_library": object()}, {"is_editable": False}]
)
def test_linked_override_or_noneditable_graph_is_not_mutated(
    geometry: Any, monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    tree = fake_tree(**changes)
    install_tree(geometry, monkeypatch, tree)
    with pytest.raises(geometry.BridgeError, match="local, editable"):
        geometry._group({"group_name": tree.name}, modify=True)
    assert geometry._group({"group_name": tree.name}) is tree


def test_group_requires_exact_geometry_tree_type(
    geometry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = fake_tree(bl_idname="ShaderNodeTree")
    install_tree(geometry, monkeypatch, tree)
    for name in (tree.name, "Missing"):
        with pytest.raises(geometry.BridgeError, match="GeometryNodeTree"):
            geometry._group({"group_name": name}, modify=True)


def test_shared_or_nested_graph_needs_per_call_acknowledgement(
    geometry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = fake_tree(users=2)
    install_tree(geometry, monkeypatch, tree)
    with pytest.raises(geometry.BridgeError, match="allow_shared"):
        geometry._group({"group_name": tree.name}, modify=True)
    assert geometry._group({"group_name": tree.name, "allow_shared": True}, modify=True) is tree
    tree.users = 1
    monkeypatch.setattr(geometry, "_users", lambda _: [fake_tree(name="Outer")])
    with pytest.raises(geometry.BridgeError, match="allow_shared"):
        geometry._group({"group_name": tree.name}, modify=True)
    with pytest.raises(geometry.BridgeError, match="boolean"):
        geometry._group({"group_name": tree.name, "allow_shared": "true"}, modify=True)


def test_geometry_inspection_is_bounded_and_reports_truncation(
    geometry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = fake_tree(nodes=NamedItems([fake_node("First"), fake_node("Second")]))
    tree.interface.items_tree = [
        SimpleNamespace(
            name="Geometry",
            identifier=f"Socket_{index}",
            item_type="SOCKET",
            in_out="INPUT",
            socket_type="NodeSocketGeometry",
        )
        for index in range(3)
    ]
    install_tree(geometry, monkeypatch, tree)
    result = geometry.inspect_graph(
        None, {"group_name": tree.name, "max_nodes": 1, "max_interface_items": 1}
    )
    assert result["graph_type"] == "GEOMETRY_NODES"
    assert "material" not in result and "node_tree" not in result
    assert result["node_count"] == 2 and len(result["nodes"]) == 1
    assert result["interface_item_count"] == 3 and len(result["interface"]) == 1
    assert result["truncated"] and result["truncated_fields"]["interface"]
    assert result["truncated_fields"]["nodes"]


@pytest.mark.parametrize(
    "params",
    [{"in_out": []}, {"in_out": "BOTH"}, {"socket_type": []}, {"socket_type": "NodeSocketObject"}],
)
def test_interface_rejects_invalid_arguments_before_creation(
    geometry: Any, monkeypatch: pytest.MonkeyPatch, params: dict[str, Any]
) -> None:
    tree = fake_tree()
    install_tree(geometry, monkeypatch, tree)
    with pytest.raises(geometry.BridgeError) as caught:
        geometry.add_interface(None, {"group_name": tree.name, "name": "New", **params})
    assert caught.value.code == "INVALID_ARGUMENT"
    assert tree.interface.items_tree == []


@pytest.mark.parametrize(
    "node_type", ["GeometryNodeGroup", "GeometryNodeSimulationOutput", "GeometryNodeRepeatInput"]
)
def test_unimplemented_zone_or_nested_group_returns_explicit_error(
    geometry: Any, monkeypatch: pytest.MonkeyPatch, node_type: str
) -> None:
    tree = fake_tree()
    install_tree(geometry, monkeypatch, tree)
    with pytest.raises(geometry.BridgeError) as caught:
        geometry.add_node(None, {"group_name": tree.name, "node_type": node_type})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert tree.nodes == []


def test_invalid_node_type_is_not_attribute_access(
    geometry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = fake_tree()
    install_tree(geometry, monkeypatch, tree)
    with pytest.raises(geometry.BridgeError, match="node_type"):
        geometry.add_node(None, {"group_name": tree.name, "node_type": "__class__.something"})


def test_link_rejects_incompatible_socket_disabled_input_and_cycles(geometry: Any) -> None:
    first, second = fake_node("First"), fake_node("Second")
    tree = fake_tree()
    source = SimpleNamespace(type="GEOMETRY", enabled=True)
    target = SimpleNamespace(type="VALUE", enabled=True)
    with pytest.raises(geometry.BridgeError, match="incompatible"):
        geometry._check_link(tree, first, source, second, target)
    target.type = "GEOMETRY"
    target.enabled = False
    with pytest.raises(geometry.BridgeError, match="disabled"):
        geometry._check_link(tree, first, source, second, target)
    target.enabled = True
    tree.links = [SimpleNamespace(from_node=second, to_node=first)]
    with pytest.raises(geometry.BridgeError, match="cycle"):
        geometry._check_link(tree, first, source, second, target)
    tree.links = []
    geometry._check_link(tree, first, source, second, target)
    with pytest.raises(geometry.BridgeError, match="cycle"):
        geometry._check_link(tree, first, source, first, target)


def test_post_state_reports_bounded_direct_users(
    geometry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = fake_tree(users=130)
    monkeypatch.setattr(
        geometry,
        "_users",
        lambda _: [
            SimpleNamespace(name=f"Object {index:03d}", bl_rna=SimpleNamespace(identifier="Object"))
            for index in range(130)
        ],
    )
    result = geometry._post_state(tree)
    assert result["direct_users_truncated"]
    assert len(result["direct_users"]) == 128 and len(result["affected_objects"]) == 128


def test_attach_rejects_wrong_modifier_without_changing_it(
    geometry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = fake_tree()
    tree.interface.items_tree = [
        SimpleNamespace(item_type="SOCKET", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    ]
    install_tree(geometry, monkeypatch, tree)
    modifier = SimpleNamespace(name="GN", type="BEVEL")
    obj = SimpleNamespace(name="Target", type="MESH", modifiers=NamedItems([modifier]))
    monkeypatch.setattr(geometry, "get_object", lambda *args, **kwargs: obj)
    with pytest.raises(geometry.BridgeError, match="not a Geometry Nodes"):
        geometry.attach_graph(
            None, {"group_name": tree.name, "object_name": obj.name, "modifier_name": modifier.name}
        )
    assert modifier.type == "BEVEL" and obj.modifiers == [modifier]


def test_attach_requires_explicit_group_replacement(
    geometry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = fake_tree()
    tree.interface.items_tree = [
        SimpleNamespace(item_type="SOCKET", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    ]
    install_tree(geometry, monkeypatch, tree)
    previous = fake_tree(name="Original")
    modifier = SimpleNamespace(name="GN", type="NODES", node_group=previous)
    obj = SimpleNamespace(name="Target", type="MESH", modifiers=NamedItems([modifier]))
    monkeypatch.setattr(geometry, "get_object", lambda *args, **kwargs: obj)
    with pytest.raises(geometry.BridgeError, match="replace_existing_group"):
        geometry.attach_graph(
            None, {"group_name": tree.name, "object_name": obj.name, "modifier_name": modifier.name}
        )
    assert modifier.node_group is previous


def test_node_settings_do_not_allow_paths_or_pointers(
    geometry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = fake_tree(nodes=NamedItems([fake_node("Target")]))
    install_tree(geometry, monkeypatch, tree)
    for settings in (
        {"node_tree": "Other"},
        {"inputs[0].default_value": 5},
        {"script": "anything"},
    ):
        with pytest.raises(geometry.BridgeError) as caught:
            geometry.set_node_properties(
                None, {"group_name": tree.name, "node_name": "Target", "settings": settings}
            )
        assert caught.value.code == "INVALID_ARGUMENT"
