from __future__ import annotations

import asyncio
import importlib
import itertools
import struct
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from mcp_server.tools.weight_brushes import WeightBrushTools, load_definitions

IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))
_IDS = itertools.count(1)


def native_id(owner):
    owner.session_uid = next(_IDS)
    pointer = owner.session_uid * 16
    owner.as_pointer = lambda: pointer
    return owner


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
    obj = native_id(NS(name=name, type="MESH", mode="OBJECT", matrix_world=IDENTITY,
             library=None, override_library=None, is_editable=True, update_tag=lambda **kwargs: None))
    obj.data = native_id(NS(name=name + "Mesh", users=1, library=None, override_library=None, is_editable=True,
                  vertices=[NS(co=tuple(point), groups=[]) for point in positions], edges=[], polygons=[],
                  loop_triangles=[], update=lambda: None, calc_loop_triangles=lambda: None))
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
    native_context = NS(mode="OBJECT", scene=native_id(NS(frame_current=1, frame_subframe=0.)),
                        view_layer=NS(update=lambda: None))
    monkeypatch.setattr(mod, "require_blender", lambda: NS(context=native_context))
    grants = {"EDIT_MESH": True}
    flags = {"paused": False, "emergency_stopped": False}

    def require(*permissions):
        if any(not grants[p.value] for p in permissions):
            raise mod.BridgeError(mod.ErrorCode.PERMISSION_DENIED, "Denied")

    context = NS(require=require, check_cancelled=None, state=NS(snapshot=lambda: dict(flags)))
    return NS(mod=mod, target=target, source=source, context=context, grants=grants, flags=flags,
              native_context=native_context)


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


def apply_two(f, *, source=False):
    group = f.target.vertex_groups[1]
    return f.mod._apply(f.context, f.target, [(group, 1, .8), (group, 2, .9)],
                        f.source if source else None, f.mod._snapshot(f.target),
                        f.mod._snapshot(f.source) if source else None)


def updates_log(f):
    calls = []
    f.target.data.update = lambda: calls.append("mesh")
    f.target.update_tag = lambda **kwargs: calls.append("object")
    f.native_context.view_layer.update = lambda: calls.append("view_layer")
    return calls


def registered(f):
    module = importlib.import_module(f"{f.mod.__package__.rsplit('.', 1)[0]}.tool_registry")
    registry = module.ToolRegistry(enabled_toolsets=["weights"])
    f.mod.register_tools(registry)
    f.context.registry = registry
    return registry


@pytest.mark.parametrize("location", ["future", "earlier", "protected", "new_membership", "source"])
def test_manual_membership_drift_after_native_write_is_never_overwritten(fixture, location):
    f = fixture
    updates = updates_log(f)
    group = f.target.vertex_groups[1]

    def manual_edit():
        if location == "new_membership":
            f.target.data.vertices[0].groups.pop()
        elif location == "source":
            f.source.data.vertices[0].groups[1].weight = .67
        else:
            vertex, member = {"future": (2, 1), "earlier": (1, 1), "protected": (0, 2)}[location]
            f.target.data.vertices[vertex].groups[member].weight = .67

    group.after_write = manual_edit
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f, source=location == "source")
    evidence = caught.value.context["recovery_evidence"]
    assert group.calls == 1 and updates == []
    assert evidence["rollback_verified"] is False and evidence["retained_partial"] is True
    assert evidence["state_known"] is False and evidence["observed_sha256"] is None
    assert evidence["restoration_attempts"] == 0
    if location == "future":
        assert f.target.data.vertices[2].groups[1].weight == .67
    elif location == "earlier":
        assert f.target.data.vertices[1].groups[1].weight == .67
    elif location == "protected":
        assert f.target.data.vertices[0].groups[2].weight == .67
    elif location == "new_membership":
        assert len(f.target.data.vertices[0].groups) == 2
    else:
        assert f.source.data.vertices[0].groups[1].weight == .67


