"""Persistent permissions, native saves and checkpoint reopen in owned Blender processes.

Only scripts/run_blender_checks.py launches this interactive fixture. Its TCP
worker has no Blender references. All bridge calls use the registered executor
timer on the private test desktop. The master switch is exercised through the
local operator's confirmed execution path, without synthesizing mouse clicks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import traceback
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = "blender_codex_bridge"
WRITER_MARKER = "BLENDER_PERSISTENT_SAVE_WRITER_OK "
READER_MARKER = "BLENDER_PERSISTENT_SAVE_READER_OK "
DANGEROUS = ("DELETE_OBJECTS", "EXECUTE_PYTHON", "ACCESS_EXTERNAL_FILES", "SAVE_PROJECT")
PHASES = ("writer", "normal_restart", "crash_restart")
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_REPLY_BYTES = 256 * 1024
TEXTURE_NAME = "Owned persistent-save texture"


def fingerprint(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    assert 0 < len(data) <= MAX_FILE_BYTES, "Unexpected owned fixture file size"
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def tiny_png():
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    header = struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
    row = b"\x00\xff\x00\x00\xff\x00\x00\xff\xff"
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(row * 2)) + chunk(b"IEND", b"")


def rpc_worker(port, request, outcome):
    """Bounded loopback exchange. This thread never calls Blender APIs."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=20.) as connection:
            connection.sendall(json.dumps(request, allow_nan=False).encode() + b"\n")
            with connection.makefile("rb") as reader:
                raw = reader.readline(MAX_REPLY_BYTES + 1)
        assert 0 < len(raw) <= MAX_REPLY_BYTES and raw.endswith(b"\n"), "No bounded terminal reply"
        response = json.loads(raw)
        assert response["id"] == request["id"] and response["protocol_version"] == "1.0"
        assert type(response["ok"]) is bool
        outcome["response"] = response
    except Exception as error:
        outcome["error"] = error


