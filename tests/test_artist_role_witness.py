"""Actual readonly previous-owner witnesses preserve bounded authored content."""

from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError
from types import SimpleNamespace as NS

import pytest
from test_artist_loop import arm, loop, rna_env  # noqa: F401
from test_object_rna_mutation import RNA, Items, Properties, prop


class Native(RNA):
    def __init__(self, **values):
        super().__init__(**values)
        self._custom, self._writes, self._getters, self._reads = {}, [], {}, []

    def __setattr__(self, name, value):
        if not name.startswith("_") and "_writes" in vars(self):
            self._writes.append((name, value))
        super().__setattr__(name, value)

    def __getattribute__(self, name):
        values = super().__getattribute__("__dict__")
        if name in values.get("_getters", {}):
            values["_reads"].append(name)
            return values["_getters"][name]()
        return super().__getattribute__(name)

    def as_pointer(self):
        return id(self)

    def keys(self):
        return self._custom.keys()

    def __getitem__(self, name):
        return self._custom[name]


def native(kind, *, fields=(), **values):
    owner = Native(bl_rna=NS(identifier=kind, properties=Properties((item.identifier, item) for item in fields)),
                   **values)
    owner._writes.clear()
    return owner


def identifier(kind, name, *, fields=(), **values):
    return native(kind, fields=fields, name=name, session_uid=id(values), library=None, override_library=None,
                  is_editable=True, users=1, use_fake_user=False, **values)


class RoleProof:
    def __init__(self):
        self.projections = []

    def check_after_read(self):
        return None

    def object_references(self, references):
        self.projections.append(references)
        return references


@pytest.fixture
def witness_case(loop, addon_package):  # noqa: F811
    case = loop
    module = importlib.import_module(f"{addon_package}.tools._artist_role_witness")
    original = case.protected
    old = Native(**vars(original))
    old.material_slots = []
    old.data = None
    old.delta_location, old.delta_rotation_euler = (0., 0., 0.), (0., 0., 0.)
    old.delta_rotation_quaternion, old.delta_scale = (1., 0., 0., 0.), (1., 1., 1.)
    old.matrix_parent_inverse = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))
    old._custom["artist_note"] = {"label": "preserve", "values": [1, 2., True]}
    old.bl_rna = NS(identifier="Object", properties=Properties(old.bl_rna.properties))
    old.bl_rna.properties["data"] = prop("data", "POINTER")
    old._writes.clear()
    case.bpy.data.objects[case.bpy.data.objects.index(original)] = old
    case.protected = old
    case.obj.material_slots = []
    case.obj.as_pointer = lambda: id(case.obj)
    case.witness_module, case.old, case.role_plan = module, old, RoleProof()
    case.capture = lambda: module.capture(case.bpy, old, case.role_plan)
    return case


def mesh(case):
    vertex = native("MeshVertex", fields=(prop("co"),), co=(0., 0., 0.), groups=[])
    value = native("FloatAttributeValue", fields=(prop("value"),), value=.25)
    attribute = native("FloatAttribute", fields=(prop("name", "STRING"), prop("data", "COLLECTION", readonly=True)),
                       name="artist_weight", domain="POINT", data_type="FLOAT", data=[value])
    data = identifier("Mesh", "ProtectedMesh", fields=(prop("offset"), prop("vertices", "COLLECTION", readonly=True)),
        offset=.1, vertices=[vertex], edges=[], loops=[], polygons=[], attributes=[attribute], materials=[],
        shape_keys=None, animation_data=None)
    case.old.type, case.old.data = "MESH", data
    case.mesh, case.vertex, case.attribute_value = data, vertex, value
    return data


def material(case):
    roughness = native("NodeSocketFloat", fields=(prop("default_value"),),
        identifier="Roughness", name="Roughness", bl_idname="NodeSocketFloat", default_value=.5, is_linked=False)
    shader = native("NodeSocketShader", identifier="BSDF", name="BSDF", bl_idname="NodeSocketShader", is_linked=False)
    surface = native("NodeSocketShader", identifier="Surface", name="Surface", bl_idname="NodeSocketShader", is_linked=False)
    principled = native("ShaderNodeBsdfPrincipled", fields=(prop("name", "STRING"), prop("mute", "BOOLEAN")),
        name="Principled BSDF", bl_idname="ShaderNodeBsdfPrincipled", parent=None, mute=False,
        inputs=[roughness], outputs=[shader])
    output = native("ShaderNodeOutputMaterial", fields=(prop("name", "STRING"),),
        name="Material Output", bl_idname="ShaderNodeOutputMaterial", parent=None, inputs=[surface], outputs=[])
    nodes = Items([principled, output])
    interface = native("NodeTreeInterface", items_tree=[], active=None)
    tree = identifier("ShaderNodeTree", "ProtectedTree", animation_data=None, interface=interface, nodes=nodes, links=[])
    mat = identifier("Material", "ProtectedMaterial", fields=(prop("diffuse_color"), prop("node_tree", "POINTER")),
        diffuse_color=(.1, .2, .3, 1.), animation_data=None, grease_pencil=None, node_tree=tree)
    case.old.material_slots = [NS(link="DATA", material=mat)]
    if case.old.data is not None:
        case.old.data.materials = [mat]
    case.mat, case.tree, case.principled, case.roughness = mat, tree, principled, roughness
    return mat


