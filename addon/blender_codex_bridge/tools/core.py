"""Always-available inspection, capture, checkpoint, save, and registry tools."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..constants import ADDON_VERSION_STRING
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..scene_inspector import inspect_object, inspect_scene, project_info, scene_summary
from ..selection import inspect_selection
from ..tool_registry import ToolContext, ToolRegistry
from ..utils import bool_param, int_param, require_blender
from ..viewport import capture_viewport


def _resolve_save_as_path(raw_filepath: str) -> Path:
    """Validate a user-approved Save As destination without implicit expansion."""

    if any(ord(character) < 32 for character in raw_filepath):
        raise invalid_argument("Project save paths cannot contain control characters.")
    if raw_filepath.startswith(("\\\\", "//")):
        raise invalid_argument("Network and UNC project save paths are not supported in V1.")
    candidate = Path(raw_filepath)
    if not candidate.is_absolute():
        raise invalid_argument("Project Save As requires an absolute filepath.")
    if ".." in candidate.parts:
        raise invalid_argument("Project save paths cannot contain parent traversal segments.")
    if candidate.is_reserved():
        raise invalid_argument("Reserved device paths cannot be used for project saves.")
    try:
        target = candidate.resolve()
    except OSError as exc:
        raise invalid_argument("Project save path could not be resolved.", detail=str(exc)) from exc
    if os.name != "nt" and len(target.parts) > 1 and target.parts[1] in {"dev", "proc", "sys"}:
        raise invalid_argument("System device and process paths cannot be used for project saves.")
    if target.suffix.lower() != ".blend":
        raise invalid_argument("Project save paths must use the .blend extension.")
    return target


def bridge_status(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del params
    bpy = require_blender()
    state = context.state.snapshot()
    scene = bpy.context.scene
    active = bpy.context.view_layer.objects.active
    return {
        "blender_version": bpy.app.version_string,
        "addon_version": ADDON_VERSION_STRING,
        "connection_status": state["connection_status"],
        "server": {
            "running": state["server_running"],
            "host": state["host"],
            "port": state["port"],
            "connected_clients": state["connected_clients"],
        },
        "filepath": bpy.data.filepath,
        "mode": bpy.context.mode,
        "scene": scene.name,
        "active_object": active.name if active else None,
        "enabled_permissions": [
            name for name, enabled in context.permissions.snapshot().items() if enabled
        ],
        "permissions": context.permissions.snapshot(),
        "enabled_toolsets": list(context.registry.enabled_toolsets),
        "agent": {
            "paused": state["paused"],
            "emergency_stopped": state["emergency_stopped"],
            "current_task": state["current_task"],
            "current_method": state["current_method"],
            "is_executing": state["is_executing"],
        },
    }


def save_project(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    bpy = require_blender()
    raw_filepath = params.get("filepath")
    if raw_filepath is not None and (not isinstance(raw_filepath, str) or not raw_filepath.strip()):
        raise invalid_argument("'filepath' must be a non-empty string.")
    current = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if raw_filepath is not None:
        # Authorize before resolving or probing any caller-supplied path.
        context.require(Permission.ACCESS_EXTERNAL_FILES)
    target = _resolve_save_as_path(raw_filepath) if raw_filepath else current
    if target is None:
        raise invalid_argument(
            "The project has never been saved; provide a new .blend filepath.",
            parameter="filepath",
        )
    if target.suffix.lower() != ".blend":
        raise invalid_argument("Project save paths must use the .blend extension.")
    save_as = current is None or target != current
    if save_as:
        if not target.parent.is_dir():
            raise invalid_argument("The project destination directory does not exist.", directory=str(target.parent))
        if target.exists():
            raise invalid_argument(
                "Refusing to overwrite a different existing project file.",
                filepath=str(target),
            )
    try:
        if save_as:
            result = bpy.ops.wm.save_as_mainfile(filepath=str(target), check_existing=False, copy=False)
        else:
            result = bpy.ops.wm.save_mainfile()
    except RuntimeError as exc:
        raise BridgeError(
            ErrorCode.OPERATION_FAILED,
            "Blender failed to save the project.",
            {"filepath": str(target), "detail": str(exc)},
        ) from exc
    if "FINISHED" not in result:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Project save did not finish.")
    return {
        "saved": True,
        "filepath": bpy.data.filepath,
        "save_as": save_as,
        "is_dirty": bool(bpy.data.is_dirty),
    }


def checkpoint_create(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    description = params.get("description", "Agent checkpoint")
    if not isinstance(description, str):
        raise invalid_argument("'description' must be a string.")
    return context.checkpoints.create(description)


def checkpoint_undo_last(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    if not bool_param(params, "confirm_global_undo", False):
        raise invalid_argument(
            "Set 'confirm_global_undo' to true to acknowledge that Blender cannot prove undo ownership."
        )
    return context.checkpoints.undo_last()


def checkpoint_list(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    limit = int_param(params, "limit", 20, minimum=1, maximum=100)
    checkpoints = context.checkpoints.list(limit)
    history = context.state.history(limit)
    return {
        "checkpoints": checkpoints,
        "checkpoint_count": len(checkpoints),
        "operation_history": history,
        "operation_count": len(history),
    }


def checkpoint_restore_last(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    if not bool_param(params, "confirm_global_undo", False):
        raise invalid_argument(
            "Set 'confirm_global_undo' to true to acknowledge that restore uses Blender global undo."
        )
    return context.checkpoints.restore_last()


def toolsets_list(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    del params
    return context.registry.describe()


def _toolset_name(params: Mapping[str, Any]) -> str:
    value = params.get("name", params.get("toolset"))
    if not isinstance(value, str) or not value.strip():
        raise invalid_argument("A non-empty toolset 'name' is required.")
    return value.strip().lower()


def toolsets_enable(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    name = _toolset_name(params)
    was_enabled = name in context.registry.enabled_toolsets
    context.registry.enable_toolset(name)
    return {"changed": not was_enabled, "toolset": name, "enabled": True}


def toolsets_disable(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    name = _toolset_name(params)
    was_enabled = name in context.registry.enabled_toolsets
    context.registry.disable_toolset(name)
    return {"changed": was_enabled, "toolset": name, "enabled": False}


def register_tools(registry: ToolRegistry) -> None:
    inspect_permission = (Permission.INSPECT_SCENE,)
    registry.register("bridge.status", bridge_status, description="Return Blender, bridge, permission, and agent state.")
    registry.register("project.info", lambda c, p: project_info(p), permissions=inspect_permission, description="Inspect project-level state.")
    registry.register("scene.inspect", lambda c, p: inspect_scene(p), permissions=inspect_permission, description="Inspect bounded authoritative scene structure.")
    registry.register("scene.summary", lambda c, p: scene_summary(p), permissions=inspect_permission, description="Return an LLM-oriented scene summary in text and JSON.")
    registry.register("selection.inspect", lambda c, p: inspect_selection(p), permissions=inspect_permission, description="Inspect object and edit-mesh selection context.")
    registry.register("object.inspect", lambda c, p: inspect_object(p), permissions=inspect_permission, description="Inspect one object and compact mesh diagnostics.")
    registry.register(
        "viewport.capture",
        lambda c, p: capture_viewport(p),
        permissions=(Permission.CAPTURE_VIEWPORT,),
        modifies=True,
        automatic_checkpoint=False,
        description=(
            "Capture a managed temporary viewport PNG, restore temporary UI/render "
            "settings, and replace Blender's Render Result buffer."
        ),
    )
    registry.register("checkpoint.create", checkpoint_create, description="Create a named Blender undo marker.", automatic_checkpoint=False)
    registry.register(
        "checkpoint.undo_last",
        checkpoint_undo_last,
        modifies=True,
        description=(
            "Run one Blender global undo after explicit risk acknowledgement; interleaved user "
            "work cannot be distinguished."
        ),
        automatic_checkpoint=False,
    )
    registry.register(
        "checkpoint.restore_last",
        checkpoint_restore_last,
        modifies=True,
        description=(
            "Use repeated Blender global undo after local confirmation; interleaved user work "
            "cannot be distinguished."
        ),
        automatic_checkpoint=False,
        remote=False,
    )
    registry.register(
        "checkpoint.list",
        checkpoint_list,
        description="List bounded logical checkpoints and operation history.",
    )
    registry.register(
        "project.save",
        save_project,
        permissions=(Permission.SAVE_PROJECT,),
        modifies=True,
        automatic_checkpoint=False,
        description="Save the current project or, with extra permission, a new non-overwriting path.",
    )
    registry.register("toolsets.list", toolsets_list, description="List Blender-side structured toolsets and tools.")
    registry.register("toolsets.enable", toolsets_enable, description="Enable one Blender-side domain toolset.")
    registry.register("toolsets.disable", toolsets_disable, description="Disable one Blender-side domain toolset.")
