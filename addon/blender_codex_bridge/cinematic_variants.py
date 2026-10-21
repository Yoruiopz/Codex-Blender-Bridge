"""Bounded inert Scene JSON for explicitly rebound cinematic controls.

No permissions, native identities, paths, code or preview capabilities are stored.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from .errors import invalid_argument

PROPERTY = "_blender_codex_bridge_cinematic_variants_v1"
MAX_BYTES = 262_144
CAMERA_FIELDS = ("type", "lens", "lens_unit", "sensor_fit", "sensor_width", "sensor_height",
    "shift_x", "shift_y", "clip_start", "clip_end", "ortho_scale")
DOF_FIELDS = ("use_dof", "focus_distance", "aperture_fstop", "aperture_blades", "aperture_rotation", "aperture_ratio")
LIGHT_COMMON = ("type", "energy", "color", "use_shadow", "normalize", "exposure", "diffuse_factor",
    "specular_factor", "volume_factor", "transmission_factor", "use_custom_distance", "cutoff_distance", "use_nodes")
LIGHT_SHAPE = {"POINT": ("shadow_soft_size",), "SUN": ("angle",),
    "SPOT": ("shadow_soft_size", "spot_size", "spot_blend", "use_square"),
    "AREA": ("shape", "size", "size_y", "spread")}
HEX = re.compile(r"^[0-9a-f]{64}$")
VARIANT_ID = re.compile(r"^v_[0-9a-f]{32}$")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise invalid_argument(f"{label} has unsupported or missing fields.")


def name(value, label="Object name"):
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or "\x00" in value:
        raise invalid_argument(f"{label} must be a nonempty name of at most 256 characters.")
    return value


def names(value, label, maximum):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise invalid_argument(f"{label} requires 1-{maximum} explicit names.")
    result = [name(item, label) for item in value]
    if len(set(result)) != len(result):
        raise invalid_argument(f"{label} contains duplicate names.")
    return result


def fingerprint(raw):
    if raw is not None and not isinstance(raw, str):
        raise invalid_argument("Stored cinematic variant library must be JSON text.")
    return hashlib.sha256(("ABSENT" if raw is None else "JSON:"+raw).encode()).hexdigest()


def _number(value, label, low=-1e6, high=1e6):
    if type(value) not in (float, int) or not low <= value <= high or not math.isfinite(value):
        raise invalid_argument(f"{label} must be a bounded finite number.")


def _vector(value, length, label, low=-1e6, high=1e6):
    if not isinstance(value, list) or len(value) != length:
        raise invalid_argument(f"{label} must contain {length} numbers.")
    for item in value:
        _number(item, label, low, high)


def validate_control(control, kind):
    _keys(control, ("object_name", "data_name", "object_type", "data_type", "location", "rotation_mode", "rotation", "scale", "settings"), "Cinematic control")
    name(control["object_name"])
    name(control["data_name"], "Data name")
    data_type = control["data_type"]
    if control["object_type"] != kind or not isinstance(data_type, str) or data_type not in ({"PERSP", "ORTHO"} if kind == "CAMERA" else LIGHT_SHAPE):
        raise invalid_argument("Unsupported cinematic object/data type.")
    rotation_mode = control["rotation_mode"]
    if not isinstance(rotation_mode, str) or rotation_mode not in {"XYZ", "QUATERNION"}:
        raise invalid_argument("Cinematic controls support XYZ or QUATERNION rotations.")
    _vector(control["location"], 3, "Location")
    _vector(control["rotation"], 4 if rotation_mode == "QUATERNION" else 3, "Rotation")
    if rotation_mode == "QUATERNION" and abs(sum(v*v for v in control["rotation"])-1.) > 1e-5:
        raise invalid_argument("Cinematic quaternion must be normalized.")
    _vector(control["scale"], 3, "Scale", 1e-6, 1e6)
    keys = (*CAMERA_FIELDS, *("dof."+field for field in DOF_FIELDS), "dof.focus_object") if kind == "CAMERA" else (*LIGHT_COMMON, *LIGHT_SHAPE[data_type])
    settings = control["settings"]
    _keys(settings, keys, "Cinematic settings")
    enums = {"type": {data_type}, "lens_unit": {"MILLIMETERS", "FOV"}, "sensor_fit": {"AUTO", "HORIZONTAL", "VERTICAL"},
        "shape": {"SQUARE", "RECTANGLE", "DISK", "ELLIPSE"}}
    booleans = {"use_shadow", "normalize", "use_custom_distance", "use_nodes", "use_square", "dof.use_dof"}
    for field, value in settings.items():
        if field in enums:
            if not isinstance(value, str) or value not in enums[field]:
                raise invalid_argument("Unsupported cinematic setting enum.")
        elif field in booleans:
            if type(value) is not bool:
                raise invalid_argument("Cinematic Boolean settings require exact Boolean values.")
        elif field == "dof.focus_object":
            if value is not None:
                raise invalid_argument("Cinematic variants require explicit focus distance without a focus-object dependency.")
        elif field == "color":
            _vector(value, 3, "Light color", 0., 1.)
        elif field == "dof.aperture_blades":
            if type(value) is not int or not 0 <= value <= 16:
                raise invalid_argument("Aperture blades must be an integer in 0-16.")
        else:
            _number(value, field)
    if kind == "CAMERA" and (not 0 < settings["clip_start"] < settings["clip_end"] or settings["lens"] <= 0 or settings["dof.aperture_fstop"] <= 0):
        raise invalid_argument("Camera clipping, lens and aperture must be positive and ordered.")
    return control


def validate_record(record):
    _keys(record, ("variant_id", "label", "camera", "lights", "protected_objects", "profile_sha256"), "Cinematic variant")
    if not isinstance(record["variant_id"], str) or not VARIANT_ID.fullmatch(record["variant_id"]):
        raise invalid_argument("Invalid cinematic variant ID.")
    if not isinstance(record["label"], str) or not record["label"].strip() or len(record["label"]) > 80:
        raise invalid_argument("Variant label requires 1-80 characters.")
    if not isinstance(record["profile_sha256"], str) or not HEX.fullmatch(record["profile_sha256"]):
        raise invalid_argument("Invalid protected profile fingerprint.")
    validate_control(record["camera"], "CAMERA")
    if not isinstance(record["lights"], list) or not 1 <= len(record["lights"]) <= 8:
        raise invalid_argument("A variant needs 1-8 explicit lights.")
    for light in record["lights"]:
        validate_control(light, "LIGHT")
    references = [record["camera"]["object_name"], *(item["object_name"] for item in record["lights"])]
    protected = names(record["protected_objects"], "protected_objects", 32)
    if len(set(references)) != len(references) or set(references) & set(protected):
        raise invalid_argument("Variant control and protected references must be distinct.")
    return record


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise invalid_argument("Cinematic JSON contains duplicate fields.")
        result[key] = value
    return result


def validate_library(library):
    _keys(library, ("schema_version", "revision", "variants"), "Cinematic library")
    if type(library["schema_version"]) is not int or library["schema_version"] != 1:
        raise invalid_argument("Unsupported cinematic library schema.")
    if type(library["revision"]) is not int or not 0 <= library["revision"] <= 1_000_000_000:
        raise invalid_argument("Invalid cinematic library revision.")
    records = library["variants"]
    if not isinstance(records, list) or len(records) > 8:
        raise invalid_argument("A cinematic library supports at most eight variants.")
    for record in records:
        validate_record(record)
    if len({record["variant_id"] for record in records}) != len(records):
        raise invalid_argument("Duplicate cinematic variant IDs.")
    return library


def encode_library(library):
    validate_library(library)
    raw = json.dumps(library, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(raw.encode()) > MAX_BYTES:
        raise invalid_argument("Cinematic library exceeds 256 KiB.")
    return raw


def read_library(raw):
    if raw is None:
        return {"schema_version": 1, "revision": 0, "variants": []}
    if not isinstance(raw, str) or len(raw.encode()) > MAX_BYTES:
        raise invalid_argument("Stored cinematic library must be JSON text within 256 KiB.")
    try:
        result = json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, RecursionError) as error:
        raise invalid_argument("Stored cinematic library contains malformed JSON.") from error
    return validate_library(result)
