from __future__ import annotations

import asyncio
import copy
import importlib
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError
from test_mesh_slide import Loop, change_global_uv_flag, enable_global_uv_flags
from test_mesh_surface import LayerItem, Sequence
from test_mesh_surface import surface as surface_fixture  # noqa: F401 -- pytest fixture registration

from mcp_server.tools.catalog import load_mesh_definitions
from mcp_server.tools.mesh_chains import MeshChainTools


class Faces(Sequence):
    active = None


def _area(vertices):
    points = [vertex.co for vertex in vertices]
    total = 0.
    for index in range(1, len(points)-1):
        a = [points[index][i]-points[0][i] for i in range(3)]
        b = [points[index+1][i]-points[0][i] for i in range(3)]
        total += sum(value**2 for value in (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]))**.5*.5
    return total


@pytest.fixture
def chains(surface_fixture, monkeypatch):  # noqa: F811 -- imported pytest fixture
    env = surface_fixture
    module = importlib.import_module(env.module.__package__ + ".mesh_chains")
    bm = env.bm
    template = bm.verts[0]
    points = [(x, y, 0.) for y in (0., 1.) for x in (0., 1., 2.)] + [(3., 0., 0.), (4., 0., 0.), (4., 1., 0.), (3., 1., 0.)]
    bm.verts = Sequence([LayerItem(index=index, co=point, select=index < 6, hide=False,
        link_edges=[], link_faces=[], values=copy.deepcopy(template.values)) for index, point in enumerate(points)], bm.verts.layers)
    bm.edges, bm.faces = Sequence([]), Faces([])
    bm.select_history, bm.select_mode = [], {"EDGE"}

    def edge(a, b):
        existing = next((item for item in bm.edges if set(item.verts) == {a, b}), None)
        if existing is not None:
            return existing
        item = LayerItem(index=len(bm.edges), verts=[a, b], link_faces=[], select=False, hide=False, seam=False, smooth=True)
        bm.edges.append(item)
        a.link_edges.append(item)
        b.link_edges.append(item)
        return item

    def face_new(vertices):
        face = LayerItem(index=len(bm.faces), verts=list(vertices), edges=[], loops=[],
            select=False, hide=False, material_index=0, smooth=False, calc_area=lambda: _area(vertices))
        if hasattr(bm, "uv_select_sync_valid"):
            face.uv_select = False
        for index, vertex in enumerate(vertices):
            current = edge(vertex, vertices[(index+1) % len(vertices)])
            current.link_faces.append(face)
            face.edges.append(current)
            vertex.link_faces.append(face)
            loop = Loop(vertex, current, bm.loops.layers.uv.values())
            loop.face = face
            for data in loop.layers.values():
                data.uv, data.pin_uv, data.select, data.select_edge = (0., 0.), False, False, False
                if hasattr(bm, "uv_select_sync_valid"):
                    del data.select, data.select_edge
            if hasattr(bm, "uv_select_sync_valid"):
                loop.uv_select_vert, loop.uv_select_edge = False, False
            face.loops.append(loop)
        bm.faces.append(face)
        return face

    bm.faces.new = face_new
    for a, b in ((0, 1), (1, 2), (3, 4), (4, 5)):
        edge(bm.verts[a], bm.verts[b]).select = True
    old = face_new([bm.verts[index] for index in (6, 7, 8, 9)])
    old.select, old.material_index, old.smooth = True, 1, True
    bm.faces.active = old
    bm.select_history = [bm.edges[0], bm.verts[8], old]
    for index, loop in enumerate(old.loops):
        for data in loop.layers.values():
            data.uv, data.pin_uv = (index*.25, .75), index == 0
    material = NS(name="Second Material")
    env.obj.data.materials.append(material)
    env.obj.material_slots.append(NS(material=material, link="DATA"))
    env.obj.data.polygons = bm.faces
    env.reference = {"vertices": list(range(6)), "edges": [0, 1, 2, 3], "faces": []}
    monkeypatch.setattr(module, "_active_edit_mesh", lambda _: (env.bpy, env.objects[env.obj.name], bm, {}))
    monkeypatch.setattr(module, "validate_selection_reference", lambda *_: env.reference)
    invalidated = []
    monkeypatch.setattr(module, "clear_selection_references", invalidated.append)
    monkeypatch.setattr(module, "bmesh", NS(update_edit_mesh=lambda *a, **kw: env.calls.append(kw)))
    env.module, env.invalidated = module, invalidated
    return env


