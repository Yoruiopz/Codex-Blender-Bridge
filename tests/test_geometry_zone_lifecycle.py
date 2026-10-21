from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest
from test_geometry_node_groups import ID, Items, gn_groups, tree

from mcp_server.tools.geometry_zone_lifecycle import (
    TOOL_DATA,
    TOOL_NAMES,
    GeometryZoneLifecycleTools,
    load_definitions,
)

assert gn_groups  # Imported reusable native-shaped ownership fixture.


def node(name="Node", kind="ShaderNodeMath", **kwargs):
    result = NS(name=name, bl_idname=kind, inputs=Items(), outputs=Items())
    result.__dict__.update(kwargs)
    return result


class ZoneItem:
    def __init__(self, sockets):
        self.name, self.attribute_domain = "Amount", "POINT"
        self.sockets, self._socket_type = sockets, "FLOAT"

    @property
    def socket_type(self):
        return self._socket_type

    @socket_type.setter
    def socket_type(self, value):
        self._socket_type = value
        for socket in self.sockets:
            socket.type = {"FLOAT": "VALUE"}.get(value, value)
            socket.default_value = {"FLOAT": 0., "INT": 0, "BOOLEAN": False, "VECTOR": [0., 0., 0.], "RGBA": [0.8, 0.8, 0.8, 1.]}[value]


class Interface:
    def __init__(self, items):
        self.items_tree = Items(items)

    def move(self, item, insertion):
        old = self.items_tree.index(item)
        self.items_tree.pop(old)
        self.items_tree.insert(insertion - int(old < insertion), item)


@pytest.fixture
def lifecycle(gn_groups, addon_package, monkeypatch):
    f = gn_groups
    f.lifecycle = importlib.import_module(f"{addon_package}.tools.geometry_zone_lifecycle")
    monkeypatch.setattr(f.lifecycle, "require_blender", lambda: f.bpy)
    f.bpy.data.objects = Items([f.obj])
    f.obj.data = ID("Mesh")
    other = NS(name="Second", identifier="Socket_2", item_type="SOCKET", in_out="INPUT", socket_type="NodeSocketFloat", default_value=3.)
    f.root.interface = Interface([f.socket, other])
    sockets = [NS(name="Amount", identifier="Item_1", type="VALUE", default_value=value, is_linked=False) for value in (1.25, 2.5, 3.75, 4.5)]
    f.item = ZoneItem(sockets)
    f.output = node("Output", "GeometryNodeRepeatOutput", repeat_items=[f.item], inputs=Items([sockets[2]]), outputs=Items([sockets[3]]))
    iterations = NS(name="Iterations", identifier="Iterations", type="INT", default_value=2, is_linked=False)
    f.source = node("Input", "GeometryNodeRepeatInput", paired_output=f.output, inputs=Items([iterations, sockets[0]]), outputs=Items([sockets[1]]))
    f.root.nodes.extend([f.source, f.output])
    f.params = {"group_name": f.root.name, "output_name": f.output.name, "socket_identifier": "Item_1", "socket_type": "INT", "input_value": 4, "output_value": 8}
    return f


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_unknown_arguments_refused_before_blender(lifecycle, tool_name):
    with pytest.raises(lifecycle.lifecycle.BridgeError):
        getattr(lifecycle.lifecycle, tool_name.split(".")[1])(None, {"unknown": True})


