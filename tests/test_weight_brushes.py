from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest

from mcp_server.tools.weight_brushes import WeightBrushTools, load_definitions

IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))


class Groups(list):
    active_index = 0

    def get(self, name):
        return next((group for group in self if group.name == name), None)


class Group:
    def __init__(self, obj, name, index, locked=False):
        self.obj, self.name, self.index, self.lock_weight = obj, name, index, locked
        self.calls = 0
        self.fail_once_at = None
        self.after_write = None

    def add(self, indices, value, mode):
        assert mode == "REPLACE"
        self.calls += 1
        for index in indices:
            groups = self.obj.data.vertices[index].groups
            old = next((member for member in groups if member.group == self.index), None)
            if old is None:
                groups.append(NS(group=self.index, weight=value))
            else:
                old.weight = value
        if self.after_write:
            self.after_write()
        if self.calls == self.fail_once_at:
            raise RuntimeError("Injected partial membership failure")

    def remove(self, indices):
        self.calls += 1
        for index in indices:
            vertex = self.obj.data.vertices[index]
            vertex.groups[:] = [member for member in vertex.groups if member.group != self.index]


def make_object(name, positions):
    obj = NS(name=name, type="MESH", mode="OBJECT", matrix_world=IDENTITY,
             library=None, override_library=None, is_editable=True, update_tag=lambda **kwargs: None)
    obj.data = NS(name=name + "Mesh", users=1, library=None, override_library=None, is_editable=True,
                  vertices=[NS(co=tuple(point), groups=[]) for point in positions], edges=[], polygons=[],
                  loop_triangles=[], update=lambda: None, calc_loop_triangles=lambda: None)
    obj.vertex_groups = Groups([Group(obj, "BoneL", 0), Group(obj, "BoneR", 1), Group(obj, "Protected", 2, True)])
    for i, vertex in enumerate(obj.data.vertices):
        vertex.groups = [NS(group=0, weight=1.0 if i == 0 else 0.0),
                         NS(group=1, weight=0.2), NS(group=2, weight=0.3)]
    return obj


