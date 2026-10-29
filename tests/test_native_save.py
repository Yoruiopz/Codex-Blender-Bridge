"""Local native-save policy and canonical runtime composition models."""
from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
import sys
import threading
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import FunctionType, ModuleType
from types import SimpleNamespace as NS

import pytest

# Independent, finite mock metadata. These are C declarations, not values copied
# from native_save_profile.FIELDS or inferred from supplied Python attributes.
# This is a reviewed subset, not a complete class/absence oracle. In particular,
# calls to rna_def_animdata_common do not establish its unretained definition's
# descriptor name/type here. Native class census owns that pending evidence.
# No claim about other classes, getter purity or runtime array lengths follows.
_MOCK_BUILDS = {
    "4.5.14": "62c1db4208e862312bc36db5bc15d4a6dbcfa3e3",
    "5.2.2": "d13f752e3b9c4f8c261cda552b1021f8bcc0382c",
}
_MOCK_SOURCE_PINS = {
    "4.5.14": {
        "rna_ID.cc": "c631c5d8eed753306d6f606b4acaf535457c0276fe9b8922855c07e51af79b0f",
        "rna_scene.cc": "9cc36eae9c30e76f2a42b2470180a3cc53c5f498293fc4918a26fa8dcff2e025",
        "rna_mesh.cc": "1255053013c441f01512436420881ed2ad5100f4e061e33d92500e813620a926",
        "rna_image.cc": "8efba613364194f3d5cbc4aeee9a9e2cb44e9c2b9f54e0ba571c65117e4e7f23",
        "rna_sequencer.cc": "e7cbba3d6179607a779f16c4b44e6326ffc305515881df9348495c93eede3194",
    },
    "5.2.2": {
        "rna_ID.cc": "4c53c551002d84193d14c390a5da578ed43759874b24153e373eccc2f5685caa",
        "rna_scene.cc": "eb9cd754fcd09aee2f8c384dc866a2fd1587bc07da0c9e37922462f336deaa30",
        "rna_mesh.cc": "c1430b06bba90ac1d15918117ae6420821d39e2d98c0f0329df273e4cfcf61af",
        "rna_image.cc": "2584af5d5092adc46d82faf84e2a8482e7cbc5b2222561dc6762d70c99b52b87",
        "rna_sequencer.cc": "45e18b3357f653bce60723fac3d95b6572745a3a9be2bb376ea430354aa5e3fe",
    },
}
_MOCK_ID_FIELDS = {
    "name": "STRING", "library": "POINTER", "override_library": "POINTER",
    "session_uid": "INT", "users": "INT", "use_fake_user": "BOOLEAN",
}
_MOCK_CLASS_FIELDS = {
    "Scene": {
        "collection": "POINTER", "camera": "POINTER", "world": "POINTER", "unit_settings": "POINTER",
        "frame_start": "INT", "frame_end": "INT", "frame_current": "INT", "frame_subframe": "FLOAT",
        "render": "POINTER", "rigidbody_world": "POINTER", "sequence_editor": "POINTER",
    },
    "Mesh": {
        "is_editmode": "BOOLEAN", "shape_keys": "POINTER", "vertices": "COLLECTION", "loops": "COLLECTION",
        "edges": "COLLECTION", "uv_layers": "COLLECTION", "materials": "COLLECTION", "polygons": "COLLECTION",
    },
    "Image": {
        "source": "ENUM", "is_dirty": "BOOLEAN", "has_data": "BOOLEAN", "packed_file": "POINTER",
        "channels": "INT", "size": "INT", "pixels": "FLOAT", "filepath": "STRING",
        "colorspace_settings": "POINTER", "alpha_mode": "ENUM",
    },
}


class _MockDescriptor:
    """Descriptor-only test data; unmeasured metadata remains explicitly unknown."""

    def __init__(self, name, kind, shape=None):
        self.identifier, self.type, self.array_length = name, kind, shape
        self.is_runtime, self.is_readonly = False, None
        self.bl_rna = NS(properties={"array_length": object()} if shape is not None else {})

    @property
    def fixed_type(self):
        pytest.fail("Class census must not follow pointer/collection types")

    @property
    def default(self):
        pytest.fail("Class census must not read defaults")

    @property
    def enum_items(self):
        pytest.fail("Class census must not enumerate dynamic enum values")


def _profile_metadata(rna_type, native_version):
    if native_version not in _MOCK_BUILDS or rna_type not in _MOCK_CLASS_FIELDS:
        raise ValueError("Unreviewed native metadata class/version")
    fields = {**_MOCK_ID_FIELDS, **_MOCK_CLASS_FIELDS[rna_type]}
    if rna_type == "Scene":
        fields["node_tree" if native_version == "4.5.14" else "compositing_node_group"] = "POINTER"
    return {name: _MockDescriptor(name, kind, 2 if rna_type == "Image" and name == "size" else None)
            for name, kind in fields.items()}


def _profile_id(rna_type, name, *, native_version="4.5.14", **fields):
    metadata = _profile_metadata(rna_type, native_version)
    unknown = set(fields) - set(metadata)
    if unknown:
        raise ValueError("Unknown native metadata fields: " + ",".join(sorted(unknown)))
    values = dict(name=name, library=None, override_library=None, as_pointer=lambda: 101,
                  session_uid=102, users=1, use_fake_user=False)
    values.update(fields)
    values["bl_rna"] = NS(identifier=rna_type, properties=metadata)
    return NS(**values)


def _profile_data(module, *, native_version="4.5.14", **families):
    compositor = {"node_tree" if native_version == "4.5.14" else "compositing_node_group": None}
    scene = _profile_id("Scene", "Arbitrary Scene", native_version=native_version,
                        collection=NS(objects=[], children=[]), camera=None, world=None,
                        rigidbody_world=None, sequence_editor=None,
                        unit_settings=NS(system="METRIC", scale_length=1.), frame_start=1, frame_end=2,
                        frame_current=1, frame_subframe=0., render=NS(fps=24, fps_base=1.), **compositor)
    values = {name: [] for name in module.FAMILIES}
    values["scenes"] = [scene]
    values.update(families)
    return NS(**values, bl_rna=NS(properties=[]))


class _SequencerProperties(dict):
    """Model RNA collection lookup and ordered descriptor iteration."""

    def __iter__(self):
        return iter(self.values())


def _sequencer_metadata(native_class, native_version):
    # Independent declarations from the pinned rna_sequencer.cc definitions.
    # These are metadata, not defaults, instance fields or profile constants.
    fields = {
        "SequenceEditor": {"strips": "COLLECTION", "strips_all": "COLLECTION",
                           "meta_stack": "COLLECTION", "channels": "COLLECTION", "active_strip": "POINTER"},
        "SequenceTimelineChannel": {"name": "STRING", "lock": "BOOLEAN", "mute": "BOOLEAN"},
    }[native_class].copy()
    if native_class == "SequenceEditor" and native_version == "4.5.14":
        fields.update(sequences="COLLECTION", sequences_all="COLLECTION")
    if native_class == "SequenceTimelineChannel" and native_version == "5.2.2":
        fields["number"] = "INT"
    properties = _SequencerProperties()
    for name, kind in fields.items():
        descriptor = _MockDescriptor(name, kind, 0 if kind in {"INT", "BOOLEAN"} else None)
        descriptor.is_readonly = kind == "COLLECTION" or name == "number"
        properties[name] = descriptor
    return properties


