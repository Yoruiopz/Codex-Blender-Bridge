"""Opt-in metadata, native graph reads or private queued image workflows.

Import is inert. The first profile only reads class RNA declarations in a fresh,
owned, background factory process. It never reads Blender data instances.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
LOADED_PROFILE = "CURRENT_PIXELS_QUEUED_LOADED_BACKUP_SMALL_V2"
LOADED_MARKER = "BLENDER_CURRENT_PIXELS_LOADED_BACKUP_OK "
LOADED_REPORT_NAME = "current-pixels-loaded-backup.json"
LOADED_BACKUP_JOB_SECONDS = 60.
HELPER_RECORD_PROFILE = "CURRENT_PIXELS_QUEUED_HELPER_RECORD_SMALL_V1"
HELPER_RECORD_SCOPE = "fixture_only_queued_archive_and_helper_record"
HELPER_RECORD_MARKER = "BLENDER_CURRENT_PIXELS_HELPER_RECORD_OK "
HELPER_RECORD_REPORT_NAME = "current-pixels-helper-record.json"
HELPER_COMMIT_POLL_MS = 30000
HELPER_LIFECYCLE_KEY = "_codex_bridge_current_pixels_lifecycle_v1"
SCENE_CHECKPOINT_KEY = "_codex_bridge_undo_marker"
ACQUISITION_PROFILE = "CURRENT_PIXELS_QUEUED_ACQUISITION_SMALL_V1"
ACQUISITION_MARKER = "BLENDER_CURRENT_PIXELS_ACQUISITION_OK "
ACQUISITION_REPORT_NAME = "current-pixels-acquisition.json"
ACQUISITION_ACK_MS = 3000
ACQUISITION_CONTROL_MS = 10000
INTERRUPTION_PROFILE = "CURRENT_PIXELS_QUEUED_BACKUP_INTERRUPTION_SMALL_V1"
INTERRUPTION_MARKER = "BLENDER_CURRENT_PIXELS_BACKUP_INTERRUPTION_OK "
INTERRUPTION_REPORT_NAME = "current-pixels-backup-interruption.json"
INTERRUPTION_PREFIX = "queued-current-pixels"
INTERRUPTION_SAMPLES = 4
INTERRUPTION_ASSERTIONS = frozenset({
    "fixture_only_registration", "normal_registry_unchanged", "canonical_runtime", "real_socket_timer",
    "both_acknowledgements_unfrozen_under_three_seconds", "terminal_preview_hashes", "observed_oldpacked_staging_write",
    "queued_explicit_cancellation", "exact_partial_archive_only", "no_late_file_effects",
    "no_image_helper_or_project_write", "source_helper_and_protected_unchanged", "source_unchanged",
})
ACQUISITION_GRANTS = ("allow_inspect_scene", "allow_edit_materials", "allow_external_files", "allow_save_project")
FIXTURE_BOOLEAN_DOMAINS = {".select_vert": "POINT", ".select_edge": "EDGE", ".select_poly": "FACE",
    "sharp_face": "FACE", ".pn.UVMap": "CORNER", ".uv_select_vert": "CORNER",
    ".uv_select_edge": "CORNER", ".uv_select_face": "FACE"}
ACQUISITION_ASSERTIONS = frozenset({
    "fixture_only_registration", "normal_registry_unchanged", "canonical_runtime", "real_socket_timer",
    "four_grant_denials", "prompt_acknowledgement", "terminal_preview_hashes", "observable_nonterminal_progress",
    "queued_cancellation", "source_helper_and_protected_unchanged", "no_files_written", "source_unchanged",
})
LOADED_ASSERTIONS = frozenset({"fixture_only_registration", "normal_registry_unchanged", "canonical_runtime",
    "real_socket_timer", "both_starters_four_grant_denials", "both_acknowledgements_unfrozen_under_three_seconds",
    "terminal_preview_hashes", "preview_files_unchanged",
    "source_helper_and_protected_unchanged", "backup_only_queued_start", "backups_independently_reopened",
    "no_image_or_helper_write", "source_unchanged"})
HELPER_RECORD_ASSERTIONS = ((LOADED_ASSERTIONS - {"source_helper_and_protected_unchanged",
    "backup_only_queued_start", "no_image_or_helper_write"}) | {
    "exact_helper_record_bound_to_manifest", "native_checkpoint_created_and_finalized",
    "original_helper_content_and_protected_unchanged", "only_helper_record_and_reserved_scene_marker_written",
})
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


def owned_profile(report, *, private_display=None):
    """Accept only the runner's disposable profile and fixed output sibling."""
    assert sys.platform == "linux", "This census currently qualifies official Linux builds only"
    assert report.is_absolute() and report.name in {REPORT_NAME, GRAPH_REPORT_NAME, LOADED_REPORT_NAME,
                                                   ACQUISITION_REPORT_NAME, INTERRUPTION_REPORT_NAME, HELPER_RECORD_REPORT_NAME}
    parent = report.parent
    assert not parent.is_symlink() and parent.resolve(strict=True) == parent
    info = parent.stat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
    assert stat.S_IMODE(info.st_mode) == 0o700
    assert not report.exists() and not report.is_symlink()
    assert all(os.environ.get(key) == str(parent) for key in ("TEMP", "TMP", "TMPDIR"))
    for key in ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        if key == "XDG_RUNTIME_DIR" and private_display is not None:
            assert os.environ[key] == private_display["manifest"]["xdg_runtime_dir"]
            continue
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


