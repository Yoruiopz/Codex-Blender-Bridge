"""Presence models never resolve runtime settings or accept stored groups."""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


class Properties(list):
    pass


class Prop(NS):
    def as_pointer(self):
        return id(self)


@pytest.fixture
def runtime_case(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.tools._simulation_runtime")
    errors = importlib.import_module(f"{addon_package}.errors")
    calls = []
    class Mesh:
        @property
        def cycles(self):
            raise AssertionError("Runtime pointer getter must not run")
    p = Prop(identifier="cycles", type="POINTER", is_runtime=True,
             is_readonly=True, is_registered=False,
             fixed_type=NS(identifier="CyclesMeshSettings"))
    rna = NS(identifier="Mesh", properties=Properties([p]), as_pointer=lambda: 42)
    Mesh.bl_rna = rna
    owner = Mesh()
    present = [False]
    def presence(actual, key, *, ghost):
        assert actual is owner
        calls.append((key, ghost))
        return present[0]
    bpy = NS(types=NS(Mesh=Mesh), app=NS(build_hash=b"62c1db4208e8", version=(4, 5, 14)))
    monkeypatch.setattr(module, "_presence_descriptor", lambda actual, cls: presence)
    return NS(module=module, bpy=bpy, owner=owner, prop=p, rna=rna,
              calls=calls, present=present, errors=errors, Mesh=Mesh)


@pytest.mark.parametrize(("build", "version", "storage"), [
    (b"62c1db4208e8", (4, 5, 14), "USER"),
    (b"d13f752e3b9c", (5, 2, 2), "SYSTEM"),
])
def test_absence_calls_noncreating_method_with_ghost_false(runtime_case, build, version, storage):
    c = runtime_case
    c.bpy.app.build_hash, c.bpy.app.version = build, version
    result = c.module.absent_runtime(c.bpy, c.owner)
    assert result[0] == (build.decode(), version, storage)
    assert result[-1] == (("cycles", False),)
    assert c.calls == [("cycles", False)]


@pytest.mark.parametrize("present", [True, 0, 1, None, (), ""])
def test_every_present_or_nonboolean_answer_refuses(runtime_case, present):
    c = runtime_case
    c.present[0] = present
    with pytest.raises(c.errors.BridgeError, match="prerequisite") as caught:
        c.module.absent_runtime(c.bpy, c.owner)
    assert caught.value.context["reason"] == "STORED_RUNTIME_REQUIRES_VALUE_READER"
    assert caught.value.context["runtime_getter_invoked"] is False


@pytest.mark.parametrize(("field", "bad"), [
    ("identifier", "extension_runtime"), ("type", "COLLECTION"),
    ("is_readonly", False), ("is_registered", True),
    ("fixed_type", NS(identifier="ForeignSettings")),
])
def test_unreviewed_metadata_refuses_before_presence(runtime_case, field, bad):
    c = runtime_case
    setattr(c.prop, field, bad)
    with pytest.raises(c.errors.BridgeError):
        c.module.absent_runtime(c.bpy, c.owner)
    assert not c.calls


def test_unknown_late_runtime_field_does_not_call_earlier_presence(runtime_case):
    c = runtime_case
    c.rna.properties.append(Prop(identifier="late", type="FLOAT", array_length=0,
                                is_runtime=True, is_readonly=False, is_registered=False))
    with pytest.raises(c.errors.BridgeError):
        c.module.absent_runtime(c.bpy, c.owner)
    assert not c.calls


def test_bounded_before_iteration(runtime_case):
    c = runtime_case
    class Oversized:
        def __len__(self):
            return 513
        def __iter__(self):
            raise AssertionError("Oversized descriptors must not be iterated")
    c.rna.properties = Oversized()
    with pytest.raises(c.errors.BridgeError):
        c.module.absent_runtime(c.bpy, c.owner)
    assert not c.calls


def test_metadata_pointer_drift_after_noncreating_lookup_refuses(runtime_case, monkeypatch):
    c = runtime_case
    def presence(owner, key, *, ghost):
        c.prop.as_pointer = lambda: 999
        return False
    monkeypatch.setattr(c.module, "_presence_descriptor", lambda actual, cls: presence)
    with pytest.raises(c.errors.BridgeError) as caught:
        c.module.absent_runtime(c.bpy, c.owner)
    assert caught.value.context["reason"] == "METADATA_CHANGED_DURING_PRESENCE_READ"


@pytest.mark.parametrize(("build", "version"), [
    (b"62c1db4208e8", (4, 5, 15)), (b"different", (4, 5, 14)),
    ("62c1db4208e8", (4, 5, 14)),
])
def test_unreviewed_build_refuses_before_any_presence(runtime_case, build, version):
    c = runtime_case
    c.bpy.app.build_hash, c.bpy.app.version = build, version
    with pytest.raises(c.errors.BridgeError):
        c.module.absent_runtime(c.bpy, c.owner)
    assert not c.calls


def test_missing_or_replaced_c_method_is_not_invoked(addon_package):
    module = importlib.import_module(f"{addon_package}.tools._simulation_runtime")
    class Base:
        def is_property_set(self, *args, **kwargs):
            raise AssertionError("Python method is not a native presence reader")
    class Mesh(Base):
        pass
    bpy = NS(types=NS(bpy_struct=Base))
    with pytest.raises(Exception, match="prerequisite"):
        module._presence_descriptor(bpy, Mesh)
