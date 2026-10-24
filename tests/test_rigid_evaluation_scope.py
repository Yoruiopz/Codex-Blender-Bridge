"""Driver admission, bounded graph closure and descriptor-first read boundaries."""

from __future__ import annotations

import importlib
import itertools
from types import SimpleNamespace as NS

import pytest
from test_rigid_body_lifecycle import rigid_case

assert rigid_case  # Reuse the native-shaped cache/authority fixture explicitly.


class Properties(dict):
    def __setitem__(self, key, value):
        value.identifier = key
        super().__setitem__(key, value)

    def update(self, values):
        for key, value in values.items():
            self[key] = value

    def __iter__(self):
        return iter(self.values())


class RNA(NS):
    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other


class Native:
    _next = itertools.count(1)

    def __init__(self, rna, *, is_id=False, **values):
        self.bl_rna = rna
        self.pointer = next(self._next)
        self.hazards = {}
        self.values = values
        if is_id:
            self.values.update(session_uid=self.pointer, library=None, override_library=None,
                               is_editable=True, animation_data=None)

    def __getattr__(self, key):
        if key in self.hazards:
            self.hazards[key].append(key)
            raise AssertionError(f"Unreviewed getter executed: {key}")
        if key in self.values:
            return self.values[key]
        raise AttributeError(key)

    def as_pointer(self):
        return self.pointer


@pytest.fixture
def evaluation(addon_package):
    module = importlib.import_module(f"{addon_package}.tools._rigid_evaluation_scope")
    errors = importlib.import_module(f"{addon_package}.errors")
    types = NS()
    descriptors = {}

    def prop(kind, fixed=None, *, runtime=False):
        return NS(type=kind, fixed_type=fixed, is_runtime=runtime, is_registered=False,
                  is_registered_optional=False, is_readonly=False)

    def rna(identifier, fields=(), *, base=None, id_fields=False):
        properties = Properties()
        if id_fields:
            properties.update({"library": prop("POINTER"), "override_library": prop("POINTER"),
                "is_editable": prop("BOOLEAN"), "animation_data": prop("POINTER"), "name": prop("STRING")})
        properties.update(dict(fields))
        result = RNA(identifier=identifier, properties=properties, base=base)
        descriptors[identifier] = result
        setattr(types, identifier, NS(bl_rna=result))
        return result

    id_rna = rna("ID")
    node_tree_rna = rna("NodeTree", base=id_rna, id_fields=True)
    interface_rna = rna("NodeTreeInterface", (("items_tree", prop("COLLECTION")),))
    for kind in ("ShaderNodeTree", "CompositorNodeTree", "GeometryNodeTree"):
        rna(kind, (("nodes", prop("COLLECTION")), ("links", prop("COLLECTION")),
                   ("interface", prop("POINTER", interface_rna))), base=node_tree_rna, id_fields=True)
    rna("NodeTreeInterfaceSocketFloat", (("item_type", prop("ENUM")), ("socket_type", prop("ENUM"))))
    for kind in ("ShaderNodeValue", "CompositorNodeValue", "ShaderNodeGroup", "CompositorNodeGroup", "GeometryNodeGroup"):
        rna(kind, (("name", prop("STRING")), ("node_tree", prop("POINTER", node_tree_rna))))
    for kind in ("Scene", "Material", "World", "Object", "Light", "PointLight", "FreestyleLineStyle", "Texture"):
        rna(kind, (("node_tree", prop("POINTER", node_tree_rna)),
                   ("compositing_node_group", prop("POINTER", node_tree_rna)),
                   ("world", prop("POINTER")), ("sequence_editor", prop("POINTER"))),
            base=id_rna, id_fields=True)
    main_rna = rna("BlendData", (("node_groups", prop("COLLECTION", node_tree_rna)),
        ("scenes", prop("COLLECTION", descriptors["Scene"])),
        ("materials", prop("COLLECTION", descriptors["Material"])),
        ("worlds", prop("COLLECTION", descriptors["World"])),
        ("objects", prop("COLLECTION", descriptors["Object"])),
        ("lights", prop("COLLECTION", descriptors["Light"])),
        ("linestyles", prop("COLLECTION", descriptors["FreestyleLineStyle"])),
        ("textures", prop("COLLECTION", descriptors["Texture"]))))
    main = Native(main_rna, node_groups=[], scenes=[], materials=[], worlds=[], objects=[], lights=[], linestyles=[], textures=[])
    bpy = NS(data=main, types=types)

    def node(kind="ShaderNodeValue", name="Value", child=None):
        return Native(descriptors[kind], name=name, node_tree=child)

    def tree(name="Tree", kind="ShaderNodeTree", *, standalone=True, nodes=None):
        result = Native(descriptors[kind], is_id=True, name=name,
            nodes=[] if nodes is None else nodes, links=[],
            interface=Native(interface_rna, items_tree=[]))
        if standalone:
            main.node_groups.append(result)
        return result

    def owner(kind, name, *, tree=None):
        result = Native(descriptors[kind], is_id=True, name=name, node_tree=tree,
                        compositing_node_group=None, world=None, sequence_editor=None)
        getattr(main, {"Scene": "scenes", "Material": "materials", "World": "worlds",
                       "Object": "objects", "PointLight": "lights", "FreestyleLineStyle": "linestyles"}[kind]).append(result)
        return result

    leaf = tree("Nested Leaf", nodes=[node()])
    root = tree("Material Root", standalone=False, nodes=[node("ShaderNodeGroup", "Nested", leaf)])
    material = owner("Material", "Owned Material", tree=root)
    world = owner("World", "Owned World", tree=tree("World Tree", standalone=False, nodes=[node()]))
    scene = owner("Scene", "Owned Scene", tree=tree("Compositor Tree", "CompositorNodeTree", standalone=False,
                                                   nodes=[node("CompositorNodeValue")]))
    scene.values["world"] = world
    return NS(module=module, errors=errors, bpy=bpy, main=main, types=types, descriptors=descriptors,
              prop=prop, rna=rna, node=node, tree=tree, owner=owner,
              leaf=leaf, root=root, material=material, world=world, scene=scene)


