from __future__ import annotations

import asyncio
import copy
import importlib
import math
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError
from test_mesh_slide import (
    Item,
    Layers,
    change_global_uv_flag,
    enable_global_uv_flags,
    global_uv_flags,
    grid,
)

from mcp_server.tools.mesh_surface import MeshSurfaceTools, load_definitions

IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))


class Sequence(list):
    def __init__(self, values, layers=None):
        super().__init__(values)
        self.layers = layers or NS()

    def ensure_lookup_table(self):
        pass

    def index_update(self):
        for index, value in enumerate(self):
            value.index = index


class LayerItem(Item):
    def __getitem__(self, layer):
        return self.values[layer.name]


class Object(NS):
    __hash__ = object.__hash__

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other


def mesh_grid(height=0.):
    bm, _edges = grid()
    vertex_layers = NS(**{family: Layers({name: NS(name=name)}) for family, name in (
        ("float", "Temperature"), ("deform", "Weights"), ("float_color", "Paint"))})
    bm.verts = Sequence(bm.verts, vertex_layers)
    bm.edges, bm.faces = Sequence(bm.edges), Sequence(bm.faces)
    bm.is_valid = True
    for vertex in bm.verts:
        vertex.__class__ = LayerItem
        vertex.co = (*vertex.co[:2], height)
        vertex.values = {"Temperature": vertex.index*.125, "Weights": {0: .25, 1: .75},
                         "Paint": (.1, .2, .3, 1.)}
    for face in bm.faces:
        for loop in face.loops:
            loop.face = face
    return bm


def mesh_object(name, bm, *, target):
    mesh = NS(users=1, shape_keys=None, has_custom_normals=False, is_editmode=target,
        materials=[NS(name="Protected Material")], polygons=bm.faces, native=bm,
        attributes=[NS(name=name, domain="POINT", data_type=kind) for name, kind in (
            ("Temperature", "FLOAT"), ("Paint", "FLOAT_COLOR"))],
        uv_layers=Sequence([NS(name="UV", active_render=True), NS(name="Spare", active_render=False)]),
        color_attributes=NS(active_color_index=0, render_color_index=0))
    mesh.uv_layers.active_index = 1
    return Object(name=name, type="MESH", mode="EDIT" if target else "OBJECT", data=mesh,
        matrix_world=IDENTITY, modifiers=[], hide_viewport=False, hide_get=lambda: False,
        vertex_groups=[NS(name="Protected", index=0, lock_weight=True), NS(name="Paint", index=1, lock_weight=False)],
        material_slots=[NS(material=mesh.materials[0], link="DATA")], is_editable=True)


@pytest.fixture
def surface(addon_package, monkeypatch):
    module = importlib.import_module(addon_package + ".tools.mesh_surface")
    bm, source_bm = mesh_grid(), mesh_grid(.25)
    obj, source = mesh_object("Patch", bm, target=True), mesh_object("Reference", source_bm, target=False)
    objects = {obj.name: obj, source.name: source}
    view_layer = NS(objects=NS(get=objects.get, active=obj), update=lambda: None)
    root = Object(name="Scene Collection", children=[], users=0, use_fake_user=False,
        objects=NS(get=objects.get), user_of_id=lambda _: 1)
    scene = Object(name="Scene", collection=root, view_layers=[view_layer], user_of_id=lambda _: 3)
    obj.users_scene, obj.users_collection = [scene], [root]
    source.users_scene, source.users_collection = [scene], [root]
    consumers = {root, scene}
    bpy = NS(data=NS(objects=NS(get=objects.get), filepath="", user_map=lambda **_: {obj: consumers}),
        context=NS(scene=scene, view_layer=view_layer, mode="EDIT_MESH", edit_object=obj, selected_objects=[obj]))
    reference = {"vertices": [4], "edges": [], "faces": []}
    monkeypatch.setattr(module, "_active_edit_mesh", lambda _: (bpy, objects[obj.name], bm, {}))
    monkeypatch.setattr(module, "validate_selection_reference", lambda *_: reference)

    class Temporary:
        def from_mesh(self, mesh):
            self.verts, self.edges, self.faces, self.loops = (
                mesh.native.verts, mesh.native.edges, mesh.native.faces, mesh.native.loops)
            if hasattr(mesh.native, "uv_select_sync_valid"):
                self.uv_select_sync_valid = mesh.native.uv_select_sync_valid

        def calc_loop_triangles(self):
            return [(face.loops[0], face.loops[index], face.loops[index+1])
                for face in self.faces for index in range(1, len(face.loops)-1)]

        def free(self):
            pass

    calls, flags, grants = [], {"paused": False, "emergency_stopped": False}, {"INSPECT_SCENE": True, "EDIT_MESH": True}
    backend = NS(new=Temporary, update_edit_mesh=lambda *a, **kw: calls.append(kw))
    monkeypatch.setattr(module, "bmesh", backend)
    def require(*permissions):
        if any(not grants[permission.value] for permission in permissions):
            raise module.BridgeError("PERMISSION_DENIED", "denied")
    context = NS(require=require, check_cancelled=None, state=NS(snapshot=lambda: dict(flags)))
    return NS(module=module, bm=bm, source_bm=source_bm, obj=obj, source=source, objects=objects,
        bpy=bpy, root=root, consumers=consumers, reference=reference, calls=calls, flags=flags, grants=grants, context=context)


