from __future__ import annotations

import asyncio
import copy
import importlib
import math
from types import SimpleNamespace as NS

import pytest
from test_rig_ik import ID, Items, ik  # noqa: F401

from mcp_server.tools.deformation import TOOL_DATA, TOOL_NAMES, DeformationTools, load_definitions


class Matrix:
    def __init__(self, translation=(0., 0., 0.)):
        self.translation = translation

    def __iter__(self):
        tx, ty, tz = self.translation
        return iter(((1., 0., 0., tx), (0., 1., 0., ty), (0., 0., 1., tz), (0., 0., 0., 1.)))

    def __matmul__(self, value):
        return tuple(a+b for a, b in zip(value, self.translation, strict=True))


@pytest.fixture
def diagnostic(ik, addon_package, monkeypatch):  # noqa: F811
    module = importlib.import_module(f"{addon_package}.tools.deformation")
    module.register_tools(ik.context.registry)
    monkeypatch.setattr(module, "require_blender", lambda: ik.bpy)
    ik.bpy.context.scene.frame_current = 7
    ik.bpy.context.scene.frame_subframe = .25
    ik.bpy.context.evaluated_depsgraph_get = lambda: object()
    for obj in (ik.rig, ik.mesh, ik.target):
        obj.matrix_world = Matrix()
    for index, bone in enumerate((ik.root, ik.tip)):
        bone.bone.head_local, bone.bone.tail_local = (0., float(index), 0.), (0., float(index+1), 0.)
        for axis in "xyz":
            setattr(bone, "use_ik_limit_" + axis, axis == "x")
            setattr(bone, "ik_min_" + axis, -.5)
            setattr(bone, "ik_max_" + axis, .5)
            setattr(bone, "lock_ik_" + axis, False)
    ik.rig.data.bones = Items([ik.root.bone, ik.tip.bone, ID("Control", use_deform=False)])
    groups = Items([ID("Upper", index=0, lock_weight=False), ID("Lower", index=1, lock_weight=False),
                    ID("ProtectedDetail", index=2, lock_weight=True), ID("Control", index=3, lock_weight=False)])
    ik.mesh.vertex_groups = groups
    vertices = [NS(co=(0., 1., 0.), groups=[NS(group=0, weight=.5), NS(group=1, weight=.5), NS(group=2, weight=.25)]),
                NS(co=(1., 1., 0.), groups=[NS(group=1, weight=.5)]), NS(co=(0., 2., 0.), groups=[NS(group=2, weight=.25)])]
    edges = [NS(vertices=(0, 1)), NS(vertices=(1, 2)), NS(vertices=(2, 0))]
    faces = [NS(vertices=(0, 1, 2))]
    ik.mesh.data.shape_keys = None
    ik.mesh.data.vertices, ik.mesh.data.edges, ik.mesh.data.polygons, ik.mesh.data.loops = vertices, edges, faces, [None]*3
    ik.mesh.data.calc_loop_triangles = lambda: None
    ik.mesh.data.loop_triangles = [NS(vertices=(0, 1, 2))]
    geometry = NS(vertices=[NS(co=(vertex.co[0]+1, vertex.co[1], vertex.co[2])) for vertex in vertices], edges=list(edges), polygons=list(faces), loops=[None]*3)
    posed_root = NS(name="Upper", head=(1., 0., 0.), tail=(1., 1., 0.), parent=None)
    posed_tip = NS(name="Lower", head=(1., 1., 0.), tail=(1., 2., 0.), parent=posed_root)
    evaluated_rig = NS(pose=NS(bones=Items([posed_root, posed_tip])), matrix_world=Matrix())
    cleared = []
    evaluated_mesh = NS(to_mesh=lambda: geometry, to_mesh_clear=lambda: cleared.append(True), matrix_world=Matrix())
    ik.rig.evaluated_get = lambda graph: evaluated_rig
    ik.mesh.evaluated_get = lambda graph: evaluated_mesh
    ik.target.evaluated_get = lambda graph: ik.target
    ik.target.matrix_world = Matrix((1., 2., 0.))
    params = {"object_name": "Rig", "mesh_object": "Skin", "bone_names": ["Upper", "Lower"], "vertex_indices": [0, 1, 2],
              "coordinate_space": "WORLD", "target_object": "Target", "tip_bone_name": "Lower"}
    return NS(**{**ik.__dict__, "module": module, "params": params, "geometry": geometry, "evaluated_mesh": evaluated_mesh,
                 "evaluated_rig": evaluated_rig, "cleared": cleared})


def inspect(diagnostic, **kwargs):
    return diagnostic.module.deformation_inspect(diagnostic.context, {**diagnostic.params, **kwargs})


