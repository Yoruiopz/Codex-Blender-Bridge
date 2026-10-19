from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


class ID:
    def __init__(self, name, kind="ShaderNodeTree", **values):
        self.name, self.bl_rna = name, NS(identifier=kind)
        self.bl_idname = kind
        self.library, self.override_library, self.is_editable = None, None, True
        self.users, self.use_fake_user = 1, False
        self.__dict__.update(values)


class Nodes(list):
    def get(self, name):
        return next((node for node in self if node.name == name), None)


def tree(name):
    return ID(name, nodes=Nodes(), links=[])


@pytest.fixture
def shader(addon_package):
    module = importlib.import_module(f"{addon_package}.tools.shader_scope")
    root, parent, child = tree("Root"), tree("Parent"), tree("Child")
    root.nodes.append(ID("Outer", "ShaderNodeGroup", node_tree=parent))
    parent.nodes.append(ID("Inner", "ShaderNodeGroup", node_tree=child))
    material = ID("Material", "Material", node_tree=root)
    mesh = ID("Mesh", "Mesh")
    obj = ID("Cube", "Object", material_slots=[NS(material=material)])
    users = {child: {parent}, parent: {material}, material: {mesh}}
    bpy = NS(context=NS(mode="OBJECT"), data=NS(objects=[obj], node_groups=[parent, child],
                user_map=lambda **kw: {key: users.get(key, set()) for key in kw["subset"]}))
    return module, bpy, material, parent, child, users


def test_nested_path_and_transitive_single_owner(shader):
    module, bpy, mat, _, child, _ = shader
    assert module.resolve(bpy, mat, {"group_path": ["Outer", "Inner"]}, modify=True) is child
    result = module.ownership(bpy, child)
    assert result["coverage_complete"] and not result["requires_shared_consent"]
    assert result["affected_objects"] == ["Cube"]
    assert result["parent_groups"] == ["Child", "Parent"]
    assert result["materials"][0]["name"] == "Material"


def test_shared_material_objects_detected_through_parent_groups(shader):
    module, bpy, mat, _, child, _ = shader
    bpy.data.objects.append(ID("Protected", "Object", material_slots=[NS(material=mat)]))
    with pytest.raises(module.BridgeError, match="allow_shared"):
        module.editable(bpy, child, {})
    result = module.editable(bpy, child, {"allow_shared": True})
    assert result["affected_objects"] == ["Cube", "Protected"]
    assert child.users == 1


def test_other_material_and_world_owner_are_explicit(shader):
    module, bpy, _, parent, child, users = shader
    other = ID("Other", "Material", node_tree=tree("Other Root"))
    world = ID("World", "World")
    users[parent].add(other)
    users[child].add(world)
    result = module.ownership(bpy, child)
    assert result["requires_shared_consent"] and result["coverage_complete"]
    assert [m["name"] for m in result["materials"]] == ["Material", "Other"]
    assert result["other_owners"] == [{"name": "World", "type": "World", "local_editable": True}]


@pytest.mark.parametrize("value", ["Outer", ("Outer",), True, ["Outer"] * 9, [None], ["a\nb"], ["é" * 32], ["\ud800"]])
def test_invalid_paths(shader, value):
    module, bpy, mat, *_ = shader
    with pytest.raises(module.BridgeError) as error:
        module.resolve(bpy, mat, {"group_path": value}, modify=True)
    assert error.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("change", ["missing", "unbound", "wrong_node", "wrong_tree", "recursive", "large"])
def test_bad_path_does_not_guess(shader, change):
    module, bpy, mat, parent, child, _ = shader
    path = ["Outer", "Inner"]
    if change == "missing":
        path[1] = "Similar"
    elif change == "unbound":
        parent.nodes[0].node_tree = None
    elif change == "wrong_node":
        parent.nodes[0].bl_idname = "ShaderNodeMath"
    elif change == "wrong_tree":
        child.bl_idname = "GeometryNodeTree"
    elif change == "recursive":
        parent.nodes[0].node_tree = mat.node_tree
    else:
        parent.nodes.extend(ID(str(i)) for i in range(256))
    with pytest.raises(module.BridgeError):
        module.resolve(bpy, mat, {"group_path": path}, modify=True)


