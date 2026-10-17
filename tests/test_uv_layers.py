from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


class Buffer:
    def __init__(self, values, width=1, fail=False):
        self.values, self.width, self.fail = list(values), width, fail

    def __len__(self):
        return len(self.values) // self.width

    def foreach_get(self, prop, values):
        values[:] = self.values

    def foreach_set(self, prop, values):
        if self.fail:
            raise RuntimeError("injected buffer failure")
        assert len(values) == len(self.values)
        self.values[:] = values


class Layer:
    def __init__(self, name, owner):
        self.name, self.owner = name, owner
        self.uv, self.pin = Buffer([0.] * 8, 2), Buffer([False] * 4)
        self.vertex_selection, self.edge_selection = Buffer([False] * 4), Buffer([False] * 4)
        self.flags = {"render": False, "clone": False}

    def _set(self, key, value):
        if value:
            for layer in self.owner:
                layer.flags[key] = False
        self.flags[key] = value

    active_render = property(lambda self: self.flags["render"], lambda self, value: self._set("render", value))
    active_clone = property(lambda self: self.flags["clone"], lambda self, value: self._set("clone", value))


class Layers(list):
    active_index = 0
    fail_copy = False

    @property
    def active(self):
        return self[self.active_index] if self else None

    def keys(self):
        return [layer.name for layer in self]

    def get(self, name):
        return next((layer for layer in self if layer.name == name), None)

    def __getitem__(self, key):
        return self.get(key) if isinstance(key, str) else super().__getitem__(key)

    def new(self, *, name, do_init):
        assert not do_init
        layer = Layer(name, self)
        layer.uv.fail = self.fail_copy
        self.append(layer)
        if len(self) == 1:
            layer.active_render = layer.active_clone = True
        return layer


