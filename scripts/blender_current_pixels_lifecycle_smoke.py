"""Opt-in metadata or finite native graph reads; no lifecycle is exercised.

Import is inert. The first profile only reads class RNA declarations in a fresh,
owned, background factory process. It never reads Blender data instances.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from array import array
from pathlib import Path
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "RNA_CENSUS_ONLY_V1"
MARKER = "BLENDER_CURRENT_PIXELS_LIFECYCLE_CENSUS_OK "
MAX_REPORT = 2 * 1024 * 1024
REPORT_NAME = "current-pixels-census.json"
GRAPH_PROFILE = "CURRENT_PIXELS_NATIVE_SOURCE_GRAPH_V1"
GRAPH_MARKER = "BLENDER_CURRENT_PIXELS_SOURCE_GRAPH_OK "
GRAPH_REPORT_NAME = "current-pixels-source-graph.json"
GRAPH_ASSERTIONS = frozenset({"positive_complete_graph", "repeat_complete_graph", "four_grant_denials",
    "native_owner_refusal", "unloaded_helper_refusal", "unlisted_consumer_refusal", "instancer_refusal",
    "manual_geometry_detected", "manual_uv_detected", "manual_mapping_detected", "manual_socket_detected",
    "manual_pixel_detected", "cancel_safe_point", "source_binding_refusal", "provider_binding_refusal",
    "invalid_context_refusal", "no_observation_writes", "source_unchanged"})
BUILDS = frozenset({((4, 5, 14), b"62c1db4208e8"), ((5, 2, 2), b"d13f752e3b9c")})


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def source_fingerprints():
    """Bind all in-tree add-on Python plus both native fixture entry points."""
    paths = [ROOT / "scripts/blender_current_pixels_lifecycle_smoke.py",
             ROOT / "scripts/run_blender_checks.py"]
    paths.extend(sorted((ROOT / "addon/blender_codex_bridge").rglob("*.py")))
    assert 3 <= len(paths) <= 512
    result = {}
    for path in paths:
        assert not path.is_symlink() and path.resolve(strict=True).is_relative_to(ROOT)
        assert path.stat().st_size <= 2 * 1024 * 1024
        result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert "addon/blender_codex_bridge/current_pixels_graph.py" in result
    return result


def owned_profile(report):
    """Accept only the runner's disposable profile and fixed output sibling."""
    assert sys.platform == "linux", "This census currently qualifies official Linux builds only"
    assert report.is_absolute() and report.name in {REPORT_NAME, GRAPH_REPORT_NAME}
    parent = report.parent
    assert not parent.is_symlink() and parent.resolve(strict=True) == parent
    info = parent.stat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
    assert stat.S_IMODE(info.st_mode) == 0o700
    assert not report.exists() and not report.is_symlink()
    assert all(os.environ.get(key) == str(parent) for key in ("TEMP", "TMP", "TMPDIR"))
    for key in ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        directory = parent / ("worker-profile-" + key.lower())
        assert os.environ.get(key) == str(directory)
        assert not directory.is_symlink() and directory.is_dir()
    assert Path.cwd() == parent / "working"
    assert "PYTHONPATH" not in os.environ and "PYTHONHOME" not in os.environ
    token = os.environ.get("BRIDGE_TEST_PROCESS_TOKEN", "")
    assert len(token) == 32 and all(c in "0123456789abcdef" for c in token)
    return token


