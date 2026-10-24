"""The rigid preflight closes generic RNA readers before resolving getters."""

from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


class Properties(dict):
    def __iter__(self):
        return iter(self.values())


class RNA(NS):
    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other


class Native:
    def __init__(self, rna, **values):
        self.bl_rna = rna
        self.values = values
        self.hazards = {}
        self.raw = {}

    def keys(self):
        return self.raw.keys()

    def __getattr__(self, name):
        if name in self.hazards:
            self.hazards[name].append(name)
            raise AssertionError("Unreviewed getter resolved: " + name)
        if name in self.values:
            return self.values[name]
        raise AttributeError(name)


@pytest.fixture
def snapshot_case(addon_package):
    module = importlib.import_module(f"{addon_package}.tools._rigid_snapshot_scope")
    errors = importlib.import_module(f"{addon_package}.errors")
    types = NS()
    owners = {}

    def prop(name, kind="FLOAT", *, runtime=False, readonly=False):
        return NS(identifier=name, type=kind, is_runtime=runtime, is_readonly=readonly,
                  is_array=False, is_registered=False, is_registered_optional=False, default=0)

    def owner(label, identifier, fields=(), **values):
        rna = RNA(identifier=identifier, properties=Properties({name: prop(name, kind) for name, kind in fields}))
        setattr(types, identifier, NS(bl_rna=rna))
        result = Native(rna, **values)
        owners[label] = result
        return result

    units = owner("units", "UnitSettings", (("scale_length", "FLOAT"),), scale_length=1.)
    weights = owner("weights", "EffectorWeights", (("gravity", "FLOAT"),), gravity=1.)
    collection = owner("collection", "Collection")
    # Both collections deliberately use one canonical descriptor.
    constraints = Native(collection.bl_rna)
    owners["constraint_collection"] = constraints
    membership = owner("membership", "VertexGroupElement", (("group", "INT"), ("weight", "FLOAT")), group=0, weight=.5)
    vertex = owner("vertex", "MeshVertex", (("groups", "COLLECTION"),), groups=[membership])
    edge = owner("edge", "MeshEdge", (("vertices", "INT"),), vertices=(0, 1))
    loop = owner("loop", "MeshLoop", (("vertex_index", "INT"), ("edge_index", "INT")), vertex_index=0, edge_index=0)
    polygon = owner("polygon", "MeshPolygon", (("vertices", "INT"),), vertices=(0, 1, 2))
    attribute_value = owner("attribute_value", "FloatAttributeValue", (("value", "FLOAT"),), value=.5)
    attribute = owner("attribute", "FloatAttribute", (("data_type", "ENUM"), ("domain", "ENUM"),
        ("name", "STRING"), ("data", "COLLECTION")), data_type="FLOAT", domain="POINT", name="Weight", data=[attribute_value])
    mesh = owner("mesh", "Mesh", (("shape_keys", "POINTER"), ("vertices", "COLLECTION"),
        ("edges", "COLLECTION"), ("loops", "COLLECTION"), ("polygons", "COLLECTION"),
        ("attributes", "COLLECTION"), ("materials", "COLLECTION")), shape_keys=None, vertices=[vertex],
        edges=[edge], loops=[loop], polygons=[polygon], attributes=[attribute], materials=[])
    group = owner("group", "VertexGroup", (("name", "STRING"),), name="Weights")
    slot = owner("slot", "MaterialSlot", (("link", "ENUM"), ("material", "POINTER")), link="DATA", material=None)
    rigid_body = owner("rigid_body", "RigidBodyObject", (("mass", "FLOAT"),), mass=1.)
    obj = owner("object", "Object", (("type", "ENUM"), ("animation_data", "POINTER"), ("pose", "POINTER"),
        ("modifiers", "COLLECTION"), ("constraints", "COLLECTION"), ("rigid_body", "POINTER"),
        ("data", "POINTER"), ("vertex_groups", "COLLECTION"), ("material_slots", "COLLECTION")),
        type="MESH", animation_data=None, pose=None, modifiers=[], constraints=[], rigid_body=rigid_body,
        data=mesh, vertex_groups=[group], material_slots=[slot])
    obj.bl_rna.properties.update({name: prop(name, kind) for name, kind in (
        ("name", "STRING"), ("session_uid", "INT"), ("location", "FLOAT"), ("rotation_mode", "ENUM"),
        ("rotation_euler", "FLOAT"), ("rotation_quaternion", "FLOAT"), ("rotation_axis_angle", "FLOAT"),
        ("scale", "FLOAT"), ("delta_location", "FLOAT"), ("delta_rotation_euler", "FLOAT"),
        ("delta_rotation_quaternion", "FLOAT"), ("delta_scale", "FLOAT"),
        ("matrix_parent_inverse", "FLOAT"))})
    mesh.bl_rna.properties.update({name: prop(name, kind) for name, kind in (
        ("session_uid", "INT"), ("users", "INT"), ("library", "POINTER"),
        ("override_library", "POINTER"), ("is_editable", "BOOLEAN"))})
    world = owner("world", "RigidBodyWorld", (("effector_weights", "POINTER"), ("collection", "POINTER"),
        ("constraints", "POINTER"), ("time_scale", "FLOAT")), effector_weights=weights, collection=collection,
        constraints=constraints, time_scale=.75)
    scene = owner("scene", "Scene", (("rigidbody_world", "POINTER"), ("unit_settings", "POINTER")),
        rigidbody_world=world, unit_settings=units)
    return NS(module=module, errors=errors, bpy=NS(types=types), scene=scene, bodies=(obj,),
              owners=owners, prop=prop, owner=owner)


