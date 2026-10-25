from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addon" / "blender_codex_bridge"


def load_module(filename, name):
    spec = importlib.util.spec_from_file_location(name, ADDON / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preview = load_module("geometry_preview_dto.py", "_geometry_preview_dto_model")
worker = load_module("geometry_preview_worker.py", "_geometry_preview_worker_model")


def triangle(**kwargs):
    return preview.make_dto(
        "Requested", [(0, 0, 0), (2, 0, 0), (0, 1, 0)],
        [(0, 1), (1, 2), (2, 0)], [(0, 1, 2)], **kwargs
    )


def box(**kwargs):
    vertices = [
        (x, y, z) for x in (-1, 1) for y in (-2, 2) for z in (-0.5, 0.5)
    ]
    faces = [
        (0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
        (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3),
    ]
    edges = [(i, j) for i in range(8) for j in range(i + 1, 8) if i ^ j in {1, 2, 4}]
    return preview.make_dto("Box", vertices, edges, faces, **kwargs)


def chunk(kind, payload):
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def paeth(left, above, upper_left):
    estimate = left + above - upper_left
    distances = [abs(estimate - value) for value in (left, above, upper_left)]
    return (left, above, upper_left)[distances.index(min(distances))]


def rgba_rows():
    rows = []
    for y in range(128):
        row = bytearray()
        for x in range(128):
            alpha = 255 if 17 <= x < 83 and 31 <= y < 102 else 0
            row.extend(((3 * x + y) % 256, (x + 7 * y) % 256, (x ^ y) % 256, alpha))
        rows.append(bytes(row))
    return rows


def encoded_rows(filter_type):
    result = bytearray()
    previous = bytes(128 * 4)
    for row in rgba_rows():
        result.append(filter_type)
        for index, value in enumerate(row):
            left = row[index - 4] if index >= 4 else 0
            above = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            predictor = (0, left, above, (left + above) // 2, paeth(left, above, upper_left))[
                filter_type
            ]
            result.append((value - predictor) & 255)
        previous = row
    return bytes(result)


def png(filter_type=0, *, raw=None, width=128, height=128, depth=8, color=6, end=b""):
    header = struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, 0)
    raw = encoded_rows(filter_type) if raw is None else raw
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"") + end
    )


def test_module_import_is_standalone_without_loading_blender(monkeypatch):
    import builtins

    original = builtins.__import__

    def forbidden_blender(name, *args, **kwargs):
        if name in {"bpy", "mathutils"}:
            raise AssertionError("The standalone validator imported Blender")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbidden_blender)
    assert load_module("geometry_preview_dto.py", "_dto_import_guard").PreviewRefused.__base__ is ValueError


def test_validated_dto_is_detached_and_canonical_encoding_is_stable():
    dto = triangle()
    validated = preview.validate_dto(dto)
    assert validated == dto and validated is not dto
    before = preview.canonical(dto)
    assert type(before) is bytes and len(before) <= 2 * 1024 * 1024
    assert preview.canonical(dict(reversed(list(dto.items())))) == before
    validated.clear()
    assert preview.canonical(dto) == before


def test_validated_nested_geometry_and_transform_are_detached():
    dto = triangle()
    validated = preview.validate_dto(dto)
    validated["mesh"]["vertices"][0][0] = "0000803f"
    validated["transform"]["location"][0] = "0000803f"
    assert dto["mesh"]["vertices"][0][0] == "00000000"
    assert dto["transform"]["location"][0] == "00000000"


def test_dto_encodes_native_float32_in_little_endian_hex():
    dto = triangle(location=(1, -0.0, 0))
    assert dto["mesh"]["vertices"][1] == ["00000040", "00000000", "00000000"]
    assert dto["transform"]["location"] == ["0000803f", "00000080", "00000000"]


