"""Verify one known-build import refusal; never count this as successful import."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon"))

import blender_codex_bridge  # noqa: E402
from blender_codex_bridge.errors import BridgeError  # noqa: E402
from blender_codex_bridge.permissions import Permission, PermissionManager  # noqa: E402
from blender_codex_bridge.runtime import get_runtime  # noqa: E402
from blender_codex_bridge.tools import asset_import  # noqa: E402


def snapshot():
    return {
        "ids": {
            family: sorted(item.session_uid for item in getattr(bpy.data, family))
            for family in asset_import.FAMILIES
            if hasattr(bpy.data, family)
        },
        "project": [bpy.data.filepath, bpy.data.is_dirty],
        "context": [
            bpy.context.scene.session_uid,
            bpy.context.view_layer.name,
            bpy.context.mode,
            sorted(obj.session_uid for obj in bpy.context.selected_objects),
            getattr(bpy.context.view_layer.objects.active, "session_uid", None),
        ],
    }


def checkpoint_snapshot(runtime):
    return {
        "checkpoints": runtime.checkpoints.list(),
        "recovery": runtime.checkpoints.recovery_status(),
        "editor_session": runtime.checkpoints.editor_session_status(),
    }


def main():
    assert bpy.app.background and os.environ.get("BRIDGE_TEST_PROCESS_TOKEN")
    version, build = tuple(bpy.app.version), bpy.app.build_hash.decode("ascii")
    quarantined = version == (5, 2, 2) and build in {
        "d13f752e3b9c", "d13f752e3b9c4f8c261cda552b1021f8bcc0382c"
    }
    blender_codex_bridge.register()
    runtime = get_runtime()
    runtime.registry.enable_toolset("asset_delivery")
    runtime.permissions = runtime.executor.permissions = PermissionManager(
        lambda: {permission.value: True for permission in Permission}
    )
    before = snapshot()
    checkpoint_before = checkpoint_snapshot(runtime)
    attempts, denials, originals = [], [], []

    def replace(owner, name, value):
        originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def forbidden(*_args, **_kwargs):
        attempts.append(True)
        raise AssertionError("Build admission reached source, staging, checkpoint or native work")

    try:
        # Admission may inspect only actual native runtime metadata. Scene and
        # data readers are unavailable through the handler's Blender boundary.
        replace(asset_import, "require_blender", lambda: SimpleNamespace(app=bpy.app))
        for name in ("_preview", "read_source", "OwnedInput", "_native"):
            replace(asset_import, name, forbidden)
        for name in ("before_modification", "after_modification", "finish_editor_session"):
            replace(runtime.checkpoints, name, forbidden)
        assert runtime.registry.get("asset.import_preview").checkpoint_admission_factory is None
        if quarantined:
            for native_format in ("GLB", "FBX"):
                params = {
                    "filepath": str(Path(os.environ["TEMP"]) / ("never-read." + native_format.lower())),
                    "format": native_format,
                    "collection_name": "Never allocated",
                    "expected_fingerprint": "0" * 64,
                    "accepted_losses": [],
                }
                for direct in (False, True):
                    try:
                        if direct:
                            asset_import.import_asset(
                                runtime.executor.context,
                                {**params, "override_native_import_quarantine": True},
                            )
                        else:
                            runtime.dispatch("asset.import", params)
                    except BridgeError as error:
                        assert error.code == "NOT_IMPLEMENTED", error.to_dict()
                        assert error.context["reason"] == "KNOWN_NATIVE_IMPORT_LIFETIME_FAILURE"
                        assert error.context["native_import_quarantined"] is True
                        assert error.context["safe_import_verified"] is False
                        for key in (
                            "execution_started", "native_import_started", "source_accessed",
                            "staging_allocated", "owned_ids_allocated", "project_saved",
                        ):
                            assert error.context[key] is False, error.to_dict()
                        denials.append({"format": native_format, "direct": direct})
                    else:
                        raise AssertionError("Known crashing build admitted a typed import")
        else:
            # This control proves only that another actual build is not matched.
            # It does not invoke an importer or certify that build as safe.
            guard = asset_import._native_import_admission(runtime.executor.context, {})
            guard()
            guard.check_after_read()
        assert not attempts and snapshot() == before
        assert checkpoint_snapshot(runtime) == checkpoint_before
        print("BLENDER_ASSET_IMPORT_ADMISSION_OK " + json.dumps({
            "blender_version": bpy.app.version_string,
            "build_hash": build,
            "known_build_quarantined": quarantined,
            "denials": denials,
            "metadata_only_admission_verified": True,
            "source_staging_checkpoint_and_native_work_invoked": False,
            "native_ids_and_context_unchanged": True,
            "bridge_checkpoint_bookkeeping_unchanged": True,
            "preview_read_exercised": False,
            "import_success_tested": False,
            "full_import_acceptance": False,
            "safe_import_verified": False,
            "release_acceptance": False,
        }), flush=True)
    finally:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)
        blender_codex_bridge.unregister()


main()