def arguments(**updates):
    return {"object_name": "Patch", "selection_id": "fresh", "rail_a_start": 0, "rail_a_end": 2,
        "rail_b_start": 3, "rail_b_end": 5, "material_index": 1, **updates}


def preview(env, **updates):
    return env.module.bridge_chains_preview(env.context, arguments(**updates))


def apply(env, **updates):
    params = arguments(**updates)
    proof = preview(env, **updates)
    return env.module.bridge_chains(env.context, {**params, "expected_fingerprint": proof["fingerprint"]})


def test_explicit_open_chain_preview_is_read_only_and_complete(chains):
    env = chains
    env.grants["EDIT_MESH"] = False
    before = env.module._state(env.obj, env.bm)
    result = preview(env)
    assert not result["changed"]
    assert result["rail_vertex_indices"] == [[0, 1, 2], [3, 4, 5]]
    assert result["planned_faces"] == [[0, 1, 4, 3], [1, 2, 5, 4]]
    assert result["topology_delta"] == {"vertices": 0, "edges": 3, "faces": 2}
    assert env.module._state(env.obj, env.bm) == before and not env.calls


def test_bridge_retains_all_old_attributes_weights_selection_and_context(chains):
    env = chains
    before = env.module._state(env.obj, env.bm)
    result = apply(env)
    after = env.module._state(env.obj, env.bm)
    assert env.module._old_projection(after, before) == before
    assert result["mesh_counts_after"] == result["expected_counts_after"]
    assert result["created_faces"] == 2 and result["preservation"]["original_uvs_pins_materials_weights"]
    assert [tuple(vertex.index for vertex in face.verts) for face in env.bm.faces[1:]] == [(0, 1, 4, 3), (1, 2, 5, 4)]
    assert all(face.material_index == 1 for face in env.bm.faces[1:])
    assert all(tuple(loop[layer].uv) == (0., 0.) and not loop[layer].pin_uv
        for face in env.bm.faces[1:] for loop in face.loops for layer in env.bm.loops.layers.uv.values())
    assert env.invalidated == ["Patch"] and env.calls == [{"loop_triangles": True, "destructive": True}]*2
    assert result["derived_cache_sync"]["verified_syncs"] == 2
    assert result["derived_cache_sync"]["last_verified_face_count"] == 2
    assert result["derived_cache_sync"]["current_topology_sync_verified"]


def test_reversing_both_explicit_rails_reverses_quad_winding(chains):
    result = apply(chains, rail_a_start=2, rail_a_end=0, rail_b_start=5, rail_b_end=3)
    assert result["planned_faces"] == [[2, 1, 4, 5], [1, 0, 3, 4]]


@pytest.mark.parametrize("field,value", [("rail_a_start", True), ("rail_a_end", -1), ("material_index", 256), ("selection_id", ""), ("extra", 0)])
def test_invalid_arguments_precede_writes(chains, field, value):
    with pytest.raises(chains.module.BridgeError) as error:
        apply(chains, **{field: value})
    assert error.value.code == "INVALID_ARGUMENT" and len(chains.bm.faces) == 1


