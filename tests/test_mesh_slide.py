from __future__ import annotations

import asyncio
import copy
import importlib
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError

from mcp_server.tools.mesh_slide import MeshSlideTools


class Item:
    def __init__(self, **values):
        self.__dict__.update(values)


class Loop:
    def __init__(self, vertex, edge, layers):
        self.vert, self.edge = vertex, edge
        self.layers = {layer.name: NS(uv=(vertex.co[0]*.5, vertex.co[1]*.5), pin_uv=False,
            select=bool(vertex.index % 2), select_edge=not bool(vertex.index % 2)) for layer in layers}

    def __getitem__(self, layer):
        return self.layers[layer.name]


class Layers(dict):
    active = None


def grid():
    vertices = [Item(index=i, co=(float(i % 3), float(i // 3), 0.), select=i == 4,
        hide=False, link_edges=[], link_faces=[]) for i in range(9)]
    edges, faces, seen = [], [], {}
    layers = Layers({name: NS(name=name) for name in ("UV", "Spare")})
    layers.active = layers["Spare"]
    for indices in ((0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7)):
        face = Item(index=len(faces), verts=[vertices[i] for i in indices], edges=[], loops=[],
            select=True, hide=False, material_index=0, smooth=False)
        for first, second in zip(indices, (*indices[1:], indices[0]), strict=True):
            key = tuple(sorted((first, second)))
            if key not in seen:
                edge = Item(index=len(edges), verts=[vertices[first], vertices[second]],
                    link_faces=[], hide=False, select=False, seam=False, smooth=True)
                edges.append(edge)
                seen[key] = edge
                vertices[first].link_edges.append(edge)
                vertices[second].link_edges.append(edge)
            edge = seen[key]
            edge.link_faces.append(face)
            face.edges.append(edge)
            face.loops.append(Loop(vertices[first], edge, layers.values()))
        for vertex in face.verts:
            vertex.link_faces.append(face)
        faces.append(face)
    bm = NS(verts=vertices, edges=edges, faces=faces,
        loops=NS(layers=NS(uv=layers)), normal_update=lambda: None)
    return bm, seen


@pytest.fixture
def slide(addon_package, monkeypatch):
    module = importlib.import_module(addon_package + ".tools.mesh_slide")
    uv = importlib.import_module(addon_package + ".tools.uv_refine")
    bm, edges = grid()
    obj = NS(name="Prop", data=NS(users=1, shape_keys=None, materials=[NS(name="Mat")]), is_editable=True)
    reference = {"vertices": [4], "edges": [edges[(1, 4)].index, edges[(4, 7)].index], "faces": [0, 1, 2, 3]}
    monkeypatch.setattr(module, "_active_edit_mesh", lambda _: (None, obj, bm, {}))
    monkeypatch.setattr(module, "validate_selection_reference", lambda *_: reference)
    monkeypatch.setattr(uv.uv_edit, "_active_edit_mesh", lambda _: (None, obj, bm, {}))
    monkeypatch.setattr(uv.uv_edit, "validate_selection_reference", lambda *_: reference)
    calls = []
    backend = NS(update_edit_mesh=lambda *a, **kw: calls.append(kw))
    monkeypatch.setattr(module, "bmesh", backend)
    monkeypatch.setattr(uv, "bmesh", backend)
    errors = importlib.import_module(addon_package + ".errors")
    flags = {"paused": False, "emergency_stopped": False}
    grants = {"INSPECT_SCENE": True, "EDIT_MESH": True}
    def require(*permissions):
        if any(not grants[permission.value] for permission in permissions):
            raise errors.BridgeError("PERMISSION_DENIED", "denied")
    context = NS(require=require, check_cancelled=None, state=NS(snapshot=lambda: dict(flags)))
    return NS(module=module, uv=uv, bm=bm, obj=obj, reference=reference, calls=calls,
              context=context, grants=grants, flags=flags, edges=edges)


def arguments(**updates):
    return {"object_name": "Prop", "selection_id": "fresh", "targets": [{"vertex_index": 4, "target_vertex_index": 5}],
        "factor": .25, "max_distance": .3, **updates}


def apply(env, mode="VERTEX", **updates):
    params = arguments(**updates)
    preview = env.module.slide_preview(env.context, {**params, "mode": mode})
    return (env.module.vertex_slide if mode == "VERTEX" else env.module.edge_slide)(env.context,
        {**params, "expected_fingerprint": preview["fingerprint"]})


def test_vertex_slide_moves_only_explicit_vertex_and_preserves_uv_material_selection(slide):
    env = slide
    before = env.module._snapshot(env.obj, env.bm)
    result = apply(env)
    assert env.bm.verts[4].co == (1.25, 1., 0.)
    assert all(tuple(vertex.co) == before["vertices"][index][0] for index, vertex in enumerate(env.bm.verts) if index != 4)
    after = env.module._snapshot(env.obj, env.bm)
    assert after["uv"] == before["uv"] and after["materials"] == before["materials"]
    assert result["maximum_distance_local"] == .25 and result["protected_vertices_preserved"]
    assert not result["topology_changed"] and env.calls == [{"loop_triangles": False, "destructive": False}]


def test_edge_slide_requires_complete_chain_rails_and_revises_measured_column(slide):
    env = slide
    targets = [{"vertex_index": index, "target_vertex_index": index+1} for index in (1, 4, 7)]
    result = apply(env, "EDGE", targets=targets)
    assert result["target_count"] == 3
    assert [env.bm.verts[index].co[0] for index in (1, 4, 7)] == [1.25] * 3
    assert [env.bm.verts[index].co[0] for index in (0, 3, 6)] == [0.] * 3


def test_preview_is_nonmutating_and_needs_only_inspection(slide):
    env = slide
    env.grants["EDIT_MESH"] = False
    before = env.module._snapshot(env.obj, env.bm)
    preview = env.module.slide_preview(env.context, {**arguments(), "mode": "VERTEX"})
    assert len(preview["fingerprint"]) == 64 and not preview["changed"]
    assert env.module._snapshot(env.obj, env.bm) == before and env.calls == []


@pytest.mark.parametrize("value", [None, [], [{"vertex_index": True, "target_vertex_index": 5}],
    [{"vertex_index": 4, "target_vertex_index": 4}], [{"vertex_index": 4, "target_vertex_index": 99}],
    [{"vertex_index": 4, "target_vertex_index": 5, "extra": 1}],
    [{"vertex_index": 4, "target_vertex_index": 5}] * 2,
    [{"vertex_index": 4, "target_vertex_index": 5}, {"vertex_index": 5, "target_vertex_index": 4}]])
def test_invalid_rails_fail_before_mutation(slide, value):
    env = slide
    with pytest.raises(env.module.BridgeError):
        apply(env, targets=value)
    assert env.bm.verts[4].co == (1., 1., 0.) and not env.calls


@pytest.mark.parametrize("change", ["not_selected", "nonadjacent", "hidden_vertex", "hidden_rail", "hidden_face", "nonmanifold", "shared", "shape_key", "locked", "distance", "factor"])
def test_unsupported_or_unconsented_slide_scope_never_changes_mesh(slide, change):
    env = slide
    updates = {}
    if change == "not_selected":
        env.reference["vertices"] = [0]
    elif change == "nonadjacent":
        updates["targets"] = [{"vertex_index": 4, "target_vertex_index": 8}]
    elif change == "hidden_vertex":
        env.bm.verts[5].hide = True
    elif change == "hidden_rail":
        env.edges[(4, 5)].hide = True
    elif change == "hidden_face":
        env.bm.faces[0].hide = True
    elif change == "nonmanifold":
        env.edges[(4, 5)].link_faces.append(env.bm.faces[0])
    elif change == "shared":
        env.obj.data.users = 2
    elif change == "shape_key":
        env.obj.data.shape_keys = object()
    elif change == "locked":
        env.obj.is_editable = False
    elif change == "distance":
        updates["max_distance"] = .1
    else:
        updates["factor"] = 1.
    with pytest.raises(env.module.BridgeError):
        apply(env, **updates)
    assert env.bm.verts[4].co == (1., 1., 0.) and not env.calls


def test_stale_preview_cannot_slide_changed_coordinates(slide):
    env = slide
    params = arguments()
    preview = env.module.slide_preview(env.context, {**params, "mode": "VERTEX"})
    env.bm.verts[5].co = (2.1, 1., 0.)
    with pytest.raises(env.module.BridgeError, match="fingerprint"):
        env.module.vertex_slide(env.context, {**params, "expected_fingerprint": preview["fingerprint"]})
    assert not env.calls


def test_face_fan_inversion_and_collapse_are_rejected_independently(slide):
    env = slide
    with pytest.raises(env.module.BridgeError, match="invert"):
        env.module._face_checks(env.bm.faces, {4: (3., 1., 0.)})
    with pytest.raises(env.module.BridgeError, match="degenerate"):
        env.module._face_checks(env.bm.faces, {4: (2., 1., 0.)})


@pytest.mark.parametrize("failure", ["cancel", "pause", "permission"])
def test_postwrite_failure_reports_verified_recovery_or_revoked_edit_grant(slide, monkeypatch, failure):
    env = slide
    backend = env.module.bmesh
    def update(*args, **kwargs):
        env.calls.append(kwargs)
        if len(env.calls) == 1:
            if failure == "cancel":
                def cancelled():
                    raise env.module.BridgeError("TIMEOUT", "cancelled")
                env.context.check_cancelled = cancelled
            elif failure == "pause":
                env.flags["paused"] = True
            else:
                env.grants["EDIT_MESH"] = False
    monkeypatch.setattr(backend, "update_edit_mesh", update)
    with pytest.raises(env.module.BridgeError) as caught:
        apply(env)
    restored = failure != "permission"
    assert caught.value.context["rollback_verified"] is restored
    assert caught.value.context["possible_mutation"] is not restored
    assert env.bm.verts[4].co == ((1., 1., 0.) if restored else (1.25, 1., 0.))


def test_slide_schemas_are_strict_and_forward_exact_request():
    hints = get_type_hints(MeshSlideTools.mesh_vertex_slide, include_extras=True)
    for key, value in (("targets", [{"vertex_index": True, "target_vertex_index": 1}]),
        ("targets", [{"vertex_index": 1, "target_vertex_index": 2, "extra": 1}]),
        ("factor", True), ("factor", 1.), ("max_distance", float("nan")), ("expected_fingerprint", "old")):
        with pytest.raises(ValidationError):
            TypeAdapter(hints[key]).validate_python(value)
    calls = []
    async def call(method, params):
        calls.append((method, params))
    targets = [{"vertex_index": 1, "target_vertex_index": 2}]
    asyncio.run(MeshSlideTools(NS(call=call)).mesh_vertex_slide("Prop", "ref", targets, .2, .3, "a"*64))
    assert calls[0] == ("mesh.vertex_slide", {"object_name": "Prop", "selection_id": "ref", "targets": targets,
        "factor": .2, "max_distance": .3, "expected_fingerprint": "a"*64})


@pytest.mark.parametrize("change", ["shared", "mesh_replaced", "shape_key", "locked"])
def test_mutation_gate_rechecks_ownership_and_exact_mesh_identity(slide, change):
    env = slide
    params = arguments()
    preview = env.module.slide_preview(env.context, {**params, "mode": "VERTEX"})
    checks = 0
    def check():
        nonlocal checks
        checks += 1
        if checks != 2:
            return
        if change == "shared":
            env.obj.data.users = 2
        elif change == "mesh_replaced":
            env.obj.data = copy.copy(env.obj.data)
        elif change == "shape_key":
            env.obj.data.shape_keys = object()
        else:
            env.obj.is_editable = False
    env.context.check_cancelled = check
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.vertex_slide(env.context, {**params, "expected_fingerprint": preview["fingerprint"]})
    assert not caught.value.context["execution_started"]
    assert env.bm.verts[4].co == (1., 1., 0.) and not env.calls


@pytest.mark.parametrize("change", ["shared", "mesh_replaced"])
def test_recovery_refuses_changed_ownership_after_first_write(slide, monkeypatch, change):
    env = slide
    def update(*args, **kwargs):
        env.calls.append(kwargs)
        if change == "shared":
            env.obj.data.users = 2
        else:
            env.obj.data = copy.copy(env.obj.data)
    monkeypatch.setattr(env.module.bmesh, "update_edit_mesh", update)
    with pytest.raises(env.module.BridgeError) as caught:
        apply(env)
    assert caught.value.context["execution_started"] and caught.value.context["possible_mutation"]
    assert not caught.value.context["rollback_verified"] and env.bm.verts[4].co == (1.25, 1., 0.)
    assert len(env.calls) == 1


def test_same_named_material_replacement_invalidates_preview(slide):
    env = slide
    params = arguments()
    preview = env.module.slide_preview(env.context, {**params, "mode": "VERTEX"})
    env.obj.data.materials[0] = NS(name="Mat")
    with pytest.raises(env.module.BridgeError, match="fingerprint"):
        env.module.vertex_slide(env.context, {**params, "expected_fingerprint": preview["fingerprint"]})
    assert not env.calls


def test_partial_native_assignment_is_reported_as_attempted_mutation(slide):
    env = slide
    vertex = env.bm.verts[4]
    class Partial(Item):
        @property
        def co(self):
            return self._co
        @co.setter
        def co(self, value):
            self._co = (value[0], 42., value[2])
            raise RuntimeError("partial native coordinate assignment")
    vertex._co = vertex.__dict__.pop("co")
    vertex.__class__ = Partial
    with pytest.raises(env.module.BridgeError) as caught:
        apply(env)
    assert caught.value.context["execution_started"] and caught.value.context["possible_mutation"]
    assert not caught.value.context["rollback_verified"]


def test_raw_mode_enum_has_structured_error_for_unhashable_input(slide):
    env = slide
    with pytest.raises(env.module.BridgeError) as caught:
        env.module.slide_preview(env.context, {**arguments(), "mode": []})
    assert caught.value.code == "INVALID_ARGUMENT"