def arguments(**updates):
    return {"object_name": "Patch", "selection_id": "fresh", "source_object": "Reference",
        "source_polygon_indices": [0, 1, 2, 3], "max_distance": .3, **updates}


def preview(env, **updates):
    return env.module.surface_projection_preview(env.context, arguments(**updates))


def apply(env, **updates):
    params = arguments(**updates)
    proof = env.module.surface_projection_preview(env.context, params)
    return env.module.project_to_surface(env.context, {**params, "expected_fingerprint": proof["fingerprint"]})


def test_projection_measures_native_output_and_preserves_protected_mesh_data(surface):
    env = surface
    before, source_before = env.module._capture(env.obj, env.bm), env.module._capture(env.source, env.source_bm)
    result = apply(env)
    assert env.bm.verts[4].co == (1., 1., .25)
    after = env.module._capture(env.obj, env.bm)
    assert after["custom_data"] == before["custom_data"]
    assert after["metadata"] == before["metadata"]
    assert all(vertex == before["base"]["vertices"][index] for index, vertex in enumerate(after["base"]["vertices"]) if index != 4)
    assert env.module._capture(env.source, env.source_bm) == source_before
    assert result["maximum_distance_before_world"] == .25 and result["maximum_distance_after_world"] == 0.
    assert result["supported_custom_data_preserved"] and result["source_preserved"]
    assert env.calls == [{"loop_triangles": False, "destructive": False}]


def test_preview_is_read_only_with_inspection_permission(surface):
    env = surface
    env.grants["EDIT_MESH"] = False
    before = env.module._capture(env.obj, env.bm)
    result = preview(env)
    assert not result["changed"] and len(result["fingerprint"]) == 64
    assert result["candidate_fan_contacts"]["complete"]
    assert env.module._capture(env.obj, env.bm) == before and not env.calls


@pytest.mark.parametrize("owner", ["target", "source"])
@pytest.mark.parametrize("channel", ["sync", "face", "vertex", "edge"])
def test_actual_global_uv_flag_change_invalidates_projection_preview(surface, owner, channel):
    env = surface
    enable_global_uv_flags(env.bm)
    enable_global_uv_flags(env.source_bm)
    proof = preview(env)
    change_global_uv_flag(env.bm if owner == "target" else env.source_bm, channel)
    with pytest.raises(env.module.BridgeError, match="fingerprint"):
        env.module.project_to_surface(env.context, {**arguments(), "expected_fingerprint": proof["fingerprint"]})
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


@pytest.mark.parametrize("owner", ["target", "source"])
@pytest.mark.parametrize("channel", ["sync", "face", "vertex", "edge"])
def test_callback_global_uv_flag_change_blocks_projection_before_write(surface, monkeypatch, owner, channel):
    env = surface
    enable_global_uv_flags(env.bm)
    enable_global_uv_flags(env.source_bm)
    original = env.module._candidate_checks
    def checked(*args, **kwargs):
        result = original(*args, **kwargs)
        change_global_uv_flag(env.bm if owner == "target" else env.source_bm, channel)
        return result
    monkeypatch.setattr(env.module, "_candidate_checks", checked)
    with pytest.raises(env.module.BridgeError, match="changed during preview"):
        apply(env)
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


