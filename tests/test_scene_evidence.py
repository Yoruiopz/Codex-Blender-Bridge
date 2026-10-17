from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace as NS
from typing import get_args

import pytest

from mcp_server.tools.scene import EvidenceField, SceneTools


class ID:
    def __init__(self, name, uid, **values):
        self.name = name
        self.session_uid = uid
        self.library = None
        self.__dict__.update(values)

    def as_pointer(self):
        return self.session_uid


@pytest.fixture
def evidence(addon_package):
    module = importlib.import_module(f"{addon_package}.scene_evidence")
    mesh = ID(
        "Mesh",
        3,
        is_editmode=False,
        vertices=[NS(index=0, co=[0.0, 0.0, 0.0], groups=[])],
        edges=[],
        loops=[],
        polygons=[],
        uv_layers=type("Layers", (list,), {"active_index": 0})(),
    )
    matrix = [[float(i == j) for j in range(4)] for i in range(4)]
    obj = ID(
        "Cube",
        2,
        type="MESH",
        data=mesh,
        matrix_world=matrix,
        matrix_local=matrix,
        location=[0.0] * 3,
        scale=[1.0] * 3,
        rotation_mode="XYZ",
        rotation_euler=[0.0] * 3,
        rotation_quaternion=[1.0, 0.0, 0.0, 0.0],
        rotation_axis_angle=[0.0] * 4,
        delta_location=[0.0] * 3,
        delta_scale=[1.0] * 3,
        delta_rotation_euler=[0.0] * 3,
        delta_rotation_quaternion=[1.0, 0.0, 0.0, 0.0],
        matrix_parent_inverse=matrix,
        dimensions=[0.0] * 3,
        parent=None,
        parent_type="OBJECT",
        parent_bone="",
        users_collection=[],
        hide_viewport=False,
        hide_render=False,
        hide_get=lambda: False,
        visible_get=lambda: True,
        material_slots=[],
        vertex_groups=[],
    )
    scene = ID("Scene", 1, frame_current=1, objects=[obj])
    bpy = NS(context=NS(scene=scene, view_layer=NS(name="ViewLayer", update=lambda: None)))
    return module, module.SceneEvidenceStore(), bpy, obj


def snapshot(evidence, **kwargs):
    _, store, bpy, _ = evidence
    return store.capture(bpy, {"object_names": ["Cube"], **kwargs})


def compare(evidence, before):
    return evidence[1].compare(evidence[2], {"snapshot_id": before["snapshot_id"]})


def test_same_count_geometry_change_is_detected_and_baseline_is_immutable(evidence):
    before = snapshot(evidence)
    before["state"]["objects"]["Cube"]["fields"]["mesh_geometry"]["sha256"] = "tampered"
    assert compare(evidence, before)["status"] == "unchanged_within_scope"
    evidence[3].data.vertices[0].co[0] = 0.125
    result = compare(evidence, before)
    assert result["status"] == "changed" and result["coverage_complete"]
    assert [item["field"] for item in result["changes"]] == ["mesh_geometry"]
    assert result["changes"][0]["before"]["counts"] == result["changes"][0]["after"]["counts"]
    assert result["user_goal_verified"] is False


def test_budget_exhaustion_never_reports_unchanged(evidence):
    before = snapshot(evidence, max_elements=1)
    assert not before["coverage_complete"]
    assert compare(evidence, before)["status"] == "unknown"


def test_shared_mesh_is_read_once_with_a_global_budget(evidence):
    _, store, bpy, obj = evidence
    other = ID(
        "Other",
        4,
        **{
            key: value
            for key, value in vars(obj).items()
            if key not in {"name", "session_uid", "library"}
        },
    )
    bpy.context.scene.objects.append(other)
    before = store.capture(
        bpy, {"object_names": ["Cube", "Other"], "fields": ["mesh_geometry"], "max_elements": 2}
    )
    assert before["coverage_complete"]
    assert before["state"]["elements_read"] == 2


@pytest.mark.parametrize(
    "params",
    [
        {"object_names": []},
        {"object_names": ["Cube", "Cube"]},
        {"object_names": [True]},
        {"object_names": ["x" * 64]},
        {"object_names": ["\ud800"]},
        {"fields": []},
        {"fields": ["everything"]},
        {"fields": ["uv", "uv"]},
        {"max_elements": True},
        {"max_elements": 1000001},
    ],
)
def test_invalid_scope_is_rejected(evidence, params, bridge_error):
    _, store, bpy, _ = evidence
    with pytest.raises(bridge_error):
        store.capture(bpy, {"object_names": ["Cube"], **params})
    assert not store._snapshots


def test_missing_ambiguous_or_replaced_objects_do_not_pass_preservation(evidence):
    _, _, bpy, obj = evidence
    before = snapshot(evidence)
    obj.session_uid += 100
    result = compare(evidence, before)
    assert result["status"] == "changed" and result["changes"][0]["field"] == "identity"
    bpy.context.scene.objects.clear()
    result = compare(evidence, before)
    assert result["status"] == "changed" and not result["coverage_complete"]
    bpy.context.scene.objects.extend([obj, obj])
    assert compare(evidence, before)["state"]["objects"]["Cube"]["resolution"] == "ambiguous"