def prepare_fixture_boolean_storage(mesh, expected_uv):
    """Materialize only reviewed native flags on the owned 5.2 triangle during setup."""
    lengths = {"POINT": len(mesh.vertices), "EDGE": len(mesh.edges),
               "CORNER": len(mesh.loops), "FACE": len(mesh.polygons)}

    def geometry():
        return (tuple(tuple(vertex.co) for vertex in mesh.vertices),
                tuple(tuple(edge.vertices) for edge in mesh.edges),
                tuple(tuple(face.vertices) for face in mesh.polygons),
                tuple((loop.vertex_index, loop.edge_index) for loop in mesh.loops))

    def uv_roles():
        layer = mesh.uv_layers["UVMap"]
        clone = mesh.uv_layer_clone
        return layer.active_render, layer.active_clone, None if clone is None else clone.name

    geometry_before = geometry()
    roles = uv_roles()
    assert roles == (True, False, None)
    assert mesh.attributes["UVMap"].storage_type == "ARRAY"
    assert tuple(tuple(item.vector) for item in mesh.attributes["UVMap"].data) == expected_uv
    singles = tuple(sorted(attribute.name for attribute in mesh.attributes if attribute.storage_type == "SINGLE"))
    # Refuse unreviewed storage or declarations before accessing any SINGLE payload.
    assert all(name in FIXTURE_BOOLEAN_DOMAINS and mesh.attributes[name].data_type == "BOOLEAN"
               and mesh.attributes[name].domain == FIXTURE_BOOLEAN_DOMAINS[name] for name in singles)
    transitions = []
    for name in singles:
        domain = FIXTURE_BOOLEAN_DOMAINS[name]
        values = tuple(item.value for item in mesh.attributes[name].data)
        assert len(values) == lengths[domain] and len(set(values)) == 1 and type(values[0]) is bool
        materialized = mesh.attributes[name]
        assert materialized.storage_type == "ARRAY"
        assert tuple(item.value for item in materialized.data) == values
        transitions.append({"name": name, "domain": domain, "data_type": "BOOLEAN",
                            "before": "SINGLE", "after": "ARRAY", "count": len(values), "uniform_value": values[0]})
    assert geometry() == geometry_before
    uv_attribute = mesh.attributes["UVMap"]
    assert tuple(tuple(item.vector) for item in uv_attribute.data) == expected_uv and uv_roles() == roles
    return uv_attribute, {"phase": "owned_setup_before_baseline", "transitions": transitions,
                          "geometry_preserved": True, "uv_values_preserved": True, "uv_roles_preserved": True}


def native_graph_probe(bpy, graph, before, parent, *, loaded_backup=None):
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
    expected_uv = ((0., 0.), (1., 0.), (0., 1.))
    for item, value in zip(uv_attribute.data, expected_uv, strict=True):
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
    # The existing background graph probe owns this operator-context negative.
    # An interactive timer after factory reset has no Edit Mode operator context;
    # queued preview/backup needs only the ordinary Object Mode data context.
    storage_setup = None
    if loaded_backup is None:
        assert bpy.ops.object.mode_set(mode="EDIT") == {"FINISHED"}
        try:
            source._context_witness(bpy)
        except BridgeError as error:
            assert error.code == "NOT_IMPLEMENTED"
            assertions["invalid_context_refusal"] = True
        else:
            raise AssertionError("Edit Mode context was admitted")
        assert bpy.ops.object.mode_set(mode="OBJECT") == {"FINISHED"}
        bpy.context.view_layer.update()
        # Edit Mode replaces attribute storage. Reacquire the declared UV wrapper.
        uv_attribute = mesh.attributes["UVMap"]
        assert tuple(tuple(item.vector) for item in uv_attribute.data) == expected_uv
    if bpy.app.build_hash == b"d13f752e3b9c":
        uv_attribute, storage_setup = prepare_fixture_boolean_storage(mesh, expected_uv)
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
        if loaded_backup is not None:
            layer = bpy.context.view_layer
            selected = sorted(item.as_pointer() for item in layer.objects if item.select_get(view_layer=layer))
        else:
            selected = sorted(item.as_pointer() for item in bpy.context.selected_objects)
        for image in (original, helper):
            loaded = image.has_data
            payload = image.packed_file.data if loaded else None
            rows.append({"name": image.name, "pointer": image.as_pointer(), "uid": image.session_uid,
                "loaded": loaded, "pixels": pixels(image), "packed": None if payload is None else hashlib.sha256(payload).hexdigest(),
                "filepath": image.filepath, "roles": [image.colorspace_settings.name, image.alpha_mode],
                "dirty": image.is_dirty if loaded else None, "fake_user": image.use_fake_user,
                "keys": sorted(image.keys())})
        active = bpy.context.view_layer.objects.active
        state = {"images": rows, "owner": helper[storage.OWNER_KEY].as_pointer(), "metadata": helper[storage.METADATA_KEY],
            "vertices": [list(item.co) for item in mesh.vertices],
            "uv": [list(item.vector) for item in uv_attribute.data],
            "mapping": list(texture.texture_mapping.translation),
            "socket": shader.inputs["Roughness"].default_value,
            "nodes": [(node.name, node.bl_idname) for node in tree.nodes],
            "links": [(link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier) for link in tree.links],
            "matrix": [list(row) for row in obj.matrix_world], "mode": bpy.context.mode,
            "active": None if active is None else active.as_pointer(),
            "selected": selected,
            "frame": bpy.context.scene.frame_current, "backup_files": sorted(path.name for path in backups.iterdir()),
            "seed_sha256": hashlib.sha256(seed.read_bytes()).hexdigest()}
        if loaded_backup is None and bpy.app.build_hash == b"d13f752e3b9c":
            state["principled_panels"] = [(panel.identifier, panel.is_collapsed, panel.as_pointer())
                                          for panel in shader.panel_states]
            clone = mesh.uv_layer_clone
            state["uv_roles"] = {"layers": [(layer.name, layer.active_render, layer.active_clone) for layer in mesh.uv_layers],
                                 "clone_layer": None if clone is None else clone.name}
        return state

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
    if loaded_backup is not None:
        def start_queued():
            return _loaded_backup_probe(bpy, before, parent, runtime, prefs, original, helper, other,
                material, backups, previous, current, edited, observed, original_decoded_sha256=digest(old),
                storage_setup=storage_setup, **loaded_backup)

        if loaded_backup.get("helper_record"):
            # Factory reset discarded the timer's original window context.
            # Give the owned editor a turn before taking a fixture-only undo snapshot.
            def after_factory_reset():
                from traceback import print_exc

                from blender_artist_sidebar_smoke import owned_process_exit

                try:
                    return start_queued()
                except BaseException:
                    print_exc()
                    owned_process_exit(1)

            bpy.app.timers.register(after_factory_reset, first_interval=0.25)
            return None
        return start_queued()
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
    if bpy.app.build_hash == b"d13f752e3b9c":
        panel_baseline = observed()
        panel = shader.panel_states[0]
        previous_collapse = panel.is_collapsed
        assert type(panel) is bpy.types.NodePanelState and panel.identifier == 9 and type(previous_collapse) is bool
        try:
            panel.is_collapsed = not previous_collapse
            candidate = unchanged(capture)
            assert panel.is_collapsed is (not previous_collapse)
            assert candidate.full_native_prefix_sha256 != first.full_native_prefix_sha256
            assert candidate.full_portable_prefix_sha256 != first.full_portable_prefix_sha256
            assert candidate.payloads.facts() == first.payloads.facts()
        finally:
            panel.is_collapsed = previous_collapse
        assert observed() == panel_baseline
        assertions["manual_panel_state_detected"] = True
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
    expected_assertions = GRAPH_ASSERTIONS
    if bpy.app.build_hash == b"d13f752e3b9c":
        expected_assertions = expected_assertions | {"manual_panel_state_detected"}
    assert set(assertions) == expected_assertions and all(value is True for value in assertions.values())
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