@pytest.mark.parametrize("owner", ["target", "source"])
def test_projection_recovery_refuses_to_overwrite_external_global_uv_flags(surface, monkeypatch, owner):
    env = surface
    enable_global_uv_flags(env.bm)
    enable_global_uv_flags(env.source_bm)
    target = env.bm if owner == "target" else env.source_bm
    original_flags = global_uv_flags(target)
    def update(*args, **kwargs):
        env.calls.append(kwargs)
        change_global_uv_flag(target, "edge")
    monkeypatch.setattr(env.module.bmesh, "update_edit_mesh", update)
    with pytest.raises(env.module.BridgeError) as caught:
        apply(env)
    assert caught.value.context["execution_started"] and not caught.value.context["rollback_verified"]
    assert caught.value.context["possible_mutation"] and len(env.calls) == 1
    assert global_uv_flags(target) != original_flags and env.bm.verts[4].co == (1., 1., .25)


@pytest.mark.parametrize("failure", [False, True])
def test_projection_and_owned_fault_recovery_preserve_actual_global_uv_flags(surface, monkeypatch, failure):
    env = surface
    enable_global_uv_flags(env.bm)
    enable_global_uv_flags(env.source_bm)
    before = global_uv_flags(env.bm), global_uv_flags(env.source_bm)
    if failure:
        def update(*args, **kwargs):
            env.calls.append(kwargs)
            if len(env.calls) == 1:
                raise RuntimeError("native projection update failure")
        monkeypatch.setattr(env.module.bmesh, "update_edit_mesh", update)
        with pytest.raises(env.module.BridgeError) as caught:
            apply(env)
        assert caught.value.context["rollback_verified"] and env.bm.verts[4].co == (1., 1., 0.)
    else:
        assert apply(env)["source_preserved"]
    assert (global_uv_flags(env.bm), global_uv_flags(env.source_bm)) == before


@pytest.mark.parametrize("name, domain", [(".uv_select_vert", "CORNER"), (".uv_select_edge", "CORNER"), (".uv_select_face", "FACE")])
def test_global_uv_attribute_requires_actual_global_flag_proof(surface, name, domain):
    env = surface
    env.obj.data.attributes.append(NS(name=name, domain=domain, data_type="BOOLEAN"))
    with pytest.raises(env.module.BridgeError, match="actual native BMesh flag proof"):
        apply(env)
    assert not env.calls
    enable_global_uv_flags(env.bm)
    assert apply(env)["supported_custom_data_preserved"]


@pytest.mark.parametrize("polygons", [None, [], [True], [-1], [4], [0, 0], "0", list(range(257))])
def test_invalid_explicit_source_scope_is_rejected_before_write(surface, polygons):
    with pytest.raises(surface.module.BridgeError):
        apply(surface, source_polygon_indices=polygons)
    assert not surface.calls and surface.bm.verts[4].co == (1., 1., 0.)


@pytest.mark.parametrize("change", ["shared", "shape_keys", "custom_normals", "modifier", "hidden", "source_edit", "source_alias", "hidden_polygon", "unsupported_attribute"])
def test_unreviewed_source_target_or_protected_data_is_refused(surface, change):
    env = surface
    if change == "shared":
        env.obj.data.users = 2
    elif change in {"shape_keys", "custom_normals"}:
        setattr(env.obj.data, "shape_keys" if change == "shape_keys" else "has_custom_normals", True)
    elif change == "modifier":
        env.source.modifiers.append(NS())
    elif change == "hidden":
        env.obj.hide_viewport = True
    elif change == "source_edit":
        env.source.mode = "EDIT"
    elif change == "source_alias":
        env.source.data.is_editmode = True
    elif change == "hidden_polygon":
        env.source_bm.faces[0].hide = True
    else:
        env.obj.data.attributes.append(NS(name="Protected Bool", domain="POINT", data_type="BOOLEAN"))
    with pytest.raises(env.module.BridgeError):
        apply(env)
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


def test_existing_uv_boolean_flags_are_captured_and_preserved(surface):
    env = surface
    for obj in (env.obj, env.source):
        obj.data.attributes.extend(NS(name=f".{prefix}.UV", domain="CORNER", data_type="BOOLEAN")
            for prefix in ("vs", "es", "pn"))
    layer = env.bm.loops.layers.uv["UV"]
    corner = env.bm.faces[0].loops[0][layer]
    corner.pin_uv, corner.select, corner.select_edge = True, False, True
    before = env.module._capture(env.obj, env.bm)
    captured = next(row for row in before["custom_data"] if row[:3] == ("CORNER", "uv", "UV"))
    assert captured[4][0] == ((0., 0.), True, False, True)
    assert apply(env)["supported_custom_data_preserved"]
    assert env.module._capture(env.obj, env.bm)["custom_data"] == before["custom_data"]