class Scenario:
    def __init__(self, bpy, prefs, runtime, bundle, phase, master, token, attest_installation=None):
        self.bpy = bpy
        self.prefs = prefs
        self.runtime = runtime
        self.bundle = bundle
        self.phase = phase
        self.master = master
        self.token = token
        self.attest_installation = attest_installation
        self.deadline = time.monotonic() + 100.
        self.approved = bundle / "approved projects"
        self.outside = bundle / "outside approved root"
        self.first = self.approved / "first save.blend"
        self.second = (self.outside if master else self.approved) / "saved as.blend"
        self.state_file = bundle / (phase + ".json")
        self.stage = "start"
        self.evidence = {
            "phase": phase,
            "master": master,
            "blender_version": bpy.app.version_string,
            "build_hash": bpy.app.build_hash.decode("ascii"),
            "platform": sys.platform,
            "process_id": os.getpid(),
            "process_instance": token,
            "using_registered_executor_timer": bpy.app.timers.is_registered(runtime.executor._timer_callback),
            "methods": [],
        }
        assert self.evidence["using_registered_executor_timer"]
        self.flow = self.writer() if phase == "writer" else self.reader()
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            self.port = port.getsockname()[1]
        assert runtime.start_server("127.0.0.1", self.port, request_timeout=18.) == ("127.0.0.1", self.port)

    def call(self, method, params=None, *, error_codes=()):
        assert len(self.evidence["methods"]) < 72
        request = {"id": f"save-{self.phase}-{len(self.evidence['methods'])}", "method": method,
                   "params": {} if params is None else params, "protocol_version": "1.0", "timeout_ms": 18000}
        outcome = {}
        thread = threading.Thread(target=rpc_worker, args=(self.port, request, outcome), daemon=True)
        thread.start()
        while thread.is_alive():
            yield
        if "error" in outcome:
            raise outcome["error"]
        response = outcome["response"]
        self.evidence["methods"].append({"method": method, "ok": response["ok"],
                                         "code": response.get("error", {}).get("code")})
        if error_codes:
            assert not response["ok"] and response["error"]["code"] in error_codes, response
            assert response["error"]["message"], response
            return response["error"]
        assert response["ok"], response
        return response["result"]

    def matching_scope(self, *, before_crash):
        from blender_codex_bridge.permissions import unrestricted_project_texture_paths

        assert self.prefs.all_dangerous_permissions is self.master
        assert self.prefs.allow_unrestricted_project_texture_paths is self.master
        assert unrestricted_project_texture_paths(self.prefs) is self.master
        assert self.prefs.allow_save_project is (not self.master)
        assert self.prefs.allow_external_files is (not self.master)
        assert self.prefs.allow_execute_python is False and self.prefs.allow_delete_objects is False
        assert Path(self.prefs.project_directory) == self.approved
        assert Path(self.prefs.texture_directory) == self.approved
        assert self.prefs.allow_edit_animation is before_crash
        status = yield from self.call("bridge.status")
        expected = (self.master, self.master, True, True)
        assert tuple(status["permissions"][key] for key in DANGEROUS) == expected
        self.evidence["restored_scope"] = dict(zip(DANGEROUS, expected, strict=True))

    def dialog_context(self, area_type):
        for window in self.bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == area_type:
                    region = next((region for region in area.regions if region.type == "WINDOW"), None)
                    if region is not None:
                        return {"window": window, "area": area, "region": region}
        return None

    def inspect_dialog(self):
        bpy = self.bpy
        target = self.first
        assert (yield from self.call("project.save_dialog_state"))["state"] == "closed"
        context = self.dialog_context("VIEW_3D")
        assert context is not None, "Save As requires a stock Blender window"
        with bpy.context.temp_override(**context):
            result = bpy.ops.wm.save_as_mainfile("INVOKE_DEFAULT", filepath=str(target), check_existing=True)
        assert result == {"RUNNING_MODAL"}, result
        until = time.monotonic() + 10.
        while time.monotonic() < until:
            state = yield from self.call("project.save_dialog_state")
            if state["state"] == "open":
                break
            assert state["state"] == "closed", state
            yield
        else:
            raise AssertionError("The native Save As dialog never became observable")
        assert Path(state["filepath"]) == target and state["filename"] == target.name, state
        assert Path(state["directory"]) == target.parent, state
        proposed_filepath = state["filepath"]
        assert not target.exists() and not bpy.data.filepath, "Reading the open Save As dialog wrote a file"
        self.evidence["native_dialog"] = {"closed_before": True, "path_read": str(target), "file_not_written": True}
        if self.attest_installation is None:
            yield from self.cancel_dialog()
            assert not target.exists() and not bpy.data.filepath, "Passive dialog inspection wrote a file"
        return proposed_filepath

    def cancel_dialog(self):
        bpy = self.bpy
        context = self.dialog_context("FILE_BROWSER")
        assert context is not None
        with bpy.context.temp_override(**context):
            assert bpy.ops.file.cancel() == {"FINISHED"}
        until = time.monotonic() + 10.
        while time.monotonic() < until:
            state = yield from self.call("project.save_dialog_state")
            if state["state"] == "closed":
                break
            yield
        else:
            raise AssertionError("The canceled Save As dialog remained open")
        self.evidence["native_dialog"]["closed_after_cancel"] = True

    def save(self, target, *, current=False, proposed_filepath=None):
        params = {} if current else {"filepath": proposed_filepath or str(target), "overwrite": False}
        result = yield from self.call("project.save", params)
        assert result["saved"] is True and result["project_saved"] is True, result
        assert Path(result["filepath"]) == target and Path(self.bpy.data.filepath) == target, result
        proof = fingerprint(target)
        assert result["file_bytes"] == proof["bytes"], result
        recovery = result["recovery_checkpoint"]
        assert recovery["state"] == "available", f"Native save succeeded but recovery evidence is unavailable: {recovery!r}"
        assert Path(recovery["filepath"]) == target and recovery["verification"] == "saved_bytes", recovery
        assert recovery["file_sha256"] == proof["sha256"] and recovery["file_bytes"] == proof["bytes"], recovery
        return proof

    def checkpoint(self, target, proof):
        result = yield from self.call("project.checkpoint_status")
        assert result["state"] == "available" and Path(result["filepath"]) == target, result
        assert result["file_sha256"] == proof["sha256"] and result["file_bytes"] == proof["bytes"], result
        assert result["verification"] == "saved_bytes" and result["fresh_process_reopen_verified"] is False, result
        assert isinstance(result["checkpoint_id"], str) and result["checkpoint_id"], result
        return result["checkpoint_id"]

    def check_texture_scope(self):
        bpy, prefs = self.bpy, self.prefs
        target = self.outside / "scope test texture.png"
        with target.open("xb") as stream:
            stream.write(tiny_png())
        proof = fingerprint(target)
        yield from self.call("toolsets.enable", {"name": "materials"})
        params = {"filepath": str(target), "new_name": TEXTURE_NAME}
        before = len(bpy.data.images)
        if self.master:
            prefs.allow_unrestricted_project_texture_paths = False
        yield from self.call("image.load", params, error_codes=("PERMISSION_DENIED",))
        assert bpy.data.images.get(TEXTURE_NAME) is None and len(bpy.data.images) == before
        evidence = {"outside_folder_denied": True, "with_master_only": self.master, "override_loaded": False}
        if self.master:
            prefs.allow_unrestricted_project_texture_paths = True
            result = yield from self.call("image.load", params)
            image = bpy.data.images[TEXTURE_NAME]
            assert result["loaded"] is True and result["file_written"] is False and len(bpy.data.images) == before + 1
            assert image.has_data and Path(image.filepath) == target and tuple(image.size) == (2, 2)
            evidence["override_loaded"] = True
        assert fingerprint(target) == proof
        self.evidence["texture_folder_scope"] = {**evidence, "source_file_unchanged": True, "source": proof}

    def writer(self):
        bpy, prefs = self.bpy, self.prefs
        self.stage = "factory defaults and individual-grant denial"
        assert not bpy.data.filepath and prefs.all_dangerous_permissions is False
        assert prefs.allow_unrestricted_project_texture_paths is False and not prefs.project_directory
        self.approved.mkdir()
        self.outside.mkdir()
        prefs.allow_save_project = False
        prefs.allow_external_files = False
        prefs.allow_edit_animation = False
        yield from self.call("project.save", {"filepath": str(self.first)}, error_codes=("PERMISSION_DENIED",))
        assert not self.first.exists()

        self.stage = "explicit local consent and blank folder denial"
        if self.master:
            assert bpy.ops.blender_codex_bridge.enable_dangerous_permissions("EXEC_DEFAULT") == {"FINISHED"}
            assert prefs.all_dangerous_permissions is True
        else:
            prefs.allow_save_project = True
            prefs.allow_external_files = True
        assert not prefs.allow_unrestricted_project_texture_paths and not prefs.project_directory
        # Blank does not authorize a path, even if the dangerous master is on.
        yield from self.call("project.save", {"filepath": str(self.first)},
                             error_codes=("INVALID_ARGUMENT", "PERMISSION_DENIED"))
        assert not self.first.exists()
        prefs.project_directory = str(self.approved)
        prefs.texture_directory = str(self.approved)
        yield from self.call("project.save", {"filepath": str(self.outside / "blocked.blend")},
                             error_codes=("INVALID_ARGUMENT", "PERMISSION_DENIED"))
        assert not (self.outside / "blocked.blend").exists()

        self.stage = "real Save As dialog inspection"
        proposed_filepath = yield from self.inspect_dialog()

        self.stage = "first save and save current"
        missing = yield from self.call("project.save", error_codes=("INVALID_ARGUMENT",))
        assert missing["context"]["requires_filepath"] is True, missing
        cube = bpy.data.objects["Cube"]
        assert cube.type == "MESH" and len(cube.data.vertices) == 8
        cube.location = (1., 2., 3.)
        if self.attest_installation is not None:
            active = yield from self.call("project.save_dialog_state")
            assert active["state"] == "open" and Path(active["filepath"]) == self.first, active
        first = yield from self.save(self.first, proposed_filepath=proposed_filepath)
        if self.attest_installation is not None:
            active = yield from self.call("project.save_dialog_state")
            assert active["state"] in {"open", "closed"}, active
            if active["state"] == "open":
                yield from self.cancel_dialog()
            assert fingerprint(self.first) == first and Path(bpy.data.filepath) == self.first
            self.evidence["native_dialog"].update(saved_while_dialog_open=True, state_after_save=active["state"])
        self.evidence["native_dialog"]["returned_path_used_for_first_save"] = True
        first_id = yield from self.checkpoint(self.first, first)
        cube.location = (2., 3., 4.)
        current = yield from self.save(self.first, current=True)
        assert current["sha256"] != first["sha256"]

        self.stage = "Save As with no extra arm and literal path verification"
        if self.master:
            prefs.allow_unrestricted_project_texture_paths = True
        cube.location = (3., 4., 5.)
        bpy.context.scene["bridge_persistent_fixture"] = self.token
        second = yield from self.save(self.second)
        assert fingerprint(self.first) == current and second["sha256"] != current["sha256"]
        checkpoint_id = yield from self.checkpoint(self.second, second)
        assert checkpoint_id != first_id
        yield from self.call("project.save", {"filepath": str(self.first), "overwrite": False},
                             error_codes=("INVALID_ARGUMENT",))
        assert fingerprint(self.first) == current and fingerprint(self.second) == second
        yield from self.matching_scope(before_crash=False)
        self.evidence.update(first_save=first, save_current=current, save_as=second,
                             checkpoint_id=checkpoint_id, filepath=str(self.second), normal_exit_requested=True)

    def reader(self):
        bpy = self.bpy
        self.stage = "restore persisted scope before Blender project load"
        until = time.monotonic() + 5.
        while bpy.data.is_dirty and time.monotonic() < until:
            yield
        assert Path(bpy.data.filepath) == self.first and not bpy.data.is_dirty, (
            f"Owned reader baseline after startup: filepath_matches={Path(bpy.data.filepath) == self.first}, "
            f"dirty={bpy.data.is_dirty}, mode={bpy.context.mode}, scenes={len(bpy.data.scenes)}"
        )
        assert tuple(bpy.data.objects["Cube"].location) == (2., 3., 4.)
        self.evidence["owned_baseline_was_prior_revision"] = True
        writer_file = self.bundle / "writer.json"
        with writer_file.open("rb") as stream:
            writer = json.loads(stream.read(64 * 1024))
        assert writer["master"] is self.master and writer["process_instance"] != self.token
        yield from self.matching_scope(before_crash=self.phase == "crash_restart")
        if self.phase == "crash_restart":
            with (self.bundle / "normal_restart.json").open("rb") as stream:
                previous = json.loads(stream.read(64 * 1024))
            assert previous["abrupt_exit_requested"] and previous["process_instance"] != self.token

        self.stage = "discover and reopen exactly the last verified checkpoint"
        proof = fingerprint(self.second)
        checkpoint_id = yield from self.checkpoint(self.second, proof)
        assert checkpoint_id == writer["checkpoint_id"] and proof == writer["save_as"]
        yield from self.call("project.checkpoint_reopen", {"checkpoint_id": checkpoint_id, "confirm_reopen": False},
                             error_codes=("INVALID_ARGUMENT",))
        assert Path(bpy.data.filepath) == self.first
        assert tuple(bpy.data.objects["Cube"].location) == (2., 3., 4.)
        reopened = yield from self.call("project.checkpoint_reopen",
                                        {"checkpoint_id": checkpoint_id, "confirm_reopen": True})
        assert reopened["reopened"] is True and Path(reopened["filepath"]) == self.second, reopened
        assert Path(bpy.data.filepath) == self.second and fingerprint(self.second) == proof
        assert tuple(bpy.data.objects["Cube"].location) == (3., 4., 5.)
        assert len(bpy.data.objects["Cube"].data.vertices) == 8
        assert bpy.context.scene["bridge_persistent_fixture"] == writer["process_instance"]
        assert bpy.app.timers.is_registered(self.runtime.executor._timer_callback)
        assert (yield from self.checkpoint(self.second, proof)) == checkpoint_id
        self.evidence.update(checkpoint_id=checkpoint_id, filepath=str(self.second), checkpoint_file=proof,
                             reopened_native_scene_verified=True, same_listener_after_reopen=True)

        self.stage = "abrupt-exit durability or immediate master revocation"
        if self.phase == "normal_restart":
            self.stage = "texture folder policy with the separate local override"
            yield from self.check_texture_scope()
            self.stage = "dirty reopen refusal before abrupt termination"
            context = self.dialog_context("VIEW_3D")
            assert context is not None
            with bpy.context.temp_override(**context):
                layer = bpy.context.view_layer
                cube = layer.objects["Cube"]
                for obj in layer.objects:
                    obj.select_set(obj == cube, view_layer=layer)
                layer.objects.active = cube
                # This direct native data write needs a native undo step, as a
                # real editor edit would, to mark the project as modified.
                assert bpy.ops.ed.undo_push(message="Owned fixture before unsaved edit") == {"FINISHED"}
                cube.location = (3., 4., 6.)
                assert bpy.ops.ed.undo_push(message="Owned fixture unsaved edit") == {"FINISHED"}
            dirty_location = tuple(bpy.data.objects["Cube"].location)
            assert dirty_location == (3., 4., 6.), f"Fixture Cube location after edit: {dirty_location!r}"
            assert bpy.data.is_dirty, "Blender did not mark the native undoable edit dirty"
            yield from self.call("project.checkpoint_reopen", {"checkpoint_id": checkpoint_id, "confirm_reopen": True},
                                 error_codes=("BLENDER_CONTEXT_ERROR",))
            assert tuple(bpy.data.objects["Cube"].location) == dirty_location
            assert fingerprint(self.second) == proof
            # Detect persistence of a newly changed setting, not just survival
            # of the settings the writer left after its normal exit.
            self.prefs.allow_edit_animation = True
            yield from self.matching_scope(before_crash=True)
            self.evidence.update(dirty_reopen_denied=True, authored_unsaved_edit_preserved_until_exit=True,
                                 abrupt_exit_requested=True)
        elif self.master:
            assert bpy.data.images.get(TEXTURE_NAME) is None, "An unsaved texture incorrectly reappeared after restart"
            assert bpy.ops.blender_codex_bridge.disable_dangerous_permissions("EXEC_DEFAULT") == {"FINISHED"}
            assert not self.prefs.all_dangerous_permissions and not self.prefs.allow_unrestricted_project_texture_paths
            status = yield from self.call("bridge.status")
            assert all(status["permissions"][key] is False for key in DANGEROUS)
            target = self.outside / "revoked.blend"
            yield from self.call("project.save", {"filepath": str(target)}, error_codes=("PERMISSION_DENIED",))
            assert not target.exists()
            self.evidence["master_revocation_verified"] = True
        else:
            self.evidence["master_revocation_verified"] = False

    def finish(self):
        if self.attest_installation is not None:
            self.evidence["installed_addon"] = self.attest_installation()
        self.evidence["completed"] = True
        artifact = json.dumps(self.evidence, allow_nan=False, sort_keys=True)
        assert len(artifact) < 64 * 1024
        with self.state_file.open("x", encoding="utf-8") as stream:
            stream.write(artifact + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        marker = WRITER_MARKER if self.phase == "writer" else READER_MARKER
        print(marker + artifact, flush=True)
        if self.phase == "normal_restart":
            sys.stderr.flush()
            os._exit(0)  # Owned process only; no Blender teardown or preference flush.
        window = self.bpy.context.window_manager.windows[0]
        with self.bpy.context.temp_override(window=window):
            self.bpy.ops.wm.quit_blender("EXEC_DEFAULT")

    def tick(self):
        try:
            assert threading.current_thread() is threading.main_thread()
            assert time.monotonic() < self.deadline, f"Timed out in {self.stage}"
            try:
                next(self.flow)
            except StopIteration:
                self.finish()
                return None
            return .025
        except Exception:
            print(f"Persistent save smoke failed in {self.stage}", file=sys.stderr, flush=True)
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(1)


def clean_reader_baseline(bpy, bundle):
    """Load a separately verified fixture artifact before enabling the Bridge."""
    assert not bpy.data.filepath, "Expected runner-owned unsaved factory startup"
    print(f"Owned reader startup before baseline: filepath_empty=True, dirty={bpy.data.is_dirty}, "
          f"mode={bpy.context.mode}, scenes={len(bpy.data.scenes)}", flush=True)
    with (bundle / "writer.json").open("rb") as stream:
        writer = json.loads(stream.read(64 * 1024))
    first = bundle / "approved projects" / "first save.blend"
    assert first.resolve(strict=True) == first and not first.is_symlink()
    assert fingerprint(first) == writer["save_current"]
    assert bpy.ops.wm.open_mainfile(filepath=str(first), load_ui=False, use_scripts=False) == {"FINISHED"}
    assert Path(bpy.data.filepath) == first
    assert tuple(bpy.data.objects["Cube"].location) == (2., 3., 4.)


def install_pinned_addon(bpy, configuration: Path, temporary: Path):
    """Install only the frozen package into this process's disposable script root."""
    assert configuration == temporary.parent.parent / "persistent-save-addon.json"
    assert not configuration.is_symlink() and configuration.is_file()
    with configuration.open("rb") as stream:
        raw = stream.read(512 * 1024 + 1)
    assert 0 < len(raw) <= 512 * 1024, "Unexpected add-on package configuration size"
    record = json.loads(raw)
    assert set(record) == {"path", "sha256", "members_sha256"}
    assert Path(record["path"]) == configuration.with_suffix(".zip")
    assert not Path(record["path"]).is_symlink()
    sys.path.insert(0, str(ROOT))
    from scripts.blender_installed_addon_probe_smoke import _archive, _installed_bytes

    owned = temporary / "package inputs with spaces"
    owned.mkdir(mode=0o700)
    archive, members = _archive(record, owned, "persistent save candidate")
    # Test and runner helpers may originate in the checkout. The product
    # package must be loaded only from Blender's isolated installed location.
    sys.path[:] = [entry for entry in sys.path if entry and not Path(entry).resolve().is_relative_to(ROOT)]
    scripts = Path(os.environ["BLENDER_USER_SCRIPTS"])
    root = scripts / "addons" / ADDON
    assert not root.exists() and not root.is_symlink()
    assert bpy.ops.preferences.addon_install(filepath=str(archive), overwrite=False) == {"FINISHED"}
    _installed_bytes(root, members)

    def attest():
        _installed_bytes(root, members)
        origins = {}
        for name, module in tuple(sys.modules.items()):
            if name == ADDON or name.startswith(ADDON + "."):
                file = Path(module.__file__).resolve(strict=True)
                assert file.is_relative_to(root.resolve())
                relative = file.relative_to(root.parent.resolve()).as_posix()
                assert relative in members
                origins[name] = relative
        assert origins.get(ADDON) == f"{ADDON}/__init__.py"
        assert origins.get(f"{ADDON}.runtime") == f"{ADDON}/runtime.py"
        return {"zip_sha256": record["sha256"], "member_count": len(members), "root": str(root),
                "module_origins": origins}

    return attest


def main():
    import addon_utils
    import bpy

    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=PHASES, required=True)
    parser.add_argument("--bridge-master", choices=("on", "off"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    parser.add_argument("--bridge-addon-config", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    token = os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    bundle = args.bridge_bundle.resolve(strict=True)
    assert re.fullmatch("[0-9a-f]{32}", token)
    assert not bpy.app.background and {"--factory-startup", "--disable-autoexec"} <= set(sys.argv)
    assert args.bridge_bundle.is_absolute() and not args.bridge_bundle.is_symlink()
    assert bundle.is_dir() and bundle.name == f"persistent_save_master_{args.bridge_master}-bundle"
    config = Path(os.environ["BLENDER_USER_CONFIG"])
    assert config == bundle / "bridge-config" and config.is_dir() and not config.is_symlink()
    temp = Path(os.environ["TEMP"])
    assert temp.parent == bundle.parent and temp.name == f"persistent_save_master_{args.bridge_master}-{args.bridge_phase}-temp"
    for name in ("BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        path = Path(os.environ[name])
        assert path.parent == temp and path.is_dir() and not path.is_symlink()
    assert not (bundle / (args.bridge_phase + ".json")).exists()
    assert not any(name == ADDON or name.startswith(ADDON + ".") for name in sys.modules)
    if args.bridge_phase != "writer":
        clean_reader_baseline(bpy, bundle)
    attest_installation = None
    if args.bridge_addon_config is None:
        sys.path.insert(0, str(ROOT / "addon"))
    else:
        attest_installation = install_pinned_addon(bpy, args.bridge_addon_config, temp)
    # Discovery/import goes through Blender's normal add-on registration hook.
    assert addon_utils.enable(ADDON, default_set=True, persistent=True) is not None
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime

    if attest_installation is not None:
        attest_installation()
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
    prefs = get_preferences()
    assert prefs is not None
    scenario = Scenario(bpy, prefs, get_runtime(), bundle, args.bridge_phase, args.bridge_master == "on", token,
                        attest_installation)
    bpy.app.timers.register(scenario.tick, first_interval=.05, persistent=True)


if __name__ == "__main__":
    main()