def _sequencer_channel(native_version, name, lock=False, mute=False, number=0):
    values = dict(name=name, lock=lock, mute=mute,
                  bl_rna=NS(identifier="SequenceTimelineChannel",
                            properties=_sequencer_metadata("SequenceTimelineChannel", native_version)))
    if native_version == "5.2.2":
        values["number"] = number
    return NS(**values)


def _empty_sequencer(native_version, channels=None):
    values = dict(strips=[], strips_all=[], meta_stack=[], active_strip=None,
                  channels=[] if channels is None else channels,
                  bl_rna=NS(identifier="SequenceEditor",
                            properties=_sequencer_metadata("SequenceEditor", native_version)))
    if native_version == "4.5.14":
        values.update(sequences=[], sequences_all=[])
    return NS(**values)


@pytest.fixture
def sequencer_model_origin(addon_package, monkeypatch):
    """Explicit synthetic boundary; these namespaces are not native C objects.

    Payload/metadata tests model the result of origin qualification. Separate
    poison tests exercise the production origin guard without this substitution.
    """
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    monkeypatch.setattr(profile, "_sequencer_origin",
                        lambda owner, _kind: object.__getattribute__(owner, "bl_rna"))


@pytest.mark.parametrize("native_class", ["SequenceEditor", "SequenceTimelineChannel"])
@pytest.mark.parametrize("fault", ["opaque", "spoofed_name", "metaclass_getter", "metaclass_getattr",
                                  "metaclass_call", "module_getattr", "registry_getattr", "registry_name"])
def test_sequencer_origin_refuses_foreign_objects_without_any_instance_class_or_module_getter(
    addon_package, monkeypatch, native_class, fault
):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    calls = []

    def poisoned(*_args, **_kwargs):
        calls.append(fault)
        pytest.fail("Origin refusal must not call any poisoned getter, equality or truth method")

    meta_fields = {"__getattribute__": poisoned} if fault == "metaclass_getter" else {
        "__getattr__": poisoned} if fault == "metaclass_getattr" else {
        "__call__": poisoned} if fault == "metaclass_call" else {}
    meta = type("ForeignMeta", (type,), meta_fields)
    cls = meta("OpaquePointee" if fault == "opaque" else native_class, (), {
        "__module__": "bpy.types", "__getattribute__": poisoned, "__bool__": poisoned,
        "bl_rna": property(poisoned)})
    owner = object.__new__(cls)
    bpy, registry = ModuleType("bpy"), ModuleType("bpy.types")
    if fault == "module_getattr":
        bpy.__getattr__ = poisoned
    else:
        bpy.types = registry
    if fault == "registry_getattr":
        registry.__getattr__ = poisoned
    elif fault == "registry_name":
        class PoisonedName:
            __eq__ = poisoned

        registry.__name__ = PoisonedName()
    # A mutable registry alias is never proof of a native class.
    registry.__dict__[native_class] = cls
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    reason = "SCENE_CACHE_OR_SEQUENCER_UNSUPPORTED" if native_class == "SequenceEditor" else "SEQUENCER_CLASS_UNSUPPORTED"
    with pytest.raises(profile.ProfileRefused, match="^" + reason + "$"):
        profile._sequencer_schema(owner, native_class)
    assert calls == []


def test_opaque_channel_origin_refuses_before_any_channel_getter(addon_package, monkeypatch):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    origin = profile._sequencer_origin
    calls = []

    class OpaqueChannel:
        def __getattribute__(self, name):
            calls.append(name)
            pytest.fail("Opaque channels must refuse before metadata or value getters")

        def __bool__(self):
            calls.append("truth")
            pytest.fail("No channel truth coercion")

    editor = _empty_sequencer("5.2.2", [OpaqueChannel()])
    monkeypatch.setattr(profile, "_sequencer_origin", lambda owner, kind:
                        object.__getattribute__(owner, "bl_rna") if owner is editor else origin(owner, kind))
    with pytest.raises(profile.ProfileRefused, match=r"^SEQUENCER_CLASS_UNSUPPORTED$"):
        profile.empty_sequencer(editor)
    assert calls == []


@pytest.mark.parametrize("native_version,expected", [
    ("4.5.14", "7de0e6a1c42bda3248793a5da173493905f25211727c2045139e8c3b04d461ad"),
    ("5.2.2", "862abe9a25f79c9eebb955c5d104b048da0ce35299faf3883cd98d02941d47d8"),
])
def test_null_sequencer_preserves_exact_pre_extension_canonical_bytes(addon_package, native_version, expected):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    projection = profile.capture(_profile_data(profile, native_version=native_version))
    assert projection.digest == expected
    assert "sequence_editor" not in json.loads(projection.raw)["scenes"][0]


@pytest.mark.parametrize("native_version", _MOCK_BUILDS)
def test_empty_sequencer_preserves_complete_ordered_arbitrary_channel_values(addon_package, sequencer_model_origin, native_version):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    native_channels = [_sequencer_channel(native_version, f"任意 é {128 - index}", bool(index % 2),
                                         bool(index % 3), number=128 - index) for index in range(129)]
    editor = _empty_sequencer(native_version, native_channels)
    data = _profile_data(profile, native_version=native_version)
    data.scenes[0].sequence_editor = editor
    before = [(channel.name, channel.lock, channel.mute) for channel in native_channels]
    projection = profile.capture(data)
    observed = json.loads(projection.raw)["scenes"][0]["sequence_editor"]
    assert observed == {"strips": [], "strips_all": [], "meta_stack": [], "active_strip": None,
                        "native_empty_aliases": ["sequences", "sequences_all"] if native_version == "4.5.14" else [],
                        "channels": [{"name": name, "lock": lock, "mute": mute,
                                      "number": 128 - index if native_version == "5.2.2" else "UNOBSERVED"}
                                     for index, (name, lock, mute) in enumerate(before)]}
    assert [(channel.name, channel.lock, channel.mute) for channel in native_channels] == before
    assert data.scenes[0].sequence_editor is editor
    assert editor.strips == editor.strips_all == editor.meta_stack == []
    native_channels.reverse()
    assert profile.capture(data).raw != projection.raw


@pytest.mark.parametrize("native_version", _MOCK_BUILDS)
@pytest.mark.parametrize("field,value", [("name", "renamed 非標準"), ("lock", True), ("mute", True),
                                         ("number", 42)])
def test_empty_sequencer_channel_drift_changes_projection(addon_package, sequencer_model_origin, native_version, field, value):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    channel = _sequencer_channel(native_version, "Free name")
    editor = _empty_sequencer(native_version, [channel])
    before = profile.canonical(profile.empty_sequencer(editor))
    setattr(channel, field, value)
    after = profile.canonical(profile.empty_sequencer(editor))
    assert (after == before) is (field == "number" and native_version == "4.5.14")


