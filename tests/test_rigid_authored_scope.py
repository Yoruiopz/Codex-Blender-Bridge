"""Aggregate, descriptor-first admission of structural rigid Mesh evidence."""

from __future__ import annotations

import copy
import importlib
import itertools
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

    def __deepcopy__(self, memo):
        return self


class Native:
    tokens = itertools.count(1)

    def __init__(self, rna, **values):
        self.bl_rna, self.values = rna, values
        self.pointer = next(self.tokens)
        self.raw, self.hazards, self.reads = {}, {}, []
        self.pointer_reads = 0

    def as_pointer(self):
        self.pointer_reads += 1
        return self.pointer

    def keys(self):
        return self.raw.keys()

    def __getitem__(self, name):
        return self.raw[name]

    def __getattr__(self, name):
        values = object.__getattribute__(self, "values")
        hazards = object.__getattribute__(self, "hazards")
        if name in hazards:
            hazards[name].append(name)
            raise AssertionError("Unadmitted getter resolved: " + name)
        if name in values:
            self.reads.append(name)
            return values[name]
        raise AttributeError(name)


class Layers(list):
    active = None
    active_index = 0


class Attributes(Layers):
    active_color = None
    active_color_index = 0
    render_color_index = 0
    default_color_name = ""
    active_color_name = ""


@pytest.fixture
def authored(addon_package):
    module = importlib.import_module(f"{addon_package}.tools._rigid_authored_scope")
    errors = importlib.import_module(f"{addon_package}.errors")
    types = NS()

    def prop(name, kind="FLOAT", *, readonly=False, runtime=False, width=0, **extra):
        numeric = {"is_array": bool(width), "array_length": width} if kind in {"BOOLEAN", "INT", "FLOAT"} else {}
        return NS(identifier=name, type=kind, is_readonly=readonly, is_runtime=runtime,
                  **numeric, is_registered=False,
                  is_registered_optional=False, default=0, **extra)

    def schema(name, fields=(), *, base=None):
        rna = RNA(identifier=name, base=base, properties=Properties({item.identifier: item for item in fields}))
        setattr(types, name, NS(bl_rna=rna))
        return rna

    id_rna = schema("ID")
    ids = (prop("session_uid", "INT", readonly=True), prop("name", "STRING"))
    group = schema("VertexGroupElement", (prop("group", "INT", readonly=True), prop("weight")))
    vertex = schema("MeshVertex", (prop("co", width=3), prop("groups", "COLLECTION", readonly=True)))
    edge = schema("MeshEdge", (prop("vertices", "INT", readonly=True, width=2), prop("select", "BOOLEAN")))
    loop = schema("MeshLoop", (prop("vertex_index", "INT", readonly=True), prop("edge_index", "INT", readonly=True)))
    polygon = schema("MeshPolygon", (prop("vertices", "INT", readonly=True, width=3),
        prop("loop_start", "INT", readonly=True), prop("loop_total", "INT", readonly=True), prop("use_smooth", "BOOLEAN")))
    value = schema("FloatAttributeValue", (prop("value"),))
    attribute = schema("FloatAttribute", (prop("name", "STRING"), prop("domain", "ENUM", readonly=True),
        prop("data_type", "ENUM", readonly=True), prop("data", "COLLECTION", readonly=True, fixed_type=value)))
    uv_value = schema("MeshUVLoop", (prop("uv", width=2), prop("pin_uv", "BOOLEAN"),
                                     prop("select", "BOOLEAN"), prop("select_edge", "BOOLEAN")))
    uv_layer = schema("MeshUVLoopLayer", (prop("name", "STRING"), prop("active", "BOOLEAN", readonly=True),
        prop("active_render", "BOOLEAN"), prop("active_clone", "BOOLEAN"),
        prop("data", "COLLECTION", readonly=True, fixed_type=uv_value)))
    wrapper = schema("UVLoopLayers", (prop("active", "POINTER", readonly=True), prop("active_index", "INT")))
    attribute_wrapper = schema("AttributeGroupMesh", (
        prop("active", "POINTER"), prop("active_index", "INT"), prop("active_color", "POINTER"),
        prop("active_color_index", "INT"), prop("render_color_index", "INT"),
        prop("default_color_name", "STRING"), prop("active_color_name", "STRING")))
    schema("Material", ids, base=id_rna)
    mesh_rna = schema("Mesh", (*ids, prop("has_custom_normals", "BOOLEAN", readonly=True),
        prop("shape_keys", "POINTER", readonly=True), prop("vertices", "COLLECTION", readonly=True),
        prop("edges", "COLLECTION", readonly=True), prop("loops", "COLLECTION", readonly=True),
        prop("polygons", "COLLECTION", readonly=True), prop("materials", "COLLECTION", readonly=True),
        prop("attributes", "COLLECTION", readonly=True, srna=attribute_wrapper),
        prop("color_attributes", "COLLECTION", readonly=True, srna=attribute_wrapper),
        prop("uv_layer_clone", "POINTER"), prop("uv_layer_stencil", "POINTER"),
        prop("uv_layers", "COLLECTION", readonly=True, srna=wrapper, fixed_type=uv_layer)), base=id_rna)
    object_rna = schema("Object", (*ids, prop("type", "ENUM", readonly=True), prop("data", "POINTER")), base=id_rna)

    def mesh(name="Mesh"):
        layer = Native(uv_layer, name="UVMap", active=True, active_render=True, active_clone=False,
                       data=[Native(uv_value, uv=(.25, .75), pin_uv=False, select=False, select_edge=False)])
        layers = Layers([layer])
        layers.active = layer
        attributes = Attributes([Native(attribute, name="Weight", domain="POINT", data_type="FLOAT", data=[Native(value, value=.5)])])
        attributes.active = attributes[0]
        return Native(mesh_rna, session_uid=next(Native.tokens), name=name, has_custom_normals=False,
            shape_keys=None, vertices=[Native(vertex, co=(1., 2., 3.), groups=[Native(group, group=0, weight=.5)])],
            edges=[Native(edge, vertices=(0, 1), select=False)], loops=[Native(loop, vertex_index=0, edge_index=0)],
            polygons=[Native(polygon, vertices=(0, 1, 2), loop_start=0, loop_total=1, use_smooth=False)],
            attributes=attributes, color_attributes=Attributes(), materials=[],
            uv_layers=layers, uv_layer_clone=layer, uv_layer_stencil=layer)

    def consumer(data, name="Object"):
        return Native(object_rna, session_uid=next(Native.tokens), name=name, type="MESH", data=data)

    first = mesh()
    return NS(module=module, errors=errors, bpy=NS(types=types), mesh=mesh, consumer=consumer,
              first=first, object=consumer(first), prop=prop, schema=schema)


