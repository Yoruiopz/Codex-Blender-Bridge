from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def fixture(addon_package, monkeypatch):
    mod = importlib.import_module(f"{addon_package}.tools.weights")
    group = NS(name="Skin", index=0, lock_weight=False)
    obj = NS(
        name="Mesh",
        vertex_groups=NS(get=lambda name: group if name == "Skin" else None),
        data=NS(
            vertices=[NS(groups=[NS(group=0, weight=1.0)]), NS(groups=[]), NS(groups=[])],
            edges=[NS(vertices=(0, 1)), NS(vertices=(1, 2))],
        ),
    )
    monkeypatch.setattr(mod, "_object", lambda *args, **kwargs: obj)
    monkeypatch.setattr(
        mod, "_apply", lambda obj, updates: {"updates": [(i, v) for _, i, v in updates]}
    )
    return mod, obj, group


def test_smooth_fixed_boundary_and_simultaneous_iterations(fixture):
    mod, _, _ = fixture
    result = mod.smooth(
        None, {"group_name": "Skin", "vertex_indices": [1], "factor": 1.0, "iterations": 3}
    )
    assert result["updates"] == [(1, 0.5)]
    assert result["boundary_vertex_count"] == 2
    result = mod.smooth(
        None, {"group_name": "Skin", "vertex_indices": [0, 1], "factor": 1.0, "iterations": 2}
    )
    assert result["updates"] == [(0, 0.5)]


@pytest.mark.parametrize("factor", [-1, 2, True, float("nan"), float("inf"), "0.5"])
def test_smooth_rejects_invalid_factor(fixture, factor):
    mod, _, _ = fixture
    with pytest.raises(mod.BridgeError) as error:
        mod.smooth(None, {"group_name": "Skin", "vertex_indices": [1], "factor": factor})
    assert error.value.code == "INVALID_ARGUMENT"


def test_smooth_isolated_vertex_and_zero_factor_are_noops(fixture):
    mod, obj, _ = fixture
    assert (
        mod.smooth(None, {"group_name": "Skin", "vertex_indices": [1], "factor": 0})["updates"]
        == []
    )
    obj.data.edges = []
    assert mod.smooth(None, {"group_name": "Skin", "vertex_indices": [0]})["updates"] == []


def test_transfer_snapshots_positional_pairs_and_absence(fixture):
    mod, _, _ = fixture
    result = mod.transfer(
        None,
        {
            "source_group": "Skin",
            "group_name": "Skin",
            "source_indices": [0, 1],
            "vertex_indices": [1, 0],
        },
    )
    assert result["updates"] == [(1, 1.0), (0, None)]
    assert not result["normalization_performed"]


@pytest.mark.parametrize("sources,targets", [([0], [1, 2]), ([0, 0], [1, 2]), ([0, 1], [2, 2])])
def test_transfer_rejects_ambiguous_mapping(fixture, sources, targets):
    mod, _, _ = fixture
    with pytest.raises(mod.BridgeError) as error:
        mod.transfer(
            None,
            {
                "source_group": "Skin",
                "group_name": "Skin",
                "source_indices": sources,
                "vertex_indices": targets,
            },
        )
    assert error.value.code == "INVALID_ARGUMENT"


def test_locked_target_and_cancellation_prevent_application(fixture, monkeypatch):
    mod, _, group = fixture
    monkeypatch.setattr(mod, "_apply", lambda *args: pytest.fail("Unexpected mutation"))
    group.lock_weight = True
    with pytest.raises(mod.BridgeError):
        mod.smooth(None, {"group_name": "Skin", "vertex_indices": [1]})
    group.lock_weight = False

    def cancel():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        mod.smooth(NS(check_cancelled=cancel), {"group_name": "Skin", "vertex_indices": [1]})