def require_starter_grants(request, control, method, arguments):
    for preference in ACQUISITION_GRANTS:
        control("grant", preference=preference, enabled=False)
        try:
            response, _row = request(method, arguments, timeout_ms=ACQUISITION_ACK_MS)
            assert response["ok"] is False and response["error"]["code"] == "PERMISSION_DENIED", response
        finally:
            control("grant", preference=preference, enabled=True)
        control("unchanged")


def start_deferred_job(request, method, arguments):
    response, row = request(method, arguments, timeout_ms=ACQUISITION_ACK_MS)
    assert response["ok"] is True and 0 <= row["elapsed_seconds"] <= 3., response
    ack = response["result"]
    assert ack["accepted"] is True and ack["job_completed"] is False
    assert ack["input_frozen_at_acceptance"] is False and ack["undo_boundary_created"] is False
    assert re.fullmatch(r"job_[0-9a-f]{32}", ack["job_id"])
    return ack


def wait_for_loaded_success(request, ack, transcript, seconds, polls=None, *, helper_record=False):
    params = {"job_id": ack["job_id"]}
    timeout_ms = HELPER_COMMIT_POLL_MS if helper_record else ACQUISITION_CONTROL_MS
    end, revision, count = time.monotonic() + seconds, ack["revision"], 0
    while time.monotonic() < end:
        response, row = request("jobs.inspect", params, retained=False, timeout_ms=timeout_ms)
        assert response["ok"] is True, response
        job = response["result"]
        assert job["job_id"] == ack["job_id"] and job["revision"] >= revision
        revision, count = job["revision"], count + 1
        if polls is not None and len(polls) < 256:
            polls.append({"revision": revision, "state": job["state"], "progress": job["progress"],
                          "elapsed_seconds": row["elapsed_seconds"]})
        if job["terminal"] is True:
            transcript.append(row)
            assert job["state"] == "SUCCEEDED" and job["undo_boundary_created"] is helper_record, job
            if helper_record:
                assert job["undo_boundary_finalized"] is True, job
            return job, count
        time.sleep(.02)
    raise AssertionError("Private current-pixels job exceeded the diagnostic deadline")


def preview_for_backup(request, control, preview_method, arguments, transcript):
    preview_ack = start_deferred_job(request, preview_method, arguments)
    preview_job, preview_polls = wait_for_loaded_success(request, preview_ack, transcript, 93.)
    preview = preview_job["result"]
    assert preview["phase"] == "preview" and re.fullmatch(r"[0-9a-f]{64}", preview["fingerprint"])
    assert re.fullmatch(r"[0-9a-f]{64}", preview["consumer_graph_sha256"])
    assert preview["backup_files_written"] is False and preview["image_packed"] is False
    control("preview_verified", preview=preview)
    start = {**arguments, "expected_target_fingerprint": preview["fingerprint"],
             "confirm_replace_packed_bytes": True, "confirm_discard_current_buffer": True,
             "time_limit_seconds": LOADED_BACKUP_JOB_SECONDS}
    return preview_ack, preview, start, preview_polls


def loaded_backup_requests(request, control, preview_method, pack_method, arguments, result, transcript, polls,
                           *, helper_record=False):
    """Obtain a reviewed preview then run the separate, deferred backup job."""
    require_starter_grants(request, control, preview_method, arguments)
    preview_ack, preview, start, preview_polls = preview_for_backup(request, control, preview_method, arguments, transcript)
    if helper_record:
        start["confirm_record_backup"] = True
    require_starter_grants(request, control, pack_method, start)
    accepted = start_deferred_job(request, pack_method, start)
    assert accepted["job_id"] != preview_ack["job_id"]
    job, count = wait_for_loaded_success(request, accepted, transcript, LOADED_BACKUP_JOB_SECONDS + 15., polls,
                                         helper_record=helper_record)
    assert job["result"]["phase"] == ("helper_record_verified" if helper_record else "backups_verified")
    assert job["result"]["image_packed"] is False and job["result"]["project_saved"] is False
    assert job["result"]["historical_archive"] is True and job["result"]["current_scene_match_verified"] is False
    recovery = job["recovery_evidence"]
    assert recovery["stage"] == "UNKNOWN" and recovery["state_known"] is False
    assert recovery.get("observed_prefix") is None and recovery.get("observed_prefix_sha256") is None
    assert recovery["durable_backups_verified"] is True
    assert recovery["helper_record_write_attempted"] is helper_record and recovery["image_write_attempted"] is False
    if helper_record:
        digest = job["result"]["lifecycle_record_sha256"]
        assert re.fullmatch(r"[0-9a-f]{64}", digest) and recovery["lifecycle_record_sha256"] == digest
        assert job["result"]["helper_record_verified"] is True
        assert recovery["helper_record_verified"] is True and recovery["project_saved"] is False
    assert len(transcript) == 12
    result.update(preview=preview, terminal=job, preview_poll_count=preview_polls, poll_count=count)


