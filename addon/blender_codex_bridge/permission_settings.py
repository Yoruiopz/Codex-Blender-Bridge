"""The Bridge's local permission profile, stored apart from Blender projects."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .permissions import PREFERENCE_PROPERTIES

MASTER_FIELD = "all_dangerous_permissions"
UNRESTRICTED_FIELD = "allow_unrestricted_project_texture_paths"
BOOLEAN_FIELDS = (*PREFERENCE_PROPERTIES.values(), MASTER_FIELD, UNRESTRICTED_FIELD)
FOLDER_FIELDS = ("project_directory", "texture_directory", "asset_directory", "asset_source_directory")
FIELDS = (*BOOLEAN_FIELDS, *FOLDER_FIELDS)
MAX_PROFILE_BYTES = 64 * 1024
PROFILE_FILE = "permissions-v1.json"

PermissionValues = dict[str, bool | str]


def restrictive_values() -> PermissionValues:
    return {**dict.fromkeys(BOOLEAN_FIELDS, False), **dict.fromkeys(FOLDER_FIELDS, "")}


def _validated(values: Any) -> PermissionValues:
    if type(values) is not dict or set(values) != set(FIELDS):
        raise ValueError("Unknown or missing Bridge permission settings")
    if any(type(values[field]) is not bool for field in BOOLEAN_FIELDS):
        raise ValueError("Bridge permission choices must be booleans")
    for field in FOLDER_FIELDS:
        folder = values[field]
        if (type(folder) is not str or len(folder.encode("utf-8")) > 4096
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in folder)):
            raise ValueError("Invalid Bridge permission folder")
    if values[UNRESTRICTED_FIELD] and not values[MASTER_FIELD]:
        raise ValueError("Unrestricted folders require the master opt-in")
    return values


def preference_values(preferences: Any) -> PermissionValues:
    return _validated({field: getattr(preferences, field) for field in FIELDS})


def _unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Bridge permission setting")
        result[key] = value
    return result


def _plain_file(info: os.stat_result) -> bool:
    return (stat.S_ISREG(info.st_mode)
            and not getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def read_permission_settings(path: Path) -> PermissionValues | None:
    """A missing file is migration. Any invalid existing file must fail closed."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if not _plain_file(before) or before.st_size > MAX_PROFILE_BYTES:
        raise ValueError("Expected a bounded ordinary Bridge permission profile")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not _plain_file(opened) or not os.path.samestat(before, opened):
            raise ValueError("Bridge permission profile changed while opening")
        data = stream.read(MAX_PROFILE_BYTES + 1)
    if len(data) > MAX_PROFILE_BYTES:
        raise ValueError("Bridge permission profile exceeds its size limit")
    payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_json)
    if (type(payload) is not dict or set(payload) != {"version", "settings"}
            or type(payload["version"]) is not int or payload["version"] != 1):
        raise ValueError("Unsupported Bridge permission profile")
    return _validated(payload["settings"])


def write_permission_settings(path: Path, values: PermissionValues) -> None:
    """Flush a new private file, then replace the old one atomically."""
    data = (json.dumps({"version": 1, "settings": _validated(values)},
                       ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(data) > MAX_PROFILE_BYTES:
        raise ValueError("Bridge permission profile exceeds its size limit")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = None
    try:
        # On Windows the temporary file must be closed before replacement.
        with NamedTemporaryFile(dir=path.parent, prefix=".permissions-", delete=False) as stream:
            pending = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
        pending = None
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