@pytest.mark.parametrize("field", ["strips", "strips_all", "meta_stack", "active_strip", "sequences", "sequences_all"])
def test_nonempty_sequencer_refuses_with_one_sentinel_and_no_strip_traversal(addon_package, sequencer_model_origin, field):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")

    class Nonempty:
        def __len__(self):
            pytest.fail("Emptiness proof must not query collection length")

        def __iter__(self):
            yield object()
            pytest.fail("Only one sentinel may be consumed")

    editor = _empty_sequencer("4.5.14")
    setattr(editor, field, object() if field == "active_strip" else Nonempty())
    with pytest.raises(profile.ProfileRefused, match="NONEMPTY_SEQUENCER_UNSUPPORTED"):
        profile.empty_sequencer(editor)


def test_top_level_strips_refuse_before_recursive_collection_getter(addon_package, sequencer_model_origin):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")

    class Editor:
        bl_rna = _empty_sequencer("5.2.2").bl_rna
        strips = (object(),)

        @property
        def strips_all(self):
            pytest.fail("Recursive getter allocates; top-level strips must refuse first")

        def __getattr__(self, _name):
            pytest.fail("No further editor values before top-level empty proof")

    with pytest.raises(profile.ProfileRefused, match="NONEMPTY_SEQUENCER_UNSUPPORTED"):
        profile.empty_sequencer(Editor())


@pytest.mark.parametrize("owner_kind,fault", [(kind, fault) for kind in ("editor", "channel")
    for fault in ("class", "missing", "identifier", "type", "runtime", "readonly", "array", "unknown_field")
    if (kind, fault) != ("editor", "array")])
def test_sequencer_malformed_schema_refuses_before_any_owner_values(addon_package, sequencer_model_origin, fault, owner_kind):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    native_class = "SequenceEditor" if owner_kind == "editor" else "SequenceTimelineChannel"
    metadata = _sequencer_metadata(native_class, "5.2.2")
    field = "strips" if owner_kind == "editor" else "lock"
    if fault == "missing":
        del metadata[field]
    elif fault == "identifier":
        metadata[field].identifier = "wrong"
    elif fault == "type":
        metadata[field].type = "FLOAT"
    elif fault == "runtime":
        metadata[field].is_runtime = True
    elif fault == "readonly":
        metadata[field].is_readonly = not metadata[field].is_readonly
    elif fault == "array":
        metadata[field].array_length = 1
    elif fault == "unknown_field":
        metadata["new_dependency"] = _MockDescriptor("new_dependency", "COLLECTION" if owner_kind == "editor" else "STRING")

    class Unread:
        bl_rna = NS(identifier="OtherNativeClass" if fault == "class" else native_class, properties=metadata)

        def __getattr__(self, _name):
            pytest.fail("Schema refusal must precede owner values")

    owner = Unread()
    editor = owner if owner_kind == "editor" else _empty_sequencer("5.2.2", [owner])
    with pytest.raises(profile.ProfileRefused, match=r"SEQUENCER_(CLASS|SCHEMA)_UNSUPPORTED"):
        profile.empty_sequencer(editor)


def test_all_channel_metadata_precedes_first_channel_value(addon_package, sequencer_model_origin):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")

    class UnreadChannel:
        bl_rna = NS(identifier="SequenceTimelineChannel",
                    properties=_sequencer_metadata("SequenceTimelineChannel", "5.2.2"))

        def __getattr__(self, _name):
            pytest.fail("No channel values until every channel schema has qualified")

    bad_channel = _sequencer_channel("5.2.2", "Malformed later row")
    bad_channel.bl_rna.properties["mute"].is_runtime = True
    with pytest.raises(profile.ProfileRefused, match="SEQUENCER_SCHEMA_UNSUPPORTED"):
        profile.empty_sequencer(_empty_sequencer("5.2.2", [UnreadChannel(), bad_channel]))


@pytest.mark.parametrize("native_version", _MOCK_BUILDS)
def test_empty_sequencer_never_reads_cache_prefetch_creation_or_absent_number_getters(addon_package, sequencer_model_origin, native_version):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")

    class Guarded(NS):
        def __getattr__(self, name):
            pytest.fail("Undeclared or creating getter: " + name)

    channel = Guarded(**vars(_sequencer_channel(native_version, "Retained UTF-8 雪", True, True)))
    editor = Guarded(**vars(_empty_sequencer(native_version, [channel])))
    for name, kind in (("cache_raw_size", "INT"), ("cache_final_size", "INT"),
                       ("use_prefetch", "BOOLEAN"), ("selected_retiming_keys", "BOOLEAN")):
        editor.bl_rna.properties[name] = _MockDescriptor(name, kind, 0)
    row = profile.empty_sequencer(editor)
    assert row["channels"][0]["name"] == "Retained UTF-8 雪"
    assert row["channels"][0]["number"] == (0 if native_version == "5.2.2" else "UNOBSERVED")


@pytest.mark.parametrize("field,value", [("name", None), ("name", "\ud800"), ("lock", 1),
                                         ("mute", 0), ("number", True), ("number", 1.)])
def test_empty_sequencer_rejects_malformed_channel_values(addon_package, sequencer_model_origin, field, value):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    channel = _sequencer_channel("5.2.2", "Finite")
    setattr(channel, field, value)
    with pytest.raises(profile.ProfileRefused, match="SEQUENCER_CHANNEL_VALUE_UNSUPPORTED"):
        profile.empty_sequencer(_empty_sequencer("5.2.2", [channel]))


@pytest.mark.parametrize("reported,actual,reason", [(130, 0, "SEQUENCER_CHANNEL_BUDGET"),
                                                   (0, 130, "SEQUENCER_CHANNEL_BUDGET"),
                                                   (2, 1, "SEQUENCER_CHANNEL_LAYOUT_UNSUPPORTED")])
def test_sequencer_channel_budget_and_complete_count_precede_metadata(addon_package, sequencer_model_origin, reported, actual, reason):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")

    class Counted:
        def __len__(self):
            return reported

        def __iter__(self):
            if reported > 129:
                pytest.fail("Overbudget count must refuse before iteration")
            yield from (object() for _index in range(actual))
            if actual > 129:
                pytest.fail("Collection iteration must be bounded")

    with pytest.raises(profile.ProfileRefused, match=reason):
        profile.empty_sequencer(_empty_sequencer("5.2.2", Counted()))


@pytest.mark.parametrize("native_version", _MOCK_BUILDS)
def test_empty_sequencer_census_declares_only_reviewed_metadata(addon_package, native_version):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    types = NS(**{name: NS(bl_rna=NS(properties=_sequencer_metadata(name, native_version), functions=[]))
                  for name in ("SequenceEditor", "SequenceTimelineChannel")})
    census = profile.schema_census(types)
    assert not [row for row in census["mismatches"] if row["class"].startswith("Sequence")]
    fields = census["classes"]["SequenceTimelineChannel"]["fields"]
    assert (fields["number"]["metadata"] is None) is (native_version == "4.5.14")
    assert fields["lock"]["metadata"]["array_length"] == fields["mute"]["metadata"]["array_length"] == 0


