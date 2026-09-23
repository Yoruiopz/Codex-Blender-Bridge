from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("points,degenerate,invalid,area", [
    ([(0, 0), (1, 0), (1, 1), (0, 1)], 0, 0, 1),
    ([(0, 1), (1, 1), (1, 0), (0, 0)], 0, 0, 1),
    ([(10, 10), (11, 10), (11, 11), (10, 11)], 0, 0, 1),
    ([(0, 0), (0, 0), (0, 0)], 1, 0, 0),
    ([(0, 0), (1, 0), (2, 0)], 1, 0, 0),
    ([(0, 0), (float("nan"), 0), (1, 1)], 0, 1, 0),
    ([(0, 0), (1e300, 0), (0, 1e300)], 0, 1, 0),
])
def test_uv_quality_numeric_diagnostics(addon_package, points, degenerate, invalid, area):
    uv = importlib.import_module(f"{addon_package}.tools.uv")
    result = uv._uv_quality({0: points})
    assert result["degenerate_face_count"] == degenerate
    assert result["invalid_face_count"] == invalid
    assert result["total_absolute_signed_area"] == area
    verification = uv._verification({"quality": result})
    assert verification["user_goal_verified"] is False
    assert (verification["status"] == "needs_review") == bool(degenerate or invalid)


def test_incomplete_or_empty_uv_evidence_requires_review(addon_package):
    uv = importlib.import_module(f"{addon_package}.tools.uv")
    for analysis in ({"analysis_truncated": True}, {"quality": uv._uv_quality({})}):
        assert uv._verification(analysis)["status"] == "needs_review"