@pytest.mark.parametrize("container", [None, "mesh", "transform", "render"])
def test_unknown_keys_are_refused_at_each_dto_level(container):
    dto = triangle()
    target = dto if container is None else dto[container]
    target["unreviewed"] = 1
    before = copy.deepcopy(dto)
    with pytest.raises(preview.PreviewRefused):
        preview.validate_dto(dto)
    assert dto == before


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema="future_version"),
    lambda d: d.pop("mesh"),
    lambda d: d["transform"].update(rotation_mode="QUATERNION"),
    lambda d: d["transform"].update(delta_location=["00000080", "00000000", "00000000"]),
    lambda d: d["transform"].update(delta_scale=["00000040", "0000803f", "0000803f"]),
    lambda d: d["render"].update(width=True),
    lambda d: d["render"].update(samples=16),
    lambda d: d["mesh"].update(vertices=tuple(d["mesh"]["vertices"])),
])
def test_unknown_schema_shapes_delta_encodings_and_render_profiles_are_refused(change):
    dto = triangle()
    change(dto)
    with pytest.raises(preview.PreviewRefused):
        preview.validate_dto(dto)


@pytest.mark.parametrize("bits", [0, None, "0", "0000000000", "0000807f", "0000c07f", "GG000000"])
def test_encoded_values_must_be_exact_finite_float32_hex(bits):
    dto = triangle()
    dto["mesh"]["vertices"][0][0] = bits
    with pytest.raises(preview.PreviewRefused):
        preview.validate_dto(dto)


@pytest.mark.parametrize("name", ["", "x" * 256, "bad\x00name", 1, None, True])
def test_invalid_literal_names_are_refused(name):
    with pytest.raises(preview.PreviewRefused):
        preview.make_dto(name, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])


@pytest.mark.parametrize(
    "vertex",
    [(float("nan"), 0, 0), (0, float("inf"), 0), (0, 0, -float("inf")),
     (1024.1, 0, 0), (1e100, 0, 0), (10**400, 0, 0), (True, 0, 0), (0, 0), (0, 0, 0, 0)],
)
def test_nonfinite_or_unbounded_vertex_payloads_are_refused(vertex):
    with pytest.raises(preview.PreviewRefused):
        preview.make_dto("Invalid", [vertex, (1, 0, 0), (0, 1, 0)],
                         [(0, 1), (1, 2), (2, 0)], [(0, 1, 2)])


@pytest.mark.parametrize(
    "kwargs",
    [{"location": (8193, 0, 0)}, {"location": (0, float("nan"), 0)},
     {"rotation": (16 * math.pi + 0.1, 0, 0)}, {"rotation": (0, 0, float("inf"))},
     {"scale": (0, 1, 1)}, {"scale": (0.00001, 1, 1)}, {"scale": (65, 1, 1)},
     {"scale": (True, 1, 1)}, {"rotation": (0, 0)}],
)
def test_unbounded_authored_transform_is_refused(kwargs):
    with pytest.raises(preview.PreviewRefused):
        triangle(**kwargs)


@pytest.mark.parametrize("face", [(0, 1), (0, 1, 1), (0, 1, 3), (-1, 1, 2),
                                  (False, 1, 2), (0, 1, 2.0), tuple(range(65))])
