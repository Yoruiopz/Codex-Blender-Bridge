"""Launch a private loaded-image lifecycle fixture on an input-free Xorg display."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LAUNCHER = Path(__file__).resolve()
ROOT = LAUNCHER.parents[1]
CONFIG = b'''Section "ServerFlags"
 Option "AutoAddDevices" "false"
 Option "AutoEnableDevices" "false"
 Option "AutoAddGPU" "false"
 Option "DontVTSwitch" "true"
EndSection
Section "Device"
 Identifier "Owned Dummy Device"
 Driver "dummy"
 VideoRam 256000
EndSection
Section "Monitor"
 Identifier "Owned Dummy Monitor"
 HorizSync 25-90
 VertRefresh 40-75
 Modeline "1360x1024" 84.00 1360 1412 1476 1620 1024 1027 1033 1067
EndSection
Section "Screen"
 Identifier "Owned Dummy Screen"
 Device "Owned Dummy Device"
 Monitor "Owned Dummy Monitor"
 DefaultDepth 24
 SubSection "Display"
  Depth 24
  Modes "1360x1024"
 EndSubSection
EndSection
'''


def fingerprints() -> tuple[str, str]:
    """Return the exact checkout launcher and fixed dummy configuration hashes."""
    return hashlib.sha256(LAUNCHER.read_bytes()).hexdigest(), hashlib.sha256(CONFIG).hexdigest()


def ready_dimensions(server: subprocess.Popen, env: dict[str, str]) -> tuple[int, int]:
    until = time.monotonic() + 8
    while time.monotonic() < until and server.poll() is None:
        probe = subprocess.run(["/usr/bin/xdpyinfo"], env=env, capture_output=True, timeout=2, check=False)
        dimensions = re.search(rb"dimensions:\s+(\d+)x(\d+)\s+pixels", probe.stdout)
        if probe.returncode == 0 and dimensions:
            width, height = map(int, dimensions.groups())
            if 640 <= width <= 1600 and 640 <= height <= 1200:
                return width, height
            break
        time.sleep(.1)
    raise RuntimeError("Owned Xorg did not expose the reviewed private dimensions.")


def run(blenders: list[Path], output: Path, timeout: int, case: str = "current_pixels_loaded_backup") -> int:
    if sys.platform != "linux":
        raise RuntimeError("The private loaded-image launcher requires Linux.")
    if case not in {"current_pixels_loaded_backup", "current_pixels_acquisition", "current_pixels_backup_interruption"}:
        raise ValueError("Unreviewed loaded-image fixture case.")
    with tempfile.TemporaryDirectory(prefix="bcb-loaded-backup-display-") as owned:
        profile = Path(owned).resolve()
        runtime = profile / "runtime"
        runtime.mkdir(mode=0o700)
        manifest, config, authority = (profile / name for name in ("private-ui.json", "xorg.conf", "xauthority"))
        config.write_bytes(CONFIG)
        authority.touch(mode=0o600)
        display = next((f":{number}" for number in range(241, 265)
                        if not Path(f"/tmp/.X{number}-lock").exists()
                        and not Path(f"/tmp/.X11-unix/X{number}").exists()), None)
        if display is None:
            raise RuntimeError("No reviewed private display number is available.")
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
        env.update(DISPLAY=display, XAUTHORITY=str(authority), LIBGL_ALWAYS_SOFTWARE="1",
                   XDG_RUNTIME_DIR=str(runtime), XDG_SESSION_TYPE="x11",
                   BRIDGE_TEST_PRIVATE_UI_MANIFEST=str(manifest))
        subprocess.run(["/usr/bin/xauth", "-f", str(authority), "add", display, "MIT-MAGIC-COOKIE-1",
                        secrets.token_hex(16)], env=env, stdout=subprocess.DEVNULL, check=True, timeout=5)
        with (profile / "xorg-launch.log").open("wb") as log:
            server = subprocess.Popen(
                ["/usr/lib/xorg/Xorg", display, "-config", str(config), "-auth", str(authority),
                 "-nolisten", "tcp", "-noreset", "-novtswitch", "-logfile", str(profile / "xorg.log")],
                env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
        try:
            width, height = ready_dimensions(server, env)
            launcher_sha, config_sha = fingerprints()
            with manifest.open("x", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump({"schema_version": 1, "input_disabled": True, "owned_process": True,
                           "tcp_disabled": True, "display": display, "screen_width": width,
                           "screen_height": height, "profile": str(profile), "xdg_runtime_dir": str(runtime),
                           "xauthority_path": str(authority), "launcher_path": str(LAUNCHER),
                           "launcher_sha256": launcher_sha, "config_sha256": config_sha,
                           "server_pid": server.pid}, stream)
            command = [sys.executable, str(ROOT / "scripts" / "run_blender_checks.py"),
                       "--case", case, "--timeout", str(timeout), "--output", str(output)]
            for blender in blenders:
                command.extend(["--blender", str(blender)])
            return subprocess.run(command, cwd=ROOT, env=env, check=False,
                                  timeout=(timeout + 15) * len(blenders) + 30).returncode
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=("current_pixels_loaded_backup", "current_pixels_acquisition",
                                           "current_pixels_backup_interruption"),
                        default="current_pixels_loaded_backup")
    parser.add_argument("--timeout", type=int, default=300, help="Case timeout in seconds, from 90 to 300")
    args = parser.parse_args()
    if not 90 <= args.timeout <= 300:
        parser.error("--timeout must be from 90 to 300 seconds")
    return run(args.blender, args.output, args.timeout, args.case)


if __name__ == "__main__":
    raise SystemExit(main())
