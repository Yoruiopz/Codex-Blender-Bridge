"""Blender add-on preferences; these are the authoritative permission source."""

import logging
from pathlib import Path

try:
    import bpy  # type: ignore
    from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty  # type: ignore
except ImportError:  # pragma: no cover - permits pure module imports outside Blender
    bpy = None  # type: ignore

from .constants import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_REQUEST_TIMEOUT_SECONDS
from .permission_settings import (
    BOOLEAN_FIELDS,
    FOLDER_FIELDS,
    MASTER_FIELD,
    PROFILE_FILE,
    UNRESTRICTED_FIELD,
    preference_values,
    read_permission_settings,
    restrictive_values,
    write_permission_settings,
)
from .permissions import (
    DANGEROUS_PERMISSIONS,
    PREFERENCE_PROPERTIES,
    unrestricted_project_texture_paths,
)

LOGGER = logging.getLogger(__name__)
_DANGEROUS_FIELDS = frozenset(PREFERENCE_PROPERTIES[permission] for permission in DANGEROUS_PERMISSIONS)
_profile_error = ""
_restoring = False
_committed_settings = None


def _permission_profile_path():
    config = bpy.utils.user_resource("CONFIG")
    if not config or not Path(config).is_absolute():
        raise ValueError("Blender did not provide a local user config folder")
    return Path(config) / "blender_codex_bridge" / PROFILE_FILE


def _apply_permission_values(preferences, values):
    global _restoring
    _restoring = True
    try:
        for field, value in values.items():
            if getattr(preferences, field) != value:
                setattr(preferences, field, value)
    finally:
        _restoring = False


def restore_permission_settings():
    """Load the local profile without writing it or changing Blender preferences on disk."""
    global _committed_settings, _profile_error
    preferences = get_preferences()
    if preferences is None:
        return
    _profile_error = ""
    try:
        values = read_permission_settings(_permission_profile_path())
        if values is None:
            # Preserve individual permissions from older Blender profiles. The
            # two new grants are authoritative only in our own durable profile.
            _apply_permission_values(preferences, {MASTER_FIELD: False, UNRESTRICTED_FIELD: False})
            values = preference_values(preferences)
    except (OSError, ValueError, RecursionError) as exc:
        values = restrictive_values()
        _profile_error = "Permission profile could not be read. All Bridge permissions are off."
        LOGGER.warning("Bridge permission profile read refused (%s)", type(exc).__name__)
    _apply_permission_values(preferences, values)
    _committed_settings = values


def _persist_permission_values(preferences):
    global _committed_settings, _profile_error
    previous = _committed_settings if _committed_settings is not None else restrictive_values()
    try:
        values = preference_values(preferences)
        write_permission_settings(_permission_profile_path(), values)
    except (OSError, ValueError) as exc:
        # A write failure never grants new access. Honor local revocation for
        # this session and tell the user that the on-disk state has not changed.
        safe = {field: (getattr(preferences, field) is True and previous[field] is True)
                for field in BOOLEAN_FIELDS}
        for field in FOLDER_FIELDS:
            safe[field] = previous[field] if getattr(preferences, field) == previous[field] else ""
        safe[UNRESTRICTED_FIELD] &= safe[MASTER_FIELD]
        _apply_permission_values(preferences, safe)
        _profile_error = "Permission changes could not be saved. Check Blender's user config folder before restarting."
        LOGGER.warning("Bridge permission profile write failed (%s)", type(exc).__name__)
        return False
    _committed_settings = values
    _profile_error = ""
    return True


def _permission_setting_changed(preferences, _context):
    if not _restoring and _committed_settings is not None:
        _persist_permission_values(preferences)


def _set_dangerous_permissions(preferences, enabled):
    values = {MASTER_FIELD: enabled}
    if not enabled:
        values[UNRESTRICTED_FIELD] = False
    _apply_permission_values(preferences, values)
    return _persist_permission_values(preferences)