@pytest.fixture
def fixture(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.weight_brushes")
    target = make_object("Target", [(-1, 0, 0), (0, 0, 0), (1, 0, 0)])
    source = make_object("Source", [(0, 0, 0), (2, 0, 0), (0, 2, 0)])
    source.data.polygons = [NS(vertices=(0, 1, 2))]
    source.data.loop_triangles = [NS(vertices=(0, 1, 2), polygon_index=0)]
    for i in (1, 2):
        source.data.vertices[i].groups[1].weight = 1.
    source.data.vertices[0].groups[1].weight = 0.
    objects = {target.name: target, source.name: source}
    monkeypatch.setattr(mod.weights, "get_object", lambda name, **kwargs: objects[name])
    monkeypatch.setattr(mod, "require_blender", lambda: NS(context=NS(view_layer=NS(update=lambda: None))))
    grants = {"EDIT_MESH": True}
    flags = {"paused": False, "emergency_stopped": False}

    def require(*permissions):
        if any(not grants[p.value] for p in permissions):
            raise mod.BridgeError(mod.ErrorCode.PERMISSION_DENIED, "Denied")

    context = NS(require=require, check_cancelled=None, state=NS(snapshot=lambda: dict(flags)))
    return NS(mod=mod, target=target, source=source, context=context, grants=grants, flags=flags)


def brush_args(fixture, **overrides):
    values = {"object_name": fixture.target.name, "group_name": "BoneR", "vertex_indices": [2],
              "coordinate_space": "LOCAL", "blend_mode": "MIX", "falloff": "CONSTANT",
              "strokes": [{"center": [1, 0, 0], "radius": 0.5, "strength": 0.5, "weight": 1.}],
              "protected_groups": ["Protected"]}
    values.update(overrides)
    return values


def mirror_args(fixture, **overrides):
    values = {"object_name": fixture.target.name, "source_vertex_indices": [0], "vertex_indices": [2],
              "group_mapping": [{"source_group": "BoneL", "target_group": "BoneR"}],
              "axis": "X", "plane_offset": 0., "coordinate_space": "LOCAL", "max_distance": 0.01}
    values.update(overrides)
    return values


def surface_args(fixture, **overrides):
    values = {"source_object": fixture.source.name, "object_name": fixture.target.name,
              "source_polygon_indices": [0], "vertex_indices": [1], "coordinate_space": "LOCAL",
              "max_distance": 2., "group_mapping": [{"source_group": "BoneL", "target_group": "BoneL"},
                                                       {"source_group": "BoneR", "target_group": "BoneR"}]}
    values.update(overrides)
    return values


def test_brush_mix_readback_preserves_all_other_memberships(fixture):
    f = fixture
    before = f.mod._snapshot(f.target)
    result = f.mod.brush_stroke(f.context, brush_args(f))
    assert f.mod._weight(f.target, f.target.vertex_groups[1], 2) == pytest.approx(0.6)
    assert f.mod._matches(before, f.mod._snapshot(f.target), {(2, 1): 0.6})
    assert result["preservation_verified"] and result["complete_membership_readback_verified"]
    assert result["normalization_performed"] is False


@pytest.mark.parametrize("blend,expected", [("ADD", .7), ("SUBTRACT", 0.)])
def test_brush_add_subtract_and_clamping(fixture, blend, expected):
    f = fixture
    f.mod.brush_stroke(f.context, brush_args(f, blend_mode=blend))
    assert f.mod._weight(f.target, f.target.vertex_groups[1], 2) == pytest.approx(expected)


@pytest.mark.parametrize("falloff", ["LINEAR", "SMOOTH"])
def test_brush_falloff_has_fixed_explicit_boundary(fixture, falloff):
    f = fixture
    args = brush_args(f, vertex_indices=[1, 2], falloff=falloff,
                      strokes=[{"center": [0, 0, 0], "radius": 1., "strength": 1., "weight": 1.}])
    f.mod.brush_stroke(f.context, args)
    assert f.mod._weight(f.target, f.target.vertex_groups[1], 1) == 1.
    assert f.mod._weight(f.target, f.target.vertex_groups[1], 2) == .2


@pytest.mark.parametrize("field,value", [
    ("coordinate_space", []), ("group_name", []), ("group_name", "Protected"),
    ("vertex_indices", [True]), ("vertex_indices", [2, 2]), ("vertex_indices", []),
    ("blend_mode", "AUTO"), ("falloff", {}), ("protected_groups", ["BoneR"]),
    ("protected_groups", ["Missing"]), ("strokes", []),
    ("strokes", [{"center": [1, 0, 0], "radius": True, "strength": 1, "weight": 1}]),
    ("strokes", [{"center": [float("nan"), 0, 0], "radius": 1, "strength": 1, "weight": 1}]),
    ("strokes", [{"center": [1, 0, 0], "radius": 1, "strength": 1, "weight": float("inf")}]),
])
def test_invalid_brush_is_structured_without_writes(fixture, field, value):
    f = fixture
    before = f.mod._snapshot(f.target)
    with pytest.raises(f.mod.BridgeError):
        f.mod.brush_stroke(f.context, brush_args(f, **{field: value}))
    assert f.mod._snapshot(f.target) == before


def test_mirror_requires_geometric_counterpart_and_mapping(fixture):
    f = fixture
    result = f.mod.mirror_geometric(f.context, mirror_args(f))
    assert f.mod._weight(f.target, f.target.vertex_groups[1], 2) == 1.
    assert result["correspondence"][0]["source_vertex_index"] == 0
    assert f.mod._weight(f.target, f.target.vertex_groups[0], 0) == 1.
    assert f.mod._weight(f.target, f.target.vertex_groups[2], 2) == .3


def test_mirror_rejects_ambiguous_duplicate_positions_before_writes(fixture):
    f = fixture
    f.target.data.vertices[1].co = (-1, 0, 0)
    before = f.mod._snapshot(f.target)
    with pytest.raises(f.mod.BridgeError, match="unambiguous"):
        f.mod.mirror_geometric(f.context, mirror_args(f, source_vertex_indices=[0, 1]))
    assert f.mod._snapshot(f.target) == before


def test_mirror_distance_failure_does_not_apply_other_matches(fixture):
    f = fixture
    f.target.data.vertices[1].co = (4, 0, 0)
    before = f.mod._snapshot(f.target)
    with pytest.raises(f.mod.BridgeError):
        f.mod.mirror_geometric(f.context, mirror_args(f, vertex_indices=[2, 1]))
    assert f.mod._snapshot(f.target) == before


def test_surface_transfer_interpolates_barycentric_weights_and_preserves_source(fixture):
    f = fixture
    f.target.data.vertices[1].co = (.5, .5, 1.)
    before = f.mod._snapshot(f.source)
    result = f.mod.transfer_surface(f.context, surface_args(f))
    assert f.mod._weight(f.target, f.target.vertex_groups[0], 1) == pytest.approx(.5)
    assert f.mod._weight(f.target, f.target.vertex_groups[1], 1) == pytest.approx(.5)
    assert result["correspondence"][0]["barycentric"] == pytest.approx([.5, .25, .25])
    assert f.mod._snapshot(f.source) == before


def test_surface_metric_uses_target_local_frame_and_world_distance(fixture):
    f = fixture
    f.target.matrix_world = ((2., 0., 0., 0.), (0., 2., 0., 0.), (0., 0., 2., 0.), IDENTITY[3])
    f.target.data.vertices[1].co = (.5, .5, 1.)
    with pytest.raises(f.mod.BridgeError, match="farther"):
        f.mod.transfer_surface(f.context, surface_args(f, coordinate_space="WORLD", max_distance=1.1))
    result = f.mod.transfer_surface(f.context, surface_args(f, coordinate_space="LOCAL", max_distance=1.1))
    assert result["correspondence"][0]["distance"] == pytest.approx(1.)


def test_surface_rejects_degenerate_triangles_and_preserves_all(fixture):
    f = fixture
    f.source.data.vertices[2].co = (4, 0, 0)
    before = f.mod._snapshot(f.target)
    with pytest.raises(f.mod.BridgeError, match="Degenerate"):
        f.mod.transfer_surface(f.context, surface_args(f))
    assert f.mod._snapshot(f.target) == before


def test_surface_rejects_equal_distance_disagreeing_source_sheets(fixture):
    f = fixture
    f.source.data.vertices += [NS(co=vertex.co, groups=[NS(group=0, weight=.8), NS(group=1, weight=.2)]) for vertex in f.source.data.vertices]
    f.source.data.polygons.append(NS(vertices=(3, 4, 5)))
    f.source.data.loop_triangles.append(NS(vertices=(3, 4, 5), polygon_index=1))
    f.target.data.vertices[1].co = (.5, .5, 0.)
    with pytest.raises(f.mod.BridgeError, match="ambiguous"):
        f.mod.transfer_surface(f.context, surface_args(f, source_polygon_indices=[0, 1]))


@pytest.mark.parametrize("point,closest,bary", [
    ((.5, .5, 1), (.5, .5, 0), (.5, .25, .25)),
    ((-1, -1, 0), (0, 0, 0), (1, 0, 0)),
    ((3, 0, 0), (2, 0, 0), (0, 1, 0)),
    ((0, 3, 0), (0, 2, 0), (0, 0, 1)),
    ((1.5, 1.5, 0), (1, 1, 0), (0, .5, .5)),
])
def test_closest_triangle_regions(fixture, point, closest, bary):
    observed, weights = fixture.mod._closest(point, (0, 0, 0), (2, 0, 0), (0, 2, 0))
    assert observed == pytest.approx(closest)
    assert weights == pytest.approx(bary)


def test_partial_native_write_is_measured_and_recovered(fixture):
    f = fixture
    before = f.mod._snapshot(f.target)
    group = f.target.vertex_groups[1]
    group.fail_once_at = 2
    with pytest.raises(f.mod.BridgeError) as caught:
        f.mod._apply(f.context, f.target, [(group, 1, .8), (group, 2, .9)], None, before, None)
    assert caught.value.context["rollback_verified"] is True
    assert caught.value.context["possible_mutation"] is False
    assert f.mod._snapshot(f.target) == before


def test_revoked_edit_permission_prevents_compensating_writes(fixture):
    f = fixture
    group = f.target.vertex_groups[1]
    group.after_write = lambda: f.grants.update(EDIT_MESH=False)
    before = f.mod._snapshot(f.target)
    with pytest.raises(f.mod.BridgeError) as caught:
        f.mod._apply(f.context, f.target, [(group, 1, .8), (group, 2, .9)], None, before, None)
    assert caught.value.code == "PERMISSION_DENIED"
    assert caught.value.context["possible_mutation"] is True
    assert group.calls == 1
    assert f.mod._weight(f.target, group, 1) == .8
    assert f.mod._weight(f.target, group, 2) == .2


@pytest.mark.parametrize("change", ["shared", "mesh_swap", "group_lock"])
def test_final_permission_callback_cannot_bypass_ownership(fixture, change):
    f = fixture
    before = f.mod._snapshot(f.target)
    group = f.target.vertex_groups[1]
    calls = []

    def check():
        calls.append(1)
        if len(calls) == 2:
            if change == "shared":
                f.target.data.users = 2
            elif change == "group_lock":
                group.lock_weight = True
            else:
                replacement = make_object("Replacement", [vertex.co for vertex in f.target.data.vertices])
                f.target.data = replacement.data

    f.context.check_cancelled = check
    with pytest.raises(f.mod.BridgeError):
        f.mod._apply(f.context, f.target, [(group, 1, .8)], None, before, None)
    assert group.calls == 0


@pytest.mark.parametrize("flag", ["paused", "emergency_stopped"])
def test_paused_or_stopped_brush_does_not_read_or_write(fixture, flag):
    f = fixture
    f.flags[flag] = True
    before = f.mod._snapshot(f.target)
    with pytest.raises(f.mod.BridgeError):
        f.mod.brush_stroke(f.context, brush_args(f))
    assert f.mod._snapshot(f.target) == before


def test_mcp_metadata_and_forwarding():
    assert {definition.name for definition in load_definitions()} == {
        "weights.brush_stroke", "weights.mirror_geometric", "weights.transfer_surface"}
    calls = []

    class Registry:
        async def call(self, name, payload):
            calls.append((name, payload))
            return payload

    tools = WeightBrushTools(Registry())
    asyncio.run(tools.weights_mirror_geometric("Actor", [0], [1], [{"source_group": "L", "target_group": "R"}], "X", 0., "LOCAL", .001))
    assert calls[0][0] == "weights.mirror_geometric"
    assert calls[0][1]["coordinate_space"] == "LOCAL" and "protected_groups" not in calls[0][1]
    assert len(tools.bindings()) == 3


def test_protected_weight_readback_has_no_numeric_tolerance(fixture):
    f = fixture
    before = f.mod._snapshot(f.target)
    f.target.data.vertices[2].groups[2].weight += 1e-8
    after = f.mod._snapshot(f.target)
    assert not f.mod._matches(before, after, {(2, 1): .2})


def test_existing_invalid_membership_is_rejected_before_edit(fixture):
    f = fixture
    f.target.data.vertices[0].groups[2].weight = float("nan")
    with pytest.raises(f.mod.BridgeError, match="existing weight"):
        f.mod.brush_stroke(f.context, brush_args(f))
    assert f.target.vertex_groups[1].calls == 0


@pytest.mark.parametrize("change", ["shared", "mesh_swap", "group_lock", "vertex_reorder"])
def test_partial_write_rollback_refuses_changed_ownership_or_geometry(fixture, change):
    f = fixture
    before = f.mod._snapshot(f.target)
    group = f.target.vertex_groups[1]
    replacement = make_object("Replacement", [vertex.co for vertex in f.target.data.vertices])
    replacement_before = f.mod._snapshot(replacement)
    calls = []

    def check():
        calls.append(1)
        if len(calls) == 3:
            if change == "shared":
                f.target.data.users = 2
            elif change == "group_lock":
                group.lock_weight = True
            elif change == "vertex_reorder":
                f.target.data.vertices[1].co = (9, 9, 9)
            else:
                f.target.data = replacement.data

    f.context.check_cancelled = check
    with pytest.raises(f.mod.BridgeError) as caught:
        f.mod._apply(f.context, f.target, [(group, 1, .8), (group, 2, .9)], None, before, None)
    assert caught.value.context["rollback_verified"] is False
    assert caught.value.context["possible_mutation"] is True
    assert group.calls == 1
    if change == "mesh_swap":
        assert f.mod._snapshot(replacement) == replacement_before
