"""Thread-safe runtime state and concise agent operation history."""

from __future__ import annotations

import threading
import uuid
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .entry_effects import bounded_entry_effects
from .native_save_policy import POLICY_VERSION


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bounded_single_effect(value: Any) -> dict[str, Any] | None:
    """Copy only bounded flat file-effect facts, never an arbitrary tool result.

    Invalid fields are omitted rather than coercing them into misleading proof.
    Reading known keys directly also avoids traversing unbounded nested values.
    """
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key in (
        "publication_attempted", "file_published", "publication_outcome_unknown",
        "published_bytes_verified", "native_undo_removes_external_file", "crash_durability_verified",
        "render_result_replaced", "render_result_replacement_possible",
    ):
        field = value.get(key)
        if type(field) is bool:
            result[key] = field
    for key, maximum in (("filepath", 4096), ("retained_staging_path", 4096),
                         ("staging_cleanup", 64), ("windows_directory_pin_acceptance", 64)):
        if key not in value:
            continue
        field = value[key]
        if field is None:
            result[key] = None
        elif isinstance(field, str) and len(field) <= maximum and not any(ord(c) < 32 for c in field):
            try:
                if len(field.encode("utf-8")) <= maximum:
                    result[key] = field
            except UnicodeError:
                pass
    digest = value.get("file_sha256")
    if "file_sha256" in value and (digest is None or (isinstance(digest, str)
            and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest))):
        result["file_sha256"] = digest
    size = value.get("file_bytes")
    if "file_bytes" in value and (size is None or (type(size) is int and 0 <= size <= 2**53 - 1)):
        result["file_bytes"] = size
    return result or None


MAX_EXTERNAL_ARTIFACTS = 4
SCENE_RECOVERY_KINDS = frozenset({"collection_allocation_attempt", "collection_allocation", "collection_removal_attempt",
                                  "world_allocation_attempt", "world_allocation", "embedded_world_graph_allocation"})


def _bounded_scene_recovery(value: Mapping[str, Any]) -> dict[str, Any] | None:
    count, restored, supplied = value.get("owned_write_attempts"), value.get("restoration_verified"), value.get("retained_effects")
    if type(count) is not int or not 0 <= count <= 64 or type(restored) is not bool or not isinstance(supplied, list):
        return None
    effects: list[dict[str, Any]] = []
    incomplete = value.get("retained_effects_incomplete") is True
    for item in supplied[:16]:
        if not isinstance(item, Mapping) or not isinstance(item.get("kind"), str) or item.get("kind") not in SCENE_RECOVERY_KINDS:
            incomplete = True
            continue
        effect: dict[str, Any] = {"kind": item["kind"]}
        key = "world" if item["kind"] == "embedded_world_graph_allocation" else "name"
        name = item.get(key)
        if isinstance(name, str) and name and len(name) <= 63 and not any(ord(char) < 32 for char in name):
            try:
                if len(name.encode("utf-8")) <= 63:
                    effect[key] = name
            except UnicodeError:
                pass
        incomplete = incomplete or key not in effect
        if item["kind"] == "collection_allocation":
            if type(item.get("linked")) is bool:
                effect["linked"] = item["linked"]
            else:
                incomplete = True
        if item["kind"] == "embedded_world_graph_allocation":
            if item.get("automatic_identity_restoration_available") is False:
                effect["automatic_identity_restoration_available"] = False
            else:
                incomplete = True
        effects.append(effect)
    return {"kind": "scene_mutation", "owned_write_attempts": count, "restoration_verified": restored,
            "retained_effects": effects, "retained_effects_truncated": len(supplied) > 16 or value.get("retained_effects_truncated") is True,
            "retained_effects_incomplete": bool(incomplete)}


