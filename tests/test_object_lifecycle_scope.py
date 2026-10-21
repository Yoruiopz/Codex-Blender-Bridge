"""Ownership, hierarchy, and measured failure restoration for object lifecycle tools."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


class Matrix:
    def __init__(self, location=(0, 0, 0)):
        self.rows = [[float(row == column) for column in range(4)] for row in range(4)]
        for row, value in enumerate(location):
            self.rows[row][3] = float(value)

    def __iter__(self):
        return iter(self.rows)

    @property
    def translation(self):
        return tuple(row[3] for row in self.rows[:3])

    def copy(self):
        return Matrix(self.translation)

    def identity(self):
        self.__init__()

    def inverted(self):
        return Matrix(tuple(-value for value in self.translation))


class OwnedID:
    def __init__(self, name):
        self.name = name
        self.library = self.override_library = None
        self.is_editable = True
        self.users = 1
        self.use_fake_user = False


class Object(OwnedID):
    def __init__(self, name, scene):
        super().__init__(name)
        self.mode = "OBJECT"
        self.type = "EMPTY"
        self.data = None
        self._parent = None
        self.children = []
        self.parent_type = "OBJECT"
        self.matrix_parent_inverse = Matrix()
        self.matrix_basis = Matrix((2, 3, 4))
        self.constraints = []
        self.animation_data = self.rigid_body = self.instance_collection = None
        self.users_scene = (scene,)
        self.users_collection = []
        self.selected = True
        self.fail_world_once = False

    @property
    def parent(self):
        return self._parent

    @parent.setter
    def parent(self, value):
        if self._parent is not None:
            self._parent.children.remove(self)
        self._parent = value
        if value is not None:
            value.children.append(self)

    @property
    def children_recursive(self):
        return [child for direct in self.children for child in (direct, *direct.children_recursive)]

    @property
    def matrix_world(self):
        parent = self.parent.matrix_world.translation if self.parent else (0, 0, 0)
        return Matrix(tuple(a + b + c for a, b, c in zip(parent, self.matrix_parent_inverse.translation, self.matrix_basis.translation, strict=True)))

    @matrix_world.setter
    def matrix_world(self, value):
        if self.fail_world_once:
            self.fail_world_once = False
            raise RuntimeError("injected world transform assignment failure")
        parent = self.parent.matrix_world.translation if self.parent else (0, 0, 0)
        self.matrix_basis = Matrix(tuple(a - b - c for a, b, c in zip(value.translation, parent, self.matrix_parent_inverse.translation, strict=True)))

    def select_set(self, selected):
        self.selected = selected


class Links:
    def __init__(self, collection):
        self.collection = collection
        self.fail_unlink_once = False
        self.fail_unlink_always = False
        self.fail_after_link = False
        self.calls = []
        self.items = []

    def get(self, name):
        return next((obj for obj in self.items if obj.name == name), None)

    def link(self, obj):
        self.calls.append(("link", obj.name))
        obj.users_collection.append(self.collection)
        self.items.append(obj)
        if self.fail_after_link:
            self.fail_after_link = False
            raise RuntimeError("injected post-link failure")

    def unlink(self, obj):
        self.calls.append(("unlink", obj.name))
        if self.fail_unlink_once or self.fail_unlink_always:
            self.fail_unlink_once = False
            raise RuntimeError("injected unlink failure")
        obj.users_collection.remove(self.collection)
        self.items.remove(obj)


class Collection(OwnedID):
    def __init__(self, name):
        super().__init__(name)
        self.children = []
        self.objects = Links(self)

    def user_of_id(self, obj):
        return int(self in obj.users_collection)


class Objects(dict):
    active = None

    def __iter__(self):
        return iter(self.values())

    def new(self, name, data):
        obj = Object(name, self.scene)
        obj.data = data
        self[name] = obj
        return obj

    def remove(self, obj, *, do_unlink):
        assert do_unlink
        for collection in tuple(obj.users_collection):
            collection.objects.unlink(obj)
        del self[obj.name]


class Context:
    mode = "OBJECT"

    @property
    def selected_objects(self):
        return [obj for obj in self.view_layer.objects if obj.selected]


@pytest.fixture
def lifecycle(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.objects")
    errors = importlib.import_module(f"{addon_package}.errors")
    root, first, second = (Collection(name) for name in ("Root", "First", "Second"))
    root.children = [first, second]
    scene = OwnedID("Scene")
    scene.collection = root
    objects = Objects({name: Object(name, scene) for name in ("Target", "Parent", "Old Parent")})
    for obj in objects:
        root.objects.link(obj)
    objects.scene = scene
    objects.active = objects["Target"]
    context = Context()
    context.scene = scene
    context.view_layer = SimpleNamespace(objects=objects, update=lambda: None)
    incoming = {}
    data = SimpleNamespace(objects=objects, user_map=lambda *, subset: {obj: (*obj.users_collection, *incoming.get(obj, ())) for obj in subset})
    bpy = SimpleNamespace(context=context, data=data)
    collections = {collection.name: collection for collection in (root, first, second)}
    monkeypatch.setattr(module, "require_blender", lambda: bpy)
    monkeypatch.setattr(module, "get_object", lambda name, **kwargs: objects[name])
    monkeypatch.setattr(module, "get_collection", lambda name=None: collections[name] if name else root)
    monkeypatch.setattr(module, "clear_selection_references", lambda *args: None)
    monkeypatch.setattr(module, "serialize_transform", lambda obj: {"matrix_world": list(obj.matrix_world), "matrix_basis": list(obj.matrix_basis)})
    return SimpleNamespace(module=module, errors=errors, bpy=bpy, objects=objects, root=root, first=first, second=second, incoming=incoming, scene=scene)


@pytest.mark.parametrize("handler", ["delete_object", "duplicate_object", "rename_object", "set_parent", "move_to_collection"])
@pytest.mark.parametrize("field,value", [("library", object()), ("override_library", object()), ("is_editable", False)])
def test_object_lifecycle_rejects_nonlocal_id_before_other_work(lifecycle, handler, field, value):
    env = lifecycle
    obj = env.objects["Target"]
    setattr(obj, field, value)
    before = len(env.root.objects.calls)
    with pytest.raises(env.errors.BridgeError) as caught:
        getattr(env.module, handler)(None, {"object_name": obj.name})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert len(env.root.objects.calls) == before
    assert obj.parent is None


@pytest.mark.parametrize("handler,params", [
    ("create_object", {"collection": "First"}),
    ("move_to_collection", {"object_name": "Target", "collection_name": "First"}),
])
@pytest.mark.parametrize("field,value", [("library", object()), ("override_library", object()), ("is_editable", False), ("users", 2)])
def test_collection_target_is_preflighted_before_allocation_or_membership_edits(lifecycle, handler, params, field, value):
    env = lifecycle
    setattr(env.first, field, value)
    before = tuple(env.objects["Target"].users_collection)
    with pytest.raises(env.errors.BridgeError) as caught:
        getattr(env.module, handler)(None, params)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert env.first.objects.calls == []
    assert tuple(env.objects["Target"].users_collection) == before


def test_shared_ancestor_and_cross_scene_object_scope_are_rejected(lifecycle):
    env = lifecycle
    env.first.children.append(env.second)
    env.root.children.remove(env.second)
    env.first.users = 2
    with pytest.raises(env.errors.BridgeError, match="ancestry"):
        env.module.move_to_collection(None, {"object_name": "Target", "collection_name": "Second"})
    env.objects["Target"].users_scene += (OwnedID("Protected Scene"),)
    with pytest.raises(env.errors.BridgeError, match="shared between scenes"):
        env.module.delete_object(None, {"object_name": "Target"})
    assert "Target" in env.objects


@pytest.mark.parametrize("handler,params", [
    ("delete_object", {}), ("rename_object", {"new_name": "Changed"}),
    ("set_parent", {"parent_name": "Parent"}),
    ("move_to_collection", {"collection_name": "First"}),
])
def test_incoming_consumers_are_not_silently_changed(lifecycle, handler, params):
    env = lifecycle
    target = env.objects["Target"]
    env.incoming[target] = [OwnedID("Protected Driver Consumer")]
    with pytest.raises(env.errors.BridgeError, match="incoming consumers"):
        getattr(env.module, handler)(None, {"object_name": target.name, **params})
    assert target.name == "Target"
    assert target.parent is None
    assert target.users_collection == [env.root]


def test_deletion_does_not_implicitly_unparent_children(lifecycle):
    env = lifecycle
    env.objects["Parent"].parent = env.objects["Target"]
    with pytest.raises(env.errors.BridgeError, match="with children"):
        env.module.delete_object(None, {"object_name": "Target"})
    assert env.objects["Parent"].parent == env.objects["Target"]


@pytest.mark.parametrize("keep_transform", [True, False])
def test_parenting_preserves_requested_space_and_selection(lifecycle, keep_transform):
    env = lifecycle
    target, parent = env.objects["Target"], env.objects["Parent"]
    parent.matrix_basis = Matrix((10, 20, 30))
    before_world, before_basis = target.matrix_world.translation, target.matrix_basis.translation
    before_selection = tuple(env.bpy.context.selected_objects)
    result = env.module.set_parent(None, {"object_name": target.name, "parent_name": parent.name, "keep_transform": keep_transform})
    assert target.parent == parent
    assert (target.matrix_world.translation if keep_transform else target.matrix_basis.translation) == (before_world if keep_transform else before_basis)
    assert result["verified"] and result["context_preserved"]
    assert tuple(env.bpy.context.selected_objects) == before_selection
    assert env.objects.active == target


def test_parenting_failure_restores_original_parent_inverse_basis_and_world(lifecycle):
    env = lifecycle
    target, old = env.objects["Target"], env.objects["Old Parent"]
    old.matrix_basis = Matrix((10, 20, 30))
    target.parent = old
    target.matrix_parent_inverse = Matrix((-7, -8, -9))
    before = (target.matrix_parent_inverse.translation, target.matrix_basis.translation, target.matrix_world.translation)
    target.fail_world_once = True
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.set_parent(None, {"object_name": target.name, "parent_name": "Parent"})
    assert target.parent == old
    assert (target.matrix_parent_inverse.translation, target.matrix_basis.translation, target.matrix_world.translation) == before
    assert caught.value.context["execution_started"] is True
    assert caught.value.context["rollback_verified"] is True
    assert caught.value.context["possible_mutation"] is False


@pytest.mark.parametrize("attribute,value", [("parent_type", "BONE"), ("constraints", [object()]), ("animation_data", object()), ("rigid_body", object()), ("instance_collection", object())])
def test_parenting_rejects_unreviewed_transform_context_before_writing(lifecycle, attribute, value):
    env = lifecycle
    target = env.objects["Target"]
    setattr(target, attribute, value)
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.set_parent(None, {"object_name": target.name, "parent_name": "Parent"})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert target.parent is None


def test_collection_membership_partial_failure_restores_all_original_links(lifecycle):
    env = lifecycle
    target = env.objects["Target"]
    env.first.objects.link(target)
    env.first.objects.fail_unlink_once = True
    before = set(target.users_collection)
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.move_to_collection(None, {"object_name": target.name, "collection_name": "Second"})
    assert set(target.users_collection) == before
    assert caught.value.context["rollback_verified"] is True
    assert caught.value.context["execution_started"] is True


def test_collection_membership_denied_recovery_is_reported_truthfully(lifecycle):
    env = lifecycle
    env.first.objects.fail_after_link = True
    env.first.objects.fail_unlink_always = True
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.move_to_collection(None, {"object_name": "Target", "collection_name": "First"})
    assert env.first in env.objects["Target"].users_collection
    assert caught.value.context["rollback_verified"] is False
    assert caught.value.context["possible_mutation"] is True


@pytest.mark.parametrize("link_only", [True, False])
def test_membership_success_has_measured_scope_and_preserved_context(lifecycle, link_only):
    env = lifecycle
    result = env.module.move_to_collection(None, {"object_name": "Target", "collection_name": "First", "link_only": link_only})
    assert result["collections"] == (["Root", "First"] if link_only else ["First"])
    assert result["verified"] and result["context_preserved"]
    assert env.objects.active == env.objects["Target"]


@pytest.mark.parametrize("scene_uses,allowed", [(2, True), (3, False)])
def test_scene_base_and_embedded_root_membership_are_distinguished_from_extra_references(lifecycle, scene_uses, allowed):
    env = lifecycle
    env.scene.view_layers = (env.bpy.context.view_layer,)
    env.scene.user_of_id = lambda obj: scene_uses
    env.incoming[env.objects["Target"]] = [env.scene]
    if allowed:
        assert env.module.set_parent(None, {"object_name": "Target", "parent_name": "Parent"})["verified"]
    else:
        with pytest.raises(env.errors.BridgeError, match="incoming consumers"):
            env.module.set_parent(None, {"object_name": "Target", "parent_name": "Parent"})
        assert env.objects["Target"].parent is None


def test_native_datablock_identity_accepts_equivalent_rna_wrappers(lifecycle):
    env = lifecycle
    env.root.as_pointer = lambda: 42
    alternate_wrapper = OwnedID("Root wrapper")
    alternate_wrapper.as_pointer = lambda: 42
    env.incoming[env.objects["Target"]] = [alternate_wrapper]
    assert env.module.set_parent(None, {"object_name": "Target", "parent_name": "Parent"})["verified"]


def test_parenting_failure_retains_newer_selection_and_active_object(lifecycle, monkeypatch):
    env = lifecycle
    target = env.objects["Target"]
    def fail_evidence(obj):
        target.selected = False
        env.objects.active = env.objects["Parent"]
        raise RuntimeError("Injected context/evidence failure")
    monkeypatch.setattr(env.module, "serialize_transform", fail_evidence)
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.set_parent(None, {"object_name": "Target", "parent_name": "Parent"})
    assert caught.value.context["rollback_verified"] is False
    assert env.objects.active == env.objects["Parent"]
    assert target.selected is False


def test_parenting_recovery_reports_failed_world_verification(lifecycle):
    env = lifecycle
    target = env.objects["Target"]
    target.fail_world_once = True
    updates = 0
    def update():
        nonlocal updates
        updates += 1
        if updates == 2:
            target.matrix_basis = Matrix((999, 0, 0))
    env.bpy.context.view_layer.update = update
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.set_parent(None, {"object_name": "Target", "parent_name": "Parent"})
    assert caught.value.context["rollback_verified"] is False
    assert caught.value.context["possible_mutation"] is True


def live_context(addon_package, module, flags):
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry()
    module.register_tools(registry)
    registry.enable_toolset("objects")
    permissions = importlib.import_module(f"{addon_package}.permissions").PermissionManager(lambda: flags)
    state = importlib.import_module(f"{addon_package}.state").BridgeState()
    return registry_module.ToolContext(state=state, permissions=permissions, registry=registry, checkpoints=None)


@pytest.mark.parametrize("phase", ["preflight", "after_write"])
def test_parenting_checks_live_grants_at_apply_and_recovery_boundaries(lifecycle, addon_package, phase):
    env = lifecycle
    flags = {"TRANSFORM_OBJECTS": True}
    context = live_context(addon_package, env.module, flags)
    updates = 0
    def update():
        nonlocal updates
        updates += 1
        if updates == (1 if phase == "preflight" else 2):
            flags["TRANSFORM_OBJECTS"] = False
    env.bpy.context.view_layer.update = update
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.set_parent(context, {"object_name": "Target", "parent_name": "Parent"})
    assert caught.value.code == "PERMISSION_DENIED"
    assert env.objects["Target"].parent == (None if phase == "preflight" else env.objects["Parent"])
    if phase == "after_write":
        assert caught.value.context["rollback_verified"] is False


@pytest.mark.parametrize("stop", ["pause", "emergency", "cancel"])
def test_parenting_does_not_mutate_after_stop_or_caller_cancel(lifecycle, addon_package, stop):
    env = lifecycle
    context = live_context(addon_package, env.module, {"TRANSFORM_OBJECTS": True})
    cancelled = False
    updates = 0
    def check_cancelled():
        if cancelled:
            raise env.errors.BridgeError(env.errors.ErrorCode.TIMEOUT, "Caller cancelled")
    context.check_cancelled = check_cancelled
    def update():
        nonlocal updates, cancelled
        updates += 1
        if updates == 2:
            if stop == "cancel":
                cancelled = True
            elif stop == "pause":
                context.state.set_paused(True)
            else:
                context.state.set_emergency_stopped(True)
    env.bpy.context.view_layer.update = update
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.set_parent(context, {"object_name": "Target", "parent_name": "Parent"})
    assert caught.value.code == {"pause": "AGENT_PAUSED", "emergency": "EMERGENCY_STOPPED", "cancel": "TIMEOUT"}[stop]
    assert env.objects["Target"].parent == env.objects["Parent"]
    assert caught.value.context["rollback_verified"] is False


def test_parenting_does_not_overwrite_a_newer_external_parent(lifecycle):
    env = lifecycle
    updates = 0
    def update():
        nonlocal updates
        updates += 1
        if updates == 2:
            env.objects["Target"].parent = env.objects["Old Parent"]
    env.bpy.context.view_layer.update = update
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.set_parent(None, {"object_name": "Target", "parent_name": "Parent"})
    assert env.objects["Target"].parent == env.objects["Old Parent"]
    assert caught.value.context["external_state_retained"] is True


def test_membership_recovery_does_not_unlink_an_external_new_collection(lifecycle):
    env = lifecycle
    updates = 0
    def update():
        nonlocal updates
        updates += 1
        if updates == 1:
            env.second.objects.link(env.objects["Target"])
    env.bpy.context.view_layer.update = update
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.move_to_collection(None, {"object_name": "Target", "collection_name": "First"})
    assert set(env.objects["Target"].users_collection) == {env.root, env.second}
    assert caught.value.context["rollback_verified"] is False


@pytest.mark.parametrize("attribute,value", [("delta_location", (1, 0, 0)), ("delta_scale", (1, 2, 1))])
def test_parenting_rejects_nondefault_deltas_before_writes(lifecycle, attribute, value):
    env = lifecycle
    setattr(env.objects["Target"], attribute, value)
    with pytest.raises(env.errors.BridgeError, match="delta transforms"):
        env.module.set_parent(None, {"object_name": "Target", "parent_name": "Parent"})
    assert env.objects["Target"].parent is None


@pytest.mark.parametrize("handler", ["create_object", "duplicate_object"])
def test_failed_allocations_are_retained_without_implicit_delete_consent(lifecycle, addon_package, monkeypatch, handler):
    env = lifecycle
    context = live_context(addon_package, env.module, {"TRANSFORM_OBJECTS": True, "DELETE_OBJECTS": False})
    monkeypatch.setattr(env.objects, "remove", lambda *args, **kwargs: pytest.fail("Implicit deletion without consent"))
    if handler == "create_object":
        env.first.objects.fail_after_link = True
        params = {"name": "Retained Allocation", "collection": "First", "object_type": "EMPTY"}
    else:
        env.root.objects.fail_after_link = True
        env.objects["Target"].copy = lambda: env.objects.new("Retained Allocation", None)
        params = {"object_name": "Target"}
    with pytest.raises(env.errors.BridgeError) as caught:
        getattr(env.module, handler)(context, params)
    assert "Retained Allocation" in env.objects
    assert caught.value.context["retained_allocations"] == [{"kind": "OBJECT", "name": "Retained Allocation"}]
    assert caught.value.context["affected_objects"] == ["Retained Allocation"]
    assert caught.value.context["rollback_verified"] is False