def test_capture_and_recheck_are_readonly_even_for_a_protected_previous_object(witness_case):
    case = witness_case
    arm(case)
    before = case.module._object_state(case.old, artist_profile=True)
    witness = case.capture()
    witness.check(case.role_plan)
    assert witness.name == "Protected" and witness.identity == case.module.scope.action_token(case.old)
    assert case.old._writes == [] and case.module._object_state(case.old, artist_profile=True) == before
    assert case.role_plan.projections
    with pytest.raises(FrozenInstanceError):
        witness.authored = ()
    affected, _references = case.module._closure(case.bpy, case.obj)
    assert affected == (case.obj,) and case.old not in affected


@pytest.mark.parametrize("field,value", [
    ("location", (3., 2., 1.)), ("scale", (2., 1., 1.)), ("rotation_mode", "QUATERNION"),
    ("rotation_euler", (.1, .2, .3)), ("rotation_quaternion", (.5, .5, .5, .5)),
    ("rotation_axis_angle", (1., 0., 0., 1.)), ("delta_location", (1., 0., 0.)),
    ("delta_rotation_euler", (.1, 0., 0.)), ("delta_rotation_quaternion", (.5, .5, .5, .5)),
    ("delta_scale", (2., 2., 2.)), ("matrix_parent_inverse", ((2., 0., 0., 0.),) * 4),
])
def test_all_previous_transform_channels_reject_manual_edits_without_repair(witness_case, field, value):
    case = witness_case
    witness = case.capture()
    setattr(case.old, field, value)
    case.old._writes.clear()
    with pytest.raises(case.module.BridgeError) as caught:
        witness.check(case.role_plan)
    assert caught.value.context["previous_owner_witness_complete"] is False
    assert getattr(case.old, field) == value and case.old._writes == []


@pytest.mark.parametrize("change", ["nested_custom", "modifier", "constraint", "display"])
def test_previous_authored_components_and_nested_settings_are_preserved(witness_case, change):
    case = witness_case
    component = case.old.modifiers.new()
    constraint = case.old.constraints.new(name="Constraint", type="LIMIT_LOCATION")
    display = native("ObjectDisplay", fields=(prop("show_shadows", "BOOLEAN"),), show_shadows=True)
    case.old.display = display
    case.old.bl_rna.properties["display"] = prop("display", "POINTER", readonly=True)
    witness = case.capture()
    if change == "nested_custom":
        case.old._custom["artist_note"]["values"][1] = 9.
    elif change == "modifier":
        component.width = 2.
    elif change == "constraint":
        constraint.width = 2.
    else:
        display.show_shadows = False
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)


@pytest.mark.parametrize("change", ["rename", "replace", "session_identity", "global_unlink", "scene_unlink", "layer_unlink"])
def test_identity_and_each_membership_are_rechecked(witness_case, change):
    case = witness_case
    witness = case.capture()
    if change == "rename":
        case.old.name = "Renamed manually"
    elif change == "replace":
        case.bpy.data.objects[case.bpy.data.objects.index(case.old)] = Native(**vars(case.old))
    elif change == "session_identity":
        case.old.session_uid += 1
    elif change == "global_unlink":
        case.bpy.data.objects.remove(case.old)
    elif change == "scene_unlink":
        case.bpy.context.scene.objects = Items([case.obj])
    else:
        case.bpy.context.view_layer.objects = Items([case.obj])
    with pytest.raises(case.module.BridgeError) as caught:
        witness.check(case.role_plan)
    assert caught.value.context["previous_owner_witness_complete"] is False


def test_incoming_current_target_is_allowed_without_freezing_its_authored_channels(witness_case):
    case = witness_case
    case.users[case.old] = {case.obj}
    case.obj.user_of_id = lambda owner: int(owner is case.old)
    witness = case.capture()
    case.obj.location = (4., 5., 6.)
    case.obj.rotation_quaternion = (.5, .5, .5, .5)
    witness.check(case.role_plan)
    affected, _references = case.module._closure(case.bpy, case.obj)
    assert affected == (case.obj,) and case.old not in affected
    assert case.old.location == (0., 0., 0.)


