"""Install exact ZIPs into a disposable profile, upgrade, reconnect and roll back.

Only the runner launches this fixture. Its explicit package configuration pins
both archives and all member bytes; no source-checkout imports are permitted.
This development probe is not the complete installed artist acceptance suite.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import socket
import stat
import sys
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

import addon_utils  # type: ignore
import bpy  # type: ignore

MODULE = "blender_codex_bridge"


def _archive(record: dict, owned: Path, label: str) -> tuple[Path, dict[str, str]]:
    source = Path(record["path"])
    with source.open("rb") as stream:
        payload = stream.read(32 * 1024 * 1024 + 1)
    assert len(payload) <= 32 * 1024 * 1024
    assert hashlib.sha256(payload).hexdigest() == record["sha256"]
    frozen = owned / (label + " package with spaces.zip")
    frozen.write_bytes(payload)
    members: dict[str, str] = {}
    normalized_names: set[str] = set()
    total = 0
    with zipfile.ZipFile(frozen) as archive:
        assert archive.testzip() is None
        for item in archive.infolist():
            name = PurePosixPath(item.filename)
            raw_parts = item.filename.rstrip("/").split("/")
            assert (not name.is_absolute() and ".." not in name.parts
                    and "\\" not in item.filename and ":" not in item.filename
                    and name.parts[0] == MODULE and len(name.parts) > 1)
            assert all(part not in {"", ".", ".."} for part in raw_parts)
            normalized = str(name).casefold()
            assert normalized not in normalized_names
            normalized_names.add(normalized)
            assert stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR)
            if item.is_dir():
                continue
            assert item.filename not in members
            total += item.file_size
            assert total <= 64 * 1024 * 1024 and len(members) < 512
            members[item.filename] = hashlib.sha256(archive.read(item)).hexdigest()
    assert members == record["members_sha256"]
    assert MODULE + "/__init__.py" in members
    return frozen, members


def _unload() -> None:
    if MODULE in sys.modules:
        addon_utils.disable(MODULE, default_set=True)
    for name in tuple(sys.modules):
        if name == MODULE or name.startswith(MODULE + "."):
            del sys.modules[name]
    importlib.invalidate_caches()


def _installed_bytes(root: Path, expected: dict[str, str]) -> None:
    actual = {str(path.relative_to(root.parent)).replace("\\", "/"):
              hashlib.sha256(path.read_bytes()).hexdigest()
              for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts}
    assert actual == expected, {"missing": sorted(expected.keys() - actual.keys()),
                                "extra": sorted(actual.keys() - expected.keys())}
    for name, module in tuple(sys.modules.items()):
        if name == MODULE or name.startswith(MODULE + "."):
            assert Path(module.__file__).resolve().is_relative_to(root.resolve()), (name, module.__file__)


def _network(runtime, label: str) -> dict:
    # The networking thread only sends bytes; Blender dispatch remains on this
    # fixture's main thread, as the normal timer would do outside a script.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    runtime.start_server("127.0.0.1", port, request_timeout=5.)
    result = {}

    def client() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.) as connection:
                request = {"id": label, "method": "bridge.status", "params": {},
                           "protocol_version": "1.0", "timeout_ms": 5000}
                connection.sendall(json.dumps(request).encode() + b"\n")
                with connection.makefile("rb") as stream:
                    result["response"] = json.loads(stream.readline())
        except Exception as error:
            result["error"] = str(error)

    thread = threading.Thread(target=client, daemon=True)
    thread.start()
    deadline = time.monotonic() + 8.
    while thread.is_alive() and time.monotonic() < deadline:
        runtime.executor._drain_timer()
        time.sleep(.005)
    thread.join(timeout=.1)
    runtime.stop_server()
    assert not thread.is_alive() and "error" not in result, result
    response = result["response"]
    assert response["id"] == label and response["ok"] is True, response
    return {"id": response["id"], "ok": response["ok"]}


def _exercise(label: str, archive: Path, members: dict, record: dict, scripts: Path) -> dict:
    _unload()
    installed = scripts / "addons" / MODULE
    replaced = installed.exists()
    if replaced:
        # Blender's overwrite installer retains obsolete source files. A clean
        # replacement in this owned disposable profile is the reviewed path;
        # this does not claim preferences migration or UI-uninstall coverage.
        assert not installed.is_symlink() and installed.resolve().is_relative_to(scripts)
        shutil.rmtree(installed)
    assert bpy.ops.preferences.addon_install(filepath=str(archive), overwrite=True) == {"FINISHED"}
    addon_utils.modules_refresh()
    discovered = [module for module in addon_utils.modules() if module.__name__ == MODULE]
    if record.get("require_discovery", True):
        assert len(discovered) == 1 and discovered[0].bl_info.get("version") == tuple(map(int, record["version"].split("."))), discovered
    module = addon_utils.enable(MODULE, default_set=True, persistent=True)
    assert module is not None and addon_utils.check(MODULE)[1]
    _installed_bytes(installed, members)
    runtime = importlib.import_module(MODULE + ".runtime").get_runtime()
    BridgeError = importlib.import_module(MODULE + ".errors").BridgeError
    permissions_module = importlib.import_module(MODULE + ".permissions")
    status = runtime.dispatch("bridge.status", {})
    assert status["addon_version"] == record["version"]
    default_permissions = runtime.permissions.snapshot()
    assert all(default_permissions[key] is False for key in ("DELETE_OBJECTS", "EXECUTE_PYTHON", "ACCESS_EXTERNAL_FILES"))
    assert bpy.context.preferences.addons[MODULE].preferences.auto_start is False
    runtime.dispatch("toolsets.enable", {"name": "objects"})
    try:
        runtime.dispatch("object.delete", {"object_names": ["Cube"]})
    except BridgeError as error:
        assert error.code == "PERMISSION_DENIED", error
    else:
        raise AssertionError("Installed default profile granted deletion")
    runtime.dispatch("toolsets.disable", {"name": "objects"})
    tool_count = len(runtime.registry.list_tools()) - 1  # internal toolsets.list is not an MCP tool
    assert tool_count == record["expected_tools"], tool_count
    first = _network(runtime, label + "-connect")
    second = _network(runtime, label + "-reconnect")
    allowed = {permission.value: True for permission in permissions_module.Permission}
    permissions = permissions_module.PermissionManager(lambda: allowed)
    runtime.permissions = runtime.executor.permissions = permissions
    runtime.dispatch("toolsets.enable", {"name": "objects"})
    created = runtime.dispatch("object.create", {"object_type": "CUBE", "name": label + " installed cube"})
    name = created["object"]
    runtime.dispatch("transform.set", {"object_name": name, "location": [1., 2., 3.]})
    assert tuple(bpy.data.objects[name].location) == (1., 2., 3.)
    _installed_bytes(installed, members)
    return {"label": label, "archive_sha256": record["sha256"], "version": status["addon_version"],
            "documented_tool_count": tool_count, "installed_members_verified": len(members),
            "module_path": str(Path(module.__file__).resolve()), "default_deletion_denied": True,
            "default_permissions": default_permissions, "discovered_in_addon_list": bool(discovered),
            "clean_directory_replacement": replaced,
            "loopback": [first, second], "created_object": name, "location": [1., 2., 3.]}


def main() -> None:
    config_path = os.environ.get("BRIDGE_TEST_PACKAGE_PROBE_CONFIG")
    assert config_path, "Select explicit pinned ZIPs with --package-probe-config"
    with Path(config_path).open("rb") as stream:
        config_bytes = stream.read(512 * 1024 + 1)
    assert len(config_bytes) <= 512 * 1024
    config = json.loads(config_bytes)
    assert config["schema_version"] == 1 and set(config) == {"schema_version", "candidate", "previous"}
    scripts = Path(os.environ["BLENDER_USER_SCRIPTS"]).resolve()
    assert scripts.is_dir() and scripts != Path.home()
    # Keep the caller's user-script folder untouched; the runner supplies this
    # process's unique disposable profile. All ZIP staging paths contain spaces.
    owned = scripts.parent / "package inputs with spaces"
    owned.mkdir(mode=0o700)
    candidate, candidate_members = _archive(config["candidate"], owned, "candidate")
    previous, previous_members = _archive(config["previous"], owned, "previous")
    # Remove every checkout path before the first bridge import. The Blender
    # installer adds the isolated profile's addons directory separately.
    repository = Path(__file__).resolve().parents[1]
    sys.path[:] = [entry for entry in sys.path if entry and not Path(entry).resolve().is_relative_to(repository)]
    assert MODULE not in sys.modules
    observations = []
    try:
        observations.append(_exercise("fresh-candidate", candidate, candidate_members, config["candidate"], scripts))
        observations.append(_exercise("previous", previous, previous_members, config["previous"], scripts))
        observations.append(_exercise("upgrade", candidate, candidate_members, config["candidate"], scripts))
        observations.append(_exercise("rollback", previous, previous_members, config["previous"], scripts))
    finally:
        _unload()
    assert not addon_utils.check(MODULE)[1]
    print("BLENDER_INSTALLED_ADDON_PROBE_OK " + json.dumps({
        "blender_version": bpy.app.version_string, "configuration_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "observations": observations, "unregistered_after_probe": True,
        "project_saved": False, "user_preferences_saved": False,
        "scope": "Actual isolated installed ZIP enable/disable, exact member/import proof, default denial, loopback reconnect, bounded creation/transform and clean-directory upgrade/rollback. No preferences migration, UI-uninstall, complete installed artist scenarios or Windows qualification. Previous alpha may require known-name enablement because its nonliteral metadata is undiscoverable.",
        "release_readiness": "NOT_ASSESSED"}), flush=True)


if __name__ == "__main__":
    main()
