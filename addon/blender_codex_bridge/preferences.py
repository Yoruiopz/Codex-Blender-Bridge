"""Blender add-on preferences; these are the authoritative permission source."""

try:
    import bpy  # type: ignore
    from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty  # type: ignore
except ImportError:  # pragma: no cover - permits pure module imports outside Blender
    bpy = None  # type: ignore

from .constants import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_REQUEST_TIMEOUT_SECONDS

if bpy is not None:

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

        allow_inspect_scene: BoolProperty(name="Inspect Scene", default=True)
        allow_viewport_capture: BoolProperty(name="Viewport Capture", default=True)
        allow_transform_objects: BoolProperty(name="Transform Objects", default=True)
        allow_edit_mesh: BoolProperty(name="Edit Meshes", default=True)
        allow_edit_materials: BoolProperty(name="Edit Materials", default=True)
        allow_edit_animation: BoolProperty(name="Edit Animation", default=True)
        allow_edit_scene: BoolProperty(name="Edit Scene, Cameras & Lights", default=True)
        allow_edit_render: BoolProperty(name="Edit Render Settings", default=True)
        allow_delete_objects: BoolProperty(
            name="Delete Objects",
            description="Allow permanent object deletion through structured tools",
            default=False,
        )
        allow_execute_python: BoolProperty(
            name="Execute Blender Python (Dangerous)",
            description=(
                "Arm a super-permission that bypasses structured edit gates; calls also require "
                "Delete Objects, Access External Files, and Save Project permissions"
            ),
            default=False,
        )
        allow_external_files: BoolProperty(
            name="Access External Files",
            description="Allow explicitly requested paths outside bridge-managed temporary captures",
            default=False,
        )
        allow_save_project: BoolProperty(name="Save Project", default=True)
        ui_history_rows: IntProperty(
            name="History Rows",
            description="Recent bridge operations shown in the sidebar",
            default=8,
            min=3,
            max=20,
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
                permissions.prop(self, property_name)
            danger = permissions.column()
            danger.alert = self.allow_execute_python or self.allow_external_files
            danger.prop(self, "allow_execute_python")
            danger.prop(self, "allow_external_files")
            interface = layout.box()
            interface.label(text="Interface", icon="WINDOW")
            interface.prop(self, "ui_history_rows")


    CLASSES = (BlenderCodexBridgePreferences,)
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
