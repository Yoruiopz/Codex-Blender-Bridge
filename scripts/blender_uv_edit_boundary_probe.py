"""Owned UV boundary prerequisites: exposed capture, schema witnesses, checkpoints.

This is native research, not a public UV guard. Old ordinary loops are queried
only for wrapper validity after schema changes; old UV/layer/vector payloads are
never retained. Exposed inventories cannot prove internal PYPTR allocation purity.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import traceback
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
NAMES = ("Boundary Primary", "Boundary Secondary")
TEMP = "Boundary Temporary"
METHOD = "fixture.uv_edit_checkpoint_noop"


def indices(bm: Any) -> dict[str, Any] | None:
    if bm is None or not bm.is_valid:
        return None
    return {name: [item.index for item in getattr(bm, name)] for name in ("verts", "edges", "faces")}


def make_proof_type(base: Any, helper: Any, bmesh: Any) -> Any:
    class Probe(base):
        def __init__(self, folder: Path, attestation: dict[str, Any], process_token: str):
            self.path = folder / "uv-edit-boundary-evidence.json"
            assert not self.path.exists()
            self.bm, self.work = None, None
            self.scene, self.layer = bpy.context.scene, bpy.context.scene.view_layers[0]
            self.protected = bpy.data.objects["Cube"]
            self.data: dict[str, Any] = {"blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
                "process_instance": process_token, "owned_profile_attestation": attestation, "completed": False,
                "inventories": {}, "getter_accesses": [], "object_property_copies": [], "actions": [],
                "observations": [], "schema_cases": [], "witnesses": [], "optional_unavailable": [],
                "checkpoint_receipts": [], "checkpoint_counts": {},
                "scope": "Three separate raw research phases; capture effects, same-BMesh schema invalidation, actual normal Edit Mode NOOP checkpoint/history",
                "fixture_remote_spec_scope": "Only this owned factory probe registers the transport-admissible NOOP; no server start or production registry/package tool-count change",
                "limits": {"internal_PYPTR_allocation_purity_qualified": False, "persistent_layer_identity_qualified": False,
                    "all_schema_or_session_paths_qualified": False, "production_UV_guard_qualified": False,
                    "checkpoint_admission_factory_qualified": False, "public_UV_mutator_invoked": False,
                    "provider_faults": False, "rollback_or_native_undo_qualified": False, "durable_recovery": False,
                    "project_saved": False, "visual_capture": False, "artist_goal_verified": False,
                    "Windows_qualified": False, "release_acceptance": False},
                "termination": "Owned fixture os._exit after JSON/stdio flush; no save/quit callbacks"}
            self.flush()

        def action(self, label: str, callback: Any) -> Any:
            row = {"label": label, "indices_before": indices(self.bm), "inventory_before": self.inventory(),
                   "context_before": self.context(), "consumers_before": self.consumers()}
            self.data["actions"].append(row)
            self.flush()
            try:
                result = callback()
                row["returned"] = sorted(result) if isinstance(result, set) else None
                return result
            finally:
                row["indices_after"], row["inventory_after"] = indices(self.bm), self.inventory()
                row["context_after"], row["consumers_after"] = self.context(), self.consumers()
                self.flush()

        def read_maps(self, stage: str, *, edit: bool) -> dict[str, Any]:
            assert edit, "This probe has no Object Mode UV reader"
            names = list(self.bm.loops.layers.uv.keys())
            assert 1 <= len(names) <= 3
            keys = [(face.index, corner) for face in self.bm.faces for corner, _loop in enumerate(face.loops)]
            assert len(keys) == 8
            result = {}
            for name in names:
                corners = []
                for face_index, corner_index in keys:
                    def fresh_copy(name: str = name, face_index: int = face_index, corner_index: int = corner_index) -> dict[str, Any]:
                        current = bmesh.from_edit_mesh(self.work.data)
                        face = next(face for face in current.faces if face.index == face_index)
                        loop = next(loop for ordinal, loop in enumerate(face.loops) if ordinal == corner_index)
                        assert current.is_valid and loop.is_valid
                        vertex, edge = loop.vert.index, loop.edge.index
                        layer = current.loops.layers.uv.get(name)
                        assert layer is not None
                        uv = loop[layer]
                        coordinates = [float(value) for value in uv.uv]
                        row = {"face": face_index, "corner": corner_index, "vertex": vertex, "edge": edge,
                               "uv": coordinates, "float32_le": helper.pair_bits(coordinates)}
                        fields = ("pin_uv",) if self.global_selection else ("pin_uv", "select", "select_edge")
                        unavailable = {}
                        for field in fields:
                            if not helper.has_static(uv, field):
                                row[field] = None
                                unavailable[field] = {"reason": "property_absent"}
                                continue
                            try:
                                row[field] = bool(getattr(uv, field))
                            except (RuntimeError, SystemError) as error:
                                row[field] = None
                                unavailable[field] = {"reason": "native_getter_unavailable", "type": type(error).__name__, "message": str(error)[:180]}
                        if unavailable:
                            row["optional_unavailable"] = unavailable
                        # Return only copied primitives. All native handles die
                        # before the inventory/flush callback after this copy.
                        return row

                    copied = self.access(f"{stage}:fresh_corner:{name}:{face_index}:{corner_index}", fresh_copy)
                    if "optional_unavailable" in copied:
                        self.data["optional_unavailable"].append({"stage": stage, "map": name,
                            "face": face_index, "corner": corner_index, "fields": copied["optional_unavailable"]})
                    corners.append(copied)
                result[name] = corners
            return result

        def capture_loops(self) -> tuple[Any, list[Any], list[Any]]:
            current = bmesh.from_edit_mesh(self.work.data)
            faces = list(current.faces)
            loops = [loop for face in faces for loop in face.loops]
            assert len(faces) == 2 and len(loops) == 8 and all(loop.is_valid for loop in loops)
            return current, faces, loops

        def witness(self, label: str, held: tuple[Any, list[Any], list[Any]], *, fresh: bool = False) -> dict[str, Any]:
            bm, faces, loops = held
            row = {"label": label, "bmesh": helper.wrapper(bm), "faces": [helper.wrapper(face) for face in faces],
                   "loops": [helper.wrapper(loop) for loop in loops]}
            if fresh:
                current, new_faces, new_loops = self.capture_loops()
                row["fresh_bmesh"] = helper.wrapper(current)
                row["fresh_faces"], row["fresh_loops"] = [helper.wrapper(face) for face in new_faces], [helper.wrapper(loop) for loop in new_loops]
                row["same_bmesh_python_wrapper"] = current is bm
                row["same_loop_python_wrappers"] = [old is new for old, new in zip(loops, new_loops, strict=True)]
            self.data["witnesses"].append(row)
            self.flush()
            return row

    return Probe


def main() -> None:
    import blender_uv_edit_storage_smoke as helper
    import bmesh
    from blender_artist_quaternion_storage_smoke import owned_profile

    folder, process_token, attestation = owned_profile()
    proof = make_proof_type(helper.Proof, helper, bmesh)(folder, attestation, process_token)
    try:
        bpy.context.preferences.use_preferences_save = False
        bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
        proof.data["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
            Path(__file__), ROOT / "scripts/blender_uv_edit_storage_smoke.py", ROOT / "scripts/blender_artist_quaternion_storage_smoke.py",
            ROOT / "scripts/blender_artist_sidebar_smoke.py", ROOT / "addon/blender_codex_bridge/checkpoints.py",
            ROOT / "addon/blender_codex_bridge/executor.py", ROOT / "addon/blender_codex_bridge/tool_registry.py",
            ROOT / "scripts/blender_artist_target_verification_smoke.py")}
        mesh = bpy.data.meshes.new("UV Boundary Geometry")
        mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (2., 0., 0.), (0., 1., 0.), (1., 1., 0.), (2., 1., 0.)],
                         [], [(0, 1, 4, 3), (1, 2, 5, 4)])
        mesh.update()
        proof.work = bpy.data.objects.new("UV Boundary Working", mesh)
        proof.scene.collection.objects.link(proof.work)
        predictions = {}
        for ordinal, name in enumerate(NAMES):
            proof.action("setup_create_map:" + name, lambda name=name: mesh.uv_layers.new(name=name))
            attribute = mesh.attributes.get(name)
            assert attribute is not None and attribute.data_type == "FLOAT2" and attribute.domain == "CORNER"
            predictions[name] = []
            for corner, value in enumerate(attribute.data):
                requested = (.125 * (corner + ordinal), .25 * ((corner + ordinal) % 3))
                predictions[name].append({"ordinal": corner, "requested": list(requested),
                    "requested_float64_le": [struct.pack("<d", component).hex() for component in requested],
                    "expected_float32_le": helper.pair_bits(requested)})
                value.vector = requested
        proof.data["initial_independent_UV_predictions"] = predictions
        mesh.uv_layers.active_index = 0
        for sequence in (mesh.vertices, mesh.edges, mesh.polygons):
            for item in sequence:
                item.select = True
        mesh.edges[0].use_seam = True
        material = bpy.data.materials.new("UV Boundary Material")
        mesh.materials.append(material)
        for obj in proof.layer.objects:
            obj.select_set(False, view_layer=proof.layer)
        proof.work.select_set(True, view_layer=proof.layer)
        proof.layer.objects.active = proof.work
        proof.scene.tool_settings.use_uv_select_sync = False
        proof.scene.tool_settings.mesh_select_mode = (False, False, True)
        proof.layer.update()
        proof.data["setup_literal_mesh_before_edit"] = proof.mesh_view(proof.work)
        protected = proof.mesh_view(proof.protected)
        proof.data["protected_peer_baseline"] = protected
        proof.flush()
        proof.action("A:enter_edit_mode", lambda: bpy.ops.object.mode_set(mode="EDIT"))

        def acquire() -> Any:
            proof.bm = bmesh.from_edit_mesh(mesh)
            return proof.bm

        proof.action("A:first_from_edit_mesh", acquire)
        for name in ("verts", "edges", "faces"):
            sequence = getattr(proof.bm, name)
            proof.action("A:ensure_lookup_table:" + name, sequence.ensure_lookup_table)
            proof.action("A:index_update:" + name, sequence.index_update)
        first = proof.action("A:first_ordinary_loop_capture", proof.capture_loops)
        proof.witness("A:before_first_UV_payload_copy", first)
        sample_loop = first[2][0]
        caps = {"BMesh.uv_select_sync_valid": helper.has_static(proof.bm, "uv_select_sync_valid"),
                "BMFace.uv_select": all(helper.has_static(face, "uv_select") for face in first[1]),
                "BMLoop.uv_select_vert": helper.has_static(sample_loop, "uv_select_vert"),
                "BMLoop.uv_select_edge": helper.has_static(sample_loop, "uv_select_edge")}
        proof.data["selection_capabilities_before_getters"] = caps
        proof.flush()
        assert all(caps.values()) or not any(caps.values())
        proof.global_selection = all(caps.values())
        baseline = proof.observe("A:first_complete_fresh_copy", edit=True)
        proof.witness("A:after_first_UV_payload_copy", first, fresh=True)
        for name in NAMES:
            assert [row["float32_le"] for row in baseline["maps"][name]] == [row["expected_float32_le"] for row in predictions[name]]
        assert baseline["protected_peer"] == protected
        rest = baseline["edit_rest_after"]

        def schema_change(operation: str, name: str) -> None:
            current = bmesh.from_edit_mesh(mesh)
            if operation == "add":
                current.loops.layers.uv.new(name)
            else:
                layer = current.loops.layers.uv.get(name)
                assert layer is not None
                current.loops.layers.uv.remove(layer)
            # No returned layer, UV wrapper or vector is retained or read here.

        scenarios = (("add_temporary", "add", TEMP, [*NAMES, TEMP]),
                     ("remove_temporary", "remove", TEMP, list(NAMES)),
                     ("remove_secondary", "remove", NAMES[1], [NAMES[0]]),
                     ("recreate_secondary_same_name", "add", NAMES[1], list(NAMES)))
        for label, operation, name, expected_names in scenarios:
            before = proof.observe("B:" + label + ":before", edit=True)
            held = proof.capture_loops()
            proof.witness("B:" + label + ":before_schema", held)
            proof.action("B:" + label + ":schema_write", lambda operation=operation, name=name: schema_change(operation, name))
            after_witness = proof.witness("B:" + label + ":after_schema_before_payload", held, fresh=True)
            after = proof.observe("B:" + label + ":after_fresh_copy", edit=True)
            row = {"label": label, "operation": operation, "name": name, "expected_map_order": expected_names,
                   "before": before["label"], "after": after["label"], "witness": after_witness["label"],
                   "allowance": "Fixture-owned map add/remove/recreate and its new map contents/optional storage/UV active role; never persistent layer identity"}
            proof.data["schema_cases"].append(row)
            proof.flush()
            assert list(after["maps"]) == expected_names
            assert after_witness["bmesh"]["is_valid"] is True and after_witness["same_bmesh_python_wrapper"] is True
            assert all(item["is_valid"] is False for item in after_witness["loops"])
            assert all(item["is_valid"] is True for item in after_witness["fresh_loops"])
            assert after["maps"][NAMES[0]] == before["maps"][NAMES[0]]
            if label in {"add_temporary", "remove_temporary"}:
                assert after["maps"][NAMES[1]] == before["maps"][NAMES[1]]
            assert after["edit_rest_after"] == rest and after["uv_selection"] == before["uv_selection"]
            assert after["context_after"] == before["context_before"] and after["protected_peer"] == protected
            assert after["consumers_after"] == before["consumers_before"]

        # A private NOOP intentionally follows the normal registered executor.
        # It does not add an admission factory or call a public UV mutator.
        sys.path.insert(0, str(ROOT / "addon"))
        import blender_codex_bridge
        from blender_artist_target_verification_smoke import (
            checkpoint_state as full_checkpoint_state,
        )
        from blender_codex_bridge.permissions import Permission, PermissionManager
        from blender_codex_bridge.runtime import get_runtime

        proof.action("C:register_addon", blender_codex_bridge.register)
        runtime = get_runtime()
        grants = {permission.value: permission in {Permission.INSPECT_SCENE, Permission.EDIT_MESH} for permission in Permission}
        manager = PermissionManager(lambda: dict(grants))
        runtime.permissions = runtime.executor.permissions = manager
        runtime.registry.enable_toolset("uv")
        entered: list[bool] = []

        def noop(_context: Any, _params: Any) -> dict[str, Any]:
            entered.append(True)
            return {"changed": False, "affected_objects": [], "fixture_only_noop": True}

        # Fixture-only registration permits ordinary dispatch; no server is started.
        runtime.registry.register(METHOD, noop, permissions=(Permission.EDIT_MESH,), toolset="uv", modifies=True, remote=True, batchable=False)
        counts = {name: 0 for name in ("before_modification", "after_modification", "_stamp", "_snapshot")}
        proof.data["checkpoint_counts"] = counts
        checkpoint = runtime.checkpoints
        originals = {name: getattr(checkpoint, name) for name in counts}

        def checkpoint_state() -> dict[str, Any]:
            return {"manager": full_checkpoint_state(runtime),
                "scene_custom": {key: proof.scene[key] for key in sorted(proof.scene.keys())},
                "history": runtime.state.history(100), "context": proof.context()}

        def observer(name: str, delegate: Any) -> Any:
            def call(*args: Any, **kwargs: Any) -> Any:
                row = {"delegate": name, "call_number": counts[name] + 1, "before": checkpoint_state(),
                       "handler_entries_before": len(entered), "completed": False}
                counts[name] += 1
                proof.data["checkpoint_receipts"].append(row)
                proof.flush()
                try:
                    result = delegate(*args, **kwargs)
                    row["returned"], row["completed"] = result, True
                    return result
                finally:
                    row["after"], row["handler_entries_after"] = checkpoint_state(), len(entered)
                    proof.flush()
            return call

        before = proof.observe("C:before_registered_noop", edit=True)
        held = proof.capture_loops()
        history_before = runtime.state.history(100)
        proof.data["checkpoint_baseline"] = checkpoint_state()
        for name, delegate in originals.items():
            setattr(checkpoint, name, observer(name, delegate))
        try:
            result = runtime.dispatch(METHOD, {})
        finally:
            for name, delegate in originals.items():
                setattr(checkpoint, name, delegate)
        proof.data["noop_result"] = result
        proof.witness("C:after_registered_noop", held, fresh=True)
        after = proof.observe("C:after_registered_noop_fresh_copy", edit=True)
        proof.data["checkpoint_final"] = checkpoint_state()
        proof.flush()
        assert counts == {"before_modification": 1, "after_modification": 0, "_stamp": 1, "_snapshot": 0}
        receipt = next(row for row in proof.data["checkpoint_receipts"] if row["delegate"] == "before_modification")
        assert receipt["returned"] is False and receipt["completed"] is True
        assert receipt["handler_entries_before"] == receipt["handler_entries_after"] == 0 and entered == [True]
        history_after = runtime.state.history(100)
        assert len(history_after) == len(history_before) + 1 and history_after[1:] == history_before
        assert history_after[0]["tool"] == METHOD and history_after[0]["success"] is True
        assert after["maps"] == before["maps"] and after["uv_selection"] == before["uv_selection"]
        assert after["edit_rest_after"] == before["edit_rest_after"] and after["context_after"] == before["context_before"]
        assert after["protected_peer"] == protected and after["consumers_after"] == before["consumers_before"]
        assert all(loop.is_valid for loop in held[2])
        proof.data["completed"] = True
        proof.flush()
        print("BLENDER_UV_EDIT_BOUNDARY_PROBE_OK " + json.dumps({"blender_version": bpy.app.version_string,
            "evidence_file": str(proof.path), "evidence_sha256": hashlib.sha256(proof.path.read_bytes()).hexdigest(),
            "schema_scenarios": 4, "actual_registered_NOOP_history": True, "checkpoint_counts": counts,
            "optional_unavailable_findings": len(proof.data["optional_unavailable"]), **proof.data["limits"]}, allow_nan=False), flush=True)
    except BaseException as error:
        proof.data["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        proof.flush()
        raise


if __name__ == "__main__":
    from blender_artist_quaternion_storage_smoke import owned_profile

    owned_profile()
    from blender_artist_sidebar_smoke import owned_process_exit

    exit_code = 1
    try:
        main()
        exit_code = 0
    except BaseException:
        traceback.print_exc()
    finally:
        owned_process_exit(exit_code)
