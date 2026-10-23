"""Pure numerical oracles for the bounded character revision fixture.

These functions consume retained native observations. They do not import Blender,
production deformation code, or a third-party matrix implementation. LBS checks
skinning given evaluated bone matrices; the separate two-link oracle checks IK.
"""

from __future__ import annotations

import math
from typing import Any


def _finite_matrix(value: list[list[float]]) -> None:
    assert len(value) == 4 and all(len(row) == 4 for row in value)
    assert all(math.isfinite(item) for row in value for item in row), "Nonfinite fixture matrix"


def _finite_point(value: list[float]) -> None:
    assert len(value) == 3 and all(math.isfinite(item) for item in value), "Nonfinite fixture point"


def multiply(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    _finite_matrix(left)
    _finite_matrix(right)
    return [[sum(left[row][item] * right[item][column] for item in range(4))
             for column in range(4)] for row in range(4)]


def inverse(matrix: list[list[float]]) -> list[list[float]]:
    """Invert a finite 4x4 matrix by independently implemented pivot elimination."""
    _finite_matrix(matrix)
    rows = [[float(value) for value in row] + [float(index == column) for column in range(4)]
            for index, row in enumerate(matrix)]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda index: abs(rows[index][column]))
        assert abs(rows[pivot][column]) > 1e-12, "Singular fixture matrix"
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        rows[column] = [value / divisor for value in rows[column]]
        for index in range(4):
            if index != column:
                factor = rows[index][column]
                rows[index] = [a - factor * b for a, b in zip(rows[index], rows[column], strict=True)]
    return [row[4:] for row in rows]


def point(matrix: list[list[float]], coordinate: list[float]) -> list[float]:
    _finite_matrix(matrix)
    _finite_point(coordinate)
    values = [sum(row[column] * (*coordinate, 1.)[column] for column in range(4)) for row in matrix]
    assert abs(values[3] - 1.) < 1e-8, "Fixture transforms must be affine"
    return values[:3]


def distance(left: list[float], right: list[float]) -> float:
    _finite_point(left)
    _finite_point(right)
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def lbs_vertices(record: dict[str, Any], overrides: dict[int, dict[str, float]] | None = None) -> list[list[float]]:
    """Evaluate every rest vertex, excluding nonbone Detail from normalization."""
    rest_bones, pose_bones = record["rest_bones"], record["pose_bones"]
    mesh_to_rig = multiply(inverse(record["rig_world"]), record["mesh_world"])
    deformations = {name: multiply(pose_bones[name]["matrix"], inverse(bone["matrix"]))
                    for name, bone in rest_bones.items() if bone["use_deform"]}
    results = []
    for index, vertex in enumerate(record["vertices"]):
        _finite_point(vertex["co"])
        memberships = ({member["group"]: member["weight"] for member in vertex["memberships"]}
                       if overrides is None or index not in overrides else overrides[index])
        assert all(math.isfinite(value) and value >= 0. for value in memberships.values()), "Invalid fixture weights"
        weights = {name: value for name, value in memberships.items() if name in deformations and value > 0.}
        total = sum(weights.values())
        if total == 0.:
            results.append(point(record["mesh_world"], vertex["co"]))
            continue
        coordinate = point(mesh_to_rig, vertex["co"])
        transformed = [(value / total, point(deformations[name], coordinate)) for name, value in weights.items()]
        blended = [sum(weight * value[axis] for weight, value in transformed) for axis in range(3)]
        results.append(point(record["rig_world"], blended))
    return results