def check(case):
    return case.module.preflight(case.bpy, case.scene, case.bodies)


def rejected(case):
    with pytest.raises(case.errors.BridgeError) as caught:
        check(case)
    assert caught.value.code == "NOT_IMPLEMENTED"
    return caught.value


def test_complete_generic_projection_preflight_is_repeatable_and_does_not_read_values(snapshot_case):
    case = snapshot_case
    reads = []
    for label, field in (("units", "scale_length"), ("weights", "gravity"), ("attribute_value", "value"),
                         ("world", "time_scale"), ("rigid_body", "mass"), ("group", "name")):
        case.owners[label].hazards[field] = reads
    assert check(case) is None
    assert check(case) is None
    assert reads == []


@pytest.mark.parametrize("label", ["world", "units", "weights", "collection", "constraint_collection", "object",
    "rigid_body", "mesh", "vertex", "edge", "loop", "polygon", "membership", "attribute", "attribute_value", "group", "slot"])
def test_every_generic_owner_refuses_runtime_getter_before_resolution(snapshot_case, label):
    case = snapshot_case
    owner = case.owners[label]
    owner.bl_rna.properties["owned_probe"] = case.prop("owned_probe", runtime=True)
    reads = []
    owner.hazards["owned_probe"] = reads
    error = rejected(case)
    assert "runtime RNA property" in error.message
    assert reads == []


def test_late_nested_runtime_descriptor_is_revalidated_before_generic_reader(snapshot_case):
    case = snapshot_case
    check(case)
    value = case.owners["attribute_value"]
    value.bl_rna.properties["late_probe"] = case.prop("late_probe", runtime=True)
    reads = []
    value.hazards["late_probe"] = reads
    with pytest.raises(case.errors.BridgeError):
        check(case)
        reads.append("generic reader entered")
    assert reads == []


@pytest.mark.parametrize("label,field", [("scene", "rigidbody_world"), ("scene", "unit_settings"),
    ("world", "effector_weights"), ("world", "collection"), ("world", "constraints"),
    ("object", "type"), ("object", "animation_data"), ("object", "pose"), ("object", "modifiers"),
    ("object", "constraints"), ("object", "rigid_body"), ("object", "data"),
    ("object", "vertex_groups"), ("object", "material_slots"), ("mesh", "shape_keys"),
    ("mesh", "vertices"), ("mesh", "edges"), ("mesh", "loops"), ("mesh", "polygons"),
    ("mesh", "attributes"), ("mesh", "materials"), ("vertex", "groups"),
    ("membership", "group"), ("membership", "weight"), ("edge", "vertices"),
    ("loop", "vertex_index"), ("loop", "edge_index"), ("polygon", "vertices"),
    ("attribute", "data_type"), ("attribute", "name"), ("attribute", "domain"), ("attribute", "data"),
    ("slot", "link"), ("slot", "material")])
def test_runtime_traversal_field_refused_even_when_readonly(snapshot_case, label, field):
    case = snapshot_case
    owner = case.owners[label]
    prop = owner.bl_rna.properties[field]
    prop.is_runtime = prop.is_readonly = True
    reads = []
    owner.hazards[field] = reads
    rejected(case)
    assert reads == []


@pytest.mark.parametrize("label", ["scene", "world", "units", "weights", "collection", "object", "rigid_body",
    "mesh", "vertex", "edge", "loop", "polygon", "membership", "attribute", "attribute_value", "group", "slot"])
def test_shadowed_native_class_cannot_authorize_generic_reads(snapshot_case, label):
    case = snapshot_case
    owner = case.owners[label]
    owner.bl_rna = RNA(**vars(owner.bl_rna))
    rejected(case)


def test_unknown_nested_value_class_refused_without_reading_its_fields(snapshot_case):
    case = snapshot_case
    owner = case.owners["attribute_value"]
    owner.bl_rna = RNA(identifier="OwnedCustomAttributeValue", properties=Properties())
    reads = []
    owner.hazards["value"] = reads
    rejected(case)
    assert reads == []


def test_readonly_untraversed_runtime_field_never_needs_its_getter(snapshot_case):
    case = snapshot_case
    owner = case.owners["mesh"]
    owner.bl_rna.properties["owned_probe"] = case.prop("owned_probe", runtime=True, readonly=True)
    reads = []
    owner.hazards["owned_probe"] = reads
    check(case)
    assert reads == []


