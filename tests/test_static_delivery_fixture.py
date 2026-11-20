from __future__ import annotations

import hashlib
import json

import pytest

from scripts import blender_static_delivery_smoke as fixture

ORIGINAL = {
    "points": [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [1., 1., .25]],
    "faces": [[0, 1, 2], [1, 3, 2]],
}


def test_world_comparison_accepts_reordering_small_errors_and_vertex_splits():
    observed = {
        "points": [[1., 1., .25], [0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [1., 0., 1e-6]],
        "faces": [[0, 4, 3], [3, 2, 1]],
    }

    assert fixture.compare_geometry(ORIGINAL, observed) == {
        "maximum_world_coordinate_error": 1e-6,
        "unique_world_vertices": 4,
        "source_triangles": 2,
        "observed_vertices_with_splits": 5,
    }


def test_world_comparison_rejects_topology_change_with_identical_world_vertices():
    with pytest.raises(AssertionError, match="Triangle membership changed"):
        fixture.compare_geometry(ORIGINAL, {**ORIGINAL, "faces": [[0, 1, 3], [0, 3, 2]]})


def test_world_comparison_rejects_ambiguous_coordinate_match():
    close = [[1., 1., .25 + fixture.WORLD_TOLERANCE / 2], *ORIGINAL["points"][1:]]
    expected = {**ORIGINAL, "points": close}

    with pytest.raises(AssertionError, match="World position not uniquely represented"):
        fixture.compare_geometry(expected, expected)


def test_export_failure_summary_reports_frame_and_exact_numeric_changes_without_content():
    before = {
        "frame": [3, .25], "source_object_count": 2, "scene_object_inventory": [("Private object", 321)],
        "selection": ["Private object"], "active": "Private object", "mesh.matrix_basis": [[0.]],
    }
    after = {**before, "frame": [3, 0.], "selection": [], "active": None, "mesh.matrix_basis": [[-0.]]}

    summary = fixture.export_change_summary(before, after)

    assert summary["changed_fields"] == ["active", "frame", "mesh.matrix_basis", "selection"]
    assert summary["numeric_representation_only"] == ["mesh.matrix_basis"]
    assert summary["frame_before"] == [3, .25] and summary["frame_after"] == [3, 0.]
    assert summary["selected_count_before"] == 1 and summary["selected_count_after"] == 0
    assert "Private object" not in json.dumps(summary) and "321" not in json.dumps(summary)


def test_owned_artifact_proof_checks_complete_bytes_and_bound(tmp_path, monkeypatch):
    path = tmp_path / "static sample.glb"
    content = b"bounded artifact bytes"
    path.write_bytes(content)

    assert fixture.file_proof(path) == {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    monkeypatch.setattr(fixture, "MAX_FILE_BYTES", len(content) - 1)
    with pytest.raises(AssertionError):
        fixture.file_proof(path)


def test_artifact_proof_refuses_multiple_path_owners(tmp_path):
    path = tmp_path / "static sample.glb"
    path.write_bytes(b"bounded artifact bytes")
    alias = tmp_path / "alias.glb"
    alias.hardlink_to(path)

    with pytest.raises(AssertionError):
        fixture.file_proof(path)


@pytest.mark.parametrize("change", [{}, {"phase": "reader"}, {"completed": False}, {"process_instance": "stale"}])
def test_phase_receipt_binds_phase_completion_and_process_identity(tmp_path, change):
    record = {"phase": "writer", "completed": True, "process_instance": "4" * 32, "process_id": 700,
              "using_registered_executor_timer": True, **change}
    raw = (json.dumps(record) + "\n").encode()
    (tmp_path / "writer.json").write_bytes(raw)

    if change:
        with pytest.raises(AssertionError):
            fixture.phase_receipt(tmp_path, "writer")
    else:
        assert fixture.phase_receipt(tmp_path, "writer") == (record, hashlib.sha256(raw).hexdigest())