def rejected(case, *, text=None):
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.snapshot(case.bpy)
    assert caught.value.code == "NOT_IMPLEMENTED"
    if text is not None:
        assert text in caught.value.message
    return caught.value


def test_complete_static_native_graph_profile_has_repeatable_evidence(evaluation):
    case = evaluation
    before = case.module.snapshot(case.bpy)
    assert isinstance(before, tuple) and before == case.module.snapshot(case.bpy)
    case.root.nodes[0].values["node_tree"] = None
    assert case.module.snapshot(case.bpy) != before


@pytest.mark.parametrize("target", ["material", "leaf", "world", "world_tree", "scene", "compositor"])
def test_every_owner_and_nested_tree_rejects_animation_before_evaluation(evaluation, target):
    case = evaluation
    owner = {"material": case.material, "leaf": case.leaf, "world": case.world,
             "world_tree": case.world.node_tree, "scene": case.scene, "compositor": case.scene.node_tree}[target]
    owner.values["animation_data"] = NS(drivers=["harmless-owned-driver"])
    rejected(case)


@pytest.mark.parametrize("kind", ["Material", "World", "Object", "PointLight"])
def test_unused_main_driver_owners_are_rejected_conservatively(evaluation, kind):
    case = evaluation
    unused = case.owner(kind, "Unused Animated Owner")
    unused.values["animation_data"] = NS(drivers=["counter"])
    rejected(case)


def test_scene_compositing_node_group_pointer_is_part_of_admission(evaluation):
    case = evaluation
    case.scene.values["node_tree"] = None
    group = case.tree("5.x Compositor", "CompositorNodeTree")
    case.scene.values["compositing_node_group"] = group
    before = case.module.snapshot(case.bpy)
    group.values["animation_data"] = NS(drivers=["counter"])
    rejected(case)
    group.values["animation_data"] = None
    case.scene.values["compositing_node_group"] = None
    assert case.module.snapshot(case.bpy) != before


def test_unknown_node_class_getters_are_never_called(evaluation):
    case = evaluation
    custom_rna = case.rna("OwnedCustomNode", (("name", case.prop("STRING")),))
    custom = Native(custom_rna)
    reads = []
    custom.hazards["name"] = reads
    case.leaf.nodes.append(custom)
    rejected(case)
    assert reads == []


def test_shadowed_builtin_rna_does_not_authorize_a_getter(evaluation):
    case = evaluation
    shadow = RNA(**vars(case.descriptors["ShaderNodeValue"]))
    node = Native(shadow)
    reads = []
    node.hazards["name"] = reads
    case.leaf.nodes.append(node)
    rejected(case)
    assert reads == []


def test_runtime_node_pointer_descriptor_is_rejected_before_getattr(evaluation):
    case = evaluation
    case.descriptors["ShaderNodeGroup"].properties["node_tree"].is_runtime = True
    reads = []
    del case.root.nodes[0].values["node_tree"]
    case.root.nodes[0].hazards["node_tree"] = reads
    rejected(case)
    assert reads == []


def test_runtime_owner_animation_descriptor_is_rejected_before_getattr(evaluation):
    case = evaluation
    case.descriptors["Material"].properties["animation_data"].is_runtime = True
    reads = []
    del case.material.values["animation_data"]
    case.material.hazards["animation_data"] = reads
    rejected(case)
    assert reads == []