@pytest.mark.parametrize("name, domain, kind", [(".vs.UV", "POINT", "FLOAT"),
    (".pn.UV", "CORNER", "FLOAT"), (".es.Missing", "CORNER", "BOOLEAN"),
    ("Protected Bool", "CORNER", "BOOLEAN")])
def test_uv_flag_allowance_refuses_spoofed_domain_type_or_layer(surface, name, domain, kind):
    env = surface
    env.obj.data.attributes.append(NS(name=name, domain=domain, data_type=kind))
    with pytest.raises(env.module.BridgeError):
        apply(env)
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


def test_accepted_attribute_type_requires_actual_native_layer_value_proof(surface):
    env = surface
    env.obj.data.attributes.append(NS(name="Uncaptured Float2", domain="CORNER", data_type="FLOAT2"))
    with pytest.raises(env.module.BridgeError, match="native custom-layer proof"):
        apply(env)
    assert not env.calls


def test_uv_boolean_flag_requires_native_uv_layer_for_value_proof(surface):
    env = surface
    env.obj.data.attributes.append(NS(name=".pn.UV", domain="CORNER", data_type="BOOLEAN"))
    del env.bm.loops.layers.uv["UV"]
    with pytest.raises(env.module.BridgeError, match="native custom-layer proof"):
        apply(env)
    assert not env.calls


@pytest.mark.parametrize("name, domain, kind", [("sharp_edge", "CORNER", "FLOAT"),
    (".select_vert", "POINT", "INT"), ("position", "POINT", "FLOAT")])
def test_builtin_attribute_names_require_exact_native_domain_and_type(surface, name, domain, kind):
    env = surface
    env.obj.data.attributes.append(NS(name=name, domain=domain, data_type=kind))
    with pytest.raises(env.module.BridgeError, match="Builtin mesh attribute domain/type"):
        apply(env)
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


def test_shared_reference_is_read_only_and_source_target_alias_is_rejected(surface):
    env = surface
    env.source.data.users = 2
    assert apply(env)["source_preserved"]
    env.source.data = env.obj.data
    with pytest.raises(env.module.BridgeError):
        preview(env)


@pytest.mark.parametrize("hidden", ["face", "edge", "neighbor"])
def test_projection_refuses_hidden_affected_fan_geometry(surface, hidden):
    env = surface
    if hidden == "face":
        env.bm.faces[0].hide = True
    elif hidden == "edge":
        env.bm.verts[4].link_edges[0].hide = True
    else:
        env.bm.verts[0].hide = True
    with pytest.raises(env.module.BridgeError):
        apply(env)
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


@pytest.mark.parametrize("hidden", ["face", "edge", "neighbor"])
def test_native_refresh_revalidates_affected_visibility(surface, hidden):
    env = surface
    def update():
        if hidden == "face":
            env.bm.faces[0].hide = True
        elif hidden == "edge":
            env.bm.verts[4].link_edges[0].hide = True
        else:
            env.bm.verts[0].hide = True
    env.bpy.context.view_layer.update = update
    with pytest.raises(env.module.BridgeError):
        apply(env)
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


def test_projection_requires_selected_vertices_to_belong_to_a_surface(surface):
    env = surface
    env.bm.verts[4].link_faces = []
    with pytest.raises(env.module.BridgeError, match="surface"):
        apply(env)
    assert not env.calls


@pytest.mark.parametrize("scope", ["scene", "instanced_collection", "incoming_consumer", "extra_collection_reference"])
def test_projection_rejects_effects_beyond_current_ordinary_membership(surface, scope):
    env = surface
    if scope == "scene":
        env.obj.users_scene.append(Object(name="Protected Scene"))
    elif scope == "instanced_collection":
        env.root.users = 2
    elif scope == "incoming_consumer":
        env.consumers.add(Object(name="Protected Incoming Consumer"))
    else:
        env.root.user_of_id = lambda _: 2
    with pytest.raises(env.module.BridgeError):
        apply(env)
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


def test_exact_native_root_base_and_edit_scene_membership_is_accepted(surface):
    env = surface
    assert env.bpy.context.scene.user_of_id(env.obj) == 3
    assert env.bpy.context.edit_object is env.obj
    env.module._target_scope(env.bpy, env.obj)
    assert apply(env)["source_preserved"]