@pytest.mark.parametrize("restriction", ["shared", "linked", "override", "shape_keys", "modifier", "custom_normals", "hidden", "interior", "closed", "unequal", "endpoints", "extra_chain", "folded", "existing_connection", "proof_budget"])
def test_unsupported_scope_refuses_before_allocation(chains, monkeypatch, restriction):
    env = chains
    if restriction == "shared":
        env.obj.data.users = 2
    elif restriction in {"linked", "override"}:
        setattr(env.obj.data, "library" if restriction == "linked" else "override_library", object())
    elif restriction == "shape_keys":
        env.obj.data.shape_keys = object()
    elif restriction == "modifier":
        env.obj.modifiers.append(object())
    elif restriction == "custom_normals":
        env.obj.data.has_custom_normals = True
    elif restriction == "hidden":
        env.bm.verts[0].hide = True
    elif restriction == "interior":
        env.bm.edges[0].link_faces = [object(), object()]
    elif restriction == "closed":
        env.bm.edges[1].verts[1] = env.bm.verts[0]
    elif restriction == "unequal":
        env.reference["edges"] = [0, 1, 2]
    elif restriction == "endpoints":
        with pytest.raises(env.module.BridgeError):
            preview(env, rail_a_end=5, rail_b_end=2)
        return
    elif restriction == "extra_chain":
        env.reference["edges"].append(4)
    elif restriction == "folded":
        env.bm.verts[3].co = env.bm.verts[0].co
    elif restriction == "existing_connection":
        env.bm.faces.new([env.bm.verts[index] for index in (0, 1, 4, 3)])
    else:
        monkeypatch.setattr(env.module, "MAX_PROOF_VALUES", 1)
    count = len(env.bm.faces)
    with pytest.raises(env.module.BridgeError):
        preview(env)
    assert len(env.bm.faces) == count and not env.calls


def test_same_direction_boundary_winding_requires_explicit_correction(chains):
    env = chains
    env.bm.faces.new([env.bm.verts[index] for index in (0, 1, 7, 6)])
    env.bm.faces.new([env.bm.verts[index] for index in (1, 2, 8, 7)])
    with pytest.raises(env.module.BridgeError, match="winding"):
        preview(env)


@pytest.mark.parametrize("change", ["position", "uv", "pin", "weight", "material", "selection", "active_face", "history", "identity", "policy", "endpoints"])
def test_preview_fingerprint_rejects_state_or_operation_drift(chains, monkeypatch, change):
    env = chains
    proof = preview(env)
    params = arguments(expected_fingerprint=proof["fingerprint"])
    if change == "position":
        env.bm.verts[0].co = (.125, 0., 0.)
    elif change in {"uv", "pin"}:
        data = env.bm.faces[0].loops[0][env.bm.loops.layers.uv.active]
        setattr(data, "uv" if change == "uv" else "pin_uv", (.2, .3) if change == "uv" else False)
    elif change == "weight":
        env.bm.verts[0].values["Weights"][0] = .75
    elif change == "material":
        params["material_index"] = 0
    elif change == "selection":
        env.bm.verts[9].select = True
    elif change == "active_face":
        env.bm.faces.active = None
    elif change == "history":
        env.bm.select_history.pop()
    elif change == "identity":
        env.obj.session_uid = 999
    elif change == "policy":
        monkeypatch.setattr(env.module, "SESSION_NONCE", "new-session")
    else:
        params.update(rail_a_start=2, rail_a_end=0, rail_b_start=5, rail_b_end=3)
    with pytest.raises(env.module.BridgeError, match="fingerprint"):
        env.module.bridge_chains(env.context, params)
    assert len(env.bm.faces) == 1 and not env.calls


@pytest.mark.parametrize("channel", ["sync", "face", "vertex", "edge"])
def test_native_global_uv_flags_are_preserved_and_fingerprinted(chains, channel):
    env = chains
    enable_global_uv_flags(env.bm)
    proof = preview(env)
    change_global_uv_flag(env.bm, channel)
    with pytest.raises(env.module.BridgeError, match="fingerprint"):
        env.module.bridge_chains(env.context, arguments(expected_fingerprint=proof["fingerprint"]))
    before = env.module._state(env.obj, env.bm)
    apply(env)
    assert env.module._old_projection(env.module._state(env.obj, env.bm), before) == before