def test_empty_sequencer_census_refuses_writable_channel_number_metadata(addon_package):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    metadata = _sequencer_metadata("SequenceTimelineChannel", "5.2.2")
    metadata["number"].is_readonly = False
    census = profile.schema_census(NS(SequenceTimelineChannel=NS(bl_rna=NS(properties=metadata, functions=[]))))
    assert {"class": "SequenceTimelineChannel", "field": "number", "reason": "FIELD_METADATA_MISMATCH"} in census["mismatches"]


@pytest.mark.parametrize("rna_type,field", [("Scene", "rigid_body_world"), ("Scene", "polygon"),
    ("Mesh", "rigidbody_world"), ("Mesh", "vertexes"), ("Image", "color_space_settings"),
    ("Image", "animation_data"), ("Scene", "bl_rna")])
def test_profile_mock_cannot_invent_native_descriptors_from_keyword_arguments(rna_type, field):
    with pytest.raises(ValueError, match="Unknown native metadata fields"):
        _profile_id(rna_type, "Arbitrary asset", **{field: object()})


@pytest.mark.parametrize("native_version", _MOCK_BUILDS)
def test_profile_mock_scene_uses_exact_native_rigidbody_spelling_and_compositor_schema(addon_package, native_version):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    data = _profile_data(profile, native_version=native_version)
    scene = data.scenes[0]
    assert scene.bl_rna.properties["rigidbody_world"].type == "POINTER"
    assert "rigid_body_world" not in scene.bl_rna.properties
    scene.rigid_body_world = object()  # A Python attribute never supplies native metadata.
    with pytest.raises(profile.ProfileRefused, match="NATIVE_DESCRIPTOR_REQUIRED"):
        profile.screen(scene, ["rigid_body_world"])
    expected_compositor = "node_tree" if native_version == "4.5.14" else "compositing_node_group"
    assert profile.empty_compositor(scene) == [expected_compositor]
    with pytest.raises(ValueError, match="Unknown native metadata fields"):
        _profile_id("Scene", "Wrong compositor", native_version=native_version,
                    **{"compositing_node_group" if native_version == "4.5.14" else "node_tree": None})


@pytest.mark.parametrize("native_version", _MOCK_BUILDS)
def test_profile_declared_mock_classes_match_independent_source_metadata(addon_package, native_version):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    for family, rna_type in (("scenes", "Scene"), ("meshes", "Mesh"), ("images", "Image")):
        assert set(profile.FIELDS[family].split()) <= set(_profile_metadata(rna_type, native_version))
    assert "polygons" in profile.FIELDS["meshes"].split()
    scene = _profile_data(profile, native_version=native_version)
    assert profile.capture(scene).raw


def test_profile_mock_preserves_c_declared_types_and_unmeasured_dynamic_length():
    scene, mesh, image = (_profile_metadata(name, "4.5.14") for name in ("Scene", "Mesh", "Image"))
    assert scene["frame_current"].type == "INT" and scene["frame_subframe"].type == "FLOAT"
    assert mesh["vertices"].type == "COLLECTION" and mesh["is_editmode"].type == "BOOLEAN"
    assert image["source"].type == "ENUM" and image["packed_file"].type == "POINTER"
    assert image["size"].type == "INT" and image["size"].array_length == 2
    assert image["pixels"].type == "FLOAT" and image["pixels"].array_length is None


def _profile_metadata_types(native_version):
    # Empty function lists are chosen model data, not a native function census.
    # Every class outside the independent three-class oracle stays missing.
    return NS(**{name: NS(bl_rna=NS(properties=_profile_metadata(name, native_version), functions=[]))
                 for name in _MOCK_CLASS_FIELDS})


@pytest.mark.parametrize("native_version", _MOCK_BUILDS)
def test_profile_census_uses_only_independent_metadata_and_records_unmodeled_classes(addon_package, native_version):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    census = profile.schema_census(_profile_metadata_types(native_version))
    present = {name for name, row in census["classes"].items() if row["present"]}
    assert present == {"Scene", "Mesh", "Image"}
    assert not [row for row in census["mismatches"] if row["class"] in present]
    missing = {row["class"] for row in census["mismatches"] if row["reason"] == "CLASS_MISSING"}
    assert missing == set(profile.DECLARED_RNA) - present
    scene = census["classes"]["Scene"]["fields"]
    assert scene["rigidbody_world"]["metadata"]["type"] == "POINTER"
    assert scene["animation_data"]["metadata"] is None  # Unmodeled, not proof of native absence.
    assert census["classes"]["Image"]["fields"]["size"]["metadata"]["array_length"] == 2
    assert "array_length" not in census["classes"]["Image"]["fields"]["pixels"]["metadata"]


@pytest.mark.parametrize("fault", ["unknown_field", "wrong_type", "wrong_shape"])
def test_profile_census_collects_unknown_field_type_and_shape_without_instance_reads(addon_package, monkeypatch, fault):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    types = _profile_metadata_types("4.5.14")
    if fault == "unknown_field":
        monkeypatch.setitem(profile.DECLARED_RNA, "Scene", profile.DECLARED_RNA["Scene"] + " rigid_body_world:POINTER")
        expected = {"class": "Scene", "field": "rigid_body_world", "reason": "FIELD_MISSING"}
    elif fault == "wrong_type":
        types.Scene.bl_rna.properties["rigidbody_world"].type = "FLOAT"
        expected = {"class": "Scene", "field": "rigidbody_world", "reason": "FIELD_METADATA_MISMATCH"}
    else:
        types.Image.bl_rna.properties["size"].array_length = 3
        expected = {"class": "Image", "field": "size", "reason": "FIELD_SHAPE_MISMATCH"}
    census = profile.schema_census(types)
    known = [row for row in census["mismatches"] if row["class"] in _MOCK_CLASS_FIELDS]
    assert known == [expected]


def test_reader_failure_stage_and_reason_contract_matches_strict_process_validator(addon_package):
    reader = importlib.import_module(f"{addon_package}.native_save_reader")
    process = importlib.import_module(f"{addon_package}.native_save_process")
    assert reader.FAILURE_STAGES == process.FAILURE_STAGES
    assert len(reader.FAILURE_STAGES) == 11 and all(len(stage) <= 32 for stage in reader.FAILURE_STAGES)
    assert reader.PROFILE_REASON_PATTERN == process.PROFILE_REASON_PATTERN


@pytest.mark.parametrize("reason", ["UNSUPPORTED_ID_FAMILY:palettes", "NATIVE_DESCRIPTOR_REQUIRED:ParticleEdit.scene",
                                  "PACKED_BYTE_BUDGET"])
def test_reader_exports_only_bounded_exact_profile_code_without_stringifying(addon_package, monkeypatch, reason):
    reader = importlib.import_module(f"{addon_package}.native_save_reader")
    profile = importlib.import_module(f"{addon_package}.native_save_profile")

    def no_text(_self):
        pytest.fail("Failure diagnostics must not call exception str/repr")

    monkeypatch.setattr(profile.ProfileRefused, "__str__", no_text)
    monkeypatch.setattr(profile.ProfileRefused, "__repr__", no_text)
    error = reader._failure(profile.ProfileRefused(reason), "projection_capture", profile.ProfileRefused)
    assert error == {"code": "NATIVE_SAVE_READER_FAILED", "type": "ProfileRefused",
                     "failure_stage": "projection_capture", "profile_reason": reason}


