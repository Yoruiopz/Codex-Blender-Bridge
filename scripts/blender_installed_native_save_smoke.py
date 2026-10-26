"""Distinct 0.8 candidate installed native-save and artist guard qualification.

Fixture-only orchestration. Real Blender timers execute all queued product calls.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
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
ACCEPTED_COMMIT = "adfd0468946c7a4147b662715fb520be0afa7ae6"
ACCEPTED_TREE = "9c24b416ede7b80268496fcd47cfd33ab562c72e"
ACCEPTED_ZIP_SHA256 = "2de08ba5033f3f7ae773f1e63449e2d8c31ac1300341526c027446ad5a9b900e"
ACCEPTED_VERSION = "0.8.0"
ACCEPTED_PUBLIC_TOOLS = 270
MARKERS = {"native_save": "BLENDER_INSTALLED_NATIVE_SAVE_OK ",
           "weights": "BLENDER_INSTALLED_NATIVE_WEIGHTS_OK ",
           "curve": "BLENDER_INSTALLED_NATIVE_CURVE_OK "}
MAX_RECEIPT = 4 * 1024 * 1024
MAX_MARKER = 32 * 1024
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


def load_helpers():
    """Only fixture data/setup oracles are loaded before removing checkout paths."""
    modules, sources = {}, {}
    for name, filename in (("package", "blender_installed_addon_probe_smoke.py"),
                           ("native", "blender_native_save_smoke.py"),
                           ("weights", "blender_weight_edit_guard_smoke.py"),
                           ("curve", "blender_animation_intent_smoke.py"),
                           ("selection", "blender_isolated_asset_preview_probe_smoke.py"),
                           ("transport", "installed_fixture_transport.py")):
        path = ROOT / "scripts" / filename
        sources["scripts/" + filename] = sha256(path.read_bytes())
        spec = importlib.util.spec_from_file_location("_installed_native_oracle_" + name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        modules[name] = module
    assert not any(name == MODULE or name.startswith(MODULE + ".") for name in sys.modules)
    return SimpleNamespace(**modules), sources


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class InstalledNative:
    def __init__(self, phase, bundle, private, helpers, helper_sources):
        self.phase, self.bundle, self.helpers = phase, bundle, helpers
        self.path = Path(tempfile.gettempdir()) / "installed-native-full-receipt.json"
        assert not self.path.exists()
        self.runtime = self.prefs = self.client = self.installed = None
        self.program = self.pending = None
        self.permission_origin = None
        self.save_callback = None
        self.started = time.monotonic()
        self.report = {"schema_version": 1, "phase": phase, "completed": False,
                       "accepted_candidate_commit": ACCEPTED_COMMIT,
                       "accepted_candidate_tree": ACCEPTED_TREE,
                       "accepted_candidate_zip_sha256": ACCEPTED_ZIP_SHA256,
                       "supporting_commit": os.environ["BRIDGE_TEST_SUPPORT_COMMIT"],
                       "support_script_sha256": sha256(Path(__file__).read_bytes()),
                       "support_helper_sources": helper_sources, "private_display": private,
                       "blender_version": bpy.app.version_string, "build_hash": bpy.app.build_hash.decode(),
                       "process_instance": os.environ["BRIDGE_TEST_PROCESS_TOKEN"], "process_id": os.getpid(),
                       "calls": [], "native_cases": [], "runtime_or_provider_replaced": False,
                       "queue_or_job_timers_manually_driven": False, "native_undo_invoked": False,
                       "scope": "Fresh installed exact candidate; persistent queued loopback calls and declared authored/native-save profile only.",
                       "unqualified": ["upgrade", "rollback", "restart/reconnect", "complete artist workflow",
                                       "full project/native effects", "4K native save", "Windows", "stable 1.0"]}

    def flush(self):
        raw = canonical(self.report) + b"\n"
        assert 0 < len(raw) <= MAX_RECEIPT
        assert not self.path.is_symlink()
        self.path.write_bytes(raw)

    def origin(self):
        assert threading.current_thread() is threading.main_thread()
        current = (self.runtime, self.runtime.executor, self.runtime.permissions, self.runtime.checkpoints,
                   self.runtime.registry, self.runtime.jobs, self.runtime.command_queue)
        assert all(first is second for first, second in zip(current, self.permission_origin, strict=True))
        assert self.runtime.permissions is self.runtime.executor.permissions
        self.helpers.package._installed_bytes(self.installed, self.members)

    def setup(self):
        import addon_utils

        config_path = Path(os.environ["BRIDGE_TEST_PACKAGE_PROBE_CONFIG"])
        raw = owned_file(config_path, maximum=512 * 1024)
        config = json.loads(raw)
        assert config["schema_version"] == 1 and set(config) == {"schema_version", "candidate", "previous"}
        record = config["candidate"]
        assert record["version"] == ACCEPTED_VERSION and record["expected_tools"] == ACCEPTED_PUBLIC_TOOLS
        assert record["sha256"] == ACCEPTED_ZIP_SHA256
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
        module = addon_utils.enable(MODULE, default_set=True, persistent=True)
        assert module is not None and module.bl_info["version"] == tuple(map(int, ACCEPTED_VERSION.split(".")))
        self.installed = scripts / "addons" / MODULE
        self.helpers.package._installed_bytes(self.installed, self.members)
        self.runtime = importlib.import_module(MODULE + ".runtime").get_runtime()
        self.prefs = bpy.context.preferences.addons[MODULE].preferences
        assert self.prefs.auto_start is False
        self.permission_origin = (self.runtime, self.runtime.executor, self.runtime.permissions,
                                  self.runtime.checkpoints, self.runtime.registry, self.runtime.jobs,
                                  self.runtime.command_queue)
        permissions = importlib.import_module(MODULE + ".permissions")
        self.preference_names = tuple(permissions.PREFERENCE_PROPERTIES.values())
        self.original_preferences = {name: getattr(self.prefs, name) for name in self.preference_names}
        assert all(not self.runtime.permissions.snapshot()[name] for name in
                   ("DELETE_OBJECTS", "EXECUTE_PYTHON", "ACCESS_EXTERNAL_FILES", "NATIVE_SAVE_EFFECTS"))
        enabled = {"allow_inspect_scene"}
        enabled.update({"allow_external_files", "allow_save_project"} if self.phase == "native_save"
                       else {"allow_edit_mesh" if self.phase == "weights" else "allow_edit_animation"})
        for name in self.preference_names:
            setattr(self.prefs, name, name in enabled)
        self.report.update(configuration_sha256=sha256(raw), installed_members_sha256=self.members,
                           public_surface=self.helpers.package._public_tool_surface(self.runtime.registry, record),
                           permission_source="Original installed Runtime PermissionManager and actual local add-on preferences")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.runtime.start_server("127.0.0.1", port, request_timeout=30.)
        self.client = self.helpers.transport.PersistentTCP(port, self.phase, request_timeout=30.)
        self.origin()

    def rpc(self, label, method, params, *, error=None, retain=False):
        self.origin()
        response = yield (method, copy.deepcopy(params))
        self.origin()
        assert type(response) is dict and response["ok"] is (error is None), response
        if error is not None:
            assert response["error"]["code"] == error, response
        result = response.get("result")
        record = {"label": label, "method": method, "request": copy.deepcopy(self.last_exchange["request"]),
                  "response_sha256": sha256(canonical(response)), "ok": response["ok"],
                  "elapsed_seconds": time.monotonic() - self.started}
        if error is not None or retain:
            record["response"] = response
        elif method == "jobs.inspect":
            record["job_observation"] = {key: result[key] for key in ("job_id", "state", "terminal", "revision", "progress")}
        self.report["calls"].append(record)
        self.flush()
        return result

    def assert_call(self, label, method, params, snapshot, expected, *, error=None):
        before, checkpoints = snapshot(), checkpoint_state(self.runtime)
        history = self.runtime.state.history(limit=50)
        row = {"label": label, "before": before, "expected": copy.deepcopy(expected),
               "checkpoint_before": checkpoints, "history_before_sha256": sha256(canonical(history))}
        self.report.setdefault("artist_cases", []).append(row)
        result = yield from self.rpc(label, method, params, error=error, retain=True)
        row.update(after=snapshot(), checkpoint_after=checkpoint_state(self.runtime))
        after_history = self.runtime.state.history(limit=50)
        row["history_after_sha256"] = sha256(canonical(after_history))
        assert self.helpers.curve.same(row["after"], expected), label
        if error is not None:
            assert row["checkpoint_after"] == checkpoints
        newest = after_history[0]
        assert newest["tool"] == method and newest["success"] is (error is None)
        assert after_history[1:] == history[:49]
        assert not history or newest["operation_id"] != history[0]["operation_id"]
        if error is not None:
            assert newest["error_code"] == error
        else:
            assert newest["recovery_evidence"] == result["recovery_evidence"]
        row["complete_prediction_and_history_verified"] = True
        self.flush()
        return result

    def prepare_checkpoint(self, snapshot):
        before = snapshot()
        row = {"before": before, "original_intent_captured": False,
               "scope": "Explicit genuine TCP checkpoint before frozen request; preparation can synchronize/encode Main."}
        self.report["preparation"] = row
        yield from self.rpc("prepare_checkpoint", "checkpoint.create", {"description": "Installed " + self.phase + " fixture setup"})
        row["after"] = snapshot()
        assert self.runtime.checkpoints._pending is None
        self.flush()

    def workflow(self):
        status = yield from self.rpc("status", "bridge.status", {}, retain=True)
        assert status["addon_version"] == ACCEPTED_VERSION
        if self.phase != "native_save":
            domain = "weights" if self.phase == "weights" else "animation"
            yield from self.rpc("enable_domain", "toolsets.enable", {"name": domain})
        yield from getattr(self, self.phase)()
        self.origin()
        self.report.update(completed=True, installed_queued_profile_qualified=True,
                           installed_module_origins_verified=True, persistent_owner_socket=True,
                           final_history=self.runtime.state.history(limit=50),
                           genuine_runtime_services_preserved=True)

    def tick(self):
        try:
            assert time.monotonic() - self.started < 300, "Installed qualification phase deadline"
            if self.program is None:
                self.setup()
                self.program = self.workflow()
                method, params = next(self.program)
            else:
                exchange = self.client.poll()
                if exchange is None:
                    return .01
                self.last_exchange = exchange
                method, params = self.program.send(exchange["response"])
            self.client.submit(method, params)
            return .01
        except StopIteration:
            self.finish(0)
        except BaseException:
            self.report["failure"] = traceback.format_exc()
            self.finish(1)
        return None

    def finish(self, status):
        if self.save_callback is not None and self.save_callback in bpy.app.handlers.save_post:
            bpy.app.handlers.save_post.remove(self.save_callback)
        if self.client is not None:
            self.client.close()
        if self.runtime is not None:
            self.runtime.stop_server()
        if self.prefs is not None and hasattr(self, "original_preferences"):
            for name, value in self.original_preferences.items():
                setattr(self.prefs, name, value)
        self.flush()
        with self.path.open("rb") as stream:
            readback = stream.read(MAX_RECEIPT + 1)
        assert 0 < len(readback) <= MAX_RECEIPT and json.loads(readback) == self.report
        if status == 0:
            payload = {"blender_version": bpy.app.version_string, "phase": self.phase,
                       "process_instance": self.report["process_instance"], "process_id": os.getpid(),
                       "accepted_candidate_commit": ACCEPTED_COMMIT, "accepted_candidate_tree": ACCEPTED_TREE,
                       "accepted_candidate_zip_sha256": ACCEPTED_ZIP_SHA256,
                       "installed_queued_profile_qualified": True, "full_artist_workflow_qualified": False,
                       "receipt": {"path": str(self.path), "bytes": len(readback), "sha256": sha256(readback)}}
            line = MARKERS[self.phase] + canonical(payload).decode()
            assert len(line.encode()) <= MAX_MARKER
            print(line, flush=True)
        owned_process_exit(status)



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

        yield from self.prepare_checkpoint(snapshot)
        request = {"object_name": obj.name, "group_name": "A", "vertex_indices": [0, 1], "weight": .5}
        expected = copy.deepcopy(snapshot())
        memberships = expected["target"]["target"]["memberships"]
        memberships[0][0][1] = memberships[1][0][1] = helper.bits(.5)
        assigned = yield from self.assert_call("assign", "weights.assign", request, snapshot, expected)
        assert assigned["recovery_evidence"]["owned_membership_verified"] == 2
        expected = copy.deepcopy(snapshot())
        expected["target"]["target"]["memberships"][:2] = [
            [[0, helper.bits(7/12)], [1, helper.bits(7/24)], [2, helper.bits(.125)]]] * 2
        yield from self.assert_call("normalize", "weights.normalize", {"object_name": obj.name, "group_names": ["A", "B"],
                                                    "vertex_indices": [0, 1]}, snapshot, expected)
        self.prefs.allow_edit_mesh = False
        yield from self.assert_call("permission_denial", "weights.assign", request, snapshot, snapshot(), error="PERMISSION_DENIED")
        self.prefs.allow_edit_mesh = True
        yield from self.assert_call("locked_group_scope", "weights.assign", {**request, "group_name": "Locked"},
                  snapshot, snapshot(), error="NOT_IMPLEMENTED")
        yield from self.assert_call("invalid_vertex_type", "weights.assign", {**request, "vertex_indices": [True]},
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

        yield from self.prepare_checkpoint(snapshot)
        base = {"object_name": work.name, "data_path": "location", "index": 0}
        request = {**base, "keyframes": [{"frame": 11, "co": [11., 12.],
                                         "handle_left": [10., 11.], "handle_right": [14., 13.]}]}
        expected = helper.predict(snapshot(), action.as_pointer(), request)
        result = yield from self.assert_call("future_raw_co_handles", "animation.curve_edit", request, snapshot, expected)
        assert result["authored_profile"] == "RAW_FREE_POINT_V1"
        assert result["current_pose_revision_qualified"] is False
        assert result["recovery_evidence"]["native_update_attempts"] == 0
        yield from self.assert_call("exact_noop", "animation.curve_edit", request, snapshot, snapshot())
        self.prefs.allow_edit_animation = False
        yield from self.assert_call("permission_denial", "animation.curve_edit", request, snapshot, snapshot(), error="PERMISSION_DENIED")
        self.prefs.allow_edit_animation = True
        for label, changed in (("current_pose_scope", {**base, "keyframes": [{"frame": 1, "co": [1., 2.]}]}),
                               ("handle_conversion_scope", {**base, "keyframes": [{"frame": 11, "handle_left_type": "FREE"}]})):
            yield from self.assert_call(label, "animation.curve_edit", changed, snapshot, snapshot(), error="NOT_IMPLEMENTED")
        yield from self.assert_call("invalid_frame_type", "animation.curve_edit", {**base, "keyframes": [{"frame": True, "co": [11., 13.]}]},
                  snapshot, snapshot(), error="INVALID_ARGUMENT")

    def native_save(self):
        helper = self.helpers.native
        artifacts = self.bundle / "artifacts"
        artifacts.mkdir(mode=0o700)
        (artifacts / "moved folder").mkdir(mode=0o700)
        paths = bpy.context.preferences.filepaths
        paths.file_preview_type, paths.save_version = "NONE", 1
        paths.use_auto_save_temporary_files = False
        self.prefs.project_directory = str(artifacts)
        setup = {"factory_before_cleanup": helper.data_inventory(bpy.data),
                 "bindings_before": helper.setup_bindings(bpy.data)}
        self.report["native_setup"] = setup
        protected_headers = {name: [helper.id_header(owner) for owner in getattr(bpy.data, name)]
                             for name in ("scenes", "screens", "window_managers", "workspaces")}
        setup["factory_removed"] = helper.clean_factory_data(bpy.data, attested=OWNED_ATTESTED)
        setup["bindings_after"] = helper.setup_bindings(bpy.data)
        assert protected_headers == {name: [helper.id_header(owner) for owner in getattr(bpy.data, name)]
                                     for name in protected_headers}
        profile = importlib.import_module(MODULE + ".native_save_profile")
        setup["schema_census"] = profile.schema_census(bpy.types)
        assert not setup["schema_census"]["mismatches"]
        setup["unsupported_after_cleanup"] = helper.unsupported_remainders(
            helper.data_inventory(bpy.data), profile.FAMILIES, profile.UI)
        assert not setup["unsupported_after_cleanup"]
        _scene, layer, obj, _rig, actor = helper.fixture(self.bundle)
        obj.name, obj.data.name = "Installed Saved Mesh", "Installed Saved Data"
        (artifacts / "textures").rename(self.bundle / "unavailable external textures")
        batch = helper.value_preflight(bpy.data, build_hash=bpy.app.build_hash.decode())
        setup["before_owned_sequence_clear"] = batch
        setup["owned_empty_sequence_clear"] = helper.clear_owned_empty_sequence_editors(
            bpy.data, attested=OWNED_ATTESTED, preflight=batch, build_hash=bpy.app.build_hash.decode())
        setup["after_owned_sequence_clear"] = helper.value_preflight(bpy.data, build_hash=bpy.app.build_hash.decode())
        assert setup["after_owned_sequence_clear"]["complete"] and not setup["after_owned_sequence_clear"]["violations"]
        sentinel = self.bundle / "owned callback outside approved project folder.txt"
        sentinel.write_text("0\n")
        callbacks = {"count": 0, "revoke": False}

        def save_post(*_args):
            callbacks["count"] += 1
            sentinel.write_text(str(callbacks["count"]) + "\n")
            if callbacks["revoke"]:
                self.runtime.revoke_native_save_effects()

        self.save_callback = save_post
        bpy.app.handlers.save_post.append(save_post)
        original = artifacts / "original installed project.blend"
        default = {"mode": "SAVE_AS", "filepath": str(original), "overwrite_policy": "NATIVE_NEW_EXPECTED"}
        yield from self.rpc("default_off", "project.native_save_preview", default, error="PERMISSION_DENIED", retain=True)
        yield from self.rpc("legacy_save_still_held", "project.save", {"filepath": str(original)}, error="NOT_IMPLEMENTED")
        assert not original.exists() and callbacks["count"] == 0
        assert not self.runtime.permissions.snapshot()["NATIVE_SAVE_EFFECTS"]
        assert bpy.ops.blender_codex_bridge.arm_native_save("EXEC_DEFAULT") == {"FINISHED"}
        assert self.runtime.permissions.snapshot()["NATIVE_SAVE_EFFECTS"]
        self.report["local_ui_grant"] = {"operator": "blender_codex_bridge.arm_native_save", "default_off_verified": True,
                                         "actual_permission_snapshot": self.runtime.permissions.snapshot()}
        self.runtime.state.set_paused(True)
        yield from self.rpc("pause_denial", "project.native_save_preview", default, error="AGENT_PAUSED")
        self.runtime.state.set_paused(False)
        self.runtime.state.set_emergency_stopped(True)
        yield from self.rpc("stop_denial", "project.native_save_preview", default, error="EMERGENCY_STOPPED")
        self.runtime.state.set_emergency_stopped(False)
        self.runtime.state.set_paused(False)
        layer.objects.active = obj
        obj.select_set(True, view_layer=layer)
        assert bpy.ops.object.mode_set(mode="EDIT") == {"FINISHED"}
        yield from self.rpc("invalid_context", "project.native_save_preview", default, error="NOT_IMPLEMENTED")
        assert bpy.ops.object.mode_set(mode="OBJECT") == {"FINISHED"}
        tasks = (("initial", "SAVE_AS", original, "NATIVE_NEW_EXPECTED"),
                 ("copy", "COPY_NEW", artifacts / "installed portable copy.blend", "NO_CLOBBER"),
                 ("current", "SAVE_CURRENT", original, "NATIVE_REPLACE_EXPECTED"),
                 ("as_new", "SAVE_AS", artifacts / "moved folder" / "installed project.blend", "NATIVE_NEW_EXPECTED"),
                 ("as_replace", "SAVE_AS", artifacts / "moved folder" / "installed project.blend", "NATIVE_REPLACE_EXPECTED"),
                 ("cancel_reader", "COPY_NEW", artifacts / "cancelled reader copy.blend", "NO_CLOBBER"),
                 ("revoke_reader", "COPY_NEW", artifacts / "reader revoked copy.blend", "NO_CLOBBER"),
                 ("revoke", "COPY_NEW", artifacts / "revoked copy.blend", "NO_CLOBBER"),
                 ("manual", "COPY_NEW", artifacts / "stale copy.blend", "NO_CLOBBER"))
        manual_edit = None
        for task, mode, path, overwrite in tasks:
            if task == "copy":
                obj.data.vertices[0].co.x = .125
            if task == "as_replace":
                obj.data.vertices[0].co.z = .25
            if task in {"revoke", "manual"}:
                assert bpy.ops.blender_codex_bridge.arm_native_save("EXEC_DEFAULT") == {"FINISHED"}
            callbacks["revoke"] = task == "revoke"
            actor.hide_set(False, view_layer=layer)
            for owner in layer.objects:
                owner.select_set(False, view_layer=layer)
            actor.select_set(True, view_layer=layer)
            layer.objects.active = actor
            layer.update()  # Explicit owned setup before each immutable native-save intent.
            batch = helper.value_preflight(bpy.data, build_hash=bpy.app.build_hash.decode())
            assert batch["complete"] and not batch["violations"]
            actor.hide_set(True, view_layer=layer)
            actor.location = (0., 0., 0.)
            raw_before = {"selection": self.helpers.selection.raw_selection(layer), "location": list(actor.location)}
            params = {"mode": mode, "filepath": str(path), "overwrite_policy": overwrite}
            preview = yield from self.rpc(task + "_preview", "project.native_save_preview", params)
            accepted = yield from self.rpc(task + "_start", "project.native_save_start", {
                **params, "preview_id": preview["preview_id"], "expected_fingerprint": preview["fingerprint"],
                "accepted_losses": preview["required_accepted_losses"], "time_limit_seconds": 120}, retain=True)
            assert accepted["accepted"] and not accepted["job_completed"]
            raw_after_start = {"selection": self.helpers.selection.raw_selection(layer), "location": list(actor.location)}
            interrupted = False
            while True:
                row = yield from self.rpc(task + "_poll", "jobs.inspect", {"job_id": accepted["job_id"]})
                if row["terminal"]:
                    break
                if row["progress"].get("phase") == "fresh_process_reopen":
                    if task in {"cancel_reader", "revoke_reader"} and not interrupted:
                        if task == "cancel_reader":
                            yield from self.rpc(task + "_cancel", "jobs.cancel", {"job_id": accepted["job_id"]})
                        else:
                            assert bpy.ops.blender_codex_bridge.revoke_native_save("EXEC_DEFAULT") == {"FINISHED"}
                        interrupted = True
                    if task == "manual" and manual_edit is None:
                        obj.data.vertices[0].co.y = .625
                        manual_edit = list(obj.data.vertices[0].co)
            callbacks["revoke"] = False
            retained_observations = []
            if task not in {"cancel_reader", "revoke_reader", "revoke", "manual"}:
                assert row["state"] == "SUCCEEDED" and row["result"]["fresh_process_reopen_verified"]
                assert row["external_effects"]["published_bytes_verified"] and path.is_file()
            else:
                assert row["state"] in {"FAILED", "CANCELLED"} and row["result"] is None
                assert row["external_effects"]["native_save"]["native_save_completed"] and not path.exists()
                retained = row["external_effects"]["retained_staging_path"]
                assert type(retained) is str and Path(retained).is_dir()
                assert Path(retained).resolve(strict=True).is_relative_to(artifacts.resolve(strict=True))
                if task == "revoke":
                    # Lost grant prevents product-side file observation. Keep that
                    # unknown; this test-owned byte oracle grants no restore authority.
                    assert row["external_effects"]["artifacts"] == []
                    assert row["external_effects"]["artifacts_incomplete"] is True
                    entries = list(Path(retained).iterdir())
                    assert 0 < len(entries) <= 4
                    for observed_path in entries:
                        observed = owned_file(observed_path, maximum=256 * 1024 * 1024)
                        retained_observations.append({"filepath": str(observed_path), "file_bytes": len(observed),
                            "file_sha256": sha256(observed), "source": "fixture-owned post-revocation byte observation; not product authority"})
                else:
                    assert row["external_effects"]["artifacts"]
                    for artifact in row["external_effects"]["artifacts"]:
                        observed_path = Path(artifact["filepath"])
                        observed = owned_file(observed_path, maximum=256 * 1024 * 1024)
                        assert len(observed) == artifact["file_bytes"] and sha256(observed) == artifact["file_sha256"]
                        retained_observations.append({"filepath": str(observed_path), "file_bytes": len(observed),
                            "file_sha256": sha256(observed), "source": "fixture-owned independent product-artifact verification"})
                if task in {"cancel_reader", "revoke_reader"}:
                    assert interrupted and row["external_effects"]["native_save"]["worker_reaped"]
                if task == "manual":
                    assert manual_edit is not None and list(obj.data.vertices[0].co) == manual_edit
            history = self.runtime.state.history(limit=50)
            operation = next(item for item in history if item["operation_id"] == row["operation_id"])
            assert operation["tool"] == "project.native_save_start" and operation["success"] is (row["state"] == "SUCCEEDED")
            recorded = operation["external_effects"]
            for key, value in row["external_effects"].items():
                if key == "native_save":
                    for field, actual in value.items():
                        assert recorded[key][field] == actual
                    assert type(recorded[key]["evidence_incomplete"]) is bool
                else:
                    assert recorded[key] == value
            self.report["native_cases"].append({"case": task, "terminal_job": row, "history_operation": operation,
                "fixture_owned_retained_file_observations": retained_observations,
                "callback_count": callbacks["count"], "raw_before_entry": raw_before, "raw_after_start": raw_after_start,
                "raw_after_terminal": {"selection": self.helpers.selection.raw_selection(layer), "location": list(actor.location)},
                "pre_intent_value_projection_sha256": sha256(canonical(batch))})
            self.flush()
        layer.update()  # Owned protected-scope test setup after every save has terminated.
        plan = yield from self.rpc("set_protected_plan", "task.plan.set", {"goal": "Keep installed saved mesh", "steps": [
            {"id": "saved", "description": "Verify installed native delivery"}], "protected_objects": [obj.name]})
        yield from self.rpc("enforce_protected_plan", "task.plan.enforce", {"enabled": True, "expected_revision": plan["plan"]["revision"]})
        yield from self.rpc("protected_denial", "project.native_save_preview", {
            "mode": "COPY_NEW", "filepath": str(artifacts / "protected copy.blend"), "overwrite_policy": "NO_CLOBBER"}, error="NOT_IMPLEMENTED")
        self.report.update(real_local_ui_grant_and_runtime_permissions=True, callback_count=callbacks["count"],
                           callback_kind="OWNED_PYTHON_SAVE_POST_NOT_NATIVE_C_CATALOG", manual_edit_preserved=manual_edit,
                           actual_current_filepath=bpy.data.filepath, external_source_folder_unavailable=True,
                           protected_scope_still_enforced=True)


def main():
    global OWNED_ATTESTED
    assert not bpy.app.background and "--factory-startup" in sys.argv and "--disable-autoexec" in sys.argv
    assert threading.current_thread() is threading.main_thread() and sys.dont_write_bytecode
    private = private_display_manifest()
    assert (tuple(bpy.app.version), bpy.app.build_hash) in {
        ((4, 5, 14), b"62c1db4208e8"), ((5, 2, 2), b"d13f752e3b9c")}
    assert bpy.app.build_type == b"Release"
    assert re.fullmatch("[0-9a-f]{32}", os.environ["BRIDGE_TEST_PROCESS_TOKEN"])
    assert re.fullmatch("[0-9a-f]{40}", os.environ["BRIDGE_TEST_SUPPORT_COMMIT"])
    folder = Path(tempfile.gettempdir()).resolve(strict=True)
    private["owned_process_paths"] = {}
    for key in ("TEMP", "TMP", "TMPDIR", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        requested = Path(os.environ[key])
        resolved = requested.resolve(strict=True)
        assert requested.is_absolute() and resolved.is_dir() and resolved.is_relative_to(folder)
        assert resolved == folder if key in {"TEMP", "TMP", "TMPDIR"} else resolved.parent == folder
        private["owned_process_paths"][key] = str(resolved)
    OWNED_ATTESTED = True
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=tuple(MARKERS), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert args.bridge_bundle.is_dir()
    helpers, sources = load_helpers()
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
    fixture = InstalledNative(args.bridge_phase, args.bridge_bundle, private, helpers, sources)
    bpy.app.timers.register(fixture.tick, first_interval=.5)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        if OWNED_ATTESTED:
            owned_process_exit(1)
        raise