@pytest.mark.parametrize("restriction", ["permission", "pause", "stop", "cancel", "pure_deadline"])
def test_live_denial_before_first_write(chains, restriction):
    env = chains
    params = arguments(expected_fingerprint=preview(env)["fingerprint"])
    if restriction == "permission":
        env.grants["EDIT_MESH"] = False
    elif restriction in {"pause", "stop"}:
        env.flags["paused" if restriction == "pause" else "emergency_stopped"] = True
    else:
        def deny():
            raise env.module.BridgeError("TIMEOUT", "expired")
        setattr(env.context, "check_cancelled" if restriction == "cancel" else "check_final_request", deny)
    with pytest.raises(env.module.BridgeError) as error:
        env.module.bridge_chains(env.context, params)
    assert not error.value.context.get("execution_started") and len(env.bm.faces) == 1 and not env.calls


def test_provider_mutation_cannot_be_adopted_before_publication(chains):
    env = chains
    params = arguments(expected_fingerprint=preview(env)["fingerprint"])
    require = env.context.require
    def mutate(*permissions):
        require(*permissions)
        env.bm.verts[9].values["Weights"][0] = .9
    env.context.require = mutate
    with pytest.raises(env.module.BridgeError) as error:
        env.module.bridge_chains(env.context, params)
    assert not error.value.context["execution_started"] and len(env.bm.faces) == 1


@pytest.mark.parametrize("kind", ["coordinate", "uv", "custom_float", "weight_type", "uv_clone"])
def test_provider_signed_zero_or_scalar_type_drift_is_not_unchanged(chains, kind):
    env = chains
    if kind == "weight_type":
        env.bm.verts[9].values["Weights"][0] = 1
    params = arguments(expected_fingerprint=preview(env)["fingerprint"])
    require = env.context.require
    def mutate(*permissions):
        require(*permissions)
        if kind == "coordinate":
            env.bm.verts[0].co = (-0., 0., 0.)
        elif kind == "uv":
            data = env.bm.faces[0].loops[0][env.bm.loops.layers.uv.active]
            data.uv = (-0., .75)
        elif kind == "custom_float":
            env.bm.verts[9].values["Temperature"] = -0.
        elif kind == "weight_type":
            env.bm.verts[9].values["Weights"][0] = True
        else:
            env.obj.data.uv_layers[0].active_clone = True
    env.context.require = mutate
    with pytest.raises(env.module.BridgeError) as error:
        env.module.bridge_chains(env.context, params)
    assert not error.value.context["execution_started"] and len(env.bm.faces) == 1


@pytest.mark.parametrize("failure", ["second_face", "late_stop", "late_permission", "newer_old_data", "newer_output", "new_edge_select", "new_edge_hide", "new_uv_select", "bad_native_uv", "bad_native_topology", "update"])
def test_partial_failure_retains_truthful_effects_without_cleanup_writes(chains, monkeypatch, failure):
    env = chains
    original = env.module._new_face
    allocations = []
    def fault(bm, vertices):
        if failure == "second_face" and allocations:
            raise RuntimeError("injected second allocation fault")
        face = original(bm, vertices)
        allocations.append(face)
        if failure == "late_stop":
            env.flags["emergency_stopped"] = True
        elif failure == "late_permission":
            env.grants["EDIT_MESH"] = False
        elif failure == "newer_old_data":
            bm.verts[9].co = (3., 1., .5)
        elif failure == "newer_output":
            face.select = True
        elif failure in {"new_edge_select", "new_edge_hide"}:
            setattr(bm.edges[-1], "select" if failure == "new_edge_select" else "hide", True)
        elif failure == "new_uv_select":
            face.loops[0][bm.loops.layers.uv.active].select = True
        elif failure == "bad_native_uv":
            face.loops[0][bm.loops.layers.uv.active].uv = (.1, .2)
        elif failure == "bad_native_topology":
            face.verts.reverse()
        return face
    monkeypatch.setattr(env.module, "_new_face", fault)
    if failure == "update":
        def fail_update(*_args, **_kwargs):
            raise RuntimeError("injected edit sync fault")
        monkeypatch.setattr(env.module.bmesh, "update_edit_mesh", fail_update)
    with pytest.raises(env.module.BridgeError) as error:
        apply(env)
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
    assert error.value.context["verification_required"] and len(env.bm.faces) > 1
    if failure == "second_face":
        assert env.calls == [{"loop_triangles": True, "destructive": True}]
        sync = error.value.context["derived_cache_sync"]
        assert sync["verified_syncs"] == sync["last_verified_face_count"] == 1
        assert sync["edit_mesh_update_calls_started"] == sync["edit_mesh_update_calls_returned"] == 1
    else:
        assert not env.calls
    assert not error.value.context["derived_cache_sync"]["current_topology_sync_verified"]
    assert not env.invalidated


