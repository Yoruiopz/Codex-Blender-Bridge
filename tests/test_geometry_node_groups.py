from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest

from mcp_server.tools.geometry_node_groups import (
    TOOL_DATA,
    TOOL_NAMES,
    GeometryNodeGroupTools,
    load_definitions,
)


class Items(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class ID:
    def __init__(self, name, **kwargs):
        self.name = name
        self.library = self.override_library = None
        self.is_editable = True
        self.users = 0
        self.use_fake_user = False
        self.__dict__.update(kwargs)


class Modifier(dict):
    def __init__(self, tree, **values):
        super().__init__(**values)
        self.name, self.type, self.node_group = "Procedural", "NODES", tree


def tree(name="Graph", **kwargs):
    return ID(name, bl_idname="GeometryNodeTree", nodes=Items(), links=[], interface=NS(items_tree=[]), **kwargs)


def node(name="Node", kind="ShaderNodeMath", **kwargs):
    return NS(name=name, bl_idname=kind, inputs=Items(), outputs=Items(), **kwargs)


@pytest.fixture
def gn_groups(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.geometry_node_groups")
    permission = importlib.import_module(f"{addon_package}.permissions")
    root = tree()
    socket = NS(name="Width", identifier="Socket_1", item_type="SOCKET", in_out="INPUT", socket_type="NodeSocketFloat", default_value=2.0)
    root.interface.items_tree = Items([socket])
    modifier = Modifier(root, Socket_1=2.0)
    obj = ID("Object", type="MESH", modifiers=Items([modifier]), animation_data=None, bl_rna=NS(identifier="Object"), update_tag=lambda: None)
    user_map = {root: {obj}}
    bpy = NS(context=NS(mode="OBJECT", scene=NS(objects=Items([obj]))),
             data=NS(node_groups=Items([root]), user_map=lambda **kwargs: user_map))
    grants = {item.value: True for item in permission.Permission}
    flags = {"paused": False, "emergency_stopped": False}

    def require(*required):
        missing = [item.value for item in required if not grants[item.value]]
        if missing:
            raise module.BridgeError(module.ErrorCode.PERMISSION_DENIED, "Denied", {"missing": missing})

    context = NS(check_cancelled=None, state=NS(snapshot=lambda: dict(flags)), require=require)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    return NS(module=module, root=root, socket=socket, modifier=modifier, obj=obj, bpy=bpy, user_map=user_map,
              grants=grants, flags=flags, context=context)


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_handlers_reject_unknown_arguments_before_reading_blender(gn_groups, name):
    handler = name.split(".")[1]
    with pytest.raises(gn_groups.module.BridgeError) as error:
        getattr(gn_groups.module, handler)(None, {"unknown": True})
    assert error.value.code == "INVALID_ARGUMENT"


def test_addon_and_mcp_metadata_permissions_and_bindings_match(gn_groups, addon_package):
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry(enabled_toolsets=("geometry_nodes",))
    gn_groups.module.register_tools(registry)
    assert set(registry.list_tools()) == set(TOOL_NAMES)
    assert tuple(item.name for item in load_definitions()) == TOOL_NAMES
    assert tuple(item.name for item in GeometryNodeGroupTools(None).bindings()) == TOOL_NAMES
    for tool_name, _, modifying, permissions in TOOL_DATA:
        spec = registry.get(tool_name)
        assert spec.modifies is modifying and spec.automatic_checkpoint
        assert {item.value for item in spec.permissions} == set(permissions)
        assert spec.toolset == "geometry_nodes"


def test_mcp_forwards_explicit_stable_ids_and_scope():
    calls = []

    class Registry:
        async def call(self, tool_name, params):
            calls.append((tool_name, params))

    wrapper = GeometryNodeGroupTools(Registry())
    asyncio.run(wrapper.geometry_nodes_modifier_set_input("Object", "GN", "Socket_1", 4.0))
    asyncio.run(wrapper.geometry_nodes_group_bind("Parent", "Child", "Instance", allow_shared=True))
    assert calls == [("geometry_nodes.modifier_set_input", {"object_name": "Object", "modifier_name": "GN", "socket_identifier": "Socket_1", "value": 4.0}),
                     ("geometry_nodes.group_bind", {"parent_group_name": "Parent", "child_group_name": "Child", "node_name": "Instance", "allow_shared": True})]


@pytest.mark.parametrize("node_type", ["GeometryNodeImportOBJ", "GeometryNodeObjectInfo", "ShaderNodeScript"])
def test_recursive_review_refuses_unreviewed_nodes_before_attachment(gn_groups, node_type):
    child = tree("Child")
    child.nodes.append(node(kind=node_type))
    gn_groups.root.nodes.append(node(kind="GeometryNodeGroup", node_tree=child))
    with pytest.raises(gn_groups.module.BridgeError) as error:
        gn_groups.module._review(gn_groups.root, gn_groups.context)
    assert error.value.code == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("problem", ["recursive", "unbound", "node_budget", "interface_budget", "socket_budget", "readonly", "depth", "tree_budget"])
def test_bounded_recursive_graph_review_fails_closed(gn_groups, problem):
    root = gn_groups.root
    if problem == "recursive":
        root.nodes.append(node(kind="GeometryNodeGroup", node_tree=root))
    elif problem == "unbound":
        root.nodes.append(node(kind="GeometryNodeGroup", node_tree=None))
    elif problem == "node_budget":
        root.nodes = [node()] * 257
    elif problem == "interface_budget":
        root.interface.items_tree = [gn_groups.socket] * 129
    elif problem == "socket_budget":
        entry = node()
        entry.inputs = [gn_groups.socket] * 129
        root.nodes.append(entry)
    elif problem == "readonly":
        root.library = object()
    elif problem == "depth":
        current = root
        for i in range(10):
            child = tree(f"Child{i}")
            current.nodes.append(node(kind="GeometryNodeGroup", node_tree=child))
            current = child
    else:
        root.nodes = [node(name=f"Node{i}", kind="GeometryNodeGroup", node_tree=tree(f"Child{i}")) for i in range(32)]
    with pytest.raises(gn_groups.module.BridgeError):
        gn_groups.module._review(root, gn_groups.context)


def test_parent_scope_requires_acknowledgement_and_rejects_readonly_consumers(gn_groups):
    parent = tree("Parent")
    gn_groups.user_map[gn_groups.root] = {parent}
    gn_groups.user_map[parent] = {gn_groups.obj}
    with pytest.raises(gn_groups.module.BridgeError, match="allow_shared"):
        gn_groups.module._editable(gn_groups.bpy, gn_groups.root, gn_groups.context, {})
    scope = gn_groups.module._editable(gn_groups.bpy, gn_groups.root, gn_groups.context, {"allow_shared": True})
    assert scope["affected_objects"] == [gn_groups.obj.name] and scope["parent_groups"] == [parent.name]
    gn_groups.obj.override_library = object()
    with pytest.raises(gn_groups.module.BridgeError, match="read-only consumers"):
        gn_groups.module._editable(gn_groups.bpy, gn_groups.root, gn_groups.context, {"allow_shared": True})


@pytest.mark.parametrize("socket_type,value", [("NodeSocketBool", 1), ("NodeSocketInt", True), ("NodeSocketInt", 2**31),
                                              ("NodeSocketFloat", True), ("NodeSocketFloat", float("nan")), ("NodeSocketFloat", 10**1000),
                                              ("NodeSocketVector", [1, 2]), ("NodeSocketColor", [1, 2, 3, float("inf")]),
                                              ("NodeSocketString", "line\nbreak"), ("NodeSocketString", "x" * 1025), ("NodeSocketObject", "Object")])
def test_invalid_typed_values_are_structured_errors_without_mutation(gn_groups, socket_type, value):
    gn_groups.socket.socket_type = socket_type
    with pytest.raises(gn_groups.module.BridgeError):
        gn_groups.module.modifier_set_input(gn_groups.context, {"object_name": "Object", "modifier_name": "Procedural", "socket_identifier": "Socket_1", "value": value})
    assert gn_groups.modifier["Socket_1"] == 2.0


def set_modifier(gn_groups, **kwargs):
    return gn_groups.module.modifier_set_input(gn_groups.context, {"object_name": "Object", "modifier_name": "Procedural", "socket_identifier": "Socket_1", "value": 4.0, **kwargs})


def test_modifier_value_edit_is_object_owned_and_does_not_require_single_user_mesh(gn_groups):
    gn_groups.obj.data = ID("Shared", users=2)
    gn_groups.root.users = 2
    other_modifier = Modifier(gn_groups.root, Socket_1=2.0)
    result = set_modifier(gn_groups)
    assert result["value"] == 4.0 and result["affected_objects"] == ["Object"]
    assert not result["group_definition_changed"] and gn_groups.socket.default_value == 2.0
    assert other_modifier["Socket_1"] == 2.0


@pytest.mark.parametrize("socket_type,value", [("NodeSocketFloat", 3.0), ("NodeSocketInt", 3), ("NodeSocketBool", True),
                                              ("NodeSocketVector", [1.0, 2.0, 3.0]), ("NodeSocketColor", [0.1, 0.2, 0.3, 1.0]), ("NodeSocketString", "value")])
def test_reviewed_modifier_constant_types_are_measured(gn_groups, socket_type, value):
    gn_groups.socket.socket_type = socket_type
    result = set_modifier(gn_groups, value=value)
    assert result["value"] == value


@pytest.mark.parametrize("reason", ["stale", "attribute", "animated", "linked", "mode", "permission", "pause", "stop"])
def test_modifier_preconditions_preserve_existing_state(gn_groups, reason):
    kwargs = {}
    if reason == "stale":
        kwargs["socket_identifier"] = "Socket_999"
    elif reason == "attribute":
        gn_groups.modifier["Socket_1_use_attribute"] = True
    elif reason == "animated":
        gn_groups.obj.animation_data = object()
    elif reason == "linked":
        gn_groups.obj.library = object()
    elif reason == "mode":
        gn_groups.bpy.context.mode = "EDIT_MESH"
    elif reason == "permission":
        gn_groups.grants["TRANSFORM_OBJECTS"] = False
    else:
        gn_groups.flags["paused" if reason == "pause" else "emergency_stopped"] = True
    with pytest.raises(gn_groups.module.BridgeError):
        set_modifier(gn_groups, **kwargs)
    assert gn_groups.modifier["Socket_1"] == 2.0


@pytest.mark.parametrize("existed", [True, False])
def test_cancel_after_modifier_write_restores_measured_value_or_absence(gn_groups, existed):
    if not existed:
        del gn_groups.modifier["Socket_1"]

    def cancel_after_write():
        if gn_groups.modifier.get("Socket_1") == 4.0:
            raise gn_groups.module.BridgeError(gn_groups.module.ErrorCode.OPERATION_FAILED, "Injected cancellation")

    gn_groups.context.check_cancelled = cancel_after_write
    with pytest.raises(gn_groups.module.BridgeError) as error:
        set_modifier(gn_groups)
    assert error.value.context["rollback_verified"] and not error.value.context["possible_mutation"]
    assert ("Socket_1" in gn_groups.modifier) is existed
    assert gn_groups.modifier.get("Socket_1", gn_groups.socket.default_value) == 2.0


def test_revoked_consent_after_write_is_reported_as_possible_mutation(gn_groups):
    def revoke_after_write():
        if gn_groups.modifier.get("Socket_1") == 4.0:
            gn_groups.grants["TRANSFORM_OBJECTS"] = False

    gn_groups.context.check_cancelled = revoke_after_write
    with pytest.raises(gn_groups.module.BridgeError) as error:
        set_modifier(gn_groups)
    assert not error.value.context["rollback_verified"] and error.value.context["possible_mutation"]
    assert gn_groups.modifier["Socket_1"] == 4.0


def test_inspection_reports_stable_ids_after_name_change_without_evaluation(gn_groups):
    gn_groups.socket.name = "Renamed"
    result = gn_groups.module.modifier_inspect(gn_groups.context, {"object_name": "Object", "modifier_name": "Procedural"})
    assert result["inputs"][0]["identifier"] == "Socket_1"
    assert result["inputs"][0]["name"] == "Renamed" and result["inputs"][0]["value"] == 2.0
    assert not result["truncated"]


def gate_hook(gn_groups, monkeypatch, hook):
    original = gn_groups.module._gate
    count = []

    def gate(context, *permissions):
        original(context, *permissions)
        count.append(None)
        hook(len(count))

    monkeypatch.setattr(gn_groups.module, "_gate", gate)


def runtime_socket():
    return NS(name="Width", identifier="Socket_1", type="VALUE", socket_type="NodeSocketFloat", default_value=2.0,
              enabled=True, is_linked=False, is_multi_input=False)


def graph_input(gn_groups):
    target = node(name="Math")
    target.inputs.append(runtime_socket())
    gn_groups.root.nodes.append(target)
    return target.inputs[0]


@pytest.mark.parametrize("ordinal", [1, 2])
def test_group_input_gate_edits_are_not_overwritten_by_write_or_compensation(gn_groups, monkeypatch, ordinal):
    socket = graph_input(gn_groups)

    def hook(count):
        if count == ordinal:
            socket.default_value = 42.0

    gate_hook(gn_groups, monkeypatch, hook)
    with pytest.raises(gn_groups.module.BridgeError):
        gn_groups.module.group_set_input(gn_groups.context, {"group_name": "Graph", "node_name": "Math", "socket_identifier": "Socket_1", "value": 4.0})
    assert socket.default_value == 42.0


@pytest.mark.parametrize("ordinal", [1, 2])
@pytest.mark.parametrize("change_binding", [False, True])
def test_modifier_gate_value_or_binding_edits_are_preserved(gn_groups, monkeypatch, ordinal, change_binding):
    replacement = tree("Manual Replacement")

    def hook(count):
        if count == ordinal:
            gn_groups.modifier["Socket_1"] = 42.0
            if change_binding:
                gn_groups.modifier.node_group = replacement

    gate_hook(gn_groups, monkeypatch, hook)
    with pytest.raises(gn_groups.module.BridgeError):
        set_modifier(gn_groups)
    assert gn_groups.modifier["Socket_1"] == 42.0
    assert gn_groups.modifier.node_group == (replacement if change_binding else gn_groups.root)


def test_group_link_final_gate_does_not_replace_new_manual_connection(gn_groups, monkeypatch):
    source, target, manual = node("Source"), node("Target"), node("Manual")
    source.outputs.append(runtime_socket())
    manual.outputs.append(runtime_socket())
    target.inputs.append(runtime_socket())
    gn_groups.root.nodes.extend([source, target, manual])
    connection = NS(from_node=manual, from_socket=manual.outputs[0], to_node=target, to_socket=target.inputs[0])

    def hook(count):
        if count == 1:
            gn_groups.root.links.append(connection)

    gate_hook(gn_groups, monkeypatch, hook)
    with pytest.raises(gn_groups.module.BridgeError, match="changed after inspection"):
        gn_groups.module.group_link(gn_groups.context, {"group_name": "Graph", "from_node": "Source", "from_socket_identifier": "Socket_1", "to_node": "Target", "to_socket_identifier": "Socket_1"})
    assert gn_groups.root.links == [connection]


def test_group_copy_final_gate_does_not_overwrite_a_changed_child_binding(gn_groups, monkeypatch):
    original, replacement = tree("Child"), tree("Replacement")
    gn_groups.bpy.data.node_groups.extend([original, replacement])
    original.copy = lambda: pytest.fail("Stale child binding was copied")
    instance = node("Nested", "GeometryNodeGroup", node_tree=original)
    gn_groups.root.nodes.append(instance)

    def hook(count):
        if count == 1:
            instance.node_tree = replacement

    gate_hook(gn_groups, monkeypatch, hook)
    with pytest.raises(gn_groups.module.BridgeError, match="changed after inspection"):
        gn_groups.module.group_copy_for_node(gn_groups.context, {"parent_group_name": "Graph", "node_name": "Nested", "new_group_name": "Copy"})
    assert instance.node_tree == replacement


@pytest.mark.parametrize("change_binding", [False, True])
def test_post_copy_manual_binding_or_configuration_is_not_rolled_back(gn_groups, monkeypatch, change_binding):
    original, replacement, clone = tree("Child"), tree("Replacement"), tree("Copy")
    gn_groups.bpy.data.node_groups.extend([original, replacement])

    def copy():
        gn_groups.bpy.data.node_groups.append(clone)
        return clone

    original.copy = copy
    instance = node("Nested", "GeometryNodeGroup", node_tree=original)
    gn_groups.root.nodes.append(instance)

    def hook(count):
        if count == 2:
            if change_binding:
                instance.node_tree = replacement
            else:
                clone.nodes.append(node("Manual edit"))

    gate_hook(gn_groups, monkeypatch, hook)
    with pytest.raises(gn_groups.module.BridgeError) as error:
        gn_groups.module.group_copy_for_node(gn_groups.context, {"parent_group_name": "Graph", "node_name": "Nested", "new_group_name": "Copy"})
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
    assert not error.value.context["binding_restored"]
    assert instance.node_tree == (replacement if change_binding else clone)
    assert clone in gn_groups.bpy.data.node_groups


def test_group_removal_rechecks_live_users_after_gate(gn_groups, monkeypatch):
    def hook(count):
        if count == 1:
            gn_groups.root.users = 1

    gate_hook(gn_groups, monkeypatch, hook)
    with pytest.raises(gn_groups.module.BridgeError, match="users/configuration changed"):
        gn_groups.module.group_remove(gn_groups.context, {"group_name": "Graph", "confirm_unused": True})
    assert gn_groups.root in gn_groups.bpy.data.node_groups


@pytest.mark.parametrize("ordinal", [1, 2])
def test_group_attachment_gate_rebinding_is_not_overwritten_or_rolled_back(gn_groups, monkeypatch, ordinal):
    original, replacement = tree("Old Binding"), tree("Manual Binding")
    gn_groups.modifier.node_group = original
    gn_groups.root.interface.items_tree.append(NS(name="Geometry", identifier="Socket_0", item_type="SOCKET", in_out="OUTPUT", socket_type="NodeSocketGeometry"))

    def hook(count):
        if count == ordinal:
            gn_groups.modifier.node_group = replacement
            gn_groups.modifier["Socket_1"] = 42.0

    gate_hook(gn_groups, monkeypatch, hook)
    with pytest.raises(gn_groups.module.BridgeError):
        gn_groups.module.group_attach(gn_groups.context, {"group_name": "Graph", "object_name": "Object", "modifier_name": "Procedural", "replace_existing_group": True})
    assert gn_groups.modifier.node_group == replacement and gn_groups.modifier["Socket_1"] == 42.0


@pytest.mark.parametrize("allow_shared", [False, True])
@pytest.mark.parametrize("change", ["consumer", "readonly"])
def test_graph_compensation_refuses_new_consumer_scope_or_readonly_root(gn_groups, monkeypatch, allow_shared, change):
    socket = graph_input(gn_groups)
    consumer = ID("Protected New Consumer", bl_rna=NS(identifier="Object"))

    def hook(count):
        if count == 2:
            if change == "consumer":
                gn_groups.user_map[gn_groups.root].add(consumer)
                gn_groups.root.users = 2
            else:
                gn_groups.root.is_editable = False

    gate_hook(gn_groups, monkeypatch, hook)
    with pytest.raises(gn_groups.module.BridgeError) as error:
        gn_groups.module.group_set_input(gn_groups.context, {"group_name": "Graph", "node_name": "Math", "socket_identifier": "Socket_1", "value": 4.0, "allow_shared": allow_shared})
    assert socket.default_value == 4.0
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
