"""Read Blender's native Save As browser without changing its UI state."""

from __future__ import annotations

import os
from pathlib import Path

from ..permissions import Permission
from ..utils import require_blender

_SAVE_OPERATORS = {"WM_OT_save_as_mainfile", "WM_OT_save_mainfile", "wm.save_as_mainfile", "wm.save_mainfile"}


def _directory_text(value):
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    if any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF for character in value):
        return None
    return value


def save_dialog_state(context, params):
    del params
    context.require(Permission.INSPECT_SCENE, Permission.ACCESS_EXTERNAL_FILES)
    bpy = require_blender()
    result = {"state": "closed", "operator": None, "directory": None, "filename": None, "filepath": None}
    windows = getattr(bpy.context.window_manager, "windows", ())
    if getattr(bpy.app, "background", False) or not windows:
        return {**result, "state": "unavailable"}

    dialogs = []
    unreadable = False
    try:
        for window in windows:
            context.check_cancelled()
            for area in window.screen.areas:
                if area.type != "FILE_BROWSER":
                    continue
                space = area.spaces.active
                operator = space.active_operator
                if operator is None or operator.bl_idname not in _SAVE_OPERATORS:
                    continue
                if space.params is None:
                    unreadable = True
                    continue
                dialogs.append((operator.bl_idname, space.params))
        if len(dialogs) > 1 or (dialogs and unreadable):
            return {**result, "state": "ambiguous"}
        if not dialogs:
            return {**result, "state": "unavailable"} if unreadable else result
        operator, selection = dialogs[0]
        directory = _directory_text(selection.directory)
        filename = _directory_text(selection.filename)
    except (AttributeError, OSError, ReferenceError, RuntimeError, ValueError):
        return {**result, "state": "unavailable"}

    filepath = None
    if (directory and filename and Path(directory).is_absolute() and filename not in {".", ".."}
            and not any(separator in filename for separator in ("/", "\\", ":"))):
        filepath = str(Path(directory) / filename)
    return {"state": "open", "operator": operator, "directory": directory, "filename": filename, "filepath": filepath}


def register_tools(registry):
    registry.register(
        "project.save_dialog_state", save_dialog_state,
        permissions=(Permission.INSPECT_SCENE, Permission.ACCESS_EXTERNAL_FILES),
        description="Read Blender's open Save or Save As dialog and its proposed path.",
    )
