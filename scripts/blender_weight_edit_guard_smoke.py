"""Opt-in registered direct-weight native fixture; source-only until qualified.

Launch through run_blender_checks.py. The production reader is never replaced.
A pending native gate is a failed fixture, not a success or accepted limitation.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import time
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "addon"), str(ROOT / "scripts")]


def bits(value):
    return struct.pack("<f", value).hex()


def snapshot(obj):
    return {"object": [int(obj.as_pointer()), int(obj.session_uid)],
            "mesh": [int(obj.data.as_pointer()), int(obj.data.session_uid)],
            "groups": [[g.name, g.index, int(g.as_pointer()), bool(g.lock_weight)] for g in obj.vertex_groups],
            "memberships": [sorted([[g.group, bits(g.weight)] for g in v.groups]) for v in obj.data.vertices],
            "positions": [[bits(x) for x in v.co] for v in obj.data.vertices],
            "edges": [list(e.vertices) for e in obj.data.edges],
            "polygons": [list(p.vertices) for p in obj.data.polygons]}


def main():
    from blender_artist_quaternion_storage_smoke import owned_profile
    folder, process, attestation = owned_profile()
    from blender_artist_sidebar_smoke import owned_process_exit
    from blender_codex_bridge.errors import BridgeError
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime

    status = 1
    report = {"process_instance": process, "blender_version": bpy.app.version_string,
              "build_hash": bpy.app.build_hash.decode("ascii"), "profile": attestation,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "native_profile_qualified": False, "completed": False,
              "registered_methods": ["weights.assign", "weights.normalize"],
              "checkpoint_replaced": False, "production_reader_replaced": False,
              "project_saved": False, "windows_qualified": False, "cases": []}
    path = folder / "weight-edit-guard-evidence.json"
    try:
        assert bpy.ops.preferences.addon_enable(module="blender_codex_bridge") == {"FINISHED"}
        prefs, runtime = get_preferences(), get_runtime()
        assert prefs is not None and prefs.auto_start is False
        prefs.allow_inspect_scene = prefs.allow_edit_mesh = True
        runtime.dispatch("toolsets.enable", {"name": "weights"})
        mesh = bpy.data.meshes.new("Owned Direct Weight Mesh")
        mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("Owned Direct Weight Target", mesh)
        bpy.context.scene.collection.children[0].objects.link(obj)
        for name, weight in (("A", .25), ("B", .25), ("Locked", .125)):
            group = obj.vertex_groups.new(name=name)
            group.add((0, 1, 2), weight, "REPLACE")
            group.lock_weight = name == "Locked"
        # Setup only. There is no evaluation or checkpoint replacement below.
        before = snapshot(obj)
        request = {"object_name": obj.name, "group_name": "A", "vertex_indices": [0, 1], "weight": .5}
        started = time.monotonic()
        result = runtime.dispatch("weights.assign", request)
        after = snapshot(obj)
        assert after["memberships"] == [[[0, bits(.5)], [1, bits(.25)], [2, bits(.125)]],
                                         [[0, bits(.5)], [1, bits(.25)], [2, bits(.125)]],
                                         before["memberships"][2]]
        assert {k: v for k, v in before.items() if k != "memberships"} == {
            k: v for k, v in after.items() if k != "memberships"}
        assert result["recovery_evidence"]["owned_membership_verified"] == 2
        report["cases"].append({"case": "assign", "before": before, "after": after,
                                "elapsed_seconds": time.monotonic() - started,
                                "recovery_evidence": result["recovery_evidence"]})
        normalized = runtime.dispatch("weights.normalize", {"object_name": obj.name,
            "group_names": ["A", "B"], "vertex_indices": [0, 1]})
        observed = snapshot(obj)
        assert observed["memberships"][:2] == [
            [[0, bits(7 / 12)], [1, bits(7 / 24)], [2, bits(.125)]]] * 2
        report["cases"].append({"case": "normalize", "after": observed,
                                "recovery_evidence": normalized["recovery_evidence"]})
        prefs.allow_edit_mesh = False
        denied_before = snapshot(obj)
        try:
            runtime.dispatch("weights.assign", request)
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:
            raise AssertionError("Denied native edit was accepted")
        assert snapshot(obj) == denied_before
        report.update(registered_membership_cases_completed=True, completed=True)
        status = 0
    except Exception as error:
        if isinstance(error, BridgeError):
            report["structured_error"] = error.to_dict()
        report["failure"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        raw = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        with path.open("xb") as stream:
            stream.write(raw)
        if status == 0:
            print("BLENDER_WEIGHT_EDIT_GUARD_OK " + json.dumps({
                "blender_version": bpy.app.version_string, "evidence_file": str(path),
                "evidence_sha256": hashlib.sha256(raw).hexdigest(), "cases": len(report["cases"]),
                "native_profile_qualified": False, "complete_workflow_qualified": False}), flush=True)
        owned_process_exit(status)


if __name__ == "__main__":
    main()