def test_readonly_metadata_and_wrappers_match(diagnostic):
    assert tuple(item.name for item in load_definitions()) == TOOL_NAMES
    assert tuple(item.name for item in DeformationTools(None).bindings()) == TOOL_NAMES
    name, _, modifies, permissions = TOOL_DATA[0]
    spec = diagnostic.context.registry.get(name)
    assert not modifies and not spec.modifies and {item.value for item in spec.permissions} == set(permissions)

    class Registry:
        async def call(self, tool_name, params):
            return tool_name, params

    name, params = asyncio.run(DeformationTools(Registry()).rig_deformation_inspect("Rig", "Skin", ["Lower"], [2], "LOCAL"))
    assert name == TOOL_NAMES[0] and params["coordinate_space"] == "LOCAL" and params["vertex_indices"] == [2]


def test_measures_current_frame_actual_pose_skin_weights_and_degeneracy(diagnostic):
    result = inspect(diagnostic)
    assert result["frame"] == 7 and result["subframe"] == .25
    assert all(item["displacement"] == [1., 0., 0.] for item in result["vertex_samples"])
    assert [item["deform_weight_sum"] for item in result["weights"]] == [1., .5, 0.]
    assert [item["unweighted"] for item in result["weights"]] == [False, False, True]
    assert result["weights"][0]["memberships"][2] == {"group": "ProtectedDetail", "weight": .25, "deforming": False, "locked": True}
    assert result["unmatched_groups"] == ["ProtectedDetail"] and result["nondeforming_bone_groups"] == ["Control"]
    assert result["endpoint_target"]["distance"] == 0 and result["edge_length_ratio"]["minimum"] == 1.
    assert result["bones"][1]["unsigned_parent_axis_angle_radians"] == 0
    assert result["bones"][0]["stored_ik_limits"]["x"]["enabled"]
    assert result["base_triangulation_area"]["base_total"] == result["base_triangulation_area"]["evaluated_total"] == .5
    assert result["quality_verdict"] == "NOT_ASSESSED" and diagnostic.cleared == [True]


def test_local_and_world_metrics_name_their_actual_coordinate_frames(diagnostic):
    diagnostic.mesh.matrix_world = Matrix((10., 0., 0.))
    diagnostic.evaluated_mesh.matrix_world = Matrix((10., 0., 0.))
    local = inspect(diagnostic, coordinate_space="LOCAL")
    world = inspect(diagnostic)
    assert local["geometry_coordinate_space"] == "MESH_LOCAL" and local["bone_coordinate_space"] == "ARMATURE_LOCAL"
    assert local["vertex_samples"][0]["evaluated"] == [1., 1., 0.]
    assert world["vertex_samples"][0]["evaluated"] == [11., 1., 0.]
    assert local["endpoint_target"]["coordinate_space"] == "WORLD"


def test_influence_thresholds_and_partial_weight_scope_are_observations(diagnostic):
    result = inspect(diagnostic, vertex_indices=[0], max_influences=1)
    assert not result["complete_weight_coverage"] and result["weights"][0]["exceeds_declared_influence_limit"]
    assert not result["bones"][0]["ik_limit_satisfaction_assessed"]


@pytest.mark.parametrize("changes", [{"coordinate_space": []}, {"coordinate_space": "VIEW"}, {"vertex_indices": [True]},
    {"vertex_indices": [0, 0]}, {"vertex_indices": [-1]}, {"vertex_indices": [3]}, {"vertex_indices": []},
    {"bone_names": ["missing"]}, {"bone_names": [[]]}, {"target_object": None}, {"tip_bone_name": None},
    {"max_influences": True}, {"weight_tolerance": float("nan")}, {"unexpected": True}])
def test_invalid_scope_fails_explicitly(diagnostic, changes):
    with pytest.raises(diagnostic.module.BridgeError):
        inspect(diagnostic, **changes)
    assert not diagnostic.cleared


@pytest.mark.parametrize("problem", ["shape_key", "modifier", "envelope", "preserve_volume", "masked", "disabled", "mode", "group_budget", "vertex_budget", "invalid_weight", "duplicate_weight"])
def test_unreviewed_deformation_models_and_invalid_weights_are_rejected(diagnostic, problem):
    if problem == "shape_key":
        diagnostic.mesh.data.shape_keys = object()
    elif problem == "modifier":
        diagnostic.mesh.modifiers.append(object())
    elif problem == "envelope":
        diagnostic.modifier.use_bone_envelopes = True
    elif problem == "preserve_volume":
        diagnostic.modifier.use_deform_preserve_volume = True
    elif problem == "masked":
        diagnostic.modifier.vertex_group = "Control"
    elif problem == "disabled":
        diagnostic.modifier.show_viewport = False
    elif problem == "mode":
        diagnostic.bpy.context.mode = "EDIT_MESH"
    elif problem == "group_budget":
        diagnostic.mesh.vertex_groups.extend([ID(str(index), index=index+4, lock_weight=False) for index in range(128)])
    elif problem == "vertex_budget":
        diagnostic.mesh.data.vertices.extend([diagnostic.mesh.data.vertices[0]]*4096)
    elif problem == "invalid_weight":
        diagnostic.mesh.data.vertices[0].groups[0].weight = float("nan")
    else:
        diagnostic.mesh.data.vertices[0].groups.append(NS(group=0, weight=.5))
    with pytest.raises(diagnostic.module.BridgeError):
        inspect(diagnostic)