def test_malformed_face_topology_is_refused(face):
    with pytest.raises(preview.PreviewRefused):
        preview.make_dto("Invalid", [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                         [(0, 1), (1, 2), (2, 0)], [face])


@pytest.mark.parametrize("edge", [(0,), (0, 0), (0, 3), (-1, 1), (False, 1), (0, 1.0)])
def test_malformed_edge_topology_is_refused(edge):
    with pytest.raises(preview.PreviewRefused):
        preview.make_dto("Invalid", [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                         [(0, 1), (1, 2), (2, 0), edge], [(0, 1, 2)])


def test_duplicate_undirected_edges_and_missing_polygon_boundary_are_refused():
    duplicate = box()
    duplicate["mesh"]["edges"].append(list(reversed(duplicate["mesh"]["edges"][0])))
    incomplete = box()
    incomplete["mesh"]["edges"].pop(0)
    for dto in (duplicate, incomplete):
        with pytest.raises(preview.PreviewRefused):
            preview.validate_dto(dto)


def test_geometry_caps_are_independent():
    vertices = [(i % 16, i // 16, 0) for i in range(513)]
    triangle_edges = [(0, 1), (1, 2), (2, 0)]
    many_edges = [(i, j) for i in range(48) for j in range(i + 1, 48)][:1025]
    cases = [
        (vertices, triangle_edges, [(0, 1, 2)]),
        (vertices[:48], many_edges, [(0, 1, 2)]),
        (vertices[:3], triangle_edges, [(0, 1, 2)] * 513),
        (vertices[:5], [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)], [(0, 1, 2, 3, 4)] * 410),
    ]
    for points, edges, faces in cases:
        with pytest.raises(preview.PreviewRefused):
            preview.make_dto("Too large", points, edges, faces)


def test_zero_span_or_subprecision_geometry_is_not_renderable():
    for vertices in [[(0, 0, 0)] * 3, [(0, 0, 0), (1e-12, 0, 0), (0, 1e-12, 0)]]:
        with pytest.raises(preview.PreviewRefused):
            preview.make_dto("Degenerate", vertices, [(0, 1), (1, 2), (2, 0)], [(0, 1, 2)])


def test_world_coordinate_limit_applies_after_authored_scale_and_location():
    with pytest.raises(preview.PreviewRefused):
        preview.make_dto(
            "Beyond world bounds", [(1024, 0, 0), (1023, 1, 0), (1023, 0, 1)],
            [(0, 1), (1, 2), (2, 0)], [(0, 1, 2)], location=(8192, 0, 0), scale=(64, 1, 1),
        )


def test_world_bounds_match_independently_known_rotated_negative_scale_box():
    dto = box(location=(7, -5, 2), rotation=(0, 0, math.pi / 2), scale=(-2, 0.5, 3))
    bounds = preview.world_bounds(dto)
    assert bounds["min"] == pytest.approx([6, -7, 0.5], abs=1e-6)
    assert bounds["max"] == pytest.approx([8, -3, 3.5], abs=1e-6)


def test_camera_fit_projects_independently_known_world_box_inside_frame():
    dto = box(location=(7, -5, 2), rotation=(0, 0, math.pi / 2), scale=(-2, 0.5, 3))
    fit = preview.camera_fit(dto)
    right, up, back = (fit[key] for key in ("right", "up", "back"))
    def dot(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))
    for vector in (right, up, back):
        assert dot(vector, vector) == pytest.approx(1)
    for first, second in ((right, up), (right, back), (up, back)):
        assert dot(first, second) == pytest.approx(0, abs=1e-12)
    assert 0 < fit["clip_start"] < fit["clip_end"]
    projected = []
    for x in (6, 8):
        for y in (-7, -3):
            for z in (0.5, 3.5):
                delta = [a - b for a, b in zip((x, y, z), fit["location"], strict=True)]
                projected.append([2 * dot(delta, axis) / fit["ortho_scale"] for axis in (right, up)])
                depth = -dot(delta, back)
                assert fit["clip_start"] < depth < fit["clip_end"]
    expected = {
        "min": [min(point[axis] for point in projected) for axis in (0, 1)],
        "max": [max(point[axis] for point in projected) for axis in (0, 1)],
    }
    actual = preview.projected_bounds(dto, fit)
    for key in ("min", "max"):
        assert actual[key] == pytest.approx(expected[key], abs=1e-6)
    assert all(-1 < value < 1 for values in actual.values() for value in values)


@pytest.mark.parametrize("filter_type", range(5))
def test_png_standard_filters_recover_known_alpha_rectangle(filter_type):
    data = png(filter_type)
    result = preview.validate_png(data)
    assert result["width"] == result["height"] == 128
    assert result["foreground_pixels"] == 66 * 71
    assert result["alpha_bbox"] == [17, 31, 82, 101]
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    "data",
    [b"", b"not PNG", png()[:-1], png(end=b"trailing"),
     png(width=127), png(height=129), png(depth=16), png(color=2),
     png(raw=b"\x05" + bytes(128 * 4) + encoded_rows(0)[513:]),
     png(raw=bytes(129 * 513)), png(raw=bytes(10_000_000))],
)
def test_png_rejects_malformed_format_filters_and_decompression_bombs(data):
    with pytest.raises(preview.PreviewRefused):
        preview.validate_png(data)


def test_png_crc_and_required_chunk_order_are_enforced():
    damaged = bytearray(png())
    damaged[-5] ^= 1
    reordered = b"\x89PNG\r\n\x1a\n" + chunk(b"IDAT", zlib.compress(encoded_rows(0)))
    reordered += chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 6, 0, 0, 0))
    reordered += chunk(b"IEND", b"")
    for data in (bytes(damaged), reordered):
        with pytest.raises(preview.PreviewRefused):
            preview.validate_png(data)


