"""Exercise real native checkpoints under exclusive bridge mutation ownership."""

from __future__ import annotations

import gc
import json
import os
import sys
import traceback
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))
import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tool_registry import check_final_mutation  # noqa: E402

OWNER = "fixture.exclusive"
FOREIGN = "fixture.foreign"


def run():
    try:
        assert not bpy.app.background and os.environ.get("BRIDGE_TEST_PROCESS_TOKEN")
        bpy.context.preferences.use_preferences_save = False
        blender_codex_bridge.register()
        runtime = get_runtime()
        assert runtime.registry.get("asset.import").exclusive_mutation
        initial = tuple(bpy.data.objects["Cube"].location)
        grants = {permission.value: True for permission in Permission}
        counters = {"foreign_provider": 0, "foreign_factory": 0,
                    "foreign_handler": 0, "foreign_checkpoint": 0, "readonly": 0}
        seen, denials = set(), []
        active = {"context": None, "run": 0, "probing": False, "foreign": False}

        def read(context, _params):
            counters["readonly"] += 1
            return context.state.snapshot()

        runtime.registry.register("fixture.read", read, toolset="core",
            permissions=(Permission.INSPECT_SCENE,))

        def probe(stage, context):
            key = (active["run"], stage)
            if active["probing"] or key in seen:
                return
            seen.add(key)
            active["probing"] = True
            try:
                before = runtime.state.snapshot()
                runtime.dispatch("fixture.read", {})
                after = runtime.state.snapshot()
                for field in ("current_method", "current_task", "is_executing"):
                    assert after[field] == before[field], (stage, field, before, after)
                operations = (
                    lambda: runtime.dispatch(FOREIGN, {}),
                    lambda: runtime.registry.dispatch(FOREIGN, {}, context),
                    lambda: runtime.registry.invoke(runtime.registry.get(FOREIGN), {}, context),
                )
                for route, operation in enumerate(operations):
                    active["foreign"] = True
                    try:
                        operation()
                    except BridgeError as error:
                        assert error.code == "OPERATION_FAILED", error.to_dict()
                        assert error.context.get("reason") == "REENTRANT_MUTATION_BLOCKED", error.to_dict()
                        assert error.context.get("execution_started") is False, error.to_dict()
                        denials.append({"run": active["run"], "stage": stage, "route": route})
                        error.__traceback__ = error.__context__ = error.__cause__ = None
                    else:
                        raise AssertionError("Nested mutator entered during exclusive operation")
                    finally:
                        active["foreign"] = False
                assert tuple(bpy.data.objects["Cube"].location)[1:] == initial[1:]
                assert not any(counters[key] for key in (
                    "foreign_provider", "foreign_factory", "foreign_handler", "foreign_checkpoint"))
            finally:
                active["probing"] = False

        def provider():
            if active["foreign"]:
                counters["foreign_provider"] += 1
            if active["context"] is not None:
                probe("provider", active["context"])
            return grants

        runtime.permissions = runtime.executor.permissions = PermissionManager(provider)

        class Guard:
            def __init__(self, context):
                self.context = context

            def __call__(self):
                self.context.require(Permission.TRANSFORM_OBJECTS)
                check_final_mutation(self.context, OWNER)

            def check_after_read(self):
                check_final_mutation(self.context, OWNER)

        def owner_factory(context, _params):
            active["context"] = context
            probe("factory", context)
            return Guard(context)

        class ForeignGuard:
            def __init__(self, context):
                self.context = context

            def __call__(self):
                self.context.require(Permission.TRANSFORM_OBJECTS)
                check_final_mutation(self.context, FOREIGN)

            def check_after_read(self):
                check_final_mutation(self.context, FOREIGN)

        def foreign_factory(context, _params):
            counters["foreign_factory"] += 1
            return ForeignGuard(context)

        def foreign(context, _params):
            counters["foreign_handler"] += 1
            context.require(Permission.TRANSFORM_OBJECTS)
            check_final_mutation(context, FOREIGN)
            bpy.data.objects["Cube"].location.y += .5
            return {"affected_objects": ["Cube"], "changed": True}

        runtime.registry.register(FOREIGN, foreign, toolset="core", modifies=True,
            permissions=(Permission.TRANSFORM_OBJECTS,), checkpoint_admission_factory=foreign_factory)

        def owner(context, params):
            probe("handler", context)

            class Finalizer:
                def __del__(self):
                    probe("gc_finalizer", context)

            garbage = Finalizer()
            garbage.cycle = garbage
            garbage = None
            gc.collect()
            context.require(Permission.TRANSFORM_OBJECTS)
            check_final_mutation(context, OWNER)
            bpy.data.objects["Cube"].location.x += .25
            if params.get("fail"):
                raise BridgeError("OPERATION_FAILED", "Owned fixture fault after one native write",
                    {"possible_mutation": True, "verification_required": True})
            return {"affected_objects": ["Cube"], "changed": True}

        runtime.registry.register(OWNER, owner, toolset="core", modifies=True,
            permissions=(Permission.TRANSFORM_OBJECTS,), batchable=False,
            exclusive_mutation=True, checkpoint_admission_factory=owner_factory)
        original_before = runtime.checkpoints.before_modification
        original_after = runtime.checkpoints.after_modification

        def before(tool, **kwargs):
            if tool == FOREIGN:
                counters["foreign_checkpoint"] += 1
            if tool == OWNER:
                probe("checkpoint_before", active["context"])
            return original_before(tool, **kwargs)

        def after(tool, **kwargs):
            if tool.startswith(OWNER):
                probe("checkpoint_after", active["context"])
            return original_after(tool, **kwargs)

        runtime.checkpoints.before_modification = before
        runtime.checkpoints.after_modification = after
        for number, fail in enumerate((False, True), 1):
            active["run"] = number
            try:
                runtime.dispatch(OWNER, {"fail": fail})
            except BridgeError as error:
                assert fail and error.code == "OPERATION_FAILED", error.to_dict()
                error.__traceback__ = error.__context__ = error.__cause__ = None
            else:
                assert not fail
            finally:
                active["context"] = None
            assert tuple(bpy.data.objects["Cube"].location) == (initial[0]+.25, *initial[1:])
            recovered = runtime.dispatch("checkpoint.undo_last", {
                "confirm_global_undo": True, "restore_snapshot": True})
            assert recovered["snapshot_marker_verified"], recovered
            assert tuple(bpy.data.objects["Cube"].location) == initial
        required = {"factory", "provider", "checkpoint_before", "handler", "gc_finalizer", "checkpoint_after"}
        for number in (1, 2):
            assert {stage for run_number, stage in seen if run_number == number} == required
        assert len(denials) == 36 and counters["readonly"] == 12
        # Once the exclusive scope has unwound, the same actual native writer
        # is admitted normally. This also proves recovery was not a lease bypass.
        runtime.dispatch(FOREIGN, {})
        assert counters["foreign_handler"] == 1 and counters["foreign_checkpoint"] == 1
        assert tuple(bpy.data.objects["Cube"].location) == (initial[0], initial[1]+.5, initial[2])
        runtime.dispatch("checkpoint.undo_last", {"confirm_global_undo": True, "restore_snapshot": True})
        assert tuple(bpy.data.objects["Cube"].location) == initial
        print("BLENDER_EXCLUSIVE_MUTATION_OK " + json.dumps({
            "blender_version": bpy.app.version_string, "denied_nested_mutations": len(denials),
            "stages": sorted(required), "success_and_failure_scope_release_verified": True,
            "readonly_display_preserved": True, "native_changes_and_actual_recovery_verified": True,
            "next_root_mutation_admitted": True, "project_saved": False,
            "whole_project_snapshot_verified": False, "full_recovery_acceptance": False,
            "release_acceptance": False,
        }), flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(run, first_interval=1.)
