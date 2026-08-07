"""Codex Bridge 3D View N-panel and explicit user-control operators."""

try:
    import bpy  # type: ignore
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore

from .errors import BridgeError
from .preferences import get_preferences
from .runtime import get_runtime

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
                status_row.label(text=f"Modifying: {state['current_method']}", icon="REC")
            if preferences:
                connection.prop(preferences, "host")
                connection.prop(preferences, "port")

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

            task_box = layout.box()
            task_box.label(text="Current Task", icon="PRESET")
            task_box.label(text=state["current_task"] or "No active task")
            if state["current_method"]:
                task_box.label(text=f"Tool: {state['current_method']}")

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
                    "allow_delete_objects",
                    "allow_save_project",
                ):
                    permissions.prop(preferences, property_name)
                danger = permissions.column()
                danger.alert = preferences.allow_execute_python or preferences.allow_external_files
                danger.prop(preferences, "allow_execute_python")
                danger.prop(preferences, "allow_external_files")

            history = layout.box()
            history.label(text="History", icon="TIME")
            records = runtime.state.history(6)
            if not records:
                history.label(text="No recent bridge activity")
            for record in records:
                icon = "CHECKMARK" if record["success"] else "ERROR"
                history.label(text=f"{record['tool']}: {record['description'][:52]}", icon=icon)

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
        BCB_PT_bridge_panel,
    )
else:
    CLASSES = ()