def ik_metrics(record: dict[str, Any]) -> dict[str, Any]:
    """Compare against the predeclared positive projected-pole two-link branch."""
    upper, lower = record["pose_bones"]["Upper"], record["pose_bones"]["Lower"]
    rest_upper, rest_lower = record["rest_bones"]["Upper"], record["rest_bones"]["Lower"]
    root = rest_upper["head"]
    for value in (root, rest_upper["tail"], rest_lower["head"], rest_lower["tail"],
                  upper["head"], upper["tail"], lower["head"], lower["tail"],
                  record["target_world"], record["pole_world"]):
        _finite_point(value)
    target = point(inverse(record["rig_world"]), record["target_world"])
    pole = point(inverse(record["rig_world"]), record["pole_world"])
    length_upper = distance(rest_upper["head"], rest_upper["tail"])
    length_lower = distance(rest_lower["head"], rest_lower["tail"])
    span = [target[axis] - root[axis] for axis in range(3)]
    span_length = distance(root, target)
    assert abs(length_upper - length_lower) < span_length < length_upper + length_lower
    direction = [value / span_length for value in span]
    pole_delta = [pole[axis] - root[axis] for axis in range(3)]
    projection = sum(a * b for a, b in zip(pole_delta, direction, strict=True))
    projected = [pole_delta[axis] - projection * direction[axis] for axis in range(3)]
    projected_length = distance(projected, [0., 0., 0.])
    assert projected_length > 1e-6
    bend_direction = [value / projected_length for value in projected]
    offset = (length_upper ** 2 - length_lower ** 2 + span_length ** 2) / (2. * span_length)
    height = math.sqrt(length_upper ** 2 - offset ** 2)
    center = [root[axis] + offset * direction[axis] for axis in range(3)]
    positive = [center[axis] + height * bend_direction[axis] for axis in range(3)]
    negative = [center[axis] - height * bend_direction[axis] for axis in range(3)]
    elbow_delta = [upper["tail"][axis] - center[axis] for axis in range(3)]
    normal = [direction[1] * bend_direction[2] - direction[2] * bend_direction[1],
              direction[2] * bend_direction[0] - direction[0] * bend_direction[2],
              direction[0] * bend_direction[1] - direction[1] * bend_direction[0]]
    return {
        "expected_positive_elbow": positive, "expected_negative_elbow": negative,
        "actual_elbow": upper["tail"], "root_error": distance(root, upper["head"]),
        "joint_gap": distance(upper["tail"], lower["head"]),
        "endpoint_target_distance": distance(point(record["rig_world"], lower["tail"]), record["target_world"]),
        "upper_length_error": abs(distance(upper["head"], upper["tail"]) - length_upper),
        "lower_length_error": abs(distance(lower["head"], lower["tail"]) - length_lower),
        "pole_plane_error": abs(sum(a * b for a, b in zip(elbow_delta, normal, strict=True))),
        "positive_branch_error": distance(upper["tail"], positive),
        "negative_branch_error": distance(upper["tail"], negative),
        "positive_pole_halfspace": sum(a * b for a, b in zip(elbow_delta, bend_direction, strict=True)),
        "rest_lengths": [length_upper, length_lower], "target_span": span_length,
    }


def sanity_checks() -> dict[str, float]:
    """Hand-derived constants exercise rest inverse, order, offsets and Detail."""
    identity = [[float(row == column) for column in range(4)] for row in range(4)]
    rest = [row[:] for row in identity]
    rest[1][3] = 1.
    pose = [[0., -1., 0., 0.], [1., 0., 0., 1.], [0., 0., 1., 0.], [0., 0., 0., 1.]]
    rig_world = [row[:] for row in identity]
    rig_world[0][3] = 4.
    mesh_world = [row[:] for row in rig_world]
    mesh_world[1][3] = 1.
    record = {"rig_world": rig_world, "mesh_world": mesh_world,
              "vertices": [{"co": [1., 0., 0.], "memberships": [
                  {"group": "Upper", "weight": .25}, {"group": "Lower", "weight": .75},
                  {"group": "ProtectedDetail", "weight": .125}]}],
              "rest_bones": {"Upper": {"matrix": identity, "use_deform": True},
                             "Lower": {"matrix": rest, "use_deform": True}},
              "pose_bones": {"Upper": {"matrix": identity}, "Lower": {"matrix": pose}}}
    error = distance(lbs_vertices(record)[0], [4.25, 1.75, 0.])
    record["vertices"][0]["memberships"][0]["weight"] = 1.
    record["vertices"][0]["memberships"][1]["weight"] = 3.
    normalized_error = distance(lbs_vertices(record)[0], [4.25, 1.75, 0.])
    record["vertices"][0]["memberships"] = [{"group": "ProtectedDetail", "weight": .125}]
    uninfluenced_error = distance(lbs_vertices(record)[0], [5., 1., 0.])
    assert max(error, normalized_error, uninfluenced_error) < 1e-12
    return {"pivoted_affine_lbs_error": error, "normalized_deform_only_error": normalized_error,
            "nonbone_only_passthrough_error": uninfluenced_error}