def test_structural_budget_applies_across_all_mesh_collections(snapshot_case, monkeypatch):
    case = snapshot_case
    monkeypatch.setattr(case.module, "MAX_STRUCTURE", 4)
    check(case)
    monkeypatch.setattr(case.module, "MAX_STRUCTURE", 3)
    rejected(case)


def test_attribute_budget_applies_across_distinct_attribute_records(snapshot_case, monkeypatch):
    case = snapshot_case
    attribute = case.owners["attribute"]
    second = Native(attribute.bl_rna, **{**attribute.values, "name": "Second"})
    case.owners["mesh"].values["attributes"].append(second)
    monkeypatch.setattr(case.module, "MAX_ATTRIBUTE_VALUES", 2)
    check(case)
    monkeypatch.setattr(case.module, "MAX_ATTRIBUTE_VALUES", 1)
    rejected(case)


def test_attribute_type_and_value_class_must_agree(snapshot_case):
    case = snapshot_case
    case.owners["attribute"].values["data_type"] = "INT"
    rejected(case)


def test_more_than_256_descriptors_fails_before_generic_reader(snapshot_case):
    case = snapshot_case
    properties = case.owners["world"].bl_rna.properties
    properties.update({f"bounded_{index}": case.prop(f"bounded_{index}") for index in range(257)})
    rejected(case)


@pytest.mark.parametrize("field,value", [("type", "CURVE"), ("animation_data", object()),
    ("pose", object()), ("modifiers", [object()]), ("constraints", [object()])])
def test_unsupported_object_traversal_is_refused_before_generic_snapshot(snapshot_case, field, value):
    case = snapshot_case
    case.owners["object"].values[field] = value
    rejected(case)


def test_shape_key_traversal_refused_before_generic_snapshot(snapshot_case):
    case = snapshot_case
    case.owners["mesh"].values["shape_keys"] = object()
    rejected(case)


@pytest.mark.parametrize("field", ["collection", "constraints"])
def test_missing_world_collection_is_refused(snapshot_case, field):
    case = snapshot_case
    case.owners["world"].values[field] = None
    rejected(case)


def ui_probe(case, label="object"):
    owner = case.owners[label]
    prop = case.prop("active_selection_set", "INT", runtime=True)
    owner.bl_rna.properties[prop.identifier] = prop
    reads = []
    owner.hazards[prop.identifier] = reads
    return owner, prop, reads


def test_unstored_default_ui_index_is_ignored_without_resolving_its_getter(snapshot_case):
    case = snapshot_case
    _unused_owner, _unused_prop, reads = ui_probe(case)
    check(case)
    assert reads == []


@pytest.mark.parametrize("field,value", [("type", "FLOAT"), ("type", "BOOLEAN"), ("default", 1),
    ("is_array", True), ("is_registered", True), ("is_registered_optional", True)])
def test_ui_exception_requires_its_complete_reviewed_descriptor(snapshot_case, field, value):
    case = snapshot_case
    _unused_owner, prop, reads = ui_probe(case)
    setattr(prop, field, value)
    rejected(case)
    assert reads == []


def test_stored_ui_index_refused_even_when_stored_value_is_zero(snapshot_case):
    case = snapshot_case
    owner, _unused_prop, reads = ui_probe(case)
    owner.raw["active_selection_set"] = 0
    rejected(case)
    assert reads == []


@pytest.mark.parametrize("label", ["mesh", "world", "vertex", "group"])
def test_ui_index_exception_does_not_extend_to_other_native_owners(snapshot_case, label):
    case = snapshot_case
    _unused_owner, _unused_prop, reads = ui_probe(case, label)
    rejected(case)
    assert reads == []


def test_ui_exception_still_enforces_raw_property_inventory_bound(snapshot_case):
    case = snapshot_case
    owner, _unused_prop, reads = ui_probe(case)
    owner.raw = {str(index): 0 for index in range(129)}
    rejected(case)
    assert reads == []


@pytest.mark.parametrize("label,field", [("object", field) for field in (
    "name", "session_uid", "location", "rotation_mode", "rotation_euler", "rotation_quaternion",
    "rotation_axis_angle", "scale", "delta_location", "delta_rotation_euler", "delta_rotation_quaternion",
    "delta_scale", "matrix_parent_inverse")] + [("mesh", field) for field in (
    "session_uid", "users", "library", "override_library", "is_editable")])
@pytest.mark.parametrize("defect", ["runtime_readonly", "missing", "wrong_kind"])
def test_direct_identity_and_transform_channels_need_native_descriptors(snapshot_case, label, field, defect):
    case = snapshot_case
    owner = case.owners[label]
    properties = owner.bl_rna.properties
    if defect == "runtime_readonly":
        properties[field].is_runtime = properties[field].is_readonly = True
    elif defect == "missing":
        del properties[field]
    else:
        properties[field].type = "OWNED_UNKNOWN"
    reads = []
    owner.hazards[field] = reads
    rejected(case)
    assert reads == []