@pytest.mark.parametrize("scope", ["extra_scene_reference", "missing_edit_object", "wrong_edit_object", "missing_scene_user", "object_mode_count"])
def test_incoming_scope_requires_exact_native_edit_object_proof(surface, scope):
    env = surface
    if scope == "extra_scene_reference":
        env.bpy.context.scene.user_of_id = lambda _: 4
    elif scope == "missing_edit_object":
        del env.bpy.context.edit_object
    elif scope == "wrong_edit_object":
        env.bpy.context.edit_object = env.source
    elif scope == "missing_scene_user":
        env.consumers.remove(env.bpy.context.scene)
    else:
        env.bpy.context.scene.user_of_id = lambda _: 2
    with pytest.raises(env.module.BridgeError, match="incoming consumers"):
        apply(env)
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


@pytest.mark.parametrize("scope", ["scene", "consumer"])
def test_recovery_refuses_new_external_scope_after_native_write(surface, monkeypatch, scope):
    env = surface
    def update(*args, **kwargs):
        env.calls.append(kwargs)
        if scope == "scene":
            env.obj.users_scene.append(Object(name="Protected Scene"))
        else:
            env.consumers.add(Object(name="Protected Consumer"))
    monkeypatch.setattr(env.module.bmesh, "update_edit_mesh", update)
    with pytest.raises(env.module.BridgeError) as caught:
        apply(env)
    assert caught.value.context["execution_started"] and caught.value.context["possible_mutation"]
    assert not caught.value.context["rollback_verified"] and env.bm.verts[4].co == (1., 1., .25)
    assert len(env.calls) == 1


@pytest.mark.parametrize("mutation", ["consumer", "scene", "context", "source"])
def test_recovery_native_refresh_cannot_certify_changed_session_or_source(surface, monkeypatch, mutation):
    env = surface
    def update(*args, **kwargs):
        env.calls.append(kwargs)
        if len(env.calls) == 1:
            raise RuntimeError("native update fault")
        if mutation == "consumer":
            env.consumers.add(Object(name="Protected Consumer"))
        elif mutation == "scene":
            env.obj.users_scene.append(Object(name="Protected Scene"))
        elif mutation == "context":
            env.bpy.context.view_layer.objects.active = env.source
        else:
            env.objects[env.source.name] = copy.copy(env.source)
    monkeypatch.setattr(env.module.bmesh, "update_edit_mesh", update)
    with pytest.raises(env.module.BridgeError) as caught:
        apply(env)
    assert len(env.calls) == 2 and caught.value.context["execution_started"]
    assert not caught.value.context["rollback_verified"] and caught.value.context["possible_mutation"]


def test_repeated_full_proof_budget_is_checked_before_any_projection_write(surface, monkeypatch):
    env = surface
    before = env.module._capture(env.obj, env.bm)
    source = env.module._capture(env.source, env.source_bm)
    size = env.module._proof_size(before) + env.module._proof_size(source)
    monkeypatch.setattr(env.module, "MAX_REVALIDATION_VALUES", 5*size-1)
    with pytest.raises(env.module.BridgeError, match="Repeated live preservation"):
        apply(env)
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


def test_deform_influences_consume_custom_data_and_repeat_proof_budgets(surface, monkeypatch):
    env = surface
    before = env.module._capture(env.obj, env.bm)
    base_size = env.module._proof_size(before)
    env.bm.verts[4].values["Weights"] = {index: .01 for index in range(20)}
    larger = env.module._capture(env.obj, env.bm)
    assert env.module._proof_size(larger) == base_size + 18
    monkeypatch.setattr(env.module, "MAX_ATTRIBUTE_VALUES", 30)
    with pytest.raises(env.module.BridgeError, match="deform"):
        env.module._layers(env.bm)


