from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.nodes import NodeTools, load_definitions
from mcp_server.tools.shader_groups import GroupPath, ShaderGroupTools


class Items(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Nodes(Items):
    def new(self, kind):
        node = NS(name=kind, bl_idname=kind, node_tree=None, image=None)
        self.append(node)
        return node


class Interface:
    def __init__(self):
        self.items_tree = []

    def new_socket(self, *, name, in_out, socket_type):
        item = NS(name=name, in_out=in_out, socket_type=socket_type, item_type="SOCKET", identifier=f"Socket_{len(self.items_tree)}")
        if socket_type != "NodeSocketShader":
            item.default_value = {"NodeSocketFloat": 0., "NodeSocketInt": 0, "NodeSocketBool": False,
                                  "NodeSocketVector": [0., 0., 0.], "NodeSocketColor": [0., 0., 0., 1.]}[socket_type]
        self.items_tree.append(item)
        return item

    def remove(self, item):
        self.items_tree.remove(item)


class Tree:
    def __init__(self, name, collection):
        self.name, self.bl_idname, self.bl_rna = name, "ShaderNodeTree", NS(identifier="ShaderNodeTree")
        self.nodes, self.links, self.interface = Nodes(), [], Interface()
        self.library, self.override_library, self.is_editable = None, None, True
        self.users, self.use_fake_user, self.collection = 0, False, collection

    def copy(self):
        tree = self.collection.new(self.name + ".001", "ShaderNodeTree")
        tree.nodes.extend(self.nodes)
        return tree


class Groups(Items):
    def new(self, name, kind):
        assert kind == "ShaderNodeTree"
        tree = Tree(name, self)
        self.append(tree)
        return tree

    def remove(self, item, *, do_unlink):
        assert do_unlink is False and item.users == 0
        super().remove(item)


class Instance:
    def __init__(self):
        self.name, self.bl_idname = "Instance", "ShaderNodeGroup"
        self._tree, self.inputs, self.fail_once = None, [], False

    @property
    def node_tree(self):
        return self._tree

    @node_tree.setter
    def node_tree(self, value):
        if self._tree:
            self._tree.users -= 1
        self._tree = value
        if value:
            value.users += 1
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("Injected failure after pointer write")


@pytest.fixture
def fixture(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.shader_groups")
    node_module = importlib.import_module(f"{addon_package}.tools.nodes")
    groups = Groups()
    root = Tree("Root", groups)
    original = groups.new("Original", "ShaderNodeTree")
    instance = Instance()
    instance.node_tree = original
    original.users += 1  # Another independent user, never edited by isolation.
    root.nodes.append(instance)
    material = NS(name="Material", node_tree=root)
    bpy = NS(context=NS(mode="OBJECT"), data=NS(node_groups=groups, user_map=lambda **_: {}))
    context = NS(check_cancelled=None, require=lambda *_: None)
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(node_module, "_target_graph", lambda *_args, **_kw: (material, root))
    monkeypatch.setattr(node_module, "_post_state", lambda *_args: {"material": material.name, "node_tree": root.name})
    return module, bpy, context, groups, root, original, instance


def test_create_inspect_and_unused_remove(fixture):
    module, _, context, groups, _, _, _ = fixture
    result = module.create(context, {"group_name": "New"})
    assert result["created"] and len(groups.get("New").nodes) == 2
    for confirm in (False, "true"):
        with pytest.raises(module.BridgeError):
            module.remove(context, {"group_name": "New", "confirm_unused": confirm})
    result = module.remove(context, {"group_name": "New", "confirm_unused": True})
    assert groups.get("New") is None and not result["nested_data_removed"] and not result["file_deleted"]


def test_create_failure_removes_only_its_new_group(fixture, monkeypatch):
    module, _, context, groups, _, original, _ = fixture
    def fail(*_args):
        raise RuntimeError("node creation failed")
    monkeypatch.setattr(Nodes, "new", fail)
    with pytest.raises(module.BridgeError) as error:
        module.create(context, {"group_name": "New"})
    assert error.value.context["rollback_verified"] and list(groups) == [original]


@pytest.mark.parametrize("kind,value", [("NodeSocketFloat", .4), ("NodeSocketInt", 12), ("NodeSocketBool", True),
    ("NodeSocketVector", [1., 2., 3.]), ("NodeSocketColor", [.1, .2, .3, 1.])])
def test_interface_add_typed_default_and_collision(fixture, kind, value):
    module, _, context, _, _, _, _ = fixture
    module.create(context, {"group_name": "New"})
    params = {"group_name": "New", "name": "Input", "socket_type": kind, "default_value": value}
    result = module.interface_add(context, params)
    assert result["interface"][0]["default_value"] == value
    with pytest.raises(module.BridgeError, match="already"):
        module.interface_add(context, params)


def test_interface_failure_does_not_claim_global_rollback(fixture):
    module, _, context, groups, _, _, _ = fixture
    module.create(context, {"group_name": "New"})
    with pytest.raises(module.BridgeError) as error:
        module.interface_add(context, {"group_name": "New", "name": "Bad", "default_value": "not float"})
    assert not groups.get("New").interface.items_tree
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]


def test_group_copy_preserves_original_and_instance_defaults(fixture):
    module, _, context, groups, _, original, instance = fixture
    instance.inputs = [NS(identifier="Input", name="Input", default_value=.37)]
    result = module.copy_for_node(context, {"material_name": "Material", "node_name": "Instance", "new_name": "Copy"})
    assert result["copied_from"] == "Original" and not result["nested_data_copied"]
    assert instance.node_tree is groups.get("Copy") and original.users == 1
    assert instance.inputs[0].default_value == .37


@pytest.mark.parametrize("failure", ["setter", "cancel", "unexpected_users"])
def test_group_copy_failure_retains_measured_recovery(fixture, failure):
    module, _, context, groups, _, original, instance = fixture
    if failure == "setter":
        instance.fail_once = True
    else:
        def check():
            if instance.node_tree.name == "Copy":
                if failure == "cancel":
                    raise module.BridgeError("TIMEOUT", "Canceled")
                instance.node_tree.users += 1
        context.check_cancelled = check
    with pytest.raises(module.BridgeError) as error:
        module.copy_for_node(context, {"material_name": "Material", "node_name": "Instance", "new_name": "Copy"})
    assert instance.node_tree is original and original.users == 2
    assert error.value.context["rollback_verified"] is (failure != "unexpected_users")
    assert (groups.get("Copy") is not None) is (failure == "unexpected_users")


def test_group_binding_requires_clear_and_no_incident_links(fixture):
    module, _, context, groups, root, original, instance = fixture
    other = groups.new("Other", "ShaderNodeTree")
    with pytest.raises(module.BridgeError, match="clear"):
        module.bind(context, {"material_name": "Material", "node_name": "Instance", "group_name": "Other"})
    module.bind(context, {"material_name": "Material", "node_name": "Instance", "group_name": None})
    assert instance.node_tree is None and original.users == 1
    module.bind(context, {"material_name": "Material", "node_name": "Instance", "group_name": "Other"})
    assert instance.node_tree is other
    root.links.append(NS(from_node=instance, to_node=NS(name="Output")))
    with pytest.raises(module.BridgeError, match="unlinked"):
        module.bind(context, {"material_name": "Material", "node_name": "Instance", "group_name": None})


@pytest.mark.parametrize("bad", ["recursive_target", "recursive_dependency", "script", "ies", "linked"])
def test_dependency_review_rejects_unsafe_groups(fixture, bad):
    module, _, context, groups, root, original, instance = fixture
    if bad == "recursive_target":
        original.nodes.append(NS(bl_idname="ShaderNodeGroup", node_tree=root))
    elif bad == "recursive_dependency":
        original.nodes.append(NS(bl_idname="ShaderNodeGroup", node_tree=original))
    elif bad in {"script", "ies"}:
        original.nodes.append(NS(bl_idname="ShaderNodeScript" if bad == "script" else "ShaderNodeTexIES"))
    else:
        original.library = object()
    with pytest.raises(module.BridgeError):
        module.copy_for_node(context, {"material_name": "Material", "node_name": "Instance", "new_name": "Copy"})
    assert len(groups) == 1 and instance.node_tree is original


def test_dependency_file_permission_is_not_bypassed(fixture, addon_package, monkeypatch):
    module, _, context, groups, _, original, instance = fixture
    image = NS(name="Image")
    original.nodes.append(NS(bl_idname="ShaderNodeTexImage", image=image))
    images = importlib.import_module(f"{addon_package}.tools.images")
    calls = []
    def denied(_context, target):
        calls.append(target)
        raise module.BridgeError("PERMISSION_DENIED", "External files disabled")
    monkeypatch.setattr(images, "binding_source", denied)
    with pytest.raises(module.BridgeError) as error:
        module.copy_for_node(context, {"material_name": "Material", "node_name": "Instance", "new_name": "Copy"})
    assert error.value.code == "PERMISSION_DENIED" and calls == [image]
    assert len(groups) == 1 and instance.node_tree is original


def test_group_mcp_metadata_strict_paths_and_forwarding(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools.shader_groups").register_tools(registry)
    definitions = {d.name: d for d in load_definitions()}
    for tool_name in registry.list_tools():
        spec = registry.get(tool_name)
        assert spec.toolset == "nodes" and spec.modifies == definitions[tool_name].modifying
        assert {p.value for p in spec.permissions} == set(definitions[tool_name].required_permissions)
    for value in ([1], ["a"] * 9, "group"):
        with pytest.raises(ValidationError):
            TypeAdapter(GroupPath).validate_python(value)
    for method, field, value in ((ShaderGroupTools.shader_group_remove, "confirm_unused", 1),
                                (ShaderGroupTools.shader_group_bind, "allow_shared", "yes")):
        with pytest.raises(ValidationError):
            TypeAdapter(get_type_hints(method, include_extras=True)[field]).validate_python(value)
    calls = []
    class Recording:
        async def call(self, method, arguments):
            calls.append((method, arguments))
            return {}
    asyncio.run(ShaderGroupTools(Recording()).shader_group_bind("M", "Node", None, group_path=["Outer"]))
    assert calls[0][1]["group_name"] is None and calls[0][1]["group_path"] == ["Outer"]
    asyncio.run(NodeTools(Recording()).nodes_set_input("M", "N", "V", .5, group_path=["Outer", "Inner"]))
    assert calls[1][1]["group_path"] == ["Outer", "Inner"]