@pytest.mark.parametrize("change", ["appearance", "disappearance", "reference_count"])
def test_previous_object_consumer_records_remain_literal(witness_case, change):
    case = witness_case
    if change != "appearance":
        case.users[case.old] = {case.obj}
        case.obj.user_of_id = lambda _owner: 1
    witness = case.capture()
    if change == "appearance":
        case.users[case.old] = {case.obj}
        case.obj.user_of_id = lambda _owner: 1
    elif change == "disappearance":
        case.users[case.old].clear()
    else:
        case.obj.user_of_id = lambda _owner: 2
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)


@pytest.mark.parametrize("owner", ["object", "mesh", "material", "node", "socket"])
def test_nested_custom_native_references_are_refused_at_capture(witness_case, owner):
    case = witness_case
    mesh(case)
    material(case)
    target = {"object": case.old, "mesh": case.mesh, "material": case.mat,
              "node": case.principled, "socket": case.roughness}[owner]
    target._custom["hidden_dependency"] = {"nested": [case.obj]}
    with pytest.raises(case.module.BridgeError):
        case.capture()


@pytest.mark.parametrize("binding", ["object_parent", "empty_data", "geometry_pointer", "material_pointer", "node_image", "node_group", "socket_pointer"])
def test_unreviewed_outbound_bindings_are_refused_instead_of_tokenized(witness_case, binding):
    case = witness_case
    if binding == "empty_data":
        case.old.data = identifier("Curve", "UnsupportedCurve")
    else:
        mesh(case)
        material(case)
        owner, field = {
            "object_parent": (case.old, "parent"),
            "geometry_pointer": (case.mesh, "unsupported_geometry_owner"),
            "material_pointer": (case.mat, "unsupported_material_owner"),
            "node_image": (case.principled, "image"),
            "node_group": (case.principled, "node_tree"),
            "socket_pointer": (case.roughness, "unsupported_socket_owner"),
        }[binding]
        owner.bl_rna.properties[field] = prop(field, "POINTER")
        setattr(owner, field, case.obj)
    with pytest.raises(case.module.BridgeError):
        case.capture()


@pytest.mark.parametrize("change", ["scalar", "vertex", "attribute", "nested_custom", "data_identity"])
def test_static_mesh_authored_data_and_geometry_drift_are_detected(witness_case, change):
    case = witness_case
    mesh(case)
    witness = case.capture()
    if change == "scalar":
        case.mesh.offset = .9
    elif change == "vertex":
        case.vertex.co = (1., 0., 0.)
    elif change == "attribute":
        case.attribute_value.value = .75
    elif change == "nested_custom":
        case.mesh._custom["manual_note"] = {"weight": .75}
    else:
        case.old.data = identifier("Mesh", "ReplacementMesh", **{name: value for name, value in vars(case.mesh).items()
            if name not in {"name", "session_uid", "library", "override_library", "is_editable", "users", "use_fake_user", "bl_rna"}
            and not name.startswith("_")})
        case.old.data.bl_rna = case.mesh.bl_rna
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)


@pytest.mark.parametrize("change", ["roughness", "material_scalar", "material_custom", "tree_custom", "node_scalar", "tree_identity", "material_binding"])
def test_static_principled_material_content_and_bindings_remain_visible(witness_case, change):
    case = witness_case
    mesh(case)
    material(case)
    witness = case.capture()
    witness.check(case.role_plan)
    if change == "roughness":
        case.roughness.default_value = .9
    elif change == "material_scalar":
        case.mat.diffuse_color = (.9, .2, .3, 1.)
    elif change == "material_custom":
        case.mat._custom["manual_value"] = .75
    elif change == "tree_custom":
        case.tree._custom["manual_value"] = .75
    elif change == "node_scalar":
        case.principled.mute = True
    elif change == "tree_identity":
        case.mat.node_tree = Native(**vars(case.tree))
    else:
        case.old.material_slots[0].material = None
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)


def test_runtime_material_descriptor_is_refused_before_its_getter(witness_case):
    case = witness_case
    material(case)
    descriptor = prop("hostile_runtime")
    descriptor.is_runtime = True
    case.mat.bl_rna.properties["hostile_runtime"] = descriptor
    case.mat._getters["hostile_runtime"] = lambda: pytest.fail("Runtime material getter was read")
    with pytest.raises(case.module.BridgeError) as caught:
        case.capture()
    assert caught.value.context["artist_scope_profile_complete"] is False
    assert case.mat._reads == []


