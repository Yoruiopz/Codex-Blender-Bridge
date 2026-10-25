"""Fresh installed-candidate artist guards over the actual loopback queue.

Qualification driver only: no checkout product imports or replaced runtime services.
The two domains run in separate owned private interactive processes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import socket
import stat
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import bpy

ROOT = Path(__file__).resolve().parents[1]
MODULE = "blender_codex_bridge"
ACCEPTED_COMMIT = "8d07ad898ba92c5e94db57b1562fefef9c8e0e1c"
ACCEPTED_TREE = "4a9dccf8b3c9a6a05aad1d1d19187381fb4e6bbb"
ACCEPTED_ZIP_SHA256 = "0afc38c1315fedc952c3c657c82f510c720ce79a669df319f8278c959f67eaf4"
MARKERS = {"weights": "BLENDER_INSTALLED_ARTIST_WEIGHTS_OK ",
           "curve": "BLENDER_INSTALLED_ARTIST_CURVE_OK "}
OWNED_ATTESTED = False
PRIVATE_LAUNCHER_SHA256 = "d243355385d6179d85d3fe5adecd8c2e752f470b7d6cf686b71934f31e7e5aa9"
PRIVATE_XORG_CONFIG_SHA256 = "fd963752e6e6595d7f3c6602928d4daca3276ef76156f4713a84fc21569ba7c6"

def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

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


def load_helpers():
    """Load fixture data oracles only, before removing every checkout import path."""
    result, sources = {}, {"scripts/blender_artist_sidebar_smoke.py":
                           sha256((ROOT / "scripts/blender_artist_sidebar_smoke.py").read_bytes())}
    for name, filename in (("package", "blender_installed_addon_probe_smoke.py"),
                           ("weights", "blender_weight_edit_guard_smoke.py"),
                           ("curve", "blender_animation_intent_smoke.py")):
        path = ROOT / "scripts" / filename
        sources["scripts/" + filename] = sha256(path.read_bytes())
        spec = importlib.util.spec_from_file_location("_installed_guard_oracle_" + name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result[name] = module
    assert not any(name == MODULE or name.startswith(MODULE + ".") for name in sys.modules)
    return SimpleNamespace(**result), sources


class QueuedTCP:
    """The client thread sends JSON only; Blender's real queue runs on the main thread."""

    def __init__(self, runtime, phase):
        self.runtime, self.phase, self.sequence = runtime, phase, 0
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        runtime.start_server("127.0.0.1", self.port, request_timeout=30.)

    def call(self, method, params):
        self.sequence += 1
        identifier = self.phase + "-" + str(self.sequence)
        request = {"id": identifier, "method": method, "params": copy.deepcopy(params),
                   "protocol_version": "1.0", "timeout_ms": 30000}
        result = {}

        def client():
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=30.) as connection:
                    connection.sendall(json.dumps(request, allow_nan=False).encode() + b"\n")
                    with connection.makefile("rb") as stream:
                        payload = stream.readline(4 * 1024 * 1024 + 1)
                    assert payload.endswith(b"\n") and len(payload) <= 4 * 1024 * 1024
                    result["response"] = json.loads(payload)
            except BaseException:
                result["failure"] = traceback.format_exc()

        thread = threading.Thread(target=client, daemon=True)
        thread.start()
        deadline = time.monotonic() + 35.
        while thread.is_alive() and time.monotonic() < deadline:
            self.runtime.executor._drain_timer()
            time.sleep(.005)
        thread.join(timeout=.1)
        assert not thread.is_alive() and "failure" not in result, result
        response = result["response"]
        assert response["id"] == identifier and type(response["ok"]) is bool
        return {"request": request, "response": response,
                "transport": "127.0.0.1 TCP; genuine queued main-thread executor"}


