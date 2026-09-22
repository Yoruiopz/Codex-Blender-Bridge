"""Headless Blender smoke test for add-on registration and core workflows.

Run with, for example::

    blender --background --factory-startup --python scripts/blender_smoke.py

The script never saves the startup project and removes the temporary capture it
creates. It intentionally enables permissions only inside this disposable
Blender process.
"""

from __future__ import annotations

import json
import math
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import bmesh  # type: ignore
import bpy  # type: ignore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402


def _allow_smoke_permissions() -> PermissionManager:
    allowed = {permission.value: True for permission in Permission}
    return PermissionManager(lambda: allowed)


def _network_round_trip(runtime: Any) -> dict[str, Any]:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    runtime.start_server("127.0.0.1", port, request_timeout=5.0)

    outcome: dict[str, Any] = {}

    def request_status() -> None:
        request = {
            "id": "smoke_network",
            "method": "bridge.status",
            "params": {},
            "protocol_version": "1.0",
            "timeout_ms": 5_000,
        }
        with socket.create_connection(("127.0.0.1", port), timeout=5.0) as connection:
            connection.sendall(json.dumps(request).encode("utf-8") + b"\n")
            reader = connection.makefile("rb")
            outcome.update(json.loads(reader.readline()))

    thread = threading.Thread(target=request_status, name="bridge-smoke-client", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10.0
    while thread.is_alive() and time.monotonic() < deadline:
        # In normal Blender use bpy.app.timers invokes this callback. The smoke
        # script owns the main thread, so it drives one tick explicitly.
        runtime.executor._drain_timer()
        time.sleep(0.01)
    thread.join(timeout=1.0)
    runtime.stop_server()
    assert not thread.is_alive(), "network round trip did not finish"
    assert outcome.get("ok") is True, outcome
    assert outcome.get("id") == "smoke_network", outcome
    return outcome


def main() -> None:
    blender_codex_bridge.register()
    runtime = get_runtime()
    capture_path: Path | None = None
    try:
        assert runtime.dispatch("bridge.status", {})["addon_version"] == "0.3.0"
        try:
            runtime.dispatch("project.info", {})
        except BridgeError as error:
            assert error.code == "PERMISSION_DENIED"
        else:  # pragma: no cover - only reachable with unsafe preference defaults
            raise AssertionError("inspection unexpectedly bypassed disabled permissions")

        permissions = _allow_smoke_permissions()
        runtime.permissions = permissions
        runtime.executor.permissions = permissions
        for toolset in ("objects", "mesh", "materials"):
            runtime.dispatch("toolsets.enable", {"name": toolset})

        network_response = _network_round_trip(runtime)
        checkpoint = runtime.dispatch(
            "checkpoint.create", {"description": "Headless smoke checkpoint"}
        )
        created = runtime.dispatch(
            "object.create",
            {
                "object_type": "CUBE",
                "name": "CodexSmokeCube",
                "location": [1.0, 2.0, 3.0],
            },
        )
        object_name = created["object"]
        transformed = runtime.dispatch(
            "transform.set",
            {"object_name": object_name, "scale": [1.5, 1.0, 0.5]},
        )
        assert transformed["scale"] == [1.5, 1.0, 0.5]

        try:
            runtime.dispatch("object.delete", {})
        except BridgeError as error:
            assert error.code == "INVALID_ARGUMENT"
        else:
            raise AssertionError("object.delete used an implicit active target")
        assert bpy.data.objects.get(object_name) is not None
        try:
            runtime.dispatch(
                "transform.scale",
                {"object_name": object_name, "factor": math.inf},
            )
        except BridgeError as error:
            assert error.code == "INVALID_ARGUMENT"
        else:
            raise AssertionError("non-finite scalar transform unexpectedly succeeded")
        assert [float(value) for value in bpy.data.objects[object_name].scale] == [
            1.5,
            1.0,
            0.5,
        ]

        obj = bpy.data.objects[object_name]
        for selected in bpy.context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")

        # A rejected selection-scoped edit must not replace the user's live
        # Edit Mode selection before validation succeeds.
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.faces[0].select = True
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        rejected_selection_id = runtime.dispatch("selection.inspect", {})[
            "mesh_selection"
        ]["selection_id"]
        bpy.ops.mesh.select_all(action="DESELECT")
        bm.faces[1].select = True
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        selected_before = [face.index for face in bm.faces if face.select]
        try:
            runtime.dispatch(
                "mesh.bevel_selected",
                {"object_name": object_name, "selection_id": rejected_selection_id},
            )
        except BridgeError as error:
            assert error.code == "INVALID_ARGUMENT"
        else:
            raise AssertionError("invalid bevel unexpectedly succeeded")
        selected_after = [face.index for face in bm.faces if face.select]
        assert selected_after == selected_before, (selected_before, selected_after)

        bpy.ops.mesh.select_all(action="SELECT")
        selection = runtime.dispatch("selection.inspect", {})
        selection_id = selection["mesh_selection"]["selection_id"]
        normals = runtime.dispatch(
            "mesh.recalculate_normals",
            {"object_name": object_name, "selection_id": selection_id},
        )
        assert normals["faces_affected"] == 6
        bevel = runtime.dispatch(
            "mesh.bevel_selected",
            {
                "object_name": object_name,
                "selection_id": selection_id,
                "width": 0.05,
                "segments": 2,
            },
        )
        assert bevel["mesh_counts_after"]["vertices"] > 8
        try:
            runtime.dispatch(
                "mesh.recalculate_normals",
                {"object_name": object_name, "selection_id": selection_id},
            )
        except BridgeError as error:
            assert error.code == "INVALID_SELECTION"
        else:
            raise AssertionError("topology edit did not invalidate selection ID")
        bpy.ops.object.mode_set(mode="OBJECT")

        inspected = runtime.dispatch("object.inspect", {"object_name": object_name})
        assert inspected["mesh"]["vertices"] > 8
        scene = runtime.dispatch("scene.inspect", {"max_objects": 100})
        assert any(item["name"] == object_name for item in scene["objects"])
        materials = runtime.dispatch("material.inspect", {})
        assert "materials" in materials

        render = bpy.context.scene.render
        render.use_border = True
        render.use_crop_to_border = True
        render.border_min_x = 0.0
        render.border_max_x = 0.5
        render.border_min_y = 0.0
        render.border_max_y = 0.5
        eevee_samples_before = bpy.context.scene.eevee.taa_render_samples
        border_before = (
            render.use_border,
            render.use_crop_to_border,
            render.border_min_x,
            render.border_max_x,
            render.border_min_y,
            render.border_max_y,
        )
        capture = runtime.dispatch(
            "viewport.capture",
            {"view": "camera", "shading": "rendered", "resolution": [64, 64]},
        )
        capture_path = Path(capture["path"])
        assert capture["source"] == "camera_render"
        assert capture["width"] == 64 and capture["height"] == 64
        assert capture["resolution_matches_request"] is True
        assert capture["side_effects"] == ["render_result_replaced"]
        assert capture["sampling"]["eevee_taa_render_samples"] <= 16
        assert bpy.context.scene.eevee.taa_render_samples == eevee_samples_before
        assert border_before == (
            render.use_border,
            render.use_crop_to_border,
            render.border_min_x,
            render.border_max_x,
            render.border_min_y,
            render.border_max_y,
        )
        assert capture_path.is_file() and capture_path.stat().st_size > 0

        ledger = runtime.dispatch("checkpoint.list", {"limit": 20})
        assert ledger["checkpoint_count"] == 1
        assert ledger["operation_count"] > 0
        restore_metadata = next(
            tool
            for tool in runtime.registry.describe()["tools"]
            if tool["name"] == "checkpoint.restore_last"
        )
        assert restore_metadata["remote"] is False

        summary = {
            "blender_version": bpy.app.version_string,
            "network_request_id": network_response["id"],
            "checkpoint_id": checkpoint["checkpoint_id"],
            "object": object_name,
            "mesh_vertices": inspected["mesh"]["vertices"],
            "capture_bytes": capture["file_size_bytes"],
            "registered_tools": len(runtime.registry.list_tools()),
        }
        print("BLENDER_CODEX_SMOKE_OK " + json.dumps(summary, sort_keys=True))
    finally:
        runtime.stop_server()
        blender_codex_bridge.unregister()
        if capture_path is not None:
            capture_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