def test_last_permission_provider_drift_is_compared_before_first_setter(fixture):
    f = fixture
    require = f.context.require
    calls = []

    def last_provider(*permissions):
        require(*permissions)
        calls.append(1)
        if len(calls) == 4:
            f.target.data.vertices[2].groups[1].weight = .77

    f.context.require = last_provider
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    assert f.target.vertex_groups[1].calls == 0
    assert f.target.data.vertices[2].groups[1].weight == .77
    assert caught.value.context["recovery_evidence"]["restoration_attempts"] == 0


def test_failure_with_newer_manual_edit_does_not_restore_any_owned_field(fixture):
    f = fixture
    group = f.target.vertex_groups[1]
    group.fail_once_at = 2

    def manual_revision():
        if group.calls == 2:
            f.target.data.vertices[1].groups[1].weight = .61

    group.after_write = manual_revision
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    assert group.calls == 2
    assert f.target.data.vertices[1].groups[1].weight == .61
    assert f.target.data.vertices[2].groups[1].weight == .9
    assert caught.value.context["recovery_evidence"]["restoration_refused"] == "UNKNOWN_WRITE_RESULT"


def test_exact_f32_expected_result_is_independent_of_native_readback(fixture):
    f = fixture
    group = f.target.vertex_groups[1]
    expected_bits = struct.unpack("!I", struct.pack("!f", .8))[0]
    next_stored = struct.unpack("!f", struct.pack("!I", expected_bits + 1))[0]
    assert abs(next_stored - .8) < f.mod.EPS
    group.after_write = lambda: setattr(f.target.data.vertices[1].groups[1], "weight", next_stored)
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    assert group.calls == 1
    assert f.target.data.vertices[1].groups[1].weight == next_stored
    assert caught.value.context["recovery_evidence"]["owned_membership_verified"] == 0


@pytest.mark.parametrize("location", ["weight", "geometry"])
def test_signed_zero_drift_is_detected_by_stored_bits(fixture, location):
    f = fixture
    group = f.target.vertex_groups[1]

    def drift():
        if location == "weight":
            f.target.data.vertices[1].groups[0].weight = -0.
        else:
            f.target.data.vertices[0].co = (-1, -0., 0)

    group.after_write = drift
    with pytest.raises(f.mod.BridgeError):
        apply_two(f)
    assert group.calls == 1


def test_known_partial_native_write_has_exact_recovery_facts(fixture):
    f = fixture
    f.target.vertex_groups[1].fail_once_at = 2
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    facts = caught.value.context["recovery_evidence"]
    assert facts["kind"] == "weight_mutation" and facts["method"] == "weights.brush_stroke"
    assert facts["stage"] == "FAILED" and facts["state_known"] is True
    assert facts["owned_membership_attempts"] == facts["owned_membership_verified"] == 2
    assert facts["restoration_attempts"] == facts["restored_memberships"] == 2
    assert facts["native_update_attempts"] == facts["native_update_verified"] == 3
    assert facts["rollback_verified"] is True and facts["restoration_refused"] is None
    assert facts["retained_partial"] is False
    assert facts["observed_sha256"] == facts["before_sha256"] == facts["expected_sha256"]


def test_compensation_removes_only_newly_created_membership(fixture):
    f = fixture
    group = f.target.vertex_groups[1]
    f.target.data.vertices[1].groups.pop(1)
    before = f.mod._snapshot(f.target)
    group.fail_once_at = 1
    with pytest.raises(f.mod.BridgeError) as caught:
        f.mod._apply(f.context, f.target, [(group, 1, .8)], None, before, None)
    assert group.calls == 2
    assert f.mod._snapshot(f.target) == before
    assert caught.value.context["recovery_evidence"]["restored_memberships"] == 1


def test_native_no_change_return_is_not_accepted_as_success(fixture):
    f = fixture
    group = f.target.vertex_groups[1]
    group.add = lambda *_args: None
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    facts = caught.value.context["recovery_evidence"]
    assert facts["owned_membership_attempts"] == 1 and facts["owned_membership_verified"] == 0
    assert facts["rollback_verified"] is True and facts["restoration_attempts"] == 0


