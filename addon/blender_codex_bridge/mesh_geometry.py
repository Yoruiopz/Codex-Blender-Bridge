"""Blender-free, tolerance-declared triangle contacts with bounded broadphase work."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import chain, product

from .uv_geometry import intersection_area

Point = tuple[float, float, float]


@dataclass(frozen=True)
class MeshTriangle:
    index: int
    face: int
    vertices: tuple[int, int, int]
    points: tuple[Point, Point, Point]


def sub(a: Point, b: Point) -> Point:
    return tuple(a[i] - b[i] for i in range(3))


def dot(a: Point, b: Point) -> float:
    return sum(a[i] * b[i] for i in range(3))


def cross(a: Point, b: Point) -> Point:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def normal(points: Sequence[Point]) -> tuple[Point, float]:
    value = cross(sub(points[1], points[0]), sub(points[2], points[0]))
    length = math.hypot(*value)
    return (tuple(v / length for v in value) if length else (0., 0., 0.)), length * .5


def _chord(points: Sequence[Point], distances: Sequence[float], direction: Point, epsilon: float) -> list[float]:
    values = [dot(p, direction) for p, d in zip(points, distances, strict=True) if abs(d) <= epsilon]
    for i in range(3):
        j = (i + 1) % 3
        if distances[i] * distances[j] < 0:
            t = distances[i] / (distances[i] - distances[j])
            values.append(dot(tuple(points[i][k] + t * (points[j][k] - points[i][k]) for k in range(3)), direction))
    return values


def triangle_contact(first: MeshTriangle, second: MeshTriangle, epsilon: float) -> dict | None:
    # Pair-local coordinates avoid multiplying the world translation into plane tests.
    origin = first.points[0]
    a = [sub(p, origin) for p in first.points]
    b = [sub(p, origin) for p in second.points]
    na, area_a = normal(a)
    nb, area_b = normal(b)
    if min(area_a, area_b) <= epsilon * epsilon:
        return None
    da = [dot(sub(p, b[0]), nb) for p in a]
    db = [dot(p, na) for p in b]
    if any(min(d) > epsilon or max(d) < -epsilon for d in (da, db)):
        return None
    direction = cross(na, nb)
    sine = math.hypot(*direction)
    if sine <= 1e-8:
        if max(abs(d) for d in da + db) > epsilon:
            return {"kind": "near_parallel_ambiguous"}
        axis = max(range(3), key=lambda k: abs(na[k]))
        axes = [k for k in range(3) if k != axis]
        projected_a = [tuple(p[k] for k in axes) for p in a]
        projected_b = [tuple(p[k] for k in axes) for p in b]
        projected = projected_a + projected_b
        extent = max(max(p[k] for p in projected) - min(p[k] for p in projected) for k in range(2))
        if not extent:
            return None
        # The shared clipper's absolute epsilon is in normalized coordinates, not world
        # square units. Otherwise tiny valid assets silently inherit a fixed 1e-12 floor.
        area, numeric_tolerance = intersection_area([tuple(v / extent for v in p) for p in projected_a],
                                                    [tuple(v / extent for v in p) for p in projected_b])
        area *= extent * extent
        numeric_tolerance *= extent * extent
        tolerance = max(epsilon * epsilon, numeric_tolerance)
        if area <= tolerance:
            return None
        return {"kind": "coplanar_overlap", "projected_overlap_area": area,
                "projected_area_tolerance": tolerance, "projection_dropped_axis": axis}
    # Ordinary manifold joins share the intersection line itself. Do not skip shared-vertex
    # pairs: a fold through another face can start at their common vertex.
    if len(set(first.vertices) & set(second.vertices)) >= 2:
        return None
    direction = tuple(v / sine for v in direction)
    ca, cb = _chord(a, da, direction, epsilon), _chord(b, db, direction, epsilon)
    if not ca or not cb:
        return None
    length = min(max(ca), max(cb)) - max(min(ca), min(cb))
    if length <= epsilon:
        return None
    interior = all(min(d) < -epsilon and max(d) > epsilon for d in (da, db))
    return {"kind": "crossing" if interior else "boundary_contact", "segment_length_world": length}


def intersection_analysis(triangles: Sequence[MeshTriangle], *, epsilon: float, max_pair_tests: int,
                          max_reports: int, check_cancelled: Callable[[], None] | None = None) -> dict:
    eligible = []
    degenerate = precision_limited = 0
    degenerate_examples, precision_examples = [], []
    for i, triangle in enumerate(triangles):
        if i % 64 == 0 and check_cancelled:
            check_cancelled()
        if normal(triangle.points)[1] <= epsilon * epsilon:
            degenerate += 1
            if len(degenerate_examples) < max_reports:
                degenerate_examples.append({"triangle": triangle.index, "face": triangle.face})
            continue
        if any(math.ulp(v) > epsilon / 8 for p in triangle.points for v in p):
            precision_limited += 1
            if len(precision_examples) < max_reports:
                precision_examples.append({"triangle": triangle.index, "face": triangle.face})
        box = tuple(min(p[k] for p in triangle.points) - epsilon for k in range(3)) + tuple(
            max(p[k] for p in triangle.points) + epsilon for k in range(3))
        eligible.append((triangle, box))
    low = tuple(min((b[k] for _, b in eligible), default=0.) for k in range(3))
    span = tuple(max((b[k + 3] for _, b in eligible), default=1.) - low[k] for k in range(3))
    extent = max(span, default=1.)
    axes = [k for k in range(3) if span[k] > max(4 * epsilon, extent * 1e-8)]
    side = max(1, math.ceil((len(eligible) / 4) ** (1 / max(1, len(axes)))))
    cells: dict[tuple, list] = {}
    large, processed = [], []
    tests = 0
    counts = {"crossing": 0, "boundary_contact": 0, "coplanar_overlap": 0, "near_parallel_ambiguous": 0}
    examples = []
    face_pairs = set()
    exhausted = False
    for triangle, box in eligible:
        ranges = [range(max(0, min(side - 1, math.floor((box[k] - low[k]) / span[k] * side))),
                        max(0, min(side - 1, math.floor((box[k + 3] - low[k]) / span[k] * side))) + 1) for k in axes]
        is_large = math.prod(len(r) for r in ranges) > 64
        keys = [] if is_large else list(product(*ranges))
        candidates = iter(processed) if is_large else chain(large, *(cells.get(key, ()) for key in keys))
        seen = set()
        for previous, bounds in candidates:
            if previous.index in seen:
                continue
            seen.add(previous.index)
            if tests >= max_pair_tests:
                exhausted = True
                break
            tests += 1
            if tests % 128 == 0 and check_cancelled:
                check_cancelled()
            if any(box[k + 3] < bounds[k] or bounds[k + 3] < box[k] for k in range(3)):
                continue
            contact = triangle_contact(previous, triangle, epsilon)
            if contact is None:
                continue
            counts[contact["kind"]] += 1
            pair = tuple(sorted((previous.face, triangle.face)))
            face_pairs.add(pair)
            if len(examples) < max_reports:
                examples.append({"faces": list(pair), "triangles": [previous.index, triangle.index],
                                 "same_face": previous.face == triangle.face, **contact})
        if exhausted:
            break
        entry = (triangle, box)
        processed.append(entry)
        if is_large:
            large.append(entry)
        else:
            for key in keys:
                cells.setdefault(key, []).append(entry)
        if check_cancelled:
            check_cancelled()
    return {"complete": not exhausted and not degenerate and not precision_limited and not counts["near_parallel_ambiguous"],
            "pair_budget_exhausted": exhausted, "pair_tests": tests, "triangle_pairs": counts,
            "face_pairs": len(face_pairs), "examples": examples,
            "examples_truncated": sum(counts.values()) > len(examples),
            "near_zero_triangles_skipped": degenerate, "precision_limited_triangles": precision_limited,
            "near_zero_examples": degenerate_examples, "precision_limited_examples": precision_examples,
            "skipped_examples_truncated": degenerate > len(degenerate_examples) or precision_limited > len(precision_examples),
            "broadphase": "ADAPTIVE_GRID_WITH_LARGE_AABB_FALLBACK", "grid_side": side, "grid_axes": axes,
            "distance_tolerance_world": epsilon, "parallel_sine_tolerance": 1e-8,
            "projected_absolute_area_tolerance": epsilon * epsilon, "projected_relative_pair_area_tolerance": 1e-12,
            "limitations": "Base triangles only. Positive-length non-coplanar segments and positive-area near-coplanar overlaps within declared tolerances. Topologically shared non-coplanar edges and point-only contacts are excluded. Boundary contacts include unwelded joins/T contacts, not necessarily crossings. Not a solid boolean, clearance or evaluated-geometry certificate."}
