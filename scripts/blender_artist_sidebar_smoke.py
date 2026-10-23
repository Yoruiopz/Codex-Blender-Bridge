"""Private UI presentation proof using real registered artist-step receipts.

Run only through the isolated native runner and the input-disabled private Linux
display launcher. Screenshots observe the disposable Blender window; they are
fixture artifacts, not public viewport captures or artist-workflow acceptance.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import selectors
import stat
import struct
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, NoReturn

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402

WORK = "Sidebar Target"
STEP = "revise"
CATEGORY = "Codex Bridge"
METHOD = "task.plan.verify_transform"
CORE = ("location", "rotation_mode", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
STAGES = (("matched", "Matched at verification"), ("differ", "Differences at verification"),
          ("stale", "Stale; verify again"), ("unavailable", "Expectation unavailable"))
PRIVATE_LAUNCHER_SHA256 = "d243355385d6179d85d3fe5adecd8c2e752f470b7d6cf686b71934f31e7e5aa9"
PRIVATE_XORG_CONFIG_SHA256 = "fd963752e6e6595d7f3c6602928d4daca3276ef76156f4713a84fc21569ba7c6"
CAPTURE_BINARIES = ("/usr/bin/import", "/usr/bin/identify", "/usr/bin/xwininfo")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def bounded_command(argv: list[str], environment: dict[str, str]) -> dict[str, Any]:
    """Collect only bounded diagnostics from one owned capture subprocess."""
    assert argv[0] in CAPTURE_BINARIES
    assert len(argv) <= 16 and all(type(item) is str and len(item) <= 8192 for item in argv)
    maximum, timeout = 32768, 8.
    output = {"stdout": bytearray(), "stderr": bytearray()}
    timed_out = output_exceeded = cleanup_timed_out = False
    started = time.monotonic()
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=environment, shell=False, close_fds=True)
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _events in selector.select(min(.1, remaining)):
                    block = os.read(key.fd, 4096)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    retained = output[key.data]
                    allowance = maximum - len(retained)
                    retained.extend(block[:allowance])
                    if len(block) > allowance:
                        output_exceeded = True
                        break
                if output_exceeded:
                    break
        remaining = max(0., timeout - (time.monotonic() - started))
        if not timed_out and not output_exceeded:
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        if process.poll() is None:
            process.kill()  # Only the subprocess started immediately above.
        try:
            try:
                process.wait(timeout=1.)
            except subprocess.TimeoutExpired:
                cleanup_timed_out = True
        finally:
            process.stdout.close()
            process.stderr.close()
    return {"returncode": process.returncode, "stdout": bytes(output["stdout"]).decode("utf-8", errors="replace"),
            "stderr": bytes(output["stderr"]).decode("utf-8", errors="replace"),
            "timed_out": timed_out, "output_exceeded": output_exceeded, "cleanup_timed_out": cleanup_timed_out,
            "output_limit_bytes_per_stream": maximum, "timeout_seconds": timeout,
            "elapsed_seconds": time.monotonic() - started}


def usable_pixel_metrics(output: str, previous: set[str]) -> dict[str, Any]:
    """Reject blank or repeated pixels; this cannot verify visible UI wording."""
    fields = output.strip().split()
    assert len(fields) == 2 and 1 <= len(fields[0]) <= 7 and fields[0].isascii() and fields[0].isdecimal()
    colors = int(fields[0])
    signature = fields[1]
    assert len(signature) == 64 and all(character in "0123456789abcdef" for character in signature)
    assert 16 <= colors <= 1600 * 1200, "Private UI primary capture is blank or has too few colors"
    assert signature not in previous, "Private UI stages have identical decoded pixel signatures"
    return {"unique_colors": colors, "pixel_signature": signature,
            "guard_scope": "Reject blank/repeated images only; root must review original label visibility"}


def owned_process_exit(status: int) -> NoReturn:
    """Exit only this disposable fixture, bypassing Blender quit/save callbacks.

    OS process teardown and parent-owned display cleanup are not evidence of
    production cancellation, graceful add-on shutdown or durable recovery.
    """
    try:
        sys.stdout.flush()
    finally:
        try:
            sys.stderr.flush()
        finally:
            os._exit(status)


def owned_file(path: Path, *, maximum: int, private: bool = False) -> bytes:
    assert not path.is_symlink(), "Fixture evidence paths must not be symbolic links"
    metadata = path.stat()
    assert stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid()
    if private:
        assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert 0 < metadata.st_size <= maximum
    return path.read_bytes()


def private_display_manifest() -> dict[str, Any]:
    """Fail closed before observing any UI; never read Xauthority cookie bytes."""
    assert sys.platform == "linux", "This development fixture requires the reviewed private Linux display launcher"
    assert not os.environ.get("WAYLAND_DISPLAY")
    location = os.environ.get("BRIDGE_TEST_PRIVATE_UI_MANIFEST")
    assert location, "Missing input-disabled private UI attestation"
    path = Path(location)
    raw = owned_file(path, maximum=16384, private=True)
    manifest = json.loads(raw)
    assert type(manifest) is dict and len(manifest) <= 32
    assert manifest["schema_version"] == 1 and type(manifest["schema_version"]) is int
    for field in ("input_disabled", "owned_process", "tcp_disabled"):
        assert manifest[field] is True
    assert type(manifest["display"]) is str and manifest["display"] == os.environ.get("DISPLAY")
    for field, maximum in (("screen_width", 1600), ("screen_height", 1200)):
        assert type(manifest[field]) is int and 640 <= manifest[field] <= maximum
    profile = Path(manifest["profile"])
    assert not profile.is_symlink() and profile.resolve() == path.resolve().parent
    metadata = profile.stat()
    assert stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.getuid() and stat.S_IMODE(metadata.st_mode) == 0o700
    runtime = Path(manifest["xdg_runtime_dir"])
    assert not runtime.is_symlink() and runtime.resolve().parent == profile.resolve()
    assert runtime.name == "runtime" and str(runtime) == os.environ.get("XDG_RUNTIME_DIR")
    metadata = runtime.stat()
    assert stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.getuid() and stat.S_IMODE(metadata.st_mode) == 0o700
    assert not any(runtime.glob("wayland-*")), "Private runtime directory contains a Wayland endpoint"
    authority = Path(manifest["xauthority_path"])
    assert authority.resolve().parent == profile.resolve() and str(authority) == os.environ.get("XAUTHORITY")
    assert not authority.is_symlink()
    metadata = authority.stat()  # Metadata only: never retain the cookie contents.
    assert stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid() and stat.S_IMODE(metadata.st_mode) == 0o600
    launcher = Path(manifest["launcher_path"])
    launcher_raw = owned_file(launcher, maximum=65536)
    assert sha256(launcher_raw) == manifest["launcher_sha256"] == PRIVATE_LAUNCHER_SHA256
    config = profile / "xorg.conf"
    config_raw = owned_file(config, maximum=16384)
    assert sha256(config_raw) == manifest["config_sha256"] == PRIVATE_XORG_CONFIG_SHA256
    for setting in (b'Option "AutoAddDevices" "false"', b'Option "AutoEnableDevices" "false"', b'Driver "dummy"'):
        assert setting in config_raw
    server_pid = manifest["server_pid"]
    assert type(server_pid) is int and server_pid > 1 and server_pid != os.getpid()
    os.kill(server_pid, 0)
    command_raw = Path(f"/proc/{server_pid}/cmdline").read_bytes()
    assert 0 < len(command_raw) <= 16384
    command = [item.decode() for item in command_raw.split(b"\0") if item]
    assert Path(command[0]).name == "Xorg" and manifest["display"] in command
    for option, expected in (("-config", str(config)), ("-auth", str(authority)), ("-nolisten", "tcp")):
        assert option in command and command[command.index(option) + 1] == expected
    return {"manifest": manifest, "manifest_path": str(path), "manifest_sha256": sha256(raw),
            "server_command": command, "config_path": str(config),
            "xauthority_mode": "0600; metadata observed, cookie not read", "profile_mode": "0700",
            "xdg_runtime_mode": "0700; private owned directory without wayland-* endpoints"}


def object_state(obj: Any) -> dict[str, Any]:
    result = {"name": obj.name, "pointer": obj.as_pointer(), "type": obj.type,
              "channels": {field: str(getattr(obj, field)) if field == "rotation_mode" else list(getattr(obj, field))
                           for field in CORE},
              "parent": None if obj.parent is None else obj.parent.name,
              "hide": [obj.hide_viewport, obj.hide_render, obj.hide_select]}
    if obj.type == "MESH":
        assert len(obj.data.vertices) <= 32 and len(obj.data.polygons) <= 32
        result["mesh"] = {"name": obj.data.name, "pointer": obj.data.as_pointer(),
                          "vertices": [list(vertex.co) for vertex in obj.data.vertices],
                          "edges": [list(edge.vertices) for edge in obj.data.edges],
                          "polygons": [list(polygon.vertices) for polygon in obj.data.polygons],
                          "material_slots": [None if value is None else value.name for value in obj.data.materials]}
    return result


class SidebarFixture:
    def __init__(self, folder: Path):
        self.folder = folder
        self.runtime = self.window = self.area = self.layer = self.work = self.protected = None
        self.ui = self.original_formatter = None
        self.phase = "setup"
        self.stage_index = 0
        self.settle_ticks = 0
        self.data: dict[str, Any] = {
            "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
            "process_id": os.getpid(), "process_instance": os.environ.get("BRIDGE_TEST_PROCESS_TOKEN"),
            "scope": "Private sidebar presentation of cached registered artist-step receipts",
            "fixture_setup": "Raw disposable Empty/protected factory Cube and owned UI layout only",
            "artist_edits": "Registered plan/reference/preview/apply/verify calls; typed transform.set invalidates a cached observation",
            "manual_injections": [], "calls": [], "captures": [], "formatter_draws": {}, "completed": False,
            "external_commands": [], "capture_binaries": {},
            "capture_followup": "Historical f0f2 native markers passed structural checks but all eight original PNGs were black; visual gate failed",
            "readability_followup": "Historical 0613 primary X11 PNGs were readable but completion rejected unsupported ImageMagick signature syntax; target/status and warning lines were clipped at the default sidebar width",
            "capture_policy": "Native screen.screenshot is diagnostic; primary is explicit private X11 root capture after owned redraw/swap; blank/repeated pixels reject completion",
            "lifecycle_followup": [
                "Historical source249bcaf failed before capture because PreferencesFilePaths.use_save_on_exit is unsupported; no PNG was accepted",
                "Private launcher now owns XDG_RUNTIME_DIR as well as unsetting WAYLAND_DISPLAY, preventing inherited default Wayland socket discovery",
            ],
            "termination": {"method": "fixture-only os._exit after JSON and stdio flush", "requested_exit_code": None,
                            "native_quit_or_save_callbacks": False, "addon_unregister_invoked": False,
                            "parent_owns_private_display_cleanup": True, "production_cancellation_acceptance": False,
                            "graceful_cleanup_acceptance": False, "durable_recovery_acceptance": False},
            "expected_common_labels": ["Plan: 0/1 marked complete", "Revise prop (pending claim)",
                                       "Protected objects only: Not compared", "Protected scope: 1 objects (advisory)",
                                       "Step marks are claims;", "receipts do not verify the goal",
                                       "Target records are historical;", "verify after manual edits"],
            "claims": {"actual_private_window_screenshots": True, "presentation_only": True,
                       "visual_review": "REQUIRED: root must review each original PNG", "public_viewport_capture": False,
                       "new_ui_live_inspection": False, "existing_panel_providers_may_refresh": True,
                       "protected_scope_enforced": False, "protected_capture_qualification": False,
                       "artist_goal_verified": False, "project_saved": False, "native_undo": False,
                       "full_artist_acceptance": False, "Windows_qualified": False},
        }
        self.flush()

    def flush(self) -> None:
        raw = (json.dumps(self.data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        assert len(raw) < 4 * 1024 * 1024, "Sidebar evidence exceeded its bounded JSON budget"
        (self.folder / "artist-sidebar-evidence.json").write_bytes(raw)

    def call(self, method: str, params: dict[str, Any], *, error_code: str | None = None) -> Any:
        row = {"phase": self.phase, "method": method, "params": copy.deepcopy(params)}
        self.data["calls"].append(row)
        self.flush()
        try:
            result = self.runtime.dispatch(method, params)
        except BridgeError as error:
            row["error"] = error.to_dict()
            self.flush()
            assert error_code is not None and error.code == error_code, row
            return row["error"]
        row["result"] = result
        self.flush()
        assert error_code is None, (method, "Expected a structured refusal")
        return result

    def snapshot(self) -> dict[str, Any]:
        # Selection flags are read from the stored layer before other observers.
        selected = {obj.name: obj.select_get(view_layer=self.layer) for obj in self.layer.objects}
        active = self.layer.objects.active
        return {"selected": selected, "active": None if active is None else active.name,
                "provided_target": object_state(self.work), "provided_protected_peer": object_state(self.protected),
                "frame": [self.window.scene.frame_current, self.window.scene.frame_subframe],
                "history": self.runtime.state.history(50), "checkpoints": self.runtime.checkpoints.list(50)}

    def capture_environment(self) -> dict[str, str]:
        manifest = self.data["private_display"]["manifest"]
        assert not os.environ.get("WAYLAND_DISPLAY")
        expected = {"DISPLAY": manifest["display"], "XAUTHORITY": manifest["xauthority_path"],
                    "XDG_RUNTIME_DIR": manifest["xdg_runtime_dir"]}
        for key, value in expected.items():
            assert os.environ.get(key) == value
        runtime = Path(expected["XDG_RUNTIME_DIR"])
        assert not runtime.is_symlink() and runtime.resolve().parent == Path(manifest["profile"]).resolve()
        metadata = runtime.stat()
        assert stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.getuid() and stat.S_IMODE(metadata.st_mode) == 0o700
        assert not any(runtime.glob("wayland-*"))
        authority = Path(expected["XAUTHORITY"])
        assert not authority.is_symlink() and authority.resolve().parent == Path(manifest["profile"]).resolve()
        metadata = authority.stat()
        assert stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.getuid() and stat.S_IMODE(metadata.st_mode) == 0o600
        return {**expected, "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "HOME": str(self.folder.parent),
                "TEMP": str(self.folder.parent), "TMP": str(self.folder.parent), "TMPDIR": str(self.folder.parent),
                "MAGICK_TEMPORARY_PATH": str(self.folder.parent), "MAGICK_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"}

    def external(self, label: str, argv: list[str]) -> dict[str, Any]:
        environment = self.capture_environment()
        assert argv[0] in CAPTURE_BINARIES
        binary = self.data["capture_binaries"][argv[0]]
        resolved = Path(argv[0]).resolve(strict=True)
        assert str(resolved) == binary["resolved_path"] and sha256(resolved.read_bytes()) == binary["sha256"]
        row = {"phase": self.phase, "label": label, "argv": list(argv), "shell": False,
               "environment": environment, "status": "pending"}
        self.data["external_commands"].append(row)
        self.flush()
        try:
            row.update(bounded_command(argv, environment))
        except BaseException as error:
            row["error"] = {"type": type(error).__name__, "message": str(error)}
            self.flush()
            raise
        row["status"] = "observed"
        self.flush()
        assert (row["returncode"] == 0 and not row["timed_out"]
                and not row["output_exceeded"] and not row["cleanup_timed_out"]), row
        return row

    def capture_binary_metadata(self) -> None:
        for binary in CAPTURE_BINARIES:
            requested = Path(binary)
            resolved = requested.resolve(strict=True)
            metadata = resolved.stat()
            assert stat.S_ISREG(metadata.st_mode) and metadata.st_uid in {0, os.getuid()} and metadata.st_mode & 0o022 == 0
            assert 0 < metadata.st_size <= 32 * 1024 * 1024
            self.data["capture_binaries"][binary] = {"resolved_path": str(resolved), "bytes": metadata.st_size,
                                                    "sha256": sha256(resolved.read_bytes())}
            self.flush()
            version = self.external("capture_binary_version", [binary, "-version"])
            self.data["capture_binaries"][binary]["version_stdout"] = version["stdout"]
            self.data["capture_binaries"][binary]["version_stderr"] = version["stderr"]
            self.flush()

    def prepare(self) -> None:
        from blender_codex_bridge import ui

        self.capture_binary_metadata()
        blender_codex_bridge.register()
        self.runtime = get_runtime()
        grants = {permission.value: permission not in {Permission.EXECUTE_PYTHON, Permission.SAVE_PROJECT,
                                                       Permission.ACCESS_EXTERNAL_FILES} for permission in Permission}
        manager = PermissionManager(lambda: dict(grants))
        self.runtime.permissions = self.runtime.executor.permissions = manager
        self.runtime.registry.enable_toolset("objects")
        self.data["permissions"] = grants
        self.ui, self.original_formatter = ui, ui._target_channels_label

        def observe_formatter(receipt: object) -> str:
            # Return the real pure formatter output unchanged. This observer
            # records only plain labels/counters from actual Panel.draw calls.
            label = self.original_formatter(receipt)
            receipt_id = receipt.get("receipt_id") if type(receipt) is dict else None
            key = self.phase + ":" + label
            events = self.data["formatter_draws"]
            if key not in events:
                events[key] = {"phase": self.phase, "label": label, "receipt_id": receipt_id, "count": 0}
            events[key]["count"] += 1
            return label

        ui._target_channels_label = observe_formatter
        self.window = bpy.context.window
        assert self.window is not None
        scene = self.window.scene
        self.layer = self.window.view_layer
        self.protected = bpy.data.objects["Cube"]
        self.work = bpy.data.objects.new(WORK, None)
        scene.collection.objects.link(self.work)
        for obj in self.layer.objects:
            obj.select_set(False, view_layer=self.layer)
        self.work.select_set(True, view_layer=self.layer)
        self.layer.objects.active = self.work
        self.layer.update()
        self.data["provided_protected_baseline"] = object_state(self.protected)
        self.area = max((area for area in self.window.screen.areas if area.type == "VIEW_3D"), key=lambda area: area.width * area.height)
        with bpy.context.temp_override(window=self.window, area=self.area):
            result = bpy.ops.screen.screen_full_area(use_hide_panels=False)
        self.data["fixture_maximize_operator"] = sorted(result)
        assert result == {"FINISHED"}
        self.area = max((area for area in self.window.screen.areas if area.type == "VIEW_3D"), key=lambda area: area.width * area.height)
        self.area.spaces.active.show_region_ui = True
        self.data["source_sha256"] = {str(path.relative_to(ROOT)): sha256(path.read_bytes()) for path in (
            Path(__file__), ROOT / "addon/blender_codex_bridge/ui.py", ROOT / "addon/blender_codex_bridge/task_plans.py",
            ROOT / "addon/blender_codex_bridge/artist_step_evidence.py", ROOT / "addon/blender_codex_bridge/artist_target_intent.py",
            ROOT / "addon/blender_codex_bridge/tools/artist_loop.py", ROOT / "addon/blender_codex_bridge/tools/artist_target_verify.py")}
        self.call("task.plan.set", {"goal": "Inspect sidebar target receipts", "steps": [{"id": STEP,
                  "description": "Revise prop (pending claim)"}], "protected_objects": [self.protected.name]})
        self.flush()
        self.begin_stage()

    def inspect(self) -> dict[str, Any]:
        return self.call("task.plan.inspect", {})

    def current_params(self, receipt_id: str) -> dict[str, Any]:
        info = self.inspect()
        return {"step_id": STEP, "receipt_id": receipt_id, "expected_revision": info["plan"]["revision"]}

    def apply(self, requested: dict[str, Any]) -> str:
        info = self.inspect()
        reference = self.call("task.reference.resolve", {"source": "objects", "object_names": [self.work.name]})
        preview = self.call("task.plan.preview_transform", {"reference_id": reference["reference_id"],
                            "expected_revision": info["plan"]["revision"], "step_id": STEP, **requested})
        result = self.call("task.plan.apply_preview", {"preview_id": preview["preview_id"],
                           "expected_revision": info["plan"]["revision"]})
        return result["step_receipt_id"]

    def begin_stage(self) -> None:
        self.phase, label = STAGES[self.stage_index]
        self.settle_ticks = 0
        if self.phase == "matched":
            self.receipt_id = self.apply({"location": [.1, -.2, .3], "scale": [-1.25, .5, 2.75]})
            self.call(METHOD, self.current_params(self.receipt_id))
        elif self.phase == "differ":
            before = list(self.work.location)
            self.work.location.x += .125
            self.data["manual_injections"].append({"phase": self.phase, "kind": "Fixture-only manual native core-channel drift",
                                                    "before_location": before, "after_location": list(self.work.location)})
            self.flush()
            self.call(METHOD, self.current_params(self.receipt_id))
        elif self.phase == "stale":
            self.call("transform.set", {"object_name": self.work.name, "location": [.4, .5, .6]})
        else:
            assert self.phase == "unavailable" and self.work.rotation_mode == "XYZ"
            self.receipt_id = self.apply({"location": [.6, .5, .7], "rotation_mode": "ZYX", "rotation": [.1, .2, .3]})
            self.call(METHOD, self.current_params(self.receipt_id), error_code="NOT_IMPLEMENTED")
        info = self.inspect()
        receipt = info["step_evidence"]["receipts"][-1]
        self.data["captures"].append({"phase": self.phase, "expected_target_lines": ["Target core channels:", label],
                                      "receipt_id": self.receipt_id, "plan_info_before_settle": info,
                                      "provided_state_before_settle": self.snapshot(), "settle_ticks": 0})
        self.flush()
        assert receipt["receipt_id"] == self.receipt_id
        assert info["protected_scope_enforced"] is False and receipt["protected_observation"] is None
        assert info["plan"]["steps"][0]["status"] == "pending"
        observation = receipt["target_observation"]
        if self.phase in {"matched", "differ"}:
            expected = "channels_match" if self.phase == "matched" else "channels_differ"
            assert observation["status"] == expected and observation["validity"] == "recorded"
            assert observation["user_goal_verified"] is False and observation["current_scene_verified"] is False
        elif self.phase == "stale":
            assert observation["status"] == "channels_differ" and observation["validity"] == "stale"
        else:
            assert self.work.rotation_mode == "ZYX"
            assert observation is None and receipt["target_expectation"]["availability"] == "unavailable"

    def capture(self) -> None:
        row = self.data["captures"][-1]
        label = STAGES[self.stage_index][1]
        seen = self.data["formatter_draws"].get(self.phase + ":" + label)
        row["actual_formatter_draw"] = copy.deepcopy(seen)
        row["provided_state_before_screenshot"] = self.snapshot()
        row["plan_info_before_screenshot"] = self.inspect()
        row["ui_geometry"] = {"window": [self.window.width, self.window.height],
                              "area": [self.area.x, self.area.y, self.area.width, self.area.height],
                              "regions": [{"type": region.type, "x": region.x, "y": region.y,
                                           "width": region.width, "height": region.height,
                                           "category": region.active_panel_category if region.type == "UI" else None}
                                          for region in self.area.regions]}
        self.flush()
        assert seen is not None and seen["count"] >= 2 and seen["receipt_id"] == self.receipt_id
        assert row["provided_state_before_screenshot"] == row["provided_state_before_settle"]
        assert row["plan_info_before_screenshot"] == row["plan_info_before_settle"]
        assert object_state(self.protected) == self.data["provided_protected_baseline"]
        diagnostic = self.folder / f"sidebar-{self.phase}-blender-diagnostic.png"
        path = self.folder / f"sidebar-{self.phase}.png"
        assert not path.exists() and not diagnostic.exists()
        assert path.parent.resolve() == diagnostic.parent.resolve() == self.folder.resolve()
        with bpy.context.temp_override(window=self.window, area=self.area):
            redraw = bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            row["owned_window_redraw_swap"] = sorted(redraw)
            self.flush()
            result = bpy.ops.screen.screenshot(filepath=str(diagnostic), check_existing=False)
        diagnostic_raw = owned_file(diagnostic, maximum=8 * 1024 * 1024)
        row["native_screenshot_diagnostic"] = {
            "path": str(diagnostic), "sha256": sha256(diagnostic_raw), "bytes": len(diagnostic_raw),
            "operator_result": sorted(result), "scope": "Diagnostic only; no nonblank or label-visibility acceptance",
        }
        self.flush()
        assert redraw == result == {"FINISHED"}
        assert len(diagnostic_raw) >= 24 and diagnostic_raw[:8] == b"\x89PNG\r\n\x1a\n"
        row["native_screenshot_diagnostic"]["width"], row["native_screenshot_diagnostic"]["height"] = struct.unpack(
            ">II", diagnostic_raw[16:24])
        manifest = self.data["private_display"]["manifest"]
        window_tree = self.external("private_x11_root_window_tree",
                                   ["/usr/bin/xwininfo", "-display", manifest["display"], "-root", "-tree"])
        row["private_window_tree_command_index"] = len(self.data["external_commands"]) - 1
        assert window_tree["stdout"].strip()
        self.external("private_x11_root_capture", ["/usr/bin/import", "-display", manifest["display"],
                      "-window", "root", "-silent", "-depth", "8", "PNG24:" + str(path)])
        raw = owned_file(path, maximum=8 * 1024 * 1024)
        row["screenshot"] = {"path": str(path), "sha256": sha256(raw), "bytes": len(raw),
                             "capture_method": "Explicit owned private X11 root through /usr/bin/import",
                             "width": None, "height": None, "visual_review": "REQUIRED: original primary PNG retained"}
        if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
            row["screenshot"]["width"], row["screenshot"]["height"] = struct.unpack(">II", raw[16:24])
        self.flush()
        metrics = self.external("primary_unique_colors_and_pixel_signature",
                                ["/usr/bin/identify", "-format", "%k %#", str(path)])
        row["primary_metrics_command_index"] = len(self.data["external_commands"]) - 1
        row["provided_state_after_screenshot"] = self.snapshot()
        row["plan_info_after_screenshot"] = self.inspect()
        self.flush()  # Preserve PNG and raw receipts before result assertions.
        assert 0 < len(raw) <= 8 * 1024 * 1024
        width, height = row["screenshot"]["width"], row["screenshot"]["height"]
        assert width is not None and height is not None and 640 <= width <= 1600 and 640 <= height <= 1200
        assert (width, height) == (manifest["screen_width"], manifest["screen_height"])
        previous = {capture["screenshot"]["pixel_signature"] for capture in self.data["captures"][:-1]}
        row["screenshot"].update(usable_pixel_metrics(metrics["stdout"], previous))
        self.flush()
        assert row["provided_state_after_screenshot"] == row["provided_state_before_screenshot"]
        assert row["plan_info_after_screenshot"] == row["plan_info_before_screenshot"]
        row["captured"] = True
        self.flush()

    def tick(self) -> float | None:
        try:
            if self.runtime is None:
                self.prepare()
                return .25
            self.settle_ticks += 1
            row = self.data["captures"][-1]
            row["settle_ticks"] = self.settle_ticks
            regions = [region for region in self.area.regions if region.type == "UI"]
            assert len(regions) == 1
            region = regions[0]
            region.active_panel_category = CATEGORY
            self.area.tag_redraw()
            self.flush()
            if self.settle_ticks < 8:
                return .25
            assert region.width >= 200 and region.height >= 640, "Sidebar task box is not exposed"
            self.capture()
            self.stage_index += 1
            if self.stage_index < len(STAGES):
                self.begin_stage()
                return .25
            self.data["completed"] = True
            self.data["termination"]["requested_exit_code"] = 0
            self.flush()
            evidence = self.folder / "artist-sidebar-evidence.json"
            print("BLENDER_ARTIST_TARGET_SIDEBAR_OK " + json.dumps({
                "blender_version": bpy.app.version_string, "evidence_file": str(evidence),
                "evidence_sha256": sha256(evidence.read_bytes()), "original_private_window_screenshots": 4,
                "native_screenshot_diagnostics": 4, "primary_blank_and_repeated_pixels_rejected": True,
                "states": [row["phase"] for row in self.data["captures"]],
                "screenshots": [row["screenshot"] for row in self.data["captures"]],
                "diagnostics": [row["native_screenshot_diagnostic"] for row in self.data["captures"]],
                **self.data["claims"]}, allow_nan=False), flush=True)
            self.terminate(0)
        except BaseException as error:
            try:
                self.data["completed"] = False
                self.data["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
                self.flush()
                traceback.print_exc()
            finally:
                self.terminate(1)

    def terminate(self, status: int) -> NoReturn:
        exit_code = 1
        try:
            # Restoring this pure Python observer invokes no native shutdown or
            # save callbacks. The disposable process is then released by the OS.
            if self.ui is not None and self.original_formatter is not None:
                self.ui._target_channels_label = self.original_formatter
            self.data["termination"]["requested_exit_code"] = status
            self.flush()
            exit_code = status
        except BaseException:
            traceback.print_exc()
        finally:
            owned_process_exit(exit_code)


def main() -> None:
    fixture = None
    try:
        folder = Path(tempfile.gettempdir()) / "artist-sidebar-evidence"
        folder.mkdir()
        fixture = SidebarFixture(folder)
        # These supported settings belong only to this unsaved factory process.
        # Fixture termination bypasses implicit quit.blend serialization.
        fixture.data["requested_factory_preferences"] = {"use_preferences_save": False,
                                                        "use_auto_save_temporary_files": False, "show_splash": False}
        fixture.flush()
        # The reviewed native display gate precedes every bpy.context access.
        fixture.data["private_display"] = private_display_manifest()
        fixture.flush()
        assert fixture.data["process_instance"] and not bpy.app.background
        for key in ("TEMP", "TMP", "TMPDIR"):
            assert Path(os.environ[key]).resolve() == folder.parent
        for key in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
            assert Path(os.environ[key]).resolve().parent == folder.parent
        preferences = bpy.context.preferences
        preferences.use_preferences_save = False
        preferences.filepaths.use_auto_save_temporary_files = False
        preferences.view.show_splash = False
        fixture.data["factory_preferences"] = {
            "use_preferences_save": preferences.use_preferences_save,
            "use_auto_save_temporary_files": preferences.filepaths.use_auto_save_temporary_files,
            "show_splash": preferences.view.show_splash,
        }
        fixture.flush()
        assert fixture.data["factory_preferences"] == fixture.data["requested_factory_preferences"]
        bpy.app.timers.register(fixture.tick, first_interval=1.)
    except BaseException as error:
        try:
            if fixture is not None:
                fixture.data["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
                fixture.flush()
            traceback.print_exc()
        finally:
            if fixture is not None:
                fixture.terminate(1)
            owned_process_exit(1)


if __name__ == "__main__":
    main()
