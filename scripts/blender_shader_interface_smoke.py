"""Typed shader interface edits, live consent faults and fresh-process graphs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT/"addon"))
sys.path.insert(0, str(ROOT/"scripts"))
import blender_codex_bridge  # noqa: E402
import blender_shader_interface_probe_smoke as probe  # noqa: E402
from blender_codex_bridge.command_queue import QueuedRequest  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.protocol import Request  # noqa: E402
from blender_codex_bridge.request_lifecycle import ConnectionLifetime, RequestLifetime  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import shader_interface as domain  # noqa: E402
from native_fixture_save import serialize_owned_fixture  # noqa: E402


def resolve(refs):
    roots = {"Material": bpy.data.materials, "World": bpy.data.worlds, "Light": bpy.data.lights}
    return [bpy.data.node_groups[ref["name"]] if ref["kind"] == "GROUP" else roots[ref["kind"]][ref["name"]].node_tree for ref in refs]


def plan(runtime, identifier, operation, **extra):
    params = {"group_name": "Probe Shared Leaf", "socket_identifier": identifier, "operation": operation, **extra}
    preview = runtime.dispatch("shader_group.interface_preview", params)
    assert not preview["native_writes"] and not preview["project_saved"]
    assert preview["affected_objects"] == ["Light", "Probe Consumer A", "Probe Consumer B"], preview
    assert preview["affected_world_scenes"] == [bpy.context.scene.name]
    assert preview["root_owners"] == [["Light", "Light"], ["Material", "Probe Material A"], ["Material", "Probe Material B"], ["World", "Probe World"]]
    return {**params, "allow_shared": True, "expected_fingerprint": preview["fingerprint"]}


def denied(function, code=None):
    try:
        function()
    except BridgeError as error:
        if code is not None:
            assert error.code == code, error.to_dict()
        return error
    raise AssertionError("Expected a structured closed failure")


def differences(a, b, path=""):
    if type(a) is not type(b):
        return [[path, a, b]]
    if isinstance(a, dict):
        result = []
        for key in sorted(set(a) | set(b), key=str):
            result.extend(differences(a.get(key), b.get(key), path+"/"+str(key)))
        return result
    if isinstance(a, list):
        if len(a) != len(b):
            return [[path+"/length", len(a), len(b)]]
        return [part for i, (left, right) in enumerate(zip(a, b, strict=True)) for part in differences(left, right, path+"/"+str(i))]
    return [] if a == b else [[path, a, b]]


def native_provider_faults(runtime, identifier, refs):
    context, manager = runtime.executor.context, runtime.executor.context.permissions
    outcomes = []
    for recovery in (False, True):
        for signal in ("paused", "emergency_stopped", "mode", "toolset", "queued_cancel", "queued_expiry", "disconnect", "handoff_rejected"):
            params = plan(runtime, identifier, "SET_DEFAULT", value=.625)
            original = probe.snapshot(resolve(refs))
            source, write, capture, assignments = manager._source, domain._write, domain._capture, []
            boundary = {"prepared": False, "written": False, "poisoned": False}
            lifetime = RequestLifetime(ConnectionLifetime())
            request = Request(id="shader-native-"+signal, method="shader_group.interface_edit", params=params, _lifecycle=lifetime)
            queued = QueuedRequest(request)
            assert queued.try_start()

            def captured(*args, capture=capture, boundary=boundary):
                result = capture(*args)
                boundary["prepared"] = True
                return result

            def provider(boundary=boundary, signal=signal, source=source, recovery=recovery, queued=queued, lifetime=lifetime):
                if not boundary["poisoned"] and (boundary["written"] if recovery else boundary["prepared"]):
                    boundary["poisoned"] = True
                    if signal == "mode":
                        assert bpy.ops.object.mode_set(mode="EDIT") == {"FINISHED"}
                    elif signal in {"paused", "emergency_stopped"}:
                        getattr(runtime.state, "set_"+signal)(True)
                    elif signal == "toolset":
                        runtime.registry.disable_toolset("nodes")
                    elif signal == "queued_cancel":
                        queued.cancel_pending(BridgeError("TIMEOUT", "Native canonical caller canceled"))
                    elif signal == "queued_expiry":
                        queued.deadline = 0
                    elif signal == "disconnect":
                        lifetime.connection.disconnected.set()
                    else:
                        lifetime.acknowledge(False)
                return source()

            def owned_write(tree, operation, *, inverse=False, assignments=assignments, write=write, recovery=recovery, boundary=boundary):
                assignments.append("inverse" if inverse else "forward")
                write(tree, operation, inverse=inverse)
                boundary["written"] = True
                if recovery:
                    raise RuntimeError("Injected native failure after complete owned assignment")

            manager._source, domain._write, domain._capture = provider, owned_write, captured
            try:
                response = runtime.executor.execute_request(request, check_cancelled=queued.check_active)
                assert not response.ok, response.result
                failure = response.error["context"]
                assert boundary["poisoned"]
                assert assignments == (["forward"] if recovery else [])
                assert failure["possible_mutation"] == recovery
                assert failure["rollback_verified"] != recovery
                current = probe.interface(bpy.data.node_groups["Probe Shared Leaf"], identifier).default_value
                assert current == (.625 if recovery else .25)
                if signal in {"paused", "emergency_stopped"}:
                    assert domain.preview(context, {key: setting for key, setting in params.items()
                        if key not in {"allow_shared", "expected_fingerprint"}})["fingerprint"]
            finally:
                manager._source, domain._write, domain._capture = source, write, capture
                runtime.registry.enable_toolset("nodes")
                runtime.state.set_paused(False)
                runtime.state.set_emergency_stopped(False)
                if bpy.context.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
                probe.interface(bpy.data.node_groups["Probe Shared Leaf"], identifier).default_value = .25
            assert probe.snapshot(resolve(refs)) == original
            outcomes.append({"signal": signal, "recovery": recovery, "granted_provider_fault": True,
                "canonical_queued_request": True, "zero_unpermitted_assignments": True,
                "partial_state_truthful": True, "provider_trigger": "prepared/written boundary predicate"})
    return outcomes


def native_socket_family_proof(runtime):
    """Prove every default family/direction exposed by the typed contract."""
    tree, _source, _output = probe.group("Typed Default Families")
    outcomes = []
    for direction in ("INPUT", "OUTPUT"):
        for kind, initial, desired in (("NodeSocketFloat", .125, .625), ("NodeSocketInt", 2, 7),
            ("NodeSocketBool", False, True), ("NodeSocketVector", [.125, .25, .5], [.75, .625, .875]),
            ("NodeSocketColor", [.125, .25, .5, 1.], [.75, .625, .875, 1.])):
            item = tree.interface.new_socket(name=direction+kind, in_out=direction, socket_type=kind)
            item.default_value = initial
            identifier = item.identifier
            before, scope = domain._capture(bpy, tree)
            params = {"group_name": tree.name, "socket_identifier": identifier, "operation": "SET_DEFAULT", "value": desired}
            preview = runtime.dispatch("shader_group.interface_preview", params)
            try:
                runtime.dispatch("shader_group.interface_edit", {**params, "expected_fingerprint": preview["fingerprint"]})
            except Exception:
                after, _summary = domain._capture(bpy, tree)
                print("SHADER_DEFAULT_FAMILY_DIFF "+json.dumps({"type": kind, "direction": direction,
                    "before": before, "after": after, "scope": scope}), flush=True)
                raise
            assert probe.value(item.default_value) == desired
            outcomes.append({"type": kind, "direction": direction, "exact_interface_only_delta": True})
    # Exercise output rename/reorder and active interface index as native UI state.
    item = next(item for item in tree.interface.items_tree if item.in_out == "OUTPUT")
    tree.interface.active_index = list(tree.interface.items_tree).index(item)
    for operation, extra in (("RENAME", {"new_name": "Renamed Output"}), ("MOVE", {"to_index": 4}), ("MOVE", {"to_index": 0})):
        for entry in tree.interface.items_tree:
            if hasattr(entry, "select"):
                entry.select = extra.get("to_index") == 0 and entry.identifier in {item.identifier, "Socket_6"}
        active_before = getattr(tree.interface.active, "identifier", None)
        params = {"group_name": tree.name, "socket_identifier": item.identifier, "operation": operation, **extra}
        preview = runtime.dispatch("shader_group.interface_preview", params)
        runtime.dispatch("shader_group.interface_edit", {**params, "expected_fingerprint": preview["fingerprint"]})
        print("SHADER_ACTIVE_INTERFACE_CONTEXT "+json.dumps({"operation": operation,
            "active_before": active_before, "active_after": getattr(tree.interface.active, "identifier", None),
            "active_index_after": tree.interface.active_index}), flush=True)
        assert getattr(tree.interface.active, "identifier", None) == active_before
    return outcomes


def native_scope_and_recovery_faults(runtime, identifier, refs):
    """Real ownership acquisition, same-name ID replacement and protected edits."""
    context, manager = runtime.executor.context, runtime.executor.context.permissions
    outcomes = []
    for fault in ("acquired_owner", "replaced_identity", "verification_failure", "protected_late_edit"):
        params = plan(runtime, identifier, "SET_DEFAULT", value=.625)
        original = probe.snapshot(resolve(refs))
        leaf = bpy.data.node_groups["Probe Shared Leaf"]
        source, write, capture = manager._source, domain._write, domain._capture
        assignments, created, boundary = [], [], {"prepared": False, "poisoned": False}
        protected = bpy.data.node_groups["Probe Shared Outer"].nodes["Right"].inputs["Tint"]
        protected_default = tuple(protected.default_value)

        def captured(*args, capture=capture, boundary=boundary):
            result = capture(*args)
            boundary["prepared"] = True
            return result

        def provider(source=source, fault=fault, boundary=boundary, created=created, leaf=leaf):
            if not boundary["poisoned"] and boundary["prepared"]:
                boundary["poisoned"] = True
                if fault == "acquired_owner":
                    obj = bpy.data.objects.new("Acquired Light Consumer", bpy.data.lights["Light"])
                    bpy.context.scene.collection.objects.link(obj)
                    created.append(obj)
                elif fault == "replaced_identity":
                    leaf.name = "Original Definition Retained"
                    replacement = leaf.copy()
                    replacement.name = "Probe Shared Leaf"
                    created.append(replacement)
            return source()

        def owned_write(tree, operation, *, inverse=False, assignments=assignments, write=write, fault=fault, protected=protected):
            assignments.append("inverse" if inverse else "forward")
            write(tree, operation, inverse=inverse)
            if not inverse:
                if fault == "protected_late_edit":
                    protected.default_value = (.875, .125, .25, 1.)
                if fault in {"verification_failure", "protected_late_edit"}:
                    raise RuntimeError("Injected native failure after owned assignment")

        manager._source, domain._write, domain._capture = provider, owned_write, captured
        try:
            failure = denied(lambda params=params: domain.edit(context, params))
            if fault in {"acquired_owner", "replaced_identity"}:
                assert not assignments and not failure.context["possible_mutation"]
            elif fault == "protected_late_edit":
                assert assignments == ["forward"] and failure.context["possible_mutation"]
                assert tuple(protected.default_value) == (.875, .125, .25, 1.)
            else:
                assert assignments == ["forward", "inverse"]
                assert failure.context["rollback_verified"] and not failure.context["possible_mutation"]
        finally:
            manager._source, domain._write, domain._capture = source, write, capture
            for created_owner in created:
                if fault == "acquired_owner":
                    bpy.data.objects.remove(created_owner, do_unlink=True)
                else:
                    bpy.data.node_groups.remove(created_owner)
                    leaf.name = "Probe Shared Leaf"
            probe.interface(leaf, identifier).default_value = .25
            protected.default_value = protected_default
        assert probe.snapshot(resolve(refs)) == original
        outcomes.append({"fault": fault, "native_assignments": assignments,
            "unknown_external_edit_preserved": fault == "protected_late_edit",
            "rollback_verified": fault == "verification_failure",
            "fixture_owned_cleanup_verified": True})
    return outcomes


def writer(runtime, grants, bundle):
    leaf, _outer, identifiers, trees = probe.setup()
    refs = [probe.tree_reference(tree) for tree in trees]
    identifier = identifiers["Roughness"]
    initial_ids = [item.identifier for item in leaf.interface.items_tree]
    original = probe.snapshot(trees)
    # Demonstrate the exact RNA references counted by the product ownership gate.
    print("SHADER_NATIVE_OWNER_COUNTS "+json.dumps([[owner.bl_rna.identifier, owner.name,
        owner.user_of_id(leaf)] for owner in bpy.data.user_map(subset={leaf}).get(leaf, ())]), flush=True)
    params = plan(runtime, identifier, "RENAME", new_name="Surface Roughness")
    denied(lambda: runtime.dispatch("shader_group.interface_edit", {**params, "allow_shared": False}), "INVALID_ARGUMENT")
    grants[Permission.EDIT_MATERIALS.value] = False
    denied(lambda: runtime.dispatch("shader_group.interface_edit", params), "PERMISSION_DENIED")
    grants[Permission.EDIT_MATERIALS.value] = True
    denied(lambda: runtime.dispatch("shader_group.interface_edit", {**params, "expected_fingerprint": "0"*64}), "INVALID_ARGUMENT")
    bpy.ops.object.mode_set(mode="EDIT")
    denied(lambda: runtime.dispatch("shader_group.interface_preview", {key: value for key, value in params.items()
        if key not in {"allow_shared", "expected_fingerprint"}}), "INVALID_MODE")
    bpy.ops.object.mode_set(mode="OBJECT")
    assert probe.snapshot(trees) == original
    faults = native_provider_faults(runtime, identifier, refs)
    scope_faults = native_scope_and_recovery_faults(runtime, identifier, refs)
    socket_families = native_socket_family_proof(runtime)
    results = []
    for operation, extra in (("RENAME", {"new_name": "Surface Roughness"}), ("MOVE", {"to_index": 2}), ("SET_DEFAULT", {"value": .75})):
        params = plan(runtime, identifier, operation, **extra)
        before = probe.snapshot(trees)
        exact_before, _scope = domain._capture(bpy, leaf)
        projected = domain._project(exact_before, leaf.as_pointer(), domain._plan(leaf, params))
        defaults = probe.defaults(trees, leaf.name, identifier)
        try:
            result = runtime.dispatch("shader_group.interface_edit", params)
        except Exception:
            exact_after, _scope = domain._capture(bpy, leaf)
            print("SHADER_EXACT_NATIVE_DIFF "+json.dumps(differences(projected, exact_after)[:20]), flush=True)
            # Retain a compact independent diff to diagnose exact native RNA propagation.
            print("SHADER_INTERFACE_NATIVE_BEFORE "+json.dumps(before), flush=True)
            print("SHADER_INTERFACE_NATIVE_AFTER "+json.dumps(probe.snapshot(trees)), flush=True)
            raise
        assert result["protected_graph_state_preserved"] and result["existing_instance_defaults_preserved"]
        assert set(initial_ids) == {item.identifier for item in leaf.interface.items_tree}
        assert probe.defaults(trees, leaf.name, identifier) == defaults
        after = probe.snapshot(trees)
        assert probe.without_edit(before, leaf.name, identifier, operation) == probe.without_edit(after, leaf.name, identifier, operation)
        results.append({"operation": operation, "all_identifiers_links_existing_defaults_preserved": True})
    shader_identifier = next(item.identifier for item in leaf.interface.items_tree if item.socket_type == "NodeSocketShader")
    for operation, extra in (("RENAME", {"new_name": "Surface Shader"}), ("MOVE", {"to_index": 0})):
        params = plan(runtime, shader_identifier, operation, **extra)
        before = probe.snapshot(trees)
        runtime.dispatch("shader_group.interface_edit", params)
        assert probe.without_edit(before, leaf.name, shader_identifier, operation) == probe.without_edit(probe.snapshot(trees), leaf.name, shader_identifier, operation)
        results.append({"operation": operation, "socket_type": "NodeSocketShader", "all_identifiers_links_existing_defaults_preserved": True})
    fresh = probe.instance(bpy.data.node_groups["Probe Shared Outer"], leaf, "New Instance Inherits")
    assert probe.socket(fresh.inputs, identifier).default_value == .75
    fresh.id_data.nodes.remove(fresh)
    # Native unsupported animation is rejected before a single interface write.
    tree = bpy.data.materials["Probe Material A"].node_tree
    tree.animation_data_create()
    before = probe.snapshot(trees)
    denied(lambda: runtime.dispatch("shader_group.interface_preview", {"group_name": leaf.name,
        "socket_identifier": identifier, "operation": "MOVE", "to_index": 0}), "NOT_IMPLEMENTED")
    assert probe.snapshot(trees) == before
    tree.animation_data_clear()
    denied(lambda: runtime.dispatch("shader_group.interface_preview", {"group_name": leaf.name,
        "socket_identifier": identifier, "operation": "CONVERT"}), "NOT_IMPLEMENTED")
    # One complete tool edit participates in logical/native global undo.
    before_undo = probe.snapshot(trees)
    params = plan(runtime, identifier, "RENAME", new_name="Undo This Name")
    runtime.dispatch("shader_group.interface_edit", params)
    undo = runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
    assert undo["undone"], undo
    trees = resolve(refs)
    assert probe.snapshot(trees) == before_undo
    leaf = bpy.data.node_groups["Probe Shared Leaf"]
    expected = {"graphs": probe.snapshot(trees), "references": refs, "identifiers": initial_ids,
        "roughness_identifier": identifier, "leaf": leaf.name}
    fixture_save = serialize_owned_fixture(runtime, bundle/"shader-interface.blend")
    (bundle/"expected.json").write_text(json.dumps(expected), encoding="utf-8")
    return {"phase": "writer", "blender_version": bpy.app.version_string,
        "typed_operations": results, "socket_families": socket_families, "native_provider_faults": faults,
        "native_scope_recovery_faults": scope_faults, "native_undo_verified": True,
        "new_instance_default_verified": True, "shared_material_world_light_scope_verified": True,
        **fixture_save, "permission_mode_stale_preview_and_animation_denials": True, "fixture_project_serialized": True,
        "visual_review": "No rendered appearance claim; exact interface/link/default comparisons only."}


def reader(runtime, _grants, bundle):
    expected = json.loads((bundle/"expected.json").read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(bundle/"shader-interface.blend"), load_ui=False)
    runtime.registry.enable_toolset("nodes")
    trees = resolve(expected["references"])
    assert probe.snapshot(trees) == expected["graphs"]
    leaf = bpy.data.node_groups[expected["leaf"]]
    assert set(expected["identifiers"]) == {item.identifier for item in leaf.interface.items_tree}
    identifier = expected["roughness_identifier"]
    assert probe.interface(leaf, identifier).default_value == .75
    params = plan(runtime, identifier, "RENAME", new_name="Reopened Read Only")
    assert params["expected_fingerprint"]
    return {"phase": "reader", "blender_version": bpy.app.version_string,
        "fresh_process_all_nested_graphs_and_root_bindings_verified": True,
        "stable_identifiers_existing_defaults_definition_default_verified": True,
        "new_process_read_only_scope_proof": True, "project_saved_by_reader": False}


def run():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
        parser.add_argument("--bridge-bundle", type=Path, required=True)
        args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
        blender_codex_bridge.register()
        runtime = get_runtime()
        grants = {permission.value: permission in (Permission.INSPECT_SCENE, Permission.EDIT_MATERIALS,
            Permission.SAVE_PROJECT, Permission.ACCESS_EXTERNAL_FILES) for permission in Permission}
        manager = PermissionManager(lambda: grants)
        runtime.permissions = runtime.executor.permissions = manager
        runtime.registry.enable_toolset("nodes")
        result = (writer if args.bridge_phase == "writer" else reader)(runtime, grants, args.bridge_bundle.resolve(strict=True))
        result.update(process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid())
        print("BLENDER_SHADER_INTERFACE_"+args.bridge_phase.upper()+"_OK "+json.dumps(result), flush=True)
    except Exception as error:
        if isinstance(error, BridgeError):
            print("SHADER_INTERFACE_FAILURE "+json.dumps(error.to_dict()), flush=True)
        traceback.print_exc()
    finally:
        bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=.5)


bpy.app.timers.register(run, first_interval=1.)
