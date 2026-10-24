"""Provider container-kind and numeric-storage edits cannot cross Scene CAS."""

from __future__ import annotations

import importlib

import pytest
from test_scene_collection_scope import fixture as collection_fixture
from test_scene_mutation_boundaries import env

assert env  # Reuse the native-shaped Scene boundary fixture explicitly.

IDPropertyArray = type("IDPropertyArray", (list,), {"__module__": "idprop.types"})
IDPropertyGroup = type("IDPropertyGroup", (dict,), {"__module__": "idprop.types"})


@pytest.fixture(autouse=True)
def canonical_test_types(env, monkeypatch):
    monkeypatch.setattr(env.proof, "_IDPROPERTY_ARRAY", IDPropertyArray)
    monkeypatch.setattr(env.proof, "_IDPROPERTY_GROUP", IDPropertyGroup)


def array(code, values=()):
    result = IDPropertyArray(values)
    result.typecode = code
    return result


CHANGES = (
    (lambda: IDPropertyGroup(), lambda: array("i")),
    (lambda: array("i"), lambda: IDPropertyGroup()),
    (lambda: IDPropertyGroup(), list), (list, lambda: IDPropertyGroup()),
    (lambda: array("f"), lambda: array("d")),
    (lambda: array("d"), lambda: array("f")),
    (lambda: array("f", (1., 2.)), lambda: array("d", (1., 2.))),
    (lambda: array("d", (1., 2.)), lambda: array("f", (1., 2.))),
    (lambda: array("d"), list), (list, lambda: array("d")),
    (lambda: array("i"), lambda: array("b")),
)


@pytest.mark.parametrize("before,after", CHANGES)
@pytest.mark.parametrize("projection", ("scene_custom", "collection_scope"))
@pytest.mark.parametrize("nested", (False, True))
def test_provider_container_or_array_storage_change_refuses_before_owned_setter(env, addon_package, before, after, projection, nested):
    case = env
    if projection == "scene_custom":
        custom = case.owner.custom_values

        def profile():
            return case.proof.primitive(case.bpy, case.owner)
    else:
        scope = importlib.import_module(f"{addon_package}.tools._scene_collection_scope")
        bpy, scene, _root, _parent, child, _consumers = collection_fixture()
        custom = child.custom

        def profile():
            return scope.snapshot(bpy, scene, child, operation="collection.rename")
    original, newer = before(), after()
    custom["artist"] = {"nested": [original]} if nested else original
    boundary = case.proof.Boundary(case.bpy, case.context, "scene.configure", case.fields, profile)
    expected = boundary.expected_profile
    calls = []
    def edit():
        calls.append(True)
        if nested:
            custom["artist"]["nested"][0] = newer
        else:
            custom["artist"] = newer
    case.provider_hook[0] = edit
    with pytest.raises(case.errors.BridgeError) as caught:
        boundary.write("a", 9.)
    assert caught.value.code == "NOT_IMPLEMENTED" and calls and case.provider_calls
    assert case.owner.setter_calls == [] and boundary.attempted == [] and case.owner.a == 1.
    assert boundary.expected_profile is expected and profile() != expected
    assert (custom["artist"]["nested"][0] if nested else custom["artist"]) is newer


@pytest.mark.parametrize("projection", ("scene_custom", "collection_scope"))
def test_custom_container_storage_is_explicit_and_fixed_rna_defaults_are_unchanged(env, addon_package, projection):
    case = env
    scope = importlib.import_module(f"{addon_package}.tools._scene_collection_scope")

    def encode(raw):
        if projection == "scene_custom":
            return case.proof.value(raw, custom_scalars=True)
        return scope._primitive(raw, [4096], custom_scalars=True)

    assert encode(IDPropertyGroup()) == ("group", ())
    assert encode([]) == ("array", ("list", None), ())
    assert encode(()) == ("array", ("tuple", None), ())
    for code in ("f", "d", "i", "b"):
        assert encode(array(code)) == ("array", ("IDPropertyArray", code), ())
    assert encode(array("f", (1.,))) != encode(array("d", (1.,)))
    assert case.proof.value([{}, array("f", (1.,))]) == ((), (1.,))
    assert scope._primitive([{}, array("d", (1.,))], [4096]) == ((), (1.,))


@pytest.mark.parametrize("code", (None, "q", "", False, ("f",)))
@pytest.mark.parametrize("projection", ("scene_custom", "collection_scope"))
def test_unknown_numeric_custom_array_typecode_refuses_before_iteration(env, addon_package, monkeypatch, code, projection):
    case = env
    def forbidden(_self):
        pytest.fail("Unreviewed custom array payload was iterated")
    kind = type("IDPropertyArray", (list,), {"__module__": "idprop.types", "__iter__": forbidden})
    raw = kind()
    raw.typecode = code
    monkeypatch.setattr(case.proof, "_IDPROPERTY_ARRAY", kind)
    scope = importlib.import_module(f"{addon_package}.tools._scene_collection_scope")
    with pytest.raises(case.errors.BridgeError, match="typecode"):
        (case.proof.value(raw, custom_scalars=True) if projection == "scene_custom"
         else scope._primitive(raw, [4096], custom_scalars=True))


@pytest.mark.parametrize("raw", (b"", b"abc", set(), {1, 2}))
def test_unreviewed_custom_iterable_kinds_fail_closed(env, raw):
    with pytest.raises(env.errors.BridgeError, match="container kind"):
        env.proof.value(raw, custom_scalars=True)


@pytest.mark.parametrize("kind_name", ("IDPropertyGroup", "IDPropertyArray"))
@pytest.mark.parametrize("projection", ("scene_custom", "collection_scope"))
@pytest.mark.parametrize("module_name", ("unreviewed_plugin", "idprop.types"))
def test_custom_container_impostor_module_refuses_before_payload_getters(env, addon_package, kind_name, projection, module_name):
    def forbidden(*_args):
        pytest.fail("Unreviewed custom container getter ran")
    kind = type(kind_name, (), {"__module__": module_name, "keys": forbidden,
                               "__iter__": forbidden, "typecode": property(forbidden)})
    scope = importlib.import_module(f"{addon_package}.tools._scene_collection_scope")
    with pytest.raises(env.errors.BridgeError):
        (env.proof.value(kind(), custom_scalars=True) if projection == "scene_custom"
         else scope._primitive(kind(), [4096], custom_scalars=True))


@pytest.mark.parametrize("projection", ("scene_custom", "collection_scope"))
def test_hostile_unknown_class_cannot_call_back_during_custom_dispatch(env, addon_package, projection):
    callbacks = []
    class HostileMeta(type):
        def __eq__(self, other):
            callbacks.append("equality")
            return False
        def __hash__(self):
            callbacks.append("hash")
            return 0
        def __getattribute__(self, name):
            callbacks.append("class attribute")
            return super().__getattribute__(name)
    class Unknown(metaclass=HostileMeta):
        def __getattribute__(self, name):
            callbacks.append("instance attribute")
            return super().__getattribute__(name)
    raw = Unknown()
    scope = importlib.import_module(f"{addon_package}.tools._scene_collection_scope")
    with pytest.raises(env.errors.BridgeError):
        (env.proof.value(raw, custom_scalars=True) if projection == "scene_custom"
         else scope._primitive(raw, [4096], custom_scalars=True))
    assert callbacks == []


def test_custom_id_pointer_alias_refuses_without_following_it(env):
    class Alias:
        def as_pointer(self):
            pytest.fail("Custom ID alias pointer was followed")
    with pytest.raises(env.errors.BridgeError, match="native references"):
        env.proof.value(Alias(), custom_scalars=True)