def write_receipt(report, proof):
    """Create a bounded private receipt, then bind the bytes independently read."""
    payload = canonical_json(proof) + b"\n"
    assert 0 < len(payload) <= MAX_REPORT, "Census receipt exceeds the complete report bound"
    descriptor = os.open(report, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        assert stream.write(payload) == len(payload)
        stream.flush()
        os.fsync(stream.fileno())
    assert not report.is_symlink() and report.stat().st_size == len(payload)
    with report.open("rb") as stream:
        reopened = stream.read(MAX_REPORT + 1)
    assert reopened == payload
    return {"path": str(report), "bytes": len(reopened),
            "sha256": hashlib.sha256(reopened).hexdigest()}


def native_graph_probe(bpy, graph, before, parent):
    """Actual native data and grants; NOT public SourceOrigin admission.

    All seeds, operators and extra-ID allocation precede the immutable read
    boundary. Later deliberate fault writes are named fixture manual edits,
    outside each observation window; no Scene/operator/Main reset follows it.
    """
    import inspect
    import resource
    import shutil

    from blender_codex_bridge import current_pixels_files as files
    from blender_codex_bridge import current_pixels_source as source
    from blender_codex_bridge import pixel_codecs
    from blender_codex_bridge import runtime as runtime_module
    from blender_codex_bridge.errors import BridgeError
    from blender_codex_bridge.permissions import Permission, PermissionManager
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.tools import image_portability as storage

    assert Path(source.__file__).resolve(strict=True) == ROOT / "addon/blender_codex_bridge/current_pixels_source.py"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module="blender_codex_bridge")
    runtime, prefs = runtime_module.get_runtime(), get_preferences()
    assert type(runtime) is runtime_module.BridgeRuntime and runtime._registered
    assert type(runtime.permissions) is PermissionManager and prefs is not None
    runtime.registry.enable_toolset("materials")
    prefs.allow_execute_python = prefs.allow_delete_objects = False
    grants = ("allow_inspect_scene", "allow_edit_materials", "allow_external_files", "allow_save_project")
    required = (Permission.INSPECT_SCENE, Permission.EDIT_MATERIALS, Permission.ACCESS_EXTERNAL_FILES, Permission.SAVE_PROJECT)
    for name in grants:
        setattr(prefs, name, True)
    prefs.texture_directory = str(parent)
    setup_folder, backups = parent / "setup-exr", parent / "lifecycle-backups"
    setup_folder.mkdir(mode=0o700)
    backups.mkdir(mode=0o700)
    old = array("f", [-0., .25, .5, 1.]) * 4
    edited = array("f", [.125, -.25, 2., .5]) * 4

    def digest(values):
        copied = array("f", values)
        if sys.byteorder != "little":
            copied.byteswap()
        return hashlib.sha256(copied.tobytes()).hexdigest()

    def encode(values):
        return b"".join(step.data for step in pixel_codecs.encode_steps(values, 2, 2, "EXR32_RAW", "DATA"))

    previous, current = encode(old), encode(edited)
    seed = setup_folder / "original.exr"
    seed.write_bytes(previous)
    original = bpy.data.images.load(str(seed), check_existing=False)
    original.name = "Current pixels original"
    original.colorspace_settings.name, original.alpha_mode = "Non-Color", "CHANNEL_PACKED"
    original.pack(data=previous, data_len=len(previous))
    original.pixels.foreach_set(edited)
    original.update()
    helper = bpy.data.images.new("Retained current pixels", 2, 2, alpha=True, float_buffer=True)
    helper.source, helper.filepath, helper.file_format = "FILE", "", "OPEN_EXR"
    helper.colorspace_settings.name, helper.alpha_mode = "Non-Color", "CHANNEL_PACKED"
    helper.pack(data=current, data_len=len(current))
    helper.buffers_free()
    loaded = array("f", [0.]) * 16
    helper.pixels.foreach_get(loaded)  # Explicit owned setup, never preview decode.
    assert digest(loaded) == digest(edited)
    metadata = {"schema_version": 1, "mode": "CURRENT_PIXELS", "width": 2, "height": 2,
        "source": "FILE", "colorspace": "Non-Color", "alpha_mode": "CHANNEL_PACKED", "is_float": True,
        "pixels_sha256_float32_le": digest(edited), "packed_sha256": hashlib.sha256(current).hexdigest()}
    helper[storage.METADATA_KEY], helper[storage.OWNER_KEY] = canonical_json(metadata).decode(), original
    helper.use_fake_user = True
    material = bpy.data.materials.new("Current pixels material")
    material.use_nodes = True
    tree = material.node_tree
    texture = tree.nodes.new("ShaderNodeTexImage")
    texture.image = original
    shader = next(node for node in tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled")
    tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    mesh = bpy.data.meshes.new("Current pixels triangle")
    mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
    uv = mesh.uv_layers.new(name="UVMap")
    uv_attribute = mesh.attributes[uv.name]
    for item, value in zip(uv_attribute.data, ((0., 0.), (1., 0.), (0., 1.)), strict=True):
        item.vector = value
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Current pixels consumer", mesh)
    owning_collection = bpy.data.collections.new("Current pixels owning collection")
    bpy.context.scene.collection.children.link(owning_collection)
    owning_collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    # All IDs for later negative comparisons are allocated before the boundary.
    extra_material = bpy.data.materials.new("Unlisted consumer fixture")
    extra_material.use_nodes = True
    extra_texture = extra_material.node_tree.nodes.new("ShaderNodeTexImage")
    extra_texture.image = None
    instancer = bpy.data.objects.new("Unlinked instancer fixture", None)
    instancer.instance_type = "COLLECTION"
    other = bpy.data.images.new("Other native OWNER fixture", 2, 2, alpha=True, float_buffer=True)
    bpy.context.view_layer.update()
    assertions, refusals, timings = {}, [], []
    # This operator/context negative is part of setup, before the final boundary.
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        source._context_witness(bpy)
    except BridgeError as error:
        assert error.code == "NOT_IMPLEMENTED"
        assertions["invalid_context_refusal"] = True
    else:
        raise AssertionError("Edit Mode context was admitted")
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    assert original.is_dirty and original.has_data and helper.has_data
    provider, manager = runtime.permissions._source, runtime.permissions
    assert type(provider) is FunctionType and provider.__globals__ is vars(runtime_module)
    provider_codes = tuple(value for value in inspect.getattr_static(runtime_module.BridgeRuntime, "__init__").__code__.co_consts
        if type(value) is type(provider.__code__) and value.co_names == ("permission_snapshot", "_preferences"))
    assert len(provider_codes) == 1 and provider.__code__ is provider_codes[0]
    callbacks = (graph.capture_graph, graph.identity_witness, source._context_witness, source._available_memory)
    callback_facts = tuple((function, function.__code__, function.__globals__) for function in callbacks)
    deadline = time.monotonic() + 250.
    control = {"cancel": False, "foreign": 0, "captures": 0, "checks": 0}

    def pure_check():
        control["checks"] += 1
        assert time.monotonic() < deadline
        assert not control["cancel"], "Owned graph read cancelled"
        assert runtime.permissions is manager and manager._source is provider, "Provider binding changed"
        actual = (graph.capture_graph, graph.identity_witness, source._context_witness, source._available_memory)
        assert all(function is expected and function.__code__ is code and function.__globals__ is namespace
                   for function, (expected, code, namespace) in zip(actual, callback_facts, strict=True)), "Source binding changed"
        assert bpy.context.mode == "OBJECT"

    def pixels(image):
        if not image.has_data:
            return None
        values = array("f", [0.]) * 16
        image.pixels.foreach_get(values)
        return digest(values)

    def observed():
        rows = []
        for image in (original, helper):
            loaded = image.has_data
            payload = image.packed_file.data if loaded else None
            rows.append({"name": image.name, "pointer": image.as_pointer(), "uid": image.session_uid,
                "loaded": loaded, "pixels": pixels(image), "packed": None if payload is None else hashlib.sha256(payload).hexdigest(),
                "filepath": image.filepath, "roles": [image.colorspace_settings.name, image.alpha_mode],
                "dirty": image.is_dirty if loaded else None, "fake_user": image.use_fake_user,
                "keys": sorted(image.keys())})
        return {"images": rows, "owner": helper[storage.OWNER_KEY].as_pointer(), "metadata": helper[storage.METADATA_KEY],
            "vertices": [list(item.co) for item in mesh.vertices],
            "uv": [list(item.vector) for item in uv_attribute.data],
            "mapping": list(texture.texture_mapping.translation),
            "socket": shader.inputs["Roughness"].default_value,
            "nodes": [(node.name, node.bl_idname) for node in tree.nodes],
            "links": [(link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier) for link in tree.links],
            "matrix": [list(row) for row in obj.matrix_world], "mode": bpy.context.mode,
            "active": bpy.context.view_layer.objects.active.as_pointer(),
            "selected": sorted(item.as_pointer() for item in bpy.context.selected_objects),
            "frame": bpy.context.scene.frame_current, "backup_files": sorted(path.name for path in backups.iterdir()),
            "seed_sha256": hashlib.sha256(seed.read_bytes()).hexdigest()}

    def capture():
        pure_check()
        witness = graph.identity_witness(bpy, original.name, helper.name, [material.name], check=pure_check)
        context = source._context_witness(bpy)
        manager.require(required)
        pure_check()
        assert witness == graph.identity_witness(bpy, original.name, helper.name, [material.name], check=pure_check)
        assert context == source._context_witness(bpy)
        plan = files.freeze_backup_plan(str(backups), "read-only", str(parent), True, pure_check)
        memory, disk = source._available_memory(), shutil.disk_usage(plan.parent).free
        started = time.monotonic()
        control["captures"] += 1
        result = graph.capture_graph(bpy, original.name, helper.name, [material.name], check=pure_check,
            available_memory_bytes=memory, available_disk_bytes=disk)
        timings.append({"full_read_seconds": time.monotonic() - started, "memory_available": memory, "disk_available": disk})
        pure_check()
        return result

    def unchanged(call):
        baseline = observed()
        try:
            return call()
        finally:
            assert observed() == baseline, "Native observation changed owned state"

    before_read = observed()
    first = unchanged(capture)
    second = unchanged(capture)
    assert first.summary() | {"resource_facts": None} == second.summary() | {"resource_facts": None}
    assert first.payloads.current_pixels.tobytes() == edited.tobytes()
    assert first.payloads.original_packed == previous and first.payloads.snapshot_packed == current
    assertions["positive_complete_graph"] = assertions["repeat_complete_graph"] = True
    for name in grants:
        setattr(prefs, name, False)
        count = control["captures"]
        try:
            unchanged(capture)
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED" and control["captures"] == count
            refusals.append({"kind": "grant", "preference": name, "code": error.code})
        else:
            raise AssertionError("Denied current grant reached full reader")
        finally:
            setattr(prefs, name, True)
    assertions["four_grant_denials"] = len(refusals) == 4

    def refused(label, inject, restore, expected):
        inject()  # Named external/manual fixture edit, outside observation.
        try:
            try:
                unchanged(capture)
            except BridgeError as error:
                assert error.code == "NOT_IMPLEMENTED" and expected(error.context.get("reason", ""))
                refusals.append({"kind": label, "reason": error.context.get("reason")})
                assertions[label] = True
            else:
                raise AssertionError(label + " was admitted")
        finally:
            restore()

    refused("native_owner_refusal", lambda: helper.__setitem__(storage.OWNER_KEY, other),
        lambda: helper.__setitem__(storage.OWNER_KEY, original), lambda value: "OWNER" in value)
    refused("unlisted_consumer_refusal", lambda: setattr(extra_texture, "image", original),
        lambda: setattr(extra_texture, "image", None), lambda value: "CONSUMER" in value or "USER" in value)
    refused("instancer_refusal", lambda: setattr(instancer, "instance_collection", owning_collection),
        lambda: setattr(instancer, "instance_collection", None), lambda value: "INSTANC" in value or "COLLECTION" in value)
    def reload_helper():
        values = array("f", [0.]) * 16
        helper.pixels.foreach_get(values)  # Explicit fixture rehydration, outside observation.
        assert digest(values) == digest(edited)
    refused("unloaded_helper_refusal", helper.buffers_free, reload_helper, lambda value: value == "TARGET_BUFFER_UNLOADED")

    def changed(label, target, field, value):
        old_value = getattr(target, field)
        setattr(target, field, value)
        try:
            candidate = unchanged(capture)
            assert candidate.full_native_prefix_sha256 != first.full_native_prefix_sha256
            assertions[label] = True
        finally:
            setattr(target, field, old_value)
    changed("manual_geometry_detected", mesh.vertices[0].co, "x", .25)
    changed("manual_uv_detected", uv_attribute.data[0].vector, "x", .25)
    changed("manual_mapping_detected", texture.texture_mapping.translation, "x", .25)
    changed("manual_socket_detected", shader.inputs["Roughness"], "default_value", .25)
    altered = array("f", edited)
    altered[0] = .75
    def write_pixels(values):
        original.pixels.foreach_set(values)
        original.update()
    refused("manual_pixel_detected", lambda: write_pixels(altered), lambda: write_pixels(edited),
        lambda value: value == "SNAPSHOT_CURRENT_CHANNELS_DIFFER")
    control["cancel"] = True
    try:
        unchanged(capture)
    except AssertionError as error:
        assert "cancelled" in str(error)
        assertions["cancel_safe_point"] = True
    finally:
        control["cancel"] = False
    def foreign(*_args, **_kwargs):
        control["foreign"] += 1
        raise AssertionError("Foreign callback invoked")
    for label, owner, name, restored in (("source_binding_refusal", graph, "capture_graph", callbacks[0]),
                                         ("provider_binding_refusal", manager, "_source", provider)):
        setattr(owner, name, foreign)  # Negative-only injection; never called.
        try:
            unchanged(capture)
        except AssertionError as error:
            assert "binding changed" in str(error).lower() and control["foreign"] == 0
            assertions[label] = True
        finally:
            setattr(owner, name, restored)
    assert observed() == before_read and not list(backups.iterdir())
    assertions["no_observation_writes"] = True
    assert source_fingerprints() == before
    assertions["source_unchanged"] = True
    assert set(assertions) == GRAPH_ASSERTIONS and all(value is True for value in assertions.values())
    return {"assertions": assertions, "refusals": refusals, "full_read_intervals": timings,
        "checks": control["checks"], "foreign_callbacks": control["foreign"],
        "baseline": first.summary(), "independent_observation": before_read,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "setup": {"owned_empty_factory": True, "writes_before_read_boundary": ["factory setup", "local grants",
            "setup EXR", "original edited buffer", "retained helper", "Material/Object/Mesh/UV/nodes", "preallocated negative IDs"],
            "intentional_manual_edits_separate_from_observation": True, "setup_files": [str(seed)],
            "lifecycle_backup_files": [], "production_files_written": False},
        "limitations": {"current_pixels_origin_qualified": False, "public_tool_acceptance": False,
            "provider_source_refusal_is_owned_probe_guard_only": True,
            "first_authorization_pixel_only_change_detection": False, "trusted_canonical_native_registry": True,
            "native_lookup_hard_preemption": False, "project_saved": False, "restoration_qualified": False,
            "visual_reviewed": False, "windows_qualified": False}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--bridge-census-only", action="store_true")
    modes.add_argument("--bridge-source-graph", action="store_true")
    parser.add_argument("--bridge-report", type=Path, required=True)
    arguments = sys.argv[sys.argv.index("--") + 1:] if argv is None and "--" in sys.argv else argv
    args = parser.parse_args(arguments)
    assert args.bridge_report.name == (GRAPH_REPORT_NAME if args.bridge_source_graph else REPORT_NAME)
    token = owned_profile(args.bridge_report)
    import bpy

    assert bpy.app.background and "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    assert (tuple(bpy.app.version), bpy.app.build_hash) in BUILDS
    assert bpy.app.build_type == b"Release"
    before = source_fingerprints()
    addon = str(ROOT / "addon")
    sys.path.insert(0, addon)
    from blender_codex_bridge import current_pixels_graph as graph

    assert Path(graph.__file__).resolve(strict=True) == ROOT / "addon/blender_codex_bridge/current_pixels_graph.py"
    if args.bridge_source_graph:
        started = time.monotonic()
        result = native_graph_probe(bpy, graph, before, args.bridge_report.parent)
        assert source_fingerprints() == before, "Source changed during native graph probe"
        proof = {"completed": True, "profile": GRAPH_PROFILE, "scope": "native_source_graph_read_only",
            "lifecycle_functional_acceptance": False, "current_pixels_origin_qualified": False, "windows_qualified": False,
            "process_instance": token, "process_id": os.getpid(), "blender_version": bpy.app.version_string,
            "source_build": bpy.app.build_hash.decode("ascii"), "source_fingerprints": before,
            "source_snapshot_sha256": hashlib.sha256(canonical_json(before)).hexdigest(),
            "probe_seconds": time.monotonic() - started, **result}
        receipt = write_receipt(args.bridge_report, proof)
        compact = {key: proof[key] for key in ("completed", "profile", "scope", "process_instance", "process_id",
            "blender_version", "source_build", "source_snapshot_sha256", "lifecycle_functional_acceptance",
            "current_pixels_origin_qualified", "windows_qualified")}
        compact["full_receipt"] = receipt
        print(GRAPH_MARKER + canonical_json(compact).decode(), flush=True)
        return
    started = time.monotonic()
    catalog = graph.catalog_census(bpy.types, bpy.app.build_hash)
    assert type(catalog) is dict and catalog["schema"] == "current_pixels_complete_class_census_v1"
    assert catalog["build_hash"] == bpy.app.build_hash.decode("ascii")
    assert type(catalog["classes"]) is dict and len(catalog["classes"]) == 57
    assert set(catalog["classes"]) == set(graph.CENSUS_TYPES)
    elapsed = time.monotonic() - started
    assert source_fingerprints() == before, "Census source changed during execution"
    proof = {"completed": True, "profile": PROFILE, "scope": "class_metadata_only",
             "lifecycle_functional_acceptance": False, "windows_qualified": False,
             "process_instance": token, "process_id": os.getpid(),
             "blender_version": bpy.app.version_string, "source_build": bpy.app.build_hash.decode("ascii"),
             "source_fingerprints": before,
             "source_snapshot_sha256": hashlib.sha256(canonical_json(before)).hexdigest(),
             "catalog_seconds": elapsed, "catalog": catalog}
    receipt = write_receipt(args.bridge_report, proof)
    compact = {key: proof[key] for key in ("completed", "profile", "scope", "process_instance", "process_id",
               "blender_version", "source_build", "source_snapshot_sha256", "lifecycle_functional_acceptance",
               "windows_qualified")}
    compact["full_receipt"] = receipt
    print(MARKER + canonical_json(compact).decode("utf-8"), flush=True)


if __name__ == "__main__":
    main()