@pytest.mark.parametrize("loss", ["paused", "emergency_stopped", "disconnect", "reject", "deadline", "toolset", "spec", "registry"])
def test_last_provider_cannot_bypass_final_lifecycle_and_spec_gate(fixture, loss):
    f = fixture
    registry = registered(f)
    life_mod = importlib.import_module(f"{f.mod.__package__.rsplit('.', 1)[0]}.request_lifecycle")
    connection = life_mod.ConnectionLifetime()
    lifetime = life_mod.RequestLifetime(connection=connection)
    lifetime.delivered.set()
    f.context.request_lifecycle = lifetime
    require = f.context.require
    calls = []

    def provider(*permissions):
        require(*permissions)
        calls.append(1)
        if len(calls) != 4:
            return
        if loss in f.flags:
            f.flags[loss] = True
        elif loss == "disconnect":
            connection.disconnected.set()
        elif loss == "reject":
            lifetime.rejected.set()
        elif loss == "deadline":
            lifetime.delivered.clear()
            lifetime.deadline = 0.
        elif loss == "toolset":
            registry._enabled_toolsets.remove("weights")
        elif loss == "spec":
            registry._tools["weights.brush_stroke"] = replace(registry.get("weights.brush_stroke"))
        else:
            f.context.registry = NS()

    f.context.require = provider
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    assert f.target.vertex_groups[1].calls == 0
    assert caught.value.context["recovery_evidence"]["restoration_refused"] == "AUTHORITY_LOST"


def test_spec_is_retained_before_the_first_handler_permission_callback(fixture, monkeypatch):
    f = fixture
    registry = registered(f)
    require = f.context.require

    def provider(*permissions):
        require(*permissions)
        registry._tools["weights.brush_stroke"] = replace(registry.get("weights.brush_stroke"))

    f.context.require = provider
    monkeypatch.setattr(f.mod.weights, "get_object", lambda *_args, **_kwargs: pytest.fail("target read after spec loss"))
    with pytest.raises(f.mod.BridgeError, match="identity"):
        f.mod.brush_stroke(f.context, brush_args(f))


@pytest.mark.parametrize("loss", ["permission", "paused", "emergency_stopped", "disconnect", "spec"])
def test_loss_after_field_write_blocks_updates_and_compensation(fixture, loss):
    f = fixture
    registry = registered(f)
    life_mod = importlib.import_module(f"{f.mod.__package__.rsplit('.', 1)[0]}.request_lifecycle")
    connection = life_mod.ConnectionLifetime()
    f.context.request_lifecycle = life_mod.RequestLifetime(connection=connection)
    f.context.request_lifecycle.delivered.set()
    updates = updates_log(f)
    group = f.target.vertex_groups[1]

    def lose_authority():
        if loss == "permission":
            f.grants["EDIT_MESH"] = False
        elif loss in f.flags:
            f.flags[loss] = True
        elif loss == "disconnect":
            connection.disconnected.set()
        else:
            registry._tools["weights.brush_stroke"] = replace(registry.get("weights.brush_stroke"))

    group.after_write = lose_authority
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    assert group.calls == 1 and updates == []
    facts = caught.value.context["recovery_evidence"]
    assert facts["restoration_attempts"] == 0 and facts["state_known"] is False
    assert facts["observed_sha256"] is None and facts["retained_partial"] is True


@pytest.mark.parametrize("stop_before,expected", [(3, []), (4, ["mesh"]), (5, ["mesh", "object"])])
def test_each_native_update_has_a_fresh_last_provider_stop_gate(fixture, stop_before, expected):
    f = fixture
    updates = updates_log(f)
    calls = []

    def cancellation_provider():
        calls.append(1)
        if len(calls) == stop_before:
            f.flags["emergency_stopped"] = True

    f.context.check_cancelled = cancellation_provider
    group = f.target.vertex_groups[1]
    with pytest.raises(f.mod.BridgeError) as caught:
        f.mod._apply(f.context, f.target, [(group, 1, .8)], None, f.mod._snapshot(f.target), None)
    assert updates == expected and group.calls == 1
    assert caught.value.context["recovery_evidence"]["native_update_attempts"] == len(expected)


