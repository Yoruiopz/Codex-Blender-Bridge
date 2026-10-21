"""Blender-free nearest-point and affine matrix math for bounded mesh fitting."""

from __future__ import annotations

import math


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b, strict=True))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b, strict=True))


def closest_point(point, a, b, c):
    """Return closest point and barycentric weights on a nondegenerate triangle."""
    ab, ac, ap = sub(b, a), sub(c, a), sub(point, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        bary = (1., 0., 0.)
    else:
        bp = sub(point, b)
        d3, d4 = dot(ab, bp), dot(ac, bp)
        if d3 >= 0 and d4 <= d3:
            bary = (0., 1., 0.)
        else:
            vc = d1*d4-d3*d2
            if vc <= 0 and d1 >= 0 and d3 <= 0:
                v = d1/(d1-d3)
                bary = (1-v, v, 0.)
            else:
                cp = sub(point, c)
                d5, d6 = dot(ab, cp), dot(ac, cp)
                if d6 >= 0 and d5 <= d6:
                    bary = (0., 0., 1.)
                else:
                    vb = d5*d2-d1*d6
                    if vb <= 0 and d2 >= 0 and d6 <= 0:
                        w = d2/(d2-d6)
                        bary = (1-w, 0., w)
                    else:
                        va = d3*d6-d5*d4
                        if va <= 0 and d4-d3 >= 0 and d5-d6 >= 0:
                            w = (d4-d3)/((d4-d3)+(d5-d6))
                            bary = (0., 1-w, w)
                        else:
                            denominator = va+vb+vc
                            bary = (1-vb/denominator-vc/denominator, vb/denominator, vc/denominator)
    return tuple(sum(bary[i]*triangle[i] for i in range(3)) for triangle in zip(a, b, c, strict=True)), bary


def inverse(matrix):
    rows = [list(row)+[float(i == j) for j in range(4)] for i, row in enumerate(matrix)]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) <= 1e-15:
            raise ValueError("Singular matrix")
        rows[pivot], rows[column] = rows[column], rows[pivot]
        divisor = rows[column][column]
        rows[column] = [value/divisor for value in rows[column]]
        for row in range(4):
            if row != column:
                factor = rows[row][column]
                rows[row] = [a-factor*b for a, b in zip(rows[row], rows[column], strict=True)]
    result = tuple(tuple(row[4:]) for row in rows)
    if any(not math.isfinite(value) for row in result for value in row):
        raise ValueError("Non-finite inverse")
    return result


def transform(matrix, point):
    return tuple(sum(matrix[row][column]*point[column] for column in range(3))+matrix[row][3] for row in range(3))
