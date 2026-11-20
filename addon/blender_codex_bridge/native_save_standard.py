# SPDX-License-Identifier: GPL-3.0-or-later
"""Ordinary stock Blender saving under the live project and path permissions."""
from __future__ import annotations

import logging
import os
import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MethodType

from .command_queue import QueuedRequest
from .errors import BridgeError, ErrorCode, invalid_argument
from .native_save_source import hook_facts, hooks_match, initial_dependencies, qualify_provider
from .permissions import Permission, unrestricted_project_texture_paths
from .preferences import get_preferences
from .task_plans import get_task_plans
from .tool_registry import check_final_mutation
from .utils import require_blender

METHOD = "project.save"
LOGGER = logging.getLogger(__name__)
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)
# Blender's native file path buffers have 1024 bytes, including the terminator.
# Leave space for its temporary and numbered backup suffixes.
_NATIVE_FILEPATH_BYTES_MAX = 1020


def _ordinary_text(raw, *, windows):
    if (type(raw) is not str or not raw or len(raw) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in raw)):
        raise invalid_argument("Use an absolute local path with no control characters.")
    try:
        if len(raw.encode("utf-8")) > 4096:
            raise invalid_argument("The UTF-8 path exceeds the 4096 byte limit.")
    except UnicodeError as error:
        raise invalid_argument("The path is not valid UTF-8 text.") from error
    if windows:
        if re.match(r"^[A-Za-z]:[\\/]", raw) is None:
            raise invalid_argument("Use an absolute Windows drive path.")
        pieces = re.split(r"[\\/]", raw[3:])
        if any(piece.endswith((".", " ")) or _DEVICE.match(piece.split(".", 1)[0].rstrip(" "))
               or any(char in '<>:"|?*' for char in piece) for piece in pieces):
            raise invalid_argument("Windows paths cannot use device names, stream syntax, or trailing dots/spaces.")
    else:
        if not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
            raise invalid_argument("Use an absolute local filesystem path.")
        pieces = raw[1:].split("/")
    if any(piece in {".", ".."} for piece in pieces):
        raise invalid_argument("Relative path components are not allowed.")
    return raw


def ordinary_project_path(raw: str) -> Path:
    """Parse a local absolute .blend path without opening anything."""
    raw = _ordinary_text(raw, windows=os.name == "nt")
    path = Path(raw)
    if not path.is_absolute() or raw.endswith(("/", "\\")) or path.suffix.lower() != ".blend":
        raise invalid_argument("Use an absolute filepath ending in .blend.")
    if len(str(path).encode("utf-8")) > _NATIVE_FILEPATH_BYTES_MAX:
        raise invalid_argument("The filepath is too long for Blender's native save and backup paths.")
    return path


def _file_identity(path, *, directory=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not directory:
            return None
        raise
    shape = stat.S_ISDIR if directory else stat.S_ISREG
    if not shape(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE:
        raise invalid_argument("Project paths must use ordinary files and folders without aliases or junctions.")
    if directory:
        return info.st_dev, info.st_ino
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _path_identity(path):
    return (tuple(_file_identity(parent, directory=True) for parent in reversed(path.parents)),
            _file_identity(path))


def approve_project_path(raw: str, prefs) -> Path:
    """Apply live project folder policy and lstat the path only after caller authorization."""
    path = ordinary_project_path(raw)
    try:
        if not unrestricted_project_texture_paths(prefs):
            root = getattr(prefs, "project_directory", "")
            if not root:
                raise BridgeError(ErrorCode.PERMISSION_DENIED, "Choose an Approved Project Folder in Blender first.")
            root = Path(_ordinary_text(root, windows=os.name == "nt"))
            if root == Path(root.anchor) or not path.is_relative_to(root):
                raise BridgeError(ErrorCode.PERMISSION_DENIED, "Save destinations must be inside the Approved Project Folder.")
        _path_identity(path)
        if path.parent.resolve(strict=True) != path.parent:
            raise invalid_argument("Use the direct project folder path without filesystem aliases.")
    except OSError as error:
        raise _filesystem_error(error) from error
    return path


def _filesystem_error(error):
    return BridgeError(ErrorCode.OPERATION_FAILED, "Blender's project destination could not be accessed.",
                       {"reason": "PROJECT_DESTINATION_IO", "os_error": error.errno})


def _policy(prefs):
    return getattr(prefs, "project_directory", ""), unrestricted_project_texture_paths(prefs)


def _permission_set(filepath, unrestricted=False):
    if filepath is not None or unrestricted:
        return Permission.SAVE_PROJECT, Permission.ACCESS_EXTERNAL_FILES
    return (Permission.SAVE_PROJECT,)


def _require_queued(context, params):
    if threading.current_thread() is not threading.main_thread():
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Project saves need Blender's main thread.")
    callback = context.check_cancelled
    if type(callback) is not MethodType or type(callback.__self__) is not QueuedRequest:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Project saves need a queued Bridge request.",
                          {"reason": "NATIVE_SAVE_REQUIRES_QUEUED_REQUEST"})
    request = callback.__self__.request
    if request.method != METHOD or request.params is not params or request._lifecycle is not context.request_lifecycle:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "The queued save request changed.")
    return hook_facts(context)