@pytest.mark.parametrize("target", ["tree", "parent", "material", "world"])
def test_linked_override_or_readonly_owners_cannot_be_armed(shader, target):
    module, bpy, mat, parent, child, users = shader
    if target == "tree":
        child.library = object()
    elif target == "parent":
        parent.override_library = object()
    elif target == "material":
        mat.is_editable = False
    else:
        users[child].add(ID("Linked World", "World", library=object()))
    with pytest.raises(module.BridgeError) as error:
        module.resolve(bpy, mat, {"group_path": ["Outer", "Inner"], "allow_shared": True}, modify=True)
    assert error.value.code == "NOT_IMPLEMENTED"


def test_object_mode_needed_only_for_nested_mutations(shader):
    module, bpy, mat, _, child, _ = shader
    bpy.context.mode = "EDIT_MESH"
    assert module.resolve(bpy, mat, {"group_path": ["Outer", "Inner"]}) is child
    assert module.resolve(bpy, mat, {"group_path": []}, modify=True) is mat.node_tree
    with pytest.raises(module.BridgeError, match="Object Mode"):
        module.resolve(bpy, mat, {"group_path": ["Outer"]}, modify=True)


def test_group_name_ambiguity_is_not_resolved_by_first_match(shader):
    module, bpy, _, _, child, _ = shader
    assert module.group_exact(bpy, "Child") is child
    bpy.data.node_groups.append(tree("Child"))
    with pytest.raises(module.BridgeError, match="ambiguity"):
        module.group_exact(bpy, "Child")


def test_owner_budget_is_incomplete_and_blocks_mutation(shader):
    module, bpy, _, _, child, users = shader
    users[child] = {ID(str(i), "World") for i in range(101)}
    result = module.ownership(bpy, child)
    assert not result["coverage_complete"] and result["direct_users_truncated"]
    assert len(result["direct_users"]) == 100 and result["direct_user_count"] == 101
    with pytest.raises(module.BridgeError, match="budget"):
        module.editable(bpy, child, {"allow_shared": True})


def test_repeated_parent_owner_is_deduplicated_not_false_truncated(shader):
    module, bpy, mat, _, child, users = shader
    parents = {tree(f"Parent{i}") for i in range(31)}
    users[child] = parents
    for parent in parents:
        users[parent] = {mat}
    result = module.ownership(bpy, child)
    assert result["coverage_complete"] and len(result["parent_groups"]) == 32
    assert len(result["materials"]) == 1


def test_material_objects_are_scanned_once_and_same_named_users_still_need_consent(shader):
    module, bpy, mat, parent, child, users = shader
    other = ID("Other", "Material", node_tree=tree("Other Root"))
    users[parent].add(other)
    class Objects(list):
        traversals = 0
        def __iter__(self):
            self.traversals += 1
            return super().__iter__()
    bpy.data.objects = Objects([*bpy.data.objects, ID("Cube", "Object", material_slots=[NS(material=mat), NS(material=other)])])
    result = module.ownership(bpy, child)
    assert bpy.data.objects.traversals == 1
    assert result["requires_shared_consent"] and result["materials"][0]["affected_object_count"] == 2
    users[parent].remove(other)
    assert module.ownership(bpy, child)["requires_shared_consent"]


def test_parent_group_budget_and_cancellation(shader):
    module, bpy, mat, _, child, users = shader
    current = child
    for i in range(33):
        parent = tree(f"Parent{i}")
        users[current] = {parent}
        current = parent
    users[current] = {mat}
    assert module.ownership(bpy, child)["incomplete_reasons"] == ["parent_group_budget"]
    def cancelled():
        raise module.BridgeError("TIMEOUT", "Canceled")
    with pytest.raises(module.BridgeError, match="Canceled"):
        module.ownership(bpy, child, cancelled)
