"""Real providers cannot cross Scene CAS with Python-equal custom scalar edits."""

from __future__ import annotations

import importlib

import pytest
from test_scene_collection_scope import fixture as collection_fixture
from test_scene_mutation_boundaries import env  # noqa: F401


CHANGES = ((False, 0), (0, False), (True, 1), (1, True), (0, 0.0), (0.0, 0),
           (0.0, -0.0), (-0.0, 0.0))


@pytest.mark.parametrize("before,after", CHANGES)
@pytest.mark.parametrize("projection", ("scene_custom", "collection_scope"))
@pytest.mark.parametrize("nested", (False, True))
def test_provider_custom_type_or_signed_zero_change_refuses_before_owned_setter(env, addon_package, projection, nested, before, after):
    case = env
    if projection == "scene_custom":
        custom = case.owner.custom_values
        profile = lambda: case.proof.primitive(case.bpy, case.owner)
    else:
        collection_scope = importlib.import_module(f"{addon_package}.tools._scene_collection_scope")
        bpy, scene, _root, _parent, child, _consumers = collection_fixture()
        custom = child.custom
        profile = lambda: collection_scope.snapshot(bpy, scene, child, operation="collection.rename")
    custom["artist"] = {"nested": [before]} if nested else before
    boundary = case.proof.Boundary(case.bpy, case.context, "scene.configure", case.fields, profile)
    frozen = boundary.expected_profile
    calls = []
    def provider_edit():
        calls.append(True)
        if nested:
            custom["artist"]["nested"][0] = after
        else:
            custom["artist"] = after
    case.provider_hook[0] = provider_edit
    with pytest.raises(case.errors.BridgeError) as caught:
        boundary.write("a", 9.0)
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert calls and case.provider_calls
    assert case.owner.setter_calls == [] and boundary.attempted == []
    assert case.owner.a == 1.0 and boundary.expected_profile is frozen
    stored = custom["artist"]["nested"][0] if nested else custom["artist"]
    assert type(stored) is type(after)
    assert stored.hex() == after.hex() if type(after) is float else stored == after
    assert profile() != frozen


def test_custom_encoding_keeps_native_field_and_setter_representation(env, addon_package):
    case = env
    case.owner.custom_values["nested"] = {"array": [None, False, 0, 0.0, -0.0, "text"]}
    custom = dict(case.proof.custom(case.owner))["nested"]
    leaves = dict(custom)["array"]
    assert leaves == (("NoneType", None), ("bool", False), ("int", 0),
                      ("float", "0x0.0p+0"), ("float", "-0x0.0p+0"), ("str", "text"))
    assert case.proof.value([False, 0, 0.0]) == (False, 0, 0.0)
    assert type(case.fields["a"].read(case.bpy)) is float
    boundary = case.make()
    boundary.write("a", 43.1)
    assert type(boundary.expected["a"]) is float
    scope = importlib.import_module(f"{addon_package}.tools._scene_collection_scope")
    assert scope._primitive([False, 0, 0.0], [4096]) == (False, 0, 0.0)


@pytest.mark.parametrize("value", (float("inf"), float("-inf"), float("nan")))
@pytest.mark.parametrize("projection", ("scene_custom", "collection_scope"))
def test_custom_floats_remain_finite_and_bounded(env, addon_package, projection, value):
    case = env
    if projection == "scene_custom":
        case.owner.custom_values["nested"] = {"array": [value]}
        read = lambda: case.proof.custom(case.owner)
    else:
        scope = importlib.import_module(f"{addon_package}.tools._scene_collection_scope")
        _bpy, _scene, _root, _parent, child, _consumers = collection_fixture()
        child.custom["nested"] = {"array": [value]}
        read = lambda: scope._custom(child)
    with pytest.raises(case.errors.BridgeError, match="finite"):
        read()
