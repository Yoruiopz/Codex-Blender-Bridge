"""Source-pinned RNA getter side-effect probe in one disposable desktop turn.

Run through run_blender_checks.py only. This research fixture deliberately creates
a legal pending Base state; it neither changes production admission nor qualifies
an armed artist operation. No background redraw may run between observations.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

SOURCE_REFS = {
    (4, 5, 14): "62c1db4208e862312bc36db5bc15d4a6dbcfa3e3",
    (5, 2, 2): "d13f752e3b9c4f8c261cda552b1021f8bcc0382c",
}
MARKER = "BLENDER_READONLY_CONTEXT_PROBE_OK "


def raw_selection(layer):
    """Raw RNA Base filtering, not context.selected_objects or Object.select_get.

    BKE_view_layer_object_bases_get only asserts the sync precondition in Debug;
    this witness is therefore restricted to the exact Release development builds.
    This does not offer a production no-sync Base-state inspection API.
    """
    return sorted(obj.name for obj in layer.objects.selected)


def main():
    from blender_codex_bridge.tools import artist_loop
    from blender_codex_bridge.tools._object_rna_mutation import Boundary
    from blender_codex_bridge.tools._scene_checkpoint_roles import Plan

    assert threading.current_thread() is threading.main_thread()
    assert not bpy.app.background and not bpy.data.filepath
    version = tuple(bpy.app.version)
    source_ref = SOURCE_REFS[version]
    build_hash = bpy.app.build_hash.decode("ascii")
    build_type = bpy.app.build_type.decode("ascii")
    assert len(build_hash) >= 12 and source_ref.startswith(build_hash), build_hash
    assert build_type == "Release", build_type
    assert {obj.name for obj in bpy.data.objects} == {"Cube", "Camera", "Light"}
    bpy.context.preferences.use_preferences_save = False
    window = bpy.context.window
    original_scene = window.scene
    original_layer = window.view_layer
    scene = bpy.data.scenes.new("Owned Readonly Context Probe")
    mesh = bpy.data.meshes.new("Readonly Context Probe Mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    mesh.update()
    target = bpy.data.objects.new("Readonly Context Probe Target", mesh)
    collection = bpy.data.collections.new("Readonly Context Probe Collection")
    scene.collection.children.link(collection)
    collection.objects.link(target)
    window.scene = scene
    layer = window.view_layer
    geometry_before = [list(vertex.co) for vertex in mesh.vertices]
    receipts = []
    # These shells isolate the existing reader methods from their write-boundary
    # constructors. They are reader probes, not public entry/admission coverage.
    boundary_reader = SimpleNamespace(bpy=bpy, checkpoint_roles=None)
    role_reader = SimpleNamespace(
        bpy=bpy, scene=scene, active_validator=lambda _host, _active: None
    )

    def prepare_pending():
        # Setup mutations and explicit synchronization are outside measurement.
        target.hide_set(False, view_layer=layer)
        layer.update()
        target.select_set(True, view_layer=layer)
        layer.objects.active = target
        layer.update()
        assert raw_selection(layer) == [target.name]
        assert layer.objects.active == target
        # The native setter ensures BEFORE changing BASE_HIDDEN, then tags the
        # view layer out of sync. It does not clear BASE_SELECTED itself.
        target.hide_set(True, view_layer=layer)
        before = raw_selection(layer)
        assert before == [target.name], before
        return before

    def measure(label, reader, *, expect_sync):
        before = prepare_pending()
        value = reader()
        after = raw_selection(layer)
        expected = [] if expect_sync else before
        receipts.append(
            {
                "reader": label,
                "raw_selected_after_hide_set": before,
                "raw_selected_after_reader": after,
                "reader_result_type": type(value).__name__,
                "selection_changed": after != before,
                "expected_sync": expect_sync,
                "measurement_sequence": [
                    "Object.hide_set(True)",
                    "raw ViewLayer.objects.selected",
                    label,
                    "raw ViewLayer.objects.selected",
                ],
            }
        )
        print("READONLY_CONTEXT_PROBE_OBSERVATION " + json.dumps(receipts[-1]), flush=True)
        assert after == expected, (label, before, after, expected)

    try:
        measure("raw ViewLayer.objects iteration", lambda: tuple(layer.objects), expect_sync=False)
        measure("raw ViewLayer.objects.selected", lambda: raw_selection(layer), expect_sync=False)
        measure(
            "artist_loop._objects",
            lambda: artist_loop._objects(bpy, [target.name]),
            expect_sync=False,
        )
        for label, reader in (
            ("context.selected_objects", lambda: tuple(bpy.context.selected_objects)),
            ("context.active_object", lambda: bpy.context.active_object),
            ("context.mode", lambda: bpy.context.mode),
            ("ViewLayer.objects.active", lambda: layer.objects.active),
            ("Object.select_get", lambda: target.select_get(view_layer=layer)),
            ("Object.hide_get", lambda: target.hide_get(view_layer=layer)),
            ("Object.visible_get", lambda: target.visible_get(view_layer=layer)),
            ("LayerCollection.children", lambda: tuple(layer.layer_collection.children)),
            ("artist_loop._context", lambda: artist_loop._context(bpy)),
            ("Boundary._session", lambda: Boundary._session(boundary_reader)),
            ("Plan._read", lambda: Plan._read(role_reader)),
        ):
            measure(label, reader, expect_sync=True)
        assert [list(vertex.co) for vertex in mesh.vertices] == geometry_before
        assert not bpy.data.filepath and not bpy.context.preferences.use_preferences_save
    finally:
        # Only fixture-owned setup is undone, after all measured intervals.
        window.scene = original_scene
        window.view_layer = original_layer
        bpy.data.scenes.remove(scene)
        bpy.data.objects.remove(target, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        bpy.data.collections.remove(collection)

    evidence = Path(tempfile.gettempdir()) / "readonly-context-probe-evidence"
    evidence.mkdir(exist_ok=False)
    receipt = evidence / "getter-observations.json"
    payload = {
        "blender": bpy.app.version_string,
        "build_hash": build_hash,
        "build_type": build_type,
        "source_ref": source_ref,
        "main_thread": True,
        "single_timer_turn_no_yield": True,
        "controlled_context_no_overrides": True,
        "raw_witness_debug_builds_supported": False,
        "observations": receipts,
        "public_entry_admission_tested": False,
        "production_protected_capture_admitted": False,
        "geometry_unchanged": True,
        "original_window_scene_restored": window.scene == original_scene,
        "original_window_view_layer_restored": window.view_layer == original_layer,
        "project_saved": False,
        "user_preferences_saved": False,
    }
    receipt.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        MARKER
        + json.dumps(
            {
                **{key: value for key, value in payload.items() if key != "observations"},
                "observation_count": len(receipts),
                "selection_changing_readers": [
                    item["reader"] for item in receipts if item["selection_changed"]
                ],
                "receipt": str(receipt),
                "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            }
        ),
        flush=True,
    )


def run():
    try:
        main()
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.0)