@pytest.mark.parametrize("args", [(), ("/private/SECRET.blend",), ("CODE\nSECRET",), ("CODE:é",), ("X" * 161,),
                                 ("CODE", "SECRET"), (None,), ({"SECRET": "path"},)])
def test_reader_omits_unsafe_or_noncanonical_profile_arguments(addon_package, args):
    reader = importlib.import_module(f"{addon_package}.native_save_reader")
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    error = reader._failure(profile.ProfileRefused(*args), "projection_capture", profile.ProfileRefused)
    assert error == {"code": "NATIVE_SAVE_READER_FAILED", "type": "ProfileRefused", "failure_stage": "projection_capture"}


def test_reader_arbitrary_exceptions_export_type_only_and_sanitize_nonidentifier_type(addon_package):
    reader = importlib.import_module(f"{addon_package}.native_save_reader")
    profile = importlib.import_module(f"{addon_package}.native_save_profile")

    class HiddenMessage(RuntimeError):
        def __str__(self):
            pytest.fail("No arbitrary message")

        def __repr__(self):
            pytest.fail("No arbitrary representation")

    assert reader._failure(HiddenMessage("/private/SECRET.blend"), "native_open", profile.ProfileRefused) == {
        "code": "NATIVE_SAVE_READER_FAILED", "type": "HiddenMessage", "failure_stage": "native_open"}
    unsafe_type = type("/private/SECRET.blend", (RuntimeError,), {})
    assert reader._failure(unsafe_type("SECRET"), "native_open", profile.ProfileRefused)["type"] == "Exception"
    assert "profile_reason" not in reader._failure(profile.ProfileRefused("CODE"), "native_open", profile.ProfileRefused)


def test_profile_enforces_id_budget_before_copying_collections(addon_package):
    module = importlib.import_module(f"{addon_package}.native_save_profile")

    class CountOnly:
        def __len__(self):
            return 129

        def __iter__(self):
            pytest.fail("Oversized native ID collection must not be copied")

    with pytest.raises(module.ProfileRefused, match="PROFILE_ID_BUDGET"):
        module.capture(_profile_data(module, objects=CountOnly()))


def test_profile_refuses_large_mesh_before_traversing_weights(addon_package):
    module = importlib.import_module(f"{addon_package}.native_save_profile")

    class Vertices:
        def __len__(self):
            return 32769

        def __iter__(self):
            pytest.fail("No vertex/group traversal before the native count budget")

    mesh = _profile_id("Mesh", "Any Mesh", is_editmode=False, shape_keys=None, vertices=Vertices(),
                       loops=[], edges=[], uv_layers=[], materials=[])
    with pytest.raises(module.ProfileRefused, match="MESH_BUDGET"):
        module.capture(_profile_data(module, meshes=[mesh]))


def test_profile_checks_packed_size_before_copying_bytes(addon_package):
    module = importlib.import_module(f"{addon_package}.native_save_profile")

    class Packed:
        size = module.MAX_PACKED_BYTES + 1

        @property
        def data(self):
            pytest.fail("No oversized packed byte copy")

    image = _profile_id("Image", "Any Image", source="FILE", is_dirty=False, has_data=True,
                        packed_file=Packed(), channels=4, size=(2, 2), pixels=None,
                        filepath="//texture.png", colorspace_settings=NS(name="sRGB"), alpha_mode="STRAIGHT")
    with pytest.raises(module.ProfileRefused, match="PACKED_BYTE_BUDGET"):
        module.capture(_profile_data(module, images=[image]))


def _resource_memory(module, *, available=None):
    available = module.LARGE_MEMORY_BYTES if available is None else available
    return {"available_memory_bytes": available, "host_available_memory_bytes": available,
            "visible_cgroup_headroom_bytes": None, "visible_cgroup_levels": 1}


def test_large_resource_sample_includes_every_visible_limiting_ancestor(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.native_save_profile")
    gib = 1024**3
    rows = {"/proc/meminfo": "MemAvailable: 33554432 kB\n", "/proc/self/cgroup": "0::/parent/leaf\n",
            "/proc/self/mountinfo": "1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup2 rw\n",
            "/sys/fs/cgroup/parent/leaf/memory.max": "max\n", "/sys/fs/cgroup/parent/leaf/memory.current": "1\n",
            "/sys/fs/cgroup/parent/memory.max": str(12 * gib), "/sys/fs/cgroup/parent/memory.current": str(9 * gib),
            "/sys/fs/cgroup/memory.max": str(16 * gib), "/sys/fs/cgroup/memory.current": str(4 * gib)}
    reads = []

    def read(path, _maximum):
        reads.append(str(path))
        return rows[str(path)]
    monkeypatch.setattr(module, "_resource_text", read)
    result = module.available_memory_facts()
    assert result == {"available_memory_bytes": 3 * gib, "host_available_memory_bytes": 32 * gib,
                      "visible_cgroup_headroom_bytes": 3 * gib, "visible_cgroup_levels": 3}
    assert {name for name in reads if name.endswith("/memory.current")} == {
        "/sys/fs/cgroup/parent/leaf/memory.current", "/sys/fs/cgroup/parent/memory.current", "/sys/fs/cgroup/memory.current"}


@pytest.mark.parametrize("root,group,suffixes", [("/..", "/", [""]), ("/parent", "/parent/leaf", ["leaf", ""])])
def test_resource_cgroup_namespace_never_invents_hidden_parent_limits(addon_package, root, group, suffixes):
    module = importlib.import_module(f"{addon_package}.native_save_profile")
    paths = module._visible_cgroup_paths("0::" + group, "1 0 0:1 " + root + " /sys/fs/cgroup rw - cgroup2 cgroup2 rw")
    assert [str(path) for path in paths] == ["/sys/fs/cgroup" + ("/" + suffix if suffix else "") for suffix in suffixes]


@pytest.mark.parametrize("root", ["relative", "/parent/../escape", "/../child", "//parent"])
def test_namespace_root_does_not_bypass_mount_root_validation(addon_package, root):
    module = importlib.import_module(f"{addon_package}.native_save_profile")
    with pytest.raises(module.ProfileRefused, match="RESOURCE_CGROUP_UNAVAILABLE"):
        module._visible_cgroup_paths("0::/", "1 0 0:1 " + root + " /sys/fs/cgroup rw - cgroup2 cgroup2 rw")


@pytest.mark.parametrize("fault", ["host_missing", "host_duplicate", "host_bad_integer", "group_missing", "group_escape",
                                  "mount_missing", "limit_bad_integer", "current_missing"])
def test_unknown_large_memory_measurement_refuses_without_guessing(addon_package, monkeypatch, fault):
    module = importlib.import_module(f"{addon_package}.native_save_profile")
    rows = {"/proc/meminfo": "MemAvailable: 16777216 kB\n", "/proc/self/cgroup": "0::/\n",
            "/proc/self/mountinfo": "1 0 0:1 /.. /sys/fs/cgroup rw - cgroup2 cgroup2 rw\n",
            "/sys/fs/cgroup/memory.max": "17179869184", "/sys/fs/cgroup/memory.current": "1"}
    if fault.startswith("host_"):
        rows["/proc/meminfo"] = {"host_missing": "MemFree: 12 kB", "host_duplicate": rows["/proc/meminfo"] * 2,
                                  "host_bad_integer": "MemAvailable: -1 kB"}[fault]
    elif fault == "group_missing":
        rows["/proc/self/cgroup"] = "1:memory:/"
    elif fault == "group_escape":
        rows["/proc/self/cgroup"] = "0::/../escape"
    elif fault == "mount_missing":
        rows["/proc/self/mountinfo"] = "1 0 0:1 / /unrelated rw - cgroup2 cgroup2 rw"
    elif fault == "limit_bad_integer":
        rows["/sys/fs/cgroup/memory.max"] = "unknown"
    else:
        del rows["/sys/fs/cgroup/memory.current"]

    def read(path, _maximum):
        if str(path) not in rows:
            raise OSError("Unavailable synthetic OS metadata")
        return rows[str(path)]
    monkeypatch.setattr(module, "_resource_text", read)
    with pytest.raises(module.ProfileRefused, match="RESOURCE_"):
        module.available_memory_facts()


def test_large_resource_gate_pins_directory_before_space_query_and_rechecks_it(addon_package, monkeypatch, tmp_path):
    module = importlib.import_module(f"{addon_package}.native_save_profile")
    folder = tmp_path / "approved"
    folder.mkdir()
    witness = module.bind_resource_directory(str(folder))
    folder.rename(tmp_path / "old approved")
    folder.mkdir()
    monkeypatch.setattr(module.os, "fstatvfs", lambda _fd: pytest.fail("Space query before pinned ancestry comparison"))
    with pytest.raises(module.ProfileRefused, match="RESOURCE_DIRECTORY_CHANGED"):
        module.check_large_resources(module.MAX_IMAGE_PIXELS, witness)


def test_large_resource_gate_rejects_directory_swap_after_space_query(addon_package, monkeypatch, tmp_path):
    module = importlib.import_module(f"{addon_package}.native_save_profile")
    folder = tmp_path / "approved"
    folder.mkdir()
    witness = module.bind_resource_directory(str(folder))

    def changed(_fd):
        folder.rename(tmp_path / "old approved")
        folder.mkdir()
        return NS(f_bavail=module.LARGE_DISK_BYTES, f_frsize=1)
    monkeypatch.setattr(module.os, "fstatvfs", changed)
    monkeypatch.setattr(module, "available_memory_facts", lambda: _resource_memory(module))
    with pytest.raises(module.ProfileRefused, match="RESOURCE_DIRECTORY_CHANGED"):
        module.check_large_resources(module.MAX_IMAGE_PIXELS, witness)


def test_large_resource_directory_refuses_symlink_without_space_or_target_read(addon_package, monkeypatch, tmp_path):
    module = importlib.import_module(f"{addon_package}.native_save_profile")
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "link").symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(module.os, "fstatvfs", lambda _fd: pytest.fail("No space query through a link"))
    with pytest.raises(module.ProfileRefused, match="RESOURCE_DIRECTORY_"):
        module.bind_resource_directory(str(tmp_path / "link"))