def test_png_alpha_threshold_and_inclusive_bounds_use_decoded_pixels():
    raw = bytearray(128 * 513)
    raw[20 * 513 + 1 + 10 * 4 + 3] = 127
    raw[50 * 513 + 1 + 40 * 4 + 3] = 128
    result = preview.validate_png(png(raw=raw))
    assert result["foreground_pixels"] == 1
    assert result["alpha_bbox"] == [40, 50, 40, 50]
    assert result["visual_review_performed"] is False


def test_png_empty_or_clipped_alpha_refuses_without_inventing_visual_success():
    for opaque in (False, True):
        raw = bytearray(128 * 513)
        if opaque:
            raw[50 * 513 + 1 + 3] = 255
        with pytest.raises(preview.PreviewRefused):
            preview.validate_png(png(raw=raw))


def test_png_compressed_stream_cannot_hide_trailing_members_or_truncation():
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 6, 0, 0, 0))
    compressed = zlib.compress(encoded_rows(0))
    for payload in (compressed + zlib.compress(b"hidden"), compressed[:-2], b"bad zlib"):
        data = b"\x89PNG\r\n\x1a\n" + header + chunk(b"IDAT", payload) + chunk(b"IEND", b"")
        with pytest.raises(preview.PreviewRefused):
            preview.validate_png(data)


TOKEN = "ab" * 16


def native_model(**changes):
    app = NS(background=True, version_string="4.5.14 LTS", build_hash=b"62c1db4208e8")
    data = NS(filepath="")
    for key, value in changes.items():
        setattr(data if key == "filepath" else app, key, value)
    return NS(app=app, data=data)


def private_bundle(tmp_path):
    folder = tmp_path / "Owned preview with spaces"
    folder.mkdir(mode=0o700)
    path = folder / "dto.json"
    path.write_bytes(preview.canonical(triangle()))
    path.chmod(0o600)
    return folder


def test_worker_standalone_import_does_not_load_blender_register_or_launch(monkeypatch):
    import builtins
    import subprocess

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in {"bpy", "mathutils", "blender_codex_bridge"} or name.startswith("scripts"):
            raise AssertionError("Worker import entered native or research code")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("Worker launched a child"))
    module = load_module("geometry_preview_worker.py", "_worker_import_guard")
    assert module.WORKER_SCHEMA == "geometry_preview_worker_v1"
    assert callable(module.main) and callable(module.run_bundle)


@pytest.mark.parametrize("token", ["", "A" * 32, "x" * 32, "a" * 31, "a" * 33, None, 1])
def test_worker_requires_exact_random_token_before_private_work(tmp_path, token):
    folder = private_bundle(tmp_path)
    with pytest.raises(worker.PreviewRefused):
        worker.validate_bundle(folder, token)
    assert {p.name for p in folder.iterdir()} == {"dto.json"}


