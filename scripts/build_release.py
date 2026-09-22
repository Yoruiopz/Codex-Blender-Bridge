"""Build downloadable add-on, MCP wheel, plugin, and checksum release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def package_plugin(source: Path, output: Path, version: str) -> Path:
    plugin = source / "plugins" / "blender-codex-bridge"
    manifest = json.loads((plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    if manifest["name"] != plugin.name or manifest["version"].split("+")[0] != version:
        raise ValueError("Plugin name/version disagrees with release")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"blender-codex-bridge-plugin-{version}.zip"
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(plugin.rglob("*")):
            relative = path.relative_to(plugin)
            if not path.is_file() or any(part in {".agents", "__pycache__"} for part in relative.parts):
                continue
            if path.suffix == ".pyc":
                continue
            info = ZipInfo((Path(plugin.name) / relative).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return destination


def build(source: Path, output: Path, *, skip_wheel: bool = False) -> list[Path]:
    source, output = source.resolve(), output.resolve()
    match = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', (source / "pyproject.toml").read_text(), re.M)
    if not match:
        raise ValueError("Expected a numeric project release version")
    version = match.group(1)
    output.mkdir(parents=True, exist_ok=True)
    addon = output / f"blender_codex_bridge-{version}.zip"
    subprocess.run([sys.executable, str(source / "scripts" / "build_addon.py"), "--output", str(addon)], check=True)
    wheel = output / f"blender_codex_bridge-{version}-py3-none-any.whl"
    if not skip_wheel:
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", str(source), "--wheel-dir", str(output)], check=True)
    if not wheel.is_file():
        raise FileNotFoundError(wheel)
    assets = [addon, wheel, package_plugin(source, output, version)]
    checksum = output / "SHA256SUMS.txt"
    checksum.write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in assets), encoding="utf-8")
    return [*assets, checksum]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "release")
    parser.add_argument("--skip-wheel", action="store_true", help="Require an already built matching wheel")
    args = parser.parse_args()
    for asset in build(args.source, args.output, skip_wheel=args.skip_wheel):
        print(asset)