@pytest.fixture
def layers(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools.uv_layers")
    collection = Layers()
    source = collection.new(name="Source", do_init=False)
    source.uv.values[:] = [0., 0., 1., 0., 1., 1., 0., 1.]
    source.pin.values[:] = [True, False, True, False]
    source.vertex_selection.values[:] = [True] * 4
    obj = SimpleNamespace(name="Mesh", mode="OBJECT", data=SimpleNamespace(
        users=1, uv_layers=collection, loops=[None] * 4, attributes={},
    ))
    monkeypatch.setattr(module, "_mesh_object", lambda _: obj)
    monkeypatch.setattr(module, "require_blender", lambda: SimpleNamespace(context=SimpleNamespace(mode="OBJECT")))
    return module, obj, collection, SimpleNamespace(check_cancelled=None)


def params(**kwargs):
    return {"object_name": "Mesh", **kwargs}


@pytest.mark.parametrize("tool,extra", [
    ("layer_create", {"new_name": ""}), ("layer_create", {"new_name": "Source"}),
    ("layer_create", {"new_name": "New", "copy_from": "Missing"}),
    ("layer_create", {"new_name": "New", "other": 1}),
    ("layer_rename", {"uv_layer": "Source", "new_name": ""}),
    ("layer_activate", {"uv_layer": "Missing"}),
    ("layer_activate", {"uv_layer": "Source", "for_render": 1}),
    ("layer_remove", {"uv_layer": "Source"}),
    ("layer_remove", {"uv_layer": "Source", "confirm_remove": 1}),
])
def test_layer_invalid_input_is_preflighted(layers, tool, extra):
    module, obj, collection, context = layers
    before = module._state(obj)
    with pytest.raises(Exception) as error:
        getattr(module, tool)(context, params(**extra))
    assert error.value.code == "INVALID_ARGUMENT" and module._state(obj) == before
    assert collection["Source"].pin.values == [True, False, True, False]


@pytest.mark.parametrize("restriction", ["shared", "linked", "readonly", "edit", "corners", "layer_count", "aux_collision"])
def test_layer_ownership_and_resource_limits(layers, monkeypatch, restriction):
    module, obj, collection, context = layers
    if restriction == "shared":
        obj.data.users = 2
    elif restriction == "linked":
        obj.library = object()
    elif restriction == "readonly":
        obj.data.is_editable = False
    elif restriction == "edit":
        obj.mode = "EDIT"
    elif restriction == "corners":
        monkeypatch.setattr(module, "MAX_LOOPS", 2)
    elif restriction == "layer_count":
        monkeypatch.setattr(module, "MAX_LAYERS", 1)
    else:
        obj.data.attributes[".pn.New"] = object()
    with pytest.raises(Exception) as error:
        module.layer_create(context, params(new_name="New"))
    assert error.value.code in {"INVALID_ARGUMENT", "NOT_IMPLEMENTED", "INVALID_MODE"}
    assert collection.keys() == ["Source"]


def test_layer_copy_is_exact_and_preserves_existing_roles(layers):
    module, obj, collection, context = layers
    result = module.layer_create(context, params(new_name="Copy", copy_from="Source"))
    assert collection["Copy"].uv.values == collection["Source"].uv.values
    assert collection["Copy"].pin.values == collection["Source"].pin.values
    assert collection["Copy"].vertex_selection.values == [True] * 4
    assert result["uv_selection_policy"] == "COPY_PER_LAYER"
    assert all(result["after"][role] == "Source" for role in ("active", "render", "clone"))
    assert module._state(obj)["layers"] == ["Source", "Copy"]


def test_layer_rename_activate_and_confirmed_remove(layers):
    module, _, collection, context = layers
    module.layer_create(context, params(new_name="Copy"))
    assert not module.layer_rename(context, params(uv_layer="Copy", new_name="Copy"))["changed"]
    module.layer_rename(context, params(uv_layer="Copy", new_name="Renamed"))
    result = module.layer_activate(context, params(uv_layer="Renamed", for_render=True))
    assert result["after"]["active"] == result["after"]["render"] == "Renamed"
    assert result["after"]["clone"] == "Source"
    module.layer_activate(context, params(uv_layer="Source"))
    module.layer_remove(context, params(uv_layer="Renamed", confirm_remove=True))
    assert collection.keys() == ["Source"]


def test_copy_failure_removes_only_new_layer_and_restores_roles(layers):
    module, obj, collection, context = layers
    before = module._state(obj)
    collection.fail_copy = True
    with pytest.raises(Exception) as error:
        module.layer_create(context, params(new_name="Copy", copy_from="Source"))
    assert error.value.code == "OPERATION_FAILED" and error.value.context["rollback_verified"]
    assert module._state(obj) == before and collection["Source"].uv.values[2] == 1


def test_unexpected_native_name_removes_actual_created_layer(layers, monkeypatch):
    module, obj, collection, context = layers
    before = module._state(obj)
    original_new = collection.new

    def renamed(**kwargs):
        created = original_new(**kwargs)
        created.name = "Unexpected Native Suffix"
        return created

    monkeypatch.setattr(collection, "new", renamed)
    with pytest.raises(Exception) as error:
        module.layer_create(context, params(new_name="Requested"))
    assert error.value.code == "OPERATION_FAILED" and error.value.context["rollback_verified"]
    assert module._state(obj) == before


def test_create_deadline_after_mutation_restores_inventory(layers, addon_package):
    module, obj, _, context = layers
    errors = importlib.import_module(f"{addon_package}.errors")
    before = module._state(obj)
    checks = []

    def cancel():
        checks.append(True)
        if len(checks) == 2:
            raise errors.BridgeError(errors.ErrorCode.TIMEOUT, "expired")

    context.check_cancelled = cancel
    with pytest.raises(Exception) as error:
        module.layer_create(context, params(new_name="Copy", copy_from="Source"))
    assert error.value.code == "TIMEOUT" and error.value.context["rollback_verified"]
    assert module._state(obj) == before


def test_absent_optional_pin_storage_is_false_not_missing_coordinates(layers):
    module, obj, collection, _ = layers
    collection["Source"].pin = Buffer([])
    assert module._read_buffer(obj, "Source", "pin", "value", 1) == [False] * 4
    module._write_buffer(obj, "Source", "pin", "value", [False] * 4)
    collection["Source"].uv = Buffer([], 2)
    with pytest.raises(Exception) as error:
        module._read_buffer(obj, "Source", "uv", "vector", 2)
    assert error.value.code == "NOT_IMPLEMENTED"
