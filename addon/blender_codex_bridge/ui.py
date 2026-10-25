"""Codex Bridge 3D View N-panel and explicit user-control operators."""

from typing import TypeGuard

try:
    import bpy  # type: ignore
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore

from .constants import ADDON_VERSION_STRING
from .errors import BridgeError
from .preferences import get_preferences
from .protocol import PROTOCOL_VERSION
from .runtime import get_runtime
from .serialization import dumps


def _target_channels_label(receipt: object) -> str:
    """Format cached public facts without inspecting or refreshing scene state."""
    def plain_fields(value: object) -> TypeGuard[dict[str, object]]:
        return (type(value) is dict and len(value) <= 64
                and all(type(key) is str and len(key) <= 128 for key in value))

    unavailable = "Observation unavailable"
    if not plain_fields(receipt):
        return unavailable
    history = receipt.get("history_state")
    if history is not None and (type(history) is not str or len(history) > 64):
        return unavailable
    if history == "historical_after_generation_change":
        return "Stale; verify again"
    if history not in {None, "current_runtime_generation"}:
        return unavailable
    observation = receipt.get("target_observation")
    if observation is not None:
        if not plain_fields(observation):
            return unavailable
        validity = observation.get("validity")
        if type(validity) is not str or len(validity) > 64:
            return unavailable
        if validity == "stale":
            return "Stale; verify again"
        scope = observation.get("scope")
        if validity != "recorded" or type(scope) is not str or scope != "authored_core_transform_channels":
            return unavailable
        status = observation.get("status")
        if type(status) is not str or len(status) > 64:
            return unavailable
        if (observation.get("current_scene_verified") is not False
                or observation.get("user_goal_verified") is not False
                or observation.get("comparison_complete") is not (status in {"channels_match", "channels_differ"})):
            return unavailable
        return {"channels_match": "Matched at verification",
                "channels_differ": "Differences at verification",
                "target_missing": "Target missing at verification",
                "target_replaced": "Target replaced at verification"}.get(status, unavailable)
    expectation = receipt.get("target_expectation")
    if expectation is None:
        return "No retained expectation"
    if not plain_fields(expectation):
        return unavailable
    availability = expectation.get("availability")
    if type(availability) is not str or len(availability) > 64:
        return unavailable
    if availability == "available":
        return "Not verified"
    if availability == "unavailable":
        return "Expectation unavailable"
    return unavailable


def _draw_job(jobs, job):
    """Render cached image or Scene evidence without evaluating native data."""
    if job.get("kind") == "project.native_save":
        _draw_native_save_job(jobs, job)
        return
    label = job.get("new_image", job.get("label", job["kind"]))
    jobs.label(text=f"{job['state']}: {label[:36]}")
    workload = job.get("workload", {})
    if workload:
        size = workload["image_size"]
        jobs.label(text=f"{size[0]} x {size[1]} pixels")
        if "candidate_pixel_tests" in workload:
            jobs.label(text=f"{workload['candidate_pixel_tests']} brush candidates")
        if "format" in workload:
            jobs.label(text=f"Export/reimport: {workload['format']}")
        if "mode" in workload:
            jobs.label(text={"CURRENT_PIXELS_SNAPSHOT": "Snapshot current pixels",
                             "LOADED_BUFFER": "Restore loaded pixels",
                             "PACKED_RECONSTRUCTION": "Restore packed pixels"}.get(workload["mode"], "Image recovery"))
        if "private_pixel_and_payload_peak_estimate_bytes" in workload:
            jobs.label(text=f"Private pixels/payload estimate: {workload['private_pixel_and_payload_peak_estimate_bytes'] / 1048576:.1f} MiB")
        elif "private_pixel_buffers_peak_estimate_bytes" in workload:
            jobs.label(text=f"Private pixel estimate: {workload['private_pixel_buffers_peak_estimate_bytes'] / 1048576:.1f} MiB")
        jobs.label(text="Excludes native/GPU/undo buffers")
    progress = job["progress"]
    jobs.label(text=f"{progress['phase']}: {progress['completed']}/{progress['total']}")
    if not job["terminal"]:
        jobs.operator("blender_codex_bridge.cancel_job", icon="CANCEL")
    if job["error"]:
        jobs.label(text=job["error"]["code"], icon="ERROR")
        if job["error"]["context"].get("possible_mutation"):
            jobs.label(text="Possible effects; inspect/recover", icon="ERROR")
    effects = job.get("external_effects", {})
    if effects.get("file_published") or effects.get("publication_outcome_unknown"):
        jobs.label(text="File may persist after cancel/undo; inspect", icon="INFO")
    if effects.get("retained_staging_path"):
        jobs.label(text="Retained staging file; inspect job details", icon="ERROR")
    recovery = job.get("recovery_evidence", {})
    recovery_unknown = "recovery_evidence" in job.get("evidence_observation_unknown", ())
    if recovery_unknown:
        jobs.label(text="Recovery state could not be observed; inspect", icon="ERROR")
    elif recovery.get("snapshot_retained"):
        jobs.label(text=("Snapshot retained at completion; verify before saving" if job["terminal"]
                         else "Packed snapshot retained; save for durability"), icon="INFO")
    if recovery.get("possible_mutation"):
        jobs.label(text="Image may have changed; inspect recovery", icon="ERROR")


