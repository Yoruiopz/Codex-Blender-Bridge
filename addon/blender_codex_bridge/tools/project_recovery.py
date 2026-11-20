"""Verify the durable project receipt and explicitly reopen it on demand."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .. import project_recovery as recovery
from ..errors import BridgeError, ErrorCode, invalid_argument
from ..permissions import Permission
from ..tool_registry import ToolContext, ToolRegistry, check_final_mutation
from ..utils import require_blender

STATUS = "project.checkpoint_status"
REOPEN = "project.checkpoint_reopen"
READ = (Permission.INSPECT_SCENE, Permission.ACCESS_EXTERNAL_FILES)
WRITE = (Permission.EDIT_SCENE, Permission.ACCESS_EXTERNAL_FILES)


def _approve(filepath: str) -> Path:
    from ..native_save_standard import approve_project_path
    from ..runtime import _preferences

    try:
        return approve_project_path(filepath, _preferences())
    except (BridgeError, OSError, ValueError):
        raise recovery.EvidenceError("RECOVERY_PATH_NOT_APPROVED") from None


def _checkpoint() -> tuple[dict[str, Any], Path]:
    record = recovery.read_index()
    if record is None:
        raise recovery.EvidenceError("NO_VERIFIED_CHECKPOINT")
    return record, _approve(record["filepath"])


def _verify(record: dict[str, Any], path: Path, check: Callable[[], None]) -> recovery.ProjectBytes:
    try:
        if recovery.file_signature(path)[2] != record["file_bytes"]:
            raise recovery.EvidenceError("RECOVERY_FILE_CHANGED")
        evidence = recovery.hash_project_bytes(path, check)
    except FileNotFoundError:
        raise recovery.EvidenceError("RECOVERY_FILE_MISSING") from None
    if evidence.size != record["file_bytes"] or evidence.sha256 != record["file_sha256"]:
        raise recovery.EvidenceError("RECOVERY_FILE_CHANGED")
    return evidence


def recovery_hint(context: ToolContext) -> dict[str, Any] | None:
    """Report that a prior verified receipt exists without hashing on bridge.status."""
    flags = context.permissions.snapshot()
    if not all(flags.get(permission.value, False) for permission in READ):
        return None
    try:
        record, path = _checkpoint()
        if recovery.file_signature(path)[2] != record["file_bytes"]:
            return recovery.unavailable("RECOVERY_FILE_CHANGED")
    except recovery.EvidenceError as error:
        return recovery.unavailable(error.reason)
    except FileNotFoundError:
        return recovery.unavailable("RECOVERY_FILE_MISSING")
    except (BridgeError, OSError):
        return recovery.unavailable("RECOVERY_EVIDENCE_UNREADABLE")
    return recovery.summarize(record, state="verification_required")


def checkpoint_status(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    if set(params) - {"_task", "task_description"}:
        raise invalid_argument("Checkpoint status takes no arguments.")
    context.require(*READ)

    def check() -> None:
        check_final_mutation(context, STATUS)

    check()
    try:
        record, path = _checkpoint()
        evidence = _verify(record, path, check)
        context.require(*READ)
        if _approve(record["filepath"]) != path or recovery.file_signature(path) != evidence.signature:
            raise recovery.EvidenceError("RECOVERY_FILE_CHANGED")
        if recovery.read_index() != record:
            raise recovery.EvidenceError("RECOVERY_INDEX_CHANGED")
        check()
    except recovery.EvidenceError as error:
        return recovery.unavailable(error.reason)
    except OSError:
        return recovery.unavailable("RECOVERY_EVIDENCE_UNREADABLE")
    return recovery.summarize(record)


def _require_clean_project(bpy: Any, context: ToolContext) -> None:
    if bpy.data.is_dirty is not False or bpy.context.mode != "OBJECT":
        raise BridgeError(
            ErrorCode.BLENDER_CONTEXT_ERROR,
            "Checkpoint reopen requires a clean project in Object Mode. Save or discard current edits in Blender first.",
            {"reason": "RECOVERY_LIVE_PROJECT_NOT_CLEAN", "reopened": False},
        )
    # Blender's project flag can be clean while Image Editor pixels are dirty.
    if any(image.is_dirty for image in bpy.data.images):
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR,
                          "Save or discard modified image pixels in Blender before reopening a checkpoint.",
                          {"reason": "RECOVERY_DIRTY_IMAGES", "reopened": False})
    if context.checkpoints.editor_session_status() is not None:
        raise BridgeError(ErrorCode.BLENDER_CONTEXT_ERROR,
                          "Finish the current Bridge edit session before reopening a checkpoint.",
                          {"reason": "RECOVERY_EDIT_SESSION_ACTIVE", "reopened": False})


def checkpoint_reopen(context: ToolContext, params: Mapping[str, Any]) -> dict[str, Any]:
    checkpoint_id = params.get("checkpoint_id")
    if (set(params) - {"checkpoint_id", "confirm_reopen", "_task", "task_description"}
            or type(checkpoint_id) is not str or not recovery.CHECKPOINT_ID.fullmatch(checkpoint_id)
            or params.get("confirm_reopen") is not True):
        raise invalid_argument("Provide the current checkpoint_id and confirm_reopen=true.")
    if context.check_final_request is None or context.request_lifecycle is None:
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint reopen requires an owned queued Bridge request.")

    from ..runtime import get_runtime

    runtime = get_runtime()
    if any(getattr(runtime, attribute) is not getattr(context, attribute)
           for attribute in ("state", "registry", "permissions", "checkpoints", "jobs")):
        raise BridgeError(ErrorCode.NOT_IMPLEMENTED, "Checkpoint reopen requires the active Bridge runtime.")
    bpy = require_blender()
    _require_clean_project(bpy, context)
    loaded_path = bpy.data.filepath
    context.require(*WRITE)

    def check() -> None:
        check_final_mutation(context, REOPEN)

    check()
    try:
        record, path = _checkpoint()
        if record["checkpoint_id"] != checkpoint_id:
            raise recovery.EvidenceError("RECOVERY_CHECKPOINT_CHANGED")
        evidence = _verify(record, path, check)
    except (recovery.EvidenceError, OSError) as error:
        reason = error.reason if isinstance(error, recovery.EvidenceError) else "RECOVERY_EVIDENCE_UNREADABLE"
        raise recovery.refusal(reason, "The saved checkpoint could not be verified for reopen.", reopened=False) from None

    def open_verified() -> set[str]:
        context.require(*WRITE)
        _require_clean_project(bpy, context)
        try:
            if (bpy.data.filepath != loaded_path or recovery.read_index() != record
                    or _approve(record["filepath"]) != path or recovery.file_signature(path) != evidence.signature):
                raise recovery.EvidenceError("RECOVERY_FILE_OR_CONTEXT_CHANGED")
        except (recovery.EvidenceError, OSError):
            raise recovery.refusal("RECOVERY_FILE_OR_CONTEXT_CHANGED",
                                   "Checkpoint or active project changed before reopen.", reopened=False) from None
        check()
        try:
            result = bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
        except RuntimeError:
            raise recovery.refusal("RECOVERY_NATIVE_OPEN_FAILED", "Blender could not reopen the verified checkpoint.",
                                   execution_started=True, verification_required=True) from None
        actual = bpy.data.filepath
        if result != {"FINISHED"} or type(actual) is not str or Path(actual) != path or bpy.data.is_dirty is not False:
            raise recovery.refusal("RECOVERY_NATIVE_OPEN_UNVERIFIED",
                                   "Blender did not confirm the checkpoint path after opening.",
                                   execution_started=True, verification_required=True)
        try:
            if recovery.file_signature(path) != evidence.signature:
                raise recovery.EvidenceError("RECOVERY_FILE_CHANGED")
        except (recovery.EvidenceError, OSError):
            raise recovery.refusal("RECOVERY_FILE_CHANGED_DURING_OPEN",
                                   "Checkpoint bytes may have changed during Blender's open.",
                                   execution_started=True, verification_required=True) from None
        return result

    runtime.run_checkpoint_open(open_verified)
    return {**recovery.summarize(record), "reopened": True, "filepath": bpy.data.filepath,
            "auto_replayed": False, "previous_project_clean": True}


def register_tools(registry: ToolRegistry) -> None:
    registry.register(STATUS, checkpoint_status, permissions=READ,
                      description="Find and recheck the latest durable project-save checkpoint.")
    registry.register(REOPEN, checkpoint_reopen, permissions=WRITE, modifies=True,
                      automatic_checkpoint=False, exclusive_mutation=True, batchable=False,
                      description="Reopen the explicitly confirmed verified checkpoint from a clean Blender project.")
