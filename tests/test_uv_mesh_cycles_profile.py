"""Portable closed Mesh metadata policy; native C behavior is source-reviewed.

No runtime cycles getter is provided. High-level tests inject only native
presence facts; the inherited-method identity gate is separately exercised
with real CPython method descriptors, without loading Blender.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest
from test_uv_edit_guard import model  # noqa: F401


def rna(identifier, pointer, properties=(), base=None):
    return NS(
        identifier=identifier, as_pointer=lambda: pointer, properties=list(properties), base=base
    )


def prop(name, pointer, kind="STRING", *, runtime=False, readonly=False, fixed=None):
    descriptor = NS(
        identifier=name,
        as_pointer=lambda: pointer,
        type=kind,
        is_runtime=runtime,
        is_readonly=readonly,
        is_registered=False,
        fixed_type=fixed,
    )
    if kind in {"BOOLEAN", "INT", "FLOAT"}:
        descriptor.array_length = 0
    return descriptor


@pytest.fixture
def profile(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.uv_edit_guard")
    errors = importlib.import_module(f"{addon_package}.errors")
    struct = rna("Struct", 900)
    group_fields = [prop("rna_type", 11, "POINTER", readonly=True, fixed=struct), prop("name", 12)]
    group = rna("PropertyGroup", 901, group_fields)
    fixed = rna("CyclesMeshSettings", 902, group_fields, group)
    cycles = prop("cycles", 21, "POINTER", runtime=True, readonly=True, fixed=fixed)
    auto_prop = prop("use_auto_texspace", 22, "BOOLEAN")
    location_prop = prop("texspace_location", 23, "FLOAT")
    size_prop = prop("texspace_size", 24, "FLOAT")
    location_prop.array_length = size_prop.array_length = 3
    fields = [prop("name", 20), cycles, auto_prop, location_prop, size_prop]
    mesh_rna = rna("Mesh", 903, fields)

    class Mesh(dict):
        bl_rna = mesh_rna
        name = "Native Mesh"

        def __init__(self):
            self._auto = True
            self.auto_reads = self.flag_writes = 0
            self.vector_reads = []
            self.location = (1.0, -0.0, 2.0)
            self.size = (3.0, 4.0, 5.0)

        @property
        def use_auto_texspace(self):
            self.auto_reads += 1
            return self._auto

        @use_auto_texspace.setter
        def use_auto_texspace(self, value):
            self.flag_writes += 1
            pytest.fail("The guard must never switch the native AUTO flag")

        @property
        def texspace_location(self):
            if self._auto is not False:
                pytest.fail("AUTO texture-space vector getter must never run")
            self.vector_reads.append("location")
            return self.location

        @property
        def texspace_size(self):
            if self._auto is not False:
                pytest.fail("AUTO texture-space vector getter must never run")
            self.vector_reads.append("size")
            return self.size

        @property
        def cycles(self):
            pytest.fail("The runtime Cycles getter must never run")

        @property
        def is_property_set(self):
            pytest.fail("The instance presence method must never be obtained")

    class bpy_struct:
        pass

    mesh = Mesh()
    bpy = NS(
        types=NS(Mesh=Mesh, PropertyGroup=NS(bl_rna=group), bpy_struct=bpy_struct),
        app=NS(build_hash=b"62c1db4208e8"),
    )
    case = NS(
        module=module,
        errors=errors,
        bpy=bpy,
        mesh=mesh,
        cycles=cycles,
        auto_prop=auto_prop,
        location_prop=location_prop,
        size_prop=size_prop,
        fields=mesh_rna.properties,
        group=group,
        fixed=fixed,
        calls=[],
        present=None,
        authored=None,
        ghost=False,
    )

    def native_presence(owner, name, *, ghost):
        assert owner is mesh and name == "cycles"
        case.calls.append(ghost)
        present = ("cycles" in mesh) if case.present is None else case.present
        if not ghost:
            return present
        return (present and not case.ghost) if case.authored is None else case.authored

    monkeypatch.setattr(module, "_native_method_descriptor", lambda *_: native_presence)
    case.reader = module._NativeReader.__new__(module._NativeReader)
    case.reader.bpy, case.reader.mesh = bpy, mesh
    return case


def test_raw_storage_retains_absent_empty_nonempty_and_ghost_as_distinct_facts(profile):
    case = profile
    absent = case.reader._mesh_primitive()
    case.mesh["cycles"] = {}
    empty = case.reader._mesh_primitive()
    case.ghost = True
    ghost = case.reader._mesh_primitive()
    case.mesh["cycles"] = {"retained": True, "signed": -0.0, "nested": {"values": [1, 0.5]}}
    stored = case.reader._mesh_primitive()
    assert absent[1] == ()
    assert empty[1] == (("cycles", ("group", ())),)
    assert empty[2][-2:] == (True, True) and ghost[2][-2:] == (True, False)
    assert (
        "-0x0.0p+0" in str(stored[1])
        and "retained" in str(stored[1])
        and "nested" in str(stored[1])
    )
    assert len({repr(value) for value in (absent, empty, ghost, stored)}) == 4
    assert case.calls == [False, True] * 4


def test_system_absence_never_uses_raw_user_key_as_presence_or_calls_runtime_getter(profile):
    case = profile
    case.bpy.app.build_hash = b"d13f752e3b9c"
    case.present = False
    case.mesh["cycles"] = {"user_key_not_system_storage": 3}
    values = case.reader._mesh_primitive()
    assert values[2][1] == "SYSTEM_ABSENT" and values[2][-2:] == (False, False)
    assert "user_key_not_system_storage" in str(values[1])
    assert case.calls == [False]


@pytest.mark.parametrize("ghost", [False, True])
def test_any_system_group_including_ghost_refuses_before_runtime_or_raw_fallback(profile, ghost):
    case = profile
    case.bpy.app.build_hash, case.present, case.ghost = b"d13f752e3b9c", True, ghost
    with pytest.raises(case.errors.BridgeError) as caught:
        case.reader._mesh_primitive()
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert caught.value.context == {
        "mesh_cycles_storage_readable": False,
        "runtime_getter_fallback_used": False,
    }
    assert case.calls == [False]


@pytest.mark.parametrize(
    "fault", ["foreign", "fixed_type", "group_field", "readonly", "registered", "kind", "absent"]
)
def test_unreviewed_schema_is_refused_before_presence_or_runtime_getters(profile, fault):
    case = profile
    if fault == "foreign":
        case.fields.append(prop("untrusted", 31, "POINTER", runtime=True))
    elif fault == "fixed_type":
        case.cycles.fixed_type = rna("ForeignSettings", 31)
    elif fault == "group_field":
        case.fixed.properties.append(prop("untrusted", 31, runtime=True))
    elif fault == "readonly":
        case.cycles.is_readonly = False
    elif fault == "registered":
        case.cycles.is_registered = True
    elif fault == "kind":
        case.cycles.type = "COLLECTION"
    else:
        case.fields.remove(case.cycles)
    with pytest.raises(case.errors.BridgeError) as caught:
        case.reader._mesh_primitive()
    assert caught.value.code == "NOT_IMPLEMENTED" and case.calls == []


@pytest.mark.parametrize("present", [1, None, "false"])
def test_nonboolean_native_presence_is_not_coerced(profile, present):
    case = profile
    # None normally requests the fixture's raw-presence fact; use a distinct
    # explicit callable here to exercise the native-result type boundary.
    case.module._native_method_descriptor = lambda *_: lambda *args, **kwargs: present
    with pytest.raises(case.errors.BridgeError) as caught:
        case.reader._mesh_primitive()
    assert caught.value.code == "NOT_IMPLEMENTED"


def test_raw_group_mismatch_and_unsupported_payload_fail_closed(profile):
    case = profile
    case.present = True
    with pytest.raises(case.errors.BridgeError):
        case.reader._mesh_primitive()
    case.mesh["cycles"] = 4
    with pytest.raises(case.errors.BridgeError):
        case.reader._mesh_primitive()
    case.mesh["cycles"] = {"unreadable": object()}
    with pytest.raises(case.errors.BridgeError):
        case.reader._mesh_primitive()


def test_unknown_build_refuses_before_native_presence(profile):
    profile.bpy.app.build_hash = b"unreviewed"
    with pytest.raises(profile.errors.BridgeError):
        profile.reader._mesh_primitive()
    assert profile.calls == [] and profile.mesh.auto_reads == 0 and profile.mesh.vector_reads == []


def test_descriptor_identity_is_retained_even_when_name_and_value_match(profile):
    case = profile
    original = case.reader._mesh_primitive()
    case.cycles.as_pointer = lambda: 999
    changed = case.reader._mesh_primitive()
    assert original[:2] == changed[:2] and original[2] != changed[2]


@pytest.mark.parametrize("kind", ["STRING", "ENUM", "POINTER", "COLLECTION"])
def test_nonnumeric_metadata_never_looks_up_numeric_array_api(profile, kind):
    class NativeShape(NS):
        @property
        def array_length(self):
            pytest.fail("Nonnumeric RNA metadata has no numeric array API")

    descriptor = NativeShape(**vars(prop("field", 777, kind, fixed=rna("Struct", 778))))
    assert profile.module._property_signature(descriptor) == (
        "field", kind, False, False, False, ("NON_ARRAY", None),
        "Struct" if kind in {"POINTER", "COLLECTION"} else None, 777,
    )


def test_realistic_missing_nonnumeric_array_api_preserves_closed_cycles_policy(profile):
    case = profile
    assert not hasattr(case.cycles, "array_length")
    assert all(not hasattr(item, "array_length") for item in case.fixed.properties)
    result = case.reader._mesh_primitive()
    schemas = (result[2][3], result[2][5], result[2][7])
    for schema in schemas:
        for signature in schema:
            expected = ("NUMERIC_ARRAY", 3 if signature[0] in {
                "texspace_location", "texspace_size"
            } else 0) if signature[1] in {"BOOLEAN", "INT", "FLOAT"} else ("NON_ARRAY", None)
            assert signature[5] == expected
    assert case.calls == [False, True] and case.mesh.vector_reads == []


@pytest.mark.parametrize("kind", ["BOOLEAN", "INT", "FLOAT"])
def test_missing_numeric_metadata_refuses_before_mode_presence_or_values(profile, kind):
    case = profile
    descriptor = prop("numeric", 801, kind, readonly=True)
    del descriptor.array_length
    case.fields.append(descriptor)
    with pytest.raises(case.errors.BridgeError) as caught:
        case.reader._mesh_primitive()
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert case.mesh.auto_reads == 0 and case.calls == [] and case.mesh.vector_reads == []


@pytest.mark.parametrize("size", [None, False, True, -1, 1.0, "0", 65_537])
def test_malformed_numeric_metadata_is_not_defaulted_or_coerced(profile, size):
    case = profile
    descriptor = prop("numeric", 802, "INT", readonly=True)
    descriptor.array_length = size
    case.fields.append(descriptor)
    with pytest.raises(case.errors.BridgeError) as caught:
        case.reader._mesh_primitive()
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert case.mesh.auto_reads == 0 and case.calls == [] and case.mesh.vector_reads == []


def test_unknown_property_kind_refuses_before_mode_presence_or_values(profile):
    case = profile
    case.fields.append(prop("unknown", 803, "OPAQUE", readonly=True))
    with pytest.raises(case.errors.BridgeError) as caught:
        case.reader._mesh_primitive()
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert case.mesh.auto_reads == 0 and case.calls == [] and case.mesh.vector_reads == []


def test_numeric_descriptor_shape_drift_is_retained_without_value_getter(profile):
    case = profile
    descriptor = prop("metadata_only", 804, "INT", readonly=True)
    case.fields.append(descriptor)
    original = case.reader._mesh_primitive()
    descriptor.array_length = 4
    changed = case.reader._mesh_primitive()
    assert original[:2] == changed[:2] and original[2] != changed[2]
    assert original[2][3][-1][5] == ("NUMERIC_ARRAY", 0)
    assert changed[2][3][-1][5] == ("NUMERIC_ARRAY", 4)


def test_native_method_gate_accepts_only_original_inherited_c_descriptor(addon_package):
    module = importlib.import_module(f"{addon_package}.uv_edit_guard")
    errors = importlib.import_module(f"{addon_package}.errors")

    class NativeChild(dict):
        pass

    assert module._native_method_descriptor(dict, NativeChild, "get") is dict.get
    called = []
    NativeChild.get = lambda *_: called.append(True)
    with pytest.raises(errors.BridgeError):
        module._native_method_descriptor(dict, NativeChild, "get")
    assert called == []


def test_native_method_gate_does_not_call_foreign_metaclass_or_python_method(addon_package):
    module = importlib.import_module(f"{addon_package}.uv_edit_guard")
    errors = importlib.import_module(f"{addon_package}.errors")
    called = []

    class ForeignMeta(type):
        def __subclasscheck__(cls, other):
            called.append(True)
            return True

    class Foreign(metaclass=ForeignMeta):
        pass

    with pytest.raises(errors.BridgeError):
        module._native_method_descriptor(Foreign, dict)

    class PythonBase:
        def is_property_set(self, *args, **kwargs):
            called.append(True)

    with pytest.raises(errors.BridgeError):
        module._native_method_descriptor(PythonBase, PythonBase)
    assert called == []


def test_native_method_gate_never_invokes_an_override_descriptor(addon_package):
    module = importlib.import_module(f"{addon_package}.uv_edit_guard")
    errors = importlib.import_module(f"{addon_package}.errors")
    called = []

    class Adapter:
        def __get__(self, *_):
            called.append(True)
            return dict.get

    class NativeChild(dict):
        get = Adapter()

    with pytest.raises(errors.BridgeError):
        module._native_method_descriptor(dict, NativeChild, "get")
    assert called == []


def test_auto_texture_space_getters_are_never_called_or_adopted_across_copies(profile):
    case = profile
    first = case.reader._mesh_primitive()
    case.mesh.location, case.mesh.size = (9.0, 8.0, 7.0), (6.0, 5.0, 4.0)
    second = case.reader._mesh_primitive()
    assert first == second  # Deliberate omission, not an AUTO-cache preservation claim.
    assert first[2][-4] == (True, "AUTO_CACHE_EXCLUDED", ("texspace_location", "texspace_size"))
    assert "texspace_location" not in dict(first[0]) and "texspace_size" not in dict(first[0])
    assert dict(first[0])["use_auto_texspace"] is True
    assert case.mesh.vector_reads == [] and case.mesh.flag_writes == 0
    assert case.reader.mesh_texspace_profile == "AUTO_CACHE_EXCLUDED"


def test_manual_texture_space_is_copied_exactly_without_flag_or_vector_writes(profile):
    case = profile
    case.mesh._auto = False  # Explicit plain-model manual setup, not a production flag setter.
    value = case.reader._mesh_primitive()
    fields = dict(value[0])
    assert fields["texspace_location"] == (1.0, -0.0, 2.0) and fields["texspace_size"] == (
        3.0,
        4.0,
        5.0,
    )
    assert fields["texspace_location"][1].hex() == "-0x0.0p+0"
    assert value[2][-4] == (False, "MANUAL_PUBLIC_VECTORS", ())
    assert case.mesh.vector_reads == ["location", "size"] and case.mesh.flag_writes == 0


def test_mode_and_manual_source_drift_change_frozen_projection_without_auto_vector_reads(profile):
    case = profile
    automatic = case.reader._mesh_primitive()
    case.mesh._auto = False
    manual = case.reader._mesh_primitive()
    case.mesh.location = (4.0, 5.0, 6.0)
    revised = case.reader._mesh_primitive()
    assert automatic != manual != revised
    case.mesh._auto = True
    read_count = len(case.mesh.vector_reads)
    assert case.reader._mesh_primitive() == automatic
    assert len(case.mesh.vector_reads) == read_count and case.mesh.flag_writes == 0
    # Every native snapshot includes this projection. Existing guard CAS tests
    # independently require preservation changes to refuse without adopting.


@pytest.mark.parametrize("value", [None, 1, "false"])
def test_nonboolean_auto_flag_refuses_before_any_vector_or_presence_read(profile, value):
    case = profile
    case.mesh._auto = value
    with pytest.raises(case.errors.BridgeError):
        case.reader._mesh_primitive()
    assert case.mesh.vector_reads == [] and case.calls == [] and case.mesh.flag_writes == 0


@pytest.mark.parametrize(
    "field,change",
    [
        ("auto_prop", "type"),
        ("auto_prop", "runtime"),
        ("auto_prop", "array"),
        ("location_prop", "type"),
        ("location_prop", "runtime"),
        ("location_prop", "array"),
        ("size_prop", "readonly"),
    ],
)
def test_texture_space_descriptors_are_screened_before_primitive_getters(profile, field, change):
    case = profile
    descriptor = getattr(case, field)
    if change == "type":
        descriptor.type = "STRING"
    elif change == "runtime":
        descriptor.is_runtime = True
    elif change == "array":
        descriptor.array_length = 2
    else:
        descriptor.is_readonly = True
    with pytest.raises(case.errors.BridgeError):
        case.reader._mesh_primitive()
    assert case.mesh.auto_reads == 0 and case.mesh.vector_reads == [] and case.calls == []


@pytest.mark.parametrize(
    "values",
    [
        None,
        (1.0, 2.0),
        (1.0, 2.0, 3.0, 4.0),
        (True, 2.0, 3.0),
        (1, 2.0, 3.0),
        (float("nan"), 2.0, 3.0),
        (float("inf"), 2.0, 3.0),
        (1e40, 2.0, 3.0),
        (0.1, 2.0, 3.0),
    ],
)
def test_manual_texture_space_requires_exact_finite_native_float3_storage(profile, values):
    case = profile
    case.mesh._auto, case.mesh.location = False, values
    with pytest.raises(case.errors.BridgeError):
        case.reader._mesh_primitive()
    assert case.mesh.vector_reads == ["location"] and case.mesh.flag_writes == 0


@pytest.fixture
def guarded_profile(profile, request, monkeypatch):
    bridge = request.getfixturevalue("model")
    original_snapshot = type(bridge.reader).snapshot
    original_preservation = bridge.reader.preservation

    def snapshot(reader):
        projection = profile.reader._mesh_primitive()
        reader.preservation = (
            *original_preservation,
            ("mesh_projection", profile.module._plain(projection)),
        )
        return original_snapshot(reader)

    # Install before the real registry factory capture; never replace a live
    # reader or recapture its plan. Only plain model data are inspected here.
    monkeypatch.setattr(type(bridge.reader), "snapshot", snapshot)
    return profile, bridge


@pytest.mark.parametrize("drift", ["auto_to_manual", "manual_to_auto", "manual_values"])
def test_registered_guard_refuses_texture_projection_drift_without_later_owned_writes(
    guarded_profile, drift
):
    profile, bridge = guarded_profile
    if drift != "auto_to_manual":
        profile.mesh._auto = False
    changed = []

    def provider():
        if len(bridge.reader.writes) != 1 or changed:
            return
        if drift == "auto_to_manual":
            profile.mesh._auto = False
        elif drift == "manual_to_auto":
            profile.mesh._auto = True
        else:
            profile.mesh.location = (8.0, 7.0, 6.0)
        changed.append(True)

    with bridge.admitted() as (guard, _params):
        bridge.provider = provider
        with pytest.raises(bridge.errors.BridgeError) as caught:
            guard.execute()
    assert changed and len(bridge.reader.writes) == 1 and bridge.reader.updates == 0
    facts = caught.value.context["recovery_evidence"]
    assert facts["restoration_refused"] == "STATE_CHANGED"
    assert facts["restoration_attempts"] == 0 and not facts["rollback_verified"]
    assert profile.mesh.flag_writes == 0
