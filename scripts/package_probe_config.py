"""Pin exact candidate/previous ZIP inputs for the installed add-on native probe."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile


def package_record(path: Path, tools: int, *, require_discovery: bool = True) -> dict:
    if not 1 <= tools <= 4096:
        raise ValueError("Expected tool count must be between 1 and 4096")
    path = path.resolve(strict=True)
    with path.open("rb") as stream:
        payload = stream.read(32 * 1024 * 1024 + 1)
    if len(payload) > 32 * 1024 * 1024:
        raise ValueError("Add-on ZIP exceeds 32 MiB")
    with ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) > 512 or sum(item.file_size for item in entries) > 64 * 1024 * 1024:
            raise ValueError("Add-on ZIP exceeds member or expanded-byte limits")
        if archive.testzip() is not None or len({item.filename for item in entries}) != len(entries):
            raise ValueError("Add-on ZIP is corrupt or has duplicate members")
        members = {item.filename: hashlib.sha256(archive.read(item)).hexdigest()
                   for item in entries if not item.is_dir()}
        constants = ast.parse(archive.read("blender_codex_bridge/constants.py"))
        versions = [ast.literal_eval(node.value) for node in constants.body
                    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "ADDON_VERSION"
                                                          for target in node.targets)]
        if len(versions) != 1 or not isinstance(versions[0], tuple) or len(versions[0]) != 3 or any(type(value) is not int or value < 0 for value in versions[0]):
            raise ValueError("Missing literal numeric add-on version")
    return {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest(),
            "members_sha256": members, "version": ".".join(map(str, versions[0])),
            "expected_tools": tools, "require_discovery": require_discovery}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--candidate-tools", required=True, type=int)
    parser.add_argument("--previous-tools", required=True, type=int)
    parser.add_argument("--allow-previous-undiscoverable", action="store_true",
                        help="Record known-name enablement for the published alpha's metadata defect")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = {"schema_version": 1,
              "candidate": package_record(args.candidate, args.candidate_tools),
              "previous": package_record(args.previous, args.previous_tools,
                                         require_discovery=not args.allow_previous_undiscoverable)}
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(config, indent=2) + "\n")


if __name__ == "__main__":
    main()