def test_addon_mcp_metadata_parity(lifecycle, addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry(enabled_toolsets=("geometry_nodes",))
    lifecycle.lifecycle.register_tools(registry)
    assert set(registry.list_tools()) == set(TOOL_NAMES)
    assert tuple(item.name for item in load_definitions()) == TOOL_NAMES
    assert tuple(item.name for item in GeometryZoneLifecycleTools(None).bindings()) == TOOL_NAMES
    for tool_name, _, modifies, permissions in TOOL_DATA:
        spec = registry.get(tool_name)
        assert spec.modifies == modifies and spec.automatic_checkpoint
        assert {permission.value for permission in spec.permissions} == set(permissions)


def test_mcp_forwards_only_relevant_interface_parameters():
    calls = []

    class Registry:
        async def call(self, method, params):
            calls.append((method, params))

    wrapper = GeometryZoneLifecycleTools(Registry())
    asyncio.run(wrapper.geometry_nodes_interface_edit("Graph", "Socket_1", "RENAME", new_name="Width"))
    asyncio.run(wrapper.geometry_nodes_zone_item_convert("Graph", "Out", "Item_1", "INT", 2, 3))
    assert calls[0] == ("geometry_nodes.interface_edit", {"group_name": "Graph", "socket_identifier": "Socket_1", "operation": "RENAME", "new_name": "Width", "allow_shared": False})
    assert calls[1][1]["input_value"] == 2 and calls[1][1]["output_value"] == 3


def test_zone_inspection_exposes_stable_socket_identifiers(lifecycle):
    result = lifecycle.lifecycle.zone_inspect(lifecycle.context, {"group_name": "Graph", "output_name": "Output"})
    assert result["items"] == [{"name": "Amount", "socket_type": "FLOAT", "socket_identifier": "Item_1", "attribute_domain": "POINT"}]
    assert result["cache_status_verified"] is False and result["truncated"] is False


@pytest.mark.parametrize("kind,input_value,output_value", [("FLOAT", 2.5, 3.5), ("INT", 2, 3), ("BOOLEAN", True, False),
    ("VECTOR", [1., 2., 3.], [4., 5., 6.]), ("RGBA", [0., 0.2, 0.3, 1.], [0.4, 0.5, 0.6, 0.])])
def test_conversion_preserves_identifiers_and_sets_both_defaults(lifecycle, kind, input_value, output_value):
    f = lifecycle
    result = f.lifecycle.zone_item_convert(f.context, {**f.params, "socket_type": kind, "input_value": input_value, "output_value": output_value})
    assert result["paired_identifiers_preserved"]
    assert result["input_value"] == input_value and result["output_value"] == output_value
    assert f.item.socket_type == kind
    assert f.source.inputs[-1].identifier == f.output.outputs[0].identifier == "Item_1"
    assert f.source.inputs[0].default_value == 2
    assert f.modifier["Socket_1"] == 2.


@pytest.mark.parametrize("invalid", [None, True, 1.2, 2**32, "1"])
def test_bad_integer_defaults_refused_before_write(lifecycle, invalid):
    with pytest.raises(lifecycle.lifecycle.BridgeError):
        lifecycle.lifecycle.zone_item_convert(lifecycle.context, {**lifecycle.params, "input_value": invalid})
    assert lifecycle.item.socket_type == "FLOAT"


@pytest.mark.parametrize("problem", ["linked_input", "linked_output", "missing_pair", "two_pairs", "geometry", "missing_identifier", "unsupported_type", "oversized", "readonly", "mode", "cache", "animation"])
def test_conversion_refuses_unproven_or_unowned_scope(lifecycle, problem):
    f = lifecycle
    if problem == "linked_input":
        f.source.inputs[-1].is_linked = True
    elif problem == "linked_output":
        f.output.outputs[0].is_linked = True
    elif problem == "missing_pair":
        f.root.nodes.remove(f.source)
    elif problem == "two_pairs":
        f.root.nodes.append(node("Other Input", "GeometryNodeRepeatInput", paired_output=f.output, inputs=f.source.inputs))
    elif problem == "geometry":
        f.item._socket_type = "GEOMETRY"
    elif problem == "missing_identifier":
        f.params["socket_identifier"] = "Item_999"
    elif problem == "unsupported_type":
        f.params["socket_type"] = "MATERIAL"
    elif problem == "oversized":
        f.output.repeat_items *= 33
    elif problem == "readonly":
        f.root.is_editable = False
    elif problem == "mode":
        f.bpy.context.mode = "EDIT_MESH"
    elif problem == "cache":
        f.modifier.bakes = [NS()]
    else:
        f.obj.animation_data = NS()
    with pytest.raises(f.lifecycle.BridgeError):
        f.lifecycle.zone_item_convert(f.context, f.params)
    assert f.item.socket_type in {"FLOAT", "GEOMETRY"}


@pytest.mark.parametrize("operation,extra,expected", [("RENAME", {"new_name": "Renamed"}, "Renamed"),
    ("MOVE", {"to_index": 1}, 1), ("SET_DEFAULT", {"value": 4.5}, 4.5)])
def test_interface_lifecycle_preserves_modifier_values(lifecycle, operation, extra, expected):
    f = lifecycle
    result = f.lifecycle.interface_edit(f.context, {"group_name": "Graph", "socket_identifier": "Socket_1", "operation": operation, **extra})
    assert result["value"] == expected and result["existing_consumer_values_preserved"]
    assert f.modifier["Socket_1"] == 2.
    assert f.socket.identifier == "Socket_1" and f.item.socket_type == "FLOAT"
    if operation == "MOVE":
        assert [item.identifier for item in f.root.interface.items_tree] == ["Socket_2", "Socket_1"]


@pytest.mark.parametrize("operation,extra", [("REMOVE", {}), ("RENAME", {"new_name": "Second"}), ("MOVE", {"to_index": -1}),
    ("MOVE", {"to_index": 2}), ("MOVE", {"to_index": True}), ("SET_DEFAULT", {"value": float("inf")}), ("RENAME", {"new_name": "x" * 64})])
def test_interface_invalid_arguments_do_not_write(lifecycle, operation, extra):
    f = lifecycle
    with pytest.raises(f.lifecycle.BridgeError):
        f.lifecycle.interface_edit(f.context, {"group_name": "Graph", "socket_identifier": "Socket_1", "operation": operation, **extra})
    assert f.socket.name == "Width" and f.socket.default_value == 2.


@pytest.mark.parametrize("tool", ["zone_item_convert", "interface_edit"])
@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("manual", ["root_value", "consumer_value", "consumer_added", "readonly", "schema"])
def test_manual_boundary_edits_are_preserved_and_never_compensated_over(lifecycle, monkeypatch, tool, when, manual):
    f = lifecycle
    original_gate = f.module._gate
    calls = 0

    def gate(context, *permissions):
        nonlocal calls
        original_gate(context, *permissions)
        calls += 1
        if calls != (1 if when == "before" else 2):
            return
        if manual == "root_value":
            f.root.interface.items_tree[1].default_value = 19.
        elif manual == "consumer_value":
            f.modifier["Socket_1"] = 23.
        elif manual == "consumer_added":
            obj = ID("New User", bl_rna=NS(identifier="Object"))
            f.user_map[f.root].add(obj)
        elif manual == "readonly":
            f.root.is_editable = False
        else:
            f.item.name = "Manual Schema"

    monkeypatch.setattr(f.module, "_gate", gate)
    params = f.params if tool == "zone_item_convert" else {"group_name": "Graph", "socket_identifier": "Socket_1", "operation": "RENAME", "new_name": "Renamed"}
    with pytest.raises(f.lifecycle.BridgeError) as error:
        getattr(f.lifecycle, tool)(f.context, params)
    if when == "before":
        assert f.socket.name == "Width" and f.item.socket_type == "FLOAT"
    else:
        assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
    if manual == "root_value":
        assert f.root.interface.items_tree[1].default_value == 19.
    elif manual == "consumer_value":
        assert f.modifier["Socket_1"] == 23.
    elif manual == "schema":
        assert f.item.name == "Manual Schema"


@pytest.mark.parametrize("tool", ["zone_item_convert", "interface_edit"])
def test_post_write_failure_restores_complete_owned_state(lifecycle, monkeypatch, tool):
    f = lifecycle
    before = f.module._graph_guard(f.root)
    original_gate = f.module._gate
    calls = 0

    def gate(context, *permissions):
        nonlocal calls
        original_gate(context, *permissions)
        calls += 1
        if calls == 2:
            raise f.lifecycle.BridgeError(f.lifecycle.ErrorCode.OPERATION_FAILED, "Injected post-write fault")

    monkeypatch.setattr(f.module, "_gate", gate)
    params = f.params if tool == "zone_item_convert" else {"group_name": "Graph", "socket_identifier": "Socket_1", "operation": "MOVE", "to_index": 1}
    with pytest.raises(f.lifecycle.BridgeError) as error:
        getattr(f.lifecycle, tool)(f.context, params)
    assert error.value.context["rollback_verified"] and not error.value.context["possible_mutation"]
    assert f.module._graph_guard(f.root) == before


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("tool", ["zone_item_convert", "interface_edit"])
def test_live_permission_loss_never_authorizes_compensating_edits(lifecycle, monkeypatch, tool, when):
    f = lifecycle
    original_gate = f.module._gate
    calls = 0

    def gate(context, *permissions):
        nonlocal calls
        calls += 1
        if calls == (1 if when == "before" else 2):
            f.grants["EDIT_MESH"] = False
        original_gate(context, *permissions)

    monkeypatch.setattr(f.module, "_gate", gate)
    params = f.params if tool == "zone_item_convert" else {"group_name": "Graph", "socket_identifier": "Socket_1", "operation": "RENAME", "new_name": "Renamed"}
    with pytest.raises(f.lifecycle.BridgeError) as error:
        getattr(f.lifecycle, tool)(f.context, params)
    assert error.value.code == "PERMISSION_DENIED"
    if when == "after":
        assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
        assert f.item.socket_type == ("INT" if tool == "zone_item_convert" else "FLOAT")
    else:
        assert f.item.socket_type == "FLOAT" and f.socket.name == "Width"


@pytest.mark.parametrize("stop", ["paused", "emergency_stopped", "cancelled"])
@pytest.mark.parametrize("tool", ["zone_item_convert", "interface_edit"])
def test_post_write_stop_blocks_new_compensating_schema_edits(lifecycle, monkeypatch, tool, stop):
    f = lifecycle
    original_gate = f.module._gate
    calls = 0

    def gate(context, *permissions):
        nonlocal calls
        calls += 1
        if calls == 2:
            if stop == "cancelled":
                def cancelled():
                    raise f.lifecycle.BridgeError(f.lifecycle.ErrorCode.TIMEOUT, "Persistent cancellation")
                f.context.check_cancelled = cancelled
            else:
                f.flags[stop] = True
        original_gate(context, *permissions)

    monkeypatch.setattr(f.module, "_gate", gate)
    params = f.params if tool == "zone_item_convert" else {"group_name": "Graph", "socket_identifier": "Socket_1", "operation": "RENAME", "new_name": "Renamed"}
    with pytest.raises(f.lifecycle.BridgeError) as error:
        getattr(f.lifecycle, tool)(f.context, params)
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
    if tool == "zone_item_convert":
        assert f.item.socket_type == "INT" and f.source.inputs[-1].default_value == 4 and f.output.inputs[0].default_value == 8
    else:
        assert f.socket.name == "Renamed"


def test_guard_detects_same_count_zone_type_domain_pairing_changes(lifecycle):
    f = lifecycle
    before = f.module._graph_guard(f.root)
    f.item.attribute_domain = "FACE"
    assert f.module._graph_guard(f.root) != before
    f.item.attribute_domain = "POINT"
    f.source.paired_output = None
    assert f.module._graph_guard(f.root) != before


def test_shared_parent_requires_acknowledgement_and_preserves_instance_values(lifecycle):
    f = lifecycle
    parent = tree("Parent")
    instance_socket = NS(name="Width", identifier="Socket_1", type="VALUE", default_value=15.)
    parent.nodes.append(node("Nested", "GeometryNodeGroup", node_tree=f.root, inputs=Items([instance_socket])))
    f.bpy.data.node_groups.append(parent)
    f.user_map[f.root].add(parent)
    f.user_map[parent] = {f.obj}
    params = {"group_name": "Graph", "socket_identifier": "Socket_1", "operation": "SET_DEFAULT", "value": 4.}
    with pytest.raises(f.lifecycle.BridgeError):
        f.lifecycle.interface_edit(f.context, params)
    result = f.lifecycle.interface_edit(f.context, {**params, "allow_shared": True})
    assert result["existing_consumer_values_preserved"] and instance_socket.default_value == 15.


def typed_modifier(f):
    def rna(**fields):
        return NS(bl_rna=NS(properties={"rna_type": NS(), "name": NS(), **{key: NS() for key in fields}}), **fields)

    field = rna(value=2., type="VALUE", attribute_name="")
    f.modifier.properties = NS(bl_rna=NS(properties={key: NS() for key in ("rna_type", "inputs", "outputs", "panels")}),
        inputs=rna(Socket_1=field, Socket_2=rna(value=3., type="VALUE", attribute_name="")), outputs=rna(), panels=rna())
    return field


def test_typed_modifier_storage_sets_constant_and_preserves_attribute_mode(lifecycle):
    f = lifecycle
    field = typed_modifier(f)
    result = f.module.modifier_set_input(f.context, {"object_name": "Object", "modifier_name": "Procedural", "socket_identifier": "Socket_1", "value": 7.5})
    assert result["value"] == field.value == 7.5
    field.type, field.attribute_name = "ATTRIBUTE", "protected_attribute"
    with pytest.raises(f.module.BridgeError) as error:
        f.module.modifier_set_input(f.context, {"object_name": "Object", "modifier_name": "Procedural", "socket_identifier": "Socket_1", "value": 8.})
    assert error.value.code == "NOT_IMPLEMENTED" and field.value == 7.5
    summary = f.module.modifier_inspect(f.context, {"object_name": "Object", "modifier_name": "Procedural"})
    assert summary["inputs"][0]["use_attribute"] and summary["inputs"][0]["attribute_name"] == "protected_attribute"


@pytest.mark.parametrize("malformed", ["unknown_container", "missing_identifier", "unknown_identifier", "unknown_field", "unknown_mode", "missing_value", "missing_container", "panel"])
def test_typed_modifier_storage_fails_closed_on_unreviewed_native_shapes(lifecycle, malformed):
    f = lifecycle
    field = typed_modifier(f)
    if malformed == "unknown_container":
        f.modifier.properties.bl_rna.properties["unknown"] = NS()
    elif malformed == "missing_identifier":
        del f.modifier.properties.inputs.bl_rna.properties["Socket_1"]
    elif malformed == "unknown_identifier":
        f.modifier.properties.inputs.bl_rna.properties["Socket_999"] = NS()
    elif malformed == "unknown_field":
        field.bl_rna.properties["external_source"] = NS()
    elif malformed == "unknown_mode":
        field.type = "LAYER_SELECTION"
    elif malformed == "missing_value":
        del field.bl_rna.properties["value"]
    elif malformed == "missing_container":
        f.modifier.properties = None
    else:
        f.root.interface.items_tree.append(NS(item_type="PANEL"))
    with pytest.raises(f.module.BridgeError):
        f.module._modifier_properties(f.modifier)
    assert field.value == 2.


def test_legacy_modifier_type_error_is_never_replaced_by_empty_evidence(lifecycle):
    class Malformed(dict):
        def keys(self):
            raise TypeError("Malformed existing properties")

    with pytest.raises(TypeError, match="Malformed existing properties"):
        lifecycle.module._modifier_properties(Malformed(Socket_1=8.))


def test_move_rejects_unexpected_relative_order_of_other_peers(lifecycle, monkeypatch):
    f = lifecycle
    for number in (3, 4):
        f.root.interface.items_tree.append(NS(name="Input " + str(number), identifier="Socket_" + str(number),
            item_type="SOCKET", in_out="INPUT", socket_type="NodeSocketFloat", default_value=float(number)))
    original_move = f.root.interface.move

    def faulty_move(item, position):
        original_move(item, position)
        # Requested item still reaches index1, but another peer is reordered.
        f.root.interface.items_tree[0], f.root.interface.items_tree[-1] = f.root.interface.items_tree[-1], f.root.interface.items_tree[0]

    monkeypatch.setattr(f.root.interface, "move", faulty_move)
    with pytest.raises(f.lifecycle.BridgeError):
        f.lifecycle.interface_edit(f.context, {"group_name": "Graph", "socket_identifier": "Socket_1", "operation": "MOVE", "to_index": 1})
