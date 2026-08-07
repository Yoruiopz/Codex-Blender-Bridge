"""Codex Bridge 3D View N-panel and explicit user-control operators."""

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

if bpy is not None:

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
        bl_label = "Undo Agent Step (Global)"
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
                    {"confirm_global_undo": True},
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
            self.report({"INFO"}, f"Restored {result['undo_steps']} tracked agent step(s)")
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
                if preferences.allow_execute_python:
                    danger.label(
                        text="Python bypasses structured edit gates and is not a sandbox.",
                        icon="ERROR",
                    )
                    danger.label(
                        text="It also requires Delete, External Files, and Save permissions."
                    )

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
                if record["affected_objects"]:
                    history.label(text=f"Affected: {', '.join(record['affected_objects'][:4])}")
                if record["error_code"]:
                    history.label(text=f"{record['error_code']}: {record['description'][:72]}")
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
            checkpoint.operator("blender_codex_bridge.checkpoint_create", icon="ADD")
            row = checkpoint.row(align=True)
            row.operator("blender_codex_bridge.checkpoint_undo", icon="LOOP_BACK")
            row.operator("blender_codex_bridge.checkpoint_restore", icon="RECOVER_LAST")


    CLASSES = (
        BCB_OT_start_bridge,
        BCB_OT_stop_bridge,
        BCB_OT_toggle_pause,
        BCB_OT_emergency_stop,
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
