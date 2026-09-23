from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("seam", [False, True])
def test_uv_continuity_is_independent_of_seam_flags(addon_package, seam):
    uv = importlib.import_module(f"{addon_package}.tools.uv")
    endpoints = {0: (0.0, 0.0), 1: (1.0, 0.0)}
    faces = {0: [(5, seam, endpoints)], 1: [(5, seam, endpoints)]}
    assert uv._islands(faces) == [[0, 1]]


def test_uv_discontinuity_splits_without_seams(addon_package):
    uv = importlib.import_module(f"{addon_package}.tools.uv")
    faces = {
        0: [(5, False, {0: (0.0, 0.0), 1: (1.0, 0.0)})],
        1: [(5, False, {0: (0.0, 1.0), 1: (1.0, 1.0)})],
    }
    assert uv._islands(faces) == [[0], [1]]


def test_overlapping_disconnected_faces_remain_separate(addon_package):
    uv = importlib.import_module(f"{addon_package}.tools.uv")
    endpoints = {0: (0.0, 0.0), 1: (1.0, 0.0)}
    assert uv._islands({0: [(5, False, endpoints)], 1: [(6, False, endpoints)]}) == [[0], [1]]


def test_many_islands_are_deterministic(addon_package):
    uv = importlib.import_module(f"{addon_package}.tools.uv")
    assert uv._islands({i: [] for i in reversed(range(10_000))}) == [[i] for i in range(10_000)]


def test_nonmanifold_edges_are_not_guessed(addon_package):
    uv = importlib.import_module(f"{addon_package}.tools.uv")
    endpoints = {0: (0.0, 0.0), 1: (1.0, 0.0)}
    assert uv._islands({i: [(5, False, endpoints)] for i in range(3)}) == [[0], [1], [2]]