def checkpoint_state(runtime):
    manager = runtime.checkpoints
    assert manager._pending is None
    return {"sequence": manager._sequence,
            "pending": None,
            "steps": [{"label": step.label, "before_marker": step.before_marker,
                       "sequence": step.sequence, "kind": step.kind, "attempts": step.attempts}
                      for step in manager._undo_steps],
            "markers": [[int(scene.session_uid), scene.get("_codex_bridge_undo_marker")]
                        for scene in bpy.data.scenes]}


class InstalledGuards:
    def __init__(self, phase, bundle, private, helpers, helper_sources):
        self.phase, self.bundle, self.helpers = phase, bundle, helpers
        self.path = Path(tempfile.gettempdir()) / "installed-artist-guards.json"
        assert not self.path.exists()
        self.runtime = self.prefs = self.client = self.installed = None
        self.permission_origin = None
        self.report = {"phase": phase, "completed": False, "private_display": private,
                       "accepted_candidate_commit": ACCEPTED_COMMIT, "accepted_candidate_tree": ACCEPTED_TREE,
                       "supporting_commit": os.environ["BRIDGE_TEST_SUPPORT_COMMIT"],
                       "support_helper_sources": helper_sources,
                       "support_script_sha256": sha256(Path(__file__).read_bytes()),
                       "calls": [], "blender_version": bpy.app.version_string,
                       "build_hash": bpy.app.build_hash.decode(), "project_saved": False,
                       "runtime_or_provider_replaced": False, "native_undo_invoked": False,
                       "scope": "Installed candidate only; queued supported-profile positive/denial/invalid requests and declared authored/history comparisons.",
                       "unqualified": ["native injected-failure compensation", "cancel/disconnect", "cold-context preservation",
                                       "durable recovery", "appearance", "full artist scenarios", "Windows", "1.0"]}

    def flush(self):
        raw = json.dumps(self.report, indent=2, allow_nan=False).encode()
        assert len(raw) <= 8 * 1024 * 1024
        self.path.write_bytes(raw + b"\n")

    def origin(self):
        assert self.runtime.permissions is self.runtime.executor.permissions
        current = (self.runtime, self.runtime.executor, self.runtime.permissions,
                   self.runtime.checkpoints, self.runtime.registry)
        assert all(first is second for first, second in zip(current, self.permission_origin, strict=True))
        self.helpers.package._installed_bytes(self.installed, self.members)

    def setup(self):
        import addon_utils

        config_path = Path(os.environ["BRIDGE_TEST_PACKAGE_PROBE_CONFIG"])
        with config_path.open("rb") as stream:
            raw = stream.read(512 * 1024 + 1)
        assert 0 < len(raw) <= 512 * 1024
        config = json.loads(raw)
        assert config["schema_version"] == 1 and set(config) == {"schema_version", "candidate", "previous"}
        record = config["candidate"]
        assert record["version"] == "0.7.0" and record["expected_tools"] == 268
        assert record["sha256"] == ACCEPTED_ZIP_SHA256, "Candidate ZIP is not the accepted exact CI artifact"
        assert self.helpers.package._expected_tool_names(record) is not None
        scripts = Path(os.environ["BLENDER_USER_SCRIPTS"]).resolve(strict=True)
        assert " " in str(scripts) and scripts.parent == Path(tempfile.gettempdir()).resolve()
        owned = scripts.parent / "candidate inputs with spaces"
        owned.mkdir(mode=0o700)
        archive, self.members = self.helpers.package._archive(record, owned, "candidate")
        assert not any(name == MODULE or name.startswith(MODULE + ".") for name in sys.modules)
        sys.path[:] = [entry for entry in sys.path if entry and not Path(entry).resolve().is_relative_to(ROOT)]
        assert bpy.ops.preferences.addon_install(filepath=str(archive), overwrite=False) == {"FINISHED"}
        addon_utils.modules_refresh()
        # Create the real in-memory preferences entry in this disposable profile.
        # use_preferences_save was disabled before installation; no prefs file is saved.
        module = addon_utils.enable(MODULE, default_set=True, persistent=True)
        assert module is not None and module.bl_info["version"] == (0, 7, 0)
        self.installed = scripts / "addons" / MODULE
        self.helpers.package._installed_bytes(self.installed, self.members)
        import importlib

        self.runtime = importlib.import_module(MODULE + ".runtime").get_runtime()
        self.prefs = bpy.context.preferences.addons[MODULE].preferences
        assert self.prefs.auto_start is False
        self.permission_origin = (self.runtime, self.runtime.executor, self.runtime.permissions,
                                  self.runtime.checkpoints, self.runtime.registry)
        permissions = importlib.import_module(MODULE + ".permissions")
        self.preference_names = tuple(permissions.PREFERENCE_PROPERTIES.values())
        self.original_preferences = {name: getattr(self.prefs, name) for name in self.preference_names}
        assert self.runtime.permissions is self.runtime.executor.permissions
        assert all(not self.runtime.permissions.snapshot()[name] for name in
                   ("DELETE_OBJECTS", "EXECUTE_PYTHON", "ACCESS_EXTERNAL_FILES"))
        for name in self.preference_names:
            setattr(self.prefs, name, name in {"allow_inspect_scene", "allow_edit_mesh" if self.phase == "weights" else "allow_edit_animation"})
        self.report.update(configuration_sha256=sha256(raw), candidate_zip_sha256=record["sha256"],
                           installed_members_sha256=self.members,
                           public_surface=self.helpers.package._public_tool_surface(self.runtime.registry, record),
                           permission_source="Original installed Runtime PermissionManager and real local add-on preference flags")
        self.client = QueuedTCP(self.runtime, self.phase)
        status = self.client.call("bridge.status", {})
        assert status["response"]["ok"] and status["response"]["result"]["addon_version"] == "0.7.0"
        enabled = self.client.call("toolsets.enable", {"name": "weights" if self.phase == "weights" else "animation"})
        assert enabled["response"]["ok"]
        self.report["transport_setup"] = [status, enabled]
        self.origin()

    def call(self, label, method, params, snapshot, expected, *, error=None):
        self.origin()
        before = snapshot()
        checkpoints = checkpoint_state(self.runtime)
        history = self.runtime.state.history(limit=50)
        row = {"label": label, "before": before, "expected": copy.deepcopy(expected),
               "checkpoint_before": checkpoints, "history_before": history}
        self.report["calls"].append(row)
        self.flush()
        try:
            row.update(self.client.call(method, params))
        finally:
            row.update(after=snapshot(), checkpoint_after=checkpoint_state(self.runtime),
                       history_after=self.runtime.state.history(limit=50))
            self.flush()
        response = row["response"]
        assert response["ok"] is (error is None), response
        if error is not None:
            assert response["error"]["code"] == error, response
            assert row["checkpoint_after"] == checkpoints, "A refused request changed checkpoint state"
        assert self.helpers.curve.same(row["after"], expected), label + ": complete declared projection changed"
        newest = row["history_after"][0]
        assert newest["tool"] == method and newest["success"] is (error is None)
        assert row["history_after"][1:] == history[:49], "A request lost or rewrote earlier history"
        assert not history or newest["operation_id"] != history[0]["operation_id"]
        if error is not None:
            assert newest["error_code"] == error
        else:
            result = response["result"]
            assert newest["recovery_evidence"] == result["recovery_evidence"]
        row["complete_prediction_and_history_verified"] = True
        self.origin()
        self.flush()
        return response.get("result")

    def prepare_checkpoint(self, snapshot):
        row = {"before": snapshot(), "original_intent_captured": False,
               "scope": "Explicit genuine TCP checkpoint before any frozen request; preparation can encode/synchronize Main."}
        self.report["preparation"] = row
        row.update(self.client.call("checkpoint.create", {"description": "Installed " + self.phase + " fixture setup"}))
        row["after"] = snapshot()
        assert row["response"]["ok"] and self.runtime.checkpoints._pending is None
        self.flush()

    def weights(self):
        helper = self.helpers.weights
        mesh = bpy.data.meshes.new("Installed Weight Mesh")
        mesh.from_pydata([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("Installed Weight Target", mesh)
        bpy.context.scene.collection.children[0].objects.link(obj)
        for name, weight in (("A", .25), ("B", .25), ("Locked", .125)):
            group = obj.vertex_groups.new(name=name)
            group.add((0, 1, 2), weight, "REPLACE")
            group.lock_weight = name == "Locked"
        sentinel = bpy.data.objects.new("Installed Protected Static", None)
        sentinel.location = (7., 8., 9.)
        bpy.context.scene.collection.objects.link(sentinel)

        def snapshot():
            return {"target": helper.preparation_snapshot(obj),
                    "protected": {"identity": self.helpers.curve.identity(sentinel),
                                  "location": list(sentinel.location), "rotation": list(sentinel.rotation_euler),
                                  "scale": list(sentinel.scale), "parent": self.helpers.curve.identity(sentinel.parent)},
                    "context": {"active": self.helpers.curve.identity(bpy.context.view_layer.objects.active),
                                "selection": [self.helpers.curve.identity(x) for x in bpy.context.view_layer.objects if x.select_get()],
                                "frame": [bpy.context.scene.frame_current, bpy.context.scene.frame_subframe], "mode": bpy.context.mode}}

        self.prepare_checkpoint(snapshot)
        request = {"object_name": obj.name, "group_name": "A", "vertex_indices": [0, 1], "weight": .5}
        expected = copy.deepcopy(snapshot())
        memberships = expected["target"]["target"]["memberships"]
        memberships[0][0][1] = memberships[1][0][1] = helper.bits(.5)
        assigned = self.call("assign", "weights.assign", request, snapshot, expected)
        assert assigned["recovery_evidence"]["owned_membership_verified"] == 2
        expected = copy.deepcopy(snapshot())
        expected["target"]["target"]["memberships"][:2] = [
            [[0, helper.bits(7/12)], [1, helper.bits(7/24)], [2, helper.bits(.125)]]] * 2
        self.call("normalize", "weights.normalize", {"object_name": obj.name, "group_names": ["A", "B"],
                                                    "vertex_indices": [0, 1]}, snapshot, expected)
        self.prefs.allow_edit_mesh = False
        self.call("permission_denial", "weights.assign", request, snapshot, snapshot(), error="PERMISSION_DENIED")
        self.prefs.allow_edit_mesh = True
        self.call("locked_group_scope", "weights.assign", {**request, "group_name": "Locked"},
                  snapshot, snapshot(), error="NOT_IMPLEMENTED")
        self.call("invalid_vertex_type", "weights.assign", {**request, "vertex_indices": [True]},
                  snapshot, snapshot(), error="INVALID_ARGUMENT")

    def curve(self):
        helper = self.helpers.curve
        action, work = helper.make_actor("Installed IntentActor", "Installed Motion", ((1., 0.), (11., 10.)))
        protected = bpy.data.objects.new("Installed Protected", None)
        protected.location = (20., 40., 0.)
        bpy.context.scene.collection.objects.link(protected)
        protected_action, _slot = helper.make_action("Installed Protected Motion", protected.name, ((1., 20.), (11., 30.)))
        protected_action.use_fake_user = True
        active = bpy.data.objects.new("Installed Unanimated Active", None)
        bpy.context.scene.collection.objects.link(active)
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        active.select_set(True)
        bpy.context.view_layer.objects.active = active
        oracle = SimpleNamespace(runtime=self.runtime, action=action, work=work, protected=protected,
                                 protected_action=protected_action, active=active)

        def snapshot():
            return helper.Fixture.snapshot(oracle)["authored"]

        self.prepare_checkpoint(snapshot)
        base = {"object_name": work.name, "data_path": "location", "index": 0}
        request = {**base, "keyframes": [{"frame": 11, "co": [11., 12.],
                                         "handle_left": [10., 11.], "handle_right": [14., 13.]}]}
        expected = helper.predict(snapshot(), action.as_pointer(), request)
        result = self.call("future_raw_co_handles", "animation.curve_edit", request, snapshot, expected)
        assert result["authored_profile"] == "RAW_FREE_POINT_V1"
        assert result["current_pose_revision_qualified"] is False
        assert result["recovery_evidence"]["native_update_attempts"] == 0
        self.call("exact_noop", "animation.curve_edit", request, snapshot, snapshot())
        self.prefs.allow_edit_animation = False
        self.call("permission_denial", "animation.curve_edit", request, snapshot, snapshot(), error="PERMISSION_DENIED")
        self.prefs.allow_edit_animation = True
        for label, changed in (("current_pose_scope", {**base, "keyframes": [{"frame": 1, "co": [1., 2.]}]}),
                               ("handle_conversion_scope", {**base, "keyframes": [{"frame": 11, "handle_left_type": "FREE"}]})):
            self.call(label, "animation.curve_edit", changed, snapshot, snapshot(), error="NOT_IMPLEMENTED")
        self.call("invalid_frame_type", "animation.curve_edit", {**base, "keyframes": [{"frame": True, "co": [11., 13.]}]},
                  snapshot, snapshot(), error="INVALID_ARGUMENT")

    def run(self):
        status = 1
        try:
            self.setup()
            getattr(self, self.phase)()
            self.origin()
            self.report.update(completed=True, installed_queued_guard_qualified=True,
                               installed_module_origins_verified=True)
            status = 0
        except BaseException:
            self.report["failure"] = traceback.format_exc()
        finally:
            if self.runtime is not None:
                self.runtime.stop_server()
            if self.prefs is not None and hasattr(self, "original_preferences"):
                for name, value in self.original_preferences.items():
                    setattr(self.prefs, name, value)
            self.flush()
            if status == 0:
                print(MARKERS[self.phase] + json.dumps({"blender_version": bpy.app.version_string,
                    "phase": self.phase, "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"],
                    "process_id": os.getpid(), "installed_queued_guard_qualified": True,
                    "accepted_candidate_commit": ACCEPTED_COMMIT, "accepted_candidate_tree": ACCEPTED_TREE,
                    "receipt": str(self.path), "receipt_sha256": sha256(self.path.read_bytes())}), flush=True)
            owned_process_exit(status)


def main():
    global OWNED_ATTESTED
    assert not bpy.app.background and "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    assert threading.current_thread() is threading.main_thread() and sys.dont_write_bytecode
    private = private_display_manifest()  # Before preferences, Main or installation access.
    assert (tuple(bpy.app.version), bpy.app.build_hash) in {
        ((4, 5, 14), b"62c1db4208e8"), ((5, 2, 2), b"d13f752e3b9c")}
    assert bpy.app.build_type == b"Release"
    assert re.fullmatch("[0-9a-f]{32}", os.environ["BRIDGE_TEST_PROCESS_TOKEN"])
    assert re.fullmatch("[0-9a-f]{40}", os.environ["BRIDGE_TEST_SUPPORT_COMMIT"])
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    paths = {}
    for key in ("TEMP", "TMP", "TMPDIR", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        requested = Path(os.environ[key])
        resolved = requested.resolve(strict=True)
        assert requested.is_absolute() and resolved.is_dir() and resolved.is_relative_to(folder)
        assert resolved == folder if key in {"TEMP", "TMP", "TMPDIR"} else resolved.parent == folder
        paths[key] = str(resolved)
    private["owned_process_paths"] = paths
    OWNED_ATTESTED = True
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=tuple(MARKERS), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert args.bridge_bundle.is_dir()
    helpers, sources = load_helpers()
    preferences = bpy.context.preferences
    preferences.use_preferences_save = False
    preferences.filepaths.use_auto_save_temporary_files = False
    fixture = InstalledGuards(args.bridge_phase, args.bridge_bundle, private, helpers, sources)
    bpy.app.timers.register(fixture.run, first_interval=.5)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        if OWNED_ATTESTED:
            owned_process_exit(1)
        raise