@pytest.mark.parametrize("owner", ["material", "tree", "node", "socket", "interface"])
def test_reserved_custom_marker_is_literal_in_every_material_child(witness_case, owner):
    case = witness_case
    material(case)
    target = {"material": case.mat, "tree": case.tree, "node": case.principled,
              "socket": case.roughness, "interface": case.tree.interface}[owner]
    target._custom["_codex_bridge_undo_marker"] = "old artist-authored value"
    before, _identifiers = case.witness_module._material(case.bpy, case.mat)
    witness = case.capture()
    target._custom["_codex_bridge_undo_marker"] = "new manual value"
    after, _identifiers = case.witness_module._material(case.bpy, case.mat)
    assert before != after
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)
    assert target._custom["_codex_bridge_undo_marker"] == "new manual value"


def light_linking(case):
    child = native("ObjectLightLinking", fields=(prop("receiver_collection", "POINTER"),
        prop("blocker_collection", "POINTER")), receiver_collection=None, blocker_collection=None)
    case.old.bl_rna.properties["light_linking"] = prop("light_linking", "POINTER", readonly=True)
    case.old.light_linking = child
    return child


@pytest.mark.parametrize("field", ["receiver_collection", "blocker_collection"])
@pytest.mark.parametrize("when", ["capture", "recheck"])
def test_light_linking_outbound_collections_are_refused_before_or_after_capture(witness_case, field, when):
    case = witness_case
    child = light_linking(case)
    witness = case.capture() if when == "recheck" else None
    collection = identifier("Collection", "UnsupportedLightCollection")
    setattr(child, field, collection)
    child._writes.clear()
    with pytest.raises(case.module.BridgeError) as caught:
        case.capture() if witness is None else witness.check(case.role_plan)
    assert caught.value.context["previous_owner_witness_complete"] is False
    assert getattr(child, field) is collection and child._writes == []


def test_equal_light_linking_values_do_not_hide_child_identity_replacement(witness_case):
    case = witness_case
    original = light_linking(case)
    witness = case.capture()
    replacement = native("ObjectLightLinking", fields=tuple(original.bl_rna.properties),
                         receiver_collection=None, blocker_collection=None)
    assert case.module.scope.rna_state(original) == case.module.scope.rna_state(replacement)
    case.old.light_linking = replacement
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)


@pytest.mark.parametrize("owner", ["object", "mesh", "material", "tree"])
def test_asset_metadata_requires_a_separate_witness(witness_case, owner):
    case = witness_case
    mesh(case)
    material(case)
    target = {"object": case.old, "mesh": case.mesh, "material": case.mat, "tree": case.tree}[owner]
    target.bl_rna.properties["asset_data"] = prop("asset_data", "POINTER", readonly=True)
    target.asset_data = native("AssetMetaData")
    with pytest.raises(case.module.BridgeError, match="asset metadata"):
        case.capture()


@pytest.mark.parametrize("change", ["active_uv", "clone_uv", "render_uv", "active_color", "render_color", "active_vertex_group"])
def test_mesh_layer_and_vertex_group_roles_remain_literal(witness_case, change):
    case = witness_case
    mesh(case)
    layer = native("MeshUVLoopLayer", fields=(prop("name", "STRING"), prop("active", "BOOLEAN"),
        prop("active_clone", "BOOLEAN"), prop("active_render", "BOOLEAN")),
        name="ProtectedUV", active=True, active_clone=True, active_render=True)
    case.mesh.bl_rna.properties["uv_layers"] = prop("uv_layers", "COLLECTION", readonly=True)
    case.mesh.bl_rna.properties["color_attributes"] = prop("color_attributes", "COLLECTION", readonly=True)
    case.mesh.uv_layers = Items([layer])
    case.mesh.uv_layers.active_index = 0
    case.mesh.color_attributes = Items()
    case.mesh.color_attributes.active_color_index = case.mesh.color_attributes.render_color_index = -1
    case.old.vertex_groups = Items()
    case.old.vertex_groups.active_index = -1
    witness = case.capture()
    if change == "active_uv":
        case.mesh.uv_layers.active_index = 1
    elif change == "clone_uv":
        layer.active_clone = False
    elif change == "render_uv":
        layer.active_render = False
    elif change == "active_color":
        case.mesh.color_attributes.active_color_index = 0
    elif change == "render_color":
        case.mesh.color_attributes.render_color_index = 0
    else:
        case.old.vertex_groups.active_index = 0
    with pytest.raises(case.module.BridgeError):
        witness.check(case.role_plan)