def scoped_save_parameters(registry, params):
    # Freeze the existing call arguments and give the save handler ownership of
    # finalization. This tool must not finalize a previous logical edit group.
    from . import runtime

    initial_dependencies(registry, params)
    guard = runtime.native_save_permission_provider_intact
    if (guard is not runtime._PERMISSION_PROVIDER_GUARD
            or guard.__code__ is not runtime._PERMISSION_PROVIDER_GUARD_CODE or not guard()):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "The local project save permission provider changed.",
                          {"native_save_invoked": False, "execution_started": False})
    return True


@dataclass(slots=True)
class SaveOutcome:
    requested_filepath: str | None = None
    active_filepath: str | None = None
    invoked: bool = False
    completed: bool = False
    file_bytes: int | None = None

    def effects(self):
        return {"execution_started": self.invoked, "native_save_invoked": self.invoked,
                "native_save_finished": self.completed, "project_saved": self.file_bytes is not None,
                "bridge_file_writes": self.invoked, "possible_file_writes": self.invoked,
                "requested_filepath": self.requested_filepath, "active_filepath": self.active_filepath,
                "actual_saved_path": self.active_filepath if self.file_bytes is not None else None,
                "file_bytes": self.file_bytes, "native_effect_inventory_complete": False,
                "native_destination_race_excluded": False, "fresh_process_reopen_verified": False}


def save(context, params):
    """Run a single nonpreemptible native save and report the observed result."""
    outcome = SaveOutcome()
    try:
        return _save(context, params, outcome)
    except OSError as error:
        failure = _filesystem_error(error)
        failure.context.update(outcome.effects(), verification_required=outcome.invoked)
        raise failure from error
    except BridgeError as error:
        error.context.update(outcome.effects(), verification_required=outcome.invoked)
        raise