def backup_interruption_requests(request, control, preview_method, pack_method, arguments, result, transcript):
    preview_ack, preview, start, preview_polls = preview_for_backup(request, control, preview_method, arguments, transcript)
    ack = start_deferred_job(request, pack_method, start)
    assert ack["job_id"] != preview_ack["job_id"]
    params = {"job_id": ack["job_id"]}
    revision, cancel_requested = ack["revision"], False
    end = time.monotonic() + LOADED_BACKUP_JOB_SECONDS + 15.
    while time.monotonic() < end:
        response, row = request("jobs.inspect", params, retained=False, timeout_ms=ACQUISITION_CONTROL_MS)
        assert response["ok"] is True, response
        job = response["result"]
        assert job["job_id"] == ack["job_id"] and job["revision"] >= revision
        revision = job["revision"]
        if job["terminal"] is True:
            transcript.append(row)
            assert cancel_requested and job["state"] == "CANCELLED" and job["result"] is None, job
            assert job["undo_boundary_created"] is False and job["undo_boundary_finalized"] is False
            assert job["error"]["code"] == "TIMEOUT" and job["error"]["context"]["reason"] == "explicit cancellation"
            recovery = job["recovery_evidence"]
            assert recovery["stage"] == "UNKNOWN" and recovery["state_known"] is False
            assert recovery["external_write_attempted"] is True and recovery.get("durable_backups_verified", False) is False
            assert recovery["helper_record_write_attempted"] is False and recovery["image_write_attempted"] is False
            assert recovery["project_saved"] is False
            break
        progress = job["progress"]
        if not cancel_requested and job["state"] == "RUNNING" and progress["phase"] == "writing_oldpacked":
            assert progress["completed"] == progress["total"] == preview["payload_facts"]["original_packed_bytes"]
            transcript.append(row)
            response, _row = request("jobs.cancel", params, timeout_ms=ACQUISITION_CONTROL_MS)
            assert response["ok"] is True and response["result"]["state"] == "CANCELLING", response
            cancel = response["result"]
            assert cancel["job_id"] == ack["job_id"] and cancel["cancel_requested"] is True and cancel["terminal"] is False
            cancel_requested = True
        else:
            time.sleep(.005)
    else:
        raise AssertionError("Private archive cancellation exceeded the diagnostic deadline")

    samples = [control("interrupted_stable_sample", effects=job["external_effects"])]
    for _ in range(INTERRUPTION_SAMPLES - 1):
        time.sleep(.05)
        response, _row = request("jobs.inspect", params, timeout_ms=ACQUISITION_CONTROL_MS)
        assert response["ok"] is True and response["result"] == job, response
        sample = control("interrupted_stable_sample", effects=job["external_effects"])
        assert sample["tick"] > samples[-1]["tick"] and sample["artifacts"] == samples[0]["artifacts"]
        samples.append(sample)
    result.update(terminal=job, preview=preview, preview_poll_count=preview_polls, stability_samples=samples)


def interrupted_backup_artifacts(folder, previous, effects):
    """Read the owned partial namespace and independently verify old packed bytes."""
    final = folder / (INTERRUPTION_PREFIX + ".oldpacked.bin")
    stage = Path(effects["retained_staging_path"]) if effects["retained_staging_path"] is not None else None
    if stage is not None:
        assert stage.parent == folder and re.fullmatch(r"\.blender-codex-current-pixels-[a-z0-9_]{8}\.staging", stage.name)
        assert effects["staging_cleanup"] == "retained_unverified"
    published, uncertain = effects["file_published"], effects["publication_outcome_unknown"]
    assert type(published) is bool and type(uncertain) is bool and not (published and uncertain)
    assert effects["publication_attempted"] is (published or uncertain)
    assert effects["artifacts_truncated"] is False
    expected = sorted(path for path in (stage, final if published or uncertain else None) if path is not None)
    assert expected and sorted(folder.iterdir()) == expected
    if uncertain:
        assert stage is not None
    sha256 = hashlib.sha256(previous).hexdigest()
    reported = ([{"filepath": str(final), "file_bytes": len(previous) if published else None,
                  "file_sha256": sha256 if published else None}] if published or uncertain else [])
    assert effects["artifacts"] == reported

    def stable_identity(info):
        return (info.st_mode, info.st_size, info.st_dev, info.st_ino, info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)

    artifacts = []
    for path in expected:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            assert stat.S_ISREG(info.st_mode)
            assert info.st_size == len(previous) and info.st_nlink == len(expected)
            assert stream.read(len(previous) + 1) == previous
            assert stable_identity(os.fstat(stream.fileno())) == stable_identity(info)
        assert stable_identity(path.lstat()) == stable_identity(info)
        artifacts.append({"name": path.name, "bytes": info.st_size, "sha256": sha256, "device": info.st_dev,
                          "inode": info.st_ino, "links": info.st_nlink, "mtime_ns": info.st_mtime_ns,
                          "ctime_ns": info.st_ctime_ns})
    assert len({(row["device"], row["inode"]) for row in artifacts}) == 1
    return artifacts


def acquisition_requests(request, control, method, arguments, result, transcript):
    """Exercise only real socket operations; retain the two decisive job chains."""
    require_starter_grants(request, control, method, arguments)
    accepted_ids = set()
    for cancel in (False, True):
        ack = start_deferred_job(request, method, arguments)
        job_id = ack["job_id"]
        assert job_id not in accepted_ids
        accepted_ids.add(job_id)
        params = {"job_id": job_id}
        revision = ack["revision"]
        requested_cancel = False
        until = time.monotonic() + 93.
        while time.monotonic() < until:
            response, row = request("jobs.inspect", params, retained=False, timeout_ms=ACQUISITION_CONTROL_MS)
            assert response["ok"] is True, response
            job = response["result"]
            assert job["job_id"] == job_id and job["revision"] >= revision
            revision = job["revision"]
            if job["terminal"] is True:
                transcript.append(row)
                assert job["undo_boundary_created"] is False
                if cancel:
                    assert requested_cancel and job["state"] == "CANCELLED", job
                    assert job["result"] is None and job["error"]["code"] == "TIMEOUT"
                    assert job["error"]["context"]["reason"] == "explicit cancellation", job
                    assert not job["external_effects"].get("file_published")
                    control("unchanged")
                else:
                    assert job["state"] == "SUCCEEDED", job
                    preview = job["result"]
                    assert preview["phase"] == "preview" and re.fullmatch(r"[0-9a-f]{64}", preview["fingerprint"])
                    assert re.fullmatch(r"[0-9a-f]{64}", preview["consumer_graph_sha256"])
                    assert preview["backup_files_written"] is False and preview["image_packed"] is False
                    control("acquisition_preview_verified", preview=preview)
                break
            if (cancel and not requested_cancel and job["terminal"] is False and job["state"] == "RUNNING"
                    and revision > ack["revision"] and job["progress"]["phase"] == "capture_preflight"):
                transcript.append(row)
                response, _row = request("jobs.cancel", params, timeout_ms=ACQUISITION_CONTROL_MS)
                assert response["ok"] is True, response
                cancellation = response["result"]
                assert cancellation["job_id"] == job_id and cancellation["cancel_requested"] is True
                assert cancellation["state"] == "CANCELLING" and cancellation["terminal"] is False
                requested_cancel = True
            else:
                time.sleep(.01 if cancel else .03)
        else:
            raise AssertionError("Private acquisition job exceeded its diagnostic deadline")
    assert len(transcript) == 10