def test_manual_edit_from_native_update_is_preserved_without_cleanup(fixture):
    f = fixture
    calls = updates_log(f)

    def update():
        calls.append("mesh")
        f.target.data.vertices[2].groups[1].weight = .71

    f.target.data.update = update
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    assert calls == ["mesh"] and f.target.vertex_groups[1].calls == 2
    assert f.target.data.vertices[2].groups[1].weight == .71
    assert caught.value.context["recovery_evidence"]["restoration_attempts"] == 0


def test_known_update_failure_can_restore_owned_prefix_with_fresh_gates(fixture):
    f = fixture
    before = f.mod._snapshot(f.target)
    calls = updates_log(f)

    def fail_once():
        calls.append("mesh")
        if len(calls) == 1:
            raise RuntimeError("Injected update failure after a known no-change result")

    f.target.data.update = fail_once
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    assert f.mod._snapshot(f.target) == before
    facts = caught.value.context["recovery_evidence"]
    assert facts["rollback_verified"] is True
    assert facts["native_update_attempts"] == facts["native_update_verified"] == 4


def test_last_provider_stop_before_compensation_blocks_all_cleanup(fixture):
    f = fixture
    group = f.target.vertex_groups[1]
    group.fail_once_at = 2
    calls = []

    def provider():
        calls.append(1)
        if len(calls) == 4:
            f.flags["paused"] = True

    f.context.check_cancelled = provider
    updates = updates_log(f)
    with pytest.raises(f.mod.BridgeError) as caught:
        apply_two(f)
    assert group.calls == 2 and updates == []
    facts = caught.value.context["recovery_evidence"]
    assert facts["restoration_attempts"] == 0 and facts["rollback_verified"] is False
    assert facts["restoration_refused"] == "AUTHORITY_LOST"


def test_joint_comparison_budget_is_checked_before_first_setter(fixture, monkeypatch):
    f = fixture
    updates = updates_log(f)
    monkeypatch.setattr(f.mod, "MAX_COMPARE_VALUES", 1)
    with pytest.raises(f.mod.BridgeError, match="comparison budget"):
        apply_two(f)
    assert f.target.vertex_groups[1].calls == 0 and updates == []


def test_aggregate_polygon_corner_budget_rejects_before_building_evidence(fixture):
    f = fixture
    f.target.data.polygons = [NS(vertices=range(f.mod.MAX_SNAPSHOT_VALUES))]
    with pytest.raises(f.mod.BridgeError, match="aggregate snapshot budget"):
        f.mod.brush_stroke(f.context, brush_args(f))
    assert f.target.vertex_groups[1].calls == 0


@pytest.mark.parametrize("owner,field", [("object", "session_uid"), ("mesh", "as_pointer"), ("scene", "session_uid")])
def test_native_identity_is_required_without_python_id_fallback(fixture, owner, field):
    f = fixture
    obj = {"object": f.target, "mesh": f.target.data, "scene": f.native_context.scene}[owner]
    delattr(obj, field)
    with pytest.raises(f.mod.BridgeError, match="native"):
        f.mod.brush_stroke(f.context, brush_args(f))
    assert f.target.vertex_groups[1].calls == 0


def test_raw_context_cannot_acquire_a_new_registry_during_a_callback(fixture):
    f = fixture
    f.context.check_cancelled = lambda: setattr(f.context, "registry", NS())
    with pytest.raises(f.mod.BridgeError, match="registry identity"):
        f.mod.brush_stroke(f.context, brush_args(f))
    assert f.target.vertex_groups[1].calls == 0


def test_success_facts_are_bounded_plain_and_report_verified_storage(fixture):
    f = fixture
    facts = f.mod.brush_stroke(f.context, brush_args(f))["recovery_evidence"]
    assert facts["kind"] == "weight_mutation" and facts["stage"] == "COMPLETE"
    assert facts["owned_membership_attempts"] == facts["owned_membership_verified"] == 1
    assert facts["native_update_attempts"] == facts["native_update_verified"] == 3
    assert facts["state_known"] and not facts["retained_partial"] and not facts["possible_mutation"]
    assert facts["observed_sha256"] == facts["expected_sha256"] != facts["before_sha256"]
    assert all(value is None or type(value) in (str, int, bool) for value in facts.values())