def _save(context, params, outcome):
    if set(params) - {"filepath", "overwrite", "_task", "task_description"}:
        raise invalid_argument("Project save accepts only filepath and overwrite.")
    raw = params.get("filepath")
    overwrite = params.get("overwrite", False)
    if raw is not None:
        ordinary_project_path(raw)
    if type(overwrite) is not bool:
        raise invalid_argument("'overwrite' must be a boolean.")
    hooks = _require_queued(context, params)
    qualify_provider(context)
    spec = context.registry.get(METHOD)
    context.checkpoint_finalization_owner = context.checkpoint_call_id
    context.require(*_permission_set(raw))
    check_final_mutation(context, METHOD, expected_spec=spec)
    bpy = require_blender()
    prefs = get_preferences()
    if prefs is None:
        raise BridgeError(ErrorCode.PERMISSION_DENIED, "Bridge preferences are unavailable.")
    policy = _policy(prefs)
    required = _permission_set(raw, policy[1])
    if policy[1] and raw is None:
        context.require(*required)
        check_final_mutation(context, METHOD, expected_spec=spec)
    current = bpy.data.filepath
    if raw is None and not current:
        raise invalid_argument("This project has no filepath. Supply a destination for its first save.", requires_filepath=True)
    target = approve_project_path(raw if raw is not None else current, prefs)
    outcome.requested_filepath = str(target)
    parents, destination = _path_identity(target)
    if raw is not None and destination is not None and not overwrite:
        raise invalid_argument("The destination exists. Set overwrite=true only to replace this file.",
                               reason="PROJECT_DESTINATION_EXISTS")
    if raw is None and destination is None:
        raise invalid_argument("The current project is missing on disk. Supply an explicit Save As destination.",
                               reason="CURRENT_PROJECT_MISSING", requires_filepath=True)
    mode = "SAVE_CURRENT" if raw is None else "SAVE_AS"
    operator = bpy.ops.wm.save_mainfile if raw is None else bpy.ops.wm.save_as_mainfile
    if not operator.poll():
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "Blender cannot save in the current context.")
    backup_count = bpy.context.preferences.filepaths.save_version
    if type(backup_count) is not int or not 0 <= backup_count <= 32:
        raise invalid_argument("Blender's save backup count is outside the supported range 0 through 32.")
    backups = tuple(Path(f"{target}{index}") for index in range(1, backup_count + 1))
    original_backups = tuple(_file_identity(path) for path in backups)

    def live_gate():
        if not hooks_match(context, hooks):
            raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR, "The save request's queue authority changed.")
        qualify_provider(context)
        context.require(*required)
        qualify_provider(context)
        live_prefs = get_preferences()
        if live_prefs is None or _policy(live_prefs) != policy:
            raise BridgeError(ErrorCode.PERMISSION_DENIED, "Project folder permissions changed during saving.")
        if context.jobs.active is not None:
            raise BridgeError(ErrorCode.OPERATION_FAILED, "Finish or cancel the active Bridge job before saving.")
        if get_task_plans(context.state).protection is not None:
            raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Native save cannot verify the enforced protected scope.",
                              {"protected_scope_enforced": True, "scope_complete": False})
        check_final_mutation(context, METHOD, expected_spec=spec)

    live_gate()
    if (bpy.data.filepath != current or bpy.context.preferences.filepaths.save_version != backup_count
            or _path_identity(target) != (parents, destination)
            or tuple(_file_identity(path) for path in backups) != original_backups):
        raise BridgeError(ErrorCode.OPERATION_FAILED, "The project or destination changed before saving.",
                          {"reason": "PROJECT_SAVE_INTENT_CHANGED"})
    check_final_mutation(context, METHOD, expected_spec=spec)
    outcome.invoked = True
    try:
        result = operator() if raw is None else operator(filepath=str(target), check_existing=False)
        outcome.completed = result == {"FINISHED"}
    except RuntimeError as error:
        LOGGER.warning("Native %s raised a Blender save error", mode, exc_info=True)
        message = None
        if type(error) is RuntimeError and error.args and type(error.args[0]) is str:
            message = "".join(char if char.isprintable() else " " for char in error.args[0][:512]).strip()
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Blender reported an error while saving the project.",
                          {"reason": "NATIVE_SAVE_ERROR", "native_error": message}) from error
    finally:
        outcome.active_filepath = bpy.data.filepath or None
    if not outcome.completed:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Blender canceled the save or did not report completion.",
                          {"reason": "NATIVE_SAVE_NOT_FINISHED"})
    live_gate()
    if outcome.active_filepath is None or ordinary_project_path(outcome.active_filepath) != target:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Blender returned a different active filepath after saving.",
                          {"reason": "NATIVE_SAVE_PATH_MISMATCH"})
    observed_parents, saved = _path_identity(target)
    if observed_parents != parents or saved is None or saved[2] <= 0 or saved == destination:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "The native save output could not be verified on disk.",
                          {"reason": "NATIVE_SAVE_OUTPUT_UNVERIFIED"})
    outcome.file_bytes = saved[2]
    from .project_recovery import save_recovery_checkpoint, unavailable

    def check_saved_output():
        live_gate()
        if bpy.data.filepath != outcome.active_filepath or _path_identity(target) != (parents, saved):
            raise BridgeError(ErrorCode.OPERATION_FAILED, "The saved project changed during checkpoint verification.",
                              {"reason": "SAVED_PROJECT_CHANGED"})

    try:
        checkpoint = save_recovery_checkpoint(target, check_saved_output)
    except BridgeError as error:
        checkpoint = {**unavailable("RECOVERY_VERIFICATION_INTERRUPTED"), "error_code": error.code}
    return {**outcome.effects(), "saved": True, "mode": mode, "filepath": outcome.active_filepath,
            "recovery_checkpoint": checkpoint}
