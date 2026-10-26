"""Pure bounded contracts for the finite current-pixel Image lifecycle.

These plain observations never grant recovery or file/Blender authority. Native
origins, current permissions, complete comparisons and effects belong to the
domain driver. This module does not probe files, Blender, clocks or providers.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePath
from typing import Any

from .errors import BridgeError, ErrorCode, invalid_argument

PROFILE = "FILE_F32_EXR_DATA_CURRENT_PIXELS_V1"
KIND = "current_pixels_lifecycle"
MAX_DIMENSION = 4096
MAX_PIXELS = 16_777_216
MAX_PAYLOAD_BYTES = 269_484_032
MAX_MANIFEST_BYTES = 65_536
MAX_JOURNAL_BYTES = 65_536
MAX_JOURNAL_EVENTS = 64
MAX_RECEIPT_BYTES = 8192
MAX_OWNED_WRITE_ATTEMPTS = 8
MAX_IO_BLOCK_BYTES = 1_048_576
MAX_EXTERNAL_ARTIFACTS = 4
METHOD_MODES = {
    "image.pack_current_pixels_job_start": "CURRENT_PIXELS_PACK",
    "image.restore_current_pixels_job_start": "CURRENT_PIXELS_RESTORE",
}
PACK_PREVIEW = "image.current_pixels_pack_preview"
RECOVERY_PREVIEW = "image.current_pixels_recovery_preview"
PACK_START, RESTORE_START = tuple(METHOD_MODES)
FORWARD_STAGES = (
    "PREPARED", "BACKUPS_PARTIAL", "BACKUPS_DURABLE", "HELPER_RECORD_ATTEMPT",
    "HELPER_RECORD_VERIFIED", "PACK_ATTEMPT", "PACKED_BYTES_VERIFIED",
    "BUFFER_DISCARD_ATTEMPT", "PACKED_BUFFER_DISCARDED", "FORWARD_COMPLETE",
)
RESTORE_STAGES = (
    "PREPARED", "RESTORE_PREVIOUS_PACK_ATTEMPT", "RESTORE_PREVIOUS_PACK_VERIFIED",
    "RESTORE_EDITED_PIXELS_ATTEMPT", "RESTORED_COMPLETE", "ALREADY_AT_BACKED_UP_STATE",
)
# Each attempted/verified boundary must be recorded before the next one. The
# backed-up no-op is a separate PREPARED branch, never a post-restore advance.
_PREFIX_ADVANCES = {
    PACK_START: {
        "PREPARED": "BACKUPS_PARTIAL",
        "BACKUPS_PARTIAL": "BACKUPS_DURABLE",
        "BACKUPS_DURABLE": "HELPER_RECORD_ATTEMPT",
        "HELPER_RECORD_ATTEMPT": "HELPER_RECORD_VERIFIED",
        "HELPER_RECORD_VERIFIED": "PACK_ATTEMPT",
        "PACK_ATTEMPT": "PACKED_BYTES_VERIFIED",
        "PACKED_BYTES_VERIFIED": "BUFFER_DISCARD_ATTEMPT",
        "BUFFER_DISCARD_ATTEMPT": "PACKED_BUFFER_DISCARDED",
        "PACKED_BUFFER_DISCARDED": "FORWARD_COMPLETE",
    },
    RESTORE_START: {
        "PREPARED": "RESTORE_PREVIOUS_PACK_ATTEMPT",
        "RESTORE_PREVIOUS_PACK_ATTEMPT": "RESTORE_PREVIOUS_PACK_VERIFIED",
        "RESTORE_PREVIOUS_PACK_VERIFIED": "RESTORE_EDITED_PIXELS_ATTEMPT",
        "RESTORE_EDITED_PIXELS_ATTEMPT": "RESTORED_COMPLETE",
    },
}
STAGES = frozenset((*FORWARD_STAGES, *RESTORE_STAGES, "UNKNOWN"))
IDENTITY_MODES = frozenset({"SAME_SESSION_NATIVE_IDS", "SAVED_NATIVE_OWNER_GRAPH", "UNAVAILABLE"})
ATTEMPT_FLAGS = ("external_write_attempted", "helper_record_write_attempted", "image_write_attempted")
_HEX = re.compile(r"^[0-9a-f]+$")
_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
_DECIMAL = re.compile(r"^[0-9]{1,20}$")
_REQUIRED_RECEIPT = frozenset({
    "kind", "schema_version", "method", "mode", "profile", "stage", "identity_mode",
    *ATTEMPT_FLAGS, "state_known", "possible_mutation", "verification_required", "recovery_authorized",
    "project_saved", "source_file_read", "automatic_inverse_attempted",
})
_BOOL_FACTS = frozenset({
    *ATTEMPT_FLAGS, "state_known", "possible_mutation", "verification_required", "recovery_authorized",
    "durable_backups_verified", "packed_bytes_verified", "complete_pixels_verified", "snapshot_retained",
    "project_saved", "source_file_read", "automatic_inverse_attempted",
})
_DIGEST_FIELDS = frozenset({
    "expected_target_fingerprint", "manifest_sha256", "expected_prefix_sha256", "observed_prefix_sha256",
    "current_pixels_sha256_float32_le", "previous_packed_sha256", "current_packed_sha256",
    "consumer_graph_sha256", "previous_decoded_pixels_sha256",
})
_OPTIONAL_RECEIPT = frozenset({
    *_BOOL_FACTS, *_DIGEST_FIELDS, "image_name", "snapshot_name", "record_uuid", "runtime_nonce",
    "same_session_original_pointer", "same_session_original_uid", "owned_write_attempts", "packed_bytes",
    "observed_prefix",
})


def _fail(message: str) -> BridgeError:
    return invalid_argument("Current-pixel contract: " + message)


def _text(value: Any, label: str, maximum: int, *, blank: bool = False) -> str:
    if type(value) is not str or len(value) > maximum or (not blank and not value.strip()):
        raise _fail(label + " must be bounded nonblank exact text.")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as cause:
        raise _fail(label + " must be valid UTF-8.") from cause
    if size > maximum or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _fail(label + " exceeds its UTF-8/control-character contract.")
    return value


def _hex(value: Any, label: str, length: int, *, maximum: bool = False) -> str:
    if (type(value) is not str or not (1 <= len(value) <= length if maximum else len(value) == length)
            or _HEX.fullmatch(value) is None):
        raise _fail(label + " must be lowercase hexadecimal text of the declared size.")
    return value


def _int(value: Any, label: str, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _fail(label + " must be an exact integer within its declared budget.")
    return value


def _object(value: Any, label: str, allowed: set[str] | frozenset[str], required: set[str] | frozenset[str]) -> dict:
    if (type(value) is not dict or len(value) > len(allowed) or any(type(key) is not str for key in value)
            or not required.issubset(value) or not value.keys() <= allowed):
        raise _fail(label + " has unknown keys, missing fields or a non-plain shape.")
    return value


def _materials(value: Any) -> list[str]:
    if type(value) is not list or not 1 <= len(value) <= 2:
        raise _fail("affected_materials needs one or two explicit names.")
    names = [_text(item, "Material name", 63) for item in value]
    if len(set(names)) != len(names):
        raise _fail("affected_materials cannot contain duplicate names.")
    return names


def _path_text(value: Any, label: str) -> str:
    # Lexical only. The approved-parent helper decides actual local paths after
    # current grants; this validator does not resolve or probe a path.
    raw = _text(value, label, 4096)
    path = PurePath(raw)
    if raw.startswith(("//", "\\\\")) or not path.is_absolute() or ".." in path.parts:
        raise _fail(label + " must be an explicit absolute local path without traversal.")
    return raw


def validate_request(method: Any, params: Any) -> dict[str, Any]:
    """Validate the exact four typed shapes without invoking any provider."""
    if type(method) is not str or method not in {PACK_PREVIEW, RECOVERY_PREVIEW, *METHOD_MODES}:
        raise _fail("unknown lifecycle method.")
    pack = method in {PACK_PREVIEW, PACK_START}
    required = ({"image_name", "snapshot_name", "affected_materials", "backup_directory", "backup_prefix"}
                if pack else {"snapshot_name", "backup_manifest_path", "affected_materials"})
    allowed = set(required)
    if pack:
        allowed.add("retain_event_journal")
    if method in METHOD_MODES:
        expected = "expected_target_fingerprint" if pack else "expected_recovery_fingerprint"
        confirmations = ({"confirm_replace_packed_bytes", "confirm_discard_current_buffer"} if pack else
                         {"confirm_restore_previous_packed_bytes", "confirm_restore_original_current_pixels"})
        required |= {expected, *confirmations}
        allowed |= {expected, *confirmations, "time_limit_seconds"}
    value = _object(params, "request", allowed, required)
    result = {key: _text(value[key], key, 63) for key in ("image_name", "snapshot_name") if key in value}
    result["affected_materials"] = _materials(value["affected_materials"])
    if pack:
        result["backup_directory"] = _path_text(value["backup_directory"], "backup_directory")
        prefix = value["backup_prefix"]
        if type(prefix) is not str or _PREFIX.fullmatch(prefix) is None:
            raise _fail("backup_prefix must be one to 48 reviewed ASCII filename characters.")
        result["backup_prefix"] = prefix
        journal = value.get("retain_event_journal", True)
        if type(journal) is not bool:
            raise _fail("retain_event_journal must be an exact Boolean.")
        result["retain_event_journal"] = journal
    else:
        result["backup_manifest_path"] = _path_text(value["backup_manifest_path"], "backup_manifest_path")
    if method in METHOD_MODES:
        result[expected] = _hex(value[expected], expected, 64)
        for key in confirmations:
            if value[key] is not True:
                raise _fail(key + " requires explicit true confirmation.")
            result[key] = True
        deadline = value.get("time_limit_seconds", 300)
        if type(deadline) not in {int, float} or not 1 <= deadline <= 300 or not math.isfinite(deadline):
            raise _fail("time_limit_seconds must be finite and from one through 300.")
        result["time_limit_seconds"] = deadline
    return result


def validate_receipt(value: Any) -> dict[str, Any]:
    """Copy a strict recognized receipt or raise; malformed proof is never None.

    Optional known-prefix fields are omitted together or give a coherent complete
    comparison. Unknown current state can retain the last expected digest, but
    cannot describe a current observed prefix as known.
    """
    value = _object(value, "receipt", _REQUIRED_RECEIPT | _OPTIONAL_RECEIPT, _REQUIRED_RECEIPT)
    if (type(value["kind"]) is not str or value["kind"] != KIND or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or type(value["method"]) is not str or value["method"] not in METHOD_MODES
            or type(value["mode"]) is not str or value["mode"] != METHOD_MODES[value["method"]]
            or type(value["profile"]) is not str or value["profile"] != PROFILE
            or type(value["stage"]) is not str or value["stage"] not in STAGES
            or type(value["identity_mode"]) is not str or value["identity_mode"] not in IDENTITY_MODES):
        raise _fail("receipt kind/schema/method/mode/profile/stage/identity is unsupported.")
    result = dict(value)
    for key in _BOOL_FACTS & value.keys():
        if type(value[key]) is not bool:
            raise _fail(key + " must be an exact Boolean.")
    if (value["verification_required"] is not True or value["recovery_authorized"] is not False
            or any(value[key] is not False for key in ("project_saved", "source_file_read", "automatic_inverse_attempted"))):
        raise _fail("receipts cannot claim recovery authority, project save, source reads or automatic inverse.")
    for key in _DIGEST_FIELDS & value.keys():
        if value[key] is not None:
            _hex(value[key], key, 64)
    for key in ("image_name", "snapshot_name"):
        if key in value:
            _text(value[key], key, 63)
    for key in ("record_uuid", "runtime_nonce"):
        if key in value:
            _hex(value[key], key, 32)
    if "same_session_original_pointer" in value:
        _hex(value["same_session_original_pointer"], "same_session_original_pointer", 16, maximum=True)
    if "same_session_original_uid" in value and (type(value["same_session_original_uid"]) is not str
                                               or _DECIMAL.fullmatch(value["same_session_original_uid"]) is None):
        raise _fail("same_session_original_uid must be at most 20 diagnostic decimal digits.")
    if "owned_write_attempts" in value:
        count = _int(value["owned_write_attempts"], "owned_write_attempts", MAX_OWNED_WRITE_ATTEMPTS)
        if count < sum(value[key] for key in ATTEMPT_FLAGS):
            raise _fail("owned_write_attempts cannot contradict the attempted boundary flags.")
    if "packed_bytes" in value:
        _int(value["packed_bytes"], "packed_bytes", MAX_PAYLOAD_BYTES)
    if "observed_prefix" in value and value["observed_prefix"] is not None and (
            type(value["observed_prefix"]) is not str or value["observed_prefix"] not in STAGES - {"UNKNOWN"}):
        raise _fail("observed_prefix must be a known stage or null.")
    observed = {"observed_prefix", "expected_prefix_sha256", "observed_prefix_sha256"}
    if (value["state_known"] and observed & value.keys()
            and (not observed.issubset(value) or value["observed_prefix"] is None
                 or value["expected_prefix_sha256"] is None
                 or value["expected_prefix_sha256"] != value["observed_prefix_sha256"])):
        raise _fail("known observed-prefix facts must give a complete matching comparison.")
    if not value["state_known"] and any(value.get(key) is not None for key in ("observed_prefix", "observed_prefix_sha256")):
        raise _fail("unknown current state cannot claim an observed current prefix.")
    if any(value[key] for key in ATTEMPT_FLAGS) and not value["possible_mutation"]:
        raise _fail("attempted effects must remain possible mutations.")
    stage, pack = value["stage"], value["method"] == PACK_START
    allowed = FORWARD_STAGES if pack else RESTORE_STAGES
    if stage != "UNKNOWN" and stage not in allowed:
        raise _fail("stage does not belong to this method.")
    if stage == "UNKNOWN" and value["state_known"]:
        raise _fail("UNKNOWN cannot be a known current state.")
    if value["identity_mode"] == "UNAVAILABLE" and value["state_known"]:
        raise _fail("a known current target requires an available native identity mode.")
    durable = value.get("durable_backups_verified") is True
    if pack:
        index = FORWARD_STAGES.index(stage) if stage in FORWARD_STAGES else None
        if value["helper_record_write_attempted"] and (not value["external_write_attempted"] or not durable):
            raise _fail("helper writes require durable external backups.")
        if value["image_write_attempted"] and not value["helper_record_write_attempted"]:
            raise _fail("forward Image writes require an attempted helper record.")
        if index is not None:
            if index == 1 and not value["external_write_attempted"]:
                raise _fail("partial backups require a recorded external write attempt.")
            if index >= 2 and (not durable or not value["external_write_attempted"]):
                raise _fail("this forward prefix requires durable backups and an external attempt.")
            if (index < 3 and value["helper_record_write_attempted"]) or (index >= 3 and not value["helper_record_write_attempted"]):
                raise _fail("helper attempt flag contradicts the forward stage.")
            if (index < 5 and value["image_write_attempted"]) or (index >= 5 and not value["image_write_attempted"]):
                raise _fail("Image attempt flag contradicts the forward stage.")
            if index >= 6 and value.get("packed_bytes_verified") is not True:
                raise _fail("the packed prefix requires complete packed-byte verification.")
    else:
        if value["helper_record_write_attempted"]:
            raise _fail("recovery never rewrites the retained helper record.")
        if stage not in {"PREPARED", "ALREADY_AT_BACKED_UP_STATE", "UNKNOWN"} and (
                not value["image_write_attempted"] or not durable):
            raise _fail("reverse native prefixes require a recorded Image attempt and durable backups.")
        if stage == "ALREADY_AT_BACKED_UP_STATE" and value["image_write_attempted"]:
            raise _fail("already-at-backed-up-state is an Image no-op.")
        if stage == "PREPARED" and value["image_write_attempted"]:
            raise _fail("a prepared recovery has not attempted an Image write.")
        if stage == "ALREADY_AT_BACKED_UP_STATE" and (not durable or value.get("packed_bytes_verified") is not True):
            raise _fail("the complete backed-up no-op requires verified backups and packed bytes.")
        if stage in {"RESTORE_PREVIOUS_PACK_VERIFIED", "RESTORE_EDITED_PIXELS_ATTEMPT", "RESTORED_COMPLETE"} and value.get("packed_bytes_verified") is not True:
            raise _fail("reverse prefixes require verified previous packed bytes.")
        if value["image_write_attempted"] and value.get("previous_decoded_pixels_sha256") is None:
            raise _fail("native old-payload decode requires the prior decoded-pixel digest.")
    if stage in {"FORWARD_COMPLETE", "RESTORED_COMPLETE", "ALREADY_AT_BACKED_UP_STATE"} and (
            not value["state_known"] or value.get("complete_pixels_verified") is not True):
        raise _fail("complete prefixes require a known complete-pixel observation.")
    if len(_canonical(result)) > MAX_RECEIPT_BYTES:
        raise _fail("receipt exceeds eight KiB.")
    return result


def unknown_observation(value: Any) -> dict[str, Any]:
    """Retain bounded historical facts while refusing a current-state claim."""
    receipt = validate_receipt(value)
    return validate_receipt({**receipt, "stage": "UNKNOWN", "state_known": False,
                             "observed_prefix": None, "observed_prefix_sha256": None})


def prefix_receipt(previous: Any, stage: str, **facts: Any) -> dict[str, Any]:
    """Advance plain facts without clearing attempts or replacing immutable IDs."""
    before = validate_receipt(previous)
    if "stage" in facts:
        raise _fail("the prefix stage is supplied separately.")
    updated = validate_receipt({**before, **facts, "stage": stage})
    if any(key in facts and updated[key] != before[key] for key in (
            "kind", "schema_version", "method", "mode", "profile", "identity_mode")):
        raise _fail("prefix updates cannot replace the receipt identity or stage argument.")
    allowed = {before["stage"], "UNKNOWN", _PREFIX_ADVANCES[before["method"]].get(before["stage"])}
    if before["method"] == RESTORE_START and before["stage"] == "PREPARED":
        allowed.add("ALREADY_AT_BACKED_UP_STATE")
    if stage not in allowed:
        raise _fail("prefix transitions must record every attempted and verified boundary in order.")
    if any(before[key] and updated[key] is not True for key in ATTEMPT_FLAGS):
        raise _fail("attempt flags are monotonic.")
    if before.get("owned_write_attempts", 0) > updated.get("owned_write_attempts", 0):
        raise _fail("owned write attempt counts are monotonic.")
    for key in ("record_uuid", "runtime_nonce", "image_name", "snapshot_name", "expected_target_fingerprint",
                "same_session_original_pointer", "same_session_original_uid", "previous_packed_sha256",
                "previous_decoded_pixels_sha256", "current_pixels_sha256_float32_le",
                "manifest_sha256", "consumer_graph_sha256"):
        if key in before and updated.get(key) != before[key]:
            raise _fail("prefix updates cannot replace the original scope identity.")
    return validate_receipt(updated)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _metadata(value: Any) -> dict[str, Any]:
    """Copy only literal Image settings needed by the admitted domain projection.

    Optional fields are not defaults: a driver requiring one for complete CAS
    must require it at admission. Missing metadata never establishes ownership.
    """
    fixed = {"source": "FILE", "file_format": "OPEN_EXR", "colorspace": "Non-Color", "alpha_mode": "CHANNEL_PACKED"}
    flags = {"is_dirty", "has_data", "use_fake_user", "record_present"}
    digests = {"record_sha256", "manifest_sha256"}
    paths = {"filepath", "filepath_raw"}
    allowed = set(fixed) | flags | digests | paths | {"channels", "snapshot_schema_version", "record_uuid", "owner_image_name"}
    value = _object(value, "Image metadata", allowed, set())
    result: dict[str, Any] = {}
    for key, field in value.items():
        if key in fixed:
            if type(field) is not str or field != fixed[key]:
                raise _fail("Image metadata role does not match the finite profile.")
            result[key] = field
        elif key in flags:
            if type(field) is not bool:
                raise _fail("Image metadata flags must be exact Booleans.")
            result[key] = field
        elif key in digests:
            result[key] = _hex(field, key, 64)
        elif key in paths:
            result[key] = _text(field, key, 4096, blank=True)
        elif key == "channels":
            result[key] = _int(field, key, 4, 4)
        elif key == "snapshot_schema_version":
            result[key] = _int(field, key, 1, 1)
        elif key == "record_uuid":
            result[key] = _hex(field, key, 32)
        else:
            result[key] = _text(field, key, 63)
    if len(_canonical(result)) > 4096:
        raise _fail("individual Image metadata exceeds four KiB.")
    return result


def _identity(value: Any) -> dict[str, str]:
    value = _object(value, "native identity", {"pointer", "session_uid"}, {"pointer", "session_uid"})
    pointer = _hex(value["pointer"], "native diagnostic pointer", 16, maximum=True)
    uid = value["session_uid"]
    if type(uid) is not str or _DECIMAL.fullmatch(uid) is None:
        raise _fail("native diagnostic session UID must be at most 20 decimal digits.")
    return {"pointer": pointer, "session_uid": uid}


def _rows(value: Any, *, native: bool) -> list[dict[str, Any]]:
    if type(value) is not list or not 1 <= len(value) <= 16:
        raise _fail("manifest identity rows need one through 16 complete ID rows.")
    keys = {"kind", "name", "content_sha256"} | ({"pointer", "session_uid"} if native else set())
    result, identities = [], set()
    for row in value:
        row = _object(row, "manifest ID row", keys, keys)
        if type(row["kind"]) is not str or row["kind"] not in {"Image", "Material", "Object", "Mesh", "NodeTree"}:
            raise _fail("manifest ID row kind is unsupported.")
        name = _text(row["name"], "ID name", 63)
        if (row["kind"], name) in identities:
            raise _fail("manifest ID rows must be unique by kind and exact name.")
        identities.add((row["kind"], name))
        copy = {"kind": row["kind"], "name": name, "content_sha256": _hex(row["content_sha256"], "ID content digest", 64)}
        if native:
            copy.update(_identity({"pointer": row["pointer"], "session_uid": row["session_uid"]}))
        result.append(copy)
    return result


def validate_manifest(value: Any) -> dict[str, Any]:
    """Validate canonical backup metadata, not ownership or restore permission."""
    required = {
        "kind", "schema_version", "profile", "record_uuid", "runtime_nonce", "image_name", "snapshot_name",
        "width", "height", "affected_materials", "backup_prefix", "current_pixels_sha256_float32_le",
        "previous_packed_sha256", "previous_decoded_pixels_sha256", "native_graph_sha256", "portable_graph_sha256",
        "original_identity", "snapshot_identity", "roles", "native_identity_rows", "portable_identity_rows", "backups",
    }
    value = _object(value, "manifest", required | {"image_metadata", "snapshot_metadata"}, required)
    if (type(value["kind"]) is not str or value["kind"] != "current_pixels_manifest"
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or type(value["profile"]) is not str or value["profile"] != PROFILE):
        raise _fail("manifest kind/schema/profile is unsupported.")
    result = {key: value[key] for key in ("kind", "schema_version", "profile")}
    for key in ("record_uuid", "runtime_nonce"):
        result[key] = _hex(value[key], key, 32)
    for key in ("image_name", "snapshot_name"):
        result[key] = _text(value[key], key, 63)
    if result["image_name"] == result["snapshot_name"]:
        raise _fail("original and snapshot names must identify distinct Images.")
    workload = resource_requirements(value["width"], value["height"])
    result.update(width=workload["width"], height=workload["height"], affected_materials=_materials(value["affected_materials"]))
    prefix = value["backup_prefix"]
    if type(prefix) is not str or _PREFIX.fullmatch(prefix) is None:
        raise _fail("manifest backup_prefix is invalid.")
    result["backup_prefix"] = prefix
    for key in ("current_pixels_sha256_float32_le", "previous_packed_sha256", "previous_decoded_pixels_sha256", "native_graph_sha256", "portable_graph_sha256"):
        result[key] = _hex(value[key], key, 64)
    for key in ("original_identity", "snapshot_identity"):
        result[key] = _identity(value[key])
    if result["original_identity"] == result["snapshot_identity"]:
        raise _fail("manifest original and snapshot native identities must be distinct.")
    roles = {"source": "FILE", "file_format": "OPEN_EXR", "colorspace": "Non-Color", "alpha_mode": "CHANNEL_PACKED", "is_float": True}
    role_input = _object(value["roles"], "manifest roles", set(roles), set(roles))
    if any(type(role_input[key]) is not type(expected) or role_input[key] != expected for key, expected in roles.items()):
        raise _fail("manifest roles are outside the finite Float32 DATA profile.")
    result["roles"] = roles
    result["native_identity_rows"] = _rows(value["native_identity_rows"], native=True)
    result["portable_identity_rows"] = _rows(value["portable_identity_rows"], native=False)
    native_rows = [{key: field for key, field in row.items() if key not in {"pointer", "session_uid"}} for row in result["native_identity_rows"]]
    if native_rows != result["portable_identity_rows"]:
        raise _fail("portable rows must omit only native tokens from the same ID projection.")
    by_name = {(row["kind"], row["name"]): row for row in result["native_identity_rows"]}
    for name, identity in ((result["image_name"], result["original_identity"]),
                           (result["snapshot_name"], result["snapshot_identity"])):
        row = by_name.get(("Image", name))
        if row is None or any(row[key] != identity[key] for key in ("pointer", "session_uid")):
            raise _fail("native ID rows must bind both declared original and helper identities.")
    if any(("Material", name) not in by_name for name in result["affected_materials"]):
        raise _fail("ID rows must include every declared affected Material.")
    backups = _object(value["backups"], "manifest backups", {"oldpacked", "current"}, {"oldpacked", "current"})
    result["backups"] = {}
    for key, suffix in (("oldpacked", ".oldpacked.bin"), ("current", ".current.exr")):
        backup = _object(backups[key], "backup descriptor", {"filename", "bytes", "sha256"}, {"filename", "bytes", "sha256"})
        if type(backup["filename"]) is not str or backup["filename"] != prefix + suffix:
            raise _fail("manifest backups must use the exact approved-parent sibling names.")
        result["backups"][key] = {"filename": backup["filename"], "bytes": _int(backup["bytes"], "backup bytes", MAX_PAYLOAD_BYTES, 1),
                                   "sha256": _hex(backup["sha256"], "backup digest", 64)}
    if result["backups"]["oldpacked"]["sha256"] != result["previous_packed_sha256"]:
        raise _fail("oldpacked descriptor must bind the previous complete packed payload.")
    for key in ("image_metadata", "snapshot_metadata"):
        if key in value:
            result[key] = _metadata(value[key])
    if len(_canonical(result)) > MAX_MANIFEST_BYTES:
        raise _fail("manifest exceeds 64 KiB.")
    return result


def canonical_manifest(value: Any) -> bytes:
    return _canonical(validate_manifest(value))


def parse_manifest(payload: Any) -> dict[str, Any]:
    """Parse bounded canonical bytes; no filename is opened by this function."""
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_MANIFEST_BYTES:
        raise _fail("manifest payload must be one through 64 KiB of canonical bytes.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise _fail("manifest contains duplicate JSON keys.")
            result[key] = value
        return result

    def constant(_value):
        raise _fail("manifest contains a nonfinite JSON value.")

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        result = validate_manifest(value)
        if _canonical(result) != payload:
            raise _fail("manifest bytes are not the canonical representation.")
        return result
    except (UnicodeError, ValueError, RecursionError) as cause:
        raise _fail("manifest JSON is invalid or exceeds bounded parsing.") from cause


def manifest_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_manifest(value)).hexdigest()


def recovery_classification(*, target_loaded: Any, snapshot_loaded: Any, owner_verified: Any,
                            state_matches_forward: Any, state_matches_backup: Any) -> str:
    """Classify independently measured facts; the answer authorizes no mutation."""
    facts = (target_loaded, snapshot_loaded, owner_verified, state_matches_forward, state_matches_backup)
    if any(type(value) is not bool for value in facts):
        raise _fail("recovery classification requires exact measured Boolean facts.")
    reason = None
    if not target_loaded or not snapshot_loaded:
        reason = "TARGET_BUFFER_UNLOADED"
    elif not owner_verified:
        reason = "NATIVE_OWNER_UNVERIFIED"
    elif state_matches_forward and state_matches_backup:
        reason = "AMBIGUOUS_COMPLETE_STATE"
    elif state_matches_forward:
        return "FORWARD_COMPLETE"
    elif state_matches_backup:
        return "ALREADY_AT_BACKED_UP_STATE"
    else:
        reason = "PARTIAL_OR_UNKNOWN_STATE"
    raise BridgeError(ErrorCode.OPERATION_FAILED, "Current-pixel recovery is inspection-only for this state.",
                      {"reason": reason, "inspection_only": True, "recovery_authorized": False})


def resource_requirements(width: Any, height: Any) -> dict[str, Any]:
    width, height = _int(width, "width", MAX_DIMENSION, 1), _int(height, "height", MAX_DIMENSION, 1)
    pixels = width * height
    if pixels > MAX_PIXELS:
        raise _fail("pixel count exceeds the finite profile.")
    large = pixels > 1_048_576
    return {"width": width, "height": height, "pixels": pixels, "large_workload": large,
            "required_available_memory_bytes": (8 * 1024**3 if large else 512 * 1024**2),
            "required_available_disk_bytes": (2 * 1024**3 if large else 64 * 1024**2),
            "resources_reserved": False}


def validate_resource_facts(width: Any, height: Any, available_memory_bytes: Any,
                            available_disk_bytes: Any) -> dict[str, Any]:
    facts = resource_requirements(width, height)
    facts["available_memory_bytes"] = _int(available_memory_bytes, "available_memory_bytes", 2**63 - 1)
    facts["available_disk_bytes"] = _int(available_disk_bytes, "available_disk_bytes", 2**63 - 1)
    facts["admitted"] = (available_memory_bytes >= facts["required_available_memory_bytes"]
                         and available_disk_bytes >= facts["required_available_disk_bytes"])
    if not facts["admitted"]:
        raise BridgeError(ErrorCode.OPERATION_FAILED, "Current-pixel resource preflight refused before large allocation.",
                          {"reason": "RESOURCE_PREFLIGHT_REFUSED", "resource_facts": facts})
    return facts
