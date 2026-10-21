from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace as NS
from typing import get_type_hints

import pytest
from pydantic import TypeAdapter, ValidationError
from test_mesh_slide import slide  # noqa: F401

from mcp_server.tools.uv_refine import UVRefineTools

# Shared fixture is deliberately imported under its pytest name.
# ruff: noqa: F811


def arguments(**updates):
    return {"object_name": "Prop", "uv_layer": "UV", "selection_id": "fresh", **updates}


def corner(face, index):
    return {"face_index": face, "corner_index": index}


def test_align_changes_only_explicit_axis_and_preserves_other_layers_and_pins(slide):
    env = slide
    before = env.module._snapshot(env.obj, env.bm)
    result = env.uv.align(env.context, arguments(corners=[corner(0, 0)], axis="U", value=.125))
    assert env.bm.faces[0].loops[0].layers["UV"].uv == (.125, 0.)
    after = env.module._snapshot(env.obj, env.bm)
    assert after["vertices"] == before["vertices"] and after["uv"][1] == before["uv"][1]
    assert after["uv_active"] == before["uv_active"] == "Spare"
    assert result["changed_corners"] == 1 and result["pins_preserved"]


def test_align_pinned_corner_off_line_is_rejected_before_any_write(slide):
    env = slide
    env.bm.faces[0].loops[0].layers["UV"].pin_uv = True
    with pytest.raises(env.uv.BridgeError, match="pinned"):
        env.uv.align(env.context, arguments(corners=[corner(0, 0)], axis="U", value=.1))
    assert env.bm.faces[0].loops[0].layers["UV"].uv == (0., 0.) and not env.calls


def test_alignment_cannot_collapse_an_entire_face(slide):
    env = slide
    with pytest.raises(env.uv.BridgeError, match="degenerate"):
        env.uv.align(env.context, arguments(corners=[corner(0, i) for i in range(4)], axis="U", value=.25))
    assert not env.calls


def test_stitch_closes_explicit_same_vertex_gap_and_keeps_anchor_fixed(slide):
    env = slide
    source = env.bm.faces[0].loops[2].layers["UV"]
    target = env.bm.faces[1].loops[3].layers["UV"]
    target.uv = (.55, .5)
    before = env.module._snapshot(env.obj, env.bm)
    result = env.uv.stitch(env.context, arguments(pairs=[{"source": corner(0, 2), "target": corner(1, 3)}]))
    assert source.uv == target.uv == (.5, .5)
    assert result["stitched_pairs"] == 1 and result["maximum_gap_after_uv"] == 0.
    assert env.module._snapshot(env.obj, env.bm)["uv"][1] == before["uv"][1]


@pytest.mark.parametrize("change", ["different_vertex", "duplicate_target", "moving_anchor", "outside", "distance", "pinned"])
def test_invalid_stitch_correspondence_never_changes_uvs(slide, change):
    env = slide
    env.bm.faces[1].loops[3].layers["UV"].uv = (.55, .5)
    pairs = [{"source": corner(0, 2), "target": corner(1, 3)}]
    updates = {}
    if change == "different_vertex":
        pairs[0]["target"] = corner(1, 2)
    elif change == "duplicate_target":
        pairs *= 2
    elif change == "moving_anchor":
        pairs.append({"source": corner(1, 3), "target": corner(2, 1)})
    elif change == "outside":
        env.reference["faces"] = [0]
    elif change == "distance":
        updates["max_distance"] = .01
    else:
        env.bm.faces[1].loops[3].layers["UV"].pin_uv = True
    before = env.module._snapshot(env.obj, env.bm)
    with pytest.raises(env.uv.BridgeError):
        env.uv.stitch(env.context, arguments(pairs=pairs, **updates))
    assert env.module._snapshot(env.obj, env.bm) == before and not env.calls


def displace_center(env):
    for face in env.bm.faces:
        for loop in face.loops:
            if loop.vert.index == 4:
                loop.layers["UV"].uv = (.625, .5625)


def test_relax_complete_island_improves_interior_while_fixing_boundary_and_other_layers(slide):
    env = slide
    displace_center(env)
    before = env.module._snapshot(env.obj, env.bm)
    result = env.uv.relax(env.context, arguments(face_indices=[0, 1, 2, 3], iterations=10, strength=.5))
    assert result["fixed_uv_nodes"] == 8 and result["movable_uv_nodes"] == 1
    assert result["edge_energy_after"] < result["edge_energy_before"]
    for face in env.bm.faces:
        for loop in face.loops:
            if loop.vert.index == 4:
                assert loop.layers["UV"].uv == pytest.approx((.5, .5), abs=.0002)
            else:
                assert loop.layers["UV"].uv == (loop.vert.co[0]*.5, loop.vert.co[1]*.5)
    after = env.module._snapshot(env.obj, env.bm)
    assert after["vertices"] == before["vertices"] and after["uv"][1] == before["uv"][1]


def test_any_pinned_corner_fixes_the_entire_continuous_uv_node(slide):
    env = slide
    displace_center(env)
    env.bm.faces[0].loops[2].layers["UV"].pin_uv = True
    before = env.module._snapshot(env.obj, env.bm)
    result = env.uv.relax(env.context, arguments(face_indices=[0, 1, 2, 3]))
    assert result["changed_corners"] == 0 and result["movable_uv_nodes"] == 0
    assert env.module._snapshot(env.obj, env.bm) == before


