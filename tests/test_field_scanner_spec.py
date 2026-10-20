from __future__ import annotations

import importlib
import math
import struct
import xml.etree.ElementTree as ET
import zlib

from scripts import field_scanner_spec as spec


def test_original_brief_and_reference_are_present_and_versioned():
    b = spec.load_brief()
    assert b["id"] == "field-scanner-v1"
    assert b["overall_dimensions"] == [.144, .051, .260]
    assert len(spec.asset_hashes()) == 2 and all(len(value) == 64 for value in spec.asset_hashes().values())
    root = ET.parse(spec.FIXTURE / "reference.svg").getroot()
    assert root.attrib["viewBox"] == "0 0 1100 560"
    assert "original" in root.find("{http://www.w3.org/2000/svg}title").text.lower()


def test_recipe_uses_bounded_structured_topology_and_smooth_sides(addon_package):
    mesh = importlib.import_module(f"{addon_package}.tools.mesh")
    steps = spec.create_steps()
    assert len(steps) == 16 and len({step["params"]["object_name"] for step in steps}) == 16
    for step in steps:
        prepared = mesh._prepare_mesh_create(step["params"])
        assert len(prepared.vertices) <= 96 and len(prepared.faces) <= 50
        assert all(math.isfinite(value) for vertex in prepared.vertices for value in vertex)
        if "Control" in prepared.object_name:
            assert prepared.face_smooth[:2] == (False, False)
            assert all(prepared.face_smooth[2:])


def test_closed_component_recipe_has_two_opposite_users_per_edge():
    for item in spec.geometry_recipe()[1:]:
        edges = {}
        geometry = item["geometry"]
        for face in geometry["faces"]:
            for a, b in zip(face, face[1:] + face[:1], strict=True):
                edges.setdefault(tuple(sorted((a, b))), []).append((a, b))
        assert all(len(users) == 2 and users[0] == users[1][::-1] for users in edges.values()), item["name"]


def test_shell_starts_with_two_disjoint_eight_edge_wire_loops():
    geometry = spec.geometry_recipe()[0]["geometry"]
    assert not geometry.get("faces") and len(geometry["vertices"]) == 16
    assert len(geometry["edges"]) == 16
    assert all((a < 8) == (b < 8) for a, b in geometry["edges"])


def test_display_atlas_has_positive_disjoint_full_surface_islands():
    geometry = next(part["geometry"] for part in spec.geometry_recipe() if part["name"] == "Scanner Glass")
    normals = [(0, -1, 0), (0, 1, 0), (0, 0, -1), (1, 0, 0), (0, 0, 1), (-1, 0, 0)]
    faces = [{"index": i, "normal_local": normal, "vertex_indices": face}
             for i, (normal, face) in enumerate(zip(normals, geometry["faces"], strict=True))]
    updates = spec.glass_uv_updates(dict(enumerate(geometry["vertices"])), faces, spec.load_brief())
    bounds = []
    for face in faces:
        uv = [entry["uv"] for entry in updates if entry["face_index"] == face["index"]]
        assert len(uv) == 4 and all(0 <= value <= 1 for point in uv for value in point)
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(uv, uv[1:] + uv[:1], strict=True)) / 2
        assert area > 0
        bounds.append((min(p[0] for p in uv), min(p[1] for p in uv), max(p[0] for p in uv), max(p[1] for p in uv)))
    for index, (x0, y0, x1, y1) in enumerate(bounds):
        for a0, b0, a1, b1 in bounds[index + 1:]:
            assert min(x1, a1) <= max(x0, a0) or min(y1, b1) <= max(y0, b0)
    front = [entry["uv"] for entry in updates if entry["face_index"] == 0]
    assert front[0][0] < front[1][0] and front[0][1] < front[3][1]


def test_owned_texture_fixtures_are_deterministic_and_match_declared_resolutions(tmp_path):
    first = spec.write_fixture_textures(tmp_path / "first")
    second = spec.write_fixture_textures(tmp_path / "second")
    for key, path in first.items():
        data = path.read_bytes()
        assert data == second[key].read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        expected = (500, 350) if key.startswith("lcd") else ((1024, 1024) if key == "shell_color" else (512, 512))
        assert (width, height) == expected
        # All rows are unfiltered RGBA: verify the bitmap is complete, not a header stub.
        offset, chunks = 8, []
        while offset < len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            if data[offset + 4:offset + 8] == b"IDAT":
                chunks.append(data[offset + 8:offset + 8 + length])
            offset += length + 12
        assert len(zlib.decompress(b"".join(chunks))) == height * (1 + width * 4)
    assert first["lcd_scan"].read_bytes() != first["lcd_calibration"].read_bytes()


def test_surface_recipe_uses_explicit_uv_and_image_roles_with_bounded_batches(tmp_path):
    for emission in (False, True):
        steps = spec.surface_steps("Finish", "Nested Surface", "UV", tmp_path / "color.png", "Color",
                                   roughness_path=None if emission else tmp_path / "roughness.png", emission=emission)
        assert len(steps) <= 32
        assert all(step["method"] != "python.execute" for step in steps)
        loads = [step["params"] for step in steps if step["method"] == "image.load"]
        assert [step["colorspace"] for step in loads] == (["sRGB"] if emission else ["sRGB", "Non-Color"])
        uv = next(step["params"] for step in steps if step["method"] == "nodes.set_properties")
        assert uv["settings"] == {"uv_map": "UV", "from_instancer": False} and uv["group_path"] == ["Surface"]