@pytest.mark.parametrize("kind", ["relative", "missing", "symlink", "permissions", "file"])
def test_worker_refuses_borrowed_or_noncanonical_bundle_paths(tmp_path, kind):
    folder = private_bundle(tmp_path)
    if kind == "relative":
        candidate = Path(folder.name)
    elif kind == "missing":
        candidate = tmp_path / "missing"
    elif kind == "symlink":
        candidate = tmp_path / "linked"
        candidate.symlink_to(folder, target_is_directory=True)
    elif kind == "permissions":
        folder.chmod(0o755)
        candidate = folder
    else:
        candidate = folder / "dto.json"
    with pytest.raises(worker.PreviewRefused):
        worker.validate_bundle(candidate, TOKEN)


def test_worker_bundle_must_belong_to_current_user(tmp_path, monkeypatch):
    folder = private_bundle(tmp_path)
    wrong_uid = folder.stat().st_uid + 1
    monkeypatch.setattr(worker.os, "getuid", lambda: wrong_uid)
    with pytest.raises(worker.PreviewRefused):
        worker.validate_bundle(folder, TOKEN)


def test_worker_dto_read_is_canonical_and_digest_binds_exact_bytes(tmp_path):
    folder = private_bundle(tmp_path)
    value, digest = worker.read_dto(folder)
    assert value == triangle()
    assert digest == hashlib.sha256((folder / "dto.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("kind", ["whitespace", "duplicate", "invalid_json", "too_large", "permissions", "link", "hardlink"])
def test_worker_rejects_unsafe_input_without_running_renderer(tmp_path, kind, monkeypatch):
    folder = private_bundle(tmp_path)
    path = folder / "dto.json"
    if kind == "whitespace":
        path.write_bytes(path.read_bytes() + b"\n")
    elif kind == "duplicate":
        raw = path.read_bytes()
        path.write_bytes(b'{"schema":"ignored",' + raw[1:])
    elif kind == "invalid_json":
        path.write_bytes(b"invalid JSON")
    elif kind == "too_large":
        path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    elif kind == "permissions":
        path.chmod(0o644)
    elif kind == "link":
        original = folder / "original"
        path.rename(original)
        path.symlink_to(original)
    else:
        import os

        os.link(path, folder / "second-link")
    monkeypatch.setattr(worker, "render_worker", lambda *_a: pytest.fail("Unsafe DTO reached renderer"))
    result = worker.run_bundle(native_model(), folder, TOKEN)
    assert result["status"] == "failed" and result["dto_sha256"] is None
    assert result["error"]["code"] == "GEOMETRY_PREVIEW_WORKER_FAILED"
    assert result["error"]["type"] == "PreviewRefused"
    assert (folder / "worker.json").stat().st_size <= 64 * 1024
    assert not (folder / "preview.png").exists()


@pytest.mark.parametrize("changes", [{"background": False}, {"filepath": "/artist/work.blend"},
                                     {"build_hash": "not bytes"}, {"build_hash": b"not-a-build"},
                                     {"version_string": ""}])
def test_worker_refuses_wrong_runtime_before_creating_any_output(tmp_path, changes):
    folder = private_bundle(tmp_path)
    with pytest.raises(worker.PreviewRefused):
        worker.run_bundle(native_model(**changes), folder, TOKEN)
    assert {p.name for p in folder.iterdir()} == {"dto.json"}


def test_worker_success_receipt_binds_identity_and_bounded_render_evidence(tmp_path, monkeypatch):
    folder = private_bundle(tmp_path)
    image = png()

    def fake_render(_bpy, dto, output):
        output.write_bytes(image)
        return {"input_sha256": hashlib.sha256(preview.canonical(dto)).hexdigest(),
                "geometry_reconstructed": True, "raw_channels_reconstructed": True,
                "world_bounds": preview.world_bounds(dto), "camera_fit": preview.camera_fit(dto),
                "projected_bounds": preview.projected_bounds(dto, preview.camera_fit(dto)),
                "png": preview.validate_png(image), "render_engine": "CYCLES", "device": "CPU",
                "samples": 8, "source_process_contacted": False, "source_restore_writes": 0,
                "original_material_appearance_copied": False, "project_saved": False}

    monkeypatch.setattr(worker, "render_worker", fake_render)
    result = worker.run_bundle(native_model(), folder, TOKEN)
    raw = (folder / "worker.json").read_bytes()
    assert result == json.loads(raw) and raw == preview.canonical(result)
    assert len(raw) <= 64 * 1024
    assert result["schema"] == "geometry_preview_worker_v1" and result["status"] == "succeeded"
    assert result["token"] == TOKEN and type(result["process_id"]) is int and result["process_id"] > 0
    assert result["dto_sha256"] == hashlib.sha256((folder / "dto.json").read_bytes()).hexdigest()
    assert result["build_hash"] == "62c1db4208e8" and result["blender_version"] == "4.5.14 LTS"
    assert result["png"]["sha256"] == hashlib.sha256(image).hexdigest()
    assert (folder / "worker.json").stat().st_mode & 0o777 == 0o600
    assert (folder / "preview.png").stat().st_mode & 0o777 == 0o600
    timings = result["timings"]
    assert timings["clock"] == "time.monotonic" and timings["scope"] == "worker_process"
    assert 0 <= timings["render_and_validation_seconds"] <= timings["worker_elapsed_seconds"]
    assert result["peak_memory"]["scope"] == "RUSAGE_SELF"


def test_worker_injected_render_failure_is_bounded_and_never_a_success(tmp_path, monkeypatch):
    folder = private_bundle(tmp_path)

    def fail(_bpy, _dto, _path):
        raise RuntimeError("local detail that must not enter the receipt" * 1000)

    monkeypatch.setattr(worker, "render_worker", fail)
    result = worker.run_bundle(native_model(), folder, TOKEN)
    assert result["status"] == "failed" and result["dto_sha256"] is not None
    assert result["error"] == {"code": "GEOMETRY_PREVIEW_WORKER_FAILED", "type": "RuntimeError"}
    assert b"local detail" not in (folder / "worker.json").read_bytes()
    assert result["timings"]["render_and_validation_seconds"] is not None


@pytest.mark.parametrize("name", ["worker.json", "preview.png"])
def test_worker_does_not_overwrite_existing_declared_outputs(tmp_path, name):
    folder = private_bundle(tmp_path)
    existing = folder / name
    existing.write_bytes(b"retained")
    with pytest.raises(worker.PreviewRefused):
        worker.run_bundle(native_model(), folder, TOKEN)
    assert existing.read_bytes() == b"retained"


def test_worker_receipt_byte_budget_is_checked_before_open(tmp_path):
    folder = private_bundle(tmp_path)
    with pytest.raises(worker.PreviewRefused):
        worker._write_receipt(folder, {"oversized": "x" * (64 * 1024)})
    assert not (folder / "worker.json").exists()


def test_peak_memory_labels_only_linux_self_usage_and_its_native_units(monkeypatch):
    monkeypatch.setattr(worker.sys, "platform", "linux")
    metrics = worker._peak_memory()
    assert metrics["available"] is True and metrics["unit"] == "KiB"
    assert metrics["metric"] == "ru_maxrss" and metrics["scope"] == "RUSAGE_SELF"
    assert type(metrics["value"]) is int and metrics["value"] >= 0
    monkeypatch.setattr(worker.sys, "platform", "unsupported")
    metrics = worker._peak_memory()
    assert metrics["available"] is False and metrics["value"] is None and metrics["unit"] is None


def test_worker_cli_rejects_missing_factory_flags_before_importing_blender(tmp_path, monkeypatch):
    folder = private_bundle(tmp_path)
    monkeypatch.setattr(worker.sys, "argv", ["blender"])
    with pytest.raises(worker.PreviewRefused):
        worker.main(["--bundle", str(folder), "--token", TOKEN])
    assert not (folder / "worker.json").exists()


def test_worker_cli_has_no_script_or_output_override_option(tmp_path):
    folder = private_bundle(tmp_path)
    with pytest.raises(SystemExit) as error:
        worker.main(["--bundle", str(folder), "--token", TOKEN, "--script", "untrusted.py"])
    assert error.value.code == 2


def test_renderer_refuses_interactive_source_before_native_import(tmp_path):
    folder = private_bundle(tmp_path)
    with pytest.raises(worker.PreviewRefused):
        worker.render_worker(native_model(background=False), triangle(), folder / "preview.png")
    assert not (folder / "preview.png").exists()



@pytest.fixture
def source(addon_package):
    return importlib.import_module(f"{addon_package}.geometry_preview_source")


def model_native_capture():
    """RNA descriptor model; this does not demonstrate actual Blender getter purity."""
    events = []

    def native_class(name, fields, **namespace):
        properties = {
            field: NS(identifier=field, type=kind, array_length=length, is_runtime=False)
            for field, (kind, length) in fields.items()
        }
        return type(name, (), {"bl_rna": NS(identifier=name, properties=properties), **namespace})

    def coordinate(self):
        events.append("coordinate")
        return self.value

    vertex_type = native_class("MeshVertex", {"co": ("FLOAT", 3)}, co=property(coordinate))
    edge_type = native_class("MeshEdge", {"vertices": ("INT", 2)})
    polygon_type = native_class("MeshPolygon", {"vertices": ("INT", 3)})
    mesh_type = native_class("Mesh", {
        "library": ("POINTER", None), "override_library": ("POINTER", None),
        "animation_data": ("POINTER", None), "shape_keys": ("POINTER", None),
        "is_editmode": ("BOOLEAN", 0), "users": ("INT", 0),
        "vertices": ("COLLECTION", None), "edges": ("COLLECTION", None),
        "polygons": ("COLLECTION", None),
    })
    object_type = native_class("Object", {
        "name": ("STRING", None), "type": ("ENUM", None), "mode": ("ENUM", None),
        "data": ("POINTER", None), "library": ("POINTER", None),
        "override_library": ("POINTER", None), "parent": ("POINTER", None),
        "modifiers": ("COLLECTION", None), "constraints": ("COLLECTION", None),
        "animation_data": ("POINTER", None), "rotation_mode": ("ENUM", None),
        "location": ("FLOAT", 3), "rotation_euler": ("FLOAT", 3), "scale": ("FLOAT", 3),
        "delta_location": ("FLOAT", 3), "delta_rotation_euler": ("FLOAT", 3),
        "delta_rotation_quaternion": ("FLOAT", 4), "delta_scale": ("FLOAT", 3),
    })
    vertices = []
    for point in [(0, 0, 0), (2, 0, 0), (0, 1, 0)]:
        vertex = vertex_type()
        vertex.value = point
        vertices.append(vertex)
    edges = []
    for indices in [(0, 1), (1, 2), (2, 0)]:
        edge = edge_type()
        edge.vertices = indices
        edges.append(edge)
    polygon = polygon_type()
    polygon.vertices = (0, 1, 2)
    mesh = mesh_type()
    mesh.__dict__.update(library=None, override_library=None, animation_data=None, shape_keys=None,
                         is_editmode=False, users=1, vertices=vertices, edges=edges, polygons=[polygon])
    obj = object_type()
    obj.__dict__.update(name="Requested", type="MESH", mode="OBJECT", data=mesh, library=None,
                        override_library=None, parent=None, modifiers=[], constraints=[],
                        animation_data=None, rotation_mode="XYZ", location=(0, 0, 0),
                        rotation_euler=(0, 0, 0), scale=(1, 1, 1), delta_location=(0, 0, 0),
                        delta_rotation_euler=(0, 0, 0), delta_rotation_quaternion=(1, 0, 0, 0),
                        delta_scale=(1, 1, 1))

    class BpyModel:
        @property
        def context(self):
            raise AssertionError("Capture read active Blender context")

    bpy = BpyModel()
    bpy.data = NS(objects={"Requested": obj})
    bpy.types = NS(Object=object_type, Mesh=mesh_type, MeshVertex=vertex_type,
                   MeshEdge=edge_type, MeshPolygon=polygon_type)
    return bpy, obj, mesh, events


def test_capture_model_reads_only_admitted_named_geometry(source):
    bpy, _obj, _mesh, events = model_native_capture()
    assert source.capture(bpy, "Requested") == triangle()
    assert events == ["coordinate"] * 3


def test_static_polygon_descriptor_length_three_allows_dynamic_quad_instance(source):
    bpy, _obj, mesh, events = model_native_capture()
    vertex = bpy.types.MeshVertex()
    vertex.value = (2, 1, 0)
    mesh.vertices.append(vertex)
    mesh.polygons[0].vertices = (0, 1, 3, 2)
    mesh.edges = []
    for indices in ((0, 1), (1, 3), (3, 2), (2, 0)):
        edge = bpy.types.MeshEdge()
        edge.vertices = indices
        mesh.edges.append(edge)
    dto = source.capture(bpy, "Requested")
    assert dto["mesh"]["polygons"] == [[0, 1, 3, 2]]
    assert len(events) == 4


@pytest.mark.parametrize("owner,field,value", [
    ("object", "mode", "EDIT"), ("object", "library", object()),
    ("object", "override_library", object()), ("object", "parent", object()),
    ("object", "animation_data", object()), ("object", "rotation_mode", "QUATERNION"),
    ("object", "modifiers", [object()]), ("object", "constraints", [object()]),
    ("object", "delta_location", (0.25, 0, 0)),
    ("object", "delta_location", (-0.0, 0, 0)),
    ("object", "delta_rotation_quaternion", (0, 1, 0, 0)),
    ("object", "data", None), ("mesh", "is_editmode", True),
    ("mesh", "users", 2), ("mesh", "users", 0),
    ("mesh", "animation_data", object()), ("mesh", "shape_keys", object()),
    ("mesh", "library", object()), ("mesh", "override_library", object()),
])
def test_capture_profile_refusal_precedes_coordinate_getter(owner, field, value, source):
    bpy, obj, mesh, events = model_native_capture()
    setattr(obj if owner == "object" else mesh, field, value)
    with pytest.raises(source.PreviewRefused):
        source.capture(bpy, "Requested")
    assert events == []


@pytest.mark.parametrize("family,field", [("Object", "location"), ("Object", "data"),
                                         ("Mesh", "vertices"), ("MeshVertex", "co"),
                                         ("MeshEdge", "vertices"), ("MeshPolygon", "vertices")])
def test_runtime_rna_descriptor_refusal_precedes_coordinate_getter(family, field, source):
    bpy, _obj, _mesh, events = model_native_capture()
    getattr(bpy.types, family).bl_rna.properties[field].is_runtime = True
    with pytest.raises(source.PreviewRefused):
        source.capture(bpy, "Requested")
    assert events == []


@pytest.mark.parametrize("change", ["class", "identifier", "numeric_shape", "missing_descriptor",
                                    "polygon_descriptor_shape"])
def test_capture_refuses_changed_native_class_or_descriptor_before_coordinates(change, source):
    bpy, obj, _mesh, events = model_native_capture()
    if change == "class":
        obj.__class__ = type("InjectedObject", (bpy.types.Object,), {})
    elif change == "identifier":
        bpy.types.Object.bl_rna.identifier = "InjectedObject"
    elif change == "numeric_shape":
        bpy.types.MeshVertex.bl_rna.properties["co"].array_length = 2
    elif change == "polygon_descriptor_shape":
        bpy.types.MeshPolygon.bl_rna.properties["vertices"].array_length = 0
    else:
        del bpy.types.MeshVertex.bl_rna.properties["co"]
    with pytest.raises(source.PreviewRefused):
        source.capture(bpy, "Requested")
    assert events == []