@pytest.mark.parametrize("change", ["partial", "disconnected", "outside_ref", "displacement", "nonmanifold", "budget"])
def test_relax_rejects_incomplete_or_unsafe_islands_before_writes(slide, monkeypatch, change):
    env = slide
    displace_center(env)
    indices, updates = [0, 1, 2, 3], {}
    if change == "partial":
        indices = [0, 1]
    elif change == "disconnected":
        for loop in env.bm.faces[1].loops:
            u, v = loop.layers["UV"].uv
            loop.layers["UV"].uv = (u+2., v)
    elif change == "outside_ref":
        env.reference["faces"] = [0, 1]
    elif change == "displacement":
        updates["max_displacement"] = .001
    elif change == "nonmanifold":
        env.edges[(1, 4)].link_faces.append(env.bm.faces[2])
    else:
        monkeypatch.setattr(env.uv, "MAX_RELAX_CORNERS", 8)
    before = env.module._snapshot(env.obj, env.bm)
    with pytest.raises(env.uv.BridgeError):
        env.uv.relax(env.context, arguments(face_indices=indices, **updates))
    assert env.module._snapshot(env.obj, env.bm) == before and not env.calls


@pytest.mark.parametrize("failure", ["cancel", "pause", "permission"])
def test_uv_refinement_failure_reports_actual_local_recovery(slide, monkeypatch, failure):
    env = slide
    before = env.module._snapshot(env.obj, env.bm)
    def update(*args, **kwargs):
        env.calls.append(kwargs)
        if len(env.calls) == 1:
            if failure == "cancel":
                def cancelled():
                    raise env.uv.BridgeError("TIMEOUT", "cancelled")
                env.context.check_cancelled = cancelled
            elif failure == "pause":
                env.flags["paused"] = True
            else:
                env.grants["EDIT_MESH"] = False
    monkeypatch.setattr(env.uv.bmesh, "update_edit_mesh", update)
    with pytest.raises(env.uv.BridgeError) as caught:
        env.uv.align(env.context, arguments(corners=[corner(0, 0)], axis="U", value=.125))
    assert caught.value.context["rollback_verified"] is (failure != "permission")
    assert (env.module._snapshot(env.obj, env.bm) == before) is (failure != "permission")


def test_strict_uv_refine_schemas_and_forwarding():
    hints = get_type_hints(UVRefineTools.uv_relax, include_extras=True)
    for key, value in (("face_indices", [True]), ("iterations", 51), ("strength", .6), ("max_displacement", float("nan"))):
        with pytest.raises(ValidationError):
            TypeAdapter(hints[key]).validate_python(value)
    stitch_hints = get_type_hints(UVRefineTools.uv_stitch, include_extras=True)
    with pytest.raises(ValidationError):
        TypeAdapter(stitch_hints["pairs"]).validate_python([{"source": corner(0, 0), "target": {"face_index": True, "corner_index": 1}}])
    calls = []
    async def call(method, params):
        calls.append((method, params))
    asyncio.run(UVRefineTools(NS(call=call)).uv_align("Prop", "UV", "ref", [corner(0, 0)], "U", .125))
    assert calls[0] == ("uv.align", arguments(selection_id="ref", corners=[corner(0, 0)], axis="U", value=.125))


@pytest.mark.parametrize("change", ["shared", "mesh_replaced", "locked"])
def test_uv_mutation_gate_rechecks_ownership_and_exact_edit_mesh(slide, change):
    env = slide
    checks = 0
    def check():
        nonlocal checks
        checks += 1
        if checks == 2:
            if change == "shared":
                env.obj.data.users = 2
            elif change == "mesh_replaced":
                env.obj.data = copy.copy(env.obj.data)
            else:
                env.obj.is_editable = False
    env.context.check_cancelled = check
    with pytest.raises(env.uv.BridgeError) as caught:
        env.uv.align(env.context, arguments(corners=[corner(0, 0)], axis="U", value=.125))
    assert not caught.value.context["execution_started"]
    assert env.bm.faces[0].loops[0].layers["UV"].uv == (0., 0.) and not env.calls


@pytest.mark.parametrize("change", ["shared", "mesh_replaced"])
def test_uv_recovery_refuses_new_consumers_or_replaced_data(slide, monkeypatch, change):
    env = slide
    def update(*args, **kwargs):
        env.calls.append(kwargs)
        if change == "shared":
            env.obj.data.users = 2
        else:
            env.obj.data = copy.copy(env.obj.data)
    monkeypatch.setattr(env.uv.bmesh, "update_edit_mesh", update)
    with pytest.raises(env.uv.BridgeError) as caught:
        env.uv.align(env.context, arguments(corners=[corner(0, 0)], axis="U", value=.125))
    assert caught.value.context["execution_started"] and caught.value.context["possible_mutation"]
    assert not caught.value.context["rollback_verified"]
    assert env.bm.faces[0].loops[0].layers["UV"].uv == (.125, 0.) and len(env.calls) == 1


def test_partial_uv_assignment_never_claims_no_execution(slide):
    env = slide
    original = env.bm.faces[0].loops[0].layers["UV"]
    class Partial:
        pin_uv, select, select_edge = original.pin_uv, original.select, original.select_edge
        _uv = original.uv
        @property
        def uv(self):
            return self._uv
        @uv.setter
        def uv(self, value):
            self._uv = (value[0], 42.)
            raise RuntimeError("partial native UV assignment")
    env.bm.faces[0].loops[0].layers["UV"] = Partial()
    with pytest.raises(env.uv.BridgeError) as caught:
        env.uv.align(env.context, arguments(corners=[corner(0, 0)], axis="U", value=.125))
    assert caught.value.context["execution_started"] and caught.value.context["possible_mutation"]
    assert not caught.value.context["rollback_verified"]


def test_raw_axis_enum_has_structured_error_for_unhashable_input(slide):
    env = slide
    with pytest.raises(env.uv.BridgeError) as caught:
        env.uv.align(env.context, arguments(corners=[corner(0, 0)], axis=[], value=.125))
    assert caught.value.code == "INVALID_ARGUMENT"