@pytest.mark.parametrize("mutation", ["source_coordinate", "source_mesh", "target_mesh", "source_matrix", "custom_data", "material"])
def test_changed_frozen_input_invalidates_preview(surface, mutation):
    env = surface
    proof = preview(env)
    if mutation == "source_coordinate":
        env.source_bm.verts[0].co = (0., 0., .3)
    elif mutation == "source_mesh":
        env.source.data = copy.copy(env.source.data)
    elif mutation == "target_mesh":
        env.obj.data = copy.copy(env.obj.data)
    elif mutation == "source_matrix":
        env.source.matrix_world = (*IDENTITY[:2], (0., 0., 1., .01), IDENTITY[3])
    elif mutation == "custom_data":
        env.bm.verts[0].values["Weights"] = {0: .5, 1: .5}
    else:
        env.obj.data.materials[0] = NS(name="Protected Material")
    with pytest.raises(env.module.BridgeError, match="fingerprint"):
        env.module.project_to_surface(env.context, {**arguments(), "expected_fingerprint": proof["fingerprint"]})
    assert not env.calls


@pytest.mark.parametrize("mutation", ["shared", "target_mesh", "source_mesh", "source_matrix", "source_replaced", "middle_handle"])
def test_callback_scope_attacks_are_detected_before_first_write(surface, mutation):
    env = surface
    proof = preview(env)
    original = env.module._candidate_checks
    def intercepted(*args, **kwargs):
        result = original(*args, **kwargs)
        if mutation == "shared":
            env.obj.data.users = 2
        elif mutation == "target_mesh":
            env.obj.data = copy.copy(env.obj.data)
        elif mutation == "source_mesh":
            env.source.data = copy.copy(env.source.data)
        elif mutation == "source_matrix":
            env.source.matrix_world = (*IDENTITY[:2], (0., 0., 1., .01), IDENTITY[3])
        elif mutation == "source_replaced":
            env.objects["Reference"] = copy.copy(env.source)
        else:
            env.bm.verts[4] = copy.copy(env.bm.verts[4])
        return result
    env.module._candidate_checks = intercepted
    try:
        with pytest.raises(env.module.BridgeError):
            env.module.project_to_surface(env.context, {**arguments(), "expected_fingerprint": proof["fingerprint"]})
    finally:
        env.module._candidate_checks = original
    assert not env.calls and env.bm.verts[4].co == (1., 1., 0.)


@pytest.mark.parametrize("failure", ["update", "cancel", "pause", "permission", "shared", "target_mesh", "source_mesh", "replaced_output", "protected_attribute"])
def test_postwrite_failure_reports_owned_recovery_truthfully(surface, monkeypatch, failure):
    env = surface
    def update(*args, **kwargs):
        env.calls.append(kwargs)
        if len(env.calls) != 1:
            return
        if failure == "update":
            raise RuntimeError("native update failed")
        if failure == "cancel":
            def cancelled():
                raise env.module.BridgeError("TIMEOUT", "cancelled")
            env.context.check_cancelled = cancelled
        elif failure == "pause":
            env.flags["paused"] = True
        elif failure == "permission":
            env.grants["EDIT_MESH"] = False
        elif failure == "shared":
            env.obj.data.users = 2
        elif failure == "target_mesh":
            env.obj.data = copy.copy(env.obj.data)
        elif failure == "source_mesh":
            env.source.data = copy.copy(env.source.data)
        elif failure == "replaced_output":
            env.bm.verts[4].co = (1., 1., .2)
        else:
            env.bm.verts[0].values["Paint"] = (.9, .1, .3, 1.)
    monkeypatch.setattr(env.module.bmesh, "update_edit_mesh", update)
    with pytest.raises(env.module.BridgeError) as caught:
        apply(env)
    error = caught.value.context
    restored = failure in {"update", "cancel", "pause"}
    assert error["execution_started"] and error["rollback_verified"] == restored
    assert error["possible_mutation"] != restored
    assert env.bm.verts[4].co == ((1., 1., 0.) if restored else (1., 1., .2 if failure == "replaced_output" else .25))


def test_partial_native_setter_records_attempt_and_refuses_unowned_result(surface):
    env = surface
    vertex = env.bm.verts[4]
    class Partial(LayerItem):
        @property
        def co(self):
            return self._co
        @co.setter
        def co(self, value):
            self._co = (value[0], 42., value[2])
            raise RuntimeError("partial native assignment")
    vertex._co = vertex.__dict__.pop("co")
    vertex.__class__ = Partial
    with pytest.raises(env.module.BridgeError) as caught:
        apply(env)
    assert caught.value.context["execution_started"] and caught.value.context["possible_mutation"]
    assert not caught.value.context["rollback_verified"]


