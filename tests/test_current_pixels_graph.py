"""Finite metadata/identity models; these are not native graph acceptance."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import warnings
from types import ModuleType
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def graph(addon_package):
    return importlib.import_module(f"{addon_package}.current_pixels_graph")


def test_first_deprecated_RNA_reader_warning_keeps_canonical_cache_and_namespace(graph, addon_package):
    """Python warning/readback model; no Blender getter qualification claim."""
    source = importlib.import_module(addon_package + ".mesh_storage_source")
    registry = graph.__warningregistry__
    assert type(registry) is dict and source.graph is graph
    registry.clear()
    seal = source.SourceSeal.capture()
    namespace = {name: id(value) for name, value in vars(graph).items()}
    entered = []

    class Material:
        @property
        def use_nodes(self):
            entered.append("use_nodes")
            # Native 5.2 RNA attributes the deprecation to its Python caller.
            warnings.warn("'Material.use_nodes' is expected to be removed in Blender 6.0",
                          DeprecationWarning, stacklevel=2)
            return True

    reader = NS(catalog=lambda *_args: [Property("use_nodes", "BOOLEAN")], check=seal.verify)
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("default", DeprecationWarning)
        assert graph._primitive_fields(reader, Material(), "Material") == {"use_nodes": True}
        seal.verify()
        assert graph._primitive_fields(reader, Material(), "Material") == {"use_nodes": True}
        seal.verify()
    assert entered == ["use_nodes", "use_nodes"] and len(observed) == 1
    assert observed[0].category is DeprecationWarning and observed[0].filename == graph.__file__
    assert type(registry["version"]) is int
    assert any(type(key) is tuple and key[1] is DeprecationWarning for key in registry)
    assert graph.__warningregistry__ is registry
    assert {name: id(value) for name, value in vars(graph).items()} == namespace


class Property:
    def __init__(self, name, kind="STRING", *, readonly=False, runtime=False, registered=False,
                 array_length=0, fixed_type=None, enum_flag=False):
        self.identifier, self.type = name, kind
        self.is_readonly, self.is_runtime, self.is_registered = readonly, runtime, registered
        self._array_length, self._fixed_type, self._enum_flag = array_length, fixed_type, enum_flag

    def as_pointer(self):
        """Explicit synthetic native property identity, never a native proof."""
        return id(self)

    @property
    def array_length(self):
        assert self.type in {"BOOLEAN", "INT", "FLOAT"}, "Nonnumeric array metadata is absent"
        return self._array_length

    @property
    def fixed_type(self):
        assert self.type in {"POINTER", "COLLECTION"}, "Nonrelationship fixed type is absent"
        return self._fixed_type

    @property
    def is_enum_flag(self):
        assert self.type == "ENUM", "Nonenum flag metadata is absent"
        return self._enum_flag

    @property
    def default(self):
        pytest.fail("A metadata census must not inspect property defaults")


def rna(name, props=(), pointer=100):
    return NS(identifier=name, base=None, properties=list(props), functions=[], as_pointer=lambda: pointer)


def replace_model_pin(graph, monkeypatch, name, build, supplied):
    """Synthetic metadata updates replace complete immutable table bindings."""
    def frozen(value):
        return tuple((key, frozen(item)) for key, item in value.items()) if type(value) is dict else value
    table = dict(getattr(graph, name))
    table[build] = frozen(supplied)
    monkeypatch.setattr(graph, name, tuple(table.items()))


def install_model_catalogs(graph, monkeypatch, bpy):
    """Explicit synthetic constructor/static/fixed/full metadata assumptions.

    This models C-only constructors and unshadowed C field descriptors with
    plain Python data classes. Actual native constructor/field/registered lookup
    passivity remains root's gate; no permission provider is replaced.
    """
    census = graph.catalog_census(bpy.types, bpy.app.build_hash)
    full, static, targets = {}, {}, {}
    for kind, supplied in census["classes"].items():
        if not supplied["present"]:
            continue
        row = copy.deepcopy(supplied)
        full[kind] = row.pop("sha256")
        targets[kind] = {prop["identifier"]: prop["fixed_type"] for prop in row["properties"]
                         if prop["fixed_type"] is not None}
        for prop in row["properties"]:
            prop["fixed_type"] = None
        static[kind] = hashlib.sha256(graph._canonical(row)).hexdigest()
    replace_model_pin(graph, monkeypatch, "_CATALOG_HASHES", bpy.app.build_hash, full)
    replace_model_pin(graph, monkeypatch, "_STATIC_CATALOG_HASHES", bpy.app.build_hash, static)
    replace_model_pin(graph, monkeypatch, "_FIXED_TARGETS", bpy.app.build_hash, targets)
    placeholders = {}

    def modeled_native_constructor_policy(owner_bpy, name, resolved=None):
        assert owner_bpy is bpy
        canonical = resolved if resolved is not None else getattr(bpy.types, name, None)
        if canonical is None:
            canonical = placeholders.setdefault(name, type(name, (), {"bl_rna": rna(name)}))
        return canonical, canonical.bl_rna, None, None, ()

    monkeypatch.setattr(graph, "_constructor_proof", modeled_native_constructor_policy)
    monkeypatch.setattr(graph, "_unshadowed", lambda _owner, _fields: None)
    return census


def test_complete_ordered_census_preserves_shapes_without_default_or_data_getters(graph):
    owner = type("Image", (), {"bl_rna": rna("Image", [
        Property("name"), Property("has_data", "BOOLEAN", readonly=True),
        Property("size", "INT", array_length=2, readonly=True),
        Property("colorspace_settings", "POINTER", fixed_type=NS(identifier="ColorManagedInputColorspaceSettings")),
        Property("source", "ENUM"), Property("views", "COLLECTION", fixed_type=NS(identifier="ImageView"))])})
    types = NS(Image=owner)
    result = graph.catalog_census(types, b"62c1db4208e8")
    assert result["schema"] == "current_pixels_complete_class_census_v1"
    assert len(result["classes"]) == len(graph.CENSUS_TYPES) == 59
    row = result["classes"]["Image"]
    assert [prop["identifier"] for prop in row["properties"]] == ["name", "has_data", "size", "colorspace_settings", "source", "views"]
    assert row["properties"][2]["array_length"] == 2
    assert row["properties"][3]["array_length"] is None
    assert row["properties"][3]["fixed_type"] == "ColorManagedInputColorspaceSettings"
    assert row["properties"][4]["enum_flag"] is False
    assert row["properties"][0]["enum_flag"] is None
    digest = row.pop("sha256")
    assert hashlib.sha256(graph._canonical(row)).hexdigest() == digest
    assert result["classes"]["Material"] == {"present": False}
    assert not result["methods"]["ID.as_pointer"]["present"]


def test_exact_followon_mapping_classes_are_metadata_only_and_do_not_construct_instances(graph):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Class census cannot create mapping/ramp instances or call their functions")

    classes = {}
    for name, properties in (
            ("TexMapping", [Property("translation", "FLOAT", array_length=3), Property("vector_type", "ENUM")]),
            ("ColorRampElement", [Property("color", "FLOAT", array_length=4), Property("position", "FLOAT")]),
            ("ColorRampElements", []),
            ("ColorRamp", [Property("elements", "COLLECTION", fixed_type=NS(identifier="ColorRampElement")),
                           Property("interpolation", "ENUM")]),
            ("ColorMapping", [Property("color_ramp", "POINTER", fixed_type=NS(identifier="ColorRamp")),
                              Property("blend_color", "FLOAT", array_length=3)])):
        classes[name] = type(name, (), {"bl_rna": rna(name, properties), "__init__": forbidden,
                                        "new": forbidden, "remove": forbidden, "evaluate": forbidden})
    result = graph.catalog_census(NS(**classes), b"d13f752e3b9c")
    added = {"TexMapping", "ColorMapping", "ColorRamp", "ColorRampElement", "ColorRampElements"}
    assert {name for name, row in result["classes"].items() if row["present"]} == added
    assert len(set(graph.CENSUS_TYPES)) == 59
    assert not {"ShaderNodeValToRGB", "CurveMapping", "ShaderNodeGroup"} & set(graph.CENSUS_TYPES)
    color = result["classes"]["ColorMapping"]["properties"][0]
    elements = result["classes"]["ColorRamp"]["properties"][0]
    assert color["type"] == "POINTER" and color["fixed_type"] == "ColorRamp"
    assert elements["type"] == "COLLECTION" and elements["fixed_type"] == "ColorRampElement"
    assert all(row["array_length"] is None for row in (color, elements))


def test_census_reports_static_native_method_metadata_without_invocation(graph):
    class ID:
        as_pointer = list.append

    class Base:
        is_property_set = dict.get

    ID.bl_rna = rna("ID")
    result = graph.catalog_census(NS(ID=ID, bpy_struct=Base), b"d13f752e3b9c")
    assert result["methods"]["ID.as_pointer"] == {"present": True, "descriptor_type": "method_descriptor",
                                                   "declaring_class": "list", "native_descriptor": True}
    assert result["methods"]["bpy_struct.is_property_set"]["declaring_class"] == "dict"


@pytest.mark.parametrize("change", ["duplicate", "runtime_type", "too_many_properties", "too_many_functions", "oversized_array"])
def test_census_refuses_unknown_or_unbounded_class_metadata(graph, change):
    props, functions = [Property("name")], []
    if change == "duplicate":
        props += [Property("name")]
    elif change == "runtime_type":
        props = [Property("unknown", "CALLBACK")]
    elif change == "too_many_properties":
        props = [Property(str(index)) for index in range(513)]
    elif change == "too_many_functions":
        functions = [NS(identifier=str(index)) for index in range(129)]
    else:
        props = [Property("values", "FLOAT", array_length=1_048_577)]
    owner = type("Image", (), {"bl_rna": rna("Image", props)})
    owner.bl_rna.functions = functions
    with pytest.raises(graph.BridgeError):
        graph.catalog_census(NS(Image=owner), b"62c1db4208e8")


@pytest.mark.parametrize("build", [b"unknown", "62c1db4208e8", b"d13f752e3b9c-extra", None])
def test_census_requires_exact_official_build_bytes(graph, build):
    with pytest.raises(graph.BridgeError):
        graph.catalog_census(NS(), build)


def make_identity_model(graph, monkeypatch, addon_package):
    """Explicit synthetic RNA pins for source models; no product bypass exists."""
    storage = importlib.import_module(f"{addon_package}.tools.image_portability")
    calls = []

    class Image:
        bl_rna = rna("Image", [Property("name"), Property("has_data", "BOOLEAN", readonly=True)], 101)
        library = override_library = None
        is_editable = True

        def __init__(self, name, pointer):
            self.name, self.pointer, self.session_uid, self.has_data = name, pointer, pointer, True
            self.owner = None

        def as_pointer(self):
            return self.pointer

        def get(self, key):
            calls.append((self.name, key))
            assert key == storage.OWNER_KEY
            return self.owner

        @property
        def size(self):
            pytest.fail("Pre-grant identity witness cannot read size")

        @property
        def is_float(self):
            pytest.fail("Pre-grant identity witness cannot read is_float")

        @property
        def pixels(self):
            pytest.fail("Pre-grant identity witness cannot read pixels")

        @property
        def packed_file(self):
            pytest.fail("Pre-grant identity witness cannot read packed data")

        @property
        def animation_data(self):
            pytest.fail("Image.animation_data has no admitted native declaration")

    class ShaderNodeTree:
        bl_rna = rna("ShaderNodeTree", [Property("name")], 102)
        library = override_library = None
        is_editable = True
        name, session_uid = "Material Tree", 20

        def as_pointer(self):
            return 20

    class Material:
        bl_rna = rna("Material", [Property("name"), Property("node_tree", "POINTER", fixed_type=ShaderNodeTree.bl_rna)], 103)
        library = override_library = None
        is_editable = True
        name, session_uid = "Material", 30

        def __init__(self):
            self.node_tree = ShaderNodeTree()

        def as_pointer(self):
            return 30

    original, helper, material = Image("Original", 10), Image("Snapshot", 11), Material()
    helper.owner = original
    types = NS(Image=Image, Material=Material, ShaderNodeTree=ShaderNodeTree)
    bpy = NS(types=types, app=NS(build_hash=b"62c1db4208e8", version=(4, 5, 14)),
             data=NS(images={original.name: original, helper.name: helper}, materials={material.name: material}))
    install_model_catalogs(graph, monkeypatch, bpy)
    return NS(bpy=bpy, original=original, helper=helper, material=material, calls=calls, storage=storage,
              Image=Image, ShaderNodeTree=ShaderNodeTree, Material=Material)


@pytest.fixture
def identity_model(graph, monkeypatch, addon_package):
    return make_identity_model(graph, monkeypatch, addon_package)


def test_identity_witness_is_fresh_plain_native_binding_without_lazy_sensitive_getters(graph, identity_model):
    model = identity_model
    result = graph.identity_witness(model.bpy, "Original", "Snapshot", ["Material"])
    assert result["original"] == {"kind": "Image", "name": "Original", "pointer": "a", "session_uid": "10"}
    assert result["snapshot"]["pointer"] == "b" and result["native_owner"] == result["original"]
    assert result["materials"][0]["tree"]["name"] == "Material Tree"
    assert result["original_loaded"] and result["snapshot_loaded"]
    assert "pixels" not in result and "packed" not in result
    json.dumps(result, allow_nan=False)
    result["original"]["name"] = "Caller changed copy"
    assert graph.identity_witness(model.bpy, None, "Snapshot", ["Material"])["original"]["name"] == "Original"


def test_unloaded_helper_refuses_before_owner_or_original_paths(graph, identity_model):
    model = identity_model
    model.helper.has_data = False
    with pytest.raises(graph.BridgeError) as error:
        graph.identity_witness(model.bpy, None, "Snapshot", ["Material"])
    assert error.value.context["reason"] == "TARGET_BUFFER_UNLOADED" and model.calls == []


def test_unloaded_original_is_inspection_only_without_size_float_or_pixels(graph, identity_model):
    model = identity_model
    model.original.has_data = False
    with pytest.raises(graph.BridgeError) as error:
        graph.identity_witness(model.bpy, None, "Snapshot", ["Material"])
    assert error.value.context["reason"] == "TARGET_BUFFER_UNLOADED"
    assert model.calls == [("Snapshot", model.storage.OWNER_KEY)]


@pytest.mark.parametrize("case", ["missing_owner", "foreign_owner", "rebound_name", "wrong_explicit_name", "linked", "readonly", "catalog_drift", "subclass"])
def test_native_identity_or_scope_drift_refuses_without_payload_reads(graph, identity_model, case):
    model, image_name = identity_model, "Original"
    if case == "missing_owner":
        model.helper.owner = None
    elif case == "foreign_owner":
        model.helper.owner = model.material
    elif case == "rebound_name":
        model.bpy.data.images["Original"] = model.Image("Original", 99)
    elif case == "wrong_explicit_name":
        image_name = "Absent"
    elif case == "linked":
        model.original.library = object()
    elif case == "readonly":
        model.original.is_editable = False
    elif case == "catalog_drift":
        model.Image.bl_rna.properties.append(Property("unexpected_python_property", runtime=True))
    else:
        class SubImage(model.Image):
            pass
        model.helper.owner = SubImage("Original", 10)
    with pytest.raises(graph.BridgeError):
        graph.identity_witness(model.bpy, image_name, "Snapshot", ["Material"])


def test_missing_catalog_pin_cannot_be_self_qualified_by_a_census(graph, identity_model, monkeypatch):
    model = identity_model
    observed = graph.catalog_census(model.bpy.types, model.bpy.app.build_hash)
    assert observed["classes"]["Image"]["present"]
    replace_model_pin(graph, monkeypatch, "_CATALOG_HASHES", model.bpy.app.build_hash, {})
    with pytest.raises(graph.BridgeError, match="qualified finite profile"):
        graph.identity_witness(model.bpy, "Original", "Snapshot", ["Material"])
    assert model.calls == []


def test_canonical_lifecycle_record_is_exact_bounded_nonauthorizing_metadata(graph):
    value = {"schema_version": 1, "profile": graph.PROFILE, "record_uuid": "a" * 32,
             "runtime_nonce": "b" * 32, "manifest_sha256": "c" * 64}
    raw = graph._canonical(value).decode()
    assert graph.validate_lifecycle_record(raw) == raw
    for changed in ({**value, "recovery_authorized": True}, {**value, "schema_version": True},
                    {**value, "manifest_sha256": "A" * 64}, {**value, "profile": "unknown"}):
        with pytest.raises(graph.BridgeError):
            graph.validate_lifecycle_record(graph._canonical(changed).decode())
    with pytest.raises(graph.BridgeError):
        graph.validate_lifecycle_record(json.dumps(value))
    with pytest.raises(graph.BridgeError):
        graph.validate_lifecycle_record(raw[:-1] + ',"schema_version":1}')


def test_portable_stream_omits_only_native_tokens_and_preserves_signed_zero(graph):
    row = {"kind": "Mesh", "name": "Mesh", "pointer": "1", "session_uid": "1"}
    first = graph._Stream()
    first.begin(row, consumer=True)
    first.emit("coordinate", graph._vector((0., -0., .5), 3))
    first.end(row)
    second = graph._Stream()
    row2 = {**row, "pointer": "2", "session_uid": "2"}
    second.begin(row2, consumer=True)
    second.emit("coordinate", graph._vector((0., -0., .5), 3))
    second.end(row2)
    assert first.portable.digest() == second.portable.digest()
    assert first.rows[0]["content_sha256"] == second.rows[0]["content_sha256"]
    assert first.native.digest() != second.native.digest()
    third = graph._Stream()
    third.begin(row, consumer=True)
    third.emit("coordinate", graph._vector((0., 0., .5), 3))
    third.end(row)
    assert third.portable.digest() != first.portable.digest()


def test_stream_cap_fails_closed_without_retaining_whole_graph_arrays(graph, monkeypatch):
    stream = graph._Stream()
    stream.emit("small", True)
    before = copy.deepcopy(stream.rows)
    monkeypatch.setattr(graph, "MAX_CANONICAL_BYTES", stream.bytes + 4)
    with pytest.raises(graph.BridgeError):
        stream.emit("larger", ["payload"])
    assert stream.rows == before and stream.content is None


def make_capture_model(graph, monkeypatch, addon_package, *, build=b"62c1db4208e8", pointer_base=1000):
    """Synthetic exact-RNA/Array models, never installed or native acceptance.

    Real graph code, reverse ownership, UV readers and EXR codecs run unchanged.
    Only the C-only Mesh policy witness is modeled; native descriptor origins,
    passive getter behavior and real Blender array lifetimes remain unqualified.
    No PermissionManager or permission provider is substituted by this model.
    """
    import struct
    from array import array

    def native_value(value):
        if type(value) is float:
            return struct.unpack("<f", struct.pack("<f", value))[0]
        if type(value) is tuple:
            return tuple(native_value(item) for item in value)
        if type(value) is list:
            return [native_value(item) for item in value]
        return value

    codec = importlib.import_module(f"{addon_package}.pixel_codecs")
    storage = importlib.import_module(f"{addon_package}.tools.image_portability")
    uv_guard = importlib.import_module(f"{addon_package}.uv_edit_guard")
    types, all_owners, reverse = NS(), [], {}
    counters = {"packed": 0, "pixels": 0, "foreach_get": 0, "checks": 0, "attribute_data": 0}
    live = {"cancelled": False}

    class Native:
        library = override_library = animation_data = None
        is_editable = True
        users = 1
        use_fake_user = False
        is_embedded_data = False

        def __init__(self, **values):
            self.pointer = pointer_base + len(all_owners)
            self.session_uid = self.pointer
            self._custom = {}
            self.__dict__.update({key: native_value(value) for key, value in values.items()})
            all_owners.append(self)

        def as_pointer(self):
            return self.pointer

        def keys(self):
            return self._custom.keys()

        def get(self, key, default=None):
            return self._custom.get(key, default)

        def __getitem__(self, key):
            return self._custom[key]

        def __setitem__(self, key, value):
            self._custom[key] = value

        def user_of_id(self, target):
            if self.bl_rna.identifier == "Scene":
                master = self.collection
                count = int(master is target)
                count += sum(owner is target for owner in master.children)
                count += sum(owner is target for owner in master.objects)
                for layer in self.view_layers:
                    pending = [layer.layer_collection]
                    while pending:
                        item = pending.pop()
                        count += int(item.collection is target)
                        pending.extend(item.children)
                    count += sum(owner is target for owner in layer.objects)
                return count + self._custom.get("_synthetic_extra_count", {}).get(target, 0)
            if self.bl_rna.identifier == "Collection":
                return (sum(owner is target for owner in self.objects) + sum(owner is target for owner in self.children)
                        + self._custom.get("_synthetic_extra_count", {}).get(target, 0))
            return int(self in reverse.get(target, ()))

    def define(name, fields=(), **attributes):
        owner = type(name, (Native,), {"bl_rna": rna(name, fields, 100 + len(vars(types))), **attributes})
        setattr(types, name, owner)
        return owner

    def field(name, kind, size=0, *, readonly=False):
        return Property(name, kind, array_length=size, readonly=readonly)

    def primitive_fields(**values):
        fields = []
        for name, value in values.items():
            if type(value) is bool:
                fields.append(field(name, "BOOLEAN"))
            elif type(value) is int:
                fields.append(field(name, "INT"))
            elif type(value) is float:
                fields.append(field(name, "FLOAT"))
            elif type(value) in {list, tuple}:
                fields.append(field(name, "FLOAT", len(value)))
            else:
                fields.append(field(name, "STRING"))
        return fields

    def pixel_property(self):
        counters["pixels"] += 1
        assert self.has_data, "No implicit load is modeled or permitted"
        return self._pixels

    def packed_property(self):
        counters["packed"] += 1
        assert self.has_data, "No implicit packed decode is modeled or permitted"
        return self._packed

    class Pixels:
        def __init__(self, values):
            self.values = array("f", values)

        def __len__(self):
            return len(self.values)

        def foreach_get(self, destination):
            counters["foreach_get"] += 1
            destination[:] = self.values

    Image = define("Image", [field("name", "STRING"), field("has_data", "BOOLEAN", readonly=True)],
                   pixels=property(pixel_property), packed_file=property(packed_property))
    Packed = define("PackedFile", [field("size", "INT", readonly=True)])
    Colorspace = define("ColorManagedInputColorspaceSettings", [field("name", "ENUM")])
    Material = define("Material", primitive_fields(name="Material", use_nodes=True, roughness=.5, metallic=0., diffuse_color=(.8, .8, .8, 1.)))
    Tree = define("ShaderNodeTree", [field("name", "STRING")])
    Scene = define("Scene", [field("name", "STRING")])
    Collection = define("Collection", [field("name", "STRING")])
    Object = define("Object", [*primitive_fields(name="Object", location=(0., 0., 0.), rotation_euler=(0., 0., 0.),
                                                scale=(1., 1., 1.), hide_viewport=False, hide_render=False),
                               field("matrix_parent_inverse", "FLOAT", 16)])
    LayerCollection = define("LayerCollection", [
        Property("collection", "POINTER", fixed_type=Collection.bl_rna), Property("children", "COLLECTION")])
    LayerCollection.bl_rna.properties[1]._fixed_type = LayerCollection.bl_rna
    ViewLayer = define("ViewLayer", [Property("layer_collection", "POINTER", fixed_type=LayerCollection.bl_rna),
                                    Property("objects", "COLLECTION", fixed_type=Object.bl_rna)])
    Mesh = define("Mesh", primitive_fields(name="Mesh", use_auto_texspace=True))
    Slot = define("MaterialSlot", [field("link", "ENUM")])
    Vertex = define("MeshVertex")
    Edge = define("MeshEdge")
    Polygon = define("MeshPolygon")
    Loop = define("MeshLoop")
    Layer = define("MeshUVLoopLayer")
    define("UVLoopLayers")
    for kind in ("FloatVectorAttribute", "Int2Attribute", "IntAttribute", "Float2Attribute", "BoolAttribute"):
        fields = [field("name", "STRING", readonly=True), field("domain", "ENUM", readonly=True),
                  field("data_type", "ENUM", readonly=True)]
        if build == b"d13f752e3b9c":
            fields.append(field("storage_type", "ENUM", readonly=True))

        def data_property(self):
            counters["attribute_data"] += 1
            assert self.storage_type == "ARRAY", "No Single-to-Array conversion is modeled"
            return self._data

        define(kind, fields, data=property(data_property))
    for kind in ("FloatVectorAttributeValue", "Int2AttributeValue", "IntAttributeValue", "Float2AttributeValue", "BoolAttributeValue"):
        define(kind)
    NodeLink = define("NodeLink")
    ImageUser = define("ImageUser", primitive_fields(use_auto_refresh=False, frame_duration=1, frame_offset=0))
    mapping_values = dict(vector_type="POINT", translation=(0., 0., 0.), rotation=(0., 0., 0.), scale=(1., 1., 1.),
                          mapping_x="X", mapping_y="Y", mapping_z="Z", use_min=False, use_max=False,
                          min=(0., 0., 0.), max=(1., 1., 1.))
    TexMapping = define("TexMapping", primitive_fields(**mapping_values))
    ramp_values = dict(interpolation="LINEAR", color_mode="RGB", hue_interpolation="NEAR")
    ColorRamp = define("ColorRamp", primitive_fields(**ramp_values))
    RampElement = define("ColorRampElement", primitive_fields(position=0., color=(0., 0., 0., 1.)))
    define("ColorRampElements")
    color_values = dict(use_color_ramp=False, blend_color=(.5, .5, .5), blend_factor=0., blend_type="MIX",
                        brightness=1., contrast=1., saturation=1.)
    ColorMapping = define("ColorMapping", primitive_fields(**color_values))
    nodes = {}
    for kind in graph.NODES:
        nodes[kind] = define(kind, primitive_fields(name="Node", label="", mute=False, hide=False, location=(0., 0.), width=140.))
    nodes["ShaderNodeTexImage"].bl_rna.properties.extend([
        Property("texture_mapping", "POINTER", readonly=True, fixed_type=TexMapping.bl_rna),
        Property("color_mapping", "POINTER", readonly=True, fixed_type=ColorMapping.bl_rna),
        Property("image_user", "POINTER", readonly=True, fixed_type=ImageUser.bl_rna)])
    ColorMapping.bl_rna.properties.append(Property("color_ramp", "POINTER", readonly=True, fixed_type=ColorRamp.bl_rna))
    ColorRamp.bl_rna.properties.append(Property("elements", "COLLECTION", readonly=True, fixed_type=RampElement.bl_rna))
    for kind, _default, data_kind, size in (("NodeSocketColor", (0., 0., 0., 1.), "FLOAT", 4),
            ("NodeSocketFloat", .5, "FLOAT", 0), ("NodeSocketVector", (0., 0., 0.), "FLOAT", 3),
            ("NodeSocketShader", None, None, 0)):
        props = [field("name", "STRING"), field("identifier", "STRING", readonly=True),
                 field("hide", "BOOLEAN"), field("enabled", "BOOLEAN", readonly=True)]
        if data_kind:
            props.append(field("default_value", data_kind, size))
        define(kind, props)

    old_values = array("f", [0., .25, .5, 1.] * 4)
    current_values = array("f", [-0., 2., -.5, 0., .25, .5, .75, 1., 8., .125, .0625, .5, 1., 0., .5, .25])

    def encode(values):
        return b"".join(step.data for step in codec.encode_steps(values, 2, 2, "EXR32_RAW", "DATA"))

    def image(name, values, packed):
        payload = Packed(size=len(packed), data=packed)
        return Image(name=name, has_data=True, size=(2, 2), source="FILE", file_format="OPEN_EXR", is_float=True,
                     channels=4, colorspace_settings=Colorspace(name="Non-Color"), alpha_mode="CHANNEL_PACKED",
                     is_multiview=False, filepath="//original.exr", filepath_raw="//original.exr", is_dirty=True,
                     _pixels=Pixels(values), _packed=payload)

    old, edited = encode(old_values), encode(current_values)
    original, helper = image("Original", current_values, old), image("Snapshot", current_values, edited)
    helper.use_fake_user, helper.users = True, 1
    metadata = {"schema_version": 1, "mode": "CURRENT_PIXELS", "width": 2, "height": 2, "source": "FILE",
                "colorspace": "Non-Color", "alpha_mode": "CHANNEL_PACKED", "is_float": True,
                "pixels_sha256_float32_le": hashlib.sha256(current_values.tobytes()).hexdigest(),
                "packed_sha256": hashlib.sha256(edited).hexdigest()}
    helper[storage.OWNER_KEY] = original
    helper[storage.METADATA_KEY] = graph._canonical(metadata).decode()
    tree = Tree(name="Material Tree", users=1, is_embedded_data=True, nodes=[], links=[])
    material = Material(name="Material", use_nodes=True, node_tree=tree, roughness=.5, metallic=0., diffuse_color=(.8, .8, .8, 1.))
    texture = nodes["ShaderNodeTexImage"](name="Texture", label="", mute=False, hide=False, location=(0., 0.), width=140.,
                 parent=None, id_data=tree, bl_idname="ShaderNodeTexImage", image=original,
                 image_user=ImageUser(use_auto_refresh=False, frame_duration=1, frame_offset=0))
    texture.texture_mapping = TexMapping(**mapping_values)
    texture.color_mapping = ColorMapping(**color_values)
    texture.color_mapping.color_ramp = ColorRamp(**ramp_values)
    texture.color_mapping.color_ramp.elements = [RampElement(position=0., color=(0., 0., 0., 1.), alpha=1.),
                                                RampElement(position=1., color=(1., 1., 1., 1.), alpha=1.)]
    for nested in (texture.texture_mapping, texture.color_mapping, texture.color_mapping.color_ramp,
                   *texture.color_mapping.color_ramp.elements):
        nested.id_data = tree
    principled = nodes["ShaderNodeBsdfPrincipled"](name="Principled", label="", mute=False, hide=False, location=(200., 0.), width=140.,
                                                parent=None, id_data=tree, bl_idname="ShaderNodeBsdfPrincipled")
    output = nodes["ShaderNodeOutputMaterial"](name="Output", label="", mute=False, hide=False, location=(400., 0.), width=140.,
                                             parent=None, id_data=tree, bl_idname="ShaderNodeOutputMaterial")

    def socket(kind, name, node, default=None):
        value = getattr(types, kind)(name=name, identifier=name, bl_idname=kind, node=node, id_data=tree,
                                     hide=False, enabled=True, is_linked=False)
        if kind != "NodeSocketShader":
            value.default_value = native_value(default)
        return value

    texture.inputs = [socket("NodeSocketVector", "Vector", texture, (0., 0., 0.))]
    texture.outputs = [socket("NodeSocketColor", "Color", texture, (0., 0., 0., 1.)), socket("NodeSocketFloat", "Alpha", texture, 1.)]
    principled.inputs = [socket("NodeSocketColor", "Base Color", principled, (.8, .8, .8, 1.)), socket("NodeSocketFloat", "Roughness", principled, .5)]
    principled.outputs = [socket("NodeSocketShader", "BSDF", principled)]
    output.inputs, output.outputs = [socket("NodeSocketShader", "Surface", output)], []
    links = []
    for source, target in ((texture.outputs[0], principled.inputs[0]), (principled.outputs[0], output.inputs[0])):
        source.is_linked = target.is_linked = True
        links.append(NodeLink(from_node=source.node, to_node=target.node, from_socket=source, to_socket=target, is_valid=True, is_muted=False))
    tree.nodes, tree.links = [texture, principled, output], links
    vertices = [Vertex(index=index, co=co, select=index == 0, hide=False, groups=[])
                for index, co in enumerate(((0., -0., 0.), (1., 0., 0.), (0., 1., 0.)))]
    edges = [Edge(index=index, vertices=pair, use_seam=index == 0, use_edge_sharp=False, select=False, hide=False)
             for index, pair in enumerate(((0, 1), (1, 2), (2, 0)))]
    polygons = [Polygon(index=0, vertices=(0, 1, 2), loop_start=0, loop_total=3, material_index=0, use_smooth=False, select=True, hide=False)]
    loops = [Loop(index=index, vertex_index=index, edge_index=index) for index in range(3)]

    class Layers(list):
        active_index = 0

    layers = Layers([Layer(name="UVMap", active=True, active_render=True, active_clone=True)])
    mesh = Mesh(name="Mesh", vertices=vertices, edges=edges, polygons=polygons, loops=loops, uv_layers=layers,
                users=1, shape_keys=None, is_editmode=False, has_custom_normals=False, color_attributes=[],
                materials=[material], use_auto_texspace=True)
    attrs = []

    def attribute(name, domain, datatype, kind, leaf, values):
        entries = [getattr(types, leaf)(**({"vector": value} if type(value) in {tuple, list} else {"value": value})) for value in values]
        item = getattr(types, kind)(name=name, domain=domain, data_type=datatype, storage_type="ARRAY", _data=entries)
        attrs.append(item)
        return item

    attribute("position", "POINT", "FLOAT_VECTOR", "FloatVectorAttribute", "FloatVectorAttributeValue", [vertex.co for vertex in vertices])
    attribute(".edge_verts", "EDGE", "INT32_2D", "Int2Attribute", "Int2AttributeValue", [edge.vertices for edge in edges])
    for name in (".corner_vert", ".corner_edge"):
        attribute(name, "CORNER", "INT", "IntAttribute", "IntAttributeValue", [0, 1, 2])
    uv = attribute("UVMap", "CORNER", "FLOAT2", "Float2Attribute", "Float2AttributeValue", [(0., -0.), (1., 0.), (0., 1.)])
    pin = attribute(".pn.UVMap", "CORNER", "BOOLEAN", "BoolAttribute", "BoolAttributeValue", [True, False, True])
    selections = []
    if build == b"62c1db4208e8":
        names = ((".vs.UVMap", "CORNER", [False, True, False]), (".es.UVMap", "CORNER", [True, False, True]))
    else:
        names = ((".uv_select_vert", "CORNER", [False, True, False]), (".uv_select_edge", "CORNER", [True, False, True]),
                 (".uv_select_face", "FACE", [True]))
    for name, domain, values in names:
        selections.append(attribute(name, domain, "BOOLEAN", "BoolAttribute", "BoolAttributeValue", values))
    mesh.attributes = attrs
    slot = Slot(link="DATA", material=material)
    obj = Object(name="Object", data=mesh, type="MESH", mode="OBJECT", parent=None, children=[], modifiers=[], constraints=[],
                 vertex_groups=[], instance_type="NONE", material_slots=[slot], location=(0., 0., 0.), rotation_euler=(0., 0., 0.),
                 scale=(1., 1., 1.), hide_viewport=False, hide_render=False,
                 matrix_parent_inverse=((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.)))
    class NamedOwners(list):
        def get(self, name):
            return next((owner for owner in self if owner.name == name), None)

    collection = Collection(name="Collection", children=NamedOwners(), objects=NamedOwners([obj]),
                            instance_offset=(0., 0., 0.), is_embedded_data=True)
    bases = NamedOwners([obj])
    bases.active = obj
    layer = ViewLayer(layer_collection=LayerCollection(collection=collection, children=[]), objects=bases)
    scene = Scene(name="Scene", objects=[obj], collection=collection, view_layers=[layer], frame_current=1, frame_subframe=0.)
    obj.users_collection, obj.users_scene = (collection,), (scene,)
    reverse.update({original: {helper, material, tree}, helper: set(), material: {mesh}, tree: {material},
                    mesh: {obj}, obj: {scene}, collection: set(), scene: set()})
    bpy = NS(types=types, app=NS(build_hash=build, version=graph.BUILDS[build]),
             data=NS(images={original.name: original, helper.name: helper}, materials={material.name: material},
                     objects={obj.name: obj}, meshes={mesh.name: mesh}, collections={}, scenes={scene.name: scene},
                     as_pointer=lambda: 123456),
             context=NS(mode="OBJECT", scene=scene, view_layer=layer,
                        window=NS(scene=scene, as_pointer=lambda: 123457,
                                  workspace=NS(as_pointer=lambda: 123458), screen=NS(as_pointer=lambda: 123459))))
    bpy.data.user_map = lambda *, subset: {owner: set(reverse.get(owner, ())) for owner in subset}
    for owner in (original, helper, material, tree, mesh, obj, collection, scene):
        owner.id_data = owner
    install_model_catalogs(graph, monkeypatch, bpy)

    def modeled_native_mesh_policy(_bpy, target):
        assert target is mesh and target.use_auto_texspace is True
        return (), (None, None, None, None, (True, "AUTO_CACHE_EXCLUDED", ("texspace_location", "texspace_size")), None, None, None)

    monkeypatch.setattr(uv_guard, "_mesh_properties", modeled_native_mesh_policy)

    def check():
        counters["checks"] += 1
        if live["cancelled"]:
            raise graph.BridgeError("TIMEOUT", "Synthetic owner lifetime expired.")

    def steps(**kwargs):
        return graph.capture_graph_steps(bpy, "Original", "Snapshot", ["Material"], check=check,
            available_memory_bytes=512 * 1024**2, available_disk_bytes=64 * 1024**2, **kwargs)

    def capture(**kwargs):
        return graph.capture_graph(bpy, "Original", "Snapshot", ["Material"], check=check,
            available_memory_bytes=512 * 1024**2, available_disk_bytes=64 * 1024**2, **kwargs)

    return NS(bpy=bpy, types=types, original=original, helper=helper, material=material, tree=tree,
              texture=texture, principled=principled, output=output, mesh=mesh, obj=obj, collection=collection, scene=scene, layer=layer,
              uv=uv, pin=pin, selections=selections, attributes=attrs, reverse=reverse, all_owners=all_owners,
              old=old, edited=edited, old_values=old_values, current_values=current_values, counters=counters,
              live=live, storage=storage, codec=codec, attribute=attribute, steps=steps, capture=capture, check=check)


def drain_capture(steps):
    progress = []
    while True:
        try:
            progress.append(next(steps))
        except StopIteration as result:
            return result.value, progress


@pytest.fixture(params=[b"62c1db4208e8", b"d13f752e3b9c"], ids=["4.5-model", "5.2-model"])
def capture_model(graph, monkeypatch, addon_package, request):
    return make_capture_model(graph, monkeypatch, addon_package, build=request.param)


def test_real_graph_captures_old_packed_and_complete_edited_current_snapshot(capture_model):
    import struct

    model = capture_model
    result, progress = drain_capture(model.steps())
    assert result.payloads.original_packed == model.old and result.payloads.snapshot_packed == model.edited
    expected_current = hashlib.sha256(struct.pack("<16f", *model.current_values)).hexdigest()
    expected_old = hashlib.sha256(struct.pack("<16f", *model.old_values)).hexdigest()
    assert expected_current != expected_old
    assert result.payloads.current_pixels_sha256_float32_le == expected_current
    assert result.payloads.original_decoded_pixels_sha256 == expected_old
    assert result.payloads.current_pixels == model.current_values
    assert {step["phase"] for step in progress} == {"decoding_snapshot", "verifying_complete_float32_channels"}
    assert result.workload == {"vertices": 3, "edges": 3, "polygons": 1, "loops": 3, "slots": 1, "nodes": 3, "links": 2, "sockets": 7}
    summary = result.summary()
    assert summary["complete_pixels_verified"] and not summary["recovery_authorized"]
    assert "payloads" not in summary and "current_pixels" not in summary
    json.dumps(summary, allow_nan=False)
    summary["native_identity_rows"][0]["name"] = "Caller changed copy"
    assert result.summary()["native_identity_rows"][0]["name"] != "Caller changed copy"
    assert model.counters["foreach_get"] >= 4


@pytest.mark.parametrize("change", ["geometry", "uv", "pin", "selection", "socket_default", "role", "binding", "mapping", "ramp", "packed", "pixels"])
def test_private_yields_never_adopt_late_manual_edits_as_a_new_baseline(graph, capture_model, change):
    model = capture_model
    steps = model.steps()
    next(steps)
    if change == "geometry":
        model.mesh.vertices[0].co = (.25, 0., 0.)
    elif change == "uv":
        model.uv._data[0].vector = (.25, 0.)
    elif change == "pin":
        model.pin._data[0].value = False
    elif change == "selection":
        model.selections[0]._data[0].value = True
    elif change == "socket_default":
        model.principled.inputs[1].default_value = .25
    elif change == "role":
        model.mesh.uv_layers[0].active_render = False
    elif change == "binding":
        model.texture.image = None
    elif change == "mapping":
        model.texture.texture_mapping.translation = (.25, 0., 0.)
    elif change == "ramp":
        model.texture.color_mapping.color_ramp.elements[0].position = .25
    elif change == "packed":
        model.original._packed.data = model.edited
    else:
        model.original._pixels.values[0] = .25
    with pytest.raises(graph.BridgeError):
        drain_capture(steps)


@pytest.mark.parametrize("case", ["unknown_attribute", "missing_pin", "missing_selection", "unknown_image_user", "unknown_material_user",
    "nested_group", "foreign_link", "linked", "override", "helper_unloaded", "original_unloaded", "shared_mesh", "object_mode", "single_storage"])
def test_invalid_scope_refuses_before_pixel_or_packed_payload_acquisition(graph, capture_model, case):
    model = capture_model
    if case == "unknown_attribute":
        model.attribute("Unknown", "POINT", "BOOLEAN", "BoolAttribute", "BoolAttributeValue", [True] * 3)
    elif case == "missing_pin":
        model.attributes.remove(model.pin)
    elif case == "missing_selection":
        model.attributes.remove(model.selections[0])
    elif case == "unknown_image_user":
        model.reverse[model.original].add(object())
    elif case == "unknown_material_user":
        model.reverse[model.material].add(object())
    elif case == "nested_group":
        model.tree.nodes[0] = NS(bl_idname="ShaderNodeGroup")
    elif case == "foreign_link":
        model.tree.links[0].from_socket = object()
    elif case == "linked":
        model.original.library = object()
    elif case == "override":
        model.original.override_library = object()
    elif case == "helper_unloaded":
        model.helper.has_data = False
    elif case == "original_unloaded":
        model.original.has_data = False
    elif case == "shared_mesh":
        model.mesh.users = 2
    elif case == "object_mode":
        model.obj.mode = "EDIT"
    elif model.bpy.app.build_hash == b"d13f752e3b9c":
        model.uv.storage_type = "SINGLE"
    else:
        type(model.uv).bl_rna.properties.append(Property("storage_type", "ENUM", readonly=True))
    with pytest.raises(graph.BridgeError):
        model.capture()
    assert model.counters["pixels"] == model.counters["packed"] == 0


def test_resource_refusal_reports_measured_facts_before_payloads(graph, capture_model):
    model = capture_model
    with pytest.raises(graph.BridgeError) as failure:
        graph.capture_graph(model.bpy, "Original", "Snapshot", ["Material"], check=model.check,
                            available_memory_bytes=0, available_disk_bytes=0)
    assert failure.value.context["resource_facts"]["admitted"] is False
    assert model.counters["pixels"] == model.counters["packed"] == 0


def test_graph_native_tokens_change_native_fingerprint_only(graph, monkeypatch, addon_package):
    first_model = make_capture_model(graph, monkeypatch, addon_package, pointer_base=1000)
    first = first_model.capture()
    second_model = make_capture_model(graph, monkeypatch, addon_package, pointer_base=10000)
    second = second_model.capture()
    assert first.native_graph_sha256 != second.native_graph_sha256
    assert first.portable_graph_sha256 == second.portable_graph_sha256
    assert [row["content_sha256"] for row in first.native_identity_rows] == [row["content_sha256"] for row in second.native_identity_rows]
    assert first.full_portable_prefix_sha256 == second.full_portable_prefix_sha256


def test_complete_object_parent_inverse_matrix_is_measured_as_four_rows(capture_model):
    model = capture_model
    before = model.capture()
    model.obj.matrix_parent_inverse = ((1., 0., 0., .25), *model.obj.matrix_parent_inverse[1:])
    after = model.capture()
    assert before.consumer_graph_sha256 != after.consumer_graph_sha256
    assert before.portable_graph_sha256 != after.portable_graph_sha256
    old_row = next(row for row in before.native_identity_rows if row["kind"] == "Object")
    new_row = next(row for row in after.native_identity_rows if row["kind"] == "Object")
    assert old_row["content_sha256"] != new_row["content_sha256"]


@pytest.mark.parametrize("matrix", [((1., 0., 0., 0.),) * 3,
                                  ((1., 0., 0.),) * 4,
                                  ((float("nan"), 0., 0., 0.),) * 4])
def test_object_parent_inverse_matrix_refuses_incomplete_or_nonfinite_rows(graph, capture_model, matrix):
    capture_model.obj.matrix_parent_inverse = matrix
    with pytest.raises(graph.BridgeError):
        capture_model.capture()
    assert capture_model.counters["pixels"] == capture_model.counters["packed"] == 0


@pytest.mark.parametrize("change", ["dirty", "lifecycle_record", "current_packed"])
def test_volatile_image_lifecycle_prefix_is_separate_from_immutable_consumer_graph(graph, capture_model, change):
    model = capture_model
    before = model.capture()
    kwargs = {}
    if change == "dirty":
        model.original.is_dirty = False
    elif change == "lifecycle_record":
        record = graph._canonical({"schema_version": 1, "profile": graph.PROFILE, "record_uuid": "a" * 32,
                                  "runtime_nonce": "b" * 32, "manifest_sha256": "c" * 64}).decode()
        model.helper[graph.LIFECYCLE_KEY] = record
        kwargs["lifecycle_record"] = record
    else:
        model.original._packed.data, model.original._packed.size = model.edited, len(model.edited)
    after = model.capture(**kwargs)
    assert before.consumer_graph_sha256 == after.consumer_graph_sha256
    assert before.portable_graph_sha256 == after.portable_graph_sha256
    assert before.full_native_prefix_sha256 != after.full_native_prefix_sha256
    assert before.full_portable_prefix_sha256 != after.full_portable_prefix_sha256


@pytest.mark.parametrize("boundary,expected_decoder_calls", [("old_decoder", 0), ("helper_decoder", 1), ("snapshot", 2)])
def test_last_private_yield_cancellation_precedes_new_decoder_allocation_or_snapshot_reads(graph, capture_model, monkeypatch, addon_package, boundary, expected_decoder_calls):
    model = capture_model
    recovery = importlib.import_module(f"{addon_package}.tools.image_recovery_jobs")
    real_decode, real_snapshot = recovery._decode_steps, model.storage._snapshot
    calls = {"decode": 0, "snapshot": 0}

    def decode(*args, **kwargs):
        calls["decode"] += 1
        return (yield from real_decode(*args, **kwargs))

    def snapshot(*args, **kwargs):
        calls["snapshot"] += 1
        return real_snapshot(*args, **kwargs)

    monkeypatch.setattr(recovery, "_decode_steps", decode)
    monkeypatch.setattr(model.storage, "_snapshot", snapshot)
    steps, completed_digests = model.steps(), 0
    for step in steps:
        if step["phase"] == "verifying_complete_float32_channels" and step["completed"] == step["total"]:
            completed_digests += 1
            if completed_digests == {"old_decoder": 2, "helper_decoder": 3, "snapshot": 4}[boundary]:
                model.live["cancelled"] = True
                break
    with pytest.raises(graph.BridgeError) as failure:
        drain_capture(steps)
    assert failure.value.code == "TIMEOUT"
    assert calls == {"decode": expected_decoder_calls, "snapshot": 0}


@pytest.mark.parametrize("kind", ["PackedFile", "ColorManagedInputColorspaceSettings"])
def test_late_descendant_catalog_drift_refuses_before_legacy_snapshot_getters(graph, capture_model, monkeypatch, kind):
    model, calls = capture_model, []

    def forbidden_snapshot(*_args, **_kwargs):
        calls.append("legacy snapshot")
        pytest.fail("A changed descendant schema must refuse before legacy getters")

    monkeypatch.setattr(model.storage, "_snapshot", forbidden_snapshot)
    steps, completed_digests = model.steps(), 0
    for step in steps:
        if step["phase"] == "verifying_complete_float32_channels" and step["completed"] == step["total"]:
            completed_digests += 1
            if completed_digests == 4:
                break
    getattr(model.types, kind).bl_rna.properties.append(Property("foreign", runtime=True))
    with pytest.raises(graph.BridgeError) as failure:
        drain_capture(steps)
    assert failure.value.context["reason"] == "UNQUALIFIED_STATIC_RNA_CATALOG:" + kind
    assert calls == []


@pytest.mark.parametrize("case", ["foreign_scene", "nested_collection", "instancer", "collection_alias"])
def test_reverse_collection_scene_closure_refuses_foreign_or_rebound_ownership_before_payload(graph, capture_model, case):
    model = capture_model
    if case == "foreign_scene":
        foreign = model.types.Scene(name="Foreign", objects=[model.obj], collection=model.collection)
        model.bpy.data.scenes[foreign.name] = foreign
        model.reverse[model.obj].add(foreign)
    elif case == "nested_collection":
        outer = model.types.Collection(name="Outer", children=type(model.collection.children)([model.collection]), objects=[])
        model.bpy.data.collections[outer.name] = outer
        model.reverse[model.collection].add(outer)
    elif case == "instancer":
        outside = model.types.Object(name="Outside Instance", type="EMPTY", instance_type="COLLECTION", instance_collection=model.collection)
        model.bpy.data.objects[outside.name] = outside
        model.reverse[model.collection].add(outside)
    else:
        foreign_child = model.types.Collection(name=model.collection.name, children=[], objects=[])
        master = model.types.Collection(name="Master", children=type(model.collection.children)([foreign_child]),
                                        objects=type(model.collection.objects)(), is_embedded_data=True)
        model.scene.collection = master
        model.reverse[master] = set()
        model.reverse[model.collection] = {model.scene}
    with pytest.raises(graph.BridgeError):
        model.capture()
    assert model.counters["pixels"] == model.counters["packed"] == 0


@pytest.mark.parametrize("adversary", ["none", "extra_reference", "foreign_scene", "nested_consumer", "extra_base", "same_count_replacement"])
def test_checkpoint_witness_preserves_structural_consumer_closure(graph, capture_model, adversary):
    model = capture_model
    model.scene._custom["_synthetic_extra_count"] = {model.obj: 1}
    calls = []
    class ExactWitness:
        def check_scene_object_count(self, reader, scene, obj, memberships):
            calls.append((scene, obj, memberships))
            if memberships != 2:
                raise graph.refused("MODELED_STRUCTURAL_MEMBERSHIPS_CHANGED")
            graph._user_count(reader, scene, obj, expected=3)
    reader = graph._Reader(model.bpy, lambda: None)
    with pytest.raises(graph.BridgeError):
        graph._collection_closure(reader, model.obj, tuple(model.reverse[model.obj]))
    if adversary == "extra_reference":
        model.scene._custom["_synthetic_extra_count"][model.obj] = 2
    elif adversary == "foreign_scene":
        other = model.types.Scene(name="Foreign")
        model.reverse[model.obj].add(other)
    elif adversary == "nested_consumer":
        outer = model.types.Collection(name="Nested", children=[], objects=[model.obj], is_embedded_data=False)
        model.reverse[model.obj].add(outer)
    elif adversary == "extra_base":
        model.layer.objects.append(model.obj)
    elif adversary == "same_count_replacement":
        model.layer.objects.remove(model.obj)
        model.scene._custom["_synthetic_extra_count"][model.obj] = 2
    if adversary == "none":
        closure = graph._collection_closure(reader, model.obj, tuple(model.reverse[model.obj]), checkpoint_roles=ExactWitness())
        assert set(closure) == {model.scene, model.collection}
        assert calls == [(model.scene, model.obj, 2)]
    else:
        with pytest.raises(graph.BridgeError):
            graph._collection_closure(reader, model.obj, tuple(model.reverse[model.obj]), checkpoint_roles=ExactWitness())
        if adversary in {"foreign_scene", "nested_consumer"}:
            assert calls == []


def test_direct_current_scene_child_collection_is_a_complete_supported_owner(capture_model):
    model = capture_model
    master = model.types.Collection(name="Master", children=type(model.collection.children)([model.collection]),
                                    objects=type(model.collection.objects)(), is_embedded_data=True)
    model.collection.is_embedded_data = False
    model.scene.collection = master
    model.bpy.data.collections[model.collection.name] = model.collection
    model.reverse[master] = set()
    model.reverse[model.collection] = {model.scene}
    model.reverse[model.obj].add(model.collection)
    child = model.types.LayerCollection(collection=model.collection, children=[])
    model.layer.layer_collection = model.types.LayerCollection(collection=master, children=[child])
    result = model.capture()
    assert result.objects == (model.obj,)
    assert result.summary()["complete_pixels_verified"]


@pytest.mark.parametrize("family", ["vertices", "edges", "polygons", "loops", "uv_maps", "slots", "nodes", "links", "sockets"])
def test_all_workload_caps_refuse_before_large_payload_or_collection_iteration(graph, capture_model, family):
    model = capture_model
    limits = {"vertices": graph.MAX_VERTICES, "edges": graph.MAX_EDGES, "polygons": graph.MAX_POLYGONS,
              "loops": graph.MAX_LOOPS, "uv_maps": graph.MAX_UV_MAPS, "slots": graph.MAX_SLOTS,
              "nodes": graph.MAX_NODES, "links": graph.MAX_LINKS, "sockets": graph.MAX_SOCKETS}

    class OverBudget:
        def __len__(self):
            return limits[family] + 1

        def __iter__(self):
            pytest.fail("Over-budget workload must refuse before payload iteration")

    if family in {"vertices", "edges", "polygons", "loops"}:
        setattr(model.mesh, family, OverBudget())
    elif family == "uv_maps":
        model.mesh.uv_layers = OverBudget()
    elif family == "slots":
        model.obj.material_slots = OverBudget()
    elif family in {"nodes", "links"}:
        setattr(model.tree, family, OverBudget())
    else:
        model.texture.inputs = OverBudget()
    with pytest.raises(graph.BridgeError):
        model.capture()
    assert model.counters["pixels"] == model.counters["packed"] == 0
    assert model.counters["attribute_data"] == 0


@pytest.mark.parametrize("field,value", [("alpha_mode", "STRAIGHT"), ("source", "GENERATED"), ("file_format", "PNG"),
    ("is_multiview", True), ("channels", 3), ("is_float", False)])
def test_finite_file_image_profile_does_not_convert_or_adopt_roles(graph, capture_model, field, value):
    model = capture_model
    setattr(model.original, field, value)
    with pytest.raises(graph.BridgeError):
        model.capture()
    assert model.counters["pixels"] == model.counters["packed"] == 0


@pytest.mark.parametrize("corrupt", ["old_layout", "helper_layout", "old_nonfinite", "helper_pixels", "helper_metadata", "payload_size"])
def test_complete_codec_validation_refuses_corrupt_or_mismatched_payloads(graph, capture_model, corrupt):
    import struct

    model = capture_model
    if corrupt == "old_layout":
        model.original._packed.data = b"invalid" + model.old[7:]
    elif corrupt == "helper_layout":
        model.helper._packed.data = b"invalid" + model.edited[7:]
    elif corrupt == "old_nonfinite":
        payload = bytearray(model.old)
        payload[-4:] = struct.pack("<f", float("nan"))
        model.original._packed.data = bytes(payload)
    elif corrupt == "helper_pixels":
        model.helper._pixels.values[0] = .25
    elif corrupt == "helper_metadata":
        metadata = json.loads(model.helper[model.storage.METADATA_KEY])
        metadata["pixels_sha256_float32_le"] = "0" * 64
        model.helper[model.storage.METADATA_KEY] = graph._canonical(metadata).decode()
    else:
        model.original._packed.size += 1
    with pytest.raises(graph.BridgeError):
        model.capture()


def test_modeled_constructor_refusal_precedes_untrusted_fixed_target_getter(graph, identity_model, monkeypatch):
    """Counter model only: actual C descriptor qualification is not faked proof."""
    model, calls = identity_model, []
    original = model.Material.bl_rna.properties[1]

    class FixedTargetTrap(Property):
        @property
        def fixed_type(self):
            calls.append("fixed_type")
            pytest.fail("Rejected target constructor must precede fixed_type getter")

    model.Material.bl_rna.properties[1] = FixedTargetTrap(original.identifier, original.type, fixed_type=original._fixed_type)
    modeled_constructor = graph._constructor_proof

    def reject_tree(bpy, name, resolved=None):
        if name == "ShaderNodeTree":
            raise graph.refused("MODELED_NATIVE_CONSTRUCTOR_CHANGED")
        return modeled_constructor(bpy, name, resolved)

    monkeypatch.setattr(graph, "_constructor_proof", reject_tree)
    with pytest.raises(graph.BridgeError) as failure:
        graph.identity_witness(model.bpy, "Original", "Snapshot", ["Material"])
    assert failure.value.context["reason"] == "MODELED_NATIVE_CONSTRUCTOR_CHANGED"
    assert calls == []


def test_static_catalog_drift_refuses_before_new_pointer_fixed_type_getter(graph, identity_model):
    model, calls = identity_model, []

    class FixedTargetTrap(Property):
        @property
        def fixed_type(self):
            calls.append("foreign fixed_type")
            pytest.fail("Static metadata mismatch must refuse before any new target getter")

    model.Material.bl_rna.properties.append(FixedTargetTrap("new_pointer", "POINTER", fixed_type=model.Image.bl_rna))
    with pytest.raises(graph.BridgeError) as failure:
        graph.identity_witness(model.bpy, "Original", "Snapshot", ["Material"])
    assert failure.value.context["reason"] == "UNQUALIFIED_STATIC_RNA_CATALOG:Material"
    assert calls == []


def test_registered_lookup_rejects_python_substitute_without_calling_it(graph, identity_model, monkeypatch):
    model, calls = identity_model, []

    class UnqualifiedBase:
        @classmethod
        def bl_rna_get_subclass_py(cls, *_args):
            calls.append(cls)
            pytest.fail("Foreign registered-type lookup must remain uncalled")

    monkeypatch.setattr(model.bpy.types, "bpy_struct", UnqualifiedBase, raising=False)
    with pytest.raises(graph.BridgeError) as failure:
        graph._registered_target(model.bpy, "Untrusted", lambda: None)
    assert failure.value.context["reason"] == "REGISTERED_LOOKUP_DESCRIPTOR_CHANGED"
    assert calls == []


def test_live_pass_recensuses_class_metadata_after_a_private_yield(graph, capture_model):
    model = capture_model
    steps = model.steps()
    next(steps)
    type(model.original).bl_rna.properties.append(Property("newly_registered_property", runtime=True))
    with pytest.raises(graph.BridgeError) as failure:
        drain_capture(steps)
    assert failure.value.context["reason"] == "UNQUALIFIED_STATIC_RNA_CATALOG:Image"


def test_native_field_shadow_guard_refuses_python_property_without_invocation(graph):
    calls = []

    class Foreign:
        @property
        def pixels(self):
            calls.append("foreign property")
            pytest.fail("A substituted field cannot be called during qualification")

    with pytest.raises(graph.BridgeError) as failure:
        graph._unshadowed(Foreign, ("pixels",))
    assert failure.value.context["reason"] == "NATIVE_FIELD_PYTHON_SHADOW:pixels"
    assert calls == []


_MARKER_MODEL_ROWS = (
    ("Material", "cycles", "POINTER", True, "CyclesMaterialSettings"),
    ("Mesh", "cycles", "POINTER", True, "CyclesMeshSettings"),
    ("Object", "selection_sets", "COLLECTION", True, "SelectionSet"),
    ("Object", "active_selection_set", "INT", False, None),
    ("Object", "cycles", "POINTER", True, "CyclesObjectSettings"),
    ("Scene", "cycles", "POINTER", True, "CyclesRenderSettings"),
    ("Scene", "cycles_curves", "POINTER", True, "CyclesCurveRenderSettings"),
)


def make_runtime_marker_model(graph, monkeypatch, *, build=b"62c1db4208e8", scalar_only=False):
    """Synthetic C marker/constructor assumptions; graph CAS is not patched.

    Exact modules and raw class dictionaries run through real marker extraction,
    field guards, static/full catalogs, pointer order and cache checks. Only the
    native marker slot proof and existing native constructor/registry boundary
    are modeled. This supplies no native Blender or permission qualification.
    """
    calls = []

    class Marker:
        def __eq__(self, _other):
            calls.append("marker equality")
            pytest.fail("Marker identities must never invoke equality")

        @property
        def function(self):
            calls.append("marker function")
            pytest.fail("Marker function values must remain unread")

        @property
        def keywords(self):
            calls.append("marker keywords")
            pytest.fail("Marker keyword values must remain unread")

        def __call__(self, *_args, **_kwargs):
            calls.append("marker call")
            pytest.fail("Registration markers must never be invoked")

    Marker.__name__ = "_PropertyDeferred"
    bpy, props = ModuleType("owned_bpy_marker_model"), ModuleType("owned_props_marker_model")
    bpy.props, bpy.types = props, NS()
    bpy.app = NS(build_hash=build, version=graph.BUILDS[build])
    props._PropertyDeferred = Marker
    rows = tuple(row for row in _MARKER_MODEL_ROWS if not scalar_only or row[1] == "active_selection_set")
    targets = {}
    for _owner, _name, _kind, _readonly, target in rows:
        if target is not None:
            targets[target] = type(target, (), {"bl_rna": rna(target)})
            setattr(bpy.types, target, targets[target])
    classes = {}
    for owner, name, kind, readonly, target in rows:
        cls = classes.setdefault(owner, type(owner, (), {"bl_rna": rna(owner)}))
        cls.bl_rna.properties.append(Property(name, kind, readonly=readonly, runtime=True,
                                             fixed_type=targets[target].bl_rna if target else None))
        setattr(cls, name, Marker())
        setattr(bpy.types, owner, cls)
    native_field_guard = graph._unshadowed
    install_model_catalogs(graph, monkeypatch, bpy)
    monkeypatch.setattr(graph, "_unshadowed", native_field_guard)
    slots = NS(call=object(), getsets=(object(), object()))

    def modeled_native_deferred_slot_policy(owner_bpy):
        """Only the source-qualified native C slot layout is an assumption."""
        assert owner_bpy is bpy
        if (type(bpy) is not ModuleType or type(bpy.props) is not ModuleType
                or bpy.props.__dict__.get("_PropertyDeferred") is not Marker):
            raise graph.refused("MODELED_NATIVE_MARKER_ALIAS_CHANGED")
        return Marker, (bpy, bpy.props, Marker, (Marker, object), slots.call, slots.getsets,
                        object.__getattribute__, object.__setattr__, build)

    def modeled_native_registered_lookup(owner_bpy, name, check):
        """Explicit C lookup boundary for recursion-time drift injection only."""
        assert owner_bpy is bpy
        calls.append(("registered target", name))
        check()
        target = targets[name]
        check()
        return graph._constructor_proof(bpy, name, target)

    monkeypatch.setattr(graph, "_deferred_type", modeled_native_deferred_slot_policy)
    monkeypatch.setattr(graph, "_registered_target", modeled_native_registered_lookup)
    return NS(bpy=bpy, props=props, Marker=Marker, classes=classes, calls=calls, slots=slots,
              rows=rows, target_lookup=modeled_native_registered_lookup)


@pytest.mark.parametrize("build", [b"62c1db4208e8", b"d13f752e3b9c"])
def test_seven_existing_marker_rows_preserve_only_six_registered_targets(graph, monkeypatch, build):
    model = make_runtime_marker_model(graph, monkeypatch, build=build)
    reader = graph._Reader(model.bpy, lambda: None)
    retained = []
    for kind, cls in model.classes.items():
        props = reader.class_catalog(kind)
        rows = [graph.property_metadata(prop, fixed_types=False) for prop in props]
        retained.extend(graph._runtime_marker_origins(model.bpy, cls, kind, rows))
        assert reader.class_catalog(kind) == props  # The real cache path also checks markers.
    assert len(retained) == 7
    assert sorted(name for tag, name in model.calls if tag == "registered target") == sorted(
        target for _owner, _name, _kind, _readonly, target in _MARKER_MODEL_ROWS if target is not None)
    assert len(model.calls) == 6
    assert all(type(entry[1]) is model.Marker for entry in retained)
    assert all(entry[2][0] is model.bpy and entry[2][1] is model.props for entry in retained)
    assert graph._same_markers(tuple(retained), tuple(retained))


def test_existing_scalar_marker_has_no_constructor_or_runtime_value_read(graph, monkeypatch):
    model = make_runtime_marker_model(graph, monkeypatch, scalar_only=True)
    reader = graph._Reader(model.bpy, lambda: None)
    props = reader.class_catalog("Object")
    assert len(props) == 1 and props[0].identifier == "active_selection_set"
    assert reader.class_catalog("Object") is props
    assert model.calls == []


@pytest.mark.parametrize("present", [False, True])
def test_scalar_marker_does_not_replace_current_native_storage_absence_gate(graph, monkeypatch, addon_package, present):
    """The C is_property_set descriptor is modeled; its refusal is real."""
    model = make_runtime_marker_model(graph, monkeypatch, scalar_only=True)
    cls, presence_calls = model.classes["Object"], []
    owner = cls()
    model.bpy.types.bpy_struct = type("ModeledNativeStruct", (), {})
    guard = importlib.import_module(f"{addon_package}.uv_edit_guard")

    def modeled_native_presence_descriptor(base, canonical):
        assert base is model.bpy.types.bpy_struct and canonical is cls

        def presence(actual, field, *, ghost):
            assert actual is owner
            presence_calls.append((field, ghost))
            return present

        return presence

    monkeypatch.setattr(guard, "_native_method_descriptor", modeled_native_presence_descriptor)
    reader = graph._Reader(model.bpy, lambda: None)
    if present:
        with pytest.raises(graph.BridgeError) as failure:
            graph._runtime_absent(reader, owner, "Object")
        assert failure.value.context["reason"] == "STORED_RUNTIME_PROPERTY_UNQUALIFIED"
    else:
        graph._runtime_absent(reader, owner, "Object")
        assert graph._primitive_fields(reader, owner, "Object") == {}
    assert presence_calls == [("active_selection_set", False)]
    assert model.calls == []


@pytest.mark.parametrize("change", ["kind", "readonly", "registered", "array", "enum_flag", "owner", "unknown", "duplicate"])
def test_literal_runtime_marker_extraction_refuses_unreviewed_declaration_shapes(graph, monkeypatch, change):
    model = make_runtime_marker_model(graph, monkeypatch, scalar_only=True)
    cls = model.classes["Object"]
    rows = [graph.property_metadata(prop, fixed_types=False) for prop in cls.bl_rna.properties]
    kind = "Object"
    if change == "kind":
        rows[0]["type"] = "FLOAT"
    elif change == "readonly":
        rows[0]["readonly"] = True
    elif change == "registered":
        rows[0]["registered"] = True
    elif change == "array":
        rows[0]["array_length"] = 1
    elif change == "enum_flag":
        rows[0]["enum_flag"] = False
    elif change == "owner":
        kind = "Scene"
    elif change == "unknown":
        rows[0]["identifier"] = "unknown_runtime"
    else:
        rows.append(dict(rows[0]))
    with pytest.raises(graph.BridgeError):
        graph._runtime_marker_origins(model.bpy, cls, kind, rows)
    assert model.calls == []


@pytest.mark.parametrize("change", ["kind", "readonly", "runtime", "registered", "array", "unknown", "duplicate"])
def test_marker_exemption_requires_exact_existing_row_before_any_target_lookup(graph, monkeypatch, change):
    model = make_runtime_marker_model(graph, monkeypatch, scalar_only=True)
    prop = model.classes["Object"].bl_rna.properties[0]
    if change == "kind":
        prop.type = "BOOLEAN"
    elif change == "readonly":
        prop.is_readonly = True
    elif change == "runtime":
        prop.is_runtime = False
    elif change == "registered":
        prop.is_registered = True
    elif change == "array":
        prop._array_length = 1
    elif change == "unknown":
        prop.identifier = "unknown_runtime"
        model.classes["Object"].unknown_runtime = model.Marker()
    else:
        model.classes["Object"].bl_rna.properties.append(prop)
    with pytest.raises(graph.BridgeError):
        graph._Reader(model.bpy, lambda: None).class_catalog("Object")
    assert model.calls == []


@pytest.mark.parametrize("case", ["static_marker", "unknown_marker", "python_property", "foreign_marker", "subclass"])
def test_nonexempt_raw_fields_keep_real_generic_shadow_refusal_without_getters(graph, monkeypatch, case):
    model = make_runtime_marker_model(graph, monkeypatch, scalar_only=True)
    cls = model.classes["Object"]
    native_guard = graph._unshadowed
    if case == "static_marker":
        cls.bl_rna.properties[0].is_runtime = False
        install_model_catalogs(graph, monkeypatch, model.bpy)
        # Reinstall the real guard after the synthetic metadata pin update.
        monkeypatch.setattr(graph, "_unshadowed", native_guard)
    elif case == "unknown_marker":
        cls.bl_rna.properties[0].identifier = "unknown_runtime"
        cls.unknown_runtime = model.Marker()
        rows = [graph.property_metadata(prop, fixed_types=False) for prop in cls.bl_rna.properties]
        with pytest.raises(graph.BridgeError):
            graph._runtime_marker_origins(model.bpy, cls, "Object", rows)
        assert model.calls == []
        return
    elif case == "python_property":
        def forbidden(_self):
            model.calls.append("foreign owner getter")
            pytest.fail("Foreign owner field must never be read")
        cls.active_selection_set = property(forbidden)
    elif case == "foreign_marker":
        cls.active_selection_set = object()
    else:
        cls.active_selection_set = type("SubMarker", (model.Marker,), {})()
    with pytest.raises(graph.BridgeError) as failure:
        graph._Reader(model.bpy, lambda: None).class_catalog("Object")
    assert failure.value.context["reason"] == "NATIVE_FIELD_PYTHON_SHADOW:active_selection_set"
    assert model.calls == []


@pytest.mark.parametrize("change", ["marker", "alias", "module", "slots", "schema", "property_pointer", "property_order", "owner_rna"])
def test_registered_lookup_drift_cannot_rebase_marker_schema_or_property_identity(graph, monkeypatch, change):
    model = make_runtime_marker_model(graph, monkeypatch)
    cls, changed = model.classes["Scene"], []

    def lookup_then_drift(bpy, name, check):
        proof = model.target_lookup(bpy, name, check)
        if not changed:
            changed.append(change)
            if change == "marker":
                cls.cycles = model.Marker()
            elif change == "alias":
                model.props._PropertyDeferred = type("Replacement", (), {})
            elif change == "module":
                replacement = ModuleType("replacement_props")
                replacement._PropertyDeferred = model.Marker
                bpy.props = replacement
            elif change == "slots":
                model.slots.call = object()
            elif change == "schema":
                cls.bl_rna.properties[0].is_readonly = False
            elif change == "property_pointer":
                old = cls.bl_rna.properties[0]
                cls.bl_rna.properties[0] = Property(old.identifier, old.type, readonly=True, runtime=True,
                                                   fixed_type=old._fixed_type)
            elif change == "property_order":
                cls.bl_rna.properties.reverse()
            else:
                cls.bl_rna = rna("Scene", cls.bl_rna.properties)
        return proof

    monkeypatch.setattr(graph, "_registered_target", lookup_then_drift)
    with pytest.raises(graph.BridgeError):
        graph._Reader(model.bpy, lambda: None).class_catalog("Scene")
    assert changed == [change]
    assert all(type(call) is tuple and call[0] == "registered target" for call in model.calls)


@pytest.mark.parametrize("change", ["marker", "remove_marker", "alias", "module", "slots", "nonexempt_shadow"])
def test_cached_catalog_rechecks_marker_and_nonexempt_shadow_identity(graph, monkeypatch, change):
    model = make_runtime_marker_model(graph, monkeypatch, scalar_only=True)
    cls = model.classes["Object"]
    cls.bl_rna.properties.append(Property("authored_label"))
    native_guard = graph._unshadowed
    install_model_catalogs(graph, monkeypatch, model.bpy)
    monkeypatch.setattr(graph, "_unshadowed", native_guard)
    reader = graph._Reader(model.bpy, lambda: None)
    reader.class_catalog("Object")
    if change == "marker":
        cls.active_selection_set = model.Marker()
    elif change == "remove_marker":
        del cls.active_selection_set
    elif change == "alias":
        model.props._PropertyDeferred = object
    elif change == "module":
        replacement = ModuleType("replacement_props")
        replacement._PropertyDeferred = model.Marker
        model.bpy.props = replacement
    elif change == "slots":
        model.slots.getsets = (object(), model.slots.getsets[1])
    else:
        def forbidden(_self):
            model.calls.append("foreign cached getter")
            pytest.fail("A cache hit cannot invoke a new field shadow")
        cls.authored_label = property(forbidden)
    with pytest.raises(graph.BridgeError):
        reader.class_catalog("Object")
    assert model.calls == []


@pytest.mark.parametrize("replacement", ["canonical_marker", "foreign_property"])
def test_cached_marker_absence_is_not_an_exemption_for_later_replacement(graph, monkeypatch, replacement):
    model = make_runtime_marker_model(graph, monkeypatch, scalar_only=True)
    cls = model.classes["Object"]
    del cls.active_selection_set
    reader = graph._Reader(model.bpy, lambda: None)
    reader.class_catalog("Object")
    if replacement == "canonical_marker":
        cls.active_selection_set = model.Marker()
    else:
        def forbidden(_self):
            model.calls.append("new foreign getter")
            pytest.fail("A previously absent raw marker cannot authorize a later shadow")
        cls.active_selection_set = property(forbidden)
    with pytest.raises(graph.BridgeError):
        reader.class_catalog("Object")
    assert model.calls == []


def test_marker_origin_comparison_uses_identity_for_retained_native_slot_objects(graph, monkeypatch):
    model = make_runtime_marker_model(graph, monkeypatch, scalar_only=True)

    class IdentityOnly:
        def __eq__(self, _other):
            model.calls.append("origin equality")
            pytest.fail("Native origin comparison must not call object equality")

    model.slots.call, model.slots.getsets = IdentityOnly(), (IdentityOnly(), IdentityOnly())
    cls = model.classes["Object"]
    rows = [graph.property_metadata(prop, fixed_types=False) for prop in cls.bl_rna.properties]
    before = graph._runtime_marker_origins(model.bpy, cls, "Object", rows)
    same = graph._runtime_marker_origins(model.bpy, cls, "Object", rows)
    assert graph._same_markers(before, same)
    model.slots.getsets = (IdentityOnly(), model.slots.getsets[1])
    changed = graph._runtime_marker_origins(model.bpy, cls, "Object", rows)
    assert not graph._same_markers(before, changed)
    assert model.calls == []


def test_marker_cache_retains_prior_object_until_pass_reset_and_never_compares_equality(graph, monkeypatch):
    import gc
    import weakref

    model = make_runtime_marker_model(graph, monkeypatch, scalar_only=True)
    cls = model.classes["Object"]
    retained = weakref.ref(cls.active_selection_set)
    reader = graph._Reader(model.bpy, lambda: None)
    reader.class_catalog("Object")
    cls.active_selection_set = model.Marker()
    gc.collect()
    assert retained() is not None, "CAS must keep the prior marker alive, preventing address reuse"
    with pytest.raises(graph.BridgeError):
        reader.class_catalog("Object")
    assert model.calls == []
    reader.begin_pass()
    gc.collect()
    assert retained() is None
    assert reader.class_catalog("Object")
    assert model.calls == []


@pytest.mark.parametrize("case", ["missing", "python_alias", "foreign_meta", "subclass", "call_slot", "descriptor_slot", "foreign_module", "module_subclass", "foreign_bpy"])
def test_actual_native_marker_qualifier_refuses_python_shapes_without_getters_or_calls(graph, case):
    calls = []

    class HostileMeta(type):
        def __getattribute__(cls, name):
            calls.append(("foreign meta", name))
            pytest.fail("Foreign metaclass attribute hooks must remain unread")

    class Marker:
        @property
        def function(self):
            calls.append("function")
            pytest.fail("Native qualifier must not read function payload")

        @property
        def keywords(self):
            calls.append("keywords")
            pytest.fail("Native qualifier must not read keywords payload")

        def __call__(self):
            calls.append("call")
            pytest.fail("Native qualifier must never invoke marker")

    Marker.__name__ = "_PropertyDeferred"
    bpy, props = ModuleType("owned_bpy_qualifier_negative"), ModuleType("owned_props_qualifier_negative")
    bpy.props, bpy.app, props._PropertyDeferred = props, NS(build_hash=b"62c1db4208e8"), Marker
    if case == "missing":
        del props._PropertyDeferred
    elif case == "foreign_meta":
        props._PropertyDeferred = HostileMeta("_PropertyDeferred", (), {})
    elif case == "subclass":
        props._PropertyDeferred = type("_PropertyDeferred", (Marker,), {})
    elif case == "call_slot":
        Marker.__call__ = object.__str__
    elif case == "descriptor_slot":
        Marker.__get__ = lambda *_args: calls.append("descriptor")
    elif case == "foreign_module":
        bpy.props = NS(_PropertyDeferred=Marker)
    elif case == "module_subclass":
        class ForeignModule(ModuleType):
            def __getattribute__(self, name):
                calls.append(("module getter", name))
                pytest.fail("Foreign module hooks must remain unread")
        bpy.props = ForeignModule("foreign_props")
    elif case == "foreign_bpy":
        bpy = NS(props=props, app=bpy.app)
    with pytest.raises(graph.BridgeError):
        graph._deferred_type(bpy)
    assert calls == []


def test_user_keys_method_requires_exact_native_descriptor_without_shadow(graph):
    bpy = NS(types=NS(bpy_struct=dict))
    assert graph._keys_method(bpy, dict) is dict.__dict__["keys"]
    calls = []

    class Shadow(dict):
        def keys(self):
            calls.append("keys")
            raise TypeError("Synthetic callback failure must never be mistaken for no USER support")

    with pytest.raises(graph.BridgeError) as failure:
        graph._keys_method(bpy, Shadow)
    assert failure.value.context["reason"] == "NATIVE_CUSTOM_KEYS_METHOD_CHANGED"
    assert calls == []


def test_embedded_master_reverse_map_is_empty_and_direct_object_has_scene_owner_only(capture_model):
    model = capture_model
    assert model.collection.is_embedded_data is True
    assert model.reverse[model.collection] == set() and model.reverse[model.obj] == {model.scene}
    assert model.scene.user_of_id(model.collection) == 2
    assert model.scene.user_of_id(model.obj) == 2
    assert model.capture().objects == (model.obj,)


@pytest.mark.parametrize("owner", ["scene", "obj", "material"])
def test_any_embedded_master_external_reverse_alias_refuses_before_payload(graph, capture_model, owner):
    model = capture_model
    model.reverse[model.collection].add(getattr(model, owner))
    with pytest.raises(graph.BridgeError) as failure:
        model.capture()
    assert failure.value.context["reason"] == "EMBEDDED_MASTER_EXTERNAL_CONSUMER"
    assert model.counters["pixels"] == model.counters["packed"] == 0


@pytest.mark.parametrize("case", ["root_extra", "object_extra", "missing_base_extra", "not_embedded"])
def test_source_role_sum_rejects_extra_or_compensating_reference_counts(graph, capture_model, case):
    model = capture_model
    if case == "not_embedded":
        model.collection.is_embedded_data = False
    else:
        target = model.collection if case == "root_extra" else model.obj
        model.scene._custom["_synthetic_extra_count"] = {target: 1}
        if case == "missing_base_extra":
            model.layer.objects.clear()
    with pytest.raises(graph.BridgeError):
        model.capture()
    assert model.counters["pixels"] == model.counters["packed"] == 0


@pytest.mark.parametrize("query", ["user_map", "user_of_id", "layer_children"])
def test_native_reference_query_visible_context_drift_is_not_rebased(graph, capture_model, query):
    model = capture_model
    if query == "user_map":
        original = model.bpy.data.user_map
        def changed(**kwargs):
            result = original(**kwargs)
            model.scene.frame_current += 1
            return result
        model.bpy.data.user_map = changed
    elif query == "user_of_id":
        original = model.scene.user_of_id
        def changed(target):
            result = original(target)
            model.scene.frame_current += 1
            return result
        model.scene.user_of_id = changed
    else:
        class ChangedChildren:
            def __iter__(self):
                model.scene.frame_current += 1
                return iter(())
        model.layer.layer_collection.children = ChangedChildren()
    with pytest.raises(graph.BridgeError) as failure:
        model.capture()
    assert failure.value.context["reason"] == "NATIVE_REFERENCE_QUERY_CONTEXT_CHANGED"
    assert model.counters["pixels"] == model.counters["packed"] == 0


@pytest.mark.parametrize("name,depth,expected", [
    ("_CATALOG_HASHES", 2, "475f741ad6e7bded5de9050cbea011686fa27f8736b4c7edb972e20513df9297"),
    ("_STATIC_CATALOG_HASHES", 2, "082b4f8a4a48b0b6b15a2bc02bf09db0316bda1a15796a66e53dc39c61b0d983"),
    ("_FIXED_TARGETS", 3, "24c1b4eae75820b263b277b151da8e42173ef0a20b99997d4420af2bd7cc9ad0"),
    ("_RUNTIME_MARKER_ROWS", 1, "556d58b4040e3f184ef697d596aeca947796d458db3dbf26c28059f19d8fc572"),
])
def test_immutable_pin_tables_preserve_complete_prechange_contents(graph, name, depth, expected):
    """Digests are independent snapshots of every original map key and value."""
    def detached(table, levels):
        if levels == 0:
            return table
        assert type(table) is tuple
        def key(value):
            return ["bytes", value.hex()] if type(value) is bytes else (
                ["tuple", list(value)] if type(value) is tuple else ["str", value])
        return sorted([[key(k), detached(v, levels - 1)] for k, v in table],
                      key=lambda row: json.dumps(row[0]))
    payload = json.dumps(detached(getattr(graph, name), depth), ensure_ascii=True, separators=(",", ":")).encode()
    assert hashlib.sha256(payload).hexdigest() == expected


@pytest.mark.parametrize("fault", ["container", "key", "entry", "entry_key", "value", "marker_part", "nested_entry"])
def test_pin_lookup_refuses_foreign_dispatch_before_callbacks(graph, fault):
    calls = []
    class ForeignTuple(tuple):
        def __len__(self):
            calls.append("length")
            pytest.fail("Foreign tuple length was called")
        def __iter__(self):
            calls.append("iteration")
            pytest.fail("Foreign tuple iteration was called")
        def __eq__(self, _other):
            calls.append("equality")
            pytest.fail("Foreign tuple equality was called")
    class ForeignString(str):
        def __len__(self):
            calls.append("length")
            pytest.fail("Foreign string length was called")
        def __eq__(self, _other):
            calls.append("equality")
            pytest.fail("Foreign string equality was called")
        def __hash__(self):
            calls.append("hash")
            pytest.fail("Foreign string hash was called")
    table, key = (("known", "value"),), "known"
    if fault == "container":
        table = ForeignTuple(table)
    elif fault == "key":
        key = ForeignString("known")
    elif fault == "entry":
        table = (ForeignTuple(("known", "value")),)
    elif fault == "entry_key":
        table = ((ForeignString("known"), "value"),)
    elif fault == "value":
        table = (("known", ForeignString("value")),)
    elif fault == "marker_part":
        key = ("Scene", "cycles")
        table = ((key, (ForeignString("POINTER"), True, True, False, None, None)),)
    else:
        table = (("known", (ForeignTuple(("field", "value")),)),)
    with pytest.raises(graph.BridgeError):
        value = graph._pin_get(table, key, None, "rows" if fault == "nested_entry" else "text")
        if fault == "nested_entry":
            graph._pin_get(value, "field")
    assert calls == []


@pytest.mark.parametrize("table,key", [
    ((("same", "one"), ("same", "two")), "same"),
    ((("triple", "one", "extra"),), "triple"),
    (((False, "wrong key type"),), "absent"),
    (((("Scene", "cycles"), ("POINTER",)),), ("Scene", "cycles")),
    (tuple((str(index), "value") for index in range(4097)), "absent"),
])
def test_pin_lookup_rejects_duplicate_malformed_or_overbudget_rows(graph, table, key):
    with pytest.raises(graph.BridgeError):
        graph._pin_get(table, key)


def test_pin_lookup_keeps_missing_and_exact_typed_key_semantics(graph):
    table = ((b"build", (("kind", (("field", "Target"),)),)), ("build", "literal"))
    assert graph._pin_get(table, "build") == "literal"
    assert graph._pin_get(graph._pin_get(graph._pin_get(table, b"build", None, "rows"), "kind", None, "rows"), "field") == "Target"
    assert graph._pin_get(table, "missing") is None
    assert graph._pin_get((), "missing", ()) == ()
    with pytest.raises(graph.BridgeError):
        graph._pin_get(table, "missing", {})


@pytest.mark.parametrize("kind,value", [("text", (("field", "Target"),)), ("rows", "Target"),
                                        ("marker", ("POINTER", object(), True, False, None, None))])
def test_pin_lookup_refuses_wrong_terminal_type_before_native_key_use(graph, kind, value):
    with pytest.raises(graph.BridgeError):
        graph._pin_get((("kind", value),), "kind", None, kind)


@pytest.mark.parametrize("fault", ["container", "entry", "key", "value", "marker"])
def test_pin_lookup_does_not_dispatch_malicious_metaclasses(graph, fault):
    calls = []
    class Meta(type):
        def __hash__(cls):
            calls.append("metaclass_hash")
            raise AssertionError("Foreign class was hashed")
        def __eq__(cls, _other):
            calls.append("metaclass_equality")
            raise AssertionError("Foreign class was compared")
    class Tuple(tuple, metaclass=Meta):
        def __iter__(self):
            calls.append("iteration")
            raise AssertionError("Foreign tuple was iterated")
        def __len__(self):
            calls.append("length")
            raise AssertionError("Foreign tuple length was read")
        def __repr__(self):
            calls.append("repr")
            raise AssertionError("Foreign tuple was formatted")
    class Text(str, metaclass=Meta):
        def __repr__(self):
            calls.append("repr")
            raise AssertionError("Foreign text was formatted")
    table, key = (("known", "value"),), "known"
    if fault == "container":
        table = Tuple(table)
    elif fault == "entry":
        table = (Tuple(("known", "value")),)
    elif fault == "key":
        table = ((Text("known"), "value"),)
    elif fault == "value":
        table = (("known", Text("value")),)
    else:
        key = ("Scene", "cycles")
        table = ((key, (Text("POINTER"), True, True, False, None, None)),)
    with pytest.raises(graph.BridgeError):
        graph._pin_get(table, key)
    assert calls == []


@pytest.mark.parametrize("name", ["UVMap", ".pn.UVMap"])
def test_b2_inventory_describes_single_without_relaxing_original_graph_reader(graph, monkeypatch, addon_package, name):
    """Metadata inspection is separate from the old observer's ARRAY gate."""
    model = make_capture_model(graph, monkeypatch, addon_package, build=b"d13f752e3b9c")
    target = next(attribute for attribute in model.attributes if attribute.name == name)
    target.storage_type = "SINGLE"
    reader = graph._Reader(model.bpy, model.check)
    counts = {key: len(getattr(model.mesh, key)) for key in ("vertices", "edges", "loops", "polygons")}
    headers, uv, auxiliary, physical = graph._attribute_inventory(reader, model.mesh, counts, ("UVMap",))
    assert (name, target.domain, target.data_type) in headers and name in uv
    assert (name, target.domain, target.data_type, "SINGLE", len(target._data)) in physical
    assert all(type(row) is tuple and type(row[1]) is bool for row in auxiliary)
    assert model.counters["attribute_data"] == model.counters["pixels"] == model.counters["packed"] == 0

    class NoGeometryIteration:
        def __len__(self):
            return counts["vertices"]
        def __iter__(self):
            pytest.fail("Old graph iterated geometry before refusing SINGLE")

    model.mesh.vertices = NoGeometryIteration()
    with pytest.raises(graph.BridgeError) as failure:
        model.capture()
    assert failure.value.context["reason"] == "ATTRIBUTE_SINGLE_OR_UNKNOWN_STORAGE"
    assert model.counters["attribute_data"] == model.counters["pixels"] == model.counters["packed"] == 0