def capture(case, meshes=None, consumers=None):
    return case.module.snapshot_meshes(case.bpy, tuple(meshes or [case.first]),
                                      tuple(consumers if consumers is not None else [case.object]))


def refused(case, **kwargs):
    with pytest.raises(case.errors.BridgeError) as caught:
        capture(case, **kwargs)
    assert caught.value.code == "NOT_IMPLEMENTED"
    return caught.value


def forbid_projection(case, monkeypatch):
    entered = []

    def fail(_plan):
        entered.append(True)
        raise AssertionError("Generic projection started before inventory admission")

    monkeypatch.setattr(case.module, "_project", fail)
    return entered


def test_shared_mesh_captured_once_and_every_consumer_bound(authored, monkeypatch):
    case = authored
    captured = []
    original = case.module._mesh_state

    def counted(plan):
        captured.append(plan)
        return original(plan)

    monkeypatch.setattr(case.module, "_mesh_state", counted)
    result = dict(capture(case, meshes=[case.first, case.first], consumers=[case.object, case.consumer(case.first)]))
    assert len(captured) == len(result["mesh_states"]) == 1
    assert len(result["consumer_bindings"]) == 2
    assert len({binding[1] for binding in result["consumer_bindings"]}) == 1
    assert dict(result["aggregate_counts"])["structure"] == 4


def test_unused_admitted_mesh_is_preserved(authored):
    result = dict(capture(authored, meshes=[authored.first, authored.mesh("Unused")]))
    assert len(result["mesh_states"]) == 2
    assert len(result["consumer_bindings"]) == 1


