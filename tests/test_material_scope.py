from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


class ID:
    def __init__(self, name, kind="Mesh", **values):
        self.name = name
        self.bl_rna = SimpleNamespace(identifier=kind)
        self.library = None
        self.override_library = None
        self.is_editable = True
        self.__dict__.update(values)


@pytest.fixture
def scope_fixture(addon_package):
    module = importlib.import_module(f"{addon_package}.tools.material_scope")
    material = ID("Paint", "Material", users=1, node_tree=ID("Shader", "ShaderNodeTree"))
    mesh = ID("Mesh")
    obj = ID("Cube", "Object", mode="OBJECT", material_slots=[SimpleNamespace(material=material)])
    owners = {mesh}
    objects = [obj]
    bpy = SimpleNamespace(
        data=SimpleNamespace(user_map=lambda **kwargs: {material: owners}, objects=objects)
    )
    return module, bpy, material, owners, objects


def test_shared_mesh_detected_even_with_one_material_reference(scope_fixture):
    module, bpy, material, _, objects = scope_fixture
    objects.append(ID("Protected", "Object", material_slots=objects[0].material_slots))
    with pytest.raises(module.BridgeError, match="allow_shared"):
        module.editable_material_scope(bpy, material, {})
    evidence = module.editable_material_scope(bpy, material, {"allow_shared": True})
    assert evidence["affected_objects"] == ["Cube", "Protected"]
    assert evidence["material_users"] == 1


@pytest.mark.parametrize(
    "field,value", [("library", object()), ("override_library", object()), ("is_editable", False)]
)
@pytest.mark.parametrize("target", ["material", "tree"])
def test_linked_override_or_readonly_never_armed(scope_fixture, field, value, target):
    module, bpy, material, _, _ = scope_fixture
    setattr(material if target == "material" else material.node_tree, field, value)
    with pytest.raises(module.BridgeError, match="local"):
        module.editable_material_scope(bpy, material, {"allow_shared": True})


def test_node_group_reference_requires_acknowledgement(scope_fixture):
    module, bpy, material, owners, _ = scope_fixture
    owners.clear()
    owners.add(ID("Procedural", "GeometryNodeTree"))
    with pytest.raises(module.BridgeError, match="allow_shared"):
        module.editable_material_scope(bpy, material, {})
    evidence = module.editable_material_scope(bpy, material, {"allow_shared": True})
    assert evidence["indirect_users_possible"]
    assert evidence["direct_users"][0]["name"] == "Procedural"


def test_scope_limit_cannot_be_overridden(scope_fixture):
    module, bpy, material, owners, _ = scope_fixture
    owners.update(ID(str(i)) for i in range(101))
    with pytest.raises(module.BridgeError, match="limit"):
        module.editable_material_scope(bpy, material, {"allow_shared": True})
    evidence, _ = module.material_scope(bpy, material)
    assert evidence["direct_user_count"] == 102
    assert len(evidence["direct_users"]) == 100 and evidence["direct_users_truncated"]


@pytest.mark.parametrize("allow", [1, "true", None, []])
def test_consent_is_strict_boolean(scope_fixture, allow):
    module, bpy, material, _, _ = scope_fixture
    with pytest.raises(module.BridgeError, match="boolean"):
        module.editable_material_scope(bpy, material, {"allow_shared": allow})


@pytest.mark.parametrize(
    "handler",
    ["add_node", "remove_node", "rename_node", "set_node_input", "link_nodes", "unlink_nodes"],
)
def test_every_shader_mutator_checks_ownership_first(
    scope_fixture, addon_package, monkeypatch, handler
):
    module, bpy, material, _, objects = scope_fixture
    objects.append(ID("Protected", material_slots=objects[0].material_slots))
    nodes = importlib.import_module(f"{addon_package}.tools.nodes")
    monkeypatch.setattr(nodes, "require_blender", lambda: bpy)
    monkeypatch.setattr(nodes, "_material_graph", lambda _: (material, material.node_tree))
    with pytest.raises(module.BridgeError, match="allow_shared"):
        getattr(nodes, handler)(None, {"material_name": "Paint"})


def test_forced_unlink_rejects_nonlocal_owner(scope_fixture):
    module, bpy, material, owners, _ = scope_fixture
    next(iter(owners)).library = object()
    with pytest.raises(module.BridgeError, match="Forced unlink"):
        module.editable_material_scope(bpy, material, {"allow_shared": True}, unlink=True)


def test_forced_unlink_checks_actual_object_not_name_lookup(scope_fixture):
    module, bpy, material, _, objects = scope_fixture
    objects.append(
        ID(
            "Cube",
            "Object",
            library=object(),
            mode="EDIT",
            material_slots=objects[0].material_slots,
        )
    )
    with pytest.raises(module.BridgeError, match="Object Mode"):
        module.editable_material_scope(bpy, material, {"allow_shared": True}, unlink=True)


def test_duplicate_material_names_are_ambiguous(scope_fixture):
    module, bpy, material, _, _ = scope_fixture
    bpy.data.materials = [material, ID("Paint", "Material", library=object())]
    with pytest.raises(module.BridgeError, match="ambiguous"):
        module.material_exact(bpy, "Paint")


def test_material_usage_uses_identity_not_name(scope_fixture, addon_package):
    _, bpy, material, _, objects = scope_fixture
    materials = importlib.import_module(f"{addon_package}.tools.materials")
    linked = ID("Paint", "Material", library=object())
    objects.append(ID("Other", material_slots=[SimpleNamespace(material=linked)]))
    usage = materials._material_usage(bpy, {material, linked})
    assert usage[material]["objects"] == ["Cube"]
    assert usage[linked]["objects"] == ["Other"]


def test_object_scope_truncation_is_explicit_and_blocks_mutation(scope_fixture):
    module, bpy, material, _, objects = scope_fixture
    objects.extend(ID(str(i), material_slots=objects[0].material_slots) for i in range(100))
    with pytest.raises(module.BridgeError, match="limit"):
        module.editable_material_scope(bpy, material, {"allow_shared": True})
    evidence, _ = module.material_scope(bpy, material)
    assert evidence["affected_object_count"] == 101
    assert len(evidence["affected_objects"]) == 100 and evidence["affected_objects_truncated"]