def test_no_evaluated_socket_getters_are_needed_for_admission(evaluation):
    case = evaluation
    reads = []
    for key in ("inputs", "outputs", "default_value"):
        case.leaf.nodes[0].hazards[key] = reads
    case.module.snapshot(case.bpy)
    assert reads == []


@pytest.mark.parametrize("socket_type", ["NodeSocketImage", "NodeSocketObject", "OwnedCustomSocket"])
def test_unreviewed_group_socket_dependencies_are_rejected_without_defaults(evaluation, socket_type):
    case = evaluation
    item = Native(case.descriptors["NodeTreeInterfaceSocketFloat"], item_type="SOCKET", socket_type=socket_type)
    reads = []
    item.hazards["default_value"] = reads
    case.leaf.interface.items_tree.append(item)
    rejected(case)
    assert reads == []


def test_runtime_interface_class_is_rejected_before_item_getters(evaluation):
    case = evaluation
    custom_rna = case.rna("OwnedCustomInterface", (("item_type", case.prop("ENUM")), ("socket_type", case.prop("STRING"))))
    item = Native(custom_rna)
    reads = []
    item.hazards["item_type"] = reads
    case.leaf.interface.items_tree.append(item)
    rejected(case)
    assert reads == []


def test_nested_group_cycles_are_rejected_even_for_unused_main_groups(evaluation):
    case = evaluation
    first = case.tree("Unused Cycle A")
    second = case.tree("Unused Cycle B")
    first.nodes.append(case.node("ShaderNodeGroup", "To B", second))
    second.nodes.append(case.node("ShaderNodeGroup", "To A", first))
    rejected(case, text="Recursive")


@pytest.mark.parametrize("edges", [8, 9])
def test_nested_group_depth_checks_the_longest_suffix_even_when_leaves_were_visited(evaluation, edges):
    case = evaluation
    assert case.module.MAX_DEPTH == 8
    chain = [case.tree(f"Depth {index}") for index in range(edges+1)]
    for parent, child in itertools.pairwise(chain):
        parent.nodes.append(case.node("ShaderNodeGroup", "Nested", child))
    if edges == 8:
        case.module.snapshot(case.bpy)
    else:
        rejected(case, text="depth")