def test_legacy_keys_keep_two_argument_semantics_and_new_sdna_policy_is_separate(graph):
    calls = []
    class Owner:
        def keys(self):
            calls.append("legacy")
            return ["known"]
    owner = Owner()
    assert graph._keys(owner, {"known"}) == ("known",)
    assert calls == ["legacy"]
    reader = NS(build=b"d13f752e3b9c", catalog=lambda *_args: ())
    assert graph._keys(reader, owner, "NodeSocketFloat", set()) == ()
    assert calls == ["legacy"]
    with pytest.raises(graph.BridgeError):
        graph._keys(reader, owner, "NodeSocketFloat", {"known"})
    assert calls == ["legacy"]


def native_wrapper_alias(owner):
    """Separate Python wrapper with the same synthetic native ID/address."""
    alias = object.__new__(type(owner))
    alias.__dict__.update(vars(owner))
    assert alias is not owner and alias.as_pointer() == owner.as_pointer()
    return alias


def test_qualified_socket_mode_uses_native_owner_identity_without_changing_legacy_shape(
    graph, monkeypatch, addon_package,
):
    model = make_capture_model(graph, monkeypatch, addon_package, build=b"d13f752e3b9c")
    reader = graph._Reader(model.bpy, model.check)
    socket = model.texture.outputs[0]
    expected = graph._socket(reader, graph._Stream(), socket, model.texture)
    socket.node = native_wrapper_alias(model.texture)
    socket.id_data = native_wrapper_alias(model.tree)
    retained = [model.tree, model.texture, socket]
    original = graph._node_identity(reader, model.texture, model.tree, retained)
    # 5.2 sockets have no USER storage; even a model keys callback must not run.
    def forbidden(_owner):
        pytest.fail("Qualified5.2 socket attempted a USER-IDProperty query")
    monkeypatch.setattr(type(socket), "keys", forbidden)
    observed = graph._socket(reader, graph._Stream(), socket, model.texture, model.tree, retained)
    assert observed == expected
    assert graph._node_identity(reader, socket.node, model.tree, retained) == original
    with pytest.raises(graph.BridgeError) as failure:
        graph._socket(reader, graph._Stream(), socket, model.texture)
    assert failure.value.context["reason"] == "SOCKET_OWNER_CHANGED"