@pytest.mark.parametrize("boundary", ["before_normal", "after_normal", "after_edit_update", "before_next_face"])
@pytest.mark.parametrize("denial", ["permission", "cancel", "deadline", "pause", "stop"])
def test_derived_sync_stops_at_each_native_boundary_without_late_writes(chains, monkeypatch, boundary, denial):
    env = chains
    normal_calls, update_calls, stopped = [], [], []
    original_normal, original_update = env.bm.normal_update, env.module.bmesh.update_edit_mesh
    original_require = env.context.require
    def deny_now():
        stopped.append(True)
        if denial == "permission":
            env.grants["EDIT_MESH"] = False
        elif denial in {"pause", "stop"}:
            env.flags["paused" if denial == "pause" else "emergency_stopped"] = True
    def check_cancelled():
        if stopped and denial == "cancel":
            raise env.module.BridgeError("TIMEOUT", "owner cancelled")
    def check_final():
        if stopped and denial in {"deadline", "cancel"}:
            raise env.module.BridgeError("TIMEOUT", "owner expired or cancelled")
    def require(*permissions):
        if boundary == "before_normal" and len(env.bm.faces) == 2:
            deny_now()
        original_require(*permissions)
    def normal():
        normal_calls.append(True)
        original_normal()
        if boundary == "after_normal":
            deny_now()
    def update(*args, **kwargs):
        update_calls.append(kwargs)
        original_update(*args, **kwargs)
        if boundary == "after_edit_update":
            deny_now()
    env.context.require, env.context.check_cancelled, env.context.check_final_request = require, check_cancelled, check_final
    monkeypatch.setattr(env.bm, "normal_update", normal)
    monkeypatch.setattr(env.module.bmesh, "update_edit_mesh", update)
    if boundary == "before_next_face":
        original_sync = env.module._Guard.sync_verified_face
        def sync(guard):
            original_sync(guard)
            deny_now()
        monkeypatch.setattr(env.module._Guard, "sync_verified_face", sync)
    with pytest.raises(env.module.BridgeError) as error:
        apply(env)
    assert len(env.bm.faces) == 2  # No second allocation after the stopped boundary.
    assert len(normal_calls) == (0 if boundary == "before_normal" else 1)
    assert len(update_calls) == (0 if boundary in {"before_normal", "after_normal"} else 1)
    sync = error.value.context["derived_cache_sync"]
    assert sync["normal_update_calls_started"] == sync["normal_update_calls_returned"] == len(normal_calls)
    assert sync["edit_mesh_update_calls_started"] == sync["edit_mesh_update_calls_returned"] == len(update_calls)
    assert sync["verified_syncs"] == sync["last_verified_face_count"] == (1 if boundary == "before_next_face" else 0)
    assert not sync["current_topology_sync_verified"] and not env.invalidated


@pytest.mark.parametrize("stage", ["normal", "edit_update"])
def test_derived_sync_does_not_adopt_native_protected_data_changes(chains, monkeypatch, stage):
    env = chains
    if stage == "normal":
        def normal():
            env.bm.verts[9].co = (3., 1., .5)
        monkeypatch.setattr(env.bm, "normal_update", normal)
    else:
        def update(*_args, **_kwargs):
            env.bm.faces[-1].loops[0][env.bm.loops.layers.uv.active].uv = (.25, .5)
        monkeypatch.setattr(env.module.bmesh, "update_edit_mesh", update)
    with pytest.raises(env.module.BridgeError) as error:
        apply(env)
    assert error.value.code == "INVALID_SELECTION" and len(env.bm.faces) == 2
    sync = error.value.context["derived_cache_sync"]
    assert sync["normal_update_calls_started"] == sync["normal_update_calls_returned"] == 1
    assert sync["edit_mesh_update_calls_started"] == sync["edit_mesh_update_calls_returned"] == (1 if stage == "edit_update" else 0)
    assert sync["verified_syncs"] == 0 and not env.invalidated


