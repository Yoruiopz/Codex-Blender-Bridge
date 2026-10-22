"""Collection scope proves actual native references before a caller can write."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


class Props(list):
    def get(self, name):
        return next((prop for prop in self if prop.identifier == name), None)


def prop(name, kind, *, readonly=False, runtime=False):
    return SimpleNamespace(identifier=name, type=kind, is_readonly=readonly,
                           is_runtime=runtime, is_registered=False, array_length=0)


class Native:
    sequence = 100

    def __init__(self, name):
        Native.sequence += 1
        self.pointer = Native.sequence
        self.session_uid = self.pointer + 1000
        self.name = name
        self.library = self.override_library = None
        self.is_editable = True
        self.users = 1
        self.use_fake_user = False
        self.references = {}
        self.custom = {}

    def as_pointer(self):
        return self.pointer

    def user_of_id(self, other):
        return self.references.get(other, 0)

    def keys(self):
        return self.custom.keys()

    def __getitem__(self, key):
        return self.custom[key]


class Collection(Native):
    def __init__(self, name):
        super().__init__(name)
        self.children = []
        self.objects = []
        self.hide_render = False


class Scene(Native):
    pass


class ViewLayer(Native):
    pass


class LayerCollection(Native):
    def __init__(self, collection):
        super().__init__(collection.name)
        self.collection = collection
        self.children = []


class Object(Native):
    pass


def fixture():
    base = [prop("name", "STRING"), prop("session_uid", "INT", readonly=True),
            prop("library", "POINTER", readonly=True), prop("override_library", "POINTER", readonly=True),
            prop("is_editable", "BOOLEAN", readonly=True), prop("users", "INT", readonly=True),
            prop("use_fake_user", "BOOLEAN")]
    for cls, extra in ((Collection, [prop("children", "COLLECTION", readonly=True),
                                    prop("objects", "COLLECTION", readonly=True), prop("hide_render", "BOOLEAN")]),
                       (Scene, [prop("collection", "POINTER", readonly=True),
                                prop("view_layers", "COLLECTION", readonly=True)]),
                       (ViewLayer, [prop("layer_collection", "POINTER", readonly=True)]),
                       (LayerCollection, [prop("collection", "POINTER", readonly=True),
                                          prop("children", "COLLECTION", readonly=True)]), (Object, [])):
        cls.bl_rna = SimpleNamespace(identifier=cls.__name__, properties=Props([*base, *extra]))
    root, parent, child = Collection("Scene Collection"), Collection("Parent"), Collection("Child")
    root.users = 0
    root.children = [parent]
    parent.children = [child]
    root.references[parent] = 1
    parent.references[child] = 1
    scene = Scene("Scene")
    scene.collection = root
    scene.references = {root: 2, parent: 2, child: 1}
    layer = ViewLayer("ViewLayer")
    layer_root, layer_parent, layer_child = map(LayerCollection, (root, parent, child))
    layer_root.children = [layer_parent]
    layer_parent.children = [layer_child]
    layer.layer_collection = layer_root
    scene.view_layers = [layer]
    storage = {item.name: item for item in (parent, child)}
    consumers = {root: (), parent: (scene,), child: (scene, parent)}
    bpy = SimpleNamespace(types=SimpleNamespace(Scene=Scene, Collection=Collection, ViewLayer=ViewLayer,
                                                LayerCollection=LayerCollection, Object=Object),
                          context=SimpleNamespace(scene=scene),
                          data=SimpleNamespace(scenes={scene.name: scene}, collections=storage,
                                               user_map=lambda subset: {owner: consumers.get(owner, ()) for owner in subset}))
    return bpy, scene, root, parent, child, consumers


@pytest.fixture
def scope(addon_package):
    return importlib.import_module(f"{addon_package}.tools._scene_collection_scope")


@pytest.mark.parametrize("index", [2, 3, 4])
def test_root_and_ordinary_nested_memberships_are_read_only(scope, index):
    values = fixture()
    bpy, scene, root, parent, child, _ = values
    before = (tuple(root.children), tuple(parent.children), child.name)
    result = scope.snapshot(bpy, scene, values[index], operation="collection.rename")
    assert dict(result)["target"] == (values[index].as_pointer(), values[index].session_uid)
    assert (tuple(root.children), tuple(parent.children), child.name) == before


def test_actual_lazy_view_layer_occurrences_are_used(scope):
    bpy, scene, root, parent, child, consumers = fixture()
    scene.view_layers[0].layer_collection.children = []
    scene.references.update({parent: 1, child: 0})
    consumers[child] = (parent,)
    result = dict(scope.snapshot(bpy, scene, child, operation="collection.rename"))
    assert result["layers"] == tuple(record for record in result["layers"] if record[2] == root.as_pointer())


def test_unsynchronized_or_extra_scene_reference_is_refused(scope):
    bpy, scene, _root, _parent, child, _consumers = fixture()
    scene.references[child] += 1
    with pytest.raises(scope.BridgeError, match="Scene references"):
        scope.snapshot(bpy, scene, child, operation="collection.rename")


@pytest.mark.parametrize("owner_index", [2, 3, 4])
@pytest.mark.parametrize("field,value", [("library", object()), ("override_library", object()), ("is_editable", False)])
def test_nonlocal_ancestry_refused(scope, owner_index, field, value):
    values = fixture()
    setattr(values[owner_index], field, value)
    with pytest.raises(scope.BridgeError, match="local, editable"):
        scope.snapshot(values[0], values[1], values[4], operation="collection.rename")


@pytest.mark.parametrize("consumer_kind", [Object, Collection, Scene])
def test_external_or_instanced_id_consumer_is_refused(scope, consumer_kind):
    bpy, scene, _root, parent, child, consumers = fixture()
    external = consumer_kind("External")
    external.references[child] = 1
    consumers[child] = (*consumers[child], external)
    # Even a misleading native users counter cannot replace the reference proof.
    assert child.users == 1
    with pytest.raises(scope.BridgeError, match="direct consumers"):
        scope.snapshot(bpy, scene, child, operation="collection.rename")
    assert parent.children == [child]


def test_extra_pointer_from_ordinary_parent_is_refused(scope):
    bpy, scene, _root, parent, child, _ = fixture()
    parent.references[child] = 2
    with pytest.raises(scope.BridgeError, match="beyond ordinary"):
        scope.snapshot(bpy, scene, child, operation="collection.rename")


def test_additional_parent_membership_is_refused(scope):
    bpy, scene, root, _parent, child, _ = fixture()
    root.children.append(child)
    with pytest.raises(scope.BridgeError, match="multiple parent"):
        scope.snapshot(bpy, scene, child, operation="collection.rename")


def test_cyclic_membership_is_refused(scope):
    bpy, scene, root, _parent, child, _ = fixture()
    child.children.append(root)
    with pytest.raises(scope.BridgeError, match="cycle"):
        scope.snapshot(bpy, scene, child, operation="collection.rename")


@pytest.mark.parametrize("kind", ["Scene", "Collection", "ViewLayer", "LayerCollection"])
def test_runtime_getter_is_refused_before_any_get(scope, kind):
    bpy, scene, _root, _parent, child, _ = fixture()
    cls = getattr(bpy.types, kind)
    calls = []
    cls.bl_rna.properties.append(prop("unsafe", "FLOAT", runtime=True))
    cls.unsafe = property(lambda self: calls.append(self) or 2.0)
    try:
        with pytest.raises(scope.BridgeError, match="runtime"):
            scope.snapshot(bpy, scene, child, operation="collection.rename")
        assert calls == []
    finally:
        del cls.unsafe


def test_scene_bundled_readonly_pointer_is_not_resolved(scope):
    bpy, scene, _root, _parent, child, _ = fixture()
    marker = prop("cycles", "POINTER", readonly=True, runtime=True)
    marker.fixed_type = SimpleNamespace(identifier="CyclesRenderSettings")
    Scene.bl_rna.properties.append(marker)
    calls = []
    Scene.cycles = property(lambda self: calls.append(self) or None)
    try:
        scope.snapshot(bpy, scene, child, operation="collection.rename")
        assert calls == []
    finally:
        del Scene.cycles


def test_owned_rename_normalizes_only_exact_target_name(scope):
    bpy, scene, _root, _parent, child, _ = fixture()
    before = scope.snapshot(bpy, scene, child, operation="collection.rename", expected_name="Child")
    del bpy.data.collections[child.name]
    child.name = "Renamed"
    bpy.data.collections[child.name] = child
    assert scope.snapshot(bpy, scene, child, operation="collection.rename", expected_name="Renamed") == before
    child.hide_render = True
    assert scope.snapshot(bpy, scene, child, operation="collection.rename", expected_name="Renamed") != before


def test_same_name_replacement_refuses_native_storage_binding(scope):
    bpy, scene, _root, _parent, child, _ = fixture()
    bpy.data.collections[child.name] = Collection(child.name)
    with pytest.raises(scope.BridgeError, match="storage binding"):
        scope.snapshot(bpy, scene, child, operation="collection.rename")


def test_empty_unlinked_allocation_is_admitted_only_explicitly(scope):
    bpy, scene, _root, _parent, _child, _ = fixture()
    allocated = Collection("Owned Allocation")
    allocated.users = 0
    bpy.data.collections[allocated.name] = allocated
    with pytest.raises(scope.BridgeError, match="outside"):
        scope.snapshot(bpy, scene, allocated, operation="collection.create")
    result = scope.snapshot(bpy, scene, allocated, operation="collection.create", allow_unlinked=True)
    assert dict(result)["objects"] == ()
    allocated.use_fake_user = True
    with pytest.raises(scope.BridgeError, match="empty zero-user"):
        scope.snapshot(bpy, scene, allocated, operation="collection.create", allow_unlinked=True)


def test_unlinked_allocation_with_new_native_consumer_is_refused(scope):
    bpy, scene, _root, parent, _child, consumers = fixture()
    allocated = Collection("Owned Allocation")
    allocated.users = 0
    bpy.data.collections[allocated.name] = allocated
    parent.references[allocated] = 1
    consumers[allocated] = (parent,)
    with pytest.raises(scope.BridgeError, match="direct consumers"):
        scope.snapshot(bpy, scene, allocated, operation="collection.create", allow_unlinked=True)


def test_custom_native_reference_is_refused_without_following_it(scope):
    bpy, scene, _root, _parent, child, _ = fixture()
    child.custom["foreign"] = Object("Foreign")
    with pytest.raises(scope.BridgeError, match="native references"):
        scope.snapshot(bpy, scene, child, operation="collection.rename")


def test_snapshot_detects_custom_value_or_membership_change(scope):
    bpy, scene, _root, _parent, child, _ = fixture()
    before = scope.snapshot(bpy, scene, child, operation="collection.rename")
    child.custom["artist_setting"] = {"value": [1, 2, 3]}
    assert scope.snapshot(bpy, scene, child, operation="collection.rename") != before
    child.custom.clear()
    child.objects.append(Object("Member"))
    assert scope.snapshot(bpy, scene, child, operation="collection.rename") != before


def test_budget_exhaustion_refuses_before_unbounded_walk(scope, monkeypatch):
    bpy, scene, _root, _parent, child, _ = fixture()
    monkeypatch.setattr(scope, "MAX_COLLECTIONS", 2)
    with pytest.raises(scope.BridgeError, match="4096 collections"):
        scope.snapshot(bpy, scene, child, operation="collection.rename")


def test_nonarray_property_metadata_does_not_require_array_length(scope):
    bpy, scene, _root, _parent, child, _ = fixture()
    for cls in (Scene, Collection, ViewLayer, LayerCollection):
        for descriptor in cls.bl_rna.properties:
            if descriptor.type in {"STRING", "POINTER", "COLLECTION"} and hasattr(descriptor, "array_length"):
                del descriptor.array_length
    scope.snapshot(bpy, scene, child, operation="collection.rename")


def test_member_object_runtime_getter_is_never_resolved(scope):
    bpy, scene, _root, _parent, child, _ = fixture()
    calls = []
    Object.bl_rna.properties.append(prop("unread_runtime", "FLOAT", runtime=True))
    Object.unread_runtime = property(lambda self: calls.append(self) or 1.0)
    child.objects.append(Object("Member"))
    try:
        scope.snapshot(bpy, scene, child, operation="collection.rename")
        assert calls == []
    finally:
        del Object.unread_runtime


def test_unrelated_readonly_branch_is_not_an_edit_target(scope):
    bpy, scene, root, _parent, child, _ = fixture()
    unrelated = Collection("Linked Unrelated")
    unrelated.library = object()
    unrelated.is_editable = False
    root.children.append(unrelated)
    scope.snapshot(bpy, scene, child, operation="collection.rename")


@pytest.mark.parametrize("field,value", [("type", "FLOAT"), ("is_readonly", False),
                                        ("is_registered", True), ("fixed_type", None)])
def test_inexact_bundled_descriptor_is_refused_before_getter(scope, field, value):
    bpy, scene, _root, _parent, child, _ = fixture()
    descriptor = prop("cycles", "POINTER", readonly=True, runtime=True)
    descriptor.fixed_type = SimpleNamespace(identifier="CyclesRenderLayerSettings")
    setattr(descriptor, field, value)
    ViewLayer.bl_rna.properties.append(descriptor)
    calls = []
    ViewLayer.cycles = property(lambda self: calls.append(self) or None)
    try:
        with pytest.raises(scope.BridgeError, match="runtime"):
            scope.snapshot(bpy, scene, child, operation="collection.rename")
        assert calls == []
    finally:
        del ViewLayer.cycles


def test_projection_removes_only_exact_previously_proven_owned_child(scope):
    bpy, scene, _root, _parent, child, _ = fixture()
    before = scope.snapshot(bpy, scene, child, operation="collection.create")
    allocated = Collection("New Child")
    child.children.append(allocated)
    after = scope.snapshot(bpy, scene, child, operation="collection.create")
    allocated_token = (allocated.as_pointer(), allocated.session_uid)
    assert scope.without_owned_child(after, allocated_token) == before
    child.hide_render = True
    changed = scope.snapshot(bpy, scene, child, operation="collection.create")
    assert scope.without_owned_child(changed, allocated_token) != before
    with pytest.raises(scope.BridgeError, match="unique new child"):
        scope.without_owned_child(before, allocated_token)
