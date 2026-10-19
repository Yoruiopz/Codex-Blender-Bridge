"""Blender-free triangle UV metrics and budgeted positive-area intersections."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import chain

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
UV_EPSILON = 1e-12
WORLD_EPSILON = 1e-12
OVERLAP_RELATIVE_EPSILON = 1e-12


@dataclass(frozen=True)
class UVTriangle:
    index: int
    face: int
    uv: tuple[Point2, Point2, Point2]
    world: tuple[Point3, Point3, Point3]


def cross2(a: Point2, b: Point2) -> float:
    return a[0] * b[1] - a[1] * b[0]


def signed_area(points: Sequence[Point2]) -> float:
    if len(points) < 3:
        return 0.
    origin = points[0]
    return sum(cross2((points[i][0] - origin[0], points[i][1] - origin[1]),
                      (points[i + 1][0] - origin[0], points[i + 1][1] - origin[1]))
               for i in range(1, len(points) - 1)) * .5


def valid_uv(triangle: UVTriangle) -> bool:
    return all(math.isfinite(value) and abs(value) <= 1e6 for point in triangle.uv for value in point)


def triangle_metrics(triangle: UVTriangle, resolution: tuple[int, int]) -> dict:
    if not valid_uv(triangle):
        return {"valid": False, "reason": "non_finite_or_out_of_range_uv"}
    if not all(math.isfinite(value) and abs(value) <= 1e12 for point in triangle.world for value in point):
        return {"valid": False, "reason": "non_finite_or_out_of_range_world_geometry"}
    first, second, third = triangle.world
    e1 = tuple(second[i] - first[i] for i in range(3))
    e2 = tuple(third[i] - first[i] for i in range(3))
    cross = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
    twice_world_area = math.hypot(*cross)
    world_area = twice_world_area * .5
    uv_signed = signed_area(triangle.uv)
    uv_area = abs(uv_signed)
    pixel_area = uv_area * resolution[0] * resolution[1]
    result = {"valid": True, "world_area": world_area, "uv_area": uv_area,
              "uv_signed_area": uv_signed, "pixel_area": pixel_area,
              "near_zero_uv": uv_area <= UV_EPSILON, "near_zero_world": world_area <= WORLD_EPSILON,
              "mirrored": uv_signed < -UV_EPSILON,
              "density": math.sqrt(pixel_area / world_area) if world_area > WORLD_EPSILON else None,
              "sigma_min": None, "sigma_max": None, "anisotropy": None}
    if result["near_zero_world"] or result["near_zero_uv"]:
        return result
    length = math.hypot(*e1)
    along = sum(e1[i] * e2[i] for i in range(3)) / length
    height = twice_world_area / length
    a, b, c = triangle.uv
    first_pixel = ((b[0] - a[0]) * resolution[0], (b[1] - a[1]) * resolution[1])
    second_pixel = ((c[0] - a[0]) * resolution[0], (c[1] - a[1]) * resolution[1])
    j00, j10 = first_pixel[0] / length, first_pixel[1] / length
    j01, j11 = (second_pixel[0] - j00 * along) / height, (second_pixel[1] - j10 * along) / height
    # 2x2 singular values, with determinant-based small value to avoid subtraction loss.
    sigma_max = (math.hypot(j00 + j11, j10 - j01) + math.hypot(j00 - j11, j10 + j01)) * .5
    determinant = pixel_area / world_area
    sigma_min = determinant / sigma_max if sigma_max else 0.
    result.update(sigma_min=sigma_min, sigma_max=sigma_max,
                  anisotropy=max(1., sigma_max / sigma_min) if sigma_min else None)
    return result


def intersection_area(first: Sequence[Point2], second: Sequence[Point2]) -> tuple[float, float]:
    """Return intersection area and the effective absolute numerical tolerance."""
    points = [*first, *second]
    origin = (min(p[0] for p in points), min(p[1] for p in points))
    scale = max(max(p[0] for p in points) - origin[0], max(p[1] for p in points) - origin[1])
    if not scale:
        return 0., UV_EPSILON
    subject = [((p[0] - origin[0]) / scale, (p[1] - origin[1]) / scale) for p in first]
    clip = [((p[0] - origin[0]) / scale, (p[1] - origin[1]) / scale) for p in second]
    if signed_area(clip) < 0:
        clip.reverse()
    for a, b in zip(clip, clip[1:] + clip[:1], strict=True):
        if not subject:
            break
        output = []
        edge = (b[0] - a[0], b[1] - a[1])
        previous = subject[-1]
        before = cross2(edge, (previous[0] - a[0], previous[1] - a[1]))
        for point in subject:
            distance = cross2(edge, (point[0] - a[0], point[1] - a[1]))
            if (distance >= 0) != (before >= 0):
                factor = before / (before - distance)
                output.append((previous[0] + factor * (point[0] - previous[0]),
                               previous[1] + factor * (point[1] - previous[1])))
            if distance >= 0:
                output.append(point)
            previous, before = point, distance
        subject = output
    tolerance = max(UV_EPSILON, OVERLAP_RELATIVE_EPSILON * scale * scale)
    return abs(signed_area(subject)) * scale * scale, tolerance


def overlap_analysis(triangles: Sequence[UVTriangle], *, max_pair_tests: int, max_reports: int,
                     check_cancelled: Callable[[], None] | None = None) -> dict:
    eligible = []
    invalid = 0
    small = 0
    for index, triangle in enumerate(triangles):
        if index % 64 == 0 and check_cancelled:
            check_cancelled()
        if not valid_uv(triangle):
            invalid += 1
            continue
        if abs(signed_area(triangle.uv)) <= UV_EPSILON:
            small += 1
            continue
        bounds = (min(p[0] for p in triangle.uv), min(p[1] for p in triangle.uv),
                  max(p[0] for p in triangle.uv), max(p[1] for p in triangle.uv))
        eligible.append((triangle, bounds))
    # Small AABBs use a 2D grid. Large AABBs are compared directly under the same pair budget,
    # avoiding both quadratic clean-grid sweeps and unbounded large-triangle cell expansion.
    side = max(1, math.ceil(math.sqrt(len(eligible) / 4)))
    low = tuple(min((bounds[axis] for _, bounds in eligible), default=0.) for axis in range(2))
    span = tuple(max((bounds[axis + 2] for _, bounds in eligible), default=1.) - low[axis] or 1. for axis in range(2))
    cells: dict[tuple[int, int], list] = {}
    large = []
    processed = []
    tested = intersections = 0
    area_sum = 0.
    examples = []
    face_pairs = set()
    face_counts: dict[int, int] = {}
    budget_exhausted = False
    for triangle, bounds in eligible:
        minimum = tuple(max(0, min(side - 1, math.floor((bounds[axis] - low[axis]) / span[axis] * side))) for axis in range(2))
        maximum = tuple(max(0, min(side - 1, math.floor((bounds[axis + 2] - low[axis]) / span[axis] * side))) for axis in range(2))
        is_large = (maximum[0] - minimum[0] + 1) * (maximum[1] - minimum[1] + 1) > 64
        keys = [] if is_large else [(u, v) for u in range(minimum[0], maximum[0] + 1) for v in range(minimum[1], maximum[1] + 1)]
        candidates = iter(processed) if is_large else chain(large, *(cells.get(key, ()) for key in keys))
        seen = set()
        for old, box in candidates:
            if old.index in seen:
                continue
            seen.add(old.index)
            if tested >= max_pair_tests:
                budget_exhausted = True
                break
            tested += 1
            if tested % 128 == 0 and check_cancelled:
                check_cancelled()
            if any(box[axis + 2] <= bounds[axis] or bounds[axis + 2] <= box[axis] for axis in range(2)):
                continue
            area, tolerance = intersection_area(old.uv, triangle.uv)
            if area <= tolerance:
                continue
            intersections += 1
            area_sum += area
            pair = tuple(sorted((old.face, triangle.face)))
            face_pairs.add(pair)
            for face_index in set(pair):
                face_counts[face_index] = face_counts.get(face_index, 0) + 1
            if len(examples) < max_reports:
                examples.append({"faces": list(pair), "triangles": [old.index, triangle.index],
                                 "uv_area": area, "effective_area_tolerance": tolerance,
                                 "same_face": old.face == triangle.face})
        if budget_exhausted:
            break
        entry = (triangle, bounds)
        processed.append(entry)
        if is_large:
            large.append(entry)
        else:
            for key in keys:
                cells.setdefault(key, []).append(entry)
        if check_cancelled:
            check_cancelled()
    return {"complete": not budget_exhausted and not invalid, "pair_budget_exhausted": budget_exhausted,
            "pair_tests": tested, "positive_triangle_pairs": intersections, "face_pairs": len(face_pairs),
            "summed_pairwise_uv_area": area_sum, "examples": examples,
            "examples_truncated": intersections > len(examples), "invalid_uv_triangles": invalid,
            "near_zero_uv_triangles_skipped": small, "broadphase": "GRID_WITH_LARGE_AABB_FALLBACK",
            "grid_side": side, "processed_large_triangles": len(large),
            "_face_overlap_counts": face_counts,
            "absolute_area_epsilon": UV_EPSILON, "relative_pair_area_epsilon": OVERLAP_RELATIVE_EPSILON,
            "limitations": "Positive-area intersections within scope and declared tolerances. Shared edges/vertices are not overlap. Stacks may be intentional. Area sum is pairwise, not union/texture coverage; invalid or budget-limited checks are incomplete."}
