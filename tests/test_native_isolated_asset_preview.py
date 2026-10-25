from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from scripts import native_isolated_asset_preview as preview


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
    assert importlib.reload(preview).PreviewRefused.__base__ is ValueError


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


def test_capture_model_reads_only_admitted_named_geometry():
    bpy, _obj, _mesh, events = model_native_capture()
    assert preview.capture(bpy, "Requested") == triangle()
    assert events == ["coordinate"] * 3


def test_static_polygon_descriptor_length_three_allows_dynamic_quad_instance():
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
    dto = preview.capture(bpy, "Requested")
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
def test_capture_profile_refusal_precedes_coordinate_getter(owner, field, value):
    bpy, obj, mesh, events = model_native_capture()
    setattr(obj if owner == "object" else mesh, field, value)
    with pytest.raises(preview.PreviewRefused):
        preview.capture(bpy, "Requested")
    assert events == []


@pytest.mark.parametrize("family,field", [("Object", "location"), ("Object", "data"),
                                         ("Mesh", "vertices"), ("MeshVertex", "co"),
                                         ("MeshEdge", "vertices"), ("MeshPolygon", "vertices")])
def test_runtime_rna_descriptor_refusal_precedes_coordinate_getter(family, field):
    bpy, _obj, _mesh, events = model_native_capture()
    getattr(bpy.types, family).bl_rna.properties[field].is_runtime = True
    with pytest.raises(preview.PreviewRefused):
        preview.capture(bpy, "Requested")
    assert events == []


@pytest.mark.parametrize("change", ["class", "identifier", "numeric_shape", "missing_descriptor",
                                    "polygon_descriptor_shape"])
def test_capture_refuses_changed_native_class_or_descriptor_before_coordinates(change):
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
    with pytest.raises(preview.PreviewRefused):
        preview.capture(bpy, "Requested")
    assert events == []


def test_preview_runner_is_opt_in_and_gives_each_phase_an_owned_thin_profile(monkeypatch, tmp_path):
    runner = importlib.import_module("scripts.run_blender_checks")
    case = "isolated_asset_preview_probe"
    assert case in runner.CASES and case in runner.PHASED_CASES and case in runner.OPT_IN_CASES
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setenv("GITHUB_TOKEN", "test-only-placeholder")
    monkeypatch.setenv("PYTHONPATH", "/untrusted-python-path")
    monkeypatch.setenv("BLENDER_USER_SCRIPTS", "/untrusted-blender-path")
    monkeypatch.delenv("BRIDGE_TEST_PRIVATE_UI_MANIFEST", raising=False)
    observed = []

    def run(command, **kwargs):
        phase = command[command.index("--bridge-phase") + 1]
        observed.append(phase)
        assert "--disable-autoexec" in command and "--factory-startup" in command
        assert ("--background" in command) is (phase == "reader")
        assert command.index("--python-expr") < command.index("--python")
        assert command[command.index("--python-expr") + 1] == "import sys; sys.dont_write_bytecode = True"
        assert command[command.index("--python-exit-code") + 1] == "1"
        environment = kwargs["env"]
        assert "GITHUB_TOKEN" not in environment and "PYTHONPATH" not in environment
        for name in ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                     "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                     "XDG_RUNTIME_DIR", "TEMP", "TMP", "TMPDIR"):
            assert Path(environment[name]).is_relative_to(tmp_path)
            assert Path(environment[name]).is_dir()
        assert Path(kwargs["cwd"]).is_relative_to(tmp_path)
        marker = runner.PHASED_CASES[case][0 if phase == "writer" else 1]
        evidence = {"blender_version": "5.2.2", "phase": phase, "process_id": len(observed),
                    "process_instance": environment["BRIDGE_TEST_PROCESS_TOKEN"]}
        kwargs["stdout"].write((marker + json.dumps(evidence)).encode())
        return NS(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), case, tmp_path, 10)
    assert observed == ["writer", "reader"]  # The runner's reader phase is the render worker.
    assert result["status"] == "passed" and result["fresh_process_verified"] is True
    assert result["phases"][0]["execution_mode"] == "interactive_display"
    assert result["phases"][1]["execution_mode"] == "background"


def test_preview_runner_failure_does_not_start_worker(monkeypatch, tmp_path):
    runner = importlib.import_module("scripts.run_blender_checks")
    calls = []

    def run(command, **_kwargs):
        calls.append(command[command.index("--bridge-phase") + 1])
        return NS(returncode=1)

    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.subprocess, "run", run)
    result = runner.run_case(Path("blender"), "isolated_asset_preview_probe", tmp_path, 10)
    assert result["status"] == "failed" and result["reader_started"] is False
    assert calls == ["writer"]