@pytest.mark.parametrize("resource", ["memory", "disk"])
def test_large_capture_resource_floor_precedes_packed_copy_and_float_array(addon_package, monkeypatch, tmp_path, resource):
    module = importlib.import_module(f"{addon_package}.native_save_profile")

    class Packed:
        size = 67_120_000

        @property
        def data(self):
            pytest.fail("Packed data read before resource gate")
    image = _profile_id("Image", "Ordinary 4K", source="FILE", is_dirty=False, has_data=True,
        packed_file=Packed(), channels=4, size=(4096, 4096), pixels=None, filepath="//texture.png",
        colorspace_settings=NS(name="sRGB"), alpha_mode="STRAIGHT")
    witness = module.bind_resource_directory(str(tmp_path))
    monkeypatch.setattr(module, "available_memory_facts", lambda: _resource_memory(module,
        available=module.LARGE_MEMORY_BYTES - 1 if resource == "memory" else module.LARGE_MEMORY_BYTES))
    monkeypatch.setattr(module.os, "fstatvfs", lambda _fd: NS(
        f_bavail=module.LARGE_DISK_BYTES - 1 if resource == "disk" else module.LARGE_DISK_BYTES, f_frsize=1))
    monkeypatch.setattr(module, "array", lambda *_args: pytest.fail("Float allocation before resource gate"))
    with pytest.raises(module.ProfileRefused, match="LARGE_IMAGE_" + resource.upper() + "_BUDGET"):
        module.capture(_profile_data(module, images=[image]), resource_directory=witness)


