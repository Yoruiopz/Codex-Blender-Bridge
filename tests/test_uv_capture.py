from __future__ import annotations

import importlib
import struct
import zlib
from types import SimpleNamespace

import pytest

from mcp_server.tools.uv import load_definitions


@pytest.fixture
def capture(addon_package, monkeypatch, tmp_path):
    module = importlib.import_module(f"{addon_package}.tools.uv_capture")
    collector = module._faces
    faces = [[(0., 0., True), (1., 0., False), (1., 1., False), (0., 1., False)]]
    monkeypatch.setattr(module, "_faces", lambda *args: ("Mesh", "UV", faces, "OBJECT_MESH_DATA"))
    path = tmp_path / "capture.png"
    monkeypatch.setattr(module, "_managed_capture_path", lambda: path)
    return module, faces, path, SimpleNamespace(check_cancelled=None, collector=collector)


def test_uv_capture_png_is_real_and_preserves_equal_axis_scale(capture):
    module, _, path, context = capture
    result = module.capture_layout(context, {"size": 256})
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (256, 256)
    length = struct.unpack(">I", data[33:37])[0]
    pixels = zlib.decompress(data[41:41 + length])
    assert len(pixels) == 256 * (256 * 3 + 1)
    assert bytes((210, 45, 55)) in pixels and bytes((30, 95, 180)) in pixels
    assert result["pinned_corners"] == 1 and not result["outside_view_corners"]
    assert result["source"] == "uv_coordinate_raster" and not result["scene_changed"]
    assert not result["render_result_replaced"] and not result["analysis_truncated"]


@pytest.mark.parametrize("extra", [{"size": 255}, {"size": 1025}, {"size": True}, {"view": []}, {"view": "bad"}, {"path": "elsewhere"}])
def test_bad_capture_parameters_do_not_create_files(capture, extra):
    module, _, path, context = capture
    with pytest.raises(Exception) as error:
        module.capture_layout(context, extra)
    assert error.value.code == "INVALID_ARGUMENT" and not path.exists()


def test_fit_handles_collapsed_uvs_and_unit_tile_reports_clipping(capture):
    module, faces, path, context = capture
    faces[:] = [[(3., 2., False), (4., 2., False), (4., 3., False)]]
    result = module.capture_layout(context, {"view": "UNIT_TILE", "size": 256})
    assert result["outside_view_corners"] == 3
    path.unlink()
    faces[:] = [[(1_000_000., 1_000_000., True)] * 3]
    fit = module.capture_layout(context, {"view": "FIT", "size": 256})
    assert not fit["outside_view_corners"]
    assert fit["view_bounds"]["max"][0] > fit["view_bounds"]["min"][0]


def test_clip_rejects_distant_segments_and_bounds_intersections(capture):
    module, _, _, _ = capture
    bounds = (0., 0., 1., 1.)
    assert module._clip((2, 2), (3, 3), bounds) is None
    assert module._clip((-1, .5), (2, .5), bounds) == (0, .5, 1, .5)


def test_canceled_capture_does_not_write_png(capture):
    module, _, path, context = capture

    def cancel():
        raise RuntimeError("canceled")

    context.check_cancelled = cancel
    with pytest.raises(RuntimeError, match="canceled"):
        module.capture_layout(context, {"size": 256})
    assert not path.exists()


def test_capture_permission_metadata(addon_package):
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    importlib.import_module(f"{addon_package}.tools.uv_capture").register_tools(registry)
    spec = registry.get("uv.capture_layout")
    definition = next(item for item in load_definitions() if item.name == spec.name)
    assert not spec.modifies and not definition.modifying
    assert {p.value for p in spec.permissions} == set(definition.required_permissions) == {"INSPECT_SCENE", "CAPTURE_VIEWPORT"}


@pytest.mark.parametrize("restriction", ["faces", "corners", "nonfinite", "large_uv", "empty", "reference_mode"])
def test_uv_data_scope_rejects_incomplete_or_invalid_evidence(capture, monkeypatch, restriction):
    module, _, path, context = capture
    monkeypatch.setattr(module, "_faces", context.collector)
    data = [SimpleNamespace(uv=(0., 0.), pin_uv=False) for _ in range(4)]
    layer = SimpleNamespace(name="UV", data=data)
    face = SimpleNamespace(loop_total=4, loop_start=0, select=True)
    obj = SimpleNamespace(name="Mesh", mode="OBJECT", data=SimpleNamespace(uv_layers={"UV": layer}, polygons=[face]))
    monkeypatch.setattr(module, "_mesh_object", lambda _: obj)
    extra = {}
    if restriction == "faces":
        monkeypatch.setattr(module, "MAX_FACES", 0)
    elif restriction == "corners":
        monkeypatch.setattr(module, "MAX_CORNERS", 3)
    elif restriction == "nonfinite":
        data[0].uv = (float("nan"), 0.)
    elif restriction == "large_uv":
        data[0].uv = (1e30, 0.)
    elif restriction == "empty":
        face.select = False
        extra["selected_only"] = True
    else:
        extra["selection_id"] = "ref"
    with pytest.raises(Exception) as error:
        module.capture_layout(context, {"object_name": "Mesh", "uv_layer": "UV", **extra})
    assert error.value.code in {"INVALID_ARGUMENT", "INVALID_SELECTION", "INVALID_MODE"} and not path.exists()


def test_raster_work_budget_prevents_file_creation(capture, monkeypatch):
    module, _, path, context = capture
    monkeypatch.setattr(module, "MAX_RASTER_STEPS", 1_000)
    with pytest.raises(Exception) as error:
        module.capture_layout(context, {"size": 256})
    assert error.value.code == "INVALID_ARGUMENT" and not path.exists()
