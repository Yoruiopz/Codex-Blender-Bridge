"""Pin exact candidate/previous ZIP inputs for the installed add-on native probe."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
from pathlib import Path
from zipfile import ZipFile

MAX_TOOLS_BYTES = 512 * 1024
TOOL_NAME = r"[a-z][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+"


def tool_names_record(path: Path, count: int) -> dict:
    path = path.resolve(strict=True)
    with path.open("rb") as stream:
        payload = stream.read(MAX_TOOLS_BYTES + 1)
    if len(payload) > MAX_TOOLS_BYTES:
        raise ValueError("Expected tool names JSON exceeds 512 KiB")

    def invalid_constant(value: str) -> None:
        raise ValueError("Expected tool names require standard JSON: " + value)

    names = json.loads(payload, parse_constant=invalid_constant)
    if (type(names) is not list or len(names) != count
            or any(type(name) is not str or len(name) > 128 or re.fullmatch(TOOL_NAME, name) is None for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("Expected tool names must be a unique valid name list matching the tool count")
    return {"expected_tool_names": sorted(names),
            "expected_tool_names_sha256": hashlib.sha256(payload).hexdigest(),
            "expected_tool_names_source": str(path)}


def package_record(path: Path, tools: int, *, require_discovery: bool = True,
                   tools_file: Path | None = None) -> dict:
    if type(tools) is not int or not 1 <= tools <= 4096:
        raise ValueError("Expected tool count must be between 1 and 4096")
    names = {} if tools_file is None else tool_names_record(tools_file, tools)
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
            "expected_tools": tools, "require_discovery": require_discovery, **names}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--candidate-tools", required=True, type=int)
    parser.add_argument("--candidate-tools-file", type=Path,
                        help="Pin the exact accepted MCP tool-name JSON for the candidate")
    parser.add_argument("--previous-tools", required=True, type=int)
    parser.add_argument("--allow-previous-undiscoverable", action="store_true",
                        help="Record known-name enablement for the published alpha's metadata defect")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    config = {"schema_version": 1,
              "candidate": package_record(args.candidate, args.candidate_tools,
                                          tools_file=args.candidate_tools_file),
              "previous": package_record(args.previous, args.previous_tools,
                                         require_discovery=not args.allow_previous_undiscoverable)}
    payload = json.dumps(config, indent=2) + "\n"
    if len(payload.encode("utf-8")) > 512 * 1024:
        raise ValueError("Package-probe configuration exceeds 512 KiB")
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(payload)


if __name__ == "__main__":
    main()