def _draw_native_save_effects(layout, effects):
    """Read bounded cached file facts; never inspect live source or callback state."""
    native = effects.get("native_save", {})
    if native.get("native_save_invoked") or native.get("possible_native_effects"):
        layout.label(text="Native save effects may persist after cancel/undo", icon="INFO")
    if native.get("native_effect_inventory_complete") is False:
        layout.label(text="Callback/catalog file effects are not fully enumerated", icon="INFO")
    before, after = native.get("source_filepath_before"), native.get("source_filepath_after")
    if before != after and after:
        layout.label(text="Active project filepath changed; inspect job details", icon="INFO")
    if effects.get("file_published") or effects.get("publication_outcome_unknown"):
        layout.label(text="Project file may persist; inspect saved bytes", icon="INFO")
    if effects.get("retained_staging_path"):
        layout.label(text="Owned staging retained; inspect job details", icon="ERROR")
    if native.get("retained_reader_path"):
        layout.label(text="Owned reader files retained; inspect job details", icon="ERROR")
    if native.get("worker_reaped") is False:
        layout.label(text="Reader process exit not verified", icon="ERROR")
    if native.get("cleanup_outcome_unknown") is True:
        layout.label(text="Reader cleanup outcome unknown; reinspection required", icon="ERROR")
    if effects.get("artifacts_truncated") or effects.get("artifacts_incomplete") or native.get("evidence_incomplete"):
        layout.label(text="File evidence incomplete; reinspection required", icon="ERROR")


def _draw_native_save_job(layout, job):
    layout.label(text=f"{job['state']}: Native project save")
    layout.label(text=f"Phase: {job.get('progress', {}).get('phase', 'unknown')}")
    layout.label(text="Native save cannot be preempted; cancellation stops later work")
    if not job["terminal"]:
        layout.operator("blender_codex_bridge.cancel_job", icon="CANCEL")
    if job.get("error"):
        layout.label(text=job["error"]["code"], icon="ERROR")
    _draw_native_save_effects(layout, job.get("external_effects", {}))


