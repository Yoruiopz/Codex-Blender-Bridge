"""Verify the durable project receipt and explicitly reopen it on demand."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
_PRIMARY_UNAVAILABLE = frozenset({
    "RECOVERY_FILE_MISSING", "RECOVERY_FILE_CHANGED", "RECOVERY_FILE_SHAPE_OR_LIMIT", "RECOVERY_NOT_BLEND_FILE"
})

_PrimaryWitness = tuple[tuple[tuple[int, int], ...], tuple[int, int, int, int, int] | None]


@dataclass(frozen=True, slots=True)
class _VerifiedCheckpoint:
    path: Path
    evidence: recovery.ProjectBytes
    primary_witness: _PrimaryWitness | None = None

    @property
    def is_backup(self) -> bool:
        return self.primary_witness is not None


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


def _primary_witness(primary: Path) -> _PrimaryWitness:
    from ..native_save_standard import _path_identity

    try:
        return _path_identity(primary)
    except BridgeError:
        raise recovery.EvidenceError("RECOVERY_FILE_OR_CONTEXT_CHANGED") from None


def _verify_with_backup(record: dict[str, Any], primary: Path, check: Callable[[], None],
                        *, require_backup: bool = False) -> _VerifiedCheckpoint:
    before = _primary_witness(primary)
    try:
        evidence = _verify(record, primary, check)
    except recovery.EvidenceError as primary_error:
        # A changing metadata signature during hashing is a live race, not
        # an established missing or replaced primary file.
        if primary_error.reason not in _PRIMARY_UNAVAILABLE or primary_error.facts:
            raise
        if _primary_witness(primary) != before:
            raise recovery.EvidenceError("RECOVERY_FILE_OR_CONTEXT_CHANGED") from None
        backup = primary.with_name(primary.name + "1")
        try:
            evidence = _verify(record, backup, check)
        except (recovery.EvidenceError, OSError):
            if require_backup:
                raise recovery.EvidenceError("RECOVERY_VERIFIED_BACKUP_UNAVAILABLE") from None
            raise primary_error from None
        return _VerifiedCheckpoint(backup, evidence, before)
    if require_backup:
        raise recovery.EvidenceError("RECOVERY_PRIMARY_AVAILABLE")
    return _VerifiedCheckpoint(primary, evidence)


def _still_verified(record: dict[str, Any], primary: Path, verified: _VerifiedCheckpoint) -> None:
    if (_approve(record["filepath"]) != primary
            or (verified.is_backup and _primary_witness(primary) != verified.primary_witness)
            or recovery.file_signature(verified.path) != verified.evidence.signature):
        raise recovery.EvidenceError("RECOVERY_FILE_OR_CONTEXT_CHANGED")


def _summary(record: dict[str, Any], verified: _VerifiedCheckpoint) -> dict[str, Any]:
    if verified.is_backup:
        return {**recovery.summarize(record, state="backup_available"),
                "recovery_source": "blender_backup", "recovery_filepath": str(verified.path),
                "save_as_required": True}
    return recovery.summarize(record)


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
        record, primary = _checkpoint()
        verified = _verify_with_backup(record, primary, check)
        context.require(*READ)
        _still_verified(record, primary, verified)
        if recovery.read_index() != record:
            raise recovery.EvidenceError("RECOVERY_INDEX_CHANGED")
        check()
    except recovery.EvidenceError as error:
        return recovery.unavailable(error.reason)
    except OSError:
        return recovery.unavailable("RECOVERY_EVIDENCE_UNREADABLE")
    return _summary(record, verified)


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
    use_backup = params.get("use_verified_backup", False)
    if (set(params) - {"checkpoint_id", "confirm_reopen", "use_verified_backup", "_task", "task_description"}
            or type(checkpoint_id) is not str or not recovery.CHECKPOINT_ID.fullmatch(checkpoint_id)
            or params.get("confirm_reopen") is not True or type(use_backup) is not bool):
        raise invalid_argument("Provide the current checkpoint_id and confirm_reopen=true. "
                               "If set, use_verified_backup must be a boolean.")
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
        record, primary = _checkpoint()
        if record["checkpoint_id"] != checkpoint_id:
            raise recovery.EvidenceError("RECOVERY_CHECKPOINT_CHANGED")
        verified = (_verify_with_backup(record, primary, check, require_backup=True) if use_backup
                    else _VerifiedCheckpoint(primary, _verify(record, primary, check)))
    except (recovery.EvidenceError, OSError) as error:
        reason = error.reason if isinstance(error, recovery.EvidenceError) else "RECOVERY_EVIDENCE_UNREADABLE"
        raise recovery.refusal(reason, "The saved checkpoint could not be verified for reopen.", reopened=False) from None

    path = verified.path

    def open_verified() -> set[str]:
        context.require(*WRITE)
        _require_clean_project(bpy, context)
        try:
            if bpy.data.filepath != loaded_path or recovery.read_index() != record:
                raise recovery.EvidenceError("RECOVERY_FILE_OR_CONTEXT_CHANGED")
            _still_verified(record, primary, verified)
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
            if recovery.file_signature(path) != verified.evidence.signature:
                raise recovery.EvidenceError("RECOVERY_FILE_CHANGED")
        except (recovery.EvidenceError, OSError):
            raise recovery.refusal("RECOVERY_FILE_CHANGED_DURING_OPEN",
                                   "Checkpoint bytes may have changed during Blender's open.",
                                   execution_started=True, verification_required=True) from None
        return result

    runtime.run_checkpoint_open(open_verified)
    source = ({"original_filepath": record["filepath"]} if verified.is_backup else {})
    return {**_summary(record, verified), **source, "reopened": True, "filepath": bpy.data.filepath,
            "auto_replayed": False, "previous_project_clean": True}


def register_tools(registry: ToolRegistry) -> None:
    registry.register(STATUS, checkpoint_status, permissions=READ,
                      description="Recheck the latest project checkpoint and look for a matching Blender backup if needed.")
    registry.register(REOPEN, checkpoint_reopen, permissions=WRITE, modifies=True,
                      automatic_checkpoint=False, exclusive_mutation=True, batchable=False,
                      description="Reopen the confirmed checkpoint or explicitly selected matching backup from a clean project.")