def test_aggregate_geometry_exhausts_before_any_generic_projection(authored, monkeypatch):
    entered = forbid_projection(authored, monkeypatch)
    monkeypatch.setattr(authored.module, "MAX_STRUCTURE", 7)
    refused(authored, meshes=[authored.first, authored.mesh("Second")])
    assert entered == []


def test_attribute_budget_counts_vector_components_across_meshes(authored, monkeypatch):
    case = authored
    value = case.schema("FloatVectorAttributeValue", (case.prop("vector", width=3),))
    attribute = case.schema("FloatVectorAttribute", (case.prop("name", "STRING"),
        case.prop("domain", "ENUM", readonly=True), case.prop("data_type", "ENUM", readonly=True),
        case.prop("data", "COLLECTION", readonly=True, fixed_type=value)))
    second = case.mesh("Second")
    for mesh in (case.first, second):
        mesh.values["attributes"][:] = [Native(attribute, name="Vector", domain="POINT", data_type="FLOAT_VECTOR",
                                               data=[Native(value, vector=(1., 2., 3.))])]
        mesh.values["attributes"].active = mesh.values["attributes"][0]
    entered = forbid_projection(case, monkeypatch)
    monkeypatch.setattr(case.module, "MAX_ATTRIBUTE_COMPONENTS", 5)
    refused(case, meshes=[case.first, second])
    assert entered == []


def test_full_payload_reservation_exhausts_before_generic_values(authored, monkeypatch):
    case = authored
    limit = dict(dict(capture(case))["aggregate_counts"])["payload_components"]
    entered = forbid_projection(case, monkeypatch)
    monkeypatch.setattr(case.module, "MAX_COMPONENTS", limit - 1)
    assert "payload_components" in refused(case).message
    assert entered == []


def test_custom_normals_refused_without_geometry_getters(authored):
    case = authored
    case.first.values["has_custom_normals"] = True
    reads = []
    case.first.hazards["vertices"] = reads
    assert "Custom split normals" in refused(case).message
    assert reads == []


def test_late_runtime_field_never_runs_or_enters_an_earlier_generic_getter(authored):
    case = authored
    value = case.first.values["attributes"][0].values["data"][0]
    value.bl_rna.properties["late"] = case.prop("late", runtime=True)
    reads = []
    value.hazards["late"] = reads
    case.first.values["vertices"][0].hazards["co"] = reads
    refused(case)
    assert reads == []


@pytest.mark.parametrize("field", ["has_custom_normals", "shape_keys", "vertices", "attributes", "uv_layers"])
def test_runtime_direct_mesh_fields_refuse_before_getters(authored, field):
    case = authored
    prop = case.first.bl_rna.properties[field]
    prop.is_runtime = prop.is_readonly = True
    reads = []
    case.first.hazards[field] = reads
    refused(case)
    assert reads == []


def test_runtime_readonly_uv_selector_refused_before_getter(authored):
    case = authored
    prop = case.bpy.types.UVLoopLayers.bl_rna.properties["active_index"]
    prop.is_runtime = prop.is_readonly = True
    refused(case)


def test_unproven_uv_wrapper_metadata_refuses(authored):
    case = authored
    case.first.bl_rna.properties["uv_layers"].srna = case.bpy.types.MeshUVLoopLayer.bl_rna
    assert "wrapper metadata" in refused(case).message


def test_unproven_modern_uv_value_metadata_refuses_before_values(authored):
    case = authored
    layer = case.first.values["uv_layers"][0]
    layer.bl_rna.properties["uv"] = case.prop("uv", "COLLECTION", readonly=True, fixed_type=None)
    reads = []
    layer.hazards["uv"] = reads
    assert "value metadata" in refused(case).message
    assert reads == []


def test_uv_active_selector_change_changes_comparison(authored):
    case = authored
    layers = case.first.values["uv_layers"]
    second = copy.deepcopy(layers[0])
    second.values.update(name="Second", active=False)
    layers.append(second)
    before = capture(case)
    layers[0].values["active"] = False
    second.values["active"] = True
    layers.active, layers.active_index = second, 1
    assert capture(case) != before


@pytest.mark.parametrize("flag", ["active_render", "active_clone"])
def test_readonly_layer_roles_are_captured(authored, flag):
    case = authored
    layer = case.first.values["uv_layers"][0]
    layer.bl_rna.properties[flag].is_readonly = True
    before = capture(case)
    layer.values[flag] = not layer.values[flag]
    assert capture(case) != before