def bounded_recovery_evidence(value: Any) -> dict[str, Any] | None:
    """Retain typed bounded recovery facts, separately from external file effects.

    A retained in-memory snapshot is not a saved project or an external backup.
    Unknown fields and invalid values never become recovery proof in history.
    """
    if not isinstance(value, Mapping):
        return None
    if value.get("kind") == "scene_mutation":
        return _bounded_scene_recovery(value)
    if value.get("kind") == "weight_mutation":
        return _bounded_weight_recovery(value)
    if value.get("kind") == "uv_mutation":
        return _bounded_uv_recovery(value)
    if value.get("kind") == "curve_mutation":
        return _bounded_curve_recovery(value)
    result: dict[str, Any] = {}
    mode = value.get("mode")
    if isinstance(mode, str) and mode in {"CURRENT_PIXELS_SNAPSHOT", "LOADED_BUFFER", "PACKED_RECONSTRUCTION"}:
        result["mode"] = mode
    for key in ("image_name", "snapshot_name", "retained_image_name"):
        field = value.get(key)
        if isinstance(field, str) and field and len(field) <= 63 and not any(ord(c) < 32 for c in field):
            try:
                if len(field.encode("utf-8")) <= 63:
                    result[key] = field
            except UnicodeError:
                pass
    for key in ("snapshot_retained", "project_saved", "source_file_read", "packed_payload_replaced",
                "complete_pixels_verified", "original_pixels_unchanged", "possible_mutation"):
        field = value.get(key)
        if type(field) is bool:
            result[key] = field
    for key in ("pixels_sha256_float32_le", "packed_sha256", "previous_packed_sha256"):
        if key not in value:
            continue
        field = value[key]
        if field is None or (isinstance(field, str) and len(field) == 64
                             and all(c in "0123456789abcdef" for c in field)):
            result[key] = field
    size = value.get("packed_bytes")
    if type(size) is int and 0 <= size <= 288 * 1024 * 1024:
        result["packed_bytes"] = size
    return result or None