if bpy is not None:

    class BCB_OT_enable_dangerous_permissions(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.enable_dangerous_permissions"
        bl_label = "Enable all dangerous permissions"
        bl_description = (
            "Allow the Bridge to delete objects, access files, save projects, and run raw Blender Python "
            "with Blender's access. The raw Python tool can bypass structured edit and path checks"
        )

        def invoke(self, context, event):
            del event
            return context.window_manager.invoke_props_dialog(self, width=470)

        def draw(self, context):
            del context
            self.layout.label(text="Allow deletion, file access, saving, and raw Blender Python.", icon="ERROR")
            self.layout.label(text="Raw Python can bypass structured permission and path checks.")
            self.layout.label(text="This choice persists until you turn it off in Bridge preferences.")

        def execute(self, context):
            preferences = get_preferences(context)
            if preferences is None or not _set_dangerous_permissions(preferences, True):
                self.report({"ERROR"}, "Could not save the Bridge permission opt-in.")
                return {"CANCELLED"}
            return {"FINISHED"}


    class BCB_OT_disable_dangerous_permissions(bpy.types.Operator):
        bl_idname = "blender_codex_bridge.disable_dangerous_permissions"
        bl_label = "Turn off dangerous permissions override"
        bl_description = "Return to individual Bridge permissions and approved folders"

        def execute(self, context):
            preferences = get_preferences(context)
            if preferences is None:
                return {"CANCELLED"}
            if not _set_dangerous_permissions(preferences, False):
                self.report({"ERROR"}, "Override disabled for this session, but the change could not be saved.")
                return {"CANCELLED"}
            return {"FINISHED"}


    class BlenderCodexBridgePreferences(bpy.types.AddonPreferences):
        bl_idname = __package__

        host: StringProperty(
            name="Host",
            description="Local listener address; non-loopback values are always rejected",
            default=DEFAULT_HOST,
        )
        port: IntProperty(
            name="Port",
            description="Local TCP port used by the MCP bridge",
            default=DEFAULT_PORT,
            min=1,
            max=65535,
        )
        request_timeout: FloatProperty(
            name="Request Timeout",
            description="Maximum queue wait in seconds before a pending request is canceled",
            default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            min=0.5,
            max=300.0,
        )
        auto_start: BoolProperty(
            name="Start Bridge When Enabled",
            description="Start the localhost listener when this add-on is enabled",
            default=False,
        )

        allow_inspect_scene: BoolProperty(name="Inspect Scene", default=True, update=_permission_setting_changed)
        allow_viewport_capture: BoolProperty(name="Viewport Capture", default=True, update=_permission_setting_changed)
        allow_transform_objects: BoolProperty(name="Transform Objects", default=True, update=_permission_setting_changed)
        allow_edit_mesh: BoolProperty(name="Edit Meshes", default=True, update=_permission_setting_changed)
        allow_edit_materials: BoolProperty(name="Edit Materials", default=True, update=_permission_setting_changed)
        allow_edit_animation: BoolProperty(name="Edit Animation", default=True, update=_permission_setting_changed)
        allow_edit_scene: BoolProperty(name="Edit Scene, Cameras & Lights", default=True, update=_permission_setting_changed)
        allow_edit_render: BoolProperty(name="Edit Render Settings", default=True, update=_permission_setting_changed)
        allow_delete_objects: BoolProperty(
            name="Delete Objects",
            description="Allow permanent object deletion through structured tools",
            default=False,
            update=_permission_setting_changed,
        )
        allow_execute_python: BoolProperty(
            name="Execute Blender Python (Dangerous)",
            description=(
                "Arm a super-permission that bypasses structured edit gates; calls also require "
                "Delete Objects, Access External Files, and Save Project permissions"
            ),
            default=False,
            update=_permission_setting_changed,
        )
        allow_external_files: BoolProperty(
            name="Access External Files",
            description="Allow explicitly requested paths outside bridge-managed temporary captures",
            default=False,
            update=_permission_setting_changed,
        )
        allow_save_project: BoolProperty(
            name="Save Project",
            description="Persistently allow native Blender saves and their ordinary save callbacks",
            default=True,
            update=_permission_setting_changed,
        )
        all_dangerous_permissions: BoolProperty(default=False, options={"HIDDEN"})
        allow_unrestricted_project_texture_paths: BoolProperty(
            name="Use project and texture paths outside approved folders",
            description="The Bridge may use project and texture paths that Blender can access. This does not grant OS or Codex permissions",
            default=False,
            update=_permission_setting_changed,
        )
        project_directory: StringProperty(
            name="Approved Project Folder",
            description="Local .blend artifact folder. Blank grants no folder access. Only configurable in Blender preferences",
            subtype="DIR_PATH", default="",
            update=_permission_setting_changed,
        )
        texture_directory: StringProperty(
            name="Approved Texture Folder",
            description="User-approved absolute local folder for structured image reads; empty blocks loading. Not configurable through MCP",
            subtype="DIR_PATH",
            default="",
            update=_permission_setting_changed,
        )
        asset_directory: StringProperty(
            name="Approved Asset Folder",
            description="User-approved absolute local folder for structured GLB/FBX output; empty blocks asset export. Not configurable through MCP",
            subtype="DIR_PATH",
            default="",
            update=_permission_setting_changed,
        )
        asset_source_directory: StringProperty(
            name="Approved Asset Source Folder",
            description="User-approved absolute local folder for structured GLB/FBX reads; empty blocks asset import. Not configurable through MCP",
            subtype="DIR_PATH",
            default="",
            update=_permission_setting_changed,
        )
        ui_history_rows: IntProperty(
            name="History Rows",
            description="Recent bridge operations shown in the sidebar",
            default=8,
            min=3,
            max=20,
        )
        paint_job_budget_ms: IntProperty(
            name="Image Job CPU Budget (ms)",
            description="Cooperative CPU work per timer tick, not a bound on native image transfers; not configurable through MCP",
            default=4, min=1, max=8,
        )

        def draw(self, context):
            del context
            layout = self.layout
            network = layout.box()
            network.label(text="Local Connection", icon="NETWORK_DRIVE")
            network.prop(self, "host")
            network.prop(self, "port")
            network.prop(self, "request_timeout")
            network.prop(self, "auto_start")
            network.label(text="Only IPv4 loopback addresses are accepted.", icon="LOCKED")

            permissions = layout.box()
            permissions.label(text="Blender-side Permissions", icon="KEYINGSET")
            if _profile_error:
                permissions.label(text=_profile_error, icon="ERROR")
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
                "allow_save_project", "allow_execute_python", "allow_external_files",
            ):
                row = permissions.row()
                row.enabled = not (self.all_dangerous_permissions and property_name in _DANGEROUS_FIELDS)
                row.prop(self, property_name)
            danger = permissions.box()
            danger.alert = self.all_dangerous_permissions
            if self.all_dangerous_permissions:
                danger.label(text="Dangerous permissions override is ON", icon="ERROR")
                danger.operator("blender_codex_bridge.disable_dangerous_permissions", icon="LOCKED")
                danger.prop(self, UNRESTRICTED_FIELD)
                if unrestricted_project_texture_paths(self):
                    danger.label(text="Project and texture folder restrictions are OFF", icon="ERROR")
            else:
                danger.operator("blender_codex_bridge.enable_dangerous_permissions", icon="UNLOCKED")
            danger.label(text="Raw Blender Python can bypass structured edit and path checks.")
            danger.label(text="These choices persist in this Blender profile.")
            textures = layout.box()
            textures.label(text="Texture File Access", icon="IMAGE_DATA")
            textures.prop(self, "texture_directory")
            textures.label(text="Image reads also require Access External Files.")
            assets = layout.box()
            assets.label(text="Asset Delivery", icon="PACKAGE")
            assets.prop(self, "asset_directory")
            assets.label(text="Asset exports require file and save permission.")
            assets.prop(self, "asset_source_directory")
            assets.label(text="Asset imports require Access External Files.")
            projects = layout.box()
            projects.label(text="Native Project Saving", icon="FILE_BLEND")
            projects.prop(self, "project_directory")
            projects.label(text="Bridge saves require Save Project. New paths require Access External Files.")
            interface = layout.box()
            interface.label(text="Interface", icon="WINDOW")
            interface.prop(self, "ui_history_rows")
            interface.prop(self, "paint_job_budget_ms")


    CLASSES = (BlenderCodexBridgePreferences, BCB_OT_enable_dangerous_permissions, BCB_OT_disable_dangerous_permissions)
else:
    BlenderCodexBridgePreferences = None
    CLASSES = ()


def get_preferences(context=None):
    """Return live preferences, or ``None`` before registration/outside Blender."""

    if bpy is None:
        return None
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None