def test_uv_active_pointer_must_match_structural_index(authored):
    case = authored
    case.first.values["uv_layers"].active_index = 4
    assert "selector index disagree" in refused(case).message


def test_raw_custom_budget_is_aggregate_and_precedes_generic_projection(authored, monkeypatch):
    case = authored
    second = case.mesh("Second")
    case.first.raw["key"] = "1234"
    second.raw["key"] = "5678"
    monkeypatch.setattr(case.module, "MAX_CUSTOM_COMPONENTS", 13)
    entered = forbid_projection(case, monkeypatch)
    assert "custom_components" in refused(case, meshes=[case.first, second]).message
    assert entered == []


def test_foreign_consumer_data_refuses_before_generic_projection(authored, monkeypatch):
    case = authored
    case.object.values["data"] = case.mesh("Foreign")
    entered = forbid_projection(case, monkeypatch)
    assert "outside the admitted Mesh inventory" in refused(case).message
    assert entered == []


def test_structural_child_identity_churn_is_accepted_only_with_identical_values(authored):
    case = authored
    before = capture(case)
    for name in ("vertices", "edges", "loops", "polygons", "attributes"):
        case.first.values[name] = copy.deepcopy(case.first.values[name])
    layers = case.first.values["uv_layers"]
    layers[0] = copy.deepcopy(layers[0])
    layers.active = layers[0]
    case.first.values["uv_layer_clone"] = case.first.values["uv_layer_stencil"] = layers[0]
    children = [*case.first.values["vertices"], *case.first.values["edges"], *case.first.values["loops"],
                *case.first.values["polygons"], *case.first.values["attributes"], layers[0],
                *layers[0].values["data"]]
    for child in children:
        child.pointer = next(Native.tokens)
    assert capture(case) == before
    assert all(child.pointer_reads == 0 for child in children)
    case.first.values["vertices"][0].values["co"] = (1., 2., 4.)
    assert capture(case) != before


def test_same_content_mesh_replacement_changes_id_binding(authored):
    case = authored
    before = capture(case)
    replacement = case.mesh()
    case.object.values["data"] = replacement
    assert capture(case, meshes=[replacement]) != before


def test_attribute_and_uv_value_edits_are_detected(authored):
    case = authored
    before = capture(case)
    case.first.values["attributes"][0].values["data"][0].values["value"] = .75
    assert capture(case) != before
    before = capture(case)
    case.first.values["uv_layers"][0].values["data"][0].values["uv"] = (.5, .75)
    assert capture(case) != before


def test_native_descriptor_shadowing_refuses(authored):
    case = authored
    vertex = case.first.values["vertices"][0]
    vertex.bl_rna = RNA(**vars(vertex.bl_rna))
    refused(case)


def test_custom_property_changes_are_compared_and_bytes_remain_json_serializable(authored):
    import json

    case = authored
    case.first.raw["metadata"] = {"version": 1, "bytes": b"original"}
    before = capture(case)
    json.dumps(before)
    case.first.raw["metadata"]["version"] = 2
    assert capture(case) != before


def test_custom_id_alias_is_refused_before_generic_projection(authored, monkeypatch):
    case = authored
    case.first.raw["alias"] = case.object
    entered = forbid_projection(case, monkeypatch)
    assert "separate consumer proof" in refused(case).message
    assert entered == []


def test_runtime_readonly_uv_role_never_invokes_getter(authored):
    case = authored
    layer = case.first.values["uv_layers"][0]
    prop = layer.bl_rna.properties["active_render"]
    prop.is_runtime = prop.is_readonly = True
    reads = []
    layer.hazards["active_render"] = reads
    refused(case)
    assert reads == []


def test_runtime_late_consumer_refuses_before_earlier_mesh_generic_values(authored):
    case = authored
    case.object.bl_rna.properties["late"] = case.prop("late", runtime=True)
    reads = []
    case.object.hazards["late"] = reads
    case.first.values["vertices"][0].hazards["co"] = reads
    refused(case)
    assert reads == []


