"""Run isolated Blender smokes and retain truthful, versioned execution evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CASES = {
    "exclusive_mutation": ("blender_exclusive_mutation_smoke.py", "BLENDER_EXCLUSIVE_MUTATION_OK "),
    "project_save_denial": ("blender_project_save_denial_smoke.py", "BLENDER_PROJECT_SAVE_DENIAL_OK "),
    "core": ("blender_smoke.py", "BLENDER_CODEX_SMOKE_OK "),
    "extended": ("blender_extended_smoke.py", "BRIDGE_EXTENDED_SMOKE "),
    "rig": ("blender_rig_animation_smoke.py", "BLENDER_CODEX_RIG_ANIMATION_SMOKE_OK "),
    "uv_modifiers": (
        "blender_uv_modifier_constraint_smoke.py",
        "BLENDER_CODEX_UV_MODIFIER_CONSTRAINT_SMOKE_OK ",
    ),
    "interaction": ("blender_interaction_smoke.py", "BLENDER_CODEX_INTERACTION_SMOKE_OK "),
    "layout": ("blender_layout_smoke.py", "BLENDER_CODEX_LAYOUT_SMOKE_OK "),
    "geometry_nodes": ("blender_geometry_nodes_smoke.py", "BLENDER_CODEX_GEOMETRY_NODES_SMOKE_OK "),
    "batch": ("blender_batch_smoke.py", "BLENDER_CODEX_BATCH_SMOKE_OK "),
    "seams": ("blender_seams_smoke.py", "BLENDER_CODEX_SEAMS_SMOKE_OK "),
    "uv_islands": ("blender_uv_islands_smoke.py", "BLENDER_CODEX_UV_ISLANDS_SMOKE_OK "),
    "uv_workflow": ("blender_uv_workflow_smoke.py", "BLENDER_CODEX_UV_WORKFLOW_SMOKE_OK "),
    "artist": ("blender_artist_smoke.py", "artist_smoke"),
    "material_ownership": ("blender_material_ownership_smoke.py", "material_ownership_smoke"),
    "undo_lifecycle": ("blender_undo_lifecycle_smoke.py", "BLENDER_UNDO_LIFECYCLE_OK "),
    "scene_evidence": ("blender_scene_evidence_smoke.py", "BLENDER_SCENE_EVIDENCE_OK "),
    "mesh_edit_recovery": ("blender_mesh_edit_recovery_smoke.py", "BLENDER_MESH_EDIT_RECOVERY_OK "),
    "mesh_repair": ("blender_mesh_repair_smoke.py", "BLENDER_MESH_REPAIR_OK "),
    "uv_authoring": ("blender_uv_authoring_smoke.py", "BLENDER_UV_AUTHORING_OK "),
    "prop_workflow": ("blender_prop_workflow_smoke.py", "BLENDER_PROP_WORKFLOW_OK "),
    "uv_analysis": ("blender_uv_analysis_smoke.py", "BLENDER_UV_ANALYSIS_OK "),
    "mesh_analysis": ("blender_mesh_analysis_smoke.py", "BLENDER_MESH_ANALYSIS_OK "),
    "image_assets": ("blender_image_assets_smoke.py", "BLENDER_IMAGE_ASSETS_OK "),
    "shader_groups": ("blender_shader_groups_smoke.py", "BLENDER_SHADER_GROUPS_OK "),
    "undo_capacity": ("blender_undo_capacity_smoke.py", "BLENDER_UNDO_CAPACITY_OK "),
    "shader_settings": ("blender_shader_settings_smoke.py", "BLENDER_SHADER_SETTINGS_OK "),
    "image_revisions": ("blender_image_revisions_smoke.py", "BLENDER_IMAGE_REVISIONS_OK "),
    "field_scanner": ("blender_field_scanner_smoke.py", "BLENDER_FIELD_SCANNER_OK "),
    "texture_paint": ("blender_texture_paint_smoke.py", "BLENDER_TEXTURE_PAINT_OK "),
    "paint_jobs": ("blender_paint_jobs_smoke.py", "BLENDER_PAINT_JOBS_OK "),
    "large_paint": ("blender_large_paint_smoke.py", "BLENDER_LARGE_PAINT_OK "),
    "image_masks": ("blender_image_masks_smoke.py", "BLENDER_IMAGE_MASKS_OK "),
    "pixel_codecs": ("blender_pixel_codecs_smoke.py", "BLENDER_PIXEL_CODECS_OK "),
    "image_alpha": ("blender_image_alpha_smoke.py", "BLENDER_IMAGE_ALPHA_OK "),
    "image_streams": ("blender_image_streams_smoke.py", "BLENDER_IMAGE_STREAMS_OK "),
    "image_delivery": ("blender_image_delivery_smoke.py", "BLENDER_IMAGE_DELIVERY_OK "),
    "image_reopen": ("blender_image_reopen_smoke.py", "BLENDER_IMAGE_REOPEN_READER_OK "),
    "image_portability_probe": ("blender_image_portability_smoke.py", "BLENDER_IMAGE_PORTABILITY_PROBE_READER_OK "),
    "animation_curves": ("blender_animation_curves_smoke.py", "BLENDER_CODEX_ANIMATION_CURVES_SMOKE_OK "),
    "geometry_node_groups": ("blender_geometry_node_groups_smoke.py", "BLENDER_GEOMETRY_NODE_GROUPS_OK "),
    "task_plans": ("blender_task_plans_smoke.py", "BLENDER_TASK_PLANS_READER_OK "),
    "artist_loop": ("blender_artist_loop_smoke.py", "BLENDER_ARTIST_LOOP_OK "),
    "asset_delivery": ("blender_asset_delivery_smoke.py", "BLENDER_ASSET_DELIVERY_READER_OK "),
    "weight_brushes": ("blender_weight_brushes_smoke.py", "BLENDER_CODEX_WEIGHT_BRUSHES_SMOKE_OK "),
    "rig_drivers": ("blender_rig_drivers_smoke.py", "BLENDER_RIG_DRIVERS_OK "),
    "surface_brushes": ("blender_surface_brushes_smoke.py", "BLENDER_SURFACE_BRUSHES_OK "),
    "mesh_uv_refinement": ("blender_mesh_uv_refinement_smoke.py", "BLENDER_MESH_UV_REFINEMENT_OK "),
    "rig_ik": ("blender_rig_ik_smoke.py", "BLENDER_CODEX_RIG_IK_SMOKE_OK "),
    "mesh_surface_projection": ("blender_mesh_surface_projection_smoke.py", "BLENDER_MESH_SURFACE_PROJECTION_OK "),
    "geometry_zone_lifecycle_probe": ("blender_geometry_zone_lifecycle_probe_smoke.py", "BLENDER_GEOMETRY_ZONE_LIFECYCLE_PROBE_READER_OK "),
    "geometry_zone_lifecycle": ("blender_geometry_zone_lifecycle_smoke.py", "BLENDER_GEOMETRY_ZONE_LIFECYCLE_OK "),
    "surface_projection_probe": ("blender_surface_projection_probe_smoke.py", "BLENDER_CODEX_SURFACE_PROJECTION_PROBE_OK "),
    "simulation_cache_probe": ("blender_simulation_cache_probe_smoke.py", "BLENDER_SIMULATION_CACHE_PROBE_OK "),
    "surface_paint": ("blender_surface_paint_smoke.py", "BLENDER_SURFACE_PAINT_OK "),
    "uv_selection_storage": ("blender_uv_selection_storage_smoke.py", "BLENDER_UV_SELECTION_STORAGE_OK "),
    "action_lifecycle_probe": ("blender_action_lifecycle_probe_smoke.py", "BLENDER_CODEX_ACTION_LIFECYCLE_PROBE_OK "),
    "asset_import_probe": ("blender_asset_import_probe_smoke.py", "BLENDER_ASSET_IMPORT_PROBE_READER_OK "),
    "cinematic_variant_probe": ("blender_cinematic_variant_probe_smoke.py", "BLENDER_CINEMATIC_VARIANT_PROBE_OK "),
    "nla_lifecycle_probe": ("blender_nla_lifecycle_probe_smoke.py", "BLENDER_NLA_LIFECYCLE_PROBE_OK "),
    "cinematic_variants": ("blender_cinematic_variants_smoke.py", "BLENDER_CINEMATIC_VARIANTS_READER_OK "),
    "asset_import": ("blender_asset_import_smoke.py", "BLENDER_ASSET_IMPORT_READER_OK "),
    "action_lifecycle": ("blender_action_lifecycle_smoke.py", "BLENDER_ACTION_LIFECYCLE_READER_OK "),
    "nla_lifecycle": ("blender_nla_lifecycle_smoke.py", "BLENDER_NLA_LIFECYCLE_OK "),
    "image_recovery_probe": ("blender_image_recovery_probe_smoke.py", "BLENDER_IMAGE_RECOVERY_PROBE_READER_OK "),
    "image_large_recovery_probe": ("blender_image_large_recovery_probe_smoke.py", "BLENDER_IMAGE_LARGE_RECOVERY_PROBE_READER_OK "),
    "image_recovery": ("blender_image_recovery_smoke.py", "BLENDER_IMAGE_RECOVERY_READER_OK "),
    "image_recovery_jobs": ("blender_image_recovery_jobs_smoke.py", "BLENDER_IMAGE_RECOVERY_JOBS_READER_OK "),
    "image_recovery_jobs_large": ("blender_image_recovery_jobs_large_smoke.py", "BLENDER_IMAGE_RECOVERY_JOBS_LARGE_READER_OK "),
    "installed_addon_probe": ("blender_installed_addon_probe_smoke.py", "BLENDER_INSTALLED_ADDON_PROBE_OK "),
    "asset_import_admission": ("blender_asset_import_admission_smoke.py", "BLENDER_ASSET_IMPORT_ADMISSION_OK "),
    "object_drivers": ("blender_object_drivers_smoke.py", "BLENDER_CODEX_OBJECT_DRIVERS_OK "),
    "shader_interface_probe": ("blender_shader_interface_probe_smoke.py", "BLENDER_SHADER_INTERFACE_PROBE_READER_OK "),
    "animation_mutations": ("blender_animation_mutations_smoke.py", "BLENDER_ANIMATION_MUTATIONS_OK "),
    "character_nla": ("blender_character_nla_smoke.py", "BLENDER_CHARACTER_NLA_READER_OK "),
    "rig_binding_probe": ("blender_rig_binding_probe_smoke.py", "BLENDER_RIG_BINDING_PROBE_OK "),
    "rig_binding": ("blender_rig_binding_smoke.py", "BLENDER_RIG_BINDING_OK "),
    "rig_binding_reopen": ("blender_rig_binding_reopen_smoke.py", "BLENDER_RIG_BINDING_READER_OK "),
    "rig_edit_probe": ("blender_rig_edit_probe_smoke.py", "BLENDER_RIG_EDIT_PROBE_OK "),
    "rig_edit_boundaries": ("blender_rig_edit_boundaries_smoke.py", "BLENDER_RIG_EDIT_BOUNDARIES_OK "),
    "rig_edit_reopen": ("blender_rig_edit_boundaries_smoke.py", "BLENDER_RIG_EDIT_READER_OK "),
    "object_rna_mutations": ("blender_object_rna_mutations_smoke.py", "BLENDER_CODEX_OBJECT_RNA_MUTATIONS_OK "),
    "shader_interface": ("blender_shader_interface_smoke.py", "BLENDER_SHADER_INTERFACE_READER_OK "),
    "rigid_lifecycle_probe": ("blender_rigid_lifecycle_probe_smoke.py", "BLENDER_RIGID_LIFECYCLE_PROBE_READER_OK "),
    "rigid_body_scope": ("blender_rigid_body_scope_smoke.py", "BLENDER_RIGID_BODY_SCOPE_OK "),
    "rigid_evaluation_dependencies": ("blender_rigid_evaluation_dependencies_smoke.py", "BLENDER_RIGID_EVALUATION_DEPENDENCIES_OK "),
    "rigid_runtime_getters": ("blender_rigid_runtime_getters_smoke.py", "BLENDER_RIGID_RUNTIME_GETTERS_OK "),
    "rigid_create_new_probe": ("blender_rigid_create_new_probe_smoke.py", "BLENDER_RIGID_CREATE_NEW_PROBE_OK "),
    "portable_blend_writer_probe": ("blender_portable_blend_worker_probe_smoke.py", "BLENDER_PORTABLE_BLEND_WORKER_WRITER_OK "),
    "portable_blend_worker_probe": ("blender_portable_blend_worker_probe_smoke.py", "BLENDER_PORTABLE_BLEND_WORKER_WORKER_OK "),
    "portable_blend_reader_probe": ("blender_portable_blend_worker_probe_smoke.py", "BLENDER_PORTABLE_BLEND_WORKER_READER_OK "),
    "rigid_startup_defaults_probe": ("blender_rigid_startup_defaults_probe_smoke.py", "BLENDER_RIGID_STARTUP_DEFAULTS_PROBE_OK "),
    "rigid_scope_profile_probe": ("blender_rigid_scope_profile_probe_smoke.py", "BLENDER_RIGID_SCOPE_PROFILE_PROBE_OK "),
    "scene_edit_probe": ("blender_scene_edit_probe_smoke.py", "BLENDER_SCENE_EDIT_PROBE_OK "),
    "scene_collection_scope": ("blender_scene_collection_scope_smoke.py", "BLENDER_SCENE_COLLECTION_SCOPE_OK "),
    "scene_edit_boundaries": ("blender_scene_edit_boundaries_smoke.py", "BLENDER_SCENE_EDIT_BOUNDARIES_OK "),
    "scene_checkpoint_admission": ("blender_scene_checkpoint_admission_smoke.py", "BLENDER_SCENE_CHECKPOINT_ADMISSION_OK "),
    "render_scope_probe": ("blender_render_scope_probe_smoke.py", "BLENDER_RENDER_SCOPE_PROBE_OK "),
    "render_boundaries": ("blender_render_boundaries_smoke.py", "BLENDER_RENDER_BOUNDARIES_OK "),
    "render_adversarial": ("blender_render_adversarial_smoke.py", "BLENDER_RENDER_ADVERSARIAL_OK "),
    "render_boundaries_interactive": ("blender_render_boundaries_smoke.py", "BLENDER_RENDER_BOUNDARIES_OK "),
    "render_checkpoint_probe": ("blender_render_checkpoint_probe_smoke.py", "BLENDER_RENDER_CHECKPOINT_PROBE_OK "),
}
# Each phase must exit successfully before a new process can consume its artifacts.
PHASED_CASES = {
    "image_reopen": ("BLENDER_IMAGE_REOPEN_WRITER_OK ", "BLENDER_IMAGE_REOPEN_READER_OK "),
    "image_portability_probe": ("BLENDER_IMAGE_PORTABILITY_PROBE_WRITER_OK ", "BLENDER_IMAGE_PORTABILITY_PROBE_READER_OK "),
    "task_plans": ("BLENDER_TASK_PLANS_WRITER_OK ", "BLENDER_TASK_PLANS_READER_OK "),
    "asset_delivery": ("BLENDER_ASSET_DELIVERY_WRITER_OK ", "BLENDER_ASSET_DELIVERY_READER_OK "),
    "geometry_zone_lifecycle_probe": ("BLENDER_GEOMETRY_ZONE_LIFECYCLE_PROBE_WRITER_OK ", "BLENDER_GEOMETRY_ZONE_LIFECYCLE_PROBE_READER_OK "),
    "asset_import_probe": ("BLENDER_ASSET_IMPORT_PROBE_WRITER_OK ", "BLENDER_ASSET_IMPORT_PROBE_READER_OK "),
    "cinematic_variants": ("BLENDER_CINEMATIC_VARIANTS_WRITER_OK ", "BLENDER_CINEMATIC_VARIANTS_READER_OK "),
    "asset_import": ("BLENDER_ASSET_IMPORT_WRITER_OK ", "BLENDER_ASSET_IMPORT_READER_OK "),
    "action_lifecycle": ("BLENDER_ACTION_LIFECYCLE_WRITER_OK ", "BLENDER_ACTION_LIFECYCLE_READER_OK "),
    "image_recovery_probe": ("BLENDER_IMAGE_RECOVERY_PROBE_WRITER_OK ", "BLENDER_IMAGE_RECOVERY_PROBE_READER_OK "),
    "image_large_recovery_probe": ("BLENDER_IMAGE_LARGE_RECOVERY_PROBE_WRITER_OK ", "BLENDER_IMAGE_LARGE_RECOVERY_PROBE_READER_OK "),
    "image_recovery": ("BLENDER_IMAGE_RECOVERY_WRITER_OK ", "BLENDER_IMAGE_RECOVERY_READER_OK "),
    "image_recovery_jobs": ("BLENDER_IMAGE_RECOVERY_JOBS_WRITER_OK ", "BLENDER_IMAGE_RECOVERY_JOBS_READER_OK "),
    "image_recovery_jobs_large": ("BLENDER_IMAGE_RECOVERY_JOBS_LARGE_WRITER_OK ", "BLENDER_IMAGE_RECOVERY_JOBS_LARGE_READER_OK "),
    "shader_interface_probe": ("BLENDER_SHADER_INTERFACE_PROBE_WRITER_OK ", "BLENDER_SHADER_INTERFACE_PROBE_READER_OK "),
    "character_nla": ("BLENDER_CHARACTER_NLA_WRITER_OK ", "BLENDER_CHARACTER_NLA_READER_OK "),
    "shader_interface": ("BLENDER_SHADER_INTERFACE_WRITER_OK ", "BLENDER_SHADER_INTERFACE_READER_OK "),
    "rig_edit_reopen": ("BLENDER_RIG_EDIT_WRITER_OK ", "BLENDER_RIG_EDIT_READER_OK "),
    "rig_binding_reopen": ("BLENDER_RIG_BINDING_WRITER_OK ", "BLENDER_RIG_BINDING_READER_OK "),
    "rigid_lifecycle_probe": ("BLENDER_RIGID_LIFECYCLE_PROBE_WRITER_OK ", "BLENDER_RIGID_LIFECYCLE_PROBE_READER_OK "),
}
OPT_IN_CASES = set(PHASED_CASES)
OPT_IN_CASES.add("surface_projection_probe")
OPT_IN_CASES.add("simulation_cache_probe")
OPT_IN_CASES.add("action_lifecycle_probe")
OPT_IN_CASES.add("cinematic_variant_probe")
OPT_IN_CASES.add("nla_lifecycle_probe")
OPT_IN_CASES.add("installed_addon_probe")
OPT_IN_CASES.add("asset_import_admission")
OPT_IN_CASES.add("rig_binding_probe")
OPT_IN_CASES.add("rig_binding")
OPT_IN_CASES.add("rig_edit_probe")
OPT_IN_CASES.add("rigid_body_scope")
OPT_IN_CASES.add("rigid_evaluation_dependencies")
OPT_IN_CASES.add("rigid_runtime_getters")
OPT_IN_CASES.add("rigid_create_new_probe")
PORTABLE_BLEND_RESEARCH_PHASES = {
    "portable_blend_writer_probe": "writer",
    "portable_blend_worker_probe": "worker",
    "portable_blend_reader_probe": "reader",
}
OPT_IN_CASES.update(PORTABLE_BLEND_RESEARCH_PHASES)
OPT_IN_CASES.add("rigid_startup_defaults_probe")
OPT_IN_CASES.add("rigid_scope_profile_probe")
OPT_IN_CASES.add("scene_edit_probe")
OPT_IN_CASES.add("scene_collection_scope")
OPT_IN_CASES.add("scene_edit_boundaries")
OPT_IN_CASES.add("scene_checkpoint_admission")
OPT_IN_CASES.add("render_scope_probe")
OPT_IN_CASES.add("render_boundaries")
OPT_IN_CASES.add("render_adversarial")
OPT_IN_CASES.add("render_boundaries_interactive")
OPT_IN_CASES.add("render_checkpoint_probe")
INTERACTIVE_CASES = {"undo_lifecycle", "mesh_edit_recovery", "mesh_repair", "uv_authoring", "prop_workflow", "uv_analysis", "mesh_analysis", "image_assets", "shader_groups", "undo_capacity", "shader_settings", "image_revisions", "field_scanner", "texture_paint"}


INTERACTIVE_CASES.add("exclusive_mutation")
OPT_IN_CASES.add("exclusive_mutation")
INTERACTIVE_CASES.add("paint_jobs")
INTERACTIVE_CASES.add("large_paint")
INTERACTIVE_CASES.add("image_masks")
INTERACTIVE_CASES.add("image_alpha")
INTERACTIVE_CASES.add("image_streams")
INTERACTIVE_CASES.add("image_delivery")
INTERACTIVE_CASES.add("mesh_uv_refinement")
INTERACTIVE_CASES.add("mesh_surface_projection")
INTERACTIVE_CASES.add("surface_paint")
INTERACTIVE_CASES.add("simulation_cache_probe")
INTERACTIVE_CASES.add("nla_lifecycle_probe")
INTERACTIVE_CASES.add("cinematic_variants")
INTERACTIVE_CASES.add("nla_lifecycle")
INTERACTIVE_CASES.add("character_nla")
INTERACTIVE_CASES.add("shader_interface")
INTERACTIVE_CASES.add("image_recovery_jobs")
INTERACTIVE_CASES.add("image_recovery_jobs_large")
INTERACTIVE_CASES.update({"portable_blend_writer_probe", "portable_blend_reader_probe"})
INTERACTIVE_CASES.add("rigid_startup_defaults_probe")
INTERACTIVE_CASES.add("rigid_scope_profile_probe")
INTERACTIVE_CASES.add("render_boundaries_interactive")


def success_payload(output: str, marker: str) -> dict | None:
    for line in output.splitlines():
        if marker.endswith(" "):
            if not line.startswith(marker):
                continue
            candidate = line[len(marker) :]
        else:
            candidate = line
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and (marker.endswith(" ") or value.get(marker) == "PASS"):
            return value
    return None


def _run_process(blender: Path, case: str, output: Path, timeout: int, *,
                 phase: str | None = None, bundle: Path | None = None,
                 phase_marker: str | None = None) -> dict:
    filename, marker = CASES[case]
    script = ROOT / "scripts" / filename
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(script),
    ]
    interactive = case in INTERACTIVE_CASES
    if interactive:
        command.remove("--background")
    label = case if phase is None else f"{case}-{phase}"
    if phase is not None:
        if bundle is None or phase_marker is None:
            raise ValueError("Phased cases require an owned bundle and success marker")
        command.extend(["--", "--bridge-phase", phase, "--bridge-bundle", str(bundle)])
        marker = phase_marker
    # Blender writes quit.blend on normal UI exit. Keep it outside the user's temp recovery.
    temporary = output / f"{label}-temp"
    temporary.mkdir()
    environment = dict(os.environ, TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
    process_instance = uuid.uuid4().hex
    environment["BRIDGE_TEST_PROCESS_TOKEN"] = process_instance
    for key, folder in (("BLENDER_USER_CONFIG", "config"), ("BLENDER_USER_SCRIPTS", "scripts"),
                        ("BLENDER_USER_DATAFILES", "datafiles")):
        directory = temporary / folder
        directory.mkdir()
        environment[key] = str(directory)
    launch_cwd = ROOT
    if case in PORTABLE_BLEND_RESEARCH_PHASES:
        # Research-only operational profile. This is not an OS/network sandbox.
        # Do not inherit credential variables or arbitrary Python/Blender paths.
        environment = {key: os.environ[key] for key in (
            "PATH", "LANG", "LC_ALL", "DISPLAY", "XAUTHORITY", "LD_LIBRARY_PATH",
            "LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "MESA_LOADER_DRIVER_OVERRIDE",
            "LP_NUM_THREADS",
        ) if key in os.environ}
        for key in ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
            directory = temporary / ("worker-profile-" + key.lower())
            directory.mkdir(mode=0o700)
            environment[key] = str(directory)
        environment.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary),
                           BRIDGE_TEST_PROCESS_TOKEN=process_instance,
                           BRIDGE_TEST_PORTABLE_BLEND_PHASE=PORTABLE_BLEND_RESEARCH_PHASES[case],
                           GSETTINGS_BACKEND="memory", NO_AT_BRIDGE="1")
        launch_cwd = temporary / "working"
        launch_cwd.mkdir(mode=0o700)
        command.insert(1, "--disable-autoexec")
    log = output / f"{label}.log"
    start = time.monotonic()
    result = {
        "case": case,
        "phase": phase,
        "process_instance": process_instance,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "script": filename,
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "command": command,
        "log": str(log),
        "status": "failed",
        "exit_code": None,
        "execution_mode": (
            "private_windows_desktop" if interactive and sys.platform == "win32"
            else "interactive_display" if interactive else "background"
        ),
    }
    with log.open("wb") as stream:
        try:
            if interactive and sys.platform == "win32":
                from scripts.windows_test_process import run_isolated

                process = run_isolated(command, cwd=launch_cwd, stdout=stream,
                                       timeout=timeout, env=environment)
            else:
                process = subprocess.run(
                    command, cwd=launch_cwd, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=timeout, check=False, env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            result["exit_code"] = process.returncode
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
        except OSError as exc:
            result["launch_error"] = str(exc)
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 65536))
        payload = success_payload(stream.read().decode("utf-8", errors="replace"), marker)
    result["evidence"] = payload
    version = (
        next(
            (
                payload.get(key)
                for key in ("blender_version", "blender", "version")
                if isinstance(payload.get(key), str)
            ),
            None,
        )
        if payload
        else None
    )
    result["blender_version"] = version
    phase_evidence = phase is None or (payload is not None
        and payload.get("phase") == phase
        and payload.get("process_instance") == process_instance
        and type(payload.get("process_id")) is int and payload["process_id"] > 0)
    if result["exit_code"] == 0 and payload is not None and version and phase_evidence:
        result["status"] = "passed"
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["duration_seconds"] = round(time.monotonic() - start, 3)
    return result


def run_case(blender: Path, case: str, output: Path, timeout: int) -> dict:
    if case not in PHASED_CASES:
        return _run_process(blender, case, output, timeout)
    started = time.monotonic()
    bundle = output / f"{case}-bundle"
    bundle.mkdir()
    phases = []
    for phase, marker in zip(("writer", "reader"), PHASED_CASES[case], strict=True):
        result = _run_process(blender, case, output, timeout, phase=phase,
                              bundle=bundle, phase_marker=marker)
        phases.append(result)
        if result["status"] != "passed":
            break
    passed = len(phases) == 2 and all(p["status"] == "passed" for p in phases)
    same_version = passed and phases[0]["blender_version"] == phases[1]["blender_version"]
    return {
        "case": case, "script": CASES[case][0],
        "script_sha256": phases[0]["script_sha256"],
        "status": "passed" if same_version else phases[-1]["status"] if not passed else "failed",
        "blender_version": phases[-1]["blender_version"],
        "execution_mode": phases[0]["execution_mode"],
        "phase_sequence": [p["phase"] for p in phases], "phases": phases,
        "reader_started": len(phases) == 2, "shared_bundle": str(bundle),
        "fresh_process_verified": bool(same_version and phases[0]["process_instance"] != phases[1]["process_instance"]),
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def git_value(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--blender",
        action="append",
        type=Path,
        required=True,
        help="Explicit Blender executable; repeat for a matrix",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New evidence directory; existing paths are refused",
    )
    parser.add_argument("--case", action="append", choices=tuple(CASES), dest="cases")
    parser.add_argument("--package-probe-config", type=Path,
                        help="Pinned candidate/previous ZIP configuration for installed_addon_probe")
    parser.add_argument(
        "--include-interactive",
        action="store_true",
        help="Include UI checks (private desktop on Windows; visible display elsewhere)",
    )
    parser.add_argument(
        "--timeout", type=int, default=180, help="Seconds per isolated process (1-1800)"
    )
    args = parser.parse_args()
    if not 1 <= args.timeout <= 1800:
        parser.error("timeout must be between 1 and 1800 seconds")
    executables = [p.resolve() for p in args.blender]
    if any(not p.is_file() for p in executables):
        parser.error("Each Blender path must be an existing executable file")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    defaults = [case for case in CASES if (args.include_interactive or case not in INTERACTIVE_CASES | OPT_IN_CASES)
                and (case != "installed_addon_probe" or args.package_probe_config is not None)]
    cases = list(dict.fromkeys(args.cases or defaults))
    if "installed_addon_probe" in cases and args.package_probe_config is None:
        parser.error("installed_addon_probe requires --package-probe-config")
    package_proof = None
    # Pass a frozen configuration through only this runner's child environment.
    # The fixture independently freezes and verifies both named ZIP payloads.
    os.environ.pop("BRIDGE_TEST_PACKAGE_PROBE_CONFIG", None)
    if args.package_probe_config is not None:
        with args.package_probe_config.open("rb") as stream:
            configuration = stream.read(512 * 1024 + 1)
        if len(configuration) > 512 * 1024:
            parser.error("Package-probe configuration exceeds 512 KiB")
        frozen_configuration = output / "package-probe-config.json"
        frozen_configuration.write_bytes(configuration)
        os.environ["BRIDGE_TEST_PACKAGE_PROBE_CONFIG"] = str(frozen_configuration)
        package_proof = {"configuration_sha256": hashlib.sha256(configuration).hexdigest(),
                         "configuration": str(frozen_configuration)}
    dirty = git_value("status", "--porcelain")
    report = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "commit": git_value("rev-parse", "HEAD"),
        "worktree_dirty": None if dirty is None else bool(dirty),
        "release_readiness": "NOT_ASSESSED",
        "platform": {"system": platform.system(), "release": platform.release(),
                     "version": platform.version(), "machine": platform.machine()},
        "selected_cases": cases,
        "all_cases_selected": set(cases) == set(CASES),
        "package_probe": package_proof,
        "results": [],
    }
    sources = {
        str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ("addon", "mcp_server", "scripts")
        for p in sorted((ROOT / folder).rglob("*.py"))
    }
    report["source_sha256"] = hashlib.sha256(
        json.dumps(sources, sort_keys=True).encode()
    ).hexdigest()
    report["source_files"] = sources
    report_path = output / "report.json"
    for index, blender in enumerate(executables):
        target = output / f"blender-{index}"
        target.mkdir()
        for case in cases:
            result = run_case(blender, case, target, args.timeout)
            result["blender_executable"] = str(blender)
            report["results"].append(result)
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"{index}:{case}: {result['status']}", flush=True)
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["checks_passed"] = all(r["status"] == "passed" for r in report["results"])
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    return 0 if report["checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