if bpy is not None:

    class BCB_OT_arm_native_save(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.arm_native_save"
        bl_label = "Arm Native Save Effects for this Session"
        bl_description = "Locally permit normal native save callbacks/catalogs/history effects for a bounded session; no automatic renewal"

        def invoke(self, context, event):
            del event
            return context.window_manager.invoke_props_dialog(self, width=560)

        def draw(self, context):
            preferences = get_preferences(context)
            self.layout.label(text="Normal native Save can synchronize/flush project state.")
            self.layout.label(text="Callbacks, asset catalogs and history may write outside the project folder.")
            self.layout.label(text="Native overwrite is not atomic; cancel/undo cannot remove saved files.")
            self.layout.label(text="Applies to this Bridge session and its connected clients.")
            if preferences:
                self.layout.prop(preferences, "native_save_duration_seconds")

        def execute(self, context):
            preferences = get_preferences(context)
            if preferences is None:
                self.report({"ERROR"}, "Add-on preferences are unavailable")
                return {"CANCELLED"}
            try:
                get_runtime().arm_native_save_effects(preferences.native_save_duration_seconds)
            except (BridgeError, ValueError) as error:
                self.report({"ERROR"}, error.message if isinstance(error, BridgeError) else str(error))
                return {"CANCELLED"}
            return {"FINISHED"}


    class BCB_OT_revoke_native_save(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.revoke_native_save"
        bl_label = "Revoke Native Save Effects"

        def execute(self, context):
            del context
            get_runtime().revoke_native_save_effects()
            return {"FINISHED"}

    class BCB_OT_start_bridge(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.start"
        bl_label = "Start Bridge"
        bl_description = "Start the localhost-only Codex listener"

        def execute(self, context):
            preferences = get_preferences(context)
            if preferences is None:
                self.report({"ERROR"}, "Add-on preferences are unavailable")
                return {"CANCELLED"}
            try:
                host, port = get_runtime().start_server(
                    preferences.host,
                    preferences.port,
                    request_timeout=preferences.request_timeout,
                )
            except BridgeError as error:
                self.report({"ERROR"}, error.message)
                return {"CANCELLED"}
            self.report({"INFO"}, f"Codex Bridge listening on {host}:{port}")
            return {"FINISHED"}


    class BCB_OT_stop_bridge(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.stop"
        bl_label = "Stop Bridge"
        bl_description = "Stop the listener and cancel all requests that have not begun"

        def execute(self, context):
            del context
            get_runtime().stop_server()
            return {"FINISHED"}


    class BCB_OT_toggle_pause(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.toggle_pause"
        bl_label = "Pause / Resume Agent"
        bl_description = "Block or permit agent modification tools; inspection remains available"

        def execute(self, context):
            del context
            state = get_runtime().state
            snapshot = state.snapshot()
            state.set_paused(not snapshot["paused"])
            return {"FINISHED"}


    class BCB_OT_emergency_stop(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.emergency_stop"
        bl_label = "Emergency Stop"
        bl_description = "Stop the listener and cancel all queued requests immediately"

        def execute(self, context):
            del context
            get_runtime().emergency_stop()
            self.report({"WARNING"}, "Codex agent emergency-stopped")
            return {"FINISHED"}


    class BCB_OT_cancel_job(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.cancel_job"
        bl_label = "Cancel Job"
        bl_description = "Cancel job work at its next safe point; native calls cannot be preempted"

        def execute(self, context):
            del context
            runtime = get_runtime()
            if runtime.jobs.active is not None:
                runtime.dispatch("jobs.cancel", {"job_id": runtime.jobs.active.job_id})
            return {"FINISHED"}


    class BCB_OT_checkpoint_create(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.checkpoint_create"
        bl_label = "Create Checkpoint"

        def execute(self, context):
            del context
            try:
                get_runtime().dispatch("checkpoint.create", {"description": "User-created checkpoint"})
            except BridgeError as error:
                self.report({"ERROR"}, error.message)
                return {"CANCELLED"}
            return {"FINISHED"}


    class BCB_OT_checkpoint_undo(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.checkpoint_undo"
        bl_label = "Restore Agent Snapshot (Global)"
        bl_description = (
            "Blender cannot prove undo ownership; this may undo interleaved user work"
        )

        def invoke(self, context, event):
            return context.window_manager.invoke_confirm(self, event)

        def execute(self, context):
            del context
            try:
                get_runtime().dispatch_recovery(
                    "checkpoint.undo_last",
                    {"confirm_global_undo": True, "restore_snapshot": True},
                )
            except BridgeError as error:
                self.report({"ERROR"}, error.message)
                return {"CANCELLED"}
            return {"FINISHED"}


    class BCB_OT_checkpoint_restore(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.checkpoint_restore"
        bl_label = "Restore Checkpoint (Global)"
        bl_description = (
            "Repeated global undo may affect interleaved user work; confirmation is required"
        )

        def invoke(self, context, event):
            return context.window_manager.invoke_confirm(self, event)

        def execute(self, context):
            del context
            try:
                result = get_runtime().dispatch_recovery(
                    "checkpoint.restore_last",
                    {"confirm_global_undo": True},
                )
            except BridgeError as error:
                self.report({"ERROR"}, error.message)
                return {"CANCELLED"}
            self.report({"INFO"}, f"Reached checkpoint marker using {result['undo_steps']} native undo step(s); reinspect")
            return {"FINISHED"}


    class BCB_OT_set_toolset(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.set_toolset"
        bl_label = "Set Toolset"
        bl_description = "Enable or disable one Blender-side capability group"

        toolset: bpy.props.StringProperty(name="Toolset")
        enable: bpy.props.BoolProperty(name="Enable", default=True)

        def invoke(self, context, event):
            if self.enable and self.toolset == "python":
                return context.window_manager.invoke_confirm(self, event)
            return self.execute(context)

        def execute(self, context):
            del context
            registry = get_runtime().registry
            try:
                if self.enable:
                    registry.enable_toolset(self.toolset)
                else:
                    registry.disable_toolset(self.toolset)
            except BridgeError as error:
                self.report({"ERROR"}, error.message)
                return {"CANCELLED"}
            action = "Enabled" if self.enable else "Disabled"
            self.report({"INFO"}, f"{action} {self.toolset} toolset")
            return {"FINISHED"}


    class BCB_OT_enable_structured_toolsets(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.enable_structured_toolsets"
        bl_label = "Enable Structured Tools"
        bl_description = "Enable every registered structured toolset except dangerous Python"

        def execute(self, context):
            del context
            registry = get_runtime().registry
            changed = 0
            for item in registry.describe()["toolsets"]:
                name = item["name"]
                if name in {"core", "python"} or item["enabled"]:
                    continue
                registry.enable_toolset(name)
                changed += 1
            self.report({"INFO"}, f"Enabled {changed} structured toolset(s)")
            return {"FINISHED"}


    class BCB_OT_disable_optional_toolsets(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.disable_optional_toolsets"
        bl_label = "Disable Optional Tools"
        bl_description = "Return to core inspection and control tools only"

        def execute(self, context):
            del context
            registry = get_runtime().registry
            for name in tuple(registry.enabled_toolsets):
                if name != "core":
                    registry.disable_toolset(name)
            return {"FINISHED"}


    class BCB_OT_clear_history(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.clear_history"
        bl_label = "Clear History"
        bl_description = "Clear the local bridge activity display; Blender data is not changed"

        def execute(self, context):
            del context
            count = get_runtime().state.clear_history()
            self.report({"INFO"}, f"Cleared {count} history record(s)")
            return {"FINISHED"}


    class BCB_OT_copy_diagnostics(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.copy_diagnostics"
        bl_label = "Copy Diagnostics"
        bl_description = "Copy bounded local bridge status and recent history as JSON"

        def execute(self, context):
            runtime = get_runtime()
            payload = {
                "addon_version": ADDON_VERSION_STRING,
                "protocol_version": PROTOCOL_VERSION,
                "blender_version": bpy.app.version_string,
                "filepath": bpy.data.filepath,
                "runtime": runtime.state.snapshot(),
                "pending_requests": runtime.command_queue.pending_count,
                "permissions": runtime.permissions.snapshot(),
                "registry": runtime.registry.describe(),
                "history": runtime.state.history(20),
            }
            context.window_manager.clipboard = dumps(payload)
            self.report({"INFO"}, "Bridge diagnostics copied to clipboard")
            return {"FINISHED"}


    class BCB_PT_bridge_panel(bpy.types.Panel):
        bl_label = "Blender Codex Bridge"
        bl_idname = "BCB_PT_bridge_panel"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Codex Bridge"

        def draw(self, context):
            layout = self.layout
            runtime = get_runtime()
            state = runtime.state.snapshot()
            preferences = get_preferences(context)

            connection = layout.box()
            connection.label(text="Connection", icon="NETWORK_DRIVE")
            status_row = connection.row()
            status_row.alert = state["is_executing"] or state["emergency_stopped"]
            if state["connected_clients"]:
                label, icon = "Connected", "LINKED"
            elif state["server_running"]:
                label, icon = "Listening", "RADIOBUT_ON"
            else:
                label, icon = "Disconnected", "UNLINKED"
            status_row.label(text=f"Status: {label}", icon=icon)
            if state["is_executing"]:
                status_row.label(text=f"Running: {state['current_method']}", icon="REC")
            connection.label(
                text=(
                    f"Protocol {PROTOCOL_VERSION}  •  Add-on {ADDON_VERSION_STRING}  •  "
                    f"Clients {state['connected_clients']}"
                )
            )
            connection.label(
                text=f"Queued requests: {runtime.command_queue.pending_count}",
                icon="SORTTIME",
            )
            if preferences:
                connection.prop(preferences, "host")
                connection.prop(preferences, "port")
                connection.prop(preferences, "request_timeout")

            controls = layout.box()
            controls.label(text="Agent Control", icon="TOOL_SETTINGS")
            row = controls.row(align=True)
            row.operator("blender_codex_bridge.start", icon="PLAY")
            row.operator("blender_codex_bridge.stop", icon="PAUSE")
            pause_label = "Resume Agent" if state["paused"] else "Pause Agent"
            controls.operator("blender_codex_bridge.toggle_pause", text=pause_label, icon="PAUSE")
            emergency = controls.row()
            emergency.alert = True
            emergency.operator("blender_codex_bridge.emergency_stop", icon="CANCEL")
            if state["emergency_stopped"]:
                controls.label(text="Emergency stopped. Start Bridge to reset.", icon="ERROR")
            if state["paused"] and not state["emergency_stopped"]:
                controls.label(text="Mutations paused; inspection remains available.", icon="INFO")

            task_box = layout.box()
            task_box.label(text="Current Task", icon="PRESET")
            task_box.label(text=state["current_task"] or "No active task")
            if state["current_method"]:
                task_box.label(text=f"Tool: {state['current_method']}")
            if state["last_error"]:
                error_row = task_box.row()
                error_row.alert = True
                error_row.label(text=f"Last error: {state['last_error'][:96]}", icon="ERROR")

            plan_store = getattr(runtime.state, "_artist_task_plans", None)
            plan_info = plan_store.inspect(runtime.executor.evidence) if plan_store is not None else None
            plan = plan_info["plan"] if plan_info is not None else None
            if plan is not None:
                completed = sum(step["status"] == "completed" for step in plan["steps"])
                task_box.label(text=f"Plan: {completed}/{len(plan['steps'])} marked complete")
                icons = {"pending": "DOT", "in_progress": "PLAY", "completed": "CHECKMARK", "blocked": "ERROR"}
                for step in plan["steps"][:8]:
                    task_box.label(text=step["description"][:80], icon=icons[step["status"]])
                    receipts = [item for item in plan_info["step_evidence"]["receipts"] if item["step_id"] == step["id"]]
                    if receipts:
                        receipt = receipts[-1]
                        earlier = " (earlier scene state)" if receipt["history_state"] == "historical_after_generation_change" else ""
                        task_box.label(text=f"Last edit: {receipt['outcome'].capitalize()}{earlier}")
                        task_box.label(text="Target core channels:")
                        task_box.label(text=_target_channels_label(receipt))
                        observation = receipt["protected_observation"]
                        label = "Not compared"
                        if observation:
                            if observation["validity"] == "stale":
                                label = "Stale; compare again"
                            elif observation["validity"] == "unknown":
                                label = "Snapshot unavailable"
                            else:
                                label = {"unchanged_within_scope": "Unchanged at comparison", "changed": "Changes found",
                                         "unknown": "Comparison incomplete"}.get(observation["status"], "Comparison incomplete")
                        task_box.label(text=f"Protected objects only: {label}")
                if len(plan["steps"]) > 8:
                    task_box.label(text=f"{len(plan['steps']) - 8} more steps; inspect the plan")
                policy = "enforced" if plan_info["protected_scope_enforced"] else "advisory"
                task_box.label(text=f"Protected scope: {len(plan['protected_objects'])} objects ({policy})")
                task_box.label(text="Step marks are claims;", icon="INFO")
                task_box.label(text="receipts do not verify the goal")
                task_box.label(text="Target records are historical;", icon="INFO")
                task_box.label(text="verify after manual edits")
                if plan_info["step_evidence"]["incomplete"]:
                    task_box.label(text="Execution receipts incomplete; inspect history", icon="ERROR")

            toolsets = layout.box()
            toolsets.label(text="Capability Toolsets", icon="MODIFIER")
            toolset_controls = toolsets.row(align=True)
            toolset_controls.operator(
                "blender_codex_bridge.enable_structured_toolsets",
                text="Enable Structured",
                icon="CHECKMARK",
            )
            toolset_controls.operator(
                "blender_codex_bridge.disable_optional_toolsets",
                text="Core Only",
                icon="LOCKED",
            )
            for item in runtime.registry.describe()["toolsets"]:
                row = toolsets.row(align=True)
                row.alert = item["name"] == "python" and item["enabled"]
                icon = "CHECKBOX_HLT" if item["enabled"] else "CHECKBOX_DEHLT"
                row.label(
                    text=f"{item['name'].replace('_', ' ').title()} ({item['tool_count']})",
                    icon=icon,
                )
                if item["name"] != "core":
                    operator = row.operator(
                        "blender_codex_bridge.set_toolset",
                        text="Disable" if item["enabled"] else "Enable",
                    )
                    operator.toolset = item["name"]
                    operator.enable = not item["enabled"]

            permissions = layout.box()
            permissions.label(text="Permissions", icon="LOCKED")
            if preferences:
                for property_name in (
                    "allow_inspect_scene",
                    "allow_viewport_capture",
                    "allow_transform_objects",
                    "allow_edit_mesh",
                    "allow_edit_materials",
                    "allow_edit_animation",
                    "allow_edit_scene",
                    "allow_edit_render",
                    "allow_delete_objects",
                    "allow_save_project",
                ):
                    permissions.prop(preferences, property_name)
                danger = permissions.column()
                danger.alert = preferences.allow_execute_python or preferences.allow_external_files
                danger.prop(preferences, "allow_execute_python")
                danger.prop(preferences, "allow_external_files")
                permissions.prop(preferences, "texture_directory")
                permissions.prop(preferences, "project_directory")
                if preferences.allow_execute_python:
                    danger.label(
                        text="Python bypasses structured edit gates and is not a sandbox.",
                        icon="ERROR",
                    )
                    danger.label(
                        text="It also requires Delete, External Files, and Save permissions."
                    )

            native_save = layout.box()
            native_save.label(text="Native Project Saving", icon="FILE_BLEND")
            native_status = runtime.native_save_policy.status()
            native_save.label(text=(f"Armed: {native_status['remaining_seconds']} seconds remaining"
                                    if native_status["armed"] else "Session permission disarmed"))
            native_save.label(text="Includes native callback/catalog effects outside the project folder")
            native_save.operator("blender_codex_bridge.arm_native_save", icon="UNLOCKED")
            native_save.operator("blender_codex_bridge.revoke_native_save", icon="LOCKED")

            jobs = layout.box()
            jobs.label(text="Jobs", icon="BRUSH_DATA")
            if preferences:
                jobs.prop(preferences, "paint_job_budget_ms")
            for job in runtime.jobs.list(limit=3)["jobs"]:
                _draw_job(jobs, job)
            jobs.label(text="Session only; native transfers cannot be preempted")
            history = layout.box()
            history.label(text="History", icon="TIME")
            history_limit = preferences.ui_history_rows if preferences else 8
            records = runtime.state.history(history_limit)
            if not records:
                history.label(text="No recent bridge activity")
            for record in records:
                icon = "CHECKMARK" if record["success"] else "ERROR"
                row = history.row(align=True)
                row.alert = not record["success"]
                row.label(text=record["tool"], icon=icon)
                row.label(text=f"{record['duration_ms']:.1f} ms")
                if record["tool"] in {"image.paint_job_start", "image.paint_surface_job_start",
                                      "image.export_job_start", "image.snapshot_job_start",
                                      "image.restore_snapshot_job_start"}:
                    history.label(text=record["description"][:96])
                if record["affected_objects"]:
                    history.label(text=f"Affected: {', '.join(record['affected_objects'][:4])}")
                if record["error_code"]:
                    history.label(text=f"{record['error_code']}: {record['description'][:72]}")
                effects = record.get("external_effects")
                if effects and effects.get("native_save"):
                    _draw_native_save_effects(history, effects)
            history_controls = history.row(align=True)
            history_controls.operator(
                "blender_codex_bridge.copy_diagnostics",
                text="Copy Diagnostics",
                icon="COPYDOWN",
            )
            history_controls.operator(
                "blender_codex_bridge.clear_history",
                text="Clear",
                icon="TRASH",
            )

            checkpoint = layout.box()
            checkpoint.label(text="Checkpoint", icon="RECOVER_LAST")
            recovery = runtime.checkpoints.recovery_status(limit=1)
            checkpoint.label(text=f"Native undo limit: {recovery['native_undo_steps']} steps")
            if not recovery["global_undo_enabled"]:
                checkpoint.label(text="Native undo is disabled", icon="ERROR")
            memory_limit = recovery["native_undo_memory_limit_mb"]
            if memory_limit:
                checkpoint.label(text=f"Undo memory limit: {memory_limit} MiB")
            checkpoint.label(text=f"Tracked operations: {recovery['tracked_operation_count']} (unverified)")
            expired = recovery["expired_operations_pruned_since_clear"]
            if expired:
                checkpoint.label(text=f"Expired operations pruned: {expired}", icon="ERROR")
            checkpoint.label(text="Labels are not backups", icon="INFO")
            checkpoint.label(text="Manual edits can expire recovery points")
            edit_session = runtime.checkpoints.editor_session_status()
            if edit_session is not None:
                checkpoint.label(text=f"Edit session: {edit_session['object'][:36]}", icon="INFO")
                checkpoint.label(text=("Return to Object Mode to finalize recovery" if context.mode != "OBJECT"
                                       else "Recovery will finalize the pending edit session"))
            checkpoint.operator("blender_codex_bridge.checkpoint_create", icon="ADD")
            row = checkpoint.row(align=True)
            undo = row.column(align=True)
            latest = recovery["latest_operation"]
            if latest is not None and latest["availability"] != "unverified":
                checkpoint.label(text="Undo exceeds the recovery budget", icon="ERROR")
            undo.enabled = bool(
                (latest is not None and latest["can_attempt_restore"])
                or (edit_session is not None and context.mode == "OBJECT"
                    and recovery["global_undo_enabled"])
            )
            undo.operator("blender_codex_bridge.checkpoint_undo", icon="LOOP_BACK")
            restore = row.column(align=True)
            named = recovery["checkpoints"]
            restore.enabled = bool(named and named[0]["can_attempt_restore"])
            restore.operator("blender_codex_bridge.checkpoint_restore", icon="RECOVER_LAST")
            if named and named[0]["availability"] != "unverified":
                checkpoint.label(text=("Named checkpoint expired" if named[0]["availability"] == "expired"
                                       else "Named checkpoint exceeds recovery budget"), icon="ERROR")


    CLASSES = (
        BCB_OT_arm_native_save,
        BCB_OT_revoke_native_save,
        BCB_OT_start_bridge,
        BCB_OT_stop_bridge,
        BCB_OT_toggle_pause,
        BCB_OT_emergency_stop,
        BCB_OT_cancel_job,
        BCB_OT_checkpoint_create,
        BCB_OT_checkpoint_undo,
        BCB_OT_checkpoint_restore,
        BCB_OT_set_toolset,
        BCB_OT_enable_structured_toolsets,
        BCB_OT_disable_optional_toolsets,
        BCB_OT_clear_history,
        BCB_OT_copy_diagnostics,
        BCB_PT_bridge_panel,
    )
else:
    CLASSES = ()