def test_native_group_callable_is_resolved_after_the_last_provider(fixture):
    f = fixture
    old = f.target.vertex_groups[1]
    fresh = Group(f.target, "BoneR", 1)
    old.add = lambda *_args: pytest.fail("stale group callable retained across provider")
    require = f.context.require
    calls = []

    def provider(*permissions):
        require(*permissions)
        calls.append(1)
        if len(calls) == 4:
            f.target.vertex_groups[1] = fresh

    f.context.require = provider
    apply_two(f)
    assert old.calls == 0 and fresh.calls == 2


@pytest.mark.parametrize("operation", ["brush", "mirror", "transfer"])
def test_planning_uses_plain_group_descriptors_across_callbacks(fixture, operation):
    f = fixture

    class InvalidatedGroup(Group):
        invalid = False

        def __getattribute__(self, name):
            if name in {"name", "index", "add", "remove"} and object.__getattribute__(self, "invalid"):
                pytest.fail("stale planning group wrapper read after provider")
            return super().__getattribute__(name)

    old = f.target.vertex_groups[1]
    old.__class__ = InvalidatedGroup
    fresh = Group(f.target, "BoneR", 1)
    calls = []

    def provider():
        calls.append(1)
        if len(calls) == 2:
            f.target.vertex_groups[1] = fresh
            old.invalid = True

    f.context.check_cancelled = provider
    if operation == "brush":
        f.mod.brush_stroke(f.context, brush_args(f))
    elif operation == "mirror":
        f.mod.mirror_geometric(f.context, mirror_args(f))
    else:
        f.target.data.vertices[1].co = (.5, .5, 1.)
        f.mod.transfer_surface(f.context, surface_args(f))
    assert fresh.calls > 0


def test_update_callable_is_resolved_after_its_final_provider(fixture):
    f = fixture
    calls = []
    f.target.data.update = lambda: pytest.fail("stale update callable retained across provider")
    checks = []

    def provider():
        checks.append(1)
        if len(checks) == 3:
            f.target.data.update = lambda: calls.append("fresh")

    f.context.check_cancelled = provider
    group = f.target.vertex_groups[1]
    f.mod._apply(f.context, f.target, [(group, 1, .8)], None, f.mod._snapshot(f.target), None)
    assert calls == ["fresh"]


def test_combined_target_source_snapshot_budget_is_preflighted(fixture, monkeypatch):
    f = fixture
    target = f.mod._snapshot_values(f.mod._snapshot(f.target))
    source = f.mod._snapshot_values(f.mod._snapshot(f.source))
    monkeypatch.setattr(f.mod, "MAX_SNAPSHOT_VALUES", max(target, source))
    calls = []
    f.source.data.calc_loop_triangles = lambda: calls.append("triangles")
    with pytest.raises(f.mod.BridgeError, match="joint comparison budget"):
        f.mod.transfer_surface(f.context, surface_args(f))
    assert calls == [] and f.target.vertex_groups[1].calls == 0


@pytest.mark.parametrize("service", ["state", "request_lifecycle", "check_final_request", "check_final_job", "checkpoint_admission"])
def test_original_caller_services_cannot_be_replaced_by_last_provider(fixture, service):
    f = fixture
    calls = []

    def provider():
        calls.append(1)
        if len(calls) == 2:
            replacement = NS(snapshot=lambda: dict(f.flags)) if service == "state" else lambda: None
            setattr(f.context, service, replacement)

    f.context.check_cancelled = provider
    with pytest.raises(f.mod.BridgeError, match="did not complete") as caught:
        apply_two(f)
    assert f.target.vertex_groups[1].calls == 0
    assert caught.value.context["recovery_evidence"]["restoration_refused"] == "AUTHORITY_LOST"
