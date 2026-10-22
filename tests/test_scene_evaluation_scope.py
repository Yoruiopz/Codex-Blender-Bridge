"""The Scene adapter may project only its explicitly owned native effects."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace as NS

import pytest


class NativeID:
    def __init__(self, pointer, name):
        self.pointer, self.session_uid, self.name = pointer, pointer + 1000, name

    def as_pointer(self):
        return self.pointer


def token(owner):
    return owner.as_pointer(), owner.session_uid


def main_id(owner, kind):
    return token(owner), kind, owner.name


def graph_owner(owner, kind, *bindings):
    return (token(owner), owner.name, kind), tuple(bindings)


def tree(owner, nodes=1, links=0, interface=0):
    return ((token(owner), owner.name, "ShaderNodeTree"),
            tuple((index, "ShaderNodeValue", f"Node {index}", (None, None)) for index in range(nodes)),
            tuple((index, 1, 2, 3, 4) for index in range(links)),
            tuple((index, "SOCKET", "NodeSocketFloat") for index in range(interface)))


def snapshot(main_ids, owners, trees):
    return (tuple(main_ids), tuple(owners), tuple(trees),
            tuple(sum(len(record[index]) for record in trees) for index in (1, 2, 3)))


@pytest.fixture
def case(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools._scene_evaluation_scope")
    scene, other_scene = NativeID(1, "Scene"), NativeID(2, "Other Scene")
    world, other_world = NativeID(10, "World"), NativeID(11, "Other World")
    material, collection = NativeID(20, "Material"), NativeID(30, "Collection")
    world_tree, other_tree, material_tree = (NativeID(100, "World Tree"),
                                             NativeID(110, "Other Tree"), NativeID(120, "Material Tree"))
    empty = (None, None)
    initial = snapshot(
        (main_id(scene, "Scene"), main_id(other_scene, "Scene"), main_id(world, "World"),
         main_id(other_world, "World"), main_id(material, "Material"), main_id(collection, "Collection")),
        (graph_owner(scene, "Scene", ("node_tree", empty), ("compositing_node_group", empty), ("world", token(world))),
         graph_owner(other_scene, "Scene", ("node_tree", empty), ("compositing_node_group", empty), ("world", token(other_world))),
         graph_owner(world, "World", ("node_tree", token(world_tree))),
         graph_owner(other_world, "World", ("node_tree", token(other_tree))),
         graph_owner(material, "Material", ("node_tree", token(material_tree)))),
        (tree(world_tree, 2, 1), tree(other_tree, 3, 2, 1), tree(material_tree, 1, 0, 2)),
    )
    current, calls = [initial], []
    bpy = object()

    def native_snapshot(argument):
        calls.append(argument)
        return current[0]

    monkeypatch.setattr(module.native, "snapshot", native_snapshot)
    return NS(module=module, scene=scene, other_scene=other_scene, world=world,
              other_world=other_world, material=material, collection=collection,
              world_tree=world_tree, other_tree=other_tree, material_tree=material_tree,
              initial=initial, current=current, calls=calls, bpy=bpy)


def replace_main(case, old, new):
    main, owners, trees, _ = case.current[0]
    case.current[0] = snapshot(tuple(new if record == old else record for record in main), owners, trees)


def replace_binding(case, owner, field, new):
    main, owners, trees, _ = case.current[0]
    updated = []
    for identity, bindings in owners:
        if identity[0] == token(owner):
            bindings = tuple((key, new if key == field else value) for key, value in bindings)
        updated.append((identity, bindings))
    case.current[0] = snapshot(main, updated, trees)


def replace_tree(case, owner, *, nodes=1, links=0, interface=0):
    main, owners, trees, _ = case.current[0]
    updated = tuple(tree(owner, nodes, links, interface) if record[0][0] == token(owner) else record for record in trees)
    case.current[0] = snapshot(main, owners, updated)


def test_default_adapter_preserves_donor_and_calls_it_once_without_options(case):
    before = repr(case.initial)
    adapter = case.module.Scope(case.bpy, case.scene, "scene.configure")
    assert adapter() == case.initial
    assert case.calls == [case.bpy]
    assert repr(case.initial) == before


@pytest.mark.parametrize("method", ["collection.create", "collection.rename", "collection.delete"])
def test_only_exact_declared_collection_identity_is_projected(case, method):
    adapter = case.module.Scope(case.bpy, case.scene, method, collection_identity=lambda: token(case.collection))
    baseline = adapter()
    main, owners, trees, _ = case.initial
    case.current[0] = snapshot(tuple(record for record in main if record[0] != token(case.collection)), owners, trees)
    assert adapter() == baseline
    other = NativeID(31, "Collection")
    case.current[0] = snapshot((*case.current[0][0], main_id(other, "Collection")), owners, trees)
    assert adapter() != baseline


def test_collection_same_name_different_session_and_unrelated_renames_remain_visible(case):
    adapter = case.module.Scope(case.bpy, case.scene, "collection.rename", collection_identity=lambda: token(case.collection))
    baseline = adapter()
    record = main_id(case.collection, "Collection")
    replace_main(case, record, ((record[0][0], record[0][1] + 1), "Collection", record[2]))
    assert adapter() != baseline
    case.current[0] = case.initial
    record = main_id(case.material, "Material")
    replace_main(case, record, (record[0], record[1], "Artist Renamed Material"))
    assert adapter() != baseline


@pytest.mark.parametrize("method", ["scene.configure", "world.configure", "camera.configure", "light.configure", "unknown.method"])
def test_wrong_domain_does_not_project_collection_ids(case, method):
    adapter = case.module.Scope(case.bpy, case.scene, method, collection_identity=lambda: token(case.collection))
    baseline = case.module.Scope(case.bpy, case.scene, method)()
    assert adapter() == baseline
    assert main_id(case.collection, "Collection") in adapter()[0]


def test_scene_world_binding_projection_is_limited_to_requested_scene(case):
    adapter = case.module.Scope(case.bpy, case.scene, "world.configure")
    baseline = adapter()
    replace_binding(case, case.scene, "world", token(case.other_world))
    assert adapter() == baseline
    replace_binding(case, case.other_scene, "world", token(case.world))
    assert adapter() != baseline


@pytest.mark.parametrize("method", ["scene.configure", "camera.configure", "light.configure", "collection.rename"])
def test_other_domains_preserve_scene_world_bindings(case, method):
    adapter = case.module.Scope(case.bpy, case.scene, method)
    baseline = adapter()
    replace_binding(case, case.scene, "world", token(case.other_world))
    assert adapter() != baseline


def test_read_only_world_getter_does_not_project_world_tree_content(case):
    adapter = case.module.Scope(case.bpy, case.scene, "world.configure", world_getter=lambda: case.world)
    baseline = adapter()
    replace_tree(case, case.world_tree, nodes=5, links=2)
    assert adapter() != baseline


def test_only_requested_mutable_world_tree_is_projected(case):
    adapter = case.module.Scope(case.bpy, case.scene, "world.configure",
                                world_getter=lambda: case.world, edit_world=True)
    baseline = adapter()
    replace_tree(case, case.world_tree, nodes=5, links=4, interface=3)
    assert adapter() == baseline
    replace_tree(case, case.other_tree, nodes=4, links=2, interface=1)
    assert adapter() != baseline


def test_world_tree_projection_keeps_sibling_bindings_and_unrelated_tree_additions(case):
    adapter = case.module.Scope(case.bpy, case.scene, "world.configure",
                                world_getter=lambda: case.world, edit_world=True)
    baseline = adapter()
    replace_binding(case, case.other_world, "node_tree", token(case.material_tree))
    assert adapter() != baseline
    case.current[0] = case.initial
    main, owners, trees, _ = case.initial
    extra = NativeID(130, "Unrelated New Tree")
    case.current[0] = snapshot(main, owners, (*trees, tree(extra, 2, 1)))
    assert adapter() != baseline


def test_edit_world_does_not_ignore_existing_world_name_or_new_standalone_id(case):
    adapter = case.module.Scope(case.bpy, case.scene, "world.configure",
                                world_getter=lambda: case.world, edit_world=True)
    baseline = adapter()
    record = main_id(case.world, "World")
    replace_main(case, record, (record[0], "World", "Artist World Name"))
    assert adapter() != baseline
    case.current[0] = case.initial
    main, owners, trees, _ = case.initial
    case.current[0] = snapshot((*main, main_id(case.world_tree, "ShaderNodeTree")), owners, trees)
    assert adapter() != baseline


def test_new_world_normalizes_only_exact_owned_id_owner_and_embedded_tree(case):
    allocated = [None]
    adapter = case.module.Scope(case.bpy, case.scene, "world.configure", world_getter=lambda: allocated[0], new_world=True)
    baseline = adapter()
    world, embedded = NativeID(40, "Owned New World"), NativeID(140, "Owned Embedded Tree")
    allocated[0] = world
    main, owners, trees, _ = case.initial
    case.current[0] = snapshot((*main, main_id(world, "World")),
                              (*owners, graph_owner(world, "World", ("node_tree", token(embedded)))),
                              (*trees, tree(embedded, 2, 1)))
    replace_binding(case, case.scene, "world", token(world))
    assert adapter() == baseline
    extra = NativeID(41, "Unrelated World")
    main, owners, trees, _ = case.current[0]
    case.current[0] = snapshot((*main, main_id(extra, "World")), owners, trees)
    assert adapter() != baseline


def test_new_world_does_not_exclude_other_id_with_same_pointer_different_session(case):
    adapter = case.module.Scope(case.bpy, case.scene, "world.configure", world_getter=lambda: case.world, new_world=True)
    baseline = adapter()
    record = main_id(case.world, "World")
    replace_main(case, record, ((record[0][0], record[0][1] + 1), "World", record[2]))
    assert adapter() != baseline


@pytest.mark.parametrize("method", ["scene.configure", "camera.configure", "light.configure", "collection.create", "unknown.method"])
@pytest.mark.parametrize("flag", ["new_world", "edit_world"])
def test_wrong_domain_world_flags_preserve_complete_native_snapshot(case, method, flag):
    adapter = case.module.Scope(case.bpy, case.scene, method, world_getter=lambda: case.world, **{flag: True})
    assert adapter() == case.initial


def test_projected_totals_are_recomputed_only_from_retained_trees(case):
    adapter = case.module.Scope(case.bpy, case.scene, "world.configure", world_getter=lambda: case.world, edit_world=True)
    projected = adapter()
    assert projected[3] == (4, 2, 3)
    assert case.initial[3] == (6, 3, 3)
    assert repr(case.current[0]) == repr(case.initial)


def test_only_donor_unsupported_errors_are_translated_and_redacted(case, monkeypatch):
    original = case.module.BridgeError(case.module.ErrorCode.NOT_IMPLEMENTED,
                                       "private RNA failure path: secret-source.py", {"raw_source": "private"})

    def fail(_bpy):
        raise original

    monkeypatch.setattr(case.module.native, "snapshot", fail)
    with pytest.raises(case.module.BridgeError) as caught:
        case.module.Scope(case.bpy, case.scene, "scene.configure")()
    result = caught.value
    assert result is not original and result.__cause__ is original
    assert result.code == "NOT_IMPLEMENTED"
    assert result.context == {"scope_complete": False, "evaluation_scope_complete": False}
    assert "private" not in json.dumps(result.to_dict())
    assert "Rigid" not in result.message


@pytest.mark.parametrize("code", ["TIMEOUT", "PERMISSION_DENIED", "INVALID_ARGUMENT", "OPERATION_FAILED"])
def test_other_native_domain_errors_preserve_exact_primary_error(case, monkeypatch, code):
    original = case.module.BridgeError(code, "primary", {"retained": True})

    def fail(_bpy):
        raise original

    monkeypatch.setattr(case.module.native, "snapshot", fail)
    with pytest.raises(case.module.BridgeError) as caught:
        case.module.Scope(case.bpy, case.scene, "scene.configure")()
    assert caught.value is original


def test_unexpected_native_exception_is_not_reinterpreted_as_unsupported(case, monkeypatch):
    original = RuntimeError("native failure")

    def fail(_bpy):
        raise original

    monkeypatch.setattr(case.module.native, "snapshot", fail)
    with pytest.raises(RuntimeError) as caught:
        case.module.Scope(case.bpy, case.scene, "scene.configure")()
    assert caught.value is original


def plain_object(**changes):
    values = dict(animation_data=None, parent=None, constraints=(), modifiers=(), rigid_body=None,
                  rigid_body_constraint=None, instance_type="NONE", particle_systems=(), field=None, collision=None)
    return NS(**{**values, **changes})


@pytest.mark.parametrize("field,value", [("animation_data", object()), ("parent", object()),
                                        ("constraints", (object(),)), ("modifiers", (object(),)),
                                        ("rigid_body", object()), ("rigid_body_constraint", object()),
                                        ("instance_type", "COLLECTION")])
def test_plain_object_refuses_each_unreviewed_evaluated_source(case, monkeypatch, field, value):
    obj, calls = plain_object(**{field: value}), []
    monkeypatch.setattr(case.module.proof, "descriptors", lambda bpy, owner: calls.append((bpy, owner)))
    with pytest.raises(case.module.BridgeError, match="plain unanimated"):
        case.module.require_plain_object(case.bpy, obj)
    assert calls == [(case.bpy, obj)]


def test_plain_object_native_descriptor_denial_precedes_any_evaluated_getter(case, monkeypatch):
    calls = []

    class Unreviewed:
        @property
        def animation_data(self):
            calls.append("getter")
            raise AssertionError("Unsafe getter ran")

    def reject(_bpy, _owner):
        raise case.module.proof.unsupported("Unknown runtime descriptor")

    monkeypatch.setattr(case.module.proof, "descriptors", reject)
    with pytest.raises(case.module.BridgeError, match="runtime descriptor"):
        case.module.require_plain_object(case.bpy, Unreviewed())
    assert calls == []


def test_plain_object_and_physics_free_static_scene_are_read_only(case, monkeypatch):
    obj = plain_object(modifiers=(NS(type="SUBSURF"),))
    pure = plain_object()
    scene = NS(rigidbody_world=None)
    bpy = NS(data=NS(scenes=(scene,), objects=(obj,)))
    calls = []
    monkeypatch.setattr(case.module.proof, "descriptors", lambda argument, owner: calls.append((argument, owner)))
    case.module.require_plain_object(bpy, pure)
    case.module.require_no_physics(bpy)
    assert calls == [(bpy, pure), (bpy, obj)]
    assert obj.modifiers[0].type == "SUBSURF" and scene.rigidbody_world is None


@pytest.mark.parametrize("kind", ["CLOTH", "COLLISION", "DYNAMIC_PAINT", "EXPLODE", "FLUID",
                                 "PARTICLE_INSTANCE", "PARTICLE_SYSTEM", "SOFT_BODY"])
def test_physics_modifiers_block_units_and_gravity_changes(case, monkeypatch, kind):
    obj = plain_object(modifiers=(NS(type=kind),))
    bpy = NS(data=NS(scenes=(NS(rigidbody_world=None),), objects=(obj,)))
    monkeypatch.setattr(case.module.proof, "descriptors", lambda _bpy, _owner: None)
    with pytest.raises(case.module.BridgeError, match="physics modifiers"):
        case.module.require_no_physics(bpy)


@pytest.mark.parametrize("changes", [{"rigid_body": object()}, {"rigid_body_constraint": object()},
                                      {"particle_systems": (object(),)}, {"field": NS(type="FORCE")},
                                      {"collision": NS(use=True)}])
def test_nonmodifier_physics_blocks_units_and_gravity_changes(case, monkeypatch, changes):
    bpy = NS(data=NS(scenes=(NS(rigidbody_world=None),), objects=(plain_object(**changes),)))
    monkeypatch.setattr(case.module.proof, "descriptors", lambda _bpy, _owner: None)
    with pytest.raises(case.module.BridgeError, match="existing physics require"):
        case.module.require_no_physics(bpy)


def test_unused_scene_rigid_world_still_blocks_global_unit_physics_profile(case, monkeypatch):
    bpy = NS(data=NS(scenes=(NS(rigidbody_world=None), NS(rigidbody_world=object())), objects=()))
    monkeypatch.setattr(case.module.proof, "descriptors", lambda _bpy, _owner: None)
    with pytest.raises(case.module.BridgeError, match="rigid-body worlds"):
        case.module.require_no_physics(bpy)


def test_physics_object_descriptor_denial_precedes_nested_getters(case, monkeypatch):
    calls = []

    class Unreviewed:
        @property
        def field(self):
            calls.append("getter")
            raise AssertionError("Unsafe getter ran")

    bpy = NS(data=NS(scenes=(NS(rigidbody_world=None),), objects=(Unreviewed(),)))

    def reject(_bpy, _owner):
        raise case.module.proof.unsupported("Unknown physics descriptor")

    monkeypatch.setattr(case.module.proof, "descriptors", reject)
    with pytest.raises(case.module.BridgeError, match="physics descriptor"):
        case.module.require_no_physics(bpy)
    assert calls == []


@pytest.mark.parametrize("family,limit", [("scenes", "MAX_SCENES"), ("objects", "MAX_MAIN_IDS")])
def test_physics_inventory_budget_exhaustion_is_fail_closed(case, monkeypatch, family, limit):
    bpy = NS(data=NS(scenes=(NS(rigidbody_world=None),), objects=(plain_object(),)))
    monkeypatch.setattr(case.module.native, limit, 0)
    monkeypatch.setattr(case.module.proof, "descriptors", lambda _bpy, _owner: None)
    with pytest.raises(case.module.BridgeError, match="exceeds 0"):
        case.module.require_no_physics(bpy)