@pytest.mark.parametrize("defect", ["wire_branch", "wire_attachment", "bow_tie", "hidden_star"])
def test_affected_vertex_stars_reject_nonmanifold_or_hidden_scope(chains, defect):
    env = chains
    if defect == "wire_branch":
        vertex = env.bm.verts[1]
        extra = LayerItem(verts=[vertex, env.bm.verts[6]], link_faces=[], hide=False)
        vertex.link_edges.append(extra)
    elif defect == "wire_attachment":
        env.bm.faces.new([env.bm.verts[index] for index in (0, 6, 7)])
    elif defect == "bow_tie":
        env.bm.faces.new([env.bm.verts[index] for index in (1, 0, 6)])
        env.bm.faces.new([env.bm.verts[index] for index in (1, 7, 8)])
    else:
        env.bm.faces.new([env.bm.verts[index] for index in (1, 0, 6)])
        env.bm.verts[6].hide = True
    count = len(env.bm.faces)
    with pytest.raises(env.module.BridgeError):
        preview(env)
    assert len(env.bm.faces) == count and not env.calls


@pytest.mark.parametrize("field", ["uv", "pin", "material", "selection", "custom_float"])
def test_later_allocation_cannot_adopt_drift_in_earlier_published_face(chains, monkeypatch, field):
    env = chains
    original, allocated = env.module._new_face, []
    def allocate(bm, vertices):
        face = original(bm, vertices)
        if allocated:
            earlier = allocated[0]
            if field in {"uv", "pin"}:
                data = earlier.loops[0][bm.loops.layers.uv.active]
                setattr(data, "uv" if field == "uv" else "pin_uv", (.25, .75) if field == "uv" else True)
            elif field == "material":
                earlier.material_index = 0  # Published requested material is 1.
            elif field == "selection":
                earlier.select = True
            else:
                bm.verts[0].values["Temperature"] = .875
        allocated.append(face)
        return face
    monkeypatch.setattr(env.module, "_new_face", allocate)
    with pytest.raises(env.module.BridgeError) as error:
        apply(env)
    assert len(allocated) == 2 and len(env.bm.faces) == 3
    assert error.value.context["possible_mutation"] and not error.value.context["rollback_verified"]
    assert error.value.context["created_faces_verified"] == 1
    assert not error.value.context["created_faces_count_complete"]
    assert env.calls == [{"loop_triangles": True, "destructive": True}]


def test_invalidated_native_object_cannot_erase_partial_failure_receipt(chains, monkeypatch):
    env = chains
    original, expired = env.module._new_face, []
    original_getattribute = type(env.obj).__getattribute__
    def object_read(owner, name):
        if owner is env.obj and name == "name" and expired:
            raise ReferenceError("native object RNA was removed")
        return original_getattribute(owner, name)
    monkeypatch.setattr(type(env.obj), "__getattribute__", object_read)
    def allocate(bm, vertices):
        face = original(bm, vertices)
        expired.append(True)
        return face
    monkeypatch.setattr(env.module, "_new_face", allocate)
    with pytest.raises(env.module.BridgeError) as error:
        apply(env)
    assert error.value.code == "OPERATION_FAILED"
    assert error.value.context["object"] == "Patch" and error.value.context["affected_objects"] == ["Patch"]
    assert error.value.context["execution_started"] and error.value.context["possible_mutation"]
    assert error.value.context["created_faces_verified"] == 0
    assert not error.value.context["rollback_verified"] and not env.calls