def _bounded_weight_recovery(value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Copy a complete flat weight-write receipt; it grants no restore authority."""
    method, name, stage = value.get("method"), value.get("object_name"), value.get("stage")
    if (type(method) is not str or method not in {
            "weights.brush_stroke", "weights.mirror_geometric", "weights.transfer_surface",
            "weights.assign", "weights.normalize"}
            or type(stage) is not str or stage not in {
                "PREPARED", "FIELD_WRITE", "UPDATE", "RESTORE", "COMPLETE", "FAILED"}
            or type(name) is not str or not name or len(name) > 63 or any(ord(c) < 32 for c in name)):
        return None
    try:
        if len(name.encode("utf-8")) > 63:
            return None
    except UnicodeError:
        return None
    result: dict[str, Any] = {"kind": "weight_mutation", "method": method, "object_name": name, "stage": stage}
    direct = method in {"weights.assign", "weights.normalize"}
    if direct and stage == "UPDATE":
        return None
    for key in ("execution_started", "possible_mutation", "rollback_verified", "verification_required",
                "state_known", "retained_partial"):
        field = value.get(key)
        if type(field) is not bool:
            return None
        result[key] = field
    membership_limit, update_limit = (256, 0) if direct else (4096, 6)
    for key, maximum in (("owned_membership_attempts", membership_limit), ("owned_membership_verified", membership_limit),
                         ("restoration_attempts", membership_limit), ("restored_memberships", membership_limit),
                         ("native_update_attempts", update_limit), ("native_update_verified", update_limit)):
        field = value.get(key)
        if type(field) is not int or not 0 <= field <= maximum:
            return None
        result[key] = field
    refused = value.get("restoration_refused")
    if refused is not None and (type(refused) is not str or refused not in {
            "AUTHORITY_LOST", "STATE_CHANGED", "UNKNOWN_WRITE_RESULT", "INVALID_NATIVE_SCOPE"}):
        return None
    result["restoration_refused"] = refused
    for key in ("before_sha256", "expected_sha256", "observed_sha256"):
        field = value.get(key)
        if field is None and key == "observed_sha256":
            result[key] = None
        elif type(field) is str and len(field) == 64 and all(c in "0123456789abcdef" for c in field):
            result[key] = field
        else:
            return None
    if (result["owned_membership_verified"] > result["owned_membership_attempts"]
            or result["restored_memberships"] > result["restoration_attempts"]
            or result["native_update_verified"] > result["native_update_attempts"]
            or (result["state_known"] != (result["observed_sha256"] is not None))):
        return None
    if result["rollback_verified"] and (
            not result["state_known"] or result["observed_sha256"] != result["before_sha256"]
            or result["retained_partial"] or refused is not None):
        return None
    return result


def _bounded_uv_recovery(value: Any) -> dict[str, Any] | None:
    """Copy scalar UV recovery facts, never native handles or restore authority."""
    if (type(value) is not dict or len(value) > 64
            or any(type(key) is not str for key in value)):
        return None
    if (type(value.get("kind")) is not str or value["kind"] != "uv_mutation"
            or "observed_sha256" not in value or "restoration_refused" not in value):
        return None
    method, stage = value.get("method"), value.get("stage")
    if (type(method) is not str or method not in {"uv.coordinates_set", "uv.transform", "uv.pin"}
            or type(stage) is not str or stage not in {
                "PREPARED", "FIELD_WRITE", "UPDATE", "RESTORE", "COMPLETE", "FAILED"}):
        return None
    result: dict[str, Any] = {"kind": "uv_mutation", "method": method, "stage": stage}
    for key in ("object_name", "uv_layer"):
        field = value.get(key)
        if type(field) is not str or not field or len(field) > 63 or any(ord(c) < 32 for c in field):
            return None
        try:
            if len(field.encode("utf-8")) > 63:
                return None
        except UnicodeError:
            return None
        result[key] = field
    for key in ("object_session_uid", "mesh_session_uid", "object_pointer", "mesh_pointer"):
        field = value.get(key)
        if type(field) is not int or not 1 <= field <= 2**64 - 1:
            return None
        result[key] = field
    for key in ("execution_started", "possible_mutation", "rollback_verified", "verification_required",
                "state_known", "retained_partial"):
        field = value.get(key)
        if type(field) is not bool:
            return None
        result[key] = field
    for key, maximum in (("owned_field_attempts", 4096), ("owned_field_verified", 4096),
                         ("restoration_attempts", 4096), ("restored_fields", 4096),
                         ("native_update_attempts", 2), ("native_update_verified", 2)):
        field = value.get(key)
        if type(field) is not int or not 0 <= field <= maximum:
            return None
        result[key] = field
    refused = value.get("restoration_refused")
    if refused is not None and (type(refused) is not str or refused not in {
            "AUTHORITY_LOST", "STATE_CHANGED", "UNKNOWN_WRITE_RESULT", "INVALID_NATIVE_SCOPE",
            "SESSION_INVALIDATED"}):
        return None
    result["restoration_refused"] = refused
    for key in ("before_sha256", "expected_sha256", "observed_sha256"):
        field = value.get(key)
        if field is None and key == "observed_sha256":
            result[key] = None
        elif type(field) is str and len(field) == 64 and all(c in "0123456789abcdef" for c in field):
            result[key] = field
        else:
            return None
    if (result["owned_field_verified"] > result["owned_field_attempts"]
            or result["restored_fields"] > result["restoration_attempts"]
            or result["native_update_verified"] > result["native_update_attempts"]
            or (result["state_known"] != (result["observed_sha256"] is not None))):
        return None
    if result["rollback_verified"] and (
            not result["state_known"] or result["observed_sha256"] != result["before_sha256"]
            or result["retained_partial"] or refused is not None):
        return None
    return result


def _bounded_curve_recovery(value: Any) -> dict[str, Any] | None:
    """Retain bounded scalar curve observations, never prefixes or authority."""
    if (type(value) is not dict or len(value) > 64 or any(type(key) is not str for key in value)
            or type(value.get("kind")) is not str or value["kind"] != "curve_mutation"
            or type(value.get("method")) is not str or value["method"] != "animation.curve_edit"
            or "observed_sha256" not in value or "restoration_refused" not in value):
        return None
    stage = value.get("stage")
    if type(stage) is not str or stage not in {"PREPARED", "FIELD_WRITE", "UPDATE", "RESTORE", "COMPLETE", "FAILED"}:
        return None
    result: dict[str, Any] = {"kind": "curve_mutation", "method": value["method"], "stage": stage}
    for key, maximum in (("object_name", 63), ("action_name", 63), ("data_path", 2048)):
        field = value.get(key)
        if type(field) is not str or not field or len(field) > (512 if key == "data_path" else maximum) or any(ord(c) < 32 for c in field):
            return None
        try:
            if len(field.encode("utf-8")) > maximum:
                return None
        except UnicodeError:
            return None
        result[key] = field
    index = value.get("array_index")
    if type(index) is not int or not 0 <= index <= 16384:
        return None
    result["array_index"] = index
    for key in ("object_pointer", "object_session_uid", "action_pointer", "action_session_uid", "curve_pointer"):
        field = value.get(key)
        if type(field) is not int or not 1 <= field <= 2**64 - 1:
            return None
        result[key] = field
    for key in ("execution_started", "possible_mutation", "rollback_verified", "verification_required", "state_known", "retained_partial"):
        field = value.get(key)
        if type(field) is not bool:
            return None
        result[key] = field
    for key, maximum in (("owned_field_attempts", 1537), ("owned_field_verified", 1537),
                         ("restoration_attempts", 1537), ("restored_fields", 1537),
                         ("native_update_attempts", 2), ("native_update_verified", 2)):
        field = value.get(key)
        if type(field) is not int or not 0 <= field <= maximum:
            return None
        result[key] = field
    for key in ("before_sha256", "expected_sha256", "observed_sha256"):
        field = value.get(key)
        if key == "observed_sha256" and field is None:
            result[key] = None
        elif type(field) is str and len(field) == 64 and all(c in "0123456789abcdef" for c in field):
            result[key] = field
        else:
            return None
    refused = value["restoration_refused"]
    if refused is not None and (type(refused) is not str or refused not in {
            "AUTHORITY_LOST", "STATE_CHANGED", "UNKNOWN_WRITE_RESULT", "INVALID_NATIVE_SCOPE", "NATIVE_INTERRUPTED"}):
        return None
    result["restoration_refused"] = refused
    if (result["owned_field_verified"] > result["owned_field_attempts"]
            or result["restored_fields"] > result["restoration_attempts"]
            or result["native_update_verified"] > result["native_update_attempts"]
            or result["state_known"] != (result["observed_sha256"] is not None)):
        return None
    if result["rollback_verified"] and (not result["state_known"] or result["observed_sha256"] != result["before_sha256"]
                                       or result["retained_partial"] or refused is not None):
        return None
    return result



def _bounded_native_save(value: Any) -> dict[str, Any] | None:
    """Fixed native-save facts; callback destinations are deliberately unknown."""
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    incomplete = value.get("evidence_incomplete") is True
    for key, allowed in (("mode", {"COPY_NEW", "SAVE_CURRENT", "SAVE_AS"}),
                         ("policy_version", {POLICY_VERSION})):
        field = value.get(key)
        if type(field) is str and field in allowed:
            result[key] = field
        else:
            incomplete = True
    for key in ("native_save_invoked", "native_save_completed", "possible_native_effects",
                "native_external_effects_authorized", "declared_source_verified",
                "fresh_process_reopen_verified", "worker_reaped", "cleanup_outcome_unknown"):
        field = value.get(key)
        if type(field) is bool:
            result[key] = field
        else:
            incomplete = True
    if value.get("native_effect_inventory_complete") is False:
        result["native_effect_inventory_complete"] = False
    else:
        incomplete = True
    cleanup = value.get("reader_cleanup")
    if type(cleanup) is str and cleanup and len(cleanup) <= 64 and not any(ord(c) < 32 for c in cleanup):
        try:
            if len(cleanup.encode("utf8")) <= 64:
                result["reader_cleanup"] = cleanup
            else:
                incomplete = True
        except UnicodeError:
            incomplete = True
    else:
        incomplete = True
    for key in ("source_filepath_before", "source_filepath_after", "retained_reader_path"):
        if key not in value:
            incomplete = True
            continue
        field = value[key]
        if field is None:
            result[key] = None
        elif type(field) is str and len(field) <= 4096 and not any(ord(c) < 32 for c in field):
            try:
                if len(field.encode("utf8")) <= 4096:
                    result[key] = field
                else:
                    incomplete = True
            except UnicodeError:
                incomplete = True
        else:
            incomplete = True
    result["evidence_incomplete"] = incomplete
    return result


def bounded_external_effects(value: Any) -> dict[str, Any] | None:
    """Retain scalar effects and at most four flat managed-file descriptors.

    Optional additions preserve the existing V1 single-file representation.
    No nested caller collection is retained or recursively traversed. Missing
    bytes/hash information stays incomplete rather than becoming verified proof.
    """
    if not isinstance(value, Mapping):
        return None
    result = _bounded_single_effect(value) or {}
    if "native_save" in value:
        native_save = _bounded_native_save(value["native_save"])
        if native_save is not None:
            result["native_save"] = native_save
    supplied = value.get("artifacts")
    if isinstance(supplied, list):
        artifacts = []
        incomplete = value.get("artifacts_incomplete") is True
        for item in supplied[:MAX_EXTERNAL_ARTIFACTS]:
            if not isinstance(item, Mapping):
                incomplete = True
                continue
            parsed = _bounded_single_effect({key: item.get(key) for key in ("filepath", "file_sha256", "file_bytes")}) or {}
            if not parsed.get("filepath"):
                incomplete = True
                continue
            incomplete = incomplete or parsed.get("file_sha256") is None or parsed.get("file_bytes") is None
            artifacts.append(parsed)
        result.update(artifacts=artifacts, artifacts_truncated=(len(supplied) > MAX_EXTERNAL_ARTIFACTS
                      or value.get("artifacts_truncated") is True),
                      artifacts_incomplete=bool(incomplete))
    return result or None


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    tool: str
    timestamp: str
    description: str
    success: bool
    duration_ms: float
    affected_objects: tuple[str, ...] = ()
    error_code: str | None = None
    job_evidence: dict[str, Any] | None = None
    external_effects: dict[str, Any] | None = None
    recovery_evidence: dict[str, Any] | None = None
    entry_effects: dict[str, bool] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["affected_objects"] = list(self.affected_objects)
        if self.entry_effects is None:
            value.pop("entry_effects")
        return value


class BridgeState:
    """Mutable runtime state protected for network/UI access."""

    def __init__(self, *, history_limit: int = 50) -> None:
        self._lock = threading.RLock()
        self._history: deque[OperationRecord] = deque(maxlen=history_limit)
        self.server_running = False
        self.host = "127.0.0.1"
        self.port = 9876
        self.connected_clients = 0
        self.paused = False
        self.emergency_stopped = False
        self.current_task = ""
        self.current_method = ""
        self.is_executing = False
        self.last_error = ""

    def set_server(self, running: bool, host: str | None = None, port: int | None = None) -> None:
        with self._lock:
            self.server_running = running
            if host is not None:
                self.host = host
            if port is not None:
                self.port = port
            if not running:
                self.connected_clients = 0

    def client_connected(self) -> None:
        with self._lock:
            self.connected_clients += 1

    def client_disconnected(self) -> None:
        with self._lock:
            self.connected_clients = max(0, self.connected_clients - 1)

    def begin_execution(self, method: str, task: str | None = None) -> None:
        with self._lock:
            self.current_method = method
            self.is_executing = True
            if task is not None:
                self.current_task = task[:500]

    def end_execution(self, error: str = "") -> None:
        with self._lock:
            self.current_method = ""
            self.is_executing = False
            self.last_error = error[:500]

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self.paused = bool(paused)

    def set_emergency_stopped(self, stopped: bool) -> None:
        with self._lock:
            self.emergency_stopped = bool(stopped)
            if stopped:
                self.paused = True
                self.current_method = ""
                self.is_executing = False

    def set_task(self, description: str) -> None:
        with self._lock:
            self.current_task = description[:500]

    def record_operation(
        self,
        *,
        tool: str,
        description: str,
        success: bool,
        duration_ms: float,
        affected_objects: Iterable[str] = (),
        error_code: str | None = None,
        job_evidence: dict[str, Any] | None = None,
        external_effects: Mapping[str, Any] | None = None,
        recovery_evidence: Mapping[str, Any] | None = None,
        entry_effects: Mapping[str, Any] | None = None,
    ) -> OperationRecord:
        record = OperationRecord(
            operation_id=f"op_{uuid.uuid4().hex[:10]}",
            tool=tool,
            timestamp=_now(),
            description=description[:240],
            success=success,
            duration_ms=round(duration_ms, 3),
            affected_objects=tuple(dict.fromkeys(str(name) for name in affected_objects if name)),
            error_code=error_code,
            job_evidence=job_evidence,
            external_effects=bounded_external_effects(external_effects),
            recovery_evidence=bounded_recovery_evidence(recovery_evidence),
            entry_effects=bounded_entry_effects(entry_effects),
        )
        with self._lock:
            self._history.appendleft(record)
        return record

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [record.to_dict() for record in list(self._history)[: max(0, limit)]]

    def clear_history(self) -> int:
        """Clear the local audit display and return the removed record count."""

        with self._lock:
            count = len(self._history)
            self._history.clear()
            return count

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self.connected_clients:
                connection_status = "connected"
            elif self.server_running:
                connection_status = "listening"
            else:
                connection_status = "disconnected"
            return {
                "server_running": self.server_running,
                "connection_status": connection_status,
                "host": self.host,
                "port": self.port,
                "connected_clients": self.connected_clients,
                "paused": self.paused,
                "emergency_stopped": self.emergency_stopped,
                "current_task": self.current_task,
                "current_method": self.current_method,
                "is_executing": self.is_executing,
                "last_error": self.last_error,
            }

    def reset(self) -> None:
        from .task_plans import clear_task_plans

        with self._lock:
            self.server_running = False
            self.connected_clients = 0
            self.paused = False
            self.emergency_stopped = False
            self.current_task = ""
            self.current_method = ""
            self.is_executing = False
            self.last_error = ""
            self._history.clear()
            clear_task_plans(self)


_STATE = BridgeState()


def get_state() -> BridgeState:
    return _STATE
