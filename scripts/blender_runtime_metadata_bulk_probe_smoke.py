"""Private stock-Blender metadata API feasibility; not a product admission path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from types import MethodDescriptorType, WrapperDescriptorType

PROFILE = "RNA_RUNTIME_METADATA_BULK_API_PROBE_V1"
MARKER = "BLENDER_RUNTIME_METADATA_BULK_PROBE_OK "
OWNERS = ("Scene", "Object", "ToolSettings", "ParticleEdit", "ParticleBrush")
SOURCES = ("scripts/blender_runtime_metadata_bulk_probe_smoke.py", "scripts/run_blender_checks.py",
           "addon/blender_codex_bridge/mesh_storage_source.py", "addon/blender_codex_bridge/current_pixels_graph.py",
           "addon/blender_codex_bridge/tools/_scene_mutation.py", "addon/blender_codex_bridge/tools/_scene_checkpoint_roles.py",
           "addon/blender_codex_bridge/mesh_storage_prepare.py")
SCENARIOS = ("stop_before", "stop_after", "source_before", "source_after")


def fingerprints(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}


def validate_flags(flags, count):
    if type(flags) is not list or len(flags) != count or any(type(flag) is not bool for flag in flags):
        raise ValueError("BULK_FLAGS_MALFORMED")
    return tuple(flags)


def checked_batch(call, method, collection, count, preflight, *, after_native=None):
    """Experiment-local orchestration; actual product Access.call is injected."""
    if type(count) is not int or not 1 <= count <= 512:
        raise ValueError("BULK_METADATA_BOUND")
    preflight()
    flags = [False] * count  # Exact builtin list, no foreign buffer/sequence callbacks.
    interval = {}
    def invoke():
        started, cpu = time.monotonic(), time.process_time()
        try:
            result = method(collection, "is_runtime", flags)
        finally:
            # Direct API call only: excludes source/control guards and injected faults.
            interval.update(wall_seconds=time.monotonic() - started, cpu_seconds=time.process_time() - cpu)
        if result is not None:
            raise ValueError("BULK_RETURN_VALUE")
        if after_native is not None:
            after_native()
    call(invoke)
    preflight()
    return validate_flags(flags, count), interval


def main():
    import bpy

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "addon"))
    from blender_codex_bridge import current_pixels_graph as graph
    from blender_codex_bridge import mesh_storage_source as source

    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-report", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    report = args.bridge_report
    assert report.is_absolute() and report.parent == Path(os.environ["TEMP"])
    assert not report.exists()
    bpy.context.preferences.use_preferences_save = False
    initial_sources = fingerprints(root)
    seal = source.SourceSeal.capture()
    state = {"stop": False}
    primary = source.contract.BridgeError("TIMEOUT", "Owned metadata probe stop")
    def check():
        source.verify_seal(seal)
        if state["stop"]:
            raise primary
    access = source._CheckpointRoleAccess(bpy, check)
    collection_class = access.collection_type
    method = graph._class_find(collection_class, "foreach_get")
    if (type(method) is not MethodDescriptorType or method.__objclass__ is not collection_class
            or method.__name__ != "foreach_get"):
        raise ValueError("BULK_ORIGINAL_METHOD_UNSUPPORTED")

    def catalog(owner_name):
        canonical = access.call(getattr, access.types, owner_name)
        rna = graph._class_dict(canonical).get("bl_rna")
        if type(rna) is not access.struct_type or access.raw(rna, "identifier") != owner_name:
            raise ValueError("BULK_CANONICAL_SCHEMA")
        collection = access.raw(rna, "properties")
        if type(collection) is not collection_class:
            raise ValueError("BULK_NATIVE_COLLECTION")
        items = access.bounded(collection, 512, "metadata API probe")
        if not items:
            raise ValueError("BULK_EMPTY_COLLECTION")
        rows = tuple((format(access.key(item), "x"), access.raw(item, "identifier"),
                      access.raw(item, "type"), access.raw(item, "is_runtime")) for item in items)
        if any(type(row[1]) is not str or type(row[2]) is not str or type(row[3]) is not bool for row in rows):
            raise ValueError("BULK_SCALAR_METADATA_TYPES")
        return collection, items, rows

    def preflight(collection, items):
        check()
        if (type(collection) is not collection_class
                or type(access.collection_getter) is not WrapperDescriptorType
                or access.collection_getter.__objclass__ not in (collection_class, object)
                or access.collection_getter.__name__ != "__getattribute__"
                or graph._class_find(collection_class, "foreach_get") is not method
                or graph._class_find(collection_class, "__getattr__") is not None
                or graph._class_find(collection_class, "__getattribute__") is not access.collection_getter):
            raise ValueError("BULK_COLLECTION_ORIGIN_CHANGED")
        for item in items:
            cls = type(item)
            if not any(base is access.base for base in graph._class_mro(cls)):
                raise ValueError("BULK_METADATA_NATIVE_CLASS")
            graph._unshadowed(cls, ("identifier", "type", "is_runtime"))
            access.screen_static_metadata(item)
        check()

    def sentinel():
        return {
            "scene": [bpy.context.scene.name, bpy.context.scene.as_pointer(), bpy.context.scene.session_uid],
            "objects": sorted((obj.name, obj.as_pointer(), obj.session_uid, tuple(obj.location),
                               obj.select_get(), obj.type, obj.data.as_pointer() if obj.data else None)
                              for obj in bpy.data.objects),
            "meshes": sorted((mesh.name, mesh.as_pointer(), mesh.session_uid, len(mesh.vertices),
                              len(mesh.edges), len(mesh.polygons)) for mesh in bpy.data.meshes),
            "active": bpy.context.view_layer.objects.active.as_pointer() if bpy.context.view_layer.objects.active else None,
            "markers": [(scene.name, scene.get("_codex_bridge_undo_marker")) for scene in bpy.data.scenes],
        }

    before_sentinel = sentinel()
    before_schema = {name: catalog(name)[2] for name in OWNERS}
    payload_calls = []
    field = "bcb_owned_metadata_bulk_runtime_probe"
    assert not hasattr(bpy.types.Scene, field)
    def forbidden_payload(_owner):
        payload_calls.append(True)
        raise AssertionError("Metadata bulk read invoked runtime value getter")
    setattr(bpy.types.Scene, field, bpy.props.BoolProperty(get=forbidden_payload))
    rows, scenarios = [], {}
    try:
        for name in OWNERS:
            collection, items, before = catalog(name)
            flags, interval = checked_batch(access.call, method, collection, len(items),
                lambda collection=collection, items=items: preflight(collection, items))
            _current_collection, _current_items, after = catalog(name)
            if before != after or flags != tuple(row[3] for row in before):
                raise ValueError("BULK_SCALAR_OR_MEMBERSHIP_MISMATCH")
            rows.append({"owner": name, "count": len(items), "metadata": [list(row) for row in before],
                         "flags": list(flags), "after_metadata": [list(row) for row in after],
                         "interval": interval, "exact_native_collection": True,
                         "original_method_descriptor": True, "owned_exact_list": True})
        scene_row = rows[0]
        if not any(row[1] == field and row[3] is True for row in scene_row["metadata"]):
            raise ValueError("BULK_RUNTIME_TRUE_NOT_OBSERVED")
        collection, items, _before = catalog("Scene")
        original = source.checkpoint_proof.RUNTIME["Scene"]["cycles"]
        for scenario in SCENARIOS:
            calls, later = [], []
            def observed_method(owner, attr, flags, calls=calls):
                calls.append(True)
                return method(owner, attr, flags)
            def inject(scenario=scenario):
                if scenario.startswith("stop"):
                    state["stop"] = True
                else:
                    source.checkpoint_proof.RUNTIME["Scene"]["cycles"] = "BULK_PROBE_INJECTED_SOURCE_DRIFT"
            try:
                if scenario.endswith("before"):
                    inject()
                checked_batch(access.call, observed_method, collection, len(items),
                    lambda: preflight(collection, items), after_native=inject if scenario.endswith("after") else None)
                later.append("flags_consumed")
                raise AssertionError("Expected guard refusal")
            except source.contract.BridgeError as error:
                if scenario.startswith("stop"):
                    assert error is primary
                    reason = "TIMEOUT"
                else:
                    assert error.context["reason"] == "STORAGE_SOURCE_CHANGED"
                    reason = error.context["reason"]
                scenarios[scenario] = {"bulk_calls": len(calls), "reason": reason,
                                       "flags_consumed": False, "later_inspection_attempts": len(later),
                                       "injected_probe_callback": scenario.endswith("after")}
                error.__traceback__ = error.__cause__ = error.__context__ = None
            finally:
                state["stop"] = False
                source.checkpoint_proof.RUNTIME["Scene"]["cycles"] = original
            assert len(calls) == int(scenario.endswith("after")) and not later
        assert payload_calls == []
    finally:
        state["stop"] = False
        delattr(bpy.types.Scene, field)
    source.verify_seal(seal)
    after_schema = {name: catalog(name)[2] for name in OWNERS}
    assert before_schema == after_schema and before_sentinel == sentinel() and payload_calls == []
    assert initial_sources == fingerprints(root)
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    full = {"profile": PROFILE, "completed": True, "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
            "process_id": os.getpid(), "blender_version": bpy.app.version_string,
            "source_build": bpy.app.build_hash.decode(), "source_fingerprints": initial_sources,
            "rows": rows, "scenarios": scenarios, "payload_getter_calls": len(payload_calls),
            "runtime_field": field, "runtime_field_removed": not hasattr(bpy.types.Scene, field),
            "sentinel_before_sha256": digest(before_sentinel), "sentinel_after_sha256": digest(sentinel()),
            "schema_before_sha256": digest(before_schema), "schema_after_sha256": digest(after_schema),
            "limitations": {"product_adoption": False, "speedup_qualified": False, "mid_C_cancel": False,
                "all_native_callbacks_observed": False, "full_workflow": False, "windows": False,
                "probe_guard_source_stop_only": True, "post_C_faults_injected_by_probe": True}}
    raw = json.dumps(full, indent=2, allow_nan=False).encode()
    with report.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(MARKER + json.dumps({"profile": PROFILE, "process_instance": full["process_instance"],
        "process_id": full["process_id"], "blender_version": full["blender_version"],
        "full_receipt": {"path": str(report), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}}), flush=True)


if __name__ == "__main__":
    main()
