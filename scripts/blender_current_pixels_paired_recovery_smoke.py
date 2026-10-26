"""Private paired Image recovery primitive; no public lifecycle or Save qualification.

Both profiles run only in an attested disposable interactive Blender process.
Native timers provide the deferred observations. External backup bytes, not an
unsaved helper, source array, encoder recipe or undo step, supply recovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import stat
import struct
import sys
import time
import traceback
import uuid
from array import array
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_MANIFEST = 64 * 1024
MAX_REPORT = 2 * 1024 * 1024
MAX_PAYLOAD = 257 * 1024 * 1024
MAX_PROJECT = 530 * 1024 * 1024
MIN_MEMORY = 8 * 1024**3
MIN_DISK = 2 * 1024**3
PHASE_SECONDS = 300.
PROFILES = {"SMALL2X2": (2, 2), "LARGE4K": (4096, 4096)}
RECORD_KEY = "_codex_bridge_paired_recovery_fixture_v1"
HELPER_NAME = "Paired recovery native OWNER helper"
OLD_RGBA = (.0625, .125, .25, 1.)
R_CHANNEL = (.125, -0., 1.25, .75)
A_CHANNEL = (0., .25, .5, 1.)
BACKUPS = frozenset({"previous-packed.bin", "current-pixels.exr", "manifest.json"})


def raw_digest(values):
    assert isinstance(values, array) and values.typecode == "f" and values.itemsize == 4
    if sys.byteorder == "little":
        return hashlib.sha256(values).hexdigest()
    other = array("f", values)
    other.byteswap()
    return hashlib.sha256(other).hexdigest()


def edited_values(width, height):
    """The setup writer; the independent oracle below uses packed scalar rows."""
    assert (width, height) in PROFILES.values()
    result = array("f", [0.]) * (width * height * 4)
    red = array("f", (R_CHANNEL[x % 4] for x in range(width)))
    alpha = array("f", (A_CHANNEL[x % 4] for x in range(width)))
    for y in range(height):
        start, end = y * width * 4, (y + 1) * width * 4
        result[start:end:4] = red
        result[start + 1:end:4] = array("f", [((y % 4) + 1) / 4]) * width
        result[start + 2:end:4] = array("f", ((y * width + x) / 16777216 for x in range(width)))
        result[start + 3:end:4] = alpha
    return result


def edited_oracle(width, height):
    """Hash every coordinate independently; retain only the digest afterward."""
    assert (width, height) in PROFILES.values()
    digest = hashlib.sha256()
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(struct.pack("<ffff", (.125, -0., 1.25, .75)[x % 4],
                                   ((y % 4) + 1) * .25,
                                   (y * width + x) * (2. ** -24),
                                   (0., .25, .5, 1.)[x % 4]))
        digest.update(row)
    return digest.hexdigest()


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def record_hash(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def image_animation_schema_absence(rna):
    """Measure declared RNA absence only; never read Image.animation_data."""
    assert rna.identifier == "Image", "The fixture requires the native Image RNA schema"
    identifiers = []
    for index, prop in enumerate(rna.properties):
        assert index < 256, "Image RNA property catalog exceeds the fixture bound"
        name = prop.identifier
        assert type(name) is str and 0 < len(name) <= 128 and name.isascii()
        assert name != "animation_data", "Unexpected Image.animation_data declaration is not qualified"
        identifiers.append(name)
    assert identifiers, "Missing Image RNA property schema"
    return {"profile": "IMAGE_ANIMATION_DATA_RNA_ABSENT_V1", "property": "animation_data",
            "declared": False, "catalog_count": len(identifiers),
            "ordered_catalog_sha256": record_hash(identifiers)}


def socket_projection(values, *, native, scalar):
    """Use the registered socket class, as public shader graph inspectors do.

    bl_idname distinguishes concrete classes such as NodeSocketFloatFactor;
    socket.type is only its broad data category. No type fallback is admitted.
    """
    assert len(values) <= 64
    return [{"name": item.name, "identifier": item.identifier, "type": item.bl_idname,
             "_native": native(item), "default": scalar(item.default_value) if hasattr(item, "default_value") else None,
             "hide": item.hide, "enabled": item.enabled, "is_linked": item.is_linked} for item in values]


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate fixture metadata key")
        result[key] = value
    return result


def read_json(path, maximum=MAX_MANIFEST):
    assert not path.is_symlink() and 0 < path.stat().st_size <= maximum
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                       parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    assert isinstance(value, dict)
    return value


def file_id(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def verify_file(path, *, expected_bytes, expected_sha256, maximum=MAX_PAYLOAD):
    assert not path.is_symlink() and 0 < expected_bytes <= maximum
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
    assert before.st_size == expected_bytes
    digest, length = hashlib.sha256(), 0
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        assert file_id(os.fstat(stream.fileno())) == file_id(before)
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            length += len(block)
        assert file_id(os.fstat(stream.fileno())) == file_id(before)
    assert file_id(path.lstat()) == file_id(before)
    assert length == expected_bytes and digest.hexdigest() == expected_sha256
    return {"file": path.name, "bytes": length, "sha256": digest.hexdigest(), "identity": file_id(before),
            "independent_reopen_verified": True}


def reopened_payload(path, *, expected_bytes, expected_sha256):
    """Return the bytes checked on this fresh descriptor, not a second read."""
    assert not path.is_symlink() and 0 < expected_bytes <= MAX_PAYLOAD
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
    assert before.st_size == expected_bytes
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        assert file_id(os.fstat(stream.fileno())) == file_id(before)
        result = stream.read(MAX_PAYLOAD + 1)
        assert file_id(os.fstat(stream.fileno())) == file_id(before)
    assert file_id(path.lstat()) == file_id(before)
    assert len(result) == expected_bytes and hashlib.sha256(result).hexdigest() == expected_sha256
    return result


def durable_new(folder, name, data):
    assert name in BACKUPS and type(data) is bytes
    maximum = MAX_MANIFEST if name == "manifest.json" else MAX_PAYLOAD
    assert 0 < len(data) <= maximum and not folder.is_symlink()
    parent = folder.stat()
    assert stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid()
    path = folder / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        assert stream.write(data) == len(data)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        current = os.fstat(directory)
        assert (parent.st_dev, parent.st_ino) == (current.st_dev, current.st_ino)
        os.fsync(directory)
    finally:
        os.close(directory)
    assert (folder.stat().st_dev, folder.stat().st_ino) == (parent.st_dev, parent.st_ino)
    result = verify_file(path, expected_bytes=len(data), expected_sha256=hashlib.sha256(data).hexdigest(), maximum=maximum)
    return {**result, "file_fsync": True, "parent_directory_fsync": True, "create_only": True}


def resource_check(available, free, *, large):
    assert type(available) is int and type(free) is int
    if large:
        assert available >= MIN_MEMORY, "4K paired recovery requires measured 8 GiB headroom"
        assert free >= MIN_DISK, "4K paired recovery requires measured 2 GiB filesystem free"


def scrub_native(value):
    if isinstance(value, dict):
        return {key: scrub_native(item) for key, item in value.items() if key != "_native"}
    if isinstance(value, list):
        return [scrub_native(item) for item in value]
    return value


def differences(expected, actual, prefix=""):
    if type(expected) is not type(actual):
        return [prefix + ":type"]
    if isinstance(expected, dict):
        result = [prefix + ":keys"] if set(expected) != set(actual) else []
        for key in sorted(set(expected) & set(actual)):
            result.extend(differences(expected[key], actual[key], prefix + "/" + key))
        return result[:64]
    if isinstance(expected, list):
        result = [prefix + ":length"] if len(expected) != len(actual) else []
        for index, (one, two) in enumerate(zip(expected, actual, strict=False)):
            result.extend(differences(one, two, prefix + "/" + str(index)))
        return result[:64]
    return [] if expected == actual else [prefix]


def main():
    sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]
    import bpy
    from blender_artist_sidebar_smoke import owned_process_exit, private_display_manifest
    from blender_codex_bridge import pixel_codecs
    from blender_codex_bridge.tools import image_portability as storage
    from blender_codex_bridge.tools.image_recovery_jobs import _decode_steps
    from native_resources import linux_available_memory, linux_process_memory

    private_display_manifest()
    assert not bpy.app.background and "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    assert (tuple(bpy.app.version), bpy.app.build_hash.decode()) in {
        ((4, 5, 14), "62c1db4208e8"), ((5, 2, 2), "d13f752e3b9c")}
    args = argparse.ArgumentParser()
    args.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    args.add_argument("--bridge-bundle", type=Path, required=True)
    args.add_argument("--bridge-profile", choices=tuple(PROFILES), required=True)
    options = args.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bundle = options.bridge_bundle.resolve(strict=True)
    assert not options.bridge_bundle.is_symlink() and bundle.is_dir()
    width, height = PROFILES[options.bridge_profile]
    large, started = width == 4096, time.monotonic()
    token = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(token) == 32 and all(c in "0123456789abcdef" for c in token)
    report = {"completed": False, "phase": options.bridge_phase, "profile": options.bridge_profile,
              "process_id": os.getpid(), "process_instance": token, "blender_version": bpy.app.version_string,
              "source_build": bpy.app.build_hash.decode(), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "Private FILE Float32 Non-Color CHANNEL_PACKED paired-recovery prerequisite only",
              "observations": [], "native_boundaries": [], "phase_deadline_seconds": PHASE_SECONDS,
              "public_lifecycle_qualified": False, "public_save_qualified": False,
              "native_undo_or_hidden_caches_qualified": False, "Windows_qualified": False}
    report_path = bundle / (options.bridge_phase + "-evidence.json")
    scope, manifest, expected, state, remaining = {}, {}, {}, "start", 0
    oracle = None

    def persist():
        raw = canonical_json(report)
        assert len(raw) <= MAX_REPORT
        report_path.write_bytes(raw)

    def boundary(label, operation):
        row = {"label": label, "attempted": True, "completed": False}
        report["native_boundaries"].append(row)
        persist()
        began = time.monotonic()
        result = operation()
        row.update(completed=True, seconds=time.monotonic() - began)
        persist()
        return result

    def native(owner):
        return {"rna_type": owner.bl_rna.identifier, "pointer": int(owner.as_pointer()),
                "session_uid": int(owner.session_uid) if hasattr(owner, "session_uid") else None}

    def owner_key(owner):
        return {"name": owner.name, "rna_type": owner.bl_rna.identifier, "_native": native(owner)}

    def scalar(value):
        if value is None or type(value) in (str, bool, int):
            return value
        if isinstance(value, float):
            assert math.isfinite(value)
            return {"float64_le": struct.pack("<d", value).hex()}
        return [scalar(item) for item in value]

    def packed(image):
        value = image.packed_file
        assert value is not None and 0 < value.size <= MAX_PAYLOAD
        payload = bytes(value.data)
        assert len(payload) == value.size
        return payload

    def pixels(image):
        assert tuple(image.size) in PROFILES.values() and image.channels == 4
        values = array("f", [0.]) * len(image.pixels)
        image.pixels.foreach_get(values)
        assert len(values) == image.size[0] * image.size[1] * 4
        # Equality against the independently generated finite complete digest is
        # checked at every admitted state; do not replace it with sampling.
        return values

    def image_projection(image):
        animation_schema = image_animation_schema_absence(image.bl_rna)
        assert image.has_data, "Complete projection must not silently load an unknown buffer"
        payload = packed(image)
        consumers = sorted((owner_key(item) for item in bpy.data.user_map(subset={image}).get(image, ())),
                           key=lambda item: (item["rna_type"], item["name"]))
        return {**owner_key(image), "source": image.source, "filepath": image.filepath,
                "file_format": image.file_format, "colorspace": image.colorspace_settings.name,
                "alpha_mode": image.alpha_mode, "is_float": bool(image.is_float),
                "size": list(image.size), "channels": image.channels, "has_data": bool(image.has_data),
                "is_dirty": bool(image.is_dirty), "users": image.users, "use_fake_user": bool(image.use_fake_user),
                "library": image.library is None, "override": image.override_library is None,
                "animation_data_schema": animation_schema, "packed_bytes": len(payload),
                "packed_sha256": hashlib.sha256(payload).hexdigest(), "pixels_float32_le": raw_digest(pixels(image)),
                "consumers": consumers}

    def sockets(values):
        return socket_projection(values, native=native, scalar=scalar)

    def material_projection(material):
        tree = material.node_tree
        assert tree is not None and len(tree.nodes) <= 8 and len(tree.links) <= 8
        nodes = []
        for node in sorted(tree.nodes, key=lambda item: item.name):
            row = {"name": node.name, "type": node.bl_idname, "_native": native(node),
                   "parent": None if node.parent is None else owner_key(node.parent),
                   "label": node.label, "mute": node.mute, "hide": node.hide,
                   "location": scalar(node.location), "width": scalar(node.width),
                   "inputs": sockets(node.inputs), "outputs": sockets(node.outputs)}
            if node.bl_idname == "ShaderNodeTexImage":
                row.update(image=None if node.image is None else owner_key(node.image),
                           interpolation=node.interpolation, projection=node.projection, extension=node.extension)
            nodes.append(row)
        links = sorted([[link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier]
                        for link in tree.links])
        return {**owner_key(material), "users": material.users, "use_fake_user": material.use_fake_user,
                "use_nodes": material.use_nodes, "diffuse_color": scalar(material.diffuse_color),
                "roughness": scalar(material.roughness), "metallic": scalar(material.metallic),
                "tree": {**owner_key(tree), "nodes": nodes, "links": links}}

    def object_projection(obj):
        mesh = obj.data
        assert obj.type == "MESH" and len(mesh.vertices) == 3 and len(mesh.polygons) == 1
        return {**owner_key(obj), "data": owner_key(mesh), "users": obj.users, "parent": obj.parent is None,
                "location": scalar(obj.location), "rotation_euler": scalar(obj.rotation_euler),
                "scale": scalar(obj.scale), "hide_viewport": obj.hide_viewport, "hide_render": obj.hide_render,
                "modifiers": len(obj.modifiers), "constraints": len(obj.constraints), "animation": obj.animation_data is None,
                "collections": sorted(collection.name for collection in obj.users_collection),
                "mesh_users": mesh.users, "vertices": [scalar(vertex.co) for vertex in mesh.vertices],
                "edges": [list(edge.vertices) for edge in mesh.edges],
                "polygons": [{"vertices": list(face.vertices), "material_index": face.material_index,
                              "use_smooth": face.use_smooth} for face in mesh.polygons],
                "loops": [loop.vertex_index for loop in mesh.loops],
                "uv_layers": len(mesh.uv_layers), "shape_keys": mesh.shape_keys is None,
                "materials": [owner_key(material) for material in mesh.materials],
                "slots": [{"link": slot.link, "material": owner_key(slot.material)} for slot in obj.material_slots]}

    def graph():
        result = {"original": image_projection(scope["original"]), "protected": image_projection(scope["protected"]),
                  "materials": [material_projection(item) for item in scope["materials"]],
                  "objects": [object_projection(item) for item in scope["objects"]], "helper": None}
        if scope.get("helper") is not None:
            helper = scope["helper"]
            result["helper"] = {**image_projection(helper), "owner": owner_key(helper[storage.OWNER_KEY]),
                                "metadata": helper[storage.METADATA_KEY], "record": helper[RECORD_KEY]}
        return result

    def verify(label, wanted, *, fresh=False):
        actual = graph()
        left, right = (scrub_native(wanted), scrub_native(actual)) if fresh else (wanted, actual)
        delta = differences(left, right)
        report["observations"].append({"label": label, "expected_sha256": record_hash(left),
                                       "actual_sha256": record_hash(right), "differences": delta,
                                       "original_identity": native(scope["original"]),
                                       "original_pixels_sha256": actual["original"]["pixels_float32_le"],
                                       "original_packed_sha256": actual["original"]["packed_sha256"],
                                       "original_is_dirty": actual["original"]["is_dirty"]})
        persist()
        assert not delta, (label, delta)

    def encode(values, w, h):
        result = b"".join(step.data for step in pixel_codecs.encode_steps(values, w, h, "EXR32_RAW", "DATA"))
        assert 0 < len(result) <= MAX_PAYLOAD
        return result

    def make_file(name, values, w, h, folder):
        path = folder / (name + ".exr")
        payload = encode(values, w, h)
        path.write_bytes(payload)
        image = bpy.data.images.load(str(path), check_existing=False)
        image.name = name
        image.colorspace_settings.name, image.alpha_mode = "Non-Color", "CHANNEL_PACKED"
        image.pack(data=payload, data_len=len(payload))
        assert image.is_float and image.file_format == "OPEN_EXR" and raw_digest(pixels(image)) == raw_digest(values)
        return image

    def make_object(name, image, x):
        material = bpy.data.materials.new(name + " Material")
        material.use_nodes = True
        tree = material.node_tree
        texture = tree.nodes.new("ShaderNodeTexImage")
        texture.name = name + " Texture"
        texture.image = image
        tree.links.new(texture.outputs["Color"], tree.nodes.get("Principled BSDF").inputs["Base Color"])
        mesh = bpy.data.meshes.new(name + " Mesh")
        mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
        mesh.materials.append(material)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.location.x = x
        return obj, material

    def setup_writer():
        nonlocal oracle, manifest, expected
        folder = bundle / "external"
        folder.mkdir(mode=0o700)
        original = boundary("setup_original_file", lambda: make_file("Original edited FILE", array("f", OLD_RGBA) * (width * height), width, height, folder))
        values = edited_values(width, height)
        original.pixels.foreach_set(values)
        original.update()
        del values
        oracle = edited_oracle(width, height)
        assert original.is_dirty and raw_digest(pixels(original)) == oracle
        protected = make_file("Unrelated protected FILE", array("f", [.75, .5, .25, 1.]) * 4, 2, 2, folder)
        owners = [make_object("First consumer", original, 0.), make_object("Second consumer", original, 2.),
                  make_object("Unrelated protected consumer", protected, 4.)]
        scope.update(original=original, protected=protected, objects=[o for o, _ in owners],
                     materials=[m for _, m in owners], helper=None)
        bpy.context.view_layer.update()  # Explicit owned setup, before immutable intent.
        folder.rename(bundle / "unavailable-originals")
        assert not Path(original.filepath).exists() and not Path(protected.filepath).exists()
        before = graph()
        assert original.users == 2 and len(before["original"]["consumers"]) == 2
        current = boundary("encode_actual_original_current_pixels", lambda: encode(pixels(original), width, height))
        old = packed(original)
        manifest = {"schema": "PRIVATE_PAIRED_RECOVERY_V1", "record_uuid": uuid.uuid4().hex,
                    "profile": options.bridge_profile, "width": width, "height": height,
                    "expected_edited_sha256": oracle, "before": before,
                    "previous_file": "previous-packed.bin", "previous_bytes": len(old), "previous_sha256": hashlib.sha256(old).hexdigest(),
                    "current_file": "current-pixels.exr", "current_bytes": len(current), "current_sha256": hashlib.sha256(current).hexdigest()}
        raw = canonical_json(manifest)
        assert len(raw) <= MAX_MANIFEST
        report["durable_backups"] = [durable_new(bundle, "previous-packed.bin", old),
                                      durable_new(bundle, "current-pixels.exr", current), durable_new(bundle, "manifest.json", raw)]
        report["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
        persist()
        assert read_json(bundle / "manifest.json") == manifest
        verify_file(bundle / manifest["previous_file"], expected_bytes=len(old), expected_sha256=manifest["previous_sha256"])
        verify_file(bundle / manifest["current_file"], expected_bytes=len(current), expected_sha256=manifest["current_sha256"])
        verify("complete_pre_helper_intent_after_durable_backup_reopen", before)
        assert bpy.data.images.get(HELPER_NAME) is None
        helper = boundary("allocate_owned_helper", lambda: bpy.data.images.new(HELPER_NAME, width, height, alpha=True, float_buffer=True))
        earned = native(helper)
        helper.source, helper.filepath = "FILE", ""
        helper.colorspace_settings.name, helper.alpha_mode = "Non-Color", "CHANNEL_PACKED"
        helper.pack(data=current, data_len=len(current))
        assert packed(helper) == current
        helper.buffers_free()
        assert raw_digest(pixels(helper)) == oracle
        metadata = {"schema_version": 1, "mode": "CURRENT_PIXELS", "width": width, "height": height,
                    "source": "FILE", "colorspace": "Non-Color", "alpha_mode": "CHANNEL_PACKED", "is_float": True,
                    "pixels_sha256_float32_le": oracle, "packed_sha256": manifest["current_sha256"]}
        record = {"record_uuid": manifest["record_uuid"], "manifest_sha256": report["manifest_sha256"], "manifest_file": "manifest.json"}
        helper[storage.METADATA_KEY] = canonical_json(metadata).decode()
        helper[storage.OWNER_KEY] = original
        helper[RECORD_KEY] = canonical_json(record).decode()
        helper.use_fake_user = True
        scope["helper"] = helper
        assert native(helper) == earned and storage._snapshot(helper, original, maximum_pixels=width * height, maximum_bytes=MAX_PAYLOAD) == metadata
        expected = deepcopy(before)
        expected["original"]["users"] += 1
        expected["original"]["consumers"].append({"name": HELPER_NAME, "rna_type": "Image", "_native": earned})
        expected["original"]["consumers"].sort(key=lambda item: (item["rna_type"], item["name"]))
        expected["helper"] = {"name": HELPER_NAME, "rna_type": "Image", "_native": earned,
            "source": "FILE", "filepath": "", "file_format": "OPEN_EXR", "colorspace": "Non-Color",
            "alpha_mode": "CHANNEL_PACKED", "is_float": True, "size": [width, height], "channels": 4,
            "has_data": True, "is_dirty": False, "users": 1, "use_fake_user": True,
            "library": True, "override": True,
            "animation_data_schema": deepcopy(before["original"]["animation_data_schema"]),
            "packed_bytes": len(current),
            "packed_sha256": manifest["current_sha256"], "pixels_float32_le": oracle, "consumers": [],
            "owner": owner_key(original), "metadata": canonical_json(metadata).decode(), "record": canonical_json(record).decode()}
        verify("only_predicted_owned_helper_footprint", expected)
        (bundle / "helper-footprint.json").write_bytes(canonical_json({"expected": expected, "record": record, "helper_name": HELPER_NAME}))
        pack_forward(current)

    def forward_expected():
        result = deepcopy(expected)
        result["original"].update(packed_bytes=manifest["current_bytes"], packed_sha256=manifest["current_sha256"], is_dirty=False)
        return result

    def pack_forward(current):
        original = scope["original"]
        boundary("pack_current_original", lambda: original.pack(data=current, data_len=len(current)))
        assert packed(original) == current
        assert raw_digest(pixels(original)) == manifest["expected_edited_sha256"]
        report["complete_packed_bytes_verified_before_original_buffer_discard"] = True
        boundary("discard_original_buffer_after_byte_verification", original.buffers_free)
        assert not original.has_data
        boundary("decode_only_verified_original_packed_memory", lambda: pixels(original))
        verify("portable_edited_original_after_packed_only_decode", forward_expected())

    def reopened_recovery():
        old = reopened_payload(bundle / manifest["previous_file"], expected_bytes=manifest["previous_bytes"],
                               expected_sha256=manifest["previous_sha256"])
        current = reopened_payload(bundle / manifest["current_file"], expected_bytes=manifest["current_bytes"],
                                   expected_sha256=manifest["current_sha256"])
        metadata = {"width": width, "height": height}
        generator = _decode_steps(current, metadata, lambda: None)
        while True:
            try:
                next(generator)
            except StopIteration as completed:
                decoded = completed.value
                break
        assert raw_digest(decoded) == manifest["expected_edited_sha256"]
        return old, decoded

    def reverse(*, fresh):
        verify("before_explicit_reverse", forward_expected(), fresh=fresh)
        original, identity_before = scope["original"], native(scope["original"])
        old, decoded = reopened_recovery()
        boundary("restore_reopened_previous_packed_bytes", lambda: original.pack(data=old, data_len=len(old)))
        assert packed(original) == old
        boundary("discard_current_buffer_for_verified_previous_payload", original.buffers_free)
        boundary("decode_verified_previous_packed_memory", lambda: pixels(original))
        boundary("restore_reopened_canonical_current_pixels", lambda: original.pixels.foreach_set(decoded))
        boundary("mark_restored_edited_pixels_dirty", original.update)
        assert native(original) == identity_before
        verify("old_packed_plus_original_dirty_edited_pixels", expected, fresh=fresh)
        report["recovery_from_independently_reopened_artifacts"] = True
        report["original_image_recreated"] = False

    def save_fixture():
        path = bundle / "portable-current-pixels.blend"
        assert not path.exists()
        result = boundary("owned_fixture_only_save", lambda: bpy.ops.wm.save_as_mainfile(
            filepath=str(path), check_existing=False, relative_remap=False, compress=False, copy=True))
        assert result == {"FINISHED"} and 0 < path.stat().st_size <= MAX_PROJECT
        wanted = forward_expected()
        verify("declared_graph_after_fixture_only_save", wanted)
        proof = {"project_file": path.name, "project_bytes": path.stat().st_size,
                 "project_sha256": verify_file(path, expected_bytes=path.stat().st_size, expected_sha256=_file_sha(path), maximum=MAX_PROJECT)["sha256"],
                 "helper_name": HELPER_NAME, "record_uuid": manifest["record_uuid"],
                 "manifest_sha256": report["manifest_sha256"], "expected_forward": wanted}
        (bundle / "project-proof.json").write_bytes(canonical_json(proof))
        report["saved_native_graph_provenance"] = proof

    def _file_sha(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def setup_reader():
        nonlocal manifest, expected, oracle
        manifest = read_json(bundle / "manifest.json")
        assert (manifest["schema"], manifest["previous_file"], manifest["current_file"]) == (
            "PRIVATE_PAIRED_RECOVERY_V1", "previous-packed.bin", "current-pixels.exr")
        assert (manifest["profile"], manifest["width"], manifest["height"]) == (options.bridge_profile, width, height)
        footprint = read_json(bundle / "helper-footprint.json")
        proof = read_json(bundle / "project-proof.json", MAX_REPORT)
        assert proof["project_file"] == "portable-current-pixels.blend" and proof["helper_name"] == HELPER_NAME
        manifest_sha = hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()
        assert proof["manifest_sha256"] == footprint["record"]["manifest_sha256"] == manifest_sha
        assert proof["record_uuid"] == footprint["record"]["record_uuid"] == manifest["record_uuid"]
        assert footprint["record"]["manifest_file"] == "manifest.json"
        for key in ("previous", "current"):
            verify_file(bundle / manifest[key + "_file"], expected_bytes=manifest[key + "_bytes"], expected_sha256=manifest[key + "_sha256"])
        path = bundle / proof["project_file"]
        verify_file(path, expected_bytes=proof["project_bytes"], expected_sha256=proof["project_sha256"], maximum=MAX_PROJECT)
        boundary("open_owned_fixture_project", lambda: bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False))
        helper = bpy.data.images[proof["helper_name"]]
        assert helper[RECORD_KEY] == canonical_json(footprint["record"]).decode()
        original = helper.get(storage.OWNER_KEY)
        assert isinstance(original, bpy.types.Image) and original != helper
        assert original.name == manifest["before"]["original"]["name"]  # Diagnostic after native OWNER resolution.
        metadata = storage._snapshot(helper, original, maximum_pixels=width * height, maximum_bytes=MAX_PAYLOAD)
        oracle = edited_oracle(width, height)
        assert metadata["pixels_sha256_float32_le"] == oracle == manifest["expected_edited_sha256"]
        assert not Path(original.filepath).exists()
        # This is the first original pixel read in this fresh process. No restore,
        # original-ID lookup by name, role rewrite or replacement precedes it.
        assert raw_digest(pixels(original)) == oracle
        report["fresh_original_edited_pixels_verified_before_any_restore"] = True
        scope.update(original=original, protected=bpy.data.images[manifest["before"]["protected"]["name"]], helper=helper,
                     materials=[bpy.data.materials[item["name"]] for item in manifest["before"]["materials"]],
                     objects=[bpy.data.objects[item["name"]] for item in manifest["before"]["objects"]])
        pixels(scope["protected"])
        pixels(helper)
        expected = footprint["expected"]
        verify("fresh_saved_native_OWNER_graph_and_portable_original", forward_expected(), fresh=True)
        report["saved_native_OWNER_reference_resolved_original"] = True
        report["fresh_process_pointer_or_UID_equality_claimed"] = False

    def finish():
        report.update(completed=True, phase_seconds=time.monotonic() - started,
                      memory=linux_process_memory(), retained_helper_and_backup_footprint=True,
                      exact_pre_helper_rollback_claimed=False, visual_appearance_reviewed=False)
        persist()
        raw = report_path.read_bytes()
        marker = "BLENDER_CURRENT_PIXELS_PAIRED_RECOVERY_" + options.bridge_phase.upper() + "_OK "
        print(marker + json.dumps({"blender_version": bpy.app.version_string, "profile": options.bridge_profile,
              "phase": options.bridge_phase, "process_instance": token, "process_id": os.getpid(),
              "evidence": {"path": str(report_path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
              "private_native_prerequisite_only": True, "public_lifecycle_qualified": False}), flush=True)
        owned_process_exit(0)

    def tick():
        nonlocal state, remaining
        try:
            assert time.monotonic() - started <= PHASE_SECONDS, "Native fixture phase deadline exceeded"
            if state == "start":
                bpy.context.preferences.use_preferences_save = False
                bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
                bpy.context.preferences.filepaths.save_version = 0
                available, free = linux_available_memory(), shutil.disk_usage(bundle).free
                report["preflight"] = {"available_memory_bytes": available, "filesystem_free_bytes": free,
                    "required_memory_bytes": MIN_MEMORY if large else 0, "required_filesystem_free_bytes": MIN_DISK if large else 0,
                    "measurement_is_reservation_or_cap": False}
                persist()  # Retain refusal facts before the assertions/large allocation.
                resource_check(available, free, large=large)
                if options.bridge_phase == "writer":
                    setup_writer()
                else:
                    setup_reader()
                state, remaining = "packed_deferred", 3
                return .05
            if state == "packed_deferred":
                verify("packed_deferred_timer_turn_" + str(4 - remaining), forward_expected(), fresh=options.bridge_phase == "reader")
                remaining -= 1
                if remaining:
                    return .05
                if options.bridge_phase == "writer":
                    save_fixture()
                reverse(fresh=options.bridge_phase == "reader")
                state, remaining = "recovered_deferred", 3
                return .05
            assert state == "recovered_deferred"
            verify("recovered_deferred_timer_turn_" + str(4 - remaining), expected, fresh=options.bridge_phase == "reader")
            remaining -= 1
            if remaining:
                return .05
            finish()
        except Exception:
            report.update(failure=traceback.format_exc(), stage=state, phase_seconds=time.monotonic() - started,
                          memory=linux_process_memory())
            persist()
            traceback.print_exc()
            owned_process_exit(1)
        return None

    # The reader opens its owned .blend in the first turn. Keep this genuine
    # timer registered across that load; otherwise no deferred checks execute.
    bpy.app.timers.register(tick, first_interval=.05, persistent=True)


if __name__ == "__main__":
    main()