def test_edit_mesh_evidence_is_explicitly_incomplete(evidence):
    evidence[3].data.is_editmode = True
    before = snapshot(evidence)
    assert not before["coverage_complete"]
    assert compare(evidence, before)["status"] == "unknown"


def test_nonfinite_transform_does_not_become_a_matching_hash(evidence):
    evidence[3].location[0] = float("nan")
    before = snapshot(evidence, fields=["transforms"])
    assert not before["coverage_complete"]
    assert compare(evidence, before)["status"] == "unknown"


def test_baseline_eviction_clear_and_context_mismatch_are_explicit(evidence, bridge_error):
    _, store, bpy, _ = evidence
    before = snapshot(evidence)
    bpy.context.view_layer.name = "Other"
    with pytest.raises(bridge_error, match="different scene or view layer"):
        compare(evidence, before)
    bpy.context.view_layer.name = "ViewLayer"
    for _ in range(8):
        latest = snapshot(evidence)
    with pytest.raises(bridge_error, match="evicted"):
        compare(evidence, before)
    store.clear()
    with pytest.raises(bridge_error, match="unknown"):
        compare(evidence, latest)


def test_cancellation_propagates_without_creating_a_baseline(evidence):
    module, store, bpy, _ = evidence
    error = module.invalid_argument("fixture cancellation")

    def cancelled():
        raise error

    with pytest.raises(type(error)) as caught:
        store.capture(bpy, {"object_names": ["Cube"]}, cancelled)
    assert caught.value is error and not store._snapshots


def test_mcp_wrappers_forward_typed_scope():
    class Registry:
        async def call(self, method, params):
            return method, params

    tools = SceneTools(Registry())
    assert asyncio.run(tools.scene_snapshot(["Cube"], ["uv"], 100)) == (
        "scene.snapshot",
        {"object_names": ["Cube"], "fields": ["uv"], "max_elements": 100},
    )
    assert asyncio.run(tools.scene_compare("snap_test")) == (
        "scene.compare",
        {"snapshot_id": "snap_test"},
    )


@pytest.fixture
def bridge_error(addon_package):
    return importlib.import_module(f"{addon_package}.errors").BridgeError


def test_schema_fields_match_addon_and_identity_gaps_remain_unknown(evidence):
    module, _, bpy, _ = evidence
    assert set(get_args(EvidenceField)) == set(module.FIELDS)
    bpy.context.scene.session_uid = None
    before = snapshot(evidence)
    assert not before["coverage_complete"] and compare(evidence, before)["status"] == "unknown"


def test_evidence_tools_have_authoritative_read_permissions(addon_package, bridge_error):
    core = importlib.import_module(f"{addon_package}.tools.core")
    registry_mod = importlib.import_module(f"{addon_package}.tool_registry")
    permission_mod = importlib.import_module(f"{addon_package}.permissions")
    registry = registry_mod.ToolRegistry()
    core.register_tools(registry)
    grants = {"INSPECT_SCENE": False}
    context = NS(
        permissions=permission_mod.PermissionManager(lambda: grants),
        state=NS(snapshot=lambda: {"paused": True, "emergency_stopped": True}),
    )
    for name in ("scene.snapshot", "scene.compare"):
        assert not registry.get(name).modifies
        with pytest.raises(bridge_error) as caught:
            registry.prepare(name, context)
        assert caught.value.code == "PERMISSION_DENIED"
    grants["INSPECT_SCENE"] = True
    assert registry.prepare("scene.snapshot", context)
    assert registry.prepare("scene.compare", context)


def test_scene_rename_retains_identity_and_reports_new_context(evidence):
    before = snapshot(evidence)
    evidence[2].context.scene.name = "Renamed Scene"
    result = compare(evidence, before)
    assert result["status"] == "unchanged_within_scope"
    assert result["before_scene"]["name"] == "Scene"
    assert result["state"]["scene"]["name"] == "Renamed Scene"


def test_comparison_budget_can_grow_without_backfilling_missing_baseline(evidence):
    _, store, bpy, obj = evidence
    before = snapshot(evidence, fields=["mesh_geometry"], max_elements=2)
    obj.data.vertices.append(NS(index=1, co=[1.0, 1.0, 1.0], groups=[]))
    assert compare(evidence, before)["status"] == "unknown"
    result = store.compare(bpy, {"snapshot_id": before["snapshot_id"], "max_elements": 3})
    assert result["status"] == "changed" and result["coverage_complete"]
    incomplete = snapshot(evidence, fields=["mesh_geometry"], max_elements=1)
    result = store.compare(bpy, {"snapshot_id": incomplete["snapshot_id"], "max_elements": 10})
    assert result["status"] == "unknown" and not result["coverage_complete"]


def test_inapplicable_mesh_fields_are_visible_to_callers(evidence):
    evidence[3].type = "LIGHT"
    before = snapshot(evidence, fields=["mesh_geometry", "uv", "weights"])
    assert all(
        value["applicable"] is False
        for value in before["state"]["objects"]["Cube"]["fields"].values()
    )


def test_unsupported_mapping_socket_values_cannot_hash_only_their_keys(evidence):
    module = evidence[0]
    with pytest.raises(module.EvidenceLimit, match="Mapping socket defaults"):
        module._small({"color": 1.0})
