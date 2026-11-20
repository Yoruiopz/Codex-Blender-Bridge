"""Exercise stock Blender backup recovery through the registered Bridge."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.blender_persistent_save_smoke import ADDON, Scenario, fingerprint  # noqa: E402

PRIOR_LOCATION = (1., 2., 3.)
NEWER_LOCATION = (4., 5., 6.)


class BackupScenario(Scenario):
    def writer(self):
        from blender_codex_bridge import project_recovery

        self.stage = "first verified save with Blender's previous-version backup enabled"
        self.approved.mkdir()
        self.prefs.project_directory = str(self.approved)
        self.prefs.allow_save_project = True
        self.prefs.allow_external_files = True
        self.bpy.context.preferences.filepaths.save_version = 1
        cube = self.bpy.data.objects["Cube"]
        cube.location = PRIOR_LOCATION
        prior = yield from self.save(self.first)
        checkpoint_id = yield from self.checkpoint(self.first, prior)
        backup = self.first.with_suffix(".blend1")
        assert not backup.exists()

        self.stage = "real native overwrite with injected receipt-write failure"
        cube.location = NEWER_LOCATION
        with patch.object(project_recovery, "_write_index", side_effect=OSError("owned fixture write failure")) as write:
            result = yield from self.call("project.save")
        write.assert_called_once()
        assert result["saved"] is True and Path(result["filepath"]) == self.first, result
        receipt = result["recovery_checkpoint"]
        assert receipt["state"] == "unavailable" and receipt["reason"] == "RECOVERY_INDEX_WRITE_FAILED", receipt
        newer = fingerprint(self.first)
        assert newer != prior and fingerprint(backup) == prior
        assert project_recovery.read_index()["checkpoint_id"] == checkpoint_id
        self.evidence.update(prior=prior, newer=newer, checkpoint_id=checkpoint_id, receipt_failure=True)

    def reader(self):
        self.stage = "waiting for stock Blender to settle after the fixture baseline load"
        settle_deadline = time.monotonic() + 3.
        while self.bpy.data.is_dirty and time.monotonic() < settle_deadline:
            yield
        assert Path(self.bpy.data.filepath) == self.first and not self.bpy.data.is_dirty, (
            self.bpy.data.filepath, self.bpy.data.is_dirty,
        )
        self.stage = "fresh-process detection of the previous verified bytes"
        saved = json.loads((self.bundle / "writer.json").read_text(encoding="utf-8"))
        assert saved["process_instance"] != self.token and saved["receipt_failure"] is True
        old_bytes, new_bytes = saved["prior"], saved["newer"]
        backup = self.first.with_suffix(".blend1")
        assert fingerprint(self.first) == new_bytes and fingerprint(backup) == old_bytes
        assert self.prefs.allow_save_project and self.prefs.allow_external_files
        assert Path(self.prefs.project_directory) == self.approved
        assert tuple(self.bpy.data.objects["Cube"].location) == NEWER_LOCATION
        status = yield from self.call("bridge.status")
        assert status["project_checkpoint"]["state"] in {"verification_required", "unavailable"}, status
        status = yield from self.call("project.checkpoint_status")
        params = {"checkpoint_id": saved["checkpoint_id"], "confirm_reopen": True}
        assert status["state"] == "backup_available" and status["checkpoint_id"] == params["checkpoint_id"], status
        assert Path(status["filepath"]) == self.first and Path(status["recovery_filepath"]) == backup, status
        assert status["recovery_source"] == "blender_backup" and status["save_as_required"] is True, status
        assert status["file_sha256"] == old_bytes["sha256"] and status["file_bytes"] == old_bytes["bytes"], status

        self.stage = "default reopen refusal followed by stock Blender explicit backup reopen"
        refused = yield from self.call("project.checkpoint_reopen", params, error_codes=("OPERATION_FAILED",))
        assert refused["context"]["reason"] == "RECOVERY_FILE_CHANGED", refused
        assert Path(self.bpy.data.filepath) == self.first
        result = yield from self.call("project.checkpoint_reopen", {**params, "use_verified_backup": True})
        assert result["reopened"] is True and result["save_as_required"] is True, result
        assert Path(result["filepath"]) == Path(self.bpy.data.filepath) == backup, result
        assert Path(result["original_filepath"]) == self.first and result["auto_replayed"] is False, result
        assert tuple(self.bpy.data.objects["Cube"].location) == PRIOR_LOCATION and not self.bpy.data.is_dirty
        yield from self.call("project.info")
        yield from self.call("project.save", error_codes=("INVALID_ARGUMENT",))
        assert fingerprint(self.first) == new_bytes and fingerprint(backup) == old_bytes

        self.stage = "saving restored scene as a separate project"
        restored = self.approved / "restored checkpoint.blend"
        proof = yield from self.save(restored)
        assert fingerprint(self.first) == new_bytes and fingerprint(backup) == old_bytes
        assert proof["bytes"] > 0 and tuple(self.bpy.data.objects["Cube"].location) == PRIOR_LOCATION
        self.evidence.update(backup_opened=True, default_open_denied=True, newer_project_preserved=True,
                             backup_preserved=True, saved_as=str(restored), saved_as_sha256=proof["sha256"])


def main():
    import addon_utils
    import bpy

    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-phase", choices=("writer", "reader"), required=True)
    parser.add_argument("--bridge-bundle", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    phase = args.bridge_phase
    token = os.environ["BRIDGE_TEST_PROCESS_TOKEN"]
    bundle = args.bridge_bundle.resolve(strict=True)
    assert re.fullmatch("[0-9a-f]{32}", token) and not bpy.app.background
    assert {"--factory-startup", "--disable-autoexec"} <= set(sys.argv) and not bpy.data.filepath
    assert args.bridge_bundle == bundle and bundle.is_dir() and bundle.name == "project_checkpoint_backup-bundle"
    assert not (bundle / (phase + ".json")).exists()
    config = Path(os.environ["BLENDER_USER_CONFIG"])
    assert config == bundle / "bridge-config" and config.is_dir() and not config.is_symlink()
    temporary = Path(os.environ["TEMP"])
    assert temporary == bundle.parent / f"project_checkpoint_backup-{phase}-temp"
    for name in ("BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        path = Path(os.environ[name])
        assert path.parent == temporary and path.is_dir() and not path.is_symlink()
    if phase == "reader":
        saved = json.loads((bundle / "writer.json").read_text(encoding="utf-8"))
        primary = bundle / "approved projects" / "first save.blend"
        assert primary.resolve(strict=True) == primary and fingerprint(primary) == saved["newer"]
        assert bpy.ops.wm.open_mainfile(filepath=str(primary), load_ui=False, use_scripts=False) == {"FINISHED"}
        assert Path(bpy.data.filepath) == primary, bpy.data.filepath
    sys.path.insert(0, str(ROOT / "addon"))
    assert addon_utils.enable(ADDON, default_set=True, persistent=True) is not None
    from blender_codex_bridge.preferences import get_preferences
    from blender_codex_bridge.runtime import get_runtime

    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
    prefs = get_preferences()
    assert prefs is not None
    scenario = BackupScenario(bpy, prefs, get_runtime(), bundle, phase, False, token)
    bpy.app.timers.register(scenario.tick, first_interval=.05, persistent=True)


if __name__ == "__main__":
    main()