@pytest.mark.parametrize("change", ["frame", "mesh_id", "bone_id", "weight", "permission", "cancel"])
def test_callback_revalidates_identity_current_frame_and_consent(diagnostic, change):
    def callback():
        if change == "frame":
            diagnostic.bpy.context.scene.frame_current = 8
        elif change == "mesh_id":
            diagnostic.mesh.data = copy.copy(diagnostic.mesh.data)
        elif change == "bone_id":
            diagnostic.rig.pose.bones[0] = copy.copy(diagnostic.rig.pose.bones[0])
        elif change == "weight":
            diagnostic.mesh.data.vertices[0].groups[0].weight = .7
        elif change == "permission":
            diagnostic.grants["INSPECT_SCENE"] = False
        else:
            raise diagnostic.module.BridgeError(diagnostic.module.ErrorCode.OPERATION_FAILED, "Canceled")

    diagnostic.context.check_cancelled = callback
    with pytest.raises(diagnostic.module.BridgeError):
        inspect(diagnostic)
    assert not diagnostic.cleared


@pytest.mark.parametrize("failure", ["count", "topology", "nonfinite", "pose_missing", "source_changed", "permission"])
def test_evaluated_mesh_is_always_released_on_failed_measurement(diagnostic, failure):
    if failure == "count":
        diagnostic.geometry.vertices.append(NS(co=(0, 0, 0)))
    elif failure == "topology":
        diagnostic.geometry.polygons = [NS(vertices=(0, 2, 1))]
    elif failure == "nonfinite":
        diagnostic.geometry.vertices[0].co = (float("nan"), 0, 0)
    elif failure == "pose_missing":
        diagnostic.evaluated_rig.pose.bones.clear()
    else:
        def to_mesh():
            if failure == "source_changed":
                diagnostic.mesh.data.vertices[0].co = (4, 0, 0)
            else:
                diagnostic.grants["INSPECT_SCENE"] = False
            return diagnostic.geometry
        diagnostic.evaluated_mesh.to_mesh = to_mesh
    with pytest.raises(diagnostic.module.BridgeError):
        inspect(diagnostic)
    assert diagnostic.cleared == [True]


def test_zero_length_edges_and_collapsed_triangles_are_metrics_not_quality_pass(diagnostic):
    diagnostic.geometry.vertices[1].co = diagnostic.geometry.vertices[0].co
    result = inspect(diagnostic)
    assert result["edge_length_ratio"]["degenerate_evaluated_edge_count"] == 1
    assert result["base_triangulation_area"]["degenerate_evaluated_triangle_count"] == 1
    assert result["quality_verdict"] == "NOT_ASSESSED"


def test_native_allocation_error_still_releases_evaluated_mesh(diagnostic):
    def partial():
        raise RuntimeError("to_mesh failed after native allocation")

    diagnostic.evaluated_mesh.to_mesh = partial
    with pytest.raises(RuntimeError):
        inspect(diagnostic)
    assert diagnostic.cleared == [True]


def test_release_failure_preserves_primary_structured_error(diagnostic):
    diagnostic.geometry.polygons = [NS(vertices=(0, 2, 1))]

    def failed_clear():
        raise RuntimeError("Native clear failed")

    diagnostic.evaluated_mesh.to_mesh_clear = failed_clear
    with pytest.raises(diagnostic.module.BridgeError) as error:
        inspect(diagnostic)
    assert error.value.code == "NOT_IMPLEMENTED" and "topology" in error.value.message
    assert error.value.context["evaluated_mesh_release_failed"]


def test_joint_angle_uses_declared_space_under_nonuniform_world_scale(diagnostic):
    class Scale(Matrix):
        def __iter__(self):
            return iter(((2., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.)))

        def __matmul__(self, value):
            return value[0]*2, value[1], value[2]

    diagnostic.rig.matrix_world = diagnostic.evaluated_rig.matrix_world = Scale()
    diagnostic.evaluated_rig.pose.bones[1].tail = (2., 2., 0.)
    world, local = inspect(diagnostic), inspect(diagnostic, coordinate_space="LOCAL")
    assert math.isclose(world["bones"][1]["unsigned_parent_axis_angle_radians"], math.atan2(2, 1))
    assert math.isclose(local["bones"][1]["unsigned_parent_axis_angle_radians"], math.pi/4)
