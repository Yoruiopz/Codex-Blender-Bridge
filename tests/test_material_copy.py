from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest

from mcp_server.tools.materials import MaterialTools


class Material:
    def __init__(self, name, collection):
        self.name = name
        self.collection = collection
        self.library = self.override_library = None
        self.is_editable = True
        self.node_tree = None
        self.users = 0
        self.use_fake_user = False

    def copy(self):
        result = Material(self.name + ".001", self.collection)
        self.collection.append(result)
        return result


class Materials(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Slot:
    def __init__(self, source, override):
        self.link = "DATA"
        self.source = source
        self.override = override
        self.reject_new = False
        self.reject_restore = False

    @property
    def material(self):
        return self.source if self.link == "DATA" else self.override

    @material.setter
    def material(self, value):
        if self.reject_new and value is not None and value.name == "Isolated":
            raise RuntimeError("injected assignment failure")
        if self.reject_restore:
            raise RuntimeError("injected rollback failure")
        assert self.link == "OBJECT"
        if self.override is not None:
            self.override.users -= 1
        self.override = value
        if value is not None:
            value.users += 1


@pytest.fixture
def fixture(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.materials")
    materials = Materials()
    source = Material("Shared", materials)
    latent = Material("LatentOverride", materials)
    materials.extend([source, latent])
    slot = Slot(source, latent)
    properties = dict(library=None, override_library=None, is_editable=True)
    data = NS(materials=[source], users=2, **properties)
    obj = NS(name="Cube", data=data, material_slots=[slot], mode="OBJECT", **properties)
    bpy = NS(data=NS(materials=materials, objects=[obj]))
    monkeypatch.setattr(mod, "require_blender", lambda: bpy)
    monkeypatch.setattr(mod, "get_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(mod, "material_scope", lambda *args: ({"affected_objects": ["Cube"]}, []))
    return mod, materials, source, latent, slot, obj


def call(fixture):
    return fixture[0].copy_for_object(
        None, {"object_name": "Cube", "slot_index": 0, "new_name": "Isolated"}
    )


def test_copy_isolates_object_not_shared_data(fixture):
    _, materials, source, _, slot, obj = fixture
    result = call(fixture)
    assert slot.material == materials.get("Isolated") and slot.link == "OBJECT"
    assert obj.data.materials == [source] and obj.data.users == 2
    assert result["affected_objects"] == ["Cube"]
    assert result["mesh_data_copied"] is False


def test_assignment_failure_restores_latent_override_and_removes_copy(fixture):
    mod, materials, source, latent, slot, obj = fixture
    slot.reject_new = True
    with pytest.raises(mod.BridgeError) as caught:
        call(fixture)
    assert caught.value.context["execution_started"]
    assert caught.value.context["rollback_verified"]
    assert slot.link == "DATA" and slot.material == source and slot.override == latent
    assert obj.data.materials == [source]
    assert materials.get("Isolated") is None


def test_rollback_failure_never_claims_recovery(fixture, monkeypatch):
    mod, _, _, _, slot, _ = fixture

    # Fail while constructing post-state, after the binding was actually changed.
    def fail(*args):
        slot.reject_restore = True
        raise RuntimeError("injected verification failure")

    monkeypatch.setattr(mod, "material_scope", fail)
    with pytest.raises(mod.BridgeError) as caught:
        call(fixture)
    assert caught.value.context["rollback_verified"] is False
    assert caught.value.context["execution_started"] is True


@pytest.mark.parametrize(
    "condition", ["edit", "linked", "override", "readonly", "collision", "empty"]
)
def test_invalid_copy_rejected_before_creating_anything(fixture, condition):
    mod, materials, source, _, slot, obj = fixture
    if condition == "edit":
        obj.mode = "EDIT"
    elif condition == "linked":
        obj.library = object()
    elif condition == "override":
        obj.data.override_library = object()
    elif condition == "readonly":
        obj.data.is_editable = False
    elif condition == "collision":
        source.name = "Isolated"
    else:
        slot.source = None
    before = list(materials)
    with pytest.raises(mod.BridgeError):
        call(fixture)
    assert list(materials) == before and slot.link == "DATA"


def test_mcp_copy_wrapper_forwards_exact_scope():
    class Registry:
        async def call(self, method, params):
            return method, params

    result = asyncio.run(MaterialTools(Registry()).material_copy_for_object("Cube", 0, "Isolated"))
    assert result == (
        "material.copy_for_object",
        {"object_name": "Cube", "slot_index": 0, "new_name": "Isolated"},
    )


@pytest.mark.parametrize("index", [-1, True, 1, "0"])
def test_copy_index_validation_does_not_create_data(fixture, index):
    mod, materials, _, _, slot, _ = fixture
    before = list(materials)
    with pytest.raises(mod.BridgeError):
        mod.copy_for_object(
            None, {"object_name": "Cube", "slot_index": index, "new_name": "Isolated"}
        )
    assert list(materials) == before and slot.link == "DATA"


def test_oversized_graph_is_rejected_before_copy(fixture):
    mod, materials, source, _, slot, _ = fixture
    source.node_tree = NS(nodes=[None] * 257, links=[])
    before = list(materials)
    with pytest.raises(mod.BridgeError, match="256 root nodes"):
        call(fixture)
    assert list(materials) == before and slot.link == "DATA"