def test_aggregate_node_budget_cannot_be_bypassed_with_many_small_trees(evaluation):
    case = evaluation
    for index in range(case.module.MAX_TOTAL_NODES//case.module.MAX_NODES+1):
        case.tree(f"Small {index}", nodes=[case.node(name=f"Value {value}") for value in range(case.module.MAX_NODES)])
    rejected(case, text="aggregate")


def test_aggregate_native_id_budget_cannot_be_bypassed_by_unused_objects(evaluation):
    case = evaluation
    maximum = getattr(case.module, "MAX_MAIN_IDS", 512)
    for index in range(maximum+1):
        case.owner("Object", f"Unused {index}")
    rejected(case)


def test_main_id_limit_accepts_exact_budget_and_rejects_one_more_id(evaluation):
    case = evaluation
    before = sum(len(getattr(case.main, family)) for family in ("node_groups", "scenes", "materials", "worlds", "objects", "lights", "linestyles"))
    for index in range(case.module.MAX_MAIN_IDS-before):
        case.owner("Object", f"Bounded {index}")
    case.module.snapshot(case.bpy)
    case.owner("Object", "Over the native ID limit")
    rejected(case)


def test_main_family_runtime_descriptor_never_invokes_its_collection_getter(evaluation):
    case = evaluation
    case.main.bl_rna.properties["materials"].is_runtime = True
    reads = []
    del case.main.values["materials"]
    case.main.hazards["materials"] = reads
    rejected(case)
    assert reads == []


def main_id_alias(case):
    """Mirror 5.x's aggregate alias without counting it as another family."""
    entries = [owner for values in case.main.values.values() for owner in values]
    case.main.bl_rna.properties["all_ids"] = case.prop("COLLECTION", case.descriptors["ID"])
    case.main.values["all_ids"] = entries
    return entries


def test_all_ids_alias_matches_reviewed_families_independent_of_iteration_order(evaluation):
    case = evaluation
    before = case.module.snapshot(case.bpy)
    main_id_alias(case).reverse()
    assert case.module.snapshot(case.bpy) == before


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_all_ids_alias_requires_exact_concrete_family_pointer_set(evaluation, change):
    case = evaluation
    entries = main_id_alias(case)
    if change == "missing":
        entries.pop()
    else:
        entries.append(Native(case.descriptors["Object"], is_id=True, name="Unlisted Main ID"))
    rejected(case, text="all_ids")


def test_unknown_generic_id_alias_is_rejected_without_reading_its_collection(evaluation):
    case = evaluation
    case.main.bl_rna.properties["unreviewed_ids"] = case.prop("COLLECTION", case.descriptors["ID"])
    reads = []
    case.main.hazards["unreviewed_ids"] = reads
    rejected(case, text="alias")
    assert reads == []


def test_all_ids_runtime_descriptor_is_rejected_before_its_collection_getter(evaluation):
    case = evaluation
    main_id_alias(case)
    case.main.bl_rna.properties["all_ids"].is_runtime = True
    del case.main.values["all_ids"]
    reads = []
    case.main.hazards["all_ids"] = reads
    rejected(case)
    assert reads == []


@pytest.mark.parametrize("field,value", [("library", object()), ("override_library", object()), ("is_editable", False)])
def test_linked_override_and_noneditable_graph_owners_are_rejected(evaluation, field, value):
    case = evaluation
    case.material.values[field] = value
    rejected(case)


@pytest.mark.parametrize("kind,family", [("Object", "objects"), ("Texture", "textures")])
@pytest.mark.parametrize("field,value", [("library", object()), ("override_library", object()), ("is_editable", False)])
def test_unused_nongraph_main_ids_require_local_editable_nonoverride_ownership(evaluation, kind, family, field, value):
    case = evaluation
    unused = Native(case.descriptors[kind], is_id=True, name="Unused Dependency")
    unused.values[field] = value
    getattr(case.main, family).append(unused)
    rejected(case, text="every bounded Main ID")


def test_aggregate_link_budget_cannot_be_bypassed_with_individually_bounded_trees(evaluation):
    case = evaluation
    link_rna = case.rna("NodeLink", tuple((field, case.prop("POINTER")) for field in ("from_node", "to_node", "from_socket", "to_socket")))
    for index in range(case.module.MAX_TOTAL_LINKS//case.module.MAX_LINKS+1):
        tree = case.tree(f"Links {index}")
        tree.links.extend(Native(link_rna, from_node=None, to_node=None, from_socket=None, to_socket=None)
                          for _ in range(case.module.MAX_LINKS))
    rejected(case, text="aggregate")


def test_aggregate_interface_budget_cannot_be_bypassed_with_many_small_groups(evaluation):
    case = evaluation
    for index in range(case.module.MAX_TOTAL_INTERFACE//case.module.MAX_INTERFACE+1):
        tree = case.tree(f"Interface {index}")
        tree.interface.items_tree.extend(Native(case.descriptors["NodeTreeInterfaceSocketFloat"],
            item_type="SOCKET", socket_type="NodeSocketFloat") for _ in range(case.module.MAX_INTERFACE))
    rejected(case, text="aggregate")


@pytest.mark.parametrize("nonempty", [False, True])
def test_empty_native_sequencer_is_distinguished_from_evaluated_strips(evaluation, nonempty):
    case = evaluation
    rna = case.rna("SequenceEditor", (("strips", case.prop("COLLECTION")), ("strips_all", case.prop("COLLECTION"))))
    strips = [object()] if nonempty else []
    case.scene.values["sequence_editor"] = Native(rna, strips=strips, strips_all=strips)
    if nonempty:
        rejected(case)
    else:
        case.module.snapshot(case.bpy)


def test_group_references_to_embedded_owner_trees_are_not_inferred_as_standalone_groups(evaluation):
    case = evaluation
    case.root.nodes[0].values["node_tree"] = case.world.node_tree
    rejected(case)


@pytest.mark.parametrize("change", ["animation", "reference"])
def test_late_provider_input_change_invalidates_old_preview_before_any_owned_edit(rigid_case, evaluation, monkeypatch, change):
    case, graph = rigid_case, evaluation
    original = case.module.scope.snapshot

    def combined(*args):
        result = original(*args)
        return {**result, "protected": (*result["protected"], graph.module.snapshot(graph.bpy))}

    monkeypatch.setattr(case.module.scope, "snapshot", combined)
    params = case.proposal()
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        if calls == 3:
            if change == "animation":
                graph.leaf.values["animation_data"] = NS(drivers=["new scripted driver"])
            else:
                graph.root.nodes[0].values["node_tree"] = graph.tree("Late Static Child")

    case.provider.hook = provider
    with pytest.raises(case.errors.BridgeError) as caught:
        case.module.cache(case.context, params)
    assert calls >= 3 and not caught.value.context["possible_mutation"]
    assert not case.physics.resets and not case.physics.frame_calls and not case.physics.native_calls
    assert (case.scene.frame_current, case.scene.frame_subframe) == (7, .25)
