from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.mark.parametrize(
    "handler", ["assign_material", "unassign_material", "add_material_slot", "remove_material_slot"]
)
@pytest.mark.parametrize(
    "condition",
    [
        "shared",
        "object_library",
        "data_library",
        "object_override",
        "data_override",
        "readonly",
        "edit_mode",
    ],
)
def test_slot_mutators_reject_unsupported_ownership_before_mutation(
    addon_package, monkeypatch, handler, condition
):
    mod = importlib.import_module(f"{addon_package}.tools.materials")
    original = NS(name="Original")
    data = NS(materials=[original], users=1)
    obj = NS(name="Target", mode="OBJECT", data=data, active_material_index=0)
    if condition == "shared":
        data.users = 2
    elif condition == "edit_mode":
        obj.mode = "EDIT"
    elif condition == "readonly":
        data.is_editable = False
    else:
        owner, attribute = condition.split("_")
        setattr(
            obj if owner == "object" else data,
            "override_library" if attribute == "override" else "library",
            NS(),
        )
    monkeypatch.setattr(mod, "get_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(mod, "_material_exact", lambda *args: NS(name="Replacement"))
    with pytest.raises(mod.BridgeError) as caught:
        getattr(mod, handler)(
            None, {"object_name": "Target", "material_name": "Replacement", "slot_index": 0}
        )
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert data.materials == [original] and obj.active_material_index == 0


def test_slot_guard_accepts_local_single_user_curve_data(addon_package):
    mod = importlib.import_module(f"{addon_package}.tools.materials")
    data = NS(materials=[], users=1)
    obj = NS(name="Curve", mode="OBJECT", type="CURVE", data=data)
    assert mod._editable_slots(obj) is data.materials


def test_slot_guard_rejects_oversized_arrays(addon_package):
    mod = importlib.import_module(f"{addon_package}.tools.materials")
    obj = NS(name="Target", mode="OBJECT", data=NS(materials=[None] * 257, users=1))
    with pytest.raises(mod.BridgeError) as caught:
        mod._editable_slots(obj)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("handler", ["assign_material", "add_material_slot"])
def test_slot_append_rejects_full_capacity(addon_package, monkeypatch, handler):
    mod = importlib.import_module(f"{addon_package}.tools.materials")
    obj = NS(name="Target", mode="OBJECT", data=NS(materials=[None] * 256, users=1))
    monkeypatch.setattr(mod, "get_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(mod, "_material_exact", lambda *args: NS(name="New"))
    with pytest.raises(mod.BridgeError) as caught:
        getattr(mod, handler)(
            None, {"object_name": "Target", "material_name": "New", "slot_index": 256}
        )
    assert caught.value.code == "INVALID_ARGUMENT" and len(obj.data.materials) == 256
