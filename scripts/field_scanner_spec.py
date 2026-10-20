"""Original acceptance-asset recipe data; no Blender imports or hidden scene edits."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "field_scanner"


def load_brief() -> dict:
    brief = json.loads((FIXTURE / "brief.json").read_text(encoding="utf-8"))
    if brief.get("schema_version") != 1 or brief.get("units") != "metres" or brief.get("front_axis") != "-Y":
        raise ValueError("Unsupported scanner brief schema or coordinate convention")
    return brief


def asset_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (FIXTURE / "brief.json", FIXTURE / "reference.svg")}


def outline(width: float, height: float, corner: float) -> list[tuple[float, float]]:
    x = width / 2
    return [(-x, corner), (-x + corner, 0), (x - corner, 0), (x, corner),
            (x, height - corner), (x - corner, height), (-x + corner, height), (-x, height - corner)]


def rectangle(width: float, height: float, center_z: float) -> list[tuple[float, float]]:
    return [(-width / 2, center_z - height / 2), (width / 2, center_z - height / 2),
            (width / 2, center_z + height / 2), (-width / 2, center_z + height / 2)]


def prism(points: list[tuple[float, float]], front: float, back: float, *, smooth_sides=False) -> dict:
    n = len(points)
    return {"vertices": [[x, y, z] for y in (front, back) for x, z in points],
            "faces": [list(range(n)), list(reversed(range(n, n * 2))),
                      *[[(i + 1) % n, i, i + n, (i + 1) % n + n] for i in range(n)]],
            "face_smooth": [False, False, *([smooth_sides] * n)]}


def frame(spec: dict) -> dict:
    outer, inner = (rectangle(*spec[key], spec["center_z"]) for key in ("outer", "inner"))
    vertices = [[x, y, z] for y in (spec["front_y"], spec["back_y"]) for ring in (outer, inner) for x, z in ring]
    faces = []
    for i in range(4):
        j = (i + 1) % 4
        faces += [[i, j, j + 4, i + 4], [j + 8, i + 8, i + 12, j + 12],
                  [j, i, i + 8, j + 8], [i + 4, j + 4, j + 12, i + 12]]
    return {"vertices": vertices, "faces": faces, "face_smooth": [False] * len(faces)}


def geometry_recipe(brief: dict | None = None) -> list[dict]:
    b = brief or load_brief()
    result = []
    shell = b["shell"]
    ring = outline(shell["width"], shell["height"], shell["corner"])
    # Begin with two wire rings. Bridge/caps/fascia are actual structured edit operations.
    result.append({"name": "Scanner Shell", "role": "shell", "geometry": {
        "vertices": [[x, y, z] for y in (-shell["thickness"] / 2, shell["thickness"] / 2) for x, z in ring],
        "edges": [[base + i, base + (i + 1) % 8] for base in (0, 8) for i in range(8)]}})
    for key, name, role in (("bezel", "Scanner Bezel", "bezel"), ("handle", "Scanner Handle", "rubber")):
        result.append({"name": name, "role": role, "geometry": frame(b[key])})
    glass = b["glass"]
    result.append({"name": "Scanner Glass", "role": "glass", "geometry": prism(
        rectangle(glass["width"], glass["height"], glass["center_z"]), glass["front_y"], glass["back_y"])})

    def cylinder(name, role, x, z, radius, front, back, segments=48):
        points = [(x + radius * math.cos(i * math.tau / segments), z + radius * math.sin(i * math.tau / segments)) for i in range(segments)]
        result.append({"name": name, "role": role, "geometry": prism(points, front, back, smooth_sides=True)})
    buttons = b["buttons"]
    for label, x in zip(("Left", "Centre", "Right"), buttons["x"], strict=True):
        cylinder("Scanner Control " + label, "rubber", x, buttons["center_z"], buttons["radius"],
                 buttons["front_y"], buttons["back_y"], buttons["segments"])
    status = b["status"]
    cylinder("Scanner Status", "status", status["x"], status["z"], status["radius"], status["front_y"], status["back_y"])
    bolts = b["fasteners"]
    for index, (x, z) in enumerate((x, z) for x in bolts["x"] for z in bolts["z"]):
        cylinder(f"Scanner Fastener {index + 1}", "metal", x, z, bolts["radius"], bolts["front_y"], bolts["back_y"], 24)
    grille = b["grille"]
    for index, z in enumerate(grille["z"]):
        result.append({"name": f"Scanner Slot Cutter {index + 1}", "role": "bezel", "temporary": True, "geometry": prism(
            rectangle(grille["width"], grille["height"], z), grille["cutter_front_y"], grille["cutter_back_y"])})
    return result


def create_steps() -> list[dict]:
    return [{"method": "mesh.create", "params": {"object_name": item["name"],
             "mesh_name": item["name"] + " Mesh", **item["geometry"]}} for item in geometry_recipe()]


GLASS_ATLAS = {"front": (.02, .28, .70, .70), "back": (.75, .75, .23, .23),
               "bottom": (.02, .02, .70, .027), "top": (.02, .08, .70, .027),
               "right": (.02, .14, .488, .027), "left": (.02, .20, .488, .027)}


def glass_uv_updates(vertices: dict, faces: list[dict], brief: dict) -> list[dict]:
    g = brief["glass"]
    updates = []
    for face in faces:
        nx, ny, nz = face["normal_local"]
        kind = ("front" if ny < 0 else "back") if abs(ny) > .9 else (("top" if nz > 0 else "bottom") if abs(nz) > .9 else ("right" if nx > 0 else "left"))
        u0, v0, width, height = GLASS_ATLAS[kind]
        for corner, index in enumerate(face["vertex_indices"]):
            x, y, z = vertices[index]
            along_x = x / g["width"] + .5
            along_z = (z - g["center_z"]) / g["height"] + .5
            depth = (y - g["front_y"]) / (g["back_y"] - g["front_y"])
            if kind in {"front", "back"}:
                uv = (along_x if kind == "front" else 1 - along_x, along_z)
            elif kind in {"bottom", "top"}:
                uv = (along_x, depth if kind == "top" else 1 - depth)
            else:
                uv = (along_z, depth if kind == "left" else 1 - depth)
            updates.append({"face_index": face["index"], "corner_index": corner,
                            "uv": [u0 + uv[0] * width, v0 + uv[1] * height]})
    return updates


def _png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    stride = width * 4
    rows = b"".join(b"\0" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def write_fixture_textures(directory: Path) -> dict[str, Path]:
    """Deterministic owned test pixels, not user image editing or external downloads."""
    directory.mkdir()
    paths = {key: directory / (key + ".png") for key in ("shell_color", "shell_roughness", "lcd_scan", "lcd_calibration")}
    for key, size in (("shell_color", 1024), ("shell_roughness", 512)):
        pixels = bytearray()
        for y in range(size):
            for x in range(size):
                grain = ((x * 19 + y * 37 + x * y * 3) % 7) - 3
                rgba = (231 + grain, 132 + grain, 36 + grain, 255) if key == "shell_color" else (122 + grain,) * 3 + (255,)
                pixels.extend(rgba)
        _png(paths[key], size, size, pixels)
    glyphs = {"A": [14,17,17,31,17,17,17], "C": [15,16,16,16,16,16,15], "D": [30,17,17,17,17,17,30],
              "E": [31,16,16,30,16,16,31], "F": [31,16,16,30,16,16,16], "I": [31,4,4,4,4,4,31],
              "L": [16,16,16,16,16,16,31], "N": [17,25,25,21,19,19,17], "R": [30,17,17,30,20,18,17],
              "S": [15,16,16,14,1,1,30], "Y": [17,17,10,4,4,4,4], "9": [14,17,17,15,1,1,14],
              "2": [14,17,1,2,4,8,31], "/": [1,2,2,4,8,8,16]}
    for key in ("lcd_scan", "lcd_calibration"):
        width, height = 500, 350
        pixels = bytearray((8, 20, 31, 255)) * (width * height)
        cyan = (70, 218, 242, 255) if key == "lcd_scan" else (91, 232, 132, 255)
        def dot(x, y, color, *, width=width, height=height, pixels=pixels):
            if 0 <= x < width and 0 <= y < height:
                offset = (y * width + x) * 4
                pixels[offset:offset + 4] = bytes(color)
        # The front chart occupies exactly the UV front rectangle; other islands
        # sample the quiet dark margins, with no hidden texture stacking.
        left, top = 10, 7
        for y in range(245):
            for x in range(350):
                dot(left + x, top + y, (10, 34, 51, 255) if key == "lcd_scan" else (11, 41, 30, 255))
        def text(value, x, y, scale=2, *, dot=dot, left=left, top=top, cyan=cyan):
            for char in value:
                for row, bits in enumerate(glyphs.get(char, [])):
                    for col in range(5):
                        if bits & (1 << (4 - col)):
                            for dy in range(scale):
                                for dx in range(scale):
                                    dot(left + x + col * scale + dx, top + y + row * scale + dy, cyan)
                x += 6 * scale
        text("FIELD / SCAN" if key == "lcd_scan" else "CAL", 18, 15)
        text("READY", 18, 44)
        text("92", 278, 14, 3)
        for y in range(83, 220, 25):
            for x in range(16, 334):
                dot(left + x, top + y, (24, 56, 68, 255))
        points = [(16,195), (55,195), (80,137), (110,158), (145,98), (180,150), (220,124), (332,124)]
        for (ax, ay), (bx, by) in pairwise(points):
            count = max(abs(bx - ax), abs(by - ay))
            for index in range(count + 1):
                x, y = round(ax + (bx - ax) * index / count), round(ay + (by - ay) * index / count)
                for dy in range(-1, 2):
                    dot(left + x, top + y + dy, cyan)
        _png(paths[key], width, height, pixels)
    return paths


def surface_steps(material: str, group: str, uv_layer: str, color_path: Path,
                  image_name: str, *, roughness_path: Path | None = None, emission=False) -> list[dict]:
    steps = []
    def step(method, **params):
        steps.append({"method": method, "params": params})
    step("shader_group.create", group_name=group)
    step("shader_group.interface_add", group_name=group, name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    step("nodes.add", material_name=material, node_type="ShaderNodeGroup", name="Surface")
    step("shader_group.bind", material_name=material, node_name="Surface", group_name=group)
    target = {"material_name": material, "group_path": ["Surface"]}
    step("nodes.add", **target, node_type="ShaderNodeBsdfPrincipled", name="Finish")
    step("nodes.set_input", **target, node_name="Finish", socket_name="Roughness", value=.22 if emission else .48)
    step("nodes.set_input", **target, node_name="Finish", socket_name="Metallic", value=.05)
    step("nodes.add", **target, node_type="ShaderNodeUVMap", name="UV Coordinates")
    step("nodes.set_properties", **target, node_name="UV Coordinates", settings={"uv_map": uv_layer, "from_instancer": False})
    step("image.load", filepath=str(color_path), new_name=image_name, colorspace="sRGB")
    step("nodes.add", **target, node_type="ShaderNodeTexImage", name="Albedo")
    step("nodes.set_image", **target, node_name="Albedo", image_name=image_name)
    step("nodes.link", **target, from_node="UV Coordinates", from_socket="UV", to_node="Albedo", to_socket="Vector")
    step("nodes.link", **target, from_node="Albedo", from_socket="Color", to_node="Finish", to_socket="Base Color")
    if roughness_path is not None:
        step("image.load", filepath=str(roughness_path), new_name="Scanner Roughness", colorspace="Non-Color")
        step("nodes.add", **target, node_type="ShaderNodeTexImage", name="Roughness")
        step("nodes.set_image", **target, node_name="Roughness", image_name="Scanner Roughness")
        step("nodes.link", **target, from_node="UV Coordinates", from_socket="UV", to_node="Roughness", to_socket="Vector")
        step("nodes.link", **target, from_node="Roughness", from_socket="Color", to_node="Finish", to_socket="Roughness")
    if emission:
        step("nodes.link", **target, from_node="Albedo", from_socket="Color", to_node="Finish", to_socket="Emission Color")
        step("nodes.set_input", **target, node_name="Finish", socket_name="Emission Strength", value=.45)
    step("nodes.link", **target, from_node="Finish", from_socket="BSDF", to_node="Group Output", to_socket="Shader")
    step("nodes.link", material_name=material, from_node="Surface", from_socket="Shader", to_node="Material Output", to_socket="Surface", replace_existing=True)
    return steps