def test_large_resource_threshold_and_pixel_metadata_are_exact_without_large_allocations(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.native_save_profile")
    monkeypatch.setattr(module, "available_memory_facts", lambda: pytest.fail("Legacy profile must not add OS resource IO"))
    assert module.check_large_resources(module.LEGACY_IMAGE_PIXELS, None) is None
    assert module.projection_image_pixels({"images": [{"size": [4096, 4096]}]}) == 16_777_216
    with pytest.raises(module.ProfileRefused, match="IMAGE_PIXEL_BUDGET"):
        module.projection_image_pixels({"images": [{"size": [4096, 4096]}, {"size": [1, 1]}]})


def test_memoryview_pixel_digest_preserves_every_float32_bit_and_alpha(addon_package):
    import struct
    from array import array

    module = importlib.import_module(f"{addon_package}.native_save_profile")
    values = (-0., .25, .5, 1., .125, 0., .75, .5, 1., .5, .25, 0., .25, .5, .75, 1.)

    class Pixels:
        def __len__(self):
            return 16

        def foreach_get(self, target):
            target[:] = array("f", values)
    image = _profile_id("Image", "Ordinary image", source="FILE", is_dirty=False, has_data=True,
        packed_file=NS(size=3, data=b"PNG"), channels=4, size=(2, 2), pixels=Pixels(), filepath="//texture.png",
        colorspace_settings=NS(name="sRGB"), alpha_mode="STRAIGHT")
    projected = module.capture(_profile_data(module, images=[image]))
    row = json.loads(projected.raw)["images"][0]
    assert row["pixels_sha256"] == hashlib.sha256(struct.pack("<16f", *values)).hexdigest()
    assert projected.resource_checks == ()


def test_embedded_shader_animation_refuses_before_graph_reads(addon_package):
    module = importlib.import_module(f"{addon_package}.native_save_profile")
    tree = NS(bl_rna=NS(properties={key: NS(identifier=key, is_runtime=False)
                                   for key in ("animation_data", "nodes", "links")}), animation_data=object())
    with pytest.raises(module.ProfileRefused, match="NON_OBJECT_ANIMATION_UNSUPPORTED"):
        module.tree_projection(tree, {"nodes": 0, "links": 0})


def test_descriptor_absence_is_recorded_without_inventing_animation_value(addon_package):
    module = importlib.import_module(f"{addon_package}.native_save_profile")

    class Absent:
        bl_rna = NS(properties={})

        @property
        def animation_data(self):
            pytest.fail("Absent native descriptor must not be read")

    assert module.no_animation(Absent()) is False
    assert module.no_animation(NS(bl_rna=NS(properties={"animation_data": NS(
        identifier="animation_data", is_runtime=False)}), animation_data=None)) is True


def test_source_parameters_and_vector_shapes_are_strict(addon_package):
    profile = importlib.import_module(f"{addon_package}.native_save_profile")
    source = importlib.import_module(f"{addon_package}.native_save_source")
    with pytest.raises(profile.ProfileRefused, match="PROFILE_VECTOR_SHAPE"):
        profile.floats(range(17))
    with pytest.raises(source.BridgeError):
        source.parameters({"mode": True, "filepath": "/tmp/a.blend", "overwrite_policy": "NO_CLOBBER"}, source.PREVIEW)


@pytest.fixture
def policy_module(addon_package):
    return importlib.import_module(f"{addon_package}.native_save_policy")


@pytest.fixture
def local_runtime(addon_package, monkeypatch):
    module = importlib.import_module(f"{addon_package}.runtime")
    runtime = module.BridgeRuntime.__new__(module.BridgeRuntime)
    runtime._registered = True
    runtime._native_save_generation, runtime._native_save_local_authority = "owned-generation", object()
    runtime.native_save_policy = module.NativeSaveGrant(runtime._native_save_generation,
                                                       runtime._native_save_local_authority)
    runtime._native_save_policy_origin = runtime.native_save_policy
    runtime.permissions = module.PermissionManager(FunctionType(module._PERMISSION_PROVIDER_CODE, vars(module)))
    runtime.jobs = NS(active=None, cancel_all=lambda *_: None)
    runtime.state = module.BridgeState()
    runtime.command_queue = NS(cancel_all=lambda *_: None)
    runtime.server = NS(stop=lambda: None, start=lambda *_, **__: ("127.0.0.1", 9876))
    runtime.executor = NS(start=lambda: None, stop=lambda: None, evidence=NS(clear=lambda: None))
    runtime.checkpoints = NS(clear=lambda: None, detach=lambda: None, recovery_in_progress=False)
    runtime.registry = NS(reset_enabled_toolsets=lambda: None)
    runtime.glb_stage = module.GLBStageService(runtime)
    runtime._glb_stage_origin = runtime.glb_stage
    runtime.glb_stage._executor_origin = runtime.executor
    monkeypatch.setattr(module, "_RUNTIME", runtime)
    monkeypatch.setattr(module, "bpy", None)
    monkeypatch.setattr(module, "clear_selection_references", lambda: None)
    monkeypatch.setattr(module, "get_task_plans", lambda _state: NS(invalidate_handles=lambda: None))
    return module, runtime


def test_grant_defaults_off_and_requires_exact_local_owner(policy_module):
    owner = object()
    grant = policy_module.NativeSaveGrant("session", owner)
    assert not grant.active() and grant.status()["armed"] is False
    for supplied in (None, True, "local", {"armed": True}, object()):
        with pytest.raises(ValueError):
            grant.arm(supplied, 900)
    for supplied in (None, True, "local", {"armed": True}):
        with pytest.raises(ValueError):
            policy_module.NativeSaveGrant("session", supplied)
    assert not grant.active()


@pytest.mark.parametrize("seconds", [True, False, 0, -1, 1801, 900.0, "900"])
def test_local_grant_duration_is_strict_and_bounded(policy_module, seconds):
    owner = object()
    with pytest.raises(ValueError):
        policy_module.NativeSaveGrant("session", owner).arm(owner, seconds)


@pytest.mark.parametrize("now", [True, False, -1, float("inf"), float("nan"), "0"])
def test_invalid_monotonic_times_do_not_arm(policy_module, now):
    owner = object()
    grant = policy_module.NativeSaveGrant("session", owner)
    with pytest.raises(ValueError):
        grant.arm(owner, 900, now=now)
    assert not grant.active()


def test_statement_identity_epoch_and_expiry_are_not_rebased(policy_module):
    owner = object()
    grant = policy_module.NativeSaveGrant("session", owner)
    original = grant.arm(owner, 900)
    grant.check(original)
    assert grant.active(now=original.expires - 1) and not grant.active(now=original.expires)
    with pytest.raises(FrozenInstanceError):
        original.expires += 100
    with pytest.raises(ValueError):
        grant.check(replace(original))
    with pytest.raises(ValueError):
        grant._statement = replace(original)
    with pytest.raises(ValueError):
        grant.generation = "replacement"
    second = grant.arm(owner, 900)
    assert second.epoch > original.epoch
    with pytest.raises(ValueError):
        grant.check(original)
    grant.revoke()
    with pytest.raises(ValueError):
        grant.check(second)


def test_grant_mutations_and_construction_require_main_thread(policy_module):
    owner = object()
    grant = policy_module.NativeSaveGrant("session", owner)
    failures = []

    def background():
        for function in (lambda: grant.arm(owner, 900), grant.revoke,
                         lambda: policy_module.NativeSaveGrant("session", object())):
            try:
                function()
            except ValueError:
                failures.append(True)

    thread = threading.Thread(target=background)
    thread.start()
    thread.join(2)
    assert not thread.is_alive() and len(failures) == 3 and not grant.active()


def test_canonical_snapshot_calls_base_once_and_never_broadens_ordinary_flags(local_runtime):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()
    reads = []

    class Preferences:
        def __getattr__(self, name):
            reads.append(name)
            return name in {"allow_save_project", "allow_native_save_effects"}

    snapshot = module.permission_snapshot(Preferences())
    properties = module._base_permission_snapshot.__globals__["PREFERENCE_PROPERTIES"]
    assert reads == list(properties.values())
    assert snapshot["NATIVE_SAVE_EFFECTS"] and snapshot["SAVE_PROJECT"]
    assert not snapshot["ACCESS_EXTERNAL_FILES"] and not snapshot["EXECUTE_PYTHON"]
    assert module.native_save_permission_provider_intact()


@pytest.mark.parametrize("fault", ["singleton", "unregistered", "grant", "origin", "authority", "generation"])
def test_noncanonical_or_unready_runtime_cannot_compose_native_authority(local_runtime, monkeypatch, fault):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()
    if fault == "singleton":
        monkeypatch.setattr(module, "_RUNTIME", NS(native_save_policy=runtime.native_save_policy))
    elif fault == "unregistered":
        runtime._registered = False
    elif fault == "grant":
        runtime.native_save_policy = NS(active=lambda: pytest.fail("Foreign grant called"))
    elif fault == "origin":
        runtime._native_save_policy_origin = object()
    elif fault == "authority":
        runtime._native_save_local_authority = object()
    else:
        runtime._native_save_generation = "new-generation"
    assert module.permission_snapshot(NS(allow_native_save_effects=True))["NATIVE_SAVE_EFFECTS"] is False


@pytest.mark.parametrize("fault", ["base_alias", "base_code", "active_code", "guard_code", "generation_code"])
def test_poisoned_composition_helpers_are_detected_before_they_execute(local_runtime, monkeypatch, fault):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()

    def poison(_unused=None):
        raise AssertionError("Poisoned provider helper must not execute")

    if fault == "base_alias":
        monkeypatch.setattr(module, "_base_permission_snapshot", poison)
    else:
        function = {"base_code": module._base_permission_snapshot,
                    "active_code": module.NativeSaveGrant.active,
                    "guard_code": module.native_save_permission_provider_intact,
                    "generation_code": module.NativeSaveGrant.generation.fget}[fault]
        monkeypatch.setattr(function, "__code__", poison.__code__)
    assert module.permission_snapshot(NS(allow_save_project=True))["NATIVE_SAVE_EFFECTS"] is False


def test_wrapper_code_substitution_is_visible_to_the_pinned_caller_guard(local_runtime, monkeypatch):
    module, _runtime = local_runtime
    monkeypatch.setattr(module.permission_snapshot, "__code__", (lambda _prefs: {}). __code__)
    assert not module.native_save_permission_provider_intact()


def test_preinstalled_foreign_provider_is_not_accepted_as_canonical(local_runtime):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()
    runtime.permissions._source = lambda: pytest.fail("Foreign provider must not execute")
    assert not module.native_save_permission_provider_intact()
    assert module.permission_snapshot(NS())["NATIVE_SAVE_EFFECTS"] is False


def test_same_class_foreign_grant_cannot_substitute_for_the_runtime_origin(local_runtime):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()
    foreign = module.NativeSaveGrant(runtime._native_save_generation, runtime._native_save_local_authority)
    foreign.arm(runtime._native_save_local_authority, 900)
    runtime.native_save_policy = foreign
    assert not module.native_save_permission_provider_intact()
    assert module.permission_snapshot(NS())["NATIVE_SAVE_EFFECTS"] is False


@pytest.mark.parametrize("target", ["preferences_alias", "preferences_code", "constructor_code"])
def test_rebound_native_preference_getter_or_constructor_invalidates_provider(local_runtime, monkeypatch, target):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()

    def poison(_unused=None):
        raise AssertionError("Poisoned native preference/constructor code must not execute")

    if target == "preferences_alias":
        monkeypatch.setattr(module, "_preferences", poison)
    else:
        function = module._preferences if target == "preferences_code" else module.BridgeRuntime.__init__
        monkeypatch.setattr(function, "__code__", poison.__code__)
    assert not module.native_save_permission_provider_intact()
    assert module.permission_snapshot(NS())["NATIVE_SAVE_EFFECTS"] is False


def test_provider_from_other_globals_or_closure_is_not_canonical(local_runtime):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()
    runtime.permissions._source = FunctionType(module._PERMISSION_PROVIDER_CODE, dict(vars(module)))
    assert not module.native_save_permission_provider_intact()

    def closure(value):
        return lambda: value

    runtime.permissions._source = closure({"NATIVE_SAVE_EFFECTS": True})
    assert not module.native_save_permission_provider_intact()


def test_partial_module_and_uncreated_singleton_stay_disarmed(local_runtime, monkeypatch):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()
    monkeypatch.setattr(module, "_RUNTIME", None)
    assert not module.native_save_permission_provider_intact()
    assert module.permission_snapshot(NS())["NATIVE_SAVE_EFFECTS"] is False
    monkeypatch.setattr(module, "_RUNTIME", runtime)
    monkeypatch.setattr(module, "_CANONICAL_RUNTIME_CLASS", None)
    assert not module.native_save_permission_provider_intact()
    assert module.permission_snapshot(NS())["NATIVE_SAVE_EFFECTS"] is False


@pytest.mark.parametrize("attribute", ["NativeSaveGrant", "GrantStatement", "POLICY_VERSION"])
def test_rebound_policy_class_or_version_cannot_compose_local_authority(local_runtime, monkeypatch, attribute):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()
    monkeypatch.setattr(module._native_save_policy_module, attribute, object())
    assert module.permission_snapshot(NS())["NATIVE_SAVE_EFFECTS"] is False


def test_canonical_constructor_provider_stays_closure_free():
    source = (Path(__file__).parents[1] / "addon/blender_codex_bridge/runtime.py").read_text()
    tree = ast.parse(source)
    candidates = [node for node in ast.walk(tree) if isinstance(node, ast.Lambda)
                  and isinstance(node.body, ast.Call) and isinstance(node.body.func, ast.Name)
                  and node.body.func.id == "permission_snapshot"]
    assert len(candidates) == 1 and not candidates[0].args.args
    expected = ast.parse("lambda: permission_snapshot(_preferences())", mode="eval").body
    assert ast.dump(candidates[0], include_attributes=False) == ast.dump(expected, include_attributes=False)


@pytest.mark.parametrize("method", ["register", "unregister", "start_server", "stop_server",
                                    "emergency_stop", "prepare_for_file_load", "undo"])
def test_lifecycle_boundaries_revoke_local_permission(local_runtime, method):
    module, runtime = local_runtime
    runtime.arm_native_save_effects()
    if method == "register":
        runtime._registered = False
    if method == "undo":
        module._before_external_undo_redo(None)
    else:
        getattr(runtime, method)()
    assert not runtime.native_save_policy.active()


def test_active_native_save_prevents_renewal_but_not_revocation(local_runtime):
    _module, runtime = local_runtime
    first = runtime.native_save_policy.arm(runtime._native_save_local_authority, 900)
    runtime.jobs.active = NS(kind="project.native_save")
    with pytest.raises(Exception, match="Finish or cancel"):
        runtime.arm_native_save_effects()
    runtime.native_save_policy.check(first)
    runtime.revoke_native_save_effects()
    assert not runtime.native_save_policy.active()


def test_local_operator_presents_effects_and_uses_only_local_runtime_entry(addon_package, monkeypatch):
    reports, events = [], []

    class Operator:
        def report(self, level, message):
            reports.append((level, message))

    class Layout:
        def __init__(self):
            self.labels = []

        def label(self, *, text):
            self.labels.append(text)

        def prop(self, _preferences, name):
            assert name == "native_save_duration_seconds"

    fake_bpy = NS(types=NS(Operator=Operator, Panel=object),
                  props=NS(StringProperty=lambda **_: None, BoolProperty=lambda **_: None))
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    name = f"{addon_package}.ui_native_save_local_test"
    source = Path(__file__).parents[1] / "addon/blender_codex_bridge/ui.py"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    preferences = NS(native_save_duration_seconds=900)
    local = NS(arm_native_save_effects=lambda seconds: events.append(("arm", seconds)),
               revoke_native_save_effects=lambda: events.append(("revoke",)))
    monkeypatch.setattr(module, "get_preferences", lambda _context: preferences)
    monkeypatch.setattr(module, "get_runtime", lambda: local)
    context = NS(window_manager=NS(invoke_props_dialog=lambda _operator, **_kwargs: {"RUNNING_MODAL"}))
    arm = module.BCB_OT_arm_native_save()
    arm.layout = Layout()
    assert arm.invoke(context, object()) == {"RUNNING_MODAL"} and not events
    arm.draw(context)
    assert any("outside the project folder" in text for text in arm.layout.labels)
    assert any("connected clients" in text for text in arm.layout.labels)
    assert arm.execute(context) == {"FINISHED"} and events == [("arm", 900)]
    assert module.BCB_OT_revoke_native_save().execute(context) == {"FINISHED"}
    assert events[-1] == ("revoke",) and not reports