def test_setter_that_writes_the_owned_output_then_raises_can_be_recovered(surface):
    env = surface
    vertex = env.bm.verts[4]
    class Partial(LayerItem):
        @property
        def co(self):
            return self._co
        @co.setter
        def co(self, value):
            self._co = value
            if value[2]:
                raise RuntimeError("native assignment reported failure after write")
    vertex._co = vertex.__dict__.pop("co")
    vertex.__class__ = Partial
    with pytest.raises(env.module.BridgeError) as caught:
        apply(env)
    assert caught.value.context["execution_started"] and caught.value.context["rollback_verified"]
    assert not caught.value.context["possible_mutation"] and vertex.co == (1., 1., 0.)


@pytest.mark.parametrize("scale, translation", [(2., -1.), (-2., 3.)])
def test_distance_bound_and_native_float32_rounding_are_measured_in_world_space(surface, scale, translation):
    env = surface
    with pytest.raises(env.module.BridgeError, match="max_distance"):
        preview(env, max_distance=.2)
    env.obj.matrix_world = ((scale, 0., 0., translation), (0., .5, 0., .5), (0., 0., 3., 0.), IDENTITY[3])
    result = apply(env)
    assert result["items"][0]["after_local"][2] != 1./12.
    assert math.dist((1., 1., .25), env.module.transform(env.obj.matrix_world, env.bm.verts[4].co)) <= 1e-6
    assert result["maximum_distance_after_world"] <= 1e-6


def test_singular_transform_is_rejected_before_write(surface):
    env = surface
    env.obj.matrix_world = (IDENTITY[0], IDENTITY[1], (0., 0., 0., 0.), IDENTITY[3])
    with pytest.raises(env.module.BridgeError, match="invertible"):
        apply(env)
    assert not env.calls


def test_native_rounding_that_misses_surface_tolerance_is_refused(surface):
    env = surface
    env.obj.matrix_world = ((1e6, 0., 0., -999999.), IDENTITY[1], IDENTITY[2], IDENTITY[3])
    for vertex in env.source_bm.verts:
        vertex.co = (*vertex.co[:2], .25+.5*vertex.co[0])
    with pytest.raises(env.module.BridgeError, match="float32"):
        preview(env, max_distance=1.)
    assert not env.calls


@pytest.mark.parametrize("incomplete", ["budget", "precision", "contact"])
def test_incomplete_or_contact_candidate_checks_refuse_publication(surface, monkeypatch, incomplete):
    env = surface
    result = {"complete": incomplete == "contact", "triangle_pairs": {"crossing": int(incomplete == "contact")},
        "pair_budget_exhausted": incomplete == "budget", "precision_limited_triangles": int(incomplete == "precision")}
    monkeypatch.setattr(env.module, "intersection_analysis", lambda *a, **kw: result)
    with pytest.raises(env.module.BridgeError, match="contact"):
        apply(env)
    assert not env.calls


def test_projection_rejects_a_degenerate_or_inverted_target_fan(surface):
    env = surface
    with pytest.raises(env.module.BridgeError, match=r"degenerate|invert"):
        env.module._candidate_checks(env.bm, {4: (3., 1., 0.)}, IDENTITY, env.context)


def test_candidate_contact_checks_detect_new_overlap_of_disconnected_faces(surface):
    env = surface
    vertices = [Item(index=9+index, co=(*point, .5)) for index, point in enumerate(((.25, .25), (.75, .25), (.25, .75)))]
    env.bm.verts.extend(vertices)
    env.bm.faces.append(Item(index=4, verts=vertices))
    clean = env.module._candidate_checks(env.bm, {}, IDENTITY, env.context)
    assert clean["complete"] and not any(clean["triangle_pairs"].values())
    with pytest.raises(env.module.BridgeError, match="contacts") as caught:
        env.module._candidate_checks(env.bm, {vertex.index: (*vertex.co[:2], 0.) for vertex in vertices}, IDENTITY, env.context)
    assert caught.value.context["contacts"]["triangle_pairs"]["coplanar_overlap"]


def test_nearest_ties_require_same_output_and_choose_deterministic_source(surface):
    nearest = surface.module._nearest
    triangle = ((0., 0., 0.), (2., 0., 0.), (0., 2., 0.))
    distance, polygon, _vertices, point, bary = nearest((.25, .25, 1.), [
        (4, (3, 4, 5), triangle), (2, (0, 1, 2), triangle)])
    assert polygon == 2 and distance == 1. and point == (.25, .25, 0.)
    assert sum(bary) == pytest.approx(1.)
    with pytest.raises(surface.module.BridgeError, match="ambiguous"):
        nearest((.25, .25, 0.), [(0, (0, 1, 2), tuple((x, y, -.5) for x, y, _ in triangle)),
            (1, (3, 4, 5), tuple((x, y, .5) for x, y, _ in triangle))])


