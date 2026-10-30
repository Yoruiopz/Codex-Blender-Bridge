"""Private bounded mesh-storage preparation inputs; no public registration."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from .errors import BridgeError, ErrorCode, invalid_argument
from .permissions import Permission

PREVIEW = "mesh.attribute_storage_prepare_preview"
START = "mesh.attribute_storage_prepare_job_start"
INSPECTION_START = "mesh.attribute_storage_prepare_inspection_start"
PERMISSIONS = (Permission.INSPECT_SCENE, Permission.EDIT_MESH)
MAX_SELECTED = 32
POLICY = "OWNED_SINGLE_TO_ARRAY_ONE_ATTRIBUTE_PER_TURN_V1"
INSPECTION_POLICY = "B2_PHASED_COHERENT_READ_ONLY_V1"


def inspection_refused(reason, *, status="STALE"):
    return BridgeError(ErrorCode.OPERATION_FAILED, "Mesh storage inspection did not produce coherent evidence.",
                       {"reason": reason, "inspection_status": status, "write_authorized": False,
                        "verification_required": True})


def refused(reason):
    return BridgeError(ErrorCode.NOT_IMPLEMENTED, "Mesh storage preparation is not admitted.",
                       {"reason": reason, "verification_required": True,
                        "requires_fresh_image_preview": True})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Parameters:
    object_name: str
    mesh_name: str
    attribute_names: tuple[str, ...]
    time_limit_seconds: float
    expected_preparation_fingerprint: str | None = None

    def plain(self):
        return {"object_name": self.object_name, "mesh_name": self.mesh_name,
                "attribute_names": list(self.attribute_names), "time_limit_seconds": self.time_limit_seconds}


def parse(params, *, starting=False):
    fields = {"object_name", "mesh_name", "attribute_names", "time_limit_seconds"}
    if starting:
        fields |= {"expected_preparation_fingerprint", "confirm_materialize_storage",
                   "confirm_retained_partial_preparation"}
    if type(params) is not dict or any(type(key) is not str for key in params) or not set(params) <= fields:
        raise invalid_argument("Mesh preparation requires an exact bounded object of declared fields.")
    names = params.get("attribute_names")
    if type(names) is not list or not 1 <= len(names) <= MAX_SELECTED:
        raise invalid_argument("Select between one and 32 exact attribute names.")
    all_names = (params.get("object_name"), params.get("mesh_name"), *names)
    for name in all_names:
        if type(name) is not str or not name or "\x00" in name:
            raise invalid_argument("Object, mesh and attribute names must be exact nonempty strings.")
        try:
            if len(name.encode("utf-8")) > 63:
                raise ValueError
        except (UnicodeError, ValueError):
            raise invalid_argument("Names must fit Blender's 63-byte identifier limit.") from None
    if len(set(names)) != len(names):
        raise invalid_argument("Attribute selection contains duplicate names.")
    limit = params.get("time_limit_seconds", 60.)
    if (type(limit) is not int and type(limit) is not float) or not math.isfinite(limit) or not 1 <= limit <= 300:
        raise invalid_argument("Job deadline must be between one and 300 seconds.")
    fingerprint = params.get("expected_preparation_fingerprint")
    if starting:
        if type(fingerprint) is not str or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise invalid_argument("Start requires the exact preparation-preview fingerprint.")
        if params.get("confirm_materialize_storage") is not True or params.get("confirm_retained_partial_preparation") is not True:
            raise invalid_argument("Explicitly confirm storage materialization and retained partial preparation.")
    return Parameters(all_names[0], all_names[1], tuple(names), float(limit), fingerprint)
