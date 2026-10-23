"""Raw unused shader-interface removal, native undo/redo and owned reopen probe.

No public removal tool is added. All writes belong to the isolated factory
fixture. Recreating a socket is deliberately never used as recovery.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import threading
import traceback
from itertools import islice
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
import blender_shader_interface_probe_smoke as fixture  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from native_fixture_save import serialize_owned_fixture  # noqa: E402

KINDS = ("NodeSocketFloat", "NodeSocketInt", "NodeSocketBool", "NodeSocketVector", "NodeSocketColor", "NodeSocketShader")
JOURNAL = {"native_only_probe": True, "typed_removal_supported": False, "cases": []}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def literal(value, depth=0):
    assert depth <= 8
    if value is None or type(value) in {str, bool, int}:
        assert not isinstance(value, str) or len(value) <= 4096
        return value
    if isinstance(value, float):
        assert math.isfinite(value)
        return value
    if isinstance(value, set):
        value = sorted(value)
    assert not hasattr(value, "as_pointer") and hasattr(value, "__len__") and len(value) <= 64
    return [literal(item, depth + 1) for item in value]


def properties(owner, exclude=()):
    result = {}
    for prop in owner.bl_rna.properties:
        if prop.identifier in exclude or prop.is_readonly or prop.type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            continue
        result[prop.identifier] = literal(getattr(owner, prop.identifier))
    try:
        keys = sorted(owner.keys())
    except (AttributeError, TypeError):
        keys = []
    assert len(keys) <= 128
    if keys:
        result["custom_properties"] = {key: literal(owner[key]) for key in keys}
    return result


def resolve(refs):
    owners = {"Material": bpy.data.materials, "World": bpy.data.worlds, "Light": bpy.data.lights}
    return [bpy.data.node_groups[ref["name"]] if ref["kind"] == "GROUP"
            else owners[ref["kind"]][ref["name"]].node_tree for ref in refs]


def snapshot(refs):
    trees = resolve(refs)
    assert len(trees) <= 16
    graphs, ui = {}, {}
    for tree in trees:
        assert len(tree.nodes) <= 64 and len(tree.links) <= 128 and len(tree.interface.items_tree) <= 64
        assert tree.animation_data is None
        key = fixture.tree_key(tree)
        base = fixture.graph(tree)
        base["properties"] = properties(tree, {"tag"})
        base["interface_properties"] = properties(tree.interface, {"active_index"})
        base["active_node"] = None if tree.nodes.active is None else tree.nodes.active.name
        for record, item in zip(base["interface"], tree.interface.items_tree, strict=True):
            record["properties"] = properties(item, {"select"})
        for record in base["nodes"]:
            node = tree.nodes[record["name"]]
            record["properties"] = properties(node)
            record["parent"] = None if node.parent is None else node.parent.name
            for direction in ("inputs", "outputs"):
                sockets = {item.identifier: item for item in getattr(node, direction) if item.bl_idname != "NodeSocketVirtual"}
                assert len(sockets) == len(record[direction])
                for socket_record in record[direction]:
                    socket_record["properties"] = properties(sockets[socket_record["identifier"]])
                record["virtual_" + direction] = [{"identifier": item.identifier, "type": item.bl_idname,
                    "properties": properties(item), "linked": bool(item.is_linked)}
                    for item in getattr(node, direction) if item.bl_idname == "NodeSocketVirtual"]
        graphs[key] = base
        ui[key] = {"active_index": tree.interface.active_index,
                   "active_identifier": getattr(tree.interface.active, "identifier", None),
                   "selected": {item.identifier: item.select for item in tree.interface.items_tree if hasattr(item, "select")}}
    root_owners = [owner for collection in (bpy.data.materials, bpy.data.worlds, bpy.data.lights)
                   for owner in collection if getattr(owner, "node_tree", None) in trees]
    assert all(owner.animation_data is None for owner in root_owners)
    owner_properties = {owner.bl_rna.identifier + "::" + owner.name: properties(owner, {"tag"}) for owner in root_owners}
    users = bpy.data.user_map(subset=set(trees + root_owners))
    ownership = {}
    for target in trees + root_owners:
        name = "TREE::" + fixture.tree_key(target) if getattr(target, "bl_idname", None) == "ShaderNodeTree" else "ID::" + target.bl_rna.identifier + "::" + target.name
        ownership[name] = sorted([owner.bl_rna.identifier, owner.name, owner.user_of_id(target)] for owner in users.get(target, ()))
    bindings = {obj.name: {"data": None if obj.data is None else obj.data.name,
                "slots": [[slot.link, None if slot.material is None else slot.material.name] for slot in obj.material_slots]}
                for obj in bpy.data.objects}
    context = {"scene": bpy.context.scene.name, "layer": bpy.context.view_layer.name, "mode": bpy.context.mode,
               "active": None if bpy.context.view_layer.objects.active is None else bpy.context.view_layer.objects.active.name,
               "selected": sorted(obj.name for obj in bpy.context.selected_objects),
               "frame": [bpy.context.scene.frame_current, bpy.context.scene.frame_subframe]}
    core = {"graphs": graphs, "ownership": ownership, "owner_properties": owner_properties, "bindings": bindings, "context": context,
            "runtime_flags": {key: row["is_runtime_data"] for key, row in runtime_inventory(refs).items()}}
    assert len(json.dumps(core, allow_nan=False).encode()) <= 1_048_576
    return core, ui


def identities(refs):
    result = {}
    for tree in resolve(refs):
        key = "TREE::" + fixture.tree_key(tree)
        result[key] = tree.as_pointer()
        for node in tree.nodes:
            result[key + "/" + node.name] = node.as_pointer()
    for collection in (bpy.data.materials, bpy.data.worlds, bpy.data.lights, bpy.data.objects, bpy.data.meshes):
        for owner in collection:
            result[owner.bl_rna.identifier + "::" + owner.name] = owner.as_pointer()
    return result


def assert_same(expected, observed, label):
    if expected != observed:
        def differences(left, right, path=""):
            if type(left) is not type(right):
                yield [path, repr(left)[:200], repr(right)[:200]]
            elif isinstance(left, dict):
                for key in sorted(set(left) | set(right)):
                    yield from differences(left.get(key), right.get(key), path + "/" + str(key))
            elif isinstance(left, (list, tuple)):
                if len(left) != len(right):
                    yield [path + "/length", len(left), len(right)]
                for index, (a, b) in enumerate(zip(left, right, strict=False)):
                    yield from differences(a, b, path + "/" + str(index))
            elif left != right:
                yield [path, left, right]
        raise AssertionError(label + ": expected SHA256 " + digest(expected) + ", observed " + digest(observed)
                             + "; first differences " + json.dumps(list(islice(differences(expected, observed), 16))))


def consumers(refs, leaf_name, identifier, direction):
    result = []
    for tree in resolve(refs):
        for node in tree.nodes:
            group = getattr(node, "node_tree", None)
            definition_io = fixture.tree_key(tree) == "GROUP::" + leaf_name and node.bl_idname == ("NodeGroupInput" if direction == "INPUT" else "NodeGroupOutput")
            if group is not None and group.name == leaf_name:
                sockets = node.inputs if direction == "INPUT" else node.outputs
            elif definition_io:
                sockets = node.outputs if direction == "INPUT" else node.inputs
            else:
                continue
            socket = fixture.socket(sockets, identifier)
            assert not socket.is_linked
            assert not any(link.from_socket == socket or link.to_socket == socket for link in tree.links)
            result.append({"tree": fixture.tree_key(tree), "node": node.name, "definition_io": definition_io,
                           "default": literal(socket.default_value) if hasattr(socket, "default_value") else None})
    assert sum(row["definition_io"] for row in result) == 2
    assert any(row["tree"].startswith("Material::") for row in result)
    assert any(row["tree"] == "GROUP::Probe Shared Outer" for row in result)
    return result


def projected(before, leaf_name, identifier, direction):
    expected = copy.deepcopy(before)
    for key, tree in expected["graphs"].items():
        if key == "GROUP::" + leaf_name:
            tree["interface"] = [item for item in tree["interface"] if item["identifier"] != identifier]
        for node in tree["nodes"]:
            if node["group"] == leaf_name:
                side = "inputs" if direction == "INPUT" else "outputs"
            elif key == "GROUP::" + leaf_name and node["type"] == ("NodeGroupInput" if direction == "INPUT" else "NodeGroupOutput"):
                side = "outputs" if direction == "INPUT" else "inputs"
            else:
                continue
            node[side] = [item for item in node[side] if item["identifier"] != identifier]
    return expected


def setting(kind, index):
    if kind == "NodeSocketFloat":
        return .125 + index / 100
    if kind == "NodeSocketInt":
        return 7 + index
    if kind == "NodeSocketBool":
        return bool(index % 2)
    if kind == "NodeSocketVector":
        return (.1 + index / 100, .2, .3)
    if kind == "NodeSocketColor":
        return (.1, .2 + index / 100, .3, 1.)
    return None


def setup():
    leaf, _outer, _identifiers, trees = fixture.setup()
    for kind, collection in (("A", bpy.data.materials), ("B", bpy.data.materials)):
        fixture.instance(collection["Probe Material " + kind].node_tree, leaf, "Direct Leaf " + kind)
    fixture.instance(bpy.data.worlds["Probe World"].node_tree, leaf, "Direct World Leaf")
    leaf.nodes.new("NodeGroupInput").name = "Second Group Input"
    second_output = leaf.nodes.new("NodeGroupOutput")
    second_output.name, second_output.is_active_output = "Second Group Output", False
    leaf.nodes["Group Output"].is_active_output = True
    cases = []
    for direction in ("INPUT", "OUTPUT"):
        for kind in KINDS:
            item = leaf.interface.new_socket(name="Unused " + direction + " " + kind, in_out=direction, socket_type=kind)
            value = setting(kind, len(cases))
            if value is not None:
                item.default_value = value
            cases.append({"identifier": item.identifier, "direction": direction, "socket_type": kind})
    protected = bpy.data.node_groups["Probe Protected Unrelated"]
    for index in range(len(cases)):
        protected.interface.new_socket(name="Protected collision " + str(index), in_out="INPUT", socket_type="NodeSocketFloat")
    assert {case["identifier"] for case in cases}.intersection(item.identifier for item in protected.interface.items_tree)
    refs = [fixture.tree_reference(tree) for tree in trees]
    consumer_index = 17
    for tree in trees:
        for node in tree.nodes:
            if getattr(node, "node_tree", None) == leaf:
                for case in cases:
                    if case["direction"] == "INPUT" and case["socket_type"] != "NodeSocketShader":
                        fixture.socket(node.inputs, case["identifier"]).default_value = setting(case["socket_type"], consumer_index)
                consumer_index += 1
    return leaf.name, refs, cases


def runtime_inventory(refs):
    """Primitive status evidence for fixture shader IDs and binding/context IDs."""
    records = {}

    def include(owner):
        if owner is None:
            return
        key = "TREE::" + fixture.tree_key(owner) if getattr(owner, "bl_idname", None) == "ShaderNodeTree" else "ID::" + owner.bl_rna.identifier + "::" + owner.name
        if key in records:
            return
        assert len(records) < 64
        records[key] = {"is_runtime_data": owner.is_runtime_data,
                        "runtime_status_readonly": owner.is_property_readonly("is_runtime_data"),
                        "embedded": owner.is_embedded_data, "evaluated": owner.is_evaluated,
                        "linked": owner.library is not None, "override": owner.override_library is not None}
        include(getattr(owner, "node_tree", None))

    trees = resolve(refs)
    for tree in trees:
        include(tree)
    for collection in (bpy.data.materials, bpy.data.worlds, bpy.data.lights):
        for owner in collection:
            if getattr(owner, "node_tree", None) in trees:
                include(owner)
    for obj in bpy.data.objects:
        include(obj)
        include(obj.data)
        for slot in obj.material_slots:
            include(slot.material)
    include(bpy.context.scene)
    include(bpy.context.scene.world)
    return records


def persistent_core_projection(before):
    """Source-predicted read lifecycle delta, never an assignment to Blender."""
    result, changes = copy.deepcopy(before), []
    scopes = [("graphs/" + key, graph["properties"]) for key, graph in result["graphs"].items()]
    scopes.extend(("owner_properties/" + key, values) for key, values in result["owner_properties"].items())
    for key, values in scopes:
        assert type(values["is_runtime_data"]) is bool
        if values["is_runtime_data"]:
            values["is_runtime_data"] = False
            changes.append(key + "/is_runtime_data")
    for key, value in result["runtime_flags"].items():
        assert type(value) is bool
        if value:
            result["runtime_flags"][key] = False
            changes.append("runtime_flags/" + key)
    return result, changes


def condition_loaded_fixture(runtime, refs, bundle):
    """Own the setup transition before the measured removal baseline exists."""
    before, before_ui = snapshot(refs)
    inventory = runtime_inventory(refs)
    runtime_ids = {key: row for key, row in inventory.items() if row["is_runtime_data"]}
    assert runtime_ids, "This fixture must retain its demonstrated fresh embedded-ID origin"
    assert all(row["embedded"] and row["runtime_status_readonly"] and not row["evaluated"]
               and not row["linked"] and not row["override"] for row in runtime_ids.values())
    expected, changes = persistent_core_projection(before)
    origin = {"kind": "PERSISTENT_LOADED_OWNED_FIXTURE", "stage": "before_owned_seed_serialization",
              "before_inventory": inventory, "source_predicted_runtime_property_changes": changes,
              "before_shader_state_sha256": digest(before), "direct_runtime_flag_assignment": False,
              "property_excluded_from_comparison": False, "normalizes_user_data": False}
    JOURNAL["fixture_origin"] = origin
    (bundle / "removal-journal.json").write_text(json.dumps(JOURNAL, indent=2) + "\n")
    origin["seed_serialization"] = serialize_owned_fixture(runtime, bundle / "shader-removal-seed.blend")
    assert_same(before, snapshot(refs)[0], "Owned seed serialization changed shader state before reload")
    origin["stage"] = "owned_seed_serialized_before_reload"
    (bundle / "removal-journal.json").write_text(json.dumps(JOURNAL, indent=2) + "\n")
    # No RNA wrapper escapes the helpers above. Reacquire everything after load.
    assert bpy.ops.wm.open_mainfile(filepath=str(bundle / "shader-removal-seed.blend"), load_ui=False) == {"FINISHED"}
    # Native file loading clears the interactive window context. Return to the
    # real event loop once; do not inspect or poll undo in the loading callback.
    yield "OWNED_FILE_LOADED"
    assert bpy.context.window is not None and bpy.context.screen is not None
    loaded, loaded_ui = snapshot(refs)
    assert_same(expected, loaded, "Loaded fixture changed more than source-predicted runtime status")
    loaded_inventory = runtime_inventory(refs)
    assert set(loaded_inventory) == set(inventory)
    assert all(row["is_runtime_data"] is False and not row["evaluated"]
               and not row["linked"] and not row["override"] for row in loaded_inventory.values())
    origin.update(stage="loaded_origin_verified_before_measurement", after_inventory=loaded_inventory,
                  after_shader_state_sha256=digest(loaded), interface_ui_preserved_by_conditioning=loaded_ui == before_ui,
                  participating_id_count=len(loaded_inventory), all_participating_ids_literal_runtime_false=True,
                  post_load_snapshot_on_separate_timer_turn=True)
    (bundle / "removal-journal.json").write_text(json.dumps(JOURNAL, indent=2) + "\n")
    print("SHADER_REMOVE_PROBE_ORIGIN " + json.dumps({"kind": origin["kind"], "stage": origin["stage"],
          "runtime_property_changes": changes, "participating_ids": len(loaded_inventory)}), flush=True)


def journal(bundle, row, stage):
    row["last_completed_stage"] = stage
    (bundle / "removal-journal.json").write_text(json.dumps(JOURNAL, indent=2, allow_nan=False) + "\n")
    print("SHADER_REMOVE_PROBE_PROGRESS " + json.dumps({"case": row["case"], "stage": stage}), flush=True)


def writer(runtime, bundle, *, loaded_fixture=False):
    leaf_name, refs, cases = setup()
    if loaded_fixture:
        yield from condition_loaded_fixture(runtime, refs, bundle)
    assert bpy.context.mode == "OBJECT"
    undo_settings = bpy.context.preferences.edit
    assert undo_settings.use_global_undo and undo_settings.undo_steps >= 32
    JOURNAL["native_undo_settings"] = {"steps": undo_settings.undo_steps, "memory_limit_mb": undo_settings.undo_memory_limit}
    for index, case in enumerate(cases):
        if loaded_fixture:
            assert all(row["is_runtime_data"] is False for row in runtime_inventory(refs).values())
        leaf = bpy.data.node_groups[leaf_name]
        identifier, direction = case["identifier"], case["direction"]
        item = fixture.interface(leaf, identifier)
        assert item.bl_rna.properties["identifier"].is_readonly
        # Owned setup puts the removed item before surviving peers, exercising
        # native index shifts without assigning meaning to positional names.
        first = next(peer for peer in leaf.interface.items_tree if peer.in_out == direction)
        if first != item:
            leaf.interface.move(item, list(leaf.interface.items_tree).index(first))
        assert next(peer.identifier for peer in leaf.interface.items_tree if peer.in_out == direction) == identifier
        survivor = next(peer for peer in leaf.interface.items_tree if peer.identifier != identifier and peer.in_out == direction)
        active = item if index % 2 else survivor
        leaf.interface.active_index = list(leaf.interface.items_tree).index(active)
        if hasattr(active, "select"):
            active.select = False  # Active and selected are independent on 5.x.
        removed_values = consumers(refs, leaf_name, identifier, direction)
        before, before_ui = snapshot(refs)
        native_ids = identities(refs)
        expected = projected(before, leaf_name, identifier, direction)
        row = {"case": index, **case, "removed_socket_was_active": active == item,
               "affected_sockets": removed_values, "before_sha256": digest(before),
               "expected_after_sha256": digest(expected), "explicit_recreation_attempted": False}
        JOURNAL["cases"].append(row)
        assert bpy.ops.ed.undo_push.poll()
        assert bpy.ops.ed.undo_push(message="Shader removal probe BEFORE " + str(index)) == {"FINISHED"}
        assert_same((before, before_ui), snapshot(refs), "BEFORE push changed fixture state")
        assert identities(refs) == native_ids
        journal(bundle, row, "native_before_snapshot")
        leaf.interface.remove(item)
        # Never dereference the removed item or any pre-undo socket wrapper.
        item = None
        after, after_ui = snapshot(refs)
        assert_same(expected, after, "Removal changed surviving shader state")
        assert identities(refs) == native_ids
        assert all(entry["identifier"] != identifier for entry in after["graphs"]["GROUP::" + leaf_name]["interface"])
        row.update(native_removal_verified=True, native_tree_node_owner_identities_preserved=True,
                   surviving_shader_shape_configuration_defaults_and_links_preserved=True,
                   native_ui_before=before_ui["GROUP::" + leaf_name], native_ui_after=after_ui["GROUP::" + leaf_name],
                   native_interface_active_identifier_preserved=before_ui["GROUP::" + leaf_name]["active_identifier"] == after_ui["GROUP::" + leaf_name]["active_identifier"],
                   native_surviving_interface_selection_preserved={key: value for key, value in before_ui["GROUP::" + leaf_name]["selected"].items() if key != identifier} == after_ui["GROUP::" + leaf_name]["selected"])
        journal(bundle, row, "native_remove_verified")
        assert bpy.ops.ed.undo_push.poll()
        assert bpy.ops.ed.undo_push(message="Shader removal probe AFTER " + str(index)) == {"FINISHED"}
        assert_same((after, after_ui), snapshot(refs), "AFTER push changed fixture state")
        journal(bundle, row, "native_after_snapshot")
        assert bpy.ops.ed.undo.poll()
        assert bpy.ops.ed.undo() == {"FINISHED"}
        restored, restored_ui = snapshot(refs)  # Resolve all IDs/wrappers anew.
        assert_same(before, restored, "Native undo did not restore original identifiers and shader state")
        fixture.interface(bpy.data.node_groups[leaf_name], identifier)
        row.update(native_undo_original_identifier_and_full_shader_state_restored=True,
                   native_undo_ui_restored=restored_ui == before_ui)
        journal(bundle, row, "native_undo_verified")
        assert bpy.ops.ed.redo.poll()
        assert bpy.ops.ed.redo() == {"FINISHED"}
        redone, redone_ui = snapshot(refs)
        assert_same(after, redone, "Native redo did not restore exact removed state")
        row.update(native_redo_exact_shader_state_restored=True, native_redo_ui_restored=redone_ui == after_ui)
        journal(bundle, row, "native_redo_verified")
    final, final_ui = snapshot(refs)
    expected = {"references": refs, "core": final, "ui": final_ui, "cases": cases, "leaf": leaf_name,
                "loaded_fixture": loaded_fixture}
    fixture_save = serialize_owned_fixture(runtime, bundle / "shader-removal.blend")
    assert_same(final, snapshot(refs)[0], "Owned serialization changed shader state")
    (bundle / "expected.json").write_text(json.dumps(expected, allow_nan=False) + "\n")
    return {"phase": "writer", "blender_version": bpy.app.version_string, "native_only_probe": True,
            "typed_removal_supported": False, "case_count": len(cases), "directions": ["INPUT", "OUTPUT"],
            "socket_types": list(KINDS), "all_surviving_shader_state_verified": True,
            "all_native_undo_identifier_restorations_verified": all(row.get("native_undo_original_identifier_and_full_shader_state_restored") is True for row in JOURNAL["cases"]),
            "all_native_redo_removed_states_verified": all(row.get("native_redo_exact_shader_state_restored") is True for row in JOURNAL["cases"]),
            "direct_material_and_nested_instances_verified": True, "explicit_recreation_attempted": False,
            "journal_sha256": hashlib.sha256((bundle / "removal-journal.json").read_bytes()).hexdigest(),
            "shader_state_sha256": digest(final), "native_ui_changes_recorded_separately": True, **fixture_save,
            "fixture_origin": "PERSISTENT_LOADED_OWNED_FIXTURE" if loaded_fixture else "FRESH_CREATED_OWNED_FIXTURE",
            "post_load_snapshot_on_separate_timer_turn": loaded_fixture,
            "fresh_created_shader_recovery_qualified": False,
            "project_delivery_verified": False, "visual_review_performed": False}


def reader(_runtime, bundle, *, loaded_fixture=False):
    expected = json.loads((bundle / "expected.json").read_text())
    assert expected["loaded_fixture"] is loaded_fixture
    assert bpy.ops.wm.open_mainfile(filepath=str(bundle / "shader-removal.blend"), load_ui=False) == {"FINISHED"}
    yield "OWNED_FILE_LOADED"
    assert bpy.context.window is not None and bpy.context.screen is not None
    core, ui = snapshot(expected["references"])
    assert_same(expected["core"], core, "Fresh process shader state differs")
    if loaded_fixture:
        assert all(row["is_runtime_data"] is False for row in runtime_inventory(expected["references"]).values())
    leaf = bpy.data.node_groups[expected["leaf"]]
    remaining = {item.identifier for item in leaf.interface.items_tree}
    assert not remaining.intersection(case["identifier"] for case in expected["cases"])
    return {"phase": "reader", "blender_version": bpy.app.version_string, "native_only_probe": True,
            "typed_removal_supported": False, "fresh_process_removed_identifiers_and_all_surviving_shader_state_verified": True,
            "shader_state_sha256": digest(core), "native_ui_equal_to_saved_writer": ui == expected["ui"],
            "fixture_origin": "PERSISTENT_LOADED_OWNED_FIXTURE" if loaded_fixture else "FRESH_CREATED_OWNED_FIXTURE",
            "post_load_snapshot_on_separate_timer_turn": True,
            "fresh_created_shader_recovery_qualified": False,
            "project_saved_by_reader": False, "bridge_safe_project_save_verified": False,
            "project_delivery_verified": False, "visual_review_performed": False}


def advance_phase(phase, finish, *, resumed=False):
    """Resume one owned-load handoff; never retry context reads or operators."""
    try:
        stage = next(phase)
        assert stage == "OWNED_FILE_LOADED" and not resumed, "Unexpected or repeated post-load handoff"
        bpy.app.timers.register(lambda: advance_phase(phase, finish, resumed=True), first_interval=.1)
        return None
    except StopIteration as completed:
        try:
            finish(completed.value)
        except Exception:
            traceback.print_exc()
    except Exception:
        traceback.print_exc()
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=.5)
    return None


def run():
    try:
        assert threading.current_thread() is threading.main_thread()
        parser = argparse.ArgumentParser()
        parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
        parser.add_argument("--bridge-bundle", type=Path, required=True)
        parser.add_argument("--bridge-loaded-fixture", action="store_true")
        args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
        assert os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"), "Use the isolated native runner"
        blender_codex_bridge.register()
        runtime = get_runtime()
        grants = {permission.value: permission in (Permission.INSPECT_SCENE, Permission.EDIT_MATERIALS,
                  Permission.SAVE_PROJECT, Permission.ACCESS_EXTERNAL_FILES) for permission in Permission}
        runtime.permissions = runtime.executor.permissions = PermissionManager(lambda: grants)
        phase = (writer if args.bridge_phase == "writer" else reader)(runtime, args.bridge_bundle.resolve(strict=True),
                    loaded_fixture=args.bridge_loaded_fixture)

        def finish(result):
            result.update(process_instance=os.environ["BRIDGE_TEST_PROCESS_TOKEN"], process_id=os.getpid())
            result["blender_build_hash"] = bpy.app.build_hash.decode("ascii")
            marker = "BLENDER_SHADER_REMOVE_LOADED_PROBE_" if args.bridge_loaded_fixture else "BLENDER_SHADER_REMOVE_PROBE_"
            print(marker + args.bridge_phase.upper() + "_OK " + json.dumps(result), flush=True)

        return advance_phase(phase, finish)
    except Exception:
        traceback.print_exc()
        bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=.5)
    return None


bpy.app.timers.register(run, first_interval=1.)