@pytest.mark.parametrize("point, expected, weights", [
    ((.25, .25, 1.), (.25, .25, 0.), (.5, .25, .25)),
    ((-1., -1., 0.), (0., 0., 0.), (1., 0., 0.)),
    ((2., 0., 0.), (1., 0., 0.), (0., 1., 0.)),
    ((0., 2., 0.), (0., 1., 0.), (0., 0., 1.)),
    ((.5, -.5, 0.), (.5, 0., 0.), (.5, .5, 0.)),
    ((.75, .75, 0.), (.5, .5, 0.), (0., .5, .5)),
    ((-.5, .5, 0.), (0., .5, 0.), (.5, 0., .5)),
])
def test_closest_point_geometric_regions(addon_package, point, expected, weights):
    geometry = importlib.import_module(addon_package + ".surface_geometry")
    actual, bary = geometry.closest_point(point, (0., 0., 0.), (1., 0., 0.), (0., 1., 0.))
    assert actual == pytest.approx(expected) and bary == pytest.approx(weights)


def test_affine_inverse_roundtrip_including_mirror_and_shear(addon_package):
    geometry = importlib.import_module(addon_package + ".surface_geometry")
    matrix = ((-2., .25, 0., 10.), (0., .5, .125, -5.), (0., 0., 3., 1.), IDENTITY[3])
    point = (.125, -.75, 3.)
    assert geometry.transform(geometry.inverse(matrix), geometry.transform(matrix, point)) == pytest.approx(point)
    with pytest.raises(ValueError, match="Singular"):
        geometry.inverse(((0., 0., 0., 0.), *IDENTITY[1:]))


@pytest.mark.parametrize("parameter, value", [("source_polygon_indices", [True]), ("source_polygon_indices", [-1]),
    ("source_polygon_indices", []), ("source_polygon_indices", [20_000]), ("max_distance", True),
    ("max_distance", "0.25"), ("max_distance", float("nan")), ("max_distance", 0.),
    ("expected_fingerprint", "not-a-fingerprint"), ("object_name", 123)])
def test_mcp_schemas_reject_coercions_and_out_of_bounds(parameter, value):
    hints = get_type_hints(MeshSurfaceTools.mesh_project_to_surface, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(hints[parameter]).validate_python(value)


def test_wrappers_forward_exact_typed_contract_and_permissions():
    calls = []
    class Registry:
        async def call(self, name, params):
            calls.append((name, params))
            return {"changed": False}
    wrapper = MeshSurfaceTools(Registry())
    params = arguments()
    asyncio.run(wrapper.mesh_surface_projection_preview(**params))
    asyncio.run(wrapper.mesh_project_to_surface(**params, expected_fingerprint="a"*64))
    assert calls == [("mesh.surface_projection_preview", params),
        ("mesh.project_to_surface", {**params, "expected_fingerprint": "a"*64})]
    definitions = load_definitions()
    assert definitions[0].required_permissions == ("INSPECT_SCENE",)
    assert definitions[1].required_permissions == ("EDIT_MESH",)


@pytest.mark.parametrize("captured_boolean_layers", [True, False])
def test_legacy_named_boolean_custom_data_requires_actual_value_proof(surface, captured_boolean_layers):
    env = surface
    names = (".vs.UV", ".es.UV")
    env.obj.data.attributes.extend(NS(name=name, domain="CORNER", data_type="BOOLEAN") for name in names)
    if captured_boolean_layers:
        env.bm.loops.layers.bool = Layers({name: NS(name=name) for name in names})
    for face in env.bm.faces:
        for loop in face.loops:
            for uv in loop.layers.values():
                del uv.select
                del uv.select_edge
            if captured_boolean_layers:
                loop.layers.update({".vs.UV": True, ".es.UV": False})
    if not captured_boolean_layers:
        with pytest.raises(env.module.BridgeError, match="native custom-layer proof"):
            apply(env)
        assert not env.calls
        return
    result = apply(env)
    assert result["supported_custom_data_preserved"]
    assert all(loop.layers[".vs.UV"] is True and loop.layers[".es.UV"] is False
               for face in env.bm.faces for loop in face.loops)
