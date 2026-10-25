"""Build an installable Blender add-on ZIP without third-party dependencies."""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "addon" / "blender_codex_bridge"
PACKAGE_NAME = "blender_codex_bridge"
REQUIRED_MEMBERS = {
    f"{PACKAGE_NAME}/__init__.py",
    f"{PACKAGE_NAME}/constants.py",
    f"{PACKAGE_NAME}/blender_manifest.toml",
}
REPRODUCIBLE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _literal_assignment(source: bytes, name: str) -> object:
    try:
        nodes = ast.parse(source).body
    except SyntaxError as error:
        raise ValueError(f"Invalid Python in add-on {name} metadata") from error
    for node in nodes:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError as error:
                raise ValueError(f"Blender discovery requires literal {name} metadata") from error
    raise ValueError(f"Missing {name} metadata")


def _source_files() -> list[Path]:
    return [
        path
        for path in sorted(SOURCE.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]


def validate_archive(path: Path) -> None:
    """Reject an incomplete, corrupt, or unexpectedly rooted add-on archive."""

    try:
        with ZipFile(path) as archive:
            members = archive.namelist()
            corrupt_member = archive.testzip()
            if set(members) >= REQUIRED_MEMBERS:
                metadata = _literal_assignment(archive.read(f"{PACKAGE_NAME}/__init__.py"), "bl_info")
                version = _literal_assignment(archive.read(f"{PACKAGE_NAME}/constants.py"), "ADDON_VERSION")
                manifest = re.search(rb'^version = "([0-9]+)\.([0-9]+)\.([0-9]+)"$',
                                     archive.read(f"{PACKAGE_NAME}/blender_manifest.toml"), re.M)
                if (not isinstance(metadata, dict) or metadata.get("version") != version
                        or manifest is None or tuple(map(int, manifest.groups())) != version):
                    raise ValueError("Add-on discovery, runtime and manifest versions disagree")
    except (BadZipFile, OSError) as exc:
        raise ValueError(f"Add-on archive is not a readable ZIP: {path}") from exc
    missing = sorted(REQUIRED_MEMBERS - set(members))
    unexpected = sorted(
        name
        for name in members
        if not name.startswith(f"{PACKAGE_NAME}/")
        or "__pycache__" in Path(name).parts
        or name.endswith(".pyc")
    )
    if corrupt_member is not None:
        raise ValueError(f"Add-on archive contains corrupt member: {corrupt_member}")
    if missing or unexpected:
        raise ValueError(
            f"Invalid add-on archive layout (missing={missing}, unexpected={unexpected})"
        )


def build(output: Path) -> Path:
    """Create and validate a reproducible Blender add-on ZIP."""

    if not all((SOURCE / member.rsplit("/", 1)[-1]).is_file() for member in REQUIRED_MEMBERS):
        raise FileNotFoundError(f"Blender add-on package is missing: {SOURCE}")
    output = output.resolve()
    if output == SOURCE or SOURCE in output.parents:
        raise ValueError("Build output must be outside the add-on source directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for path in _source_files():
                member = (Path(PACKAGE_NAME) / path.relative_to(SOURCE)).as_posix()
                info = ZipInfo(member, date_time=REPRODUCIBLE_TIMESTAMP)
                info.compress_type = ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes(), compresslevel=9)
        validate_archive(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "blender_codex_bridge-0.5.0.zip",
        help="Destination ZIP path",
    )
    args = parser.parse_args()
    print(build(args.output.resolve()))


if __name__ == "__main__":
    main()