def scene_checkpoint_observation(bpy):
    scene = bpy.context.scene
    keys = list(scene.keys())
    authored = {name: scene[name] for name in keys if name != SCENE_CHECKPOINT_KEY}
    assert all(type(value) in {str, int, float, bool} for value in authored.values())
    return {"scene_uid": scene.session_uid, "scene_pointer": scene.as_pointer(), "scene_name": scene.name,
            "authored_properties": authored, "marker_key": SCENE_CHECKPOINT_KEY, "marker": scene.get(SCENE_CHECKPOINT_KEY),
            "filepath": bpy.data.filepath, "saved": bpy.data.is_saved}


def fixture_checkpoint_context(bpy, observe, protected_state):
    """Exercise the fixture's stock no-active-Object undo context before preview."""
    layer, scene = bpy.context.view_layer, bpy.context.scene
    layer.objects.active = None
    before, protected_before = observe(), protected_state()
    scene_before = scene_checkpoint_observation(bpy)
    before_self = scene.user_of_id(scene)
    assert bpy.ops.ed.undo_push.poll()
    assert bpy.ops.ed.undo_push(message="Fixture setup before Bridge preview") == {"FINISHED"}
    assert layer.objects.active is None and scene.tool_settings.particle_edit.object is None
    after_self = scene.user_of_id(scene)
    assert (before_self, after_self) in {(0, 0), (0, 1), (1, 1)} and SCENE_CHECKPOINT_KEY not in scene
    assert scene_checkpoint_observation(bpy) == scene_before
    assert observe() == before and protected_state() == protected_before
    return {"scene_self_references_before": before_self, "scene_self_references_after": after_self,
            "active_object_after": None, "particle_object_after": None,
            "native_setup_push_completed": True, "baseline_observations_unchanged": True}


def without_added_helper_record(observation):
    original, helper = observation["images"]
    keys = helper["keys"]
    assert HELPER_LIFECYCLE_KEY not in original["keys"] and keys.count(HELPER_LIFECYCLE_KEY) == 1
    return {**observation, "images": [original, {**helper, "keys": [key for key in keys if key != HELPER_LIFECYCLE_KEY]}]}


def verify_helper_record(raw, manifest, outcome, recovery, baseline):
    """Compare the native properties against the independently parsed archive."""
    expected = {"schema_version": 1, "profile": manifest["profile"], "record_uuid": manifest["record_uuid"],
                "runtime_nonce": manifest["runtime_nonce"], "manifest_sha256": outcome["manifest_sha256"]}
    assert type(raw) is str and raw == canonical_json(expected).decode()
    assert hashlib.sha256(raw.encode()).hexdigest() == outcome["lifecycle_record_sha256"] == recovery["lifecycle_record_sha256"]
    assert recovery["manifest_sha256"] == expected["manifest_sha256"]
    assert recovery["record_uuid"] == expected["record_uuid"] and recovery["runtime_nonce"] == expected["runtime_nonce"]
    for image, label, identity in zip(baseline["images"], ("image_name", "snapshot_name"),
                                      ("original_identity", "snapshot_identity"), strict=True):
        assert manifest[label] == recovery[label] == image["name"]
        assert manifest[identity] == {"pointer": format(image["pointer"], "x"), "session_uid": str(image["uid"])}
    assert baseline["owner"] == baseline["images"][0]["pointer"]