def test_checkpoint_guard_retains_pre_provider_baseline_and_updates_only_owned_state(chains):
    env = chains
    params = arguments(expected_fingerprint=preview(env)["fingerprint"])
    package = env.module.__package__.rsplit(".", 1)[0]
    registry_module = importlib.import_module(package + ".tool_registry")
    registry = registry_module.ToolRegistry(enabled_toolsets=["mesh"])
    env.module.register_tools(registry)
    state = importlib.import_module(package + ".state").BridgeState()
    permissions = importlib.import_module(package + ".permissions").PermissionManager(lambda: env.grants)
    context = registry_module.ToolContext(state, permissions, registry, None)
    spec = registry.get("mesh.bridge_chains")
    with registry.checkpoint_admission(spec, params, context) as binding:
        guard = binding.callback
        guard.check_after_read()
        result = registry.invoke(spec, params, context)
        guard.check_after_read()
        assert result["created_faces"] == 2
        env.bm.verts[9].values["Weights"][1] = .125
        with pytest.raises(env.module.BridgeError, match="state changed"):
            guard.check_after_read()


def test_two_vertex_wire_chains_make_one_quad_without_extra_vertices(chains):
    env = chains
    for edge in [env.bm.edges[1], env.bm.edges[3]]:
        for vertex in edge.verts:
            vertex.link_edges.remove(edge)
        env.bm.edges.remove(edge)
    env.bm.edges.index_update()
    env.reference["edges"] = [0, 1]
    result = apply(env, rail_a_end=1, rail_b_end=4)
    assert result["created_faces"] == 1
    assert result["topology_delta"] == {"vertices": 0, "edges": 2, "faces": 1}


def test_partial_wire_selection_cannot_leave_unreviewed_wire_attachments(chains):
    env = chains
    env.reference["edges"] = [0, 2]
    with pytest.raises(env.module.BridgeError, match="unselected extensions"):
        preview(env, rail_a_end=1, rail_b_end=4)
    assert len(env.bm.faces) == 1


def test_guard_rechecks_pure_lifetime_after_expensive_preservation_reads(chains, monkeypatch):
    env = chains
    params = arguments(expected_fingerprint=preview(env)["fingerprint"])
    guard = env.module._factory(env.context, params)
    original, expired = env.module._state, []
    def read(*args):
        state = original(*args)
        expired.append(True)
        return state
    def deadline():
        if expired:
            raise env.module.BridgeError("TIMEOUT", "expired during native evidence read")
    monkeypatch.setattr(env.module, "_state", read)
    env.context.check_final_request = deadline
    with pytest.raises(env.module.BridgeError, match="evidence read"):
        guard()
    assert len(env.bm.faces) == 1


def test_registry_permissions_schemas_and_wrappers_match(addon_package):
    registry = importlib.import_module(addon_package + ".tool_registry").ToolRegistry()
    module = importlib.import_module(addon_package + ".tools.mesh_chains")
    module.register_tools(registry)
    definitions = {item.name: item for item in load_mesh_definitions()}
    calls = []
    class Remote:
        async def call(self, name, params):
            calls.append((name, params))
            return params
    wrappers = MeshChainTools(Remote())
    for name in ("bridge_chains_preview", "bridge_chains"):
        method = getattr(wrappers, "mesh_"+name)
        params = arguments(**({"expected_fingerprint": "a"*64} if name == "bridge_chains" else {}))
        asyncio.run(method(**params))
        spec = registry.get("mesh."+name)
        assert calls[-1] == (spec.name, params)
        assert definitions[spec.name].modifying == spec.modifies
        assert set(definitions[spec.name].required_permissions) == {p.value for p in spec.permissions}
        assert spec.automatic_checkpoint
        if spec.modifies:
            assert not spec.batchable and spec.checkpoint_admission_factory is module._factory
        hints = get_type_hints(method, include_extras=True)
        for label, invalid in (("rail_a_start", True), ("rail_b_end", -1), ("material_index", 256)):
            with pytest.raises(ValidationError):
                TypeAdapter(hints[label]).validate_python(invalid)
        if spec.modifies:
            with pytest.raises(ValidationError):
                TypeAdapter(hints["expected_fingerprint"]).validate_python("wrong")