def test_qualified_leaf_owner_refusal_precedes_socket_payload_getter(graph, monkeypatch, addon_package):
    model = make_capture_model(graph, monkeypatch, addon_package, build=b"d13f752e3b9c")
    reader = graph._Reader(model.bpy, model.check)
    socket = model.texture.outputs[0]
    foreign_tree = native_wrapper_alias(model.tree)
    foreign_tree.pointer += 1
    socket.id_data = foreign_tree
    calls = []
    def forbidden(_owner):
        calls.append("default")
        raise AssertionError("Foreign-owned socket payload was read")
    monkeypatch.setattr(type(socket), "default_value", property(forbidden), raising=False)
    with pytest.raises(graph.BridgeError) as failure:
        graph._socket(reader, graph._Stream(), socket, model.texture, model.tree, [model.tree])
    assert failure.value.context["reason"] == "RNA_NATIVE_OWNER_CHANGED"
    assert calls == []


def test_qualified_mapping_mode_retains_complete_old_fields_with_equivalent_owner_wrappers(
    graph, monkeypatch, addon_package,
):
    model = make_capture_model(graph, monkeypatch, addon_package, build=b"d13f752e3b9c")
    reader = graph._Reader(model.bpy, model.check)
    expected = graph._mapping(reader, graph._Stream(), model.texture, model.tree)
    mapping = model.texture.color_mapping
    for nested in (model.texture.texture_mapping, mapping, mapping.color_ramp, *mapping.color_ramp.elements):
        nested.id_data = native_wrapper_alias(model.tree)
    actual = graph._mapping(reader, graph._Stream(), model.texture, model.tree, [model.tree, model.texture])
    assert actual == expected
    assert actual["color_mapping"]["color_ramp"]["elements"][1]["color"] == graph._vector((1., 1., 1., 1.), 4)
    with pytest.raises(graph.BridgeError) as failure:
        graph._mapping(reader, graph._Stream(), model.texture, model.tree)
    assert failure.value.context["reason"] == "MAPPING_NATIVE_OWNER_CHANGED"