def _loaded_backup_probe(bpy, before, parent, runtime, prefs, original, helper, protected,
                         material, backups, previous, current, edited, observe, *, report, token, display,
                         original_decoded_sha256, storage_setup=None, acquisition=False, interruption=False,
                         helper_record=False):
    """Real socket worker and the registered Runtime timer; no manual dispatch."""
    import queue
    import resource
    import socket
    import threading
    import traceback

    from blender_artist_sidebar_smoke import owned_process_exit
    from blender_codex_bridge import current_pixels_contract as contract
    from blender_codex_bridge import current_pixels_source as source
    from blender_codex_bridge.tool_registry import ToolRegistry
    from blender_codex_bridge.tools import image_current_pixels, register_all

    assert type(runtime.registry._tools) is dict
    normal_names = set(runtime.registry._tools)
    assert not set(source.FIXTURE_METHODS) & normal_names
    image_current_pixels.register_tools(runtime.registry)
    assert set(runtime.registry._tools) == normal_names | set(source.FIXTURE_METHODS)
    fresh_registry = ToolRegistry()
    register_all(fresh_registry)
    assert not set(source.FIXTURE_METHODS) & set(fresh_registry._tools)
    assert not (ROOT / "mcp_server/tools/image_current_pixels.py").exists()
    assert source._REGISTRATION.registry is runtime.registry
    assert type(runtime.jobs).__name__ == "NativeSaveJobs" and runtime._registered
    assert bpy.app.timers.is_registered(runtime.executor._timer_callback)
    for method in source.FIXTURE_METHODS:
        spec = runtime.registry.get(method)
        assert spec.handler is vars(image_current_pixels)[source.HANDLERS[method]]
        assert spec.checkpoint_parameter_dependencies is source.initial_dependencies
        assert spec.automatic_checkpoint is False
    preview_start = runtime.registry.get(source.PREVIEW_START)
    assert preview_start.remote and preview_start.modifies is False
    # All sample allocations/reads precede the frozen observation window.
    protected_values = array("f", [0.]) * 16
    protected.pixels.foreach_get(protected_values)

    def protected_state():
        values = array("f", [0.]) * 16
        assert protected.has_data
        protected.pixels.foreach_get(values)
        return {"name": protected.name, "pointer": protected.as_pointer(), "uid": protected.session_uid,
            "pixels_sha256": hashlib.sha256(values.tobytes()).hexdigest(), "source": protected.source,
            "roles": [protected.colorspace_settings.name, protected.alpha_mode], "filepath": protected.filepath,
            "fake_user": protected.use_fake_user, "keys": sorted(protected.keys())}

    fixture_checkpoint = fixture_checkpoint_context(bpy, observe, protected_state) if helper_record else None
    baseline, protected_before = observe(), protected_state()
    assert baseline["backup_files"] == []
    if interruption or helper_record:
        assert bpy.data.filepath == "" and not bpy.data.is_saved
    if helper_record:
        assert HELPER_LIFECYCLE_KEY not in baseline["images"][1]["keys"] and helper.get(HELPER_LIFECYCLE_KEY) is None
    checkpoint_before = scene_checkpoint_observation(bpy) if helper_record else None
    initial_names = set(runtime.registry._tools)
    controls, done, result = queue.Queue(), threading.Event(), {}
    transcript, polls, assertions = [], [], {key: True for key in (
        "fixture_only_registration", "normal_registry_unchanged", "canonical_runtime")}
    prefix = INTERRUPTION_PREFIX
    arguments = {"image_name": original.name, "snapshot_name": helper.name,
        "affected_materials": [material.name], "backup_directory": str(backups),
        "backup_prefix": prefix, "retain_event_journal": False}
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    host, actual_port = runtime.start_server("127.0.0.1", port, request_timeout=60.)
    assert host == "127.0.0.1" and actual_port == port
    began = time.monotonic()
    supervisor_ticks = 0

    def control(action, **parameters):
        event, answer = threading.Event(), []
        controls.put((action, parameters, event, answer))
        assert event.wait(70), "Owned main-thread control expired: " + action
        assert answer and answer[0] is True, answer
        return answer[1] if len(answer) > 1 else None

    def worker():
        connection = stream = None
        try:
            connection = socket.create_connection(("127.0.0.1", port), timeout=65.)
            stream = connection.makefile("rb")
            sequence = 0

            def request(method, params, *, retained=True, timeout_ms):
                nonlocal sequence
                sequence += 1
                frame = {"id": ("acquisition_" if acquisition else "loaded_backup_") + str(sequence),
                         "method": method, "params": params, "protocol_version": "1.0", "timeout_ms": timeout_ms}
                started = time.monotonic()
                connection.sendall(canonical_json(frame) + b"\n")
                raw = stream.readline(262145)
                assert 0 < len(raw) <= 262144 and raw.endswith(b"\n"), "Missing/bounded socket response"
                response = json.loads(raw)
                assert response["id"] == frame["id"] and response["protocol_version"] == "1.0"
                row = {"request": frame, "response": response, "elapsed_seconds": time.monotonic() - started}
                if retained:
                    transcript.append(row)
                return response, row

            if acquisition:
                acquisition_requests(request, control, source.PREVIEW_START, arguments, result, transcript)
                return
            if interruption:
                backup_interruption_requests(request, control, source.PREVIEW_START, contract.PACK_START,
                                             arguments, result, transcript)
                return

            loaded_backup_requests(request, control, source.PREVIEW_START, contract.PACK_START,
                                  arguments, result, transcript, polls, helper_record=helper_record)
        except BaseException:
            result["failure"] = traceback.format_exc()
        finally:
            if stream is not None:
                stream.close()
            if connection is not None:
                connection.close()
            done.set()

    def unchanged(*, allow_backups=False, allow_helper_record=False):
        now = observe()
        if allow_backups:
            now = {**now, "backup_files": []}
        if allow_helper_record:
            now = without_added_helper_record(now)
        assert now == baseline and protected_state() == protected_before, "Owned data changed"
        assert set(runtime.registry._tools) == initial_names

    def finish_interruption():
        terminal = result["terminal"]
        samples = result["stability_samples"]
        assert len(samples) == INTERRUPTION_SAMPLES
        artifacts = interrupted_backup_artifacts(backups, previous, terminal["external_effects"])
        assert all(sample["artifacts"] == artifacts for sample in samples)
        unchanged(allow_backups=True)
        assert bpy.data.filepath == "" and not bpy.data.is_saved
        assert runtime.jobs.active is None and not runtime.state.snapshot()["is_executing"]
        assert source_fingerprints() == before
        assertions.update(dict.fromkeys(INTERRUPTION_ASSERTIONS - {"terminal_preview_hashes"}, True))
        assert set(assertions) == INTERRUPTION_ASSERTIONS
        proof = {"completed": True, "profile": INTERRUPTION_PROFILE, "scope": "fixture_only_partial_archive_cancellation",
            "process_instance": token, "process_id": os.getpid(), "blender_version": bpy.app.version_string,
            "source_build": bpy.app.build_hash.decode(), "source_fingerprints": before,
            "source_snapshot_sha256": hashlib.sha256(canonical_json(before)).hexdigest(),
            "assertions": assertions, "private_display": display, "transport": transcript, "storage_setup": storage_setup,
            "payload_hashes": result["payload_hashes"], "preview_poll_count": result["preview_poll_count"],
            "baseline": baseline, "final": observe(), "protected_baseline": protected_before,
            "protected_final": protected_state(), "stability_samples": samples, "retained_artifacts": artifacts,
            "public_tool_acceptance": False, "image_forward_transition_qualified": False, "restoration_qualified": False,
            "windows_qualified": False, "image_packed": False, "project_saved": False, "complete_archive": False}
        compact = {key: proof[key] for key in ("completed", "profile", "scope", "process_instance", "process_id",
            "blender_version", "source_build", "source_snapshot_sha256", "public_tool_acceptance",
            "image_forward_transition_qualified", "restoration_qualified", "windows_qualified", "complete_archive")}
        compact["full_receipt"] = write_receipt(report, proof)
        print(INTERRUPTION_MARKER + canonical_json(compact).decode(), flush=True)
        owned_process_exit(0)

    def finish():
        assert done.is_set(), "Worker not finished"
        if "failure" in result:
            if not helper_record:
                unchanged(allow_backups=not acquisition)
            marker = ("BLENDER_CURRENT_PIXELS_ACQUISITION_REFUSAL " if acquisition
                      else "BLENDER_CURRENT_PIXELS_BACKUP_INTERRUPTION_REFUSAL " if interruption
                      else "BLENDER_CURRENT_PIXELS_HELPER_RECORD_REFUSAL " if helper_record
                      else "BLENDER_CURRENT_PIXELS_LOADED_BACKUP_REFUSAL ")
            print(marker + canonical_json({
                "source_helper_and_protected_unchanged": None if helper_record else True,
                "backup_files_present": len(tuple(backups.iterdir())),
                **({"lifecycle_record_present": HELPER_LIFECYCLE_KEY in tuple(helper.keys())} if helper_record else {}),
                "requests": [{"method": row["request"]["method"], "elapsed_seconds": row["elapsed_seconds"],
                              "error_code": row["response"].get("error", {}).get("code")}
                             for row in transcript],
            }).decode(), flush=True)
            raise AssertionError(result["failure"])
        if interruption:
            return finish_interruption()
        if acquisition:
            unchanged()
            assert runtime.jobs.active is None and not runtime.state.snapshot()["is_executing"]
            assert source_fingerprints() == before
            assertions.update(real_socket_timer=True, four_grant_denials=True, prompt_acknowledgement=True,
                observable_nonterminal_progress=True, queued_cancellation=True, source_helper_and_protected_unchanged=True,
                no_files_written=True, source_unchanged=True)
            assert set(assertions) == ACQUISITION_ASSERTIONS
            proof = {"completed": True, "profile": ACQUISITION_PROFILE, "scope": "fixture_only_queued_preview_acquisition",
                "process_instance": token, "process_id": os.getpid(), "blender_version": bpy.app.version_string,
                "source_build": bpy.app.build_hash.decode(), "source_fingerprints": before,
                "source_snapshot_sha256": hashlib.sha256(canonical_json(before)).hexdigest(),
                "assertions": assertions, "ack_request_timeout_ms": ACQUISITION_ACK_MS,
                "public_tool_acceptance": False, "image_forward_transition_qualified": False,
                "restoration_qualified": False, "windows_qualified": False, "private_display": display,
                "transport": transcript, "baseline": baseline, "final": observe(), "protected_baseline": protected_before,
                "protected_final": protected_state(), "payload_hashes": result["payload_hashes"],
                "storage_setup": storage_setup,
                "backup_files": [], "elapsed_seconds": time.monotonic() - began,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                "image_packed": False, "project_saved": False}
            compact = {key: proof[key] for key in ("completed", "profile", "scope", "process_instance", "process_id",
                "blender_version", "source_build", "source_snapshot_sha256", "public_tool_acceptance",
                "image_forward_transition_qualified", "restoration_qualified", "windows_qualified")}
            compact["full_receipt"] = write_receipt(report, proof)
            print(ACQUISITION_MARKER + canonical_json(compact).decode(), flush=True)
            owned_process_exit(0)
            return
        unchanged(allow_backups=True, allow_helper_record=helper_record)
        assert runtime.jobs.active is None and not runtime.state.snapshot()["is_executing"]
        terminal = result["terminal"]
        files = terminal["result"]["files"]
        assert type(files) is list and len(files) == 3
        expected = {prefix + ".oldpacked.bin": previous, prefix + ".current.exr": current}
        records, manifest = [], None
        for record in files:
            assert type(record) is dict and set(record) == {"filepath", "file_bytes", "file_sha256"}
            path = Path(record["filepath"])
            assert path.parent == backups and not path.is_symlink() and path.is_file()
            assert path.name in {*expected, prefix + ".manifest.json"}
            with path.open("rb") as stream:
                raw = stream.read(65537)
            assert 1 <= len(raw) <= 65536
            assert len(raw) == record["file_bytes"] and hashlib.sha256(raw).hexdigest() == record["file_sha256"]
            if path.name in expected:
                assert raw == expected[path.name]
            else:
                manifest = contract.parse_manifest(raw)
                assert hashlib.sha256(raw).hexdigest() == terminal["result"]["manifest_sha256"]
                hashes = result["payload_hashes"]
                assert manifest["current_pixels_sha256_float32_le"] == hashes["current_pixels_sha256_float32_le"]
                assert manifest["previous_packed_sha256"] == hashes["original_packed_sha256"]
                assert manifest["previous_decoded_pixels_sha256"] == hashes["original_decoded_pixels_sha256"]
            records.append(record)
        assert {path.name for path in backups.iterdir()} == {*expected, prefix + ".manifest.json"}
        assert source_fingerprints() == before
        assertions.update(backups_independently_reopened=True, source_unchanged=True,
            real_socket_timer=True, both_starters_four_grant_denials=True,
            both_acknowledgements_unfrozen_under_three_seconds=True, preview_files_unchanged=True)
        profile, scope, marker = LOADED_PROFILE, "fixture_only_queued_preview_and_backup", LOADED_MARKER
        helper_proof = {}
        if helper_record:
            from blender_codex_bridge.current_pixels_graph import (
                LIFECYCLE_KEY,
                validate_lifecycle_record,
            )

            assert LIFECYCLE_KEY == HELPER_LIFECYCLE_KEY and manifest is not None
            assert all(bpy.data.images[image.name].as_pointer() == image.as_pointer() for image in (original, helper, protected))
            raw_record = validate_lifecycle_record(helper[LIFECYCLE_KEY])
            verify_helper_record(raw_record, manifest, terminal["result"], terminal["recovery_evidence"], baseline)
            assert terminal["recovery_evidence"]["expected_target_fingerprint"] == result["preview"]["fingerprint"]
            checkpoint_after = scene_checkpoint_observation(bpy)
            assert checkpoint_before["filepath"] == "" and checkpoint_before["saved"] is False
            assert {**checkpoint_after, "marker": checkpoint_before["marker"]} == checkpoint_before
            assert re.fullmatch(r"BCB1:[0-9a-f]{32}:[0-9a-f]{32}", checkpoint_after["marker"])
            assert checkpoint_after["marker"] != checkpoint_before["marker"]
            assertions.update(exact_helper_record_bound_to_manifest=True, native_checkpoint_created_and_finalized=True,
                original_helper_content_and_protected_unchanged=True, only_helper_record_and_reserved_scene_marker_written=True)
            assert set(assertions) == HELPER_RECORD_ASSERTIONS
            profile, scope, marker = HELPER_RECORD_PROFILE, HELPER_RECORD_SCOPE, HELPER_RECORD_MARKER
            assert len(polls) == result["poll_count"]
            helper_proof = {"helper_record_qualified": True, "helper_lifecycle_key": HELPER_LIFECYCLE_KEY,
                            "lifecycle_record": raw_record, "scene_checkpoint_before": checkpoint_before,
                            "scene_checkpoint_after": checkpoint_after, "fixture_checkpoint_setup": fixture_checkpoint,
                            "helper_commit_poll_timeout_ms": HELPER_COMMIT_POLL_MS,
                            "maximum_backup_poll_elapsed_seconds": max(row["elapsed_seconds"] for row in polls)}
        else:
            assertions.update(source_helper_and_protected_unchanged=True, backup_only_queued_start=True,
                              no_image_or_helper_write=True)
            assert set(assertions) == LOADED_ASSERTIONS
        proof = {"completed": True, "profile": profile, "scope": scope,
            "process_instance": token, "process_id": os.getpid(), "blender_version": bpy.app.version_string,
            "source_build": bpy.app.build_hash.decode(), "source_fingerprints": before,
            "source_snapshot_sha256": hashlib.sha256(canonical_json(before)).hexdigest(),
            "assertions": assertions, "ack_request_timeout_ms": ACQUISITION_ACK_MS,
            "control_request_timeout_ms": ACQUISITION_CONTROL_MS, "backup_job_limit_seconds": LOADED_BACKUP_JOB_SECONDS,
            "socket_timeout_seconds": 65, "storage_setup": storage_setup, "payload_hashes": result["payload_hashes"],
            "public_three_second_latency_qualified": False, "public_tool_acceptance": False,
            "image_forward_transition_qualified": False, "restoration_qualified": False, "windows_qualified": False,
            "private_display": display, "transport": transcript, "polls": polls, "poll_count": result["poll_count"],
            "preview_poll_count": result["preview_poll_count"],
            "baseline": baseline, "protected_baseline": protected_before, "final": observe(),
            "protected_final": protected_state(), "backup_files": records, "terminal": terminal,
            "elapsed_seconds": time.monotonic() - began,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "image_packed": False, "project_saved": False, **helper_proof}
        receipt = write_receipt(report, proof)
        compact = {key: proof[key] for key in ("completed", "profile", "scope", "process_instance", "process_id",
            "blender_version", "source_build", "source_snapshot_sha256", "public_tool_acceptance",
            "image_forward_transition_qualified", "restoration_qualified", "windows_qualified")}
        if helper_record:
            compact["helper_record_qualified"] = True
        compact["full_receipt"] = receipt
        print(marker + canonical_json(compact).decode(), flush=True)
        owned_process_exit(0)

    def supervise():
        nonlocal supervisor_ticks
        supervisor_ticks += 1
        try:
            while not controls.empty():
                action, parameters, event, answer = controls.get_nowait()
                try:
                    if action == "grant":
                        assert parameters["preference"] in ACQUISITION_GRANTS
                        setattr(prefs, parameters["preference"], parameters["enabled"])
                    elif action == "unchanged":
                        unchanged()
                    elif action == "interrupted_stable_sample" and interruption:
                        unchanged(allow_backups=True)
                        assert bpy.data.filepath == "" and not bpy.data.is_saved
                        assert runtime.jobs.active is None and not runtime.state.snapshot()["is_executing"]
                        answer.extend((True, {"tick": supervisor_ticks,
                            "artifacts": interrupted_backup_artifacts(backups, previous, parameters["effects"])}))
                        continue
                    elif action == ("acquisition_preview_verified" if acquisition else "preview_verified"):
                        unchanged()
                        preview = parameters["preview"]
                        assert preview["profile"] == contract.PROFILE and preview["dimensions"] == [2, 2]
                        expected = {
                            "original_packed_sha256": hashlib.sha256(previous).hexdigest(),
                            "original_decoded_pixels_sha256": original_decoded_sha256,
                            "snapshot_packed_sha256": hashlib.sha256(current).hexdigest(),
                            "current_pixels_sha256_float32_le": hashlib.sha256(edited.tobytes()).hexdigest(),
                        }
                        assert all(preview["payload_facts"][key] == value for key, value in expected.items())
                        result["payload_hashes"] = expected
                        assertions["terminal_preview_hashes"] = True
                    else:
                        raise AssertionError(action)
                    answer.append(True)
                except BaseException:
                    answer.extend((False, traceback.format_exc()))
                finally:
                    event.set()
            if done.is_set():
                finish()
            assert time.monotonic() - began < 260., "Queued fixture exceeded the hard phase deadline"
            return .01
        except BaseException:
            traceback.print_exc()
            owned_process_exit(1)

    bpy.app.timers.register(supervise, first_interval=.01)
    threading.Thread(target=worker, name="CurrentPixelsSocketFixture", daemon=True).start()
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--bridge-census-only", action="store_true")
    modes.add_argument("--bridge-source-graph", action="store_true")
    modes.add_argument("--bridge-loaded-backup", action="store_true")
    modes.add_argument("--bridge-current-pixels-acquisition", action="store_true")
    modes.add_argument("--bridge-current-pixels-backup-interruption", action="store_true")
    modes.add_argument("--bridge-current-pixels-helper-record", action="store_true")
    parser.add_argument("--bridge-report", type=Path, required=True)
    arguments = sys.argv[sys.argv.index("--") + 1:] if argv is None and "--" in sys.argv else argv
    args = parser.parse_args(arguments)
    queued = (args.bridge_loaded_backup or args.bridge_current_pixels_acquisition or args.bridge_current_pixels_backup_interruption
              or args.bridge_current_pixels_helper_record)
    report_name = (HELPER_RECORD_REPORT_NAME if args.bridge_current_pixels_helper_record else
                   INTERRUPTION_REPORT_NAME if args.bridge_current_pixels_backup_interruption else
                   ACQUISITION_REPORT_NAME if args.bridge_current_pixels_acquisition else LOADED_REPORT_NAME
                   if args.bridge_loaded_backup else GRAPH_REPORT_NAME if args.bridge_source_graph else REPORT_NAME)
    assert args.bridge_report.name == report_name
    if not queued:
        # Original read probes attest their disposable paths before touching
        # bpy mode/build metadata. Keep this fail-closed ordering unchanged.
        token = owned_profile(args.bridge_report)
    import bpy

    if not queued:
        assert bpy.app.background
    assert "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    assert (tuple(bpy.app.version), bpy.app.build_hash) in BUILDS
    assert bpy.app.build_type == b"Release"
    addon = str(ROOT / "addon")
    sys.path.insert(0, addon)
    if queued:
        assert not bpy.app.background
        sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
        from blender_artist_sidebar_smoke import owned_process_exit, private_display_manifest

        from scripts.run_loaded_backup_private_display import LAUNCHER, fingerprints

        assert LAUNCHER == ROOT / "scripts/run_loaded_backup_private_display.py" and not LAUNCHER.is_symlink()
        display = private_display_manifest(launcher_fingerprints=fingerprints(), launcher_path=LAUNCHER)
        token = owned_profile(args.bridge_report, private_display=display)
        before = source_fingerprints()

        def setup():
            import traceback

            from blender_codex_bridge import current_pixels_graph as graph

            try:
                return native_graph_probe(bpy, graph, before, args.bridge_report.parent,
                    loaded_backup={"report": args.bridge_report, "token": token, "display": display,
                                   "acquisition": args.bridge_current_pixels_acquisition,
                                   "interruption": args.bridge_current_pixels_backup_interruption,
                                   "helper_record": args.bridge_current_pixels_helper_record})
            except BaseException:
                traceback.print_exc()
                owned_process_exit(1)

        bpy.app.timers.register(setup, first_interval=1.)
        return
    before = source_fingerprints()
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