@pytest.mark.parametrize("coordinates", [(1., 2.), (1., 2., 3., 4.), ((1.,), (2.,), (3.,))])
def test_fixed_array_payload_must_match_reserved_scalar_shape(authored, coordinates):
    case = authored
    case.first.values["vertices"][0].values["co"] = coordinates
    refused(case)


def test_enum_flag_sets_are_deterministic(authored):
    case = authored
    case.first.bl_rna.properties["flags"] = case.prop("flags", "ENUM", is_enum_flag=True)
    case.first.values["flags"] = {"Z", "A"}
    before = capture(case)
    case.first.values["flags"] = frozenset({"A", "Z"})
    assert capture(case) == before
    mesh_state = dict(dict(before)["mesh_states"][0][1])
    assert dict(mesh_state["rna"][0])["flags"] == ("A", "Z")


def test_enum_flag_sets_have_a_reserved_aggregate_budget(authored, monkeypatch):
    case = authored
    case.first.bl_rna.properties["flags"] = case.prop("flags", "ENUM", is_enum_flag=True)
    case.first.values["flags"] = {"A"}
    monkeypatch.setattr(case.module, "MAX_COMPONENTS", case.module.MAX_ENUM_FLAGS * case.module.MAX_STRING - 1)
    entered = forbid_projection(case, monkeypatch)
    assert "payload_components" in refused(case).message
    assert entered == []


@pytest.mark.parametrize("field", ["uv_layer_clone", "uv_layer_stencil"])
def test_mesh_uv_pointer_roles_are_structural_and_edits_are_detected(authored, field):
    case = authored
    layers = case.first.values["uv_layers"]
    layers.append(copy.deepcopy(layers[0]))
    before = capture(case)
    case.first.values[field] = layers[1]
    assert capture(case) != before
    assert layers[1].pointer_reads == 0


def test_modern_uv_render_pointer_is_structural(authored):
    case = authored
    layers = case.first.values["uv_layers"]
    wrapper = case.bpy.types.UVLoopLayers.bl_rna
    wrapper.properties["active_render"] = case.prop("active_render", "POINTER")
    layers.active_render = layers[0]
    before = capture(case)
    layers.active_render = None
    assert capture(case) != before
    assert layers[0].pointer_reads == 0


def test_mesh_material_slot_binding_change_is_detected(authored):
    case = authored
    material = Native(case.bpy.types.Material.bl_rna, name="First", session_uid=100)
    case.first.values["materials"] = [material, None]
    before = capture(case)
    case.first.values["materials"][0] = Native(material.bl_rna, name="Second", session_uid=101)
    assert capture(case) != before


@pytest.mark.parametrize("collection,field", [("attributes", "active_index"),
    ("attributes", "active_color_index"), ("color_attributes", "render_color_index"),
    ("color_attributes", "default_color_name")])
def test_attribute_wrapper_selector_changes_are_detected(authored, collection, field):
    case = authored
    before = capture(case)
    setattr(case.first.values[collection], field, "Second" if field.endswith("name") else 1)
    assert capture(case) != before


def test_attribute_wrapper_runtime_selector_refused_before_getter(authored):
    case = authored
    case.bpy.types.AttributeGroupMesh.bl_rna.properties["active"].is_runtime = True
    assert "native descriptor" in refused(case).message


def test_polygon_dynamic_topology_uses_measured_values_instead_of_default_array_width(authored):
    case = authored
    polygon = case.first.values["polygons"][0]
    prop = polygon.bl_rna.properties["vertices"]
    prop.is_readonly = False
    polygon.values["vertices"] = (0, 1, 2, 3)
    before = capture(case)
    polygon.values["vertices"] = (0, 1, 2, 4)
    assert capture(case) != before


@pytest.mark.parametrize("before_value,after_value", [(False, 0), (0, 0.0), (0.0, -0.0),
                                                     (True, 1), (1, 1.0)])
@pytest.mark.parametrize("nested", [False, True])
def test_custom_scalar_type_and_float_sign_changes_are_detected(authored, before_value, after_value, nested):
    case = authored
    def payload(value):
        return {"nested": [value]} if nested else value
    case.first.raw["typed"] = payload(before_value)
    before = capture(case)
    case.first.raw["typed"] = payload(after_value)
    assert capture(case) != before
    case.first.raw["typed"] = payload(before_value)
    assert capture(case) == before
