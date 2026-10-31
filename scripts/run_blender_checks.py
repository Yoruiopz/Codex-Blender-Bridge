"""Run isolated Blender smokes and retain truthful, versioned execution evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import signal
import stat
import struct
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CURRENT_PIXELS_CENSUS_CLASSES = frozenset({
    "ID", "BlendData", "Scene", "Collection", "Object", "MaterialSlot", "Mesh", "MeshVertex", "MeshEdge",
    "MeshPolygon", "MeshLoop", "UVLoopLayers", "MeshUVLoopLayer", "MeshUVLoop", "Attribute", "FloatVectorAttribute",
    "FloatVectorAttributeValue", "Int2Attribute", "Int2AttributeValue", "IntAttribute", "IntAttributeValue",
    "Float2Attribute", "Float2AttributeValue", "BoolAttribute", "BoolAttributeValue", "Material", "ShaderNodeTree",
    "Node", "NodeTree", "NodeSocket", "NodeLink", "ShaderNodeTexImage", "ShaderNodeBsdfPrincipled",
    "ShaderNodeOutputMaterial", "ImageUser", "Image", "PackedFile", "ColorManagedInputColorspaceSettings",
    "PropertyGroup", "CyclesMeshSettings", "CyclesObjectSettings", "CyclesMaterialSettings", "NodeSocketFloat",
    "NodeSocketFloatFactor", "NodeSocketFloatUnsigned", "NodeSocketFloatDistance", "NodeSocketFloatAngle",
    "NodeSocketColor", "NodeSocketVector", "NodeSocketShader", "NodeSocketInt", "NodeSocketBool",
    "TexMapping", "ColorMapping", "ColorRamp", "ColorRampElement", "ColorRampElements",
})
CURRENT_PIXELS_GRAPH_ASSERTIONS = frozenset({"positive_complete_graph", "repeat_complete_graph", "four_grant_denials",
    "native_owner_refusal", "unloaded_helper_refusal", "unlisted_consumer_refusal", "instancer_refusal",
    "manual_geometry_detected", "manual_uv_detected", "manual_mapping_detected", "manual_socket_detected",
    "manual_pixel_detected", "cancel_safe_point", "source_binding_refusal", "provider_binding_refusal",
    "invalid_context_refusal", "no_observation_writes", "source_unchanged"})
CURRENT_PIXELS_READ_CASES = frozenset({"current_pixels_lifecycle_census", "current_pixels_source_graph"})
MESH_STORAGE_ASSERTIONS = frozenset({"source_unchanged", "selected_active_mesh", "canonical_runtime",
    "original_helper_bytes", "no_public_registration", "all_prefix_recorded", "no_native_after_accepted_stop",
    "protected_measured"})

MESH_STORAGE_CASE = "mesh_storage_owned_job"
MESH_STORAGE_CONTROL_CASE = "mesh_storage_first_job_control"
MESH_STORAGE_CONTROL_PROFILE = "MESH_STORAGE_FIRST_JOB_UNTRACED_CONTROL_V1"
MESH_STORAGE_CONTROL_MARKER = "BLENDER_MESH_STORAGE_FIRST_JOB_CONTROL_DIAGNOSTIC "
MESH_STORAGE_CONTROL_REPORT = "mesh-storage-first-job-control.json"
MESH_STORAGE_TIMING_CASE = "mesh_storage_atomic_phase_timing"
MESH_STORAGE_TIMING_PROFILE = "MESH_STORAGE_ATOMIC_PHASE_OBSERVED_DIAGNOSTIC_V1"
MESH_STORAGE_TIMING_MARKER = "BLENDER_MESH_STORAGE_ATOMIC_PHASE_TIMING_DIAGNOSTIC "
MESH_STORAGE_TIMING_REPORT = "mesh-storage-atomic-phase-timing.json"
MESH_STORAGE_INSPECTION_CASE = "mesh_storage_phased_inspection"
MESH_STORAGE_INSPECTION_PROFILE = "MESH_STORAGE_PHASED_INSPECTION_NATIVE_V1"
MESH_STORAGE_INSPECTION_MARKER = "BLENDER_MESH_STORAGE_PHASED_INSPECTION_OK "
MESH_STORAGE_INSPECTION_REPORT = "mesh-storage-phased-inspection.json"
MESH_STORAGE_COST_CASE = "mesh_storage_inspection_cost_timing"
MESH_STORAGE_COST_PROFILE = "MESH_STORAGE_INSPECTION_COST_OBSERVED_V1"
MESH_STORAGE_COST_MARKER = "BLENDER_MESH_STORAGE_INSPECTION_COST_DIAGNOSTIC "
MESH_STORAGE_COST_REPORT = "mesh-storage-inspection-cost.json"
MESH_STORAGE_COST_LABELS = ("driver_advance", "gate_pure", "source_seal_verify", "metadata_plan", "collection_bindings", "checkpoint_roles_init")
MESH_STORAGE_INSPECTION_LIMITS = {
    "success_only": True, "inspection_only": True, "public_tool": False, "mcp": False,
    "writer_handoff": False, "full_artist_workflow": False, "installed_package": False,
    "windows": False, "blender_4_5": False, "physical_cache_passivity": False,
    "exact_native_entry_counters": False, "COW_event_count_observed": False,
    "postboundary_original_SINGLE_values_observed": False, "all_adversaries_qualified": False,
}
MESH_STORAGE_CONTROL_FLAGS = dict.fromkeys(("source_frame_observer_installed", "native_access_counter_observed",
    "checkpoint_boundary_observed", "complete_five_phase_qualified", "preservation_qualified",
    "cancel_disconnect_qualified", "recovery_qualified", "durable_backup_qualified",
    "full_artist_workflow_qualified", "public_tool_qualified", "installed_qualified", "release_acceptance",
    "windows_qualified"), False)

MESH_STORAGE_CASES = {"success": frozenset({"two_rows", "recovery"}),
    "cancel": frozenset({"cancel_after_first"}), "native_failure": frozenset({"failure_after_second_native"}),
    "adversarial": frozenset({"permission_denial", "invalid_context", "stale_preview", "protected_scope_denial",
                             "undelivered", "pause_revoke", "disconnect"}),
    "history_eviction": frozenset({"seed_cancel", "history_eviction"})}

MESH_STORAGE_CASE_ASSERTIONS = frozenset({"complete", "protected_preserved", "original_ids_preserved",
    "uv_roles_preserved", "expected_outcome", "no_late_domain_reads_or_writes"})

MESH_STORAGE_EXECUTABLE_SHA256 = "bafec183e960819c76fe213c000cdb2284c53a87ef6791812f8728b51f07145b"

MESH_STORAGE_HELPER_SHA256 = "a22034b857cc661b24ff611c4dce72a8b0c503e384b5c56f0141aa0abd915d99"

MESH_STORAGE_LIMITS = {"public_tool": False, "mcp": False, "blender_4_5": False, "windows": False,
    "paired_4k_image_lifecycle": False, "full_protected_hierarchy": False, "physical_cache_passivity": False,
    "atomic_rollback": False, "durable_backup": False, "installed_package": False, "full_artist_workflow": False,
    "unselected_SINGLE_logical_values": False}

MESH_STORAGE_MARKER = "BLENDER_MESH_STORAGE_OWNED_JOB_OK "

MESH_STORAGE_PHASES = ("success", "cancel", "native_failure", "adversarial", "history_eviction")

DOMAIN_MAX_REPORT = 8 * 1024 * 1024
NATIVE_SAVE_LARGE_SOURCES = (
    "scripts/blender_native_save_smoke.py", "scripts/run_blender_checks.py", "scripts/blender_artist_sidebar_smoke.py",
    *(f"addon/blender_codex_bridge/{name}.py" for name in (
        "native_save_profile", "native_save_source", "native_save_process", "native_save_reader", "native_save_jobs",
        "native_save_files", "native_save_policy", "runtime", "executor", "command_queue", "protocol", "request_lifecycle",
        "permissions", "server", "transport", "tool_registry", "job_controller")),
    "addon/blender_codex_bridge/tools/native_save.py",
)
NATIVE_SAVE_LARGE_CASES = frozenset({"success_copy", "save_as", "save_current", "replace", "permission_denial",
    "cancel", "revoke", "disconnect", "manual_drift", "reader_failure"})
RUNTIME_BULK_CASE = "runtime_metadata_bulk_probe"
RUNTIME_BULK_BUILDS = {
    "050c02562f81fe80ba616a80198fa02d381e60f8b61b8d39add881f4bca0d7d8": ("4.5.14 LTS", "62c1db4208e8"),
    "bafec183e960819c76fe213c000cdb2284c53a87ef6791812f8728b51f07145b": ("5.2.2 LTS", "d13f752e3b9c"),
}

CASES = {
    "storage_snapshot_root_approval": ("blender_storage_root_approval_smoke.py", "BLENDER_STORAGE_ROOT_APPROVAL_OK "),
    "storage_snapshot_runtime_context": ("blender_storage_snapshot_adapter_smoke.py", "BLENDER_STORAGE_RUNTIME_JOBS_CONTEXT_OK "),
    "system_storage_snapshot": ("blender_system_storage_snapshot_smoke.py", "BLENDER_SYSTEM_STORAGE_SNAPSHOT_OK "),
    "storage_snapshot_adapter": ("blender_storage_snapshot_adapter_smoke.py", "BLENDER_STORAGE_ADAPTER_OK "),
    "storage_snapshot_cleanup": ("blender_storage_snapshot_cleanup_smoke.py", "BLENDER_STORAGE_CLEANUP_OK "),
    "storage_snapshot_dispatch": ("blender_storage_snapshot_dispatch_smoke.py", "BLENDER_STORAGE_DISPATCH_OK "),
    MESH_STORAGE_COST_CASE: ("blender_mesh_storage_job_smoke.py", MESH_STORAGE_COST_MARKER),
    MESH_STORAGE_INSPECTION_CASE: ("blender_mesh_storage_job_smoke.py", MESH_STORAGE_INSPECTION_MARKER),
    MESH_STORAGE_TIMING_CASE: ("blender_mesh_storage_job_smoke.py", MESH_STORAGE_TIMING_MARKER),
    RUNTIME_BULK_CASE: ("blender_runtime_metadata_bulk_probe_smoke.py", "BLENDER_RUNTIME_METADATA_BULK_PROBE_OK "),
    MESH_STORAGE_CASE: ("blender_mesh_storage_job_smoke.py", MESH_STORAGE_MARKER),
    MESH_STORAGE_CONTROL_CASE: ("blender_mesh_storage_job_smoke.py", MESH_STORAGE_CONTROL_MARKER),
    "current_pixels_lifecycle_census": ("blender_current_pixels_lifecycle_smoke.py", "BLENDER_CURRENT_PIXELS_LIFECYCLE_CENSUS_OK "),
    "current_pixels_source_graph": ("blender_current_pixels_lifecycle_smoke.py", "BLENDER_CURRENT_PIXELS_SOURCE_GRAPH_OK "),
    "glb_stage_constructor": ("blender_glb_stage_smoke.py", "BLENDER_GLB_STAGE_CONSTRUCTOR_OK "),
    "glb_stage_structure": ("blender_glb_stage_smoke.py", "BLENDER_GLB_STAGE_STRUCTURE_OK "),
    "glb_stage_runtime": ("blender_glb_stage_runtime_smoke.py", "BLENDER_GLB_STAGE_RUNTIME_OK "),
    "native_project_saving": ("blender_native_save_smoke.py", "BLENDER_NATIVE_PROJECT_SAVING_OK "),
    "native_project_saving_large": ("blender_native_save_smoke.py", "BLENDER_NATIVE_PROJECT_SAVING_LARGE_OK "),
    "geometry_preview": ("blender_geometry_preview_smoke.py", "BLENDER_GEOMETRY_PREVIEW_OK "),
    "geometry_preview_populated_protection": ("blender_geometry_preview_smoke.py", "BLENDER_GEOMETRY_PREVIEW_OK "),
    "weight_edit_guard": ("blender_weight_edit_guard_smoke.py", "BLENDER_WEIGHT_EDIT_GUARD_OK "),
    "isolated_asset_preview_probe": ("blender_isolated_asset_preview_probe_smoke.py", "BLENDER_ISOLATED_ASSET_PREVIEW_WORKER_OK "),
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
    "large_surface_paint": ("blender_large_surface_paint_smoke.py", "BLENDER_LARGE_SURFACE_PAINT_OK "),
    "image_masks": ("blender_image_masks_smoke.py", "BLENDER_IMAGE_MASKS_OK "),
    "pixel_codecs": ("blender_pixel_codecs_smoke.py", "BLENDER_PIXEL_CODECS_OK "),
    "image_alpha": ("blender_image_alpha_smoke.py", "BLENDER_IMAGE_ALPHA_OK "),
    "image_streams": ("blender_image_streams_smoke.py", "BLENDER_IMAGE_STREAMS_OK "),
    "image_delivery": ("blender_image_delivery_smoke.py", "BLENDER_IMAGE_DELIVERY_OK "),
    "image_reopen": ("blender_image_reopen_smoke.py", "BLENDER_IMAGE_REOPEN_READER_OK "),
    "image_portability_probe": ("blender_image_portability_smoke.py", "BLENDER_IMAGE_PORTABILITY_PROBE_READER_OK "),
    "animation_curves": ("blender_animation_curves_smoke.py", "BLENDER_CODEX_ANIMATION_CURVES_SMOKE_OK "),
    "curve_sampling": ("blender_animation_curve_sampling_smoke.py", "BLENDER_ANIMATION_CURVE_SAMPLING_OK "),
    "animation_intent": ("blender_animation_intent_smoke.py", "BLENDER_ANIMATION_INTENT_OK "),
    "surface_publication_probe": ("blender_surface_publication_probe.py", "BLENDER_SURFACE_PUBLICATION_PROBE_OK "),
    "geometry_node_groups": ("blender_geometry_node_groups_smoke.py", "BLENDER_GEOMETRY_NODE_GROUPS_OK "),
    "task_plans": ("blender_task_plans_smoke.py", "BLENDER_TASK_PLANS_READER_OK "),
    "artist_loop": ("blender_artist_loop_smoke.py", "BLENDER_ARTIST_LOOP_OK "),
    "artist_target_verification": ("blender_artist_target_verification_smoke.py", "BLENDER_ARTIST_TARGET_VERIFICATION_OK "),
    "artist_target_sidebar": ("blender_artist_sidebar_smoke.py", "BLENDER_ARTIST_TARGET_SIDEBAR_OK "),
    "artist_quaternion_storage": ("blender_artist_quaternion_storage_smoke.py", "BLENDER_ARTIST_QUATERNION_STORAGE_OK "),
    "artist_quaternion": ("blender_artist_quaternion_smoke.py", "BLENDER_ARTIST_QUATERNION_OK "),
    "uv_edit_storage": ("blender_uv_edit_storage_smoke.py", "BLENDER_UV_EDIT_STORAGE_OK "),
    "uv_edit_boundary_probe": ("blender_uv_edit_boundary_probe.py", "BLENDER_UV_EDIT_BOUNDARY_PROBE_OK "),
    "uv_edit_guard": ("blender_uv_edit_guard_smoke.py", "BLENDER_UV_EDIT_GUARD_OK "),
    "artist_multitarget": ("blender_artist_multitarget_smoke.py", "BLENDER_ARTIST_MULTITARGET_OK "),
    "asset_delivery": ("blender_asset_delivery_smoke.py", "BLENDER_ASSET_DELIVERY_READER_OK "),
    "weight_brushes": ("blender_weight_brushes_smoke.py", "BLENDER_CODEX_WEIGHT_BRUSHES_SMOKE_OK "),
    "rig_drivers": ("blender_rig_drivers_smoke.py", "BLENDER_RIG_DRIVERS_OK "),
    "surface_brushes": ("blender_surface_brushes_smoke.py", "BLENDER_SURFACE_BRUSHES_OK "),
    "sculpt_mask": ("blender_sculpt_mask_smoke.py", "BLENDER_SCULPT_MASK_OK "),
    "mesh_uv_refinement": ("blender_mesh_uv_refinement_smoke.py", "BLENDER_MESH_UV_REFINEMENT_OK "),
    "rig_ik": ("blender_rig_ik_smoke.py", "BLENDER_CODEX_RIG_IK_SMOKE_OK "),
    "mesh_surface_projection": ("blender_mesh_surface_projection_smoke.py", "BLENDER_MESH_SURFACE_PROJECTION_OK "),
    "geometry_zone_lifecycle_probe": ("blender_geometry_zone_lifecycle_probe_smoke.py", "BLENDER_GEOMETRY_ZONE_LIFECYCLE_PROBE_READER_OK "),
    "geometry_zone_lifecycle": ("blender_geometry_zone_lifecycle_smoke.py", "BLENDER_GEOMETRY_ZONE_LIFECYCLE_OK "),
    "surface_projection_probe": ("blender_surface_projection_probe_smoke.py", "BLENDER_CODEX_SURFACE_PROJECTION_PROBE_OK "),
    "simulation_cache_probe": ("blender_simulation_cache_probe_smoke.py", "BLENDER_SIMULATION_CACHE_PROBE_OK "),
    "surface_paint": ("blender_surface_paint_smoke.py", "BLENDER_SURFACE_PAINT_OK "),
    "viewport_framing": ("blender_viewport_framing_smoke.py", "BLENDER_VIEWPORT_FRAMING_OK "),
    "readonly_context_probe": ("blender_readonly_context_probe_smoke.py", "BLENDER_READONLY_CONTEXT_PROBE_OK "),
    "artist_public_entry_probe": ("blender_artist_public_entry_probe_smoke.py", "BLENDER_ARTIST_PUBLIC_ENTRY_PROBE_OK "),
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
    "image_current_pixels_paired_recovery": ("blender_current_pixels_paired_recovery_smoke.py", "BLENDER_CURRENT_PIXELS_PAIRED_RECOVERY_READER_OK "),
    "image_current_pixels_paired_recovery_large": ("blender_current_pixels_paired_recovery_smoke.py", "BLENDER_CURRENT_PIXELS_PAIRED_RECOVERY_READER_OK "),
    "installed_addon_probe": ("blender_installed_addon_probe_smoke.py", "BLENDER_INSTALLED_ADDON_PROBE_OK "),
    "asset_import_admission": ("blender_asset_import_admission_smoke.py", "BLENDER_ASSET_IMPORT_ADMISSION_OK "),
    "object_drivers": ("blender_object_drivers_smoke.py", "BLENDER_CODEX_OBJECT_DRIVERS_OK "),
    "shader_interface_probe": ("blender_shader_interface_probe_smoke.py", "BLENDER_SHADER_INTERFACE_PROBE_READER_OK "),
    "shader_remove_probe": ("blender_shader_remove_probe_smoke.py", "BLENDER_SHADER_REMOVE_PROBE_READER_OK "),
    "shader_remove_loaded_probe": ("blender_shader_remove_probe_smoke.py", "BLENDER_SHADER_REMOVE_LOADED_PROBE_READER_OK "),
    "animation_mutations": ("blender_animation_mutations_smoke.py", "BLENDER_ANIMATION_MUTATIONS_OK "),
    "character_nla": ("blender_character_nla_smoke.py", "BLENDER_CHARACTER_NLA_READER_OK "),
    "character_revision": ("blender_character_revision_smoke.py", "BLENDER_CHARACTER_REVISION_OK "),
    "rig_binding_probe": ("blender_rig_binding_probe_smoke.py", "BLENDER_RIG_BINDING_PROBE_OK "),
    "rig_binding": ("blender_rig_binding_smoke.py", "BLENDER_RIG_BINDING_OK "),
    "rig_binding_reopen": ("blender_rig_binding_reopen_smoke.py", "BLENDER_RIG_BINDING_READER_OK "),
    "rig_edit_probe": ("blender_rig_edit_probe_smoke.py", "BLENDER_RIG_EDIT_PROBE_OK "),
    "rig_edit_boundaries": ("blender_rig_edit_boundaries_smoke.py", "BLENDER_RIG_EDIT_BOUNDARIES_OK "),
    "rig_edit_reopen": ("blender_rig_edit_boundaries_smoke.py", "BLENDER_RIG_EDIT_READER_OK "),
    "object_rna_mutations": ("blender_object_rna_mutations_smoke.py", "BLENDER_CODEX_OBJECT_RNA_MUTATIONS_OK "),
    "shader_interface": ("blender_shader_interface_smoke.py", "BLENDER_SHADER_INTERFACE_READER_OK "),
    "rigid_lifecycle_probe": ("blender_rigid_lifecycle_probe_smoke.py", "BLENDER_RIGID_LIFECYCLE_PROBE_READER_OK "),
    "rigid_timer_probe": ("blender_rigid_timer_probe_smoke.py", "BLENDER_RIGID_TIMER_PROBE_OK "),
    "scene_job_kernel": ("blender_scene_job_kernel_smoke.py", "BLENDER_SCENE_JOB_KERNEL_OK "),
    "executor_history_containment": ("blender_executor_history_containment_smoke.py", "BLENDER_EXECUTOR_HISTORY_CONTAINMENT_OK "),
    "rigid_evaluation_jobs": ("blender_rigid_evaluation_jobs_smoke.py", "BLENDER_RIGID_EVALUATION_JOBS_OK "),
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
    "camera_focus": ("blender_camera_focus_smoke.py", "BLENDER_CAMERA_FOCUS_OK "),
    "scene_checkpoint_admission": ("blender_scene_checkpoint_admission_smoke.py", "BLENDER_SCENE_CHECKPOINT_ADMISSION_OK "),
    "render_scope_probe": ("blender_render_scope_probe_smoke.py", "BLENDER_RENDER_SCOPE_PROBE_OK "),
    "render_boundaries": ("blender_render_boundaries_smoke.py", "BLENDER_RENDER_BOUNDARIES_OK "),
    "render_adversarial": ("blender_render_adversarial_smoke.py", "BLENDER_RENDER_ADVERSARIAL_OK "),
    "render_boundaries_interactive": ("blender_render_boundaries_smoke.py", "BLENDER_RENDER_BOUNDARIES_OK "),
    "render_checkpoint_probe": ("blender_render_checkpoint_probe_smoke.py", "BLENDER_RENDER_CHECKPOINT_PROBE_OK "),
}
# Each phase must exit successfully before a new process can consume its artifacts.
PHASED_CASES = {
    "isolated_asset_preview_probe": ("BLENDER_ISOLATED_ASSET_PREVIEW_WRITER_OK ", "BLENDER_ISOLATED_ASSET_PREVIEW_WORKER_OK "),
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
    "image_current_pixels_paired_recovery": ("BLENDER_CURRENT_PIXELS_PAIRED_RECOVERY_WRITER_OK ", "BLENDER_CURRENT_PIXELS_PAIRED_RECOVERY_READER_OK "),
    "image_current_pixels_paired_recovery_large": ("BLENDER_CURRENT_PIXELS_PAIRED_RECOVERY_WRITER_OK ", "BLENDER_CURRENT_PIXELS_PAIRED_RECOVERY_READER_OK "),
    "shader_interface_probe": ("BLENDER_SHADER_INTERFACE_PROBE_WRITER_OK ", "BLENDER_SHADER_INTERFACE_PROBE_READER_OK "),
    "shader_remove_probe": ("BLENDER_SHADER_REMOVE_PROBE_WRITER_OK ", "BLENDER_SHADER_REMOVE_PROBE_READER_OK "),
    "shader_remove_loaded_probe": ("BLENDER_SHADER_REMOVE_LOADED_PROBE_WRITER_OK ", "BLENDER_SHADER_REMOVE_LOADED_PROBE_READER_OK "),
    "character_nla": ("BLENDER_CHARACTER_NLA_WRITER_OK ", "BLENDER_CHARACTER_NLA_READER_OK "),
    "shader_interface": ("BLENDER_SHADER_INTERFACE_WRITER_OK ", "BLENDER_SHADER_INTERFACE_READER_OK "),
    "rig_edit_reopen": ("BLENDER_RIG_EDIT_WRITER_OK ", "BLENDER_RIG_EDIT_READER_OK "),
    "rig_binding_reopen": ("BLENDER_RIG_BINDING_WRITER_OK ", "BLENDER_RIG_BINDING_READER_OK "),
    "rigid_lifecycle_probe": ("BLENDER_RIGID_LIFECYCLE_PROBE_WRITER_OK ", "BLENDER_RIGID_LIFECYCLE_PROBE_READER_OK "),
}
PAIRED_RECOVERY_PROFILES = {
    "image_current_pixels_paired_recovery": "SMALL2X2",
    "image_current_pixels_paired_recovery_large": "LARGE4K",
}
OPT_IN_CASES = set(PHASED_CASES)
OPT_IN_CASES.add("current_pixels_lifecycle_census")
OPT_IN_CASES.add("current_pixels_source_graph")
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
OPT_IN_CASES.add("rigid_timer_probe")
OPT_IN_CASES.add("scene_job_kernel")
OPT_IN_CASES.add("executor_history_containment")
OPT_IN_CASES.add("rigid_evaluation_jobs")
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
OPT_IN_CASES.add("camera_focus")
OPT_IN_CASES.add("curve_sampling")
OPT_IN_CASES.add("surface_publication_probe")
OPT_IN_CASES.add("sculpt_mask")
OPT_IN_CASES.add("character_revision")
OPT_IN_CASES.add("artist_target_verification")
OPT_IN_CASES.add("artist_target_sidebar")
OPT_IN_CASES.add("artist_quaternion_storage")
OPT_IN_CASES.add("artist_quaternion")
OPT_IN_CASES.add("animation_intent")
OPT_IN_CASES.update({"glb_stage_constructor", "glb_stage_structure", "glb_stage_runtime"})
OPT_IN_CASES.add("uv_edit_storage")
OPT_IN_CASES.add("uv_edit_boundary_probe")
OPT_IN_CASES.add("large_surface_paint")
OPT_IN_CASES.add("uv_edit_guard")
OPT_IN_CASES.add("weight_edit_guard")
OPT_IN_CASES.add("scene_checkpoint_admission")
OPT_IN_CASES.add("render_scope_probe")
OPT_IN_CASES.add("render_boundaries")
OPT_IN_CASES.add("render_adversarial")
OPT_IN_CASES.add("render_boundaries_interactive")
OPT_IN_CASES.add("render_checkpoint_probe")
INTERACTIVE_CASES = {"undo_lifecycle", "mesh_edit_recovery", "mesh_repair", "uv_authoring", "prop_workflow", "uv_analysis", "mesh_analysis", "image_assets", "shader_groups", "undo_capacity", "shader_settings", "image_revisions", "field_scanner", "texture_paint"}
INTERACTIVE_CASES.add("native_project_saving")
OPT_IN_CASES.add("native_project_saving")
INTERACTIVE_CASES.add("native_project_saving_large")
OPT_IN_CASES.add("native_project_saving_large")


INTERACTIVE_CASES.add("geometry_preview")
OPT_IN_CASES.add("geometry_preview")
INTERACTIVE_CASES.add("geometry_preview_populated_protection")
OPT_IN_CASES.add("geometry_preview_populated_protection")
INTERACTIVE_CASES.add("isolated_asset_preview_probe")
INTERACTIVE_CASES.add("exclusive_mutation")
OPT_IN_CASES.add("exclusive_mutation")
INTERACTIVE_CASES.add("artist_multitarget")
INTERACTIVE_CASES.add("artist_target_sidebar")
OPT_IN_CASES.add("artist_multitarget")
INTERACTIVE_CASES.add("paint_jobs")
INTERACTIVE_CASES.add("large_paint")
INTERACTIVE_CASES.add("large_surface_paint")
INTERACTIVE_CASES.add("image_masks")
INTERACTIVE_CASES.add("image_alpha")
INTERACTIVE_CASES.add("image_streams")
INTERACTIVE_CASES.add("image_delivery")
INTERACTIVE_CASES.add("mesh_uv_refinement")
INTERACTIVE_CASES.add("mesh_surface_projection")
INTERACTIVE_CASES.add("surface_paint")
INTERACTIVE_CASES.add("viewport_framing")
OPT_IN_CASES.add("viewport_framing")
INTERACTIVE_CASES.add("readonly_context_probe")
OPT_IN_CASES.add("readonly_context_probe")
INTERACTIVE_CASES.add("artist_public_entry_probe")
OPT_IN_CASES.add("artist_public_entry_probe")
INTERACTIVE_CASES.add("simulation_cache_probe")
INTERACTIVE_CASES.add("nla_lifecycle_probe")
INTERACTIVE_CASES.add("cinematic_variants")
INTERACTIVE_CASES.add("nla_lifecycle")
INTERACTIVE_CASES.add("character_nla")
INTERACTIVE_CASES.add("shader_interface")
INTERACTIVE_CASES.add("shader_remove_probe")
INTERACTIVE_CASES.add("shader_remove_loaded_probe")
INTERACTIVE_CASES.add("image_recovery_jobs")
INTERACTIVE_CASES.add("image_recovery_jobs_large")
INTERACTIVE_CASES.update(PAIRED_RECOVERY_PROFILES)
INTERACTIVE_CASES.update({"portable_blend_writer_probe", "portable_blend_reader_probe"})
INTERACTIVE_CASES.add("rigid_startup_defaults_probe")
INTERACTIVE_CASES.add("rigid_scope_profile_probe")
INTERACTIVE_CASES.add("rigid_timer_probe")
INTERACTIVE_CASES.add("scene_job_kernel")
INTERACTIVE_CASES.add("executor_history_containment")
INTERACTIVE_CASES.add("rigid_evaluation_jobs")
INTERACTIVE_CASES.add("render_boundaries_interactive")
INTERACTIVE_CASES.add("animation_intent")
INTERACTIVE_CASES.update({"glb_stage_constructor", "glb_stage_structure", "glb_stage_runtime"})
INTERACTIVE_CASES.add(MESH_STORAGE_CASE)
OPT_IN_CASES.add(MESH_STORAGE_CASE)
INTERACTIVE_CASES.add(MESH_STORAGE_CONTROL_CASE)
OPT_IN_CASES.add(MESH_STORAGE_CONTROL_CASE)
OPT_IN_CASES.add(MESH_STORAGE_TIMING_CASE)
INTERACTIVE_CASES.add(MESH_STORAGE_TIMING_CASE)
OPT_IN_CASES.add(MESH_STORAGE_INSPECTION_CASE)
INTERACTIVE_CASES.add(MESH_STORAGE_INSPECTION_CASE)
OPT_IN_CASES.add(MESH_STORAGE_COST_CASE)
INTERACTIVE_CASES.add(MESH_STORAGE_COST_CASE)
OPT_IN_CASES.add(RUNTIME_BULK_CASE)

GLB_STAGE_CASES = frozenset({"glb_stage_constructor", "glb_stage_structure", "glb_stage_runtime"})

GLB_STAGE_SOURCES = (
    "scripts/blender_glb_stage_smoke.py",
    "scripts/run_blender_checks.py",
    "scripts/blender_artist_sidebar_smoke.py",
    "addon/blender_codex_bridge/glb_stage_driver.py",
    "addon/blender_codex_bridge/glb_stage_profile.py",
    "addon/blender_codex_bridge/glb_stage_source.py",
    "addon/blender_codex_bridge/glb_stage_state.py",
    "addon/blender_codex_bridge/asset_glb_import_plan.py",
    "addon/blender_codex_bridge/asset_glb_preflight.py",
)
GLB_STAGE_BUILDS = {(4, 5, 14): "62c1db4208e8", (5, 2, 2): "d13f752e3b9c"}
GLB_STAGE_MAX_EVIDENCE = 8 * 1024**2




STORAGE_ADAPTER_CASE = "storage_snapshot_adapter"

STORAGE_ADAPTER_PHASES = ("absent", "valid", "malformed", "permission_controls", "stop_controls", "writer_failure", "turn_binding")

STORAGE_ADAPTER_MAX_REPORT = 8 * 1024 * 1024

STORAGE_ADAPTER_BUILDS = {(4, 5, 14): "62c1db4208e8", (5, 2, 2): "d13f752e3b9c"}

STORAGE_ADAPTER_BINARY_HASHES = {
    (4, 5, 14): "050c02562f81fe80ba616a80198fa02d381e60f8b61b8d39add881f4bca0d7d8",
    (5, 2, 2): "bafec183e960819c76fe213c000cdb2284c53a87ef6791812f8728b51f07145b",
}

STORAGE_CLEANUP_CASE = "storage_snapshot_cleanup"

STORAGE_CLEANUP_PHASES = ("success", "permission_denial", "ownership_tamper", "stop_retry", "partial_failure", "sixteen_captures")

STORAGE_CLEANUP_MAX_REPORT = 8 * 1024 * 1024

STORAGE_DISPATCH_CASE = "storage_snapshot_dispatch"

STORAGE_DISPATCH_PHASES = ("success_denial", "stops", "failures")

STORAGE_DISPATCH_MAX_REPORT = 8 * 1024 * 1024
STORAGE_ROOT_APPROVAL_CASE = "storage_snapshot_root_approval"
STORAGE_RUNTIME_CONTEXT_CASE = "storage_snapshot_runtime_context"
OPT_IN_CASES.add(STORAGE_RUNTIME_CONTEXT_CASE)
INTERACTIVE_CASES.add(STORAGE_RUNTIME_CONTEXT_CASE)


OPT_IN_CASES.update({"system_storage_snapshot", STORAGE_ADAPTER_CASE, STORAGE_CLEANUP_CASE, STORAGE_DISPATCH_CASE, STORAGE_RUNTIME_CONTEXT_CASE, STORAGE_ROOT_APPROVAL_CASE})
INTERACTIVE_CASES.update({"system_storage_snapshot", STORAGE_ADAPTER_CASE, STORAGE_CLEANUP_CASE, STORAGE_DISPATCH_CASE, STORAGE_RUNTIME_CONTEXT_CASE, STORAGE_ROOT_APPROVAL_CASE})

def _cloth_file(path: Path, maximum: int, *, content: bool = False) -> tuple[str, bytes]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
        raise ValueError("CLOTH_FILE_SHAPE")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))

    def identity(item):
        return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns

    checksum, count, pieces = hashlib.sha256(), 0, []
    try:
        if identity(os.fstat(descriptor)) != identity(before):
            raise ValueError("CLOTH_FILE_CHANGED")
        while True:
            raw = os.read(descriptor, min(65536, maximum + 1 - count))
            if not raw:
                break
            count += len(raw)
            if count > maximum:
                raise ValueError("CLOTH_FILE_BUDGET")
            checksum.update(raw)
            if content:
                pieces.append(raw)
        if (count != before.st_size or identity(os.fstat(descriptor)) != identity(before)
                or identity(path.lstat()) != identity(before)):
            raise ValueError("CLOTH_FILE_CHANGED")
    finally:
        os.close(descriptor)
    return checksum.hexdigest(), b"".join(pieces)


def _cloth_unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("CLOTH_DUPLICATE_KEY")
        result[name] = value
    return result


def _cloth_nonfinite(_value):
    raise ValueError("CLOTH_NONFINITE_JSON")


def _storage_adapter_inputs(blender):
    from scripts import blender_storage_snapshot_adapter_smoke as fixture
    names = fixture.source_names(ROOT)
    required = {"scripts/blender_storage_snapshot_adapter_smoke.py", "scripts/run_blender_checks.py",
                "scripts/blender_artist_sidebar_smoke.py"}
    required.update(str(path.relative_to(ROOT)) for path in (ROOT / "addon/blender_codex_bridge").rglob("*.py"))
    if (type(names) not in (tuple, list) or any(type(name) is not str or not name
            or Path(name).is_absolute() or ".." in Path(name).parts for name in names)
            or len(set(names)) != len(names) or set(names) != required):
        raise ValueError("STORAGE_ADAPTER_SOURCE_INVENTORY")
    binary = {"path": str(blender.resolve()), "sha256": _cloth_file(blender, 1024**3)[0]}
    if binary["sha256"] not in STORAGE_ADAPTER_BINARY_HASHES.values():
        raise ValueError("STORAGE_ADAPTER_BINARY_NOT_PINNED")
    return {"source_fingerprints": {name: _cloth_file(ROOT / name, 1024**2)[0] for name in names}, "binary": binary}


def _storage_adapter_retained(full, bundle):
    """Reparse actual owned native bytes independently of fixture assertions."""
    import importlib.util
    module_name = "_bcb_storage_adapter_evidence_reader"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "addon/blender_codex_bridge/blend_storage_sdna.py")
    if spec is None or spec.loader is None:
        raise ValueError("STORAGE_ADAPTER_READER_REQUIRED")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    names = module.CYCLES_NAMES if full["version"][0] == 4 else module.CYCLES_502_NAMES
    def owned_leaf(name):
        return (name.startswith("bcb-storage-") and len(name) == 44
                and all(char in "0123456789abcdef" for char in name[12:]))
    for row in full["cases"]:
        root = bundle / (full["phase"] + "-" + row["name"] + "-owned")
        root_stat = root.lstat()
        if (row["owned_root"] != str(root) or not stat.S_ISDIR(root_stat.st_mode)
                or stat.S_IMODE(root_stat.st_mode) != 0o700):
            raise ValueError("STORAGE_ADAPTER_OWNED_ROOT")
        cells = row["journal"]["snapshots"]
        if type(cells) is not list or len(cells) > 1:
            raise ValueError("STORAGE_ADAPTER_JOURNAL_SHAPE")
        for cell in cells:
            directory = Path(cell["directory"])
            if (cell["root"] != str(root) or cell["root_identity"] != [root_stat.st_dev, root_stat.st_ino]
                    or type(cell["root_identity"]) is not list or any(type(value) is not int for value in cell["root_identity"])
                    or type(cell["directory_identity"]) is not list
                    or any(type(value) is not int for value in cell["directory_identity"])
                    or directory.parent != root or not owned_leaf(directory.name)
                    or cell["filepath"] != str(directory / "snapshot.blend")):
                raise ValueError("STORAGE_ADAPTER_JOURNAL_PATH_BINDING")
        record, retained, targets = row["native_file"], row["retained_parser"], row["raw_targets"]
        if (type(targets) is not list or len(targets) != 2 or any(type(target) is not dict
                or set(target) != {"scene_name", "view_layer_name"}
                or any(type(value) is not str or not value or len(value) > 128 for value in target.values()) for target in targets)
                or targets[0] == targets[1]):
            raise ValueError("STORAGE_ADAPTER_RAW_TARGETS")
        if record is None:
            if retained != []:
                raise ValueError("STORAGE_ADAPTER_UNEXPECTED_PARSER_PROOF")
            # No extra child or hidden positive file may escape the receipt.
            children = list(root.iterdir())
            if len(children) > 1:
                raise ValueError("STORAGE_ADAPTER_UNEXPECTED_OWNED_CHILD")
            for child in children:
                info = child.lstat()
                if (not stat.S_ISDIR(info.st_mode) or not owned_leaf(child.name) or len(cells) != 1
                        or cells[0]["directory"] != str(child)
                        or cells[0]["directory_identity"] != [info.st_dev, info.st_ino]
                        or stat.S_IMODE(info.st_mode) != (0o500 if row["name"] == "writer_failure" else 0o700)):
                    raise ValueError("STORAGE_ADAPTER_UNEXPECTED_OWNED_CHILD")
                files = list(child.iterdir())
                if len(files) > 1 or any(path.name != "snapshot.blend" or not stat.S_ISREG(path.lstat().st_mode)
                                       or path.stat().st_size != 0 for path in files):
                    raise ValueError("STORAGE_ADAPTER_UNREPORTED_NATIVE_FILE")
            continue
        if type(record) is not dict or set(record) != {"path", "bytes", "sha256"}:
            raise ValueError("STORAGE_ADAPTER_NATIVE_RECEIPT")
        path = Path(record["path"])
        leaf = path.parent.name
        parent_stat = path.parent.lstat()
        if (path.parent.parent != root or path.name != "snapshot.blend" or not owned_leaf(leaf)
                or not stat.S_ISDIR(parent_stat.st_mode) or stat.S_IMODE(parent_stat.st_mode) != 0o700
                or len(cells) != 1 or cells[0]["directory"] != str(path.parent)
                or cells[0]["directory_identity"] != [parent_stat.st_dev, parent_stat.st_ino]
                or cells[0]["filepath"] != str(path) or list(root.iterdir()) != [path.parent]
                or list(path.parent.iterdir()) != [path]):
            raise ValueError("STORAGE_ADAPTER_NATIVE_PATH")
        checksum, _ = _cloth_file(path, 1024**3)
        expected = {"path": str(path), "bytes": path.stat().st_size, "sha256": checksum}
        if record != expected or type(record["bytes"]) is not int or type(retained) is not list or len(retained) != 2:
            raise ValueError("STORAGE_ADAPTER_NATIVE_FILE_CHANGED")
        info = path.lstat()
        identity = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
        if (cells[0]["file_identity"] not in ([], identity)
                or type(cells[0]["file_identity"]) is not list
                or any(type(value) is not int for value in cells[0]["file_identity"])
                or (cells[0]["file_bytes"] is not None and type(cells[0]["file_bytes"]) is not int)
                or cells[0]["file_bytes"] not in (None, info.st_size)
                or cells[0]["file_sha256"] not in (None, checksum)):
            raise ValueError("STORAGE_ADAPTER_JOURNAL_FILE_BINDING")
        for target, proof in zip(targets, retained, strict=True):
            if type(proof) is not dict or proof.get("target") != target:
                raise ValueError("STORAGE_ADAPTER_RETAINED_TARGET")
            try:
                actual = module.inspect_view_layer_storage(str(path), target["scene_name"], target["view_layer_name"], allowed_names=names)
            except module.StorageSnapshotError as error:
                if proof != {"target": target, "error": {"type": "StorageSnapshotError", "reason": error.reason}}:
                    raise ValueError("STORAGE_ADAPTER_INDEPENDENT_REFUSAL") from error
            else:
                if proof != {"target": target, "result": actual}:
                    raise ValueError("STORAGE_ADAPTER_INDEPENDENT_PROJECTION")
        if _cloth_file(path, 1024**3)[0] != checksum:
            raise ValueError("STORAGE_ADAPTER_NATIVE_CHANGED_DURING_PARSE")


def _storage_adapter_validate(payload, phase, bundle, process_instance, process_id, inputs):
    from scripts import blender_storage_snapshot_adapter_smoke as fixture
    try:
        expected = {"schema": fixture.SCHEMA, "profile": fixture.PROFILE, "phase": phase, "completed": True,
                    "process_instance": process_instance, "process_id": process_id, **inputs}
        if (type(payload) is not dict or type(process_id) is not int or process_id <= 0
                or any(type(payload.get(key)) is not type(value) or payload.get(key) != value for key, value in expected.items())):
            raise ValueError("STORAGE_ADAPTER_MARKER_BINDING")
        version = payload.get("version")
        if (type(version) is not list or len(version) != 3 or any(type(part) is not int for part in version)
                or tuple(version) not in STORAGE_ADAPTER_BUILDS
                or type(payload.get("build_hash")) is not str
                or payload["build_hash"] != STORAGE_ADAPTER_BUILDS[tuple(version)]
                or inputs["binary"]["sha256"] != STORAGE_ADAPTER_BINARY_HASHES[tuple(version)]
                or type(payload.get("blender_version")) is not str
                or payload["blender_version"] not in {".".join(map(str, version)), ".".join(map(str, version)) + " LTS"}):
            raise ValueError("STORAGE_ADAPTER_OFFICIAL_BUILD_REQUIRED")
        path, record = bundle / (phase + ".json"), payload.get("full_receipt")
        if (type(record) is not dict or set(record) != {"path", "bytes", "sha256"}
                or record["path"] != str(path) or type(record["bytes"]) is not int
                or not 0 < record["bytes"] <= STORAGE_ADAPTER_MAX_REPORT):
            raise ValueError("STORAGE_ADAPTER_REPORT_RECEIPT")
        checksum, raw = _cloth_file(path, STORAGE_ADAPTER_MAX_REPORT, content=True)
        if checksum != record["sha256"] or len(raw) != record["bytes"]:
            raise ValueError("STORAGE_ADAPTER_REPORT_CHANGED")
        full = json.loads(raw, object_pairs_hook=_cloth_unique, parse_constant=_cloth_nonfinite)
        if (type(full) is not dict or any(type(full.get(key)) is not type(payload.get(key))
                or full.get(key) != payload.get(key) for key in (*expected, "version", "build_hash", "blender_version"))
                or fixture.validate_full(full, phase=phase, process_instance=process_instance,
                    sources=inputs["source_fingerprints"], binary=inputs["binary"], process_id=process_id) is not True):
            raise ValueError("STORAGE_ADAPTER_FULL_REPORT_INVALID")
        for flag in ("runtime_retention_qualified", "full_authored_preservation_qualified", "durable_backup_qualified",
                     "cache_pairing_qualified", "native_calls_preemptible", "windows_qualified",
                     "installed_package_qualified", "cleanup_qualified", "native_memory_cap_claimed",
                     "hidden_Main_passivity_claimed"):
            if full.get(flag) is not False:
                raise ValueError("STORAGE_ADAPTER_BROAD_QUALIFICATION_FORBIDDEN")
        if full.get("native_adapter_qualified") is not True or full.get("source_unchanged") is not True:
            raise ValueError("STORAGE_ADAPTER_COMPLETION_REQUIRED")
        _storage_adapter_retained(full, bundle)
        if _storage_adapter_inputs(Path(inputs["binary"]["path"])) != inputs:
            raise ValueError("STORAGE_ADAPTER_LIVE_INPUT_CHANGED")
        return {"passed": True, "path": str(path), "sha256": checksum, "native_files_independently_reparsed": True}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, AssertionError) as error:
        return {"passed": False, "reason": str(error)[:256] or "STORAGE_ADAPTER_EVIDENCE_INVALID"}


def _storage_adapter_bind(rows, bundle, inputs):
    reports = []
    for index, row in enumerate(rows):
        validation = _storage_adapter_validate(row.get("evidence"), STORAGE_ADAPTER_PHASES[index], bundle,
            row["process_instance"], row.get("launched_process_id"), inputs)
        if not validation["passed"] or validation != row["retained_evidence_validation"]:
            raise ValueError("STORAGE_ADAPTER_PRIOR_RECEIPT_CHANGED")
        reports.append(row["evidence"])
    if (len({row["process_instance"] for row in rows}) != len(rows)
            or len({row["launched_process_id"] for row in rows}) != len(rows)):
        raise ValueError("STORAGE_ADAPTER_REUSED_PROCESS")
    if any(any(report[key] != reports[0][key] for key in ("version", "build_hash", "blender_version")) for report in reports):
        raise ValueError("STORAGE_ADAPTER_CROSS_PHASE_BUILD_CHANGED")
    if _storage_adapter_inputs(Path(inputs["binary"]["path"])) != inputs:
        raise ValueError("STORAGE_ADAPTER_INPUT_CHANGED_BEFORE_NEXT_LAUNCH")
    return reports


def _run_storage_adapter_case(blender, output, timeout):
    from scripts import blender_storage_snapshot_adapter_smoke as fixture
    bundle = output / (STORAGE_ADAPTER_CASE + "-bundle")
    bundle.mkdir(mode=0o700)
    phases, reports, error = [], [], None
    started = time.monotonic()
    try:
        inputs = _storage_adapter_inputs(blender) if sys.platform != "win32" else None
        if inputs is None:
            raise ValueError("STORAGE_ADAPTER_WINDOWS_TESTING_DEFERRED")
        for phase in STORAGE_ADAPTER_PHASES:
            _storage_adapter_bind(phases, bundle, inputs)
            row = _run_process(blender, STORAGE_ADAPTER_CASE, output, min(timeout, 300), phase=phase,
                               bundle=bundle, phase_marker=fixture.MARKERS[phase])
            phases.append(row)
            if row["status"] != "passed":
                break
            reports = _storage_adapter_bind(phases, bundle, inputs)
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as cause:
        error = str(cause)[:256]
        if phases:
            phases[-1]["status"], phases[-1]["phase_binding_error"] = "failed", error
    complete = len(phases) == len(STORAGE_ADAPTER_PHASES) and len(reports) == len(phases) and all(row["status"] == "passed" for row in phases)
    return {"case": STORAGE_ADAPTER_CASE, "script": CASES[STORAGE_ADAPTER_CASE][0],
            "status": "passed" if complete else "failed", "phase_sequence": [row["phase"] for row in phases],
            "phases": phases, "fresh_process_verified": complete, "retained_files_independently_reparsed": complete,
            "phase_binding_error": error, "shared_bundle": str(bundle), "qualification_scope": fixture.PROFILE,
            "execution_mode": phases[0]["execution_mode"] if phases else "interactive_display",
            "blender_version": phases[-1].get("blender_version") if phases else None,
            "duration_seconds": time.monotonic() - started, "full_artist_target": "OPEN", "windows_testing_deferred": True}


def _storage_cleanup_inputs(blender):
    from scripts import blender_storage_snapshot_cleanup_smoke as fixture
    names = fixture.source_names(ROOT)
    required = {"scripts/blender_storage_snapshot_cleanup_smoke.py", "scripts/blender_storage_snapshot_adapter_smoke.py",
                "scripts/run_blender_checks.py", "scripts/blender_artist_sidebar_smoke.py"}
    required.update(str(path.relative_to(ROOT)) for path in (ROOT / "addon/blender_codex_bridge").rglob("*.py"))
    if (type(names) not in (tuple, list) or any(type(name) is not str or not name or Path(name).is_absolute()
            or ".." in Path(name).parts for name in names) or len(set(names)) != len(names) or set(names) != required):
        raise ValueError("STORAGE_CLEANUP_SOURCE_INVENTORY")
    binary = {"path": str(blender.resolve()), "sha256": _cloth_file(blender, 1024**3)[0]}
    if binary["sha256"] not in STORAGE_ADAPTER_BINARY_HASHES.values():
        raise ValueError("STORAGE_CLEANUP_BINARY_NOT_PINNED")
    return {"source_fingerprints": {name: _cloth_file(ROOT / name, 1024**2)[0] for name in names}, "binary": binary}


def _storage_dispatch_inputs(blender):
    from scripts import blender_storage_snapshot_dispatch_smoke as fixture
    names = fixture.source_names(ROOT)
    required = {"scripts/blender_storage_snapshot_dispatch_smoke.py", "scripts/blender_storage_snapshot_cleanup_smoke.py", "scripts/blender_storage_snapshot_adapter_smoke.py",
                "scripts/run_blender_checks.py", "scripts/blender_artist_sidebar_smoke.py"}
    required.update(str(path.relative_to(ROOT)) for path in (ROOT / "addon/blender_codex_bridge").rglob("*.py"))
    if (type(names) not in (tuple, list) or any(type(name) is not str or not name or Path(name).is_absolute()
            or ".." in Path(name).parts for name in names) or len(set(names)) != len(names) or set(names) != required):
        raise ValueError("STORAGE_DISPATCH_SOURCE_INVENTORY")
    binary = {"path": str(blender.resolve()), "sha256": _cloth_file(blender, 1024**3)[0]}
    if binary["sha256"] not in STORAGE_ADAPTER_BINARY_HASHES.values():
        raise ValueError("STORAGE_DISPATCH_BINARY_NOT_PINNED")
    return {"source_fingerprints": {name: _cloth_file(ROOT / name, 1024**2)[0] for name in names}, "binary": binary}


def _storage_dispatch_validate(payload, phase, bundle, process_instance, process_id, inputs):
    from scripts import blender_storage_snapshot_dispatch_smoke as fixture
    try:
        expected = {"schema": fixture.SCHEMA, "profile": fixture.PROFILE, "phase": phase, "completed": True,
                    "process_instance": process_instance, "process_id": process_id, **inputs}
        if (type(payload) is not dict or type(process_id) is not int or process_id <= 0
                or any(type(payload.get(key)) is not type(value) or payload.get(key) != value for key, value in expected.items())):
            raise ValueError("STORAGE_DISPATCH_MARKER_BINDING")
        version = payload.get("version")
        if (type(version) is not list or len(version) != 3 or any(type(part) is not int for part in version)
                or tuple(version) not in STORAGE_ADAPTER_BUILDS or payload.get("build_hash") != STORAGE_ADAPTER_BUILDS[tuple(version)]
                or inputs["binary"]["sha256"] != STORAGE_ADAPTER_BINARY_HASHES[tuple(version)]
                or payload.get("blender_version") not in {".".join(map(str, version)), ".".join(map(str, version)) + " LTS"}):
            raise ValueError("STORAGE_DISPATCH_OFFICIAL_BUILD_REQUIRED")
        path, record = bundle / (phase + ".json"), payload.get("full_receipt")
        if (type(record) is not dict or set(record) != {"path", "bytes", "sha256"} or record["path"] != str(path)
                or type(record["bytes"]) is not int or not 0 < record["bytes"] <= STORAGE_DISPATCH_MAX_REPORT):
            raise ValueError("STORAGE_DISPATCH_REPORT_RECEIPT")
        checksum, raw = _cloth_file(path, STORAGE_DISPATCH_MAX_REPORT, content=True)
        if checksum != record["sha256"] or len(raw) != record["bytes"]:
            raise ValueError("STORAGE_DISPATCH_REPORT_CHANGED")
        full = json.loads(raw, object_pairs_hook=_cloth_unique, parse_constant=_cloth_nonfinite)
        if (type(full) is not dict or any(type(full.get(key)) is not type(payload.get(key)) or full.get(key) != payload.get(key)
                for key in (*expected, "version", "build_hash", "blender_version"))
                or fixture.validate_full(full, phase=phase, process_instance=process_instance,
                    sources=inputs["source_fingerprints"], binary=inputs["binary"], process_id=process_id) is not True):
            raise ValueError("STORAGE_DISPATCH_FULL_REPORT_INVALID")
        for flag in ("runtime_retention_qualified", "full_authored_preservation_qualified", "durable_backup_qualified",
                     "cache_pairing_qualified", "native_calls_preemptible", "windows_qualified", "installed_package_qualified",
                     "native_memory_cap_claimed", "hidden_Main_passivity_claimed", "current_pixels_backup_qualified",
                     "shipping_caller_qualified"):
            if full.get(flag) is not False:
                raise ValueError("STORAGE_DISPATCH_BROAD_QUALIFICATION_FORBIDDEN")
        if (full.get("actual_dispatch_qualified") is not True or full.get("transport_qualified") is not True
                or full.get("source_unchanged") is not True
                or full.get("request_binding_kind") != "ACTUAL_QUEUED_EXECUTOR_LOOPBACK_REQUEST"):
            raise ValueError("STORAGE_DISPATCH_COMPLETION_REQUIRED")
        if fixture.validate_retained(full, bundle) is not True:
            raise ValueError("STORAGE_DISPATCH_RETAINED_ARTIFACTS_INVALID")
        if _storage_dispatch_inputs(Path(inputs["binary"]["path"])) != inputs:
            raise ValueError("STORAGE_DISPATCH_LIVE_INPUT_CHANGED")
        return {"passed": True, "path": str(path), "sha256": checksum, "native_copies_independently_reparsed": True}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, AssertionError) as error:
        return {"passed": False, "reason": str(error)[:256] or "STORAGE_DISPATCH_EVIDENCE_INVALID"}


def _storage_dispatch_bind(rows, bundle, inputs):
    reports = []
    for index, row in enumerate(rows):
        validation = _storage_dispatch_validate(row.get("evidence"), STORAGE_DISPATCH_PHASES[index], bundle,
            row["process_instance"], row.get("launched_process_id"), inputs)
        if not validation["passed"] or validation != row["retained_evidence_validation"]:
            raise ValueError("STORAGE_DISPATCH_PRIOR_RECEIPT_CHANGED")
        reports.append(row["evidence"])
    if len({row["process_instance"] for row in rows}) != len(rows) or len({row["launched_process_id"] for row in rows}) != len(rows):
        raise ValueError("STORAGE_DISPATCH_REUSED_PROCESS")
    if any(any(report[key] != reports[0][key] for key in ("version", "build_hash", "blender_version")) for report in reports):
        raise ValueError("STORAGE_DISPATCH_CROSS_PHASE_BUILD_CHANGED")
    if _storage_dispatch_inputs(Path(inputs["binary"]["path"])) != inputs:
        raise ValueError("STORAGE_DISPATCH_INPUT_CHANGED_BEFORE_NEXT_LAUNCH")
    return reports


def _run_storage_dispatch_case(blender, output, timeout):
    from scripts import blender_storage_snapshot_dispatch_smoke as fixture
    bundle = output / (STORAGE_DISPATCH_CASE + "-bundle")
    bundle.mkdir(mode=0o700)
    phases, reports, error = [], [], None
    started = time.monotonic()
    try:
        inputs = _storage_dispatch_inputs(blender) if sys.platform != "win32" else None
        if inputs is None:
            raise ValueError("STORAGE_DISPATCH_WINDOWS_TESTING_DEFERRED")
        for phase in STORAGE_DISPATCH_PHASES:
            _storage_dispatch_bind(phases, bundle, inputs)
            row = _run_process(blender, STORAGE_DISPATCH_CASE, output, min(timeout, 300), phase=phase,
                               bundle=bundle, phase_marker=fixture.MARKERS[phase])
            phases.append(row)
            if row["status"] != "passed":
                break
            reports = _storage_dispatch_bind(phases, bundle, inputs)
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as cause:
        error = str(cause)[:256]
        if phases:
            phases[-1]["status"], phases[-1]["phase_binding_error"] = "failed", error
    complete = len(phases) == len(STORAGE_DISPATCH_PHASES) and len(reports) == len(phases) and all(row["status"] == "passed" for row in phases)
    return {"case": STORAGE_DISPATCH_CASE, "script": CASES[STORAGE_DISPATCH_CASE][0],
            "status": "passed" if complete else "failed", "phase_sequence": [row["phase"] for row in phases],
            "phases": phases, "fresh_process_verified": complete, "retained_copies_independently_reparsed": complete,
            "phase_binding_error": error, "shared_bundle": str(bundle), "qualification_scope": fixture.PROFILE,
            "execution_mode": phases[0]["execution_mode"] if phases else "interactive_display",
            "blender_version": phases[-1].get("blender_version") if phases else None,
            "duration_seconds": time.monotonic() - started, "full_artist_target": "OPEN", "windows_testing_deferred": True}


def _storage_cleanup_retained(full, bundle):
    """Reparse create-only native evidence copies after originals are deleted."""
    import importlib.util
    module_name = "_bcb_storage_cleanup_evidence_reader"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "addon/blender_codex_bridge/blend_storage_sdna.py")
    if spec is None or spec.loader is None:
        raise ValueError("STORAGE_CLEANUP_READER_REQUIRED")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    names = module.CYCLES_NAMES if full["version"][0] == 4 else module.CYCLES_502_NAMES
    for row in full["cases"]:
        prefix = full["phase"] + "-" + row["name"]
        root = bundle / (prefix + "-owned")
        sentinel = bundle / (prefix + "-sentinel.bin")
        sentinel_record = row["sentinel"]
        if (type(sentinel_record) is not dict or set(sentinel_record) != {"path", "bytes", "sha256"}
                or sentinel_record["path"] != str(sentinel) or type(sentinel_record["bytes"]) is not int):
            raise ValueError("STORAGE_CLEANUP_SENTINEL_BINDING")
        sentinel_sha, _ = _cloth_file(sentinel, 65536)
        if (sentinel_record["sha256"] != sentinel_sha or sentinel_record["bytes"] != sentinel.stat().st_size
                or sentinel.lstat().st_nlink != 1):
            raise ValueError("STORAGE_CLEANUP_SENTINEL_CHANGED")
        before, after = row["journal_before"]["snapshots"], row["journal_after"]["snapshots"]
        copies, targets = row["evidence_copies"], row["raw_targets"]
        actor = row["actor"]
        request_ids = actor.get("request_ids") if type(actor) is dict else None
        if (type(request_ids) is not list or not 1 <= len(request_ids) <= 128
                or any(type(value) is not str or len(value) != 32 or any(character not in "0123456789abcdef" for character in value)
                       for value in request_ids) or len(set(request_ids)) != len(request_ids)
                or type(actor.get("contexts_created")) is not int or actor["contexts_created"] != len(request_ids)
                or (actor.get("retry_with_fresh_context") is True and len(request_ids) < 2)):
            raise ValueError("STORAGE_CLEANUP_FRESH_CONTEXT_BINDING")
        if (row["owned_root"] != str(root) or type(before) is not list or not 1 <= len(before) <= 16
                or type(after) is not list or len(after) != len(before) or type(copies) is not list
                or len(copies) != len(before) or type(targets) is not list or len(targets) != 2
                or any(type(target) is not dict or set(target) != {"scene_name", "view_layer_name"}
                    or any(type(value) is not str or not value or len(value) > 128 for value in target.values()) for target in targets)
                or targets[0] == targets[1]):
            raise ValueError("STORAGE_CLEANUP_ARTIFACT_INVENTORY")
        copy_root = bundle / (prefix + "-evidence")
        directory_stat = copy_root.lstat()
        if (not stat.S_ISDIR(directory_stat.st_mode) or stat.S_IMODE(directory_stat.st_mode) != 0o700
                or directory_stat.st_uid != os.geteuid()
                or {path.name for path in copy_root.iterdir()} != {str(index) + ".blend" for index in range(len(copies))}):
            raise ValueError("STORAGE_CLEANUP_COPY_DIRECTORY")
        for index, (cell, final, record) in enumerate(zip(before, after, copies, strict=True)):
            unchanged = ("root", "directory", "filepath", "root_identity", "directory_identity", "file_identity", "file_sha256", "file_bytes")
            if (type(cell) is not dict or type(final) is not dict or any(cell.get(key) != final.get(key) for key in unchanged)
                    or type(record) is not dict or set(record) != {"owner_index", "original_path", "original_identity", "original_binding", "original_sha256", "copy", "retained_parser"}
                    or type(record["owner_index"]) is not int or record["owner_index"] != index):
                raise ValueError("STORAGE_CLEANUP_ORIGINAL_RECEIPT")
            child = Path(cell["directory"])
            leaf = child.name
            if (cell["root"] != str(root) or child.parent != root or len(leaf) != 44 or not leaf.startswith("bcb-storage-")
                    or any(character not in "0123456789abcdef" for character in leaf[12:])
                    or cell["filepath"] != str(child / "snapshot.blend") or record["original_path"] != cell["filepath"]):
                raise ValueError("STORAGE_CLEANUP_ORIGINAL_PATH")
            for key in ("root_identity", "directory_identity"):
                if type(cell[key]) is not list or len(cell[key]) != 2 or any(type(value) is not int or value < 0 for value in cell[key]):
                    raise ValueError("STORAGE_CLEANUP_ORIGINAL_DIRECTORY_IDENTITY")
            identity, binding = record["original_identity"], record["original_binding"]
            unknown = full["phase"] == "stop_retry" and row["name"] == "unknown_after_writer_stop"
            if (type(identity) is not list or len(identity) != 4 or any(type(value) is not int or value < 0 for value in identity)
                    or not 0 < identity[2] <= 1024**3 or type(cell["file_identity"]) is not list
                    or any(type(value) is not int or value < 0 for value in cell["file_identity"])
                    or (cell["file_identity"] != identity and not (unknown and cell["file_identity"] == []))):
                raise ValueError("STORAGE_CLEANUP_ORIGINAL_FILE_IDENTITY")
            if unknown:
                if binding is not None:
                    raise ValueError("STORAGE_CLEANUP_UNKNOWN_OWNER_ADOPTED")
            elif (type(binding) is not list or len(binding) != 8 or any(type(value) is not int or value < 0 for value in binding)
                    or binding[:2] != identity[:2] or binding[2] != os.geteuid() or binding[4] != 1
                    or binding[5:7] != identity[2:]):
                raise ValueError("STORAGE_CLEANUP_ORIGINAL_FILE_BINDING")
            copy = record["copy"]
            path = copy_root / (str(index) + ".blend")
            if type(copy) is not dict or set(copy) != {"path", "bytes", "sha256"} or copy["path"] != str(path):
                raise ValueError("STORAGE_CLEANUP_COPY_BINDING")
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or type(copy["bytes"]) is not int or copy["bytes"] != info.st_size
                    or copy["bytes"] != identity[2]):
                raise ValueError("STORAGE_CLEANUP_COPY_METADATA")
            checksum, _ = _cloth_file(path, 1024**3)
            if (copy["sha256"] != checksum or record["original_sha256"] != checksum
                    or (cell["file_sha256"] != checksum and not (cell["file_sha256"] is None
                        and (unknown or row["name"] == "malformed_cleanup")))
                    or (cell["file_bytes"] is not None and type(cell["file_bytes"]) is not int)
                    or cell["file_bytes"] not in (None, identity[2])):
                raise ValueError("STORAGE_CLEANUP_COPY_CHANGED")
            proofs = record["retained_parser"]
            if type(proofs) is not list or len(proofs) != 2:
                raise ValueError("STORAGE_CLEANUP_COPY_PROJECTIONS")
            for target_index, (target, proof) in enumerate(zip(targets, proofs, strict=True)):
                if type(proof) is not dict or proof.get("target") != target:
                    raise ValueError("STORAGE_CLEANUP_COPY_TARGET")
                try:
                    actual = module.inspect_view_layer_storage(str(path), target["scene_name"], target["view_layer_name"], allowed_names=names)
                except module.StorageSnapshotError as error:
                    if (row["name"] != "malformed_cleanup" or target_index != 1 or error.reason != "RAW_PROPERTY_TYPE_UNQUALIFIED"
                            or proof != {"target": target, "error": {"type": "StorageSnapshotError", "reason": error.reason}}):
                        raise ValueError("STORAGE_CLEANUP_COPY_REFUSAL") from error
                else:
                    if proof != {"target": target, "result": actual}:
                        raise ValueError("STORAGE_CLEANUP_COPY_PROJECTION")
            if _cloth_file(path, 1024**3)[0] != checksum:
                raise ValueError("STORAGE_CLEANUP_COPY_CHANGED_DURING_PARSE")


def _storage_cleanup_validate(payload, phase, bundle, process_instance, process_id, inputs):
    from scripts import blender_storage_snapshot_cleanup_smoke as fixture
    try:
        expected = {"schema": fixture.SCHEMA, "profile": fixture.PROFILE, "phase": phase, "completed": True,
                    "process_instance": process_instance, "process_id": process_id, **inputs}
        if (type(payload) is not dict or type(process_id) is not int or process_id <= 0
                or any(type(payload.get(key)) is not type(value) or payload.get(key) != value for key, value in expected.items())):
            raise ValueError("STORAGE_CLEANUP_MARKER_BINDING")
        version = payload.get("version")
        if (type(version) is not list or len(version) != 3 or any(type(part) is not int for part in version)
                or tuple(version) not in STORAGE_ADAPTER_BUILDS or payload.get("build_hash") != STORAGE_ADAPTER_BUILDS[tuple(version)]
                or inputs["binary"]["sha256"] != STORAGE_ADAPTER_BINARY_HASHES[tuple(version)]
                or payload.get("blender_version") not in {".".join(map(str, version)), ".".join(map(str, version)) + " LTS"}):
            raise ValueError("STORAGE_CLEANUP_OFFICIAL_BUILD_REQUIRED")
        path, record = bundle / (phase + ".json"), payload.get("full_receipt")
        if (type(record) is not dict or set(record) != {"path", "bytes", "sha256"} or record["path"] != str(path)
                or type(record["bytes"]) is not int or not 0 < record["bytes"] <= STORAGE_CLEANUP_MAX_REPORT):
            raise ValueError("STORAGE_CLEANUP_REPORT_RECEIPT")
        checksum, raw = _cloth_file(path, STORAGE_CLEANUP_MAX_REPORT, content=True)
        if checksum != record["sha256"] or len(raw) != record["bytes"]:
            raise ValueError("STORAGE_CLEANUP_REPORT_CHANGED")
        full = json.loads(raw, object_pairs_hook=_cloth_unique, parse_constant=_cloth_nonfinite)
        if (type(full) is not dict or any(type(full.get(key)) is not type(payload.get(key)) or full.get(key) != payload.get(key)
                for key in (*expected, "version", "build_hash", "blender_version"))
                or fixture.validate_full(full, phase=phase, process_instance=process_instance,
                    sources=inputs["source_fingerprints"], binary=inputs["binary"], process_id=process_id) is not True):
            raise ValueError("STORAGE_CLEANUP_FULL_REPORT_INVALID")
        for flag in ("runtime_retention_qualified", "full_authored_preservation_qualified", "durable_backup_qualified",
                     "cache_pairing_qualified", "native_calls_preemptible", "windows_qualified", "installed_package_qualified",
                     "native_memory_cap_claimed", "hidden_Main_passivity_claimed", "current_pixels_backup_qualified",
                     "canonical_dispatch_qualified", "transport_qualified"):
            if full.get(flag) is not False:
                raise ValueError("STORAGE_CLEANUP_BROAD_QUALIFICATION_FORBIDDEN")
        if (full.get("cleanup_qualified") is not True or full.get("source_unchanged") is not True
                or full.get("request_binding_kind") != "SOURCE_QUALIFIED_REPLICA_FRESH_QUEUED_REQUEST"):
            raise ValueError("STORAGE_CLEANUP_COMPLETION_REQUIRED")
        _storage_cleanup_retained(full, bundle)
        if _storage_cleanup_inputs(Path(inputs["binary"]["path"])) != inputs:
            raise ValueError("STORAGE_CLEANUP_LIVE_INPUT_CHANGED")
        return {"passed": True, "path": str(path), "sha256": checksum, "native_copies_independently_reparsed": True}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, AssertionError) as error:
        return {"passed": False, "reason": str(error)[:256] or "STORAGE_CLEANUP_EVIDENCE_INVALID"}


def _storage_cleanup_bind(rows, bundle, inputs):
    reports = []
    for index, row in enumerate(rows):
        validation = _storage_cleanup_validate(row.get("evidence"), STORAGE_CLEANUP_PHASES[index], bundle,
            row["process_instance"], row.get("launched_process_id"), inputs)
        if not validation["passed"] or validation != row["retained_evidence_validation"]:
            raise ValueError("STORAGE_CLEANUP_PRIOR_RECEIPT_CHANGED")
        reports.append(row["evidence"])
    if len({row["process_instance"] for row in rows}) != len(rows) or len({row["launched_process_id"] for row in rows}) != len(rows):
        raise ValueError("STORAGE_CLEANUP_REUSED_PROCESS")
    if any(any(report[key] != reports[0][key] for key in ("version", "build_hash", "blender_version")) for report in reports):
        raise ValueError("STORAGE_CLEANUP_CROSS_PHASE_BUILD_CHANGED")
    if _storage_cleanup_inputs(Path(inputs["binary"]["path"])) != inputs:
        raise ValueError("STORAGE_CLEANUP_INPUT_CHANGED_BEFORE_NEXT_LAUNCH")
    return reports


def _run_storage_cleanup_case(blender, output, timeout):
    from scripts import blender_storage_snapshot_cleanup_smoke as fixture
    bundle = output / (STORAGE_CLEANUP_CASE + "-bundle")
    bundle.mkdir(mode=0o700)
    phases, reports, error = [], [], None
    started = time.monotonic()
    try:
        inputs = _storage_cleanup_inputs(blender) if sys.platform != "win32" else None
        if inputs is None:
            raise ValueError("STORAGE_CLEANUP_WINDOWS_TESTING_DEFERRED")
        for phase in STORAGE_CLEANUP_PHASES:
            _storage_cleanup_bind(phases, bundle, inputs)
            row = _run_process(blender, STORAGE_CLEANUP_CASE, output, min(timeout, 300), phase=phase,
                               bundle=bundle, phase_marker=fixture.MARKERS[phase])
            phases.append(row)
            if row["status"] != "passed":
                break
            reports = _storage_cleanup_bind(phases, bundle, inputs)
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as cause:
        error = str(cause)[:256]
        if phases:
            phases[-1]["status"], phases[-1]["phase_binding_error"] = "failed", error
    complete = len(phases) == len(STORAGE_CLEANUP_PHASES) and len(reports) == len(phases) and all(row["status"] == "passed" for row in phases)
    return {"case": STORAGE_CLEANUP_CASE, "script": CASES[STORAGE_CLEANUP_CASE][0],
            "status": "passed" if complete else "failed", "phase_sequence": [row["phase"] for row in phases],
            "phases": phases, "fresh_process_verified": complete, "retained_copies_independently_reparsed": complete,
            "phase_binding_error": error, "shared_bundle": str(bundle), "qualification_scope": fixture.PROFILE,
            "execution_mode": phases[0]["execution_mode"] if phases else "interactive_display",
            "blender_version": phases[-1].get("blender_version") if phases else None,
            "duration_seconds": time.monotonic() - started, "full_artist_target": "OPEN", "windows_testing_deferred": True}


def _public_cloth_payload(output, marker):
    rows = [line[len(marker):] for line in output.splitlines() if line.startswith(marker)]
    if len(rows) != 1:
        return None
    try:
        value = json.loads(rows[0], object_pairs_hook=_cloth_unique, parse_constant=_cloth_nonfinite)
        return value if type(value) is dict else None
    except (ValueError, TypeError, RecursionError):
        return None


def _system_storage_inputs(blender: Path) -> dict:
    from scripts.blender_system_storage_snapshot_smoke import SOURCES
    return {"source_sha256": {name: _glb_stage_file(ROOT / name, 1024**2)[0] for name in SOURCES},
            "binary": {"path": str(blender.resolve()), "sha256": _glb_stage_file(blender, 1024**3)[0]}}


def _system_storage_validate(payload, temporary, process_instance, inputs, process_id):
    from scripts.blender_system_storage_snapshot_smoke import (
        MAX_REPORT,
        PROFILE,
        REPORT,
        SCHEMA,
        validate_full,
    )
    try:
        expected = {"schema": SCHEMA, "profile": PROFILE, "completed": True, "process_instance": process_instance,
                    "process_id": process_id, "source_sha256": inputs["source_sha256"], "binary": inputs["binary"]}
        if (type(payload) is not dict or type(process_id) is not int or process_id <= 0
                or any(type(payload.get(key)) is not type(value) or payload.get(key) != value for key, value in expected.items())):
            raise ValueError("SYSTEM_STORAGE_MARKER_BINDING")
        report = temporary / REPORT
        binding = payload["full_receipt"]
        if (type(binding) is not dict or set(binding) != {"path", "bytes", "sha256"}
                or binding["path"] != str(report) or type(binding["bytes"]) is not int
                or not 0 < binding["bytes"] <= MAX_REPORT):
            raise ValueError("SYSTEM_STORAGE_REPORT_BINDING")
        report_checksum, raw = _glb_stage_file(report, MAX_REPORT, retain=True)
        if report_checksum != binding["sha256"] or len(raw) != binding["bytes"]:
            raise ValueError("SYSTEM_STORAGE_REPORT_CHANGED")
        full = json.loads(raw, object_pairs_hook=_glb_stage_unique, parse_constant=_glb_stage_reject_constant)
        if (any(type(full.get(key)) is not type(payload.get(key)) or full.get(key) != payload.get(key)
                for key in (*expected, "blender_version", "version", "build_hash"))
                or not validate_full(full, process_instance=process_instance, sources=inputs["source_sha256"], binary=inputs["binary"])
                or _system_storage_inputs(Path(inputs["binary"]["path"])) != inputs):
            raise ValueError("SYSTEM_STORAGE_EVIDENCE_INCOMPLETE")
        # Independently replay the detached parser against retained native bytes;
        # a self-reported storage dictionary alone is not native evidence.
        import importlib.util
        module_name = "_bcb_system_storage_evidence_reader"
        spec = importlib.util.spec_from_file_location(module_name, ROOT / "addon/blender_codex_bridge/blend_storage_sdna.py")
        module = importlib.util.module_from_spec(spec)
        previous = sys.modules.get(module_name)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            if previous is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous
        target = full["target"]
        if (type(target) is not dict or set(target) != {"scene_name", "view_layer_name"}
                or any(type(value) is not str or not value for value in target.values())):
            raise ValueError("SYSTEM_STORAGE_TARGET_REQUIRED")
        for row in full["cases"]:
            record = row["file_receipt"]
            if row["case"] in {"absent", "valid", "malformed_scalar", "stop_after"}:
                native_path = temporary / (row["case"] + ".blend")
                checksum, _ = _glb_stage_file(native_path, 1024**3)
                if record != {"path": str(native_path), "bytes": native_path.stat().st_size, "sha256": checksum}:
                    raise ValueError("SYSTEM_STORAGE_NATIVE_FILE_CHANGED")
                if row["case"] in {"absent", "valid"}:
                    independent = module.inspect_view_layer_storage(str(native_path), target["scene_name"], target["view_layer_name"],
                                                                  allowed_names=tuple(full["declared_names"]))
                    if independent != row["storage"]:
                        raise ValueError("SYSTEM_STORAGE_INDEPENDENT_PROJECTION_CHANGED")
                elif row["case"] == "malformed_scalar":
                    try:
                        module.inspect_view_layer_storage(str(native_path), target["scene_name"], target["view_layer_name"],
                                                          allowed_names=tuple(full["declared_names"]))
                    except module.StorageSnapshotError as error:
                        if error.reason != row["error"]["reason"]:
                            raise ValueError("SYSTEM_STORAGE_INDEPENDENT_REFUSAL_CHANGED") from error
                    else:
                        raise ValueError("SYSTEM_STORAGE_MALFORMED_NATIVE_FILE_ACCEPTED")
            elif record is not None:
                raise ValueError("SYSTEM_STORAGE_UNEXPECTED_FILE")
            elif row["case"] in {"permission_denial", "stop_before"} and list(temporary.glob(row["case"] + ".blend*")):
                raise ValueError("SYSTEM_STORAGE_UNAUTHORIZED_FILE")
        return {"passed": True, "path": str(report), "sha256": report_checksum,
                "durable_backup_qualified": False, "canonical_runtime_qualified": False}
    except (OSError, ValueError, TypeError, KeyError, RecursionError, AttributeError):
        return {"passed": False, "reason": "SYSTEM_STORAGE_EVIDENCE_INVALID"}



def _storage_root_approval_inputs(blender):
    from scripts import blender_storage_root_approval_smoke as fixture
    names = fixture.source_names(ROOT)
    required = {"scripts/blender_storage_root_approval_smoke.py", "scripts/blender_storage_snapshot_adapter_smoke.py",
                "scripts/run_blender_checks.py", "scripts/blender_artist_sidebar_smoke.py"}
    required.update(str(path.relative_to(ROOT)) for path in (ROOT / "addon").rglob("*.py"))
    if (type(names) not in (tuple, list) or any(type(name) is not str or not name or Path(name).is_absolute()
            or ".." in Path(name).parts for name in names) or len(set(names)) != len(names) or set(names) != required):
        raise ValueError("STORAGE_ROOT_APPROVAL_SOURCE_INVENTORY")
    binary = {"path": str(blender.resolve()), "sha256": _cloth_file(blender, 1024**3)[0]}
    if binary["sha256"] not in STORAGE_ADAPTER_BINARY_HASHES.values():
        raise ValueError("STORAGE_ROOT_APPROVAL_BINARY_NOT_PINNED")
    return {"source_fingerprints": {name: _cloth_file(ROOT / name, 1024**2)[0] for name in names},
            "binary": binary, "private_display_binding": _domain_display()}


def _storage_root_approval_validate(payload, phase, bundle, process_instance, process_id, inputs):
    from scripts import blender_storage_root_approval_smoke as fixture
    try:
        expected = {"schema": fixture.SCHEMA, "profile": fixture.PROFILE, "phase": fixture.PHASE, "completed": True,
                    "process_instance": process_instance, "process_id": process_id, **inputs}
        if (phase != fixture.PHASE or type(payload) is not dict or type(process_id) is not int or process_id <= 0
                or set(payload) != {*expected, "version", "build_hash", "blender_version", "full_receipt"}
                or any(type(payload.get(key)) is not type(value) or payload.get(key) != value for key, value in expected.items())):
            raise ValueError("STORAGE_ROOT_APPROVAL_MARKER_BINDING")
        version = payload["version"]
        if (type(version) is not list or len(version) != 3 or any(type(v) is not int for v in version)
                or tuple(version) not in STORAGE_ADAPTER_BUILDS or payload["build_hash"] != STORAGE_ADAPTER_BUILDS[tuple(version)]
                or inputs["binary"]["sha256"] != STORAGE_ADAPTER_BINARY_HASHES[tuple(version)]):
            raise ValueError("STORAGE_ROOT_APPROVAL_BUILD")
        path, binding = bundle / "registered_route.json", payload["full_receipt"]
        if (type(binding) is not dict or set(binding) != {"path", "bytes", "sha256"} or binding["path"] != str(path)
                or type(binding["bytes"]) is not int or not 0 < binding["bytes"] <= fixture.MAX_REPORT):
            raise ValueError("STORAGE_ROOT_APPROVAL_REPORT_BINDING")
        checksum, raw = _cloth_file(path, fixture.MAX_REPORT, content=True)
        if len(raw) != binding["bytes"] or checksum != binding["sha256"]:
            raise ValueError("STORAGE_ROOT_APPROVAL_REPORT_CHANGED")
        full = json.loads(raw, object_pairs_hook=_cloth_unique, parse_constant=_cloth_nonfinite)
        if (type(full) is not dict or any(type(full.get(key)) is not type(payload[key]) or full.get(key) != payload[key]
                for key in (*expected, "version", "build_hash", "blender_version"))
                or fixture.validate(full, sources=inputs["source_fingerprints"], binary=inputs["binary"],
                    process_instance=process_instance, process_id=process_id) is not True):
            raise ValueError("STORAGE_ROOT_APPROVAL_FULL_REPORT_INVALID")
        if _storage_root_approval_inputs(Path(inputs["binary"]["path"])) != inputs:
            raise ValueError("STORAGE_ROOT_APPROVAL_INPUT_CHANGED")
        return {"passed": True, "path": str(path), "sha256": checksum, "actual_registered_preference_route": True,
                "shipping_caller_qualified": False, "snapshot_writer_qualified": False, "post_C_root_check_qualified": False}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, AssertionError):
        return {"passed": False, "reason": "STORAGE_ROOT_APPROVAL_EVIDENCE_INVALID"}


def _run_storage_root_approval_case(blender, output, timeout):
    from scripts import blender_storage_root_approval_smoke as fixture
    bundle = output / (STORAGE_ROOT_APPROVAL_CASE + "-bundle")
    bundle.mkdir(mode=0o700)
    return _run_process(blender, STORAGE_ROOT_APPROVAL_CASE, output, min(timeout, 300), phase=fixture.PHASE,
                        bundle=bundle, phase_marker=fixture.MARKER)


def _storage_runtime_context_inputs(blender):
    from scripts import blender_storage_snapshot_adapter_smoke as fixture
    names = fixture.runtime_source_names(ROOT)
    required = {"scripts/blender_storage_snapshot_adapter_smoke.py", "scripts/blender_storage_snapshot_cleanup_smoke.py",
                "scripts/run_blender_checks.py", "scripts/blender_artist_sidebar_smoke.py"}
    required.update(str(path.relative_to(ROOT)) for path in (ROOT / "addon/blender_codex_bridge").rglob("*.py"))
    if (type(names) not in (tuple, list) or any(type(name) is not str or not name or Path(name).is_absolute()
            or ".." in Path(name).parts for name in names) or len(set(names)) != len(names) or set(names) != required):
        raise ValueError("STORAGE_RUNTIME_CONTEXT_SOURCE_INVENTORY")
    binary = {"path": str(blender.resolve()), "sha256": _cloth_file(blender, 1024**3)[0]}
    if binary["sha256"] not in STORAGE_ADAPTER_BINARY_HASHES.values():
        raise ValueError("STORAGE_RUNTIME_CONTEXT_BINARY_NOT_PINNED")
    return {"source_fingerprints": {name: _cloth_file(ROOT / name, 1024**2)[0] for name in names}, "binary": binary, "private_display_binding": _domain_display()}


def _storage_runtime_context_validate(payload, phase, bundle, process_instance, process_id, inputs):
    from scripts import blender_storage_snapshot_adapter_smoke as fixture
    try:
        if phase != "runtime_context":
            raise ValueError("STORAGE_RUNTIME_CONTEXT_PHASE")
        expected = {"schema": fixture.RUNTIME_SCHEMA, "profile": fixture.RUNTIME_PROFILE, "phase": phase, "completed": True,
                    "process_instance": process_instance, "process_id": process_id, **inputs}
        if (type(payload) is not dict or type(process_id) is not int or process_id <= 0
                or set(payload) != {*expected, "version", "build_hash", "blender_version", "full_receipt"}
                or any(type(payload.get(key)) is not type(value) or payload.get(key) != value for key, value in expected.items())):
            raise ValueError("STORAGE_RUNTIME_CONTEXT_MARKER_BINDING")
        version = payload["version"]
        if (type(version) is not list or len(version) != 3 or any(type(x) is not int for x in version)
                or tuple(version) not in STORAGE_ADAPTER_BUILDS or payload["build_hash"] != STORAGE_ADAPTER_BUILDS[tuple(version)]
                or inputs["binary"]["sha256"] != STORAGE_ADAPTER_BINARY_HASHES[tuple(version)]
                or payload["blender_version"] not in {".".join(map(str, version)), ".".join(map(str, version)) + " LTS"}):
            raise ValueError("STORAGE_RUNTIME_CONTEXT_OFFICIAL_BUILD")
        path, binding = bundle / "runtime_context.json", payload["full_receipt"]
        if (type(binding) is not dict or set(binding) != {"path", "bytes", "sha256"} or binding["path"] != str(path)
                or type(binding["bytes"]) is not int or not 0 < binding["bytes"] <= STORAGE_ADAPTER_MAX_REPORT):
            raise ValueError("STORAGE_RUNTIME_CONTEXT_REPORT_BINDING")
        checksum, raw = _cloth_file(path, STORAGE_ADAPTER_MAX_REPORT, content=True)
        if len(raw) != binding["bytes"] or checksum != binding["sha256"]:
            raise ValueError("STORAGE_RUNTIME_CONTEXT_REPORT_CHANGED")
        full = json.loads(raw, object_pairs_hook=_cloth_unique, parse_constant=_cloth_nonfinite)
        if (type(full) is not dict or any(type(full.get(k)) is not type(payload[k]) or full.get(k) != payload[k]
                for k in (*expected, "version", "build_hash", "blender_version"))
                or fixture.validate_runtime_context(full, process_instance=process_instance, process_id=process_id,
                    sources=inputs["source_fingerprints"], binary=inputs["binary"]) is not True):
            raise ValueError("STORAGE_RUNTIME_CONTEXT_FULL_REPORT_INVALID")
        if fixture.validate_runtime_retained(full, bundle) is not True:
            raise ValueError("STORAGE_RUNTIME_CONTEXT_RETAINED_ARTIFACTS_INVALID")
        if _storage_runtime_context_inputs(Path(inputs["binary"]["path"])) != inputs:
            raise ValueError("STORAGE_RUNTIME_CONTEXT_INPUT_CHANGED")
        return {"passed": True, "path": str(path), "sha256": checksum, "cold_SDNa_target_parses": 2,
                "genuine_Runtime_jobs_context": True, "canonical_job_resumption_qualified": False,
                "shipping_caller_qualified": False}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, AssertionError):
        return {"passed": False, "reason": "STORAGE_RUNTIME_CONTEXT_EVIDENCE_INVALID"}


def _run_storage_runtime_context_case(blender, output, timeout):
    from scripts import blender_storage_snapshot_adapter_smoke as fixture
    bundle = output / (STORAGE_RUNTIME_CONTEXT_CASE + "-bundle")
    bundle.mkdir(mode=0o700)
    return _run_process(blender, STORAGE_RUNTIME_CONTEXT_CASE, output, min(timeout, 300), phase="runtime_context",
                        bundle=bundle, phase_marker=fixture.RUNTIME_MARKER)


def _glb_stage_file(path: Path, maximum: int, *, retain: bool = False) -> tuple[str, bytes]:
    """Read a bounded ordinary file with no-follow and descriptor/path witnesses."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
        raise ValueError("GLB_STAGE_FILE_SHAPE")

    def identity(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    digest, count, chunks = hashlib.sha256(), 0, []
    try:
        if identity(os.fstat(descriptor)) != identity(before):
            raise ValueError("GLB_STAGE_FILE_CHANGED")
        while True:
            raw = os.read(descriptor, min(65536, maximum + 1 - count))
            if not raw:
                break
            count += len(raw)
            if count > maximum:
                raise ValueError("GLB_STAGE_FILE_BUDGET")
            digest.update(raw)
            if retain:
                chunks.append(raw)
        if (count != before.st_size or identity(os.fstat(descriptor)) != identity(before)
                or identity(path.lstat()) != identity(before)):
            raise ValueError("GLB_STAGE_FILE_CHANGED")
    finally:
        os.close(descriptor)
    return digest.hexdigest(), b"".join(chunks)


def _glb_stage_inputs(blender: Path, *, runtime: bool = False) -> dict:
    sources = GLB_STAGE_SOURCES
    if runtime:
        from scripts.blender_glb_stage_runtime_smoke import SOURCES
        sources = SOURCES
    return {"source_sha256": {name: _glb_stage_file(ROOT / name, 512 * 1024)[0]
                              for name in sources},
            "binary": {"path": str(blender.resolve()),
                       "sha256": _glb_stage_file(blender, 1024**3)[0]}}


def _glb_stage_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("GLB_STAGE_DUPLICATE_EVIDENCE_KEY")
        result[key] = value
    return result


def _glb_stage_reject_constant(_value):
    raise ValueError("GLB_STAGE_NONFINITE_EVIDENCE")


def _glb_stage_validate(payload: dict | None, temporary: Path, process_instance: str,
                        blender: Path, inputs: dict | None, *, structure: bool = False,
                        process_id: int | None = None) -> dict:
    """Bind one private constructor receipt to this launch and retained bytes."""
    filename = "glb-stage-structure-evidence.json" if structure else "glb-stage-evidence.json"
    result = {"passed": False, "path": str(temporary / filename)}
    try:
        if type(payload) is not dict or inputs is None:
            raise ValueError("GLB_STAGE_MARKER_MISSING")
        version = payload.get("version")
        if (type(version) is not list or len(version) != 3
                or any(type(value) is not int for value in version)
                or tuple(version) not in GLB_STAGE_BUILDS
                or payload.get("build_hash") != GLB_STAGE_BUILDS[tuple(version)]):
            raise ValueError("GLB_STAGE_BUILD_MISMATCH")
        version_text = ".".join(map(str, version))
        allowed_text = (version_text, version_text + " LTS")
        if (payload.get("schema") != ("glb_stage_structure_v1" if structure else "glb_stage_constructor_v1")
                or payload.get("profile") != ("GLB_PRIVATE_STRUCTURE_V1" if structure else "GLB_PRIVATE_STAGE_V1")
                or payload.get("completed") is not True
                or payload.get("blender_version") not in allowed_text
                or payload.get("process_instance") != process_instance
                or type(payload.get("process_id")) is not int or payload["process_id"] <= 0):
            raise ValueError("GLB_STAGE_LAUNCH_IDENTITY_MISMATCH")
        if structure and (type(process_id) is not int or process_id <= 0 or payload["process_id"] != process_id):
            raise ValueError("GLB_STRUCTURE_PROCESS_PID_MISMATCH")
        if (payload.get("source_sha256") != inputs["source_sha256"]
                or payload.get("binary") != inputs["binary"]):
            raise ValueError("GLB_STAGE_SOURCE_OR_BINARY_MISMATCH")
        if _glb_stage_inputs(blender) != inputs:
            raise ValueError("GLB_STAGE_INPUT_CHANGED_DURING_RUN")
        evidence_sha, raw = _glb_stage_file(temporary / filename,
                                             GLB_STAGE_MAX_EVIDENCE, retain=True)
        if payload.get("evidence_sha256") != evidence_sha:
            raise ValueError("GLB_STAGE_EVIDENCE_DIGEST_MISMATCH")
        proof = json.loads(raw, object_pairs_hook=_glb_stage_unique,
                           parse_constant=_glb_stage_reject_constant)
        identity_fields = ("schema", "profile", "completed", "blender_version", "version", "build_hash",
                           "process_instance", "process_id", "source_sha256", "binary")
        if (type(proof) is not dict
                or any(type(proof.get(key)) is not type(payload[key]) or proof.get(key) != payload[key]
                       for key in identity_fields)
                or any(type(value) is not int for value in proof["version"])
                or proof["completed"] is not True or type(proof["process_id"]) is not int):
            raise ValueError("GLB_STAGE_RETAINED_IDENTITY_MISMATCH")
        cases = proof.get("cases")
        required_cases = {"success": "CONSTRUCTED", "cancel": "STOPPED", "owned_change": "STOPPED",
                          "invalid_context": "REFUSED_BEFORE_ALLOCATION"}
        if structure:
            required_cases = {"success": "CONSTRUCTED", "cancel_after_uv": "STOPPED",
                              "encoded_short_drift": "STOPPED", "invalid_context": "REFUSED_BEFORE_ALLOCATION"}
            from scripts.blender_glb_stage_smoke import validate_structure_transcript
            try:
                validate_structure_transcript(proof)
            except (AssertionError, ValueError, TypeError, KeyError, IndexError, OverflowError) as cause:
                raise ValueError("GLB_STRUCTURE_TRANSCRIPT_INVALID") from cause
        if (type(cases) is not list or len(cases) != 4
                or any(type(row) is not dict or type(row.get("name")) is not str
                       or type(row.get("status")) is not str for row in cases)
                or {row["name"]: row["status"] for row in cases} != required_cases):
            raise ValueError("GLB_STAGE_CASE_EVIDENCE_MISMATCH")
        observations = proof.get("observations")
        floors = {"immediate": 0., "timer_0_1": .1, "timer_0_5": .5}
        if structure:
            floors["timer_0_3"] = .3
        if (type(observations) is not list or len(observations) != len(floors)
                or any(type(row) is not dict or type(row.get("phase")) is not str for row in observations)
                or {row["phase"] for row in observations} != set(floors)):
            raise ValueError("GLB_STAGE_DEFERRED_OBSERVATIONS_MISSING")
        elapsed = {}
        for row in observations:
            value = row.get("elapsed_seconds")
            if (type(value) not in (float, int) or not math.isfinite(value)
                    or value < floors[row["phase"]] or row.get("preserved") is not True):
                raise ValueError("GLB_STAGE_DEFERRED_OBSERVATION_INVALID")
            elapsed[row["phase"]] = value
        if elapsed["immediate"] != 0. or elapsed["timer_0_5"] < elapsed["timer_0_1"]:
            raise ValueError("GLB_STAGE_DEFERRED_OBSERVATION_ORDER")
        result.update(passed=True, sha256=evidence_sha, bytes=len(raw))
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as cause:
        result["reason"] = str(cause) if isinstance(cause, ValueError) else "GLB_STAGE_EVIDENCE_UNAVAILABLE"
    return result


def _glb_runtime_validate(payload, temporary, process_instance, blender, inputs, process_id):
    result = {"passed": False, "path": str(temporary / "glb-stage-runtime-evidence.json")}
    try:
        from scripts.blender_glb_stage_runtime_smoke import (
            PROFILE,
            SCHEMA,
            decode,
            validate_runtime_transcript,
        )
        if type(payload) is not dict or inputs is None:
            raise ValueError("GLB_RUNTIME_MARKER_OBJECT_REQUIRED")
        version = payload.get("version")
        if (type(version) is not list or any(type(v) is not int for v in version)
                or tuple(version) not in GLB_STAGE_BUILDS
                or payload.get("build_hash") != GLB_STAGE_BUILDS[tuple(version)]):
            raise ValueError("GLB_RUNTIME_BUILD_MISMATCH")
        text = ".".join(map(str, version))
        if (payload.get("schema") != SCHEMA or payload.get("profile") != PROFILE
                or payload.get("completed") is not True
                or payload.get("blender_version") not in {text, text + " LTS"}
                or payload.get("process_instance") != process_instance
                or type(process_id) is not int or process_id <= 0
                or type(payload.get("process_id")) is not int or payload["process_id"] != process_id
                or payload.get("source_sha256") != inputs["source_sha256"]
                or payload.get("binary") != inputs["binary"]):
            raise ValueError("GLB_RUNTIME_LAUNCH_IDENTITY_MISMATCH")
        if _glb_stage_inputs(blender, runtime=True) != inputs:
            raise ValueError("GLB_RUNTIME_INPUT_CHANGED_DURING_RUN")
        sha, raw = _glb_stage_file(temporary / "glb-stage-runtime-evidence.json", GLB_STAGE_MAX_EVIDENCE, retain=True)
        if payload.get("evidence_sha256") != sha:
            raise ValueError("GLB_RUNTIME_EVIDENCE_DIGEST_MISMATCH")
        proof = decode(raw)
        fields = ("schema", "profile", "completed", "blender_version", "version", "build_hash", "process_instance", "process_id", "source_sha256", "binary")
        if any(type(proof.get(key)) is not type(payload[key]) or proof.get(key) != payload[key] for key in fields):
            raise ValueError("GLB_RUNTIME_RETAINED_IDENTITY_MISMATCH")
        validate_runtime_transcript(proof)
        result.update(passed=True, sha256=sha, bytes=len(raw))
    except (AssertionError, OSError, UnicodeError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError) as cause:
        result["reason"] = str(cause) if isinstance(cause, ValueError) else "GLB_RUNTIME_TRANSCRIPT_INVALID"
    return result


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


def _native_save_file(path: Path, maximum: int, *, capture: bool = False) -> tuple[str, bytes | None]:
    """Bound and pin an ordinary evidence/source file without following a link."""
    def identity(value):
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
        raise ValueError("Native save evidence file shape or budget")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    checksum, blocks, count = hashlib.sha256(), [] if capture else None, 0
    try:
        if identity(os.fstat(descriptor)) != identity(before):
            raise ValueError("Native save evidence changed before read")
        while True:
            block = os.read(descriptor, min(65536, maximum + 1 - count))
            if not block:
                break
            count += len(block)
            if count > maximum:
                raise ValueError("Native save evidence file budget")
            checksum.update(block)
            if blocks is not None:
                blocks.append(block)
        if (count != before.st_size or identity(os.fstat(descriptor)) != identity(before)
                or identity(path.lstat()) != identity(before)):
            raise ValueError("Native save evidence changed during read")
    finally:
        os.close(descriptor)
    return checksum.hexdigest(), b"".join(blocks) if blocks is not None else None


def _native_save_json(data: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate native save evidence key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("Nonfinite native save evidence")

    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Nonfinite native save evidence")
        return result

    value = json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite, parse_float=floating)
    if type(value) is not dict:
        raise ValueError("Native save evidence must be an object")
    return value


def _native_save_sources() -> dict[str, str]:
    return {name: _native_save_file(ROOT / name, 2 * 1024 * 1024)[0] for name in NATIVE_SAVE_LARGE_SOURCES}


def _native_save_resources(facts: dict, *, require_floor: bool = True) -> bool:
    """Validate measured large-image facts without importing Blender or its add-on."""
    keys = {"scope", "available_memory_bytes", "host_available_memory_bytes", "visible_cgroup_headroom_bytes",
        "visible_cgroup_levels", "disk_free_bytes", "aggregate_image_pixels", "required_memory_bytes",
        "required_disk_bytes", "measurement_is_reservation"}
    if (type(facts) is not dict or set(facts) != keys or facts["scope"] != "LINUX_HOST_AND_VISIBLE_CGROUP_V2"
            or facts["measurement_is_reservation"] is not False):
        return False
    for name in keys - {"scope", "measurement_is_reservation", "visible_cgroup_headroom_bytes"}:
        if type(facts[name]) is not int or not 0 <= facts[name] <= 2**63 - 1:
            return False
    visible = facts["visible_cgroup_headroom_bytes"]
    if visible is not None and (type(visible) is not int or not 0 <= visible <= 2**63 - 1):
        return False
    effective = facts["host_available_memory_bytes"]
    if visible is not None:
        effective = min(effective, visible)
    return (facts["available_memory_bytes"] == effective and (not require_floor or effective >= 8 * 1024**3)
        and facts["disk_free_bytes"] >= 2 * 1024**3 and 1 <= facts["visible_cgroup_levels"] <= 128
        and facts["required_memory_bytes"] == 8 * 1024**3 and facts["required_disk_bytes"] == 2 * 1024**3
        and facts["aggregate_image_pixels"] == 16_777_216)


def _native_save_digest(value: object, length: int = 64) -> bool:
    return type(value) is str and len(value) == length and all(char in "0123456789abcdef" for char in value)


def _native_save_peak(memory: object) -> bool:
    return (type(memory) is dict and set(memory) == {"available", "metric", "scope", "value", "unit", "platform"}
        and memory == {"available": True, "metric": "ru_maxrss", "scope": "RUSAGE_SELF",
                       "value": memory.get("value"), "unit": "KiB", "platform": "linux"}
        and memory["available"] is True and type(memory["value"]) is int and 0 <= memory["value"] <= 2**53 - 1)


def _native_save_reader_receipt(row: dict, full: dict, sources: dict, *, succeeded: bool) -> bool:
    if type(row) is not dict:
        return False
    required = {"schema", "status", "token", "saved_sha256", "projection_sha256", "actual_projection_sha256",
        "program", "process_id", "blender_version", "build_hash", "native_open_invoked", "native_open_completed",
        "declared_projection_reopened", "source_process_contacted", "source_restore_writes", "reader_project_save_invoked",
        "native_effect_inventory_complete", "timings", "peak_memory", "error"}
    if set(row) != required and set(row) != required | {"resource_checks"}:
        return False
    fixed = {"schema": "native_save_reader_receipt_v1", "status": "succeeded" if succeeded else "failed",
        "blender_version": full["blender_version"], "build_hash": full["source_build"],
        "source_process_contacted": False, "source_restore_writes": 0, "reader_project_save_invoked": False,
        "native_effect_inventory_complete": False}
    if (any(type(row.get(key)) is not type(value) or row.get(key) != value for key, value in fixed.items())
            or type(row.get("process_id")) is not int or row["process_id"] <= 0 or row["process_id"] == full["process_id"]
            or not _native_save_digest(row.get("token"), 32)
            or any(not _native_save_digest(row.get(key)) for key in ("saved_sha256", "projection_sha256"))
            or row.get("program") != {name: sources["addon/blender_codex_bridge/" + name]
                                      for name in ("native_save_reader.py", "native_save_profile.py")}):
        return False
    if any(type(row[name]) is not bool for name in ("native_open_invoked", "native_open_completed", "declared_projection_reopened")):
        return False
    timings = row["timings"]
    if (type(timings) is not dict or set(timings) != {"worker_elapsed_seconds", "native_open_seconds", "projection_seconds"}
            or any(value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 300)
                   for value in timings.values()) or timings["worker_elapsed_seconds"] is None):
        return False
    if not _native_save_peak(row["peak_memory"]):
        return False
    if succeeded:
        if (row.get("error") is not None or row.get("actual_projection_sha256") != row["projection_sha256"]
                or any(row.get(key) is not True for key in
                       ("native_open_invoked", "native_open_completed", "declared_projection_reopened"))):
            return False
        checks = row.get("resource_checks")
        if (type(checks) is not list or len(checks) != 4
                or [item.get("phase") if type(item) is dict else None for item in checks] !=
                   ["before_open", "before_packed_decode", "before_packed_decode", "before_capture"]
                or any(set(item) != {"phase", "facts"} or not _native_save_resources(item["facts"]) for item in checks)):
            return False
        if any(value is None for value in timings.values()):
            return False
    else:
        error = row["error"]
        if (type(error) is not dict or set(error) not in (
                {"code", "type", "failure_stage"}, {"code", "type", "failure_stage", "profile_reason"})
                or error.get("code") != "NATIVE_SAVE_READER_FAILED" or type(error.get("type")) is not str
                or not 1 <= len(error["type"]) <= 64 or not error["type"].isascii() or not error["type"].isidentifier()
                or row["declared_projection_reopened"] is not False):
            return False
        before_open = {"build_validation", "program_validation", "input_validation", "runtime_validation",
                       "expected_projection", "reader_preferences"}
        after_open = {"image_preload", "projection_capture", "projection_compare", "final_input_validation"}
        stage = error["failure_stage"]
        if (stage not in before_open | after_open | {"native_open"}
                or (stage in before_open and row["native_open_invoked"])
                or (stage == "native_open" and (not row["native_open_invoked"] or row["native_open_completed"]))
                or (stage in after_open and not row["native_open_completed"])
                or (row["native_open_completed"] and not row["native_open_invoked"])):
            return False
        if "profile_reason" in error and (
            error["type"] != "ProfileRefused" or stage not in {"expected_projection", "projection_capture"}
            or type(error["profile_reason"]) is not str or not 0 < len(error["profile_reason"]) <= 160
        ):
            return False
        if not row["native_open_invoked"]:
            if timings["native_open_seconds"] is not None or timings["projection_seconds"] is not None:
                return False
        elif timings["native_open_seconds"] is None:
            return False
        actual = row["actual_projection_sha256"]
        if ((actual is not None and (not _native_save_digest(actual) or timings["projection_seconds"] is None))
                or (not row["native_open_completed"] and (actual is not None or timings["projection_seconds"] is not None))
                or (stage in {"image_preload", "projection_capture"} and actual is not None)
                or (stage in {"projection_compare", "final_input_validation"} and actual is None)):
            return False
        observed_phases = []
        if "resource_checks" in row:
            checks = row["resource_checks"]
            phases = ["before_open", "before_packed_decode", "before_packed_decode", "before_capture"]
            if (type(checks) is not list or len(checks) > 4
                    or any(type(item) is not dict or set(item) != {"phase", "facts"}
                           or item["phase"] != phases[index] or not _native_save_resources(item["facts"])
                           for index, item in enumerate(checks))):
                return False
            observed_phases = [item["phase"] for item in checks]
        if stage in {"build_validation", "program_validation", "input_validation", "runtime_validation"}:
            if "resource_checks" in row:
                return False
        elif stage == "expected_projection":
            if observed_phases not in ([], ["before_open"]):
                return False
        else:
            if not observed_phases or observed_phases[0] != "before_open":
                return False
            if stage in {"reader_preferences", "native_open"} and observed_phases != ["before_open"]:
                return False
            if stage == "image_preload" and "before_capture" in observed_phases:
                return False
            if stage in {"projection_capture", "projection_compare", "final_input_validation"}:
                if observed_phases.count("before_packed_decode") != 2:
                    return False
                if stage != "projection_capture" and observed_phases[-1] != "before_capture":
                    return False
    return True


def _native_save_large_receipt_matches(payload: dict | None, temporary: Path, process_instance: str,
                                     sources: dict, binary: dict) -> bool:
    """Require the owned large-mode report, real queued workflow and fresh readers."""
    try:
        fixed = {"schema": "native_save_large_fixture_v1", "profile": "NATIVE_SAVE_CLEAN_PACKED_4K_V1",
            "completed": True, "process_instance": process_instance}
        if type(payload) is not dict or any(type(payload.get(key)) is not type(value) or payload.get(key) != value
                                            for key, value in fixed.items()):
            return False
        versions = {"62c1db4208e8": "4.5.14", "d13f752e3b9c": "5.2.2"}
        version = versions[payload["source_build"]]
        if (payload.get("blender_version") not in {version, version + " LTS"}
                or type(payload.get("process_id")) is not int or payload["process_id"] <= 0 or payload.get("binary") != binary):
            return False
        report, binding = temporary / "native-save-large-evidence.json", payload["full_receipt"]
        if (type(binding) is not dict or set(binding) != {"path", "bytes", "sha256"} or binding["path"] != str(report)
                or type(binding["bytes"]) is not int or not 0 < binding["bytes"] <= 8 * 1024 * 1024):
            return False
        checksum, data = _native_save_file(report, 8 * 1024 * 1024, capture=True)
        if len(data) != binding["bytes"] or checksum != binding["sha256"]:
            return False
        full = _native_save_json(data)
        fields = (*fixed, "blender_version", "source_build", "process_id", "binary", "source_snapshot_sha256")
        if any(type(full.get(key)) is not type(payload.get(key)) or full.get(key) != payload.get(key) for key in fields):
            return False
        canonical = json.dumps(sources, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        if (full.get("source_fingerprints") != sources or payload["source_snapshot_sha256"] != hashlib.sha256(canonical).hexdigest()
                or _native_save_sources() != sources or _native_save_file(Path(binary["path"]), 1024**3)[0] != binary["sha256"]):
            return False
        flags = {"real_queued_loopback": True, "manual_ticks": False, "direct_dispatch": False,
            "external_source_folder_unavailable": True, "parent_identity_preserved": True,
            "declared_authored_projection_preserved": True, "full_4k_dirty_generated_qualified": False, "windows_qualified": False}
        if any(type(full.get(key)) is not type(value) or full.get(key) != value for key, value in flags.items()):
            return False
        if (not _native_save_peak(full.get("source_peak_memory")) or type(full.get("phase_timeout_seconds")) is not int
                or full["phase_timeout_seconds"] != 300 or type(full.get("phase_elapsed_seconds")) not in {int, float}
                or not math.isfinite(full["phase_elapsed_seconds"]) or not 0 <= full["phase_elapsed_seconds"] <= 300):
            return False
        image = full["image"]
        expected_image = {"width": 4096, "height": 4096, "channels": 4, "components": 67_108_864,
                          "colorspace": "sRGB", "alpha_mode": "STRAIGHT"}
        if (type(image) is not dict or any(type(image.get(key)) is not type(value) or image.get(key) != value
                                         for key, value in expected_image.items())
                or type(image.get("packed_bytes")) is not int or not 20 * 1024**2 < image["packed_bytes"] <= 80 * 1024**2
                or any(not _native_save_digest(image.get(key)) for key in ("packed_sha256", "pixels_sha256_float32_le"))):
            return False
        assertions, rows = full["assertions"], full["rows"]
        low_resource = full["low_resource_native_qualified"]
        if type(low_resource) is not bool:
            return False
        cases = NATIVE_SAVE_LARGE_CASES | ({"low_resource"} if low_resource else set())
        if (type(assertions) is not dict or set(assertions) != cases
                or any(value is not True for value in assertions.values()) or type(rows) is not list
                or len(rows) != len(cases) or any(type(row) is not dict for row in rows)
                or {row.get("case") for row in rows} != cases):
            return False
        readers = []
        for row in rows:
            job = row["job"]
            if type(job) is not dict:
                return False
            if row["case"] in {"permission_denial", "manual_drift", "low_resource"}:
                code = {"permission_denial": "PERMISSION_DENIED", "manual_drift": "OPERATION_FAILED",
                        "low_resource": "NOT_IMPLEMENTED"}[row["case"]]
                if job.get("ok") is not False or type(job.get("error")) is not dict or job["error"].get("code") != code:
                    return False
                if row["case"] in {"manual_drift", "low_resource"}:
                    reason = "SOURCE_CHANGED" if row["case"] == "manual_drift" else "LARGE_IMAGE_MEMORY_BUDGET"
                    if (type(job["error"].get("context")) is not dict or job["error"]["context"].get("reason") != reason
                            or row.get("native_entry_invoked") is not False):
                        return False
                    if row["case"] == "manual_drift" and row.get("manual_preserved") is not True:
                        return False
                    if row["case"] == "low_resource" and (
                        not _native_save_resources(row.get("before_resources"))
                        or not _native_save_resources(row.get("pressured_resources"), require_floor=False)
                        or not 6 * 1024**3 <= row["pressured_resources"]["available_memory_bytes"] < 8 * 1024**3
                        or type(row.get("pressure_bytes")) is not int or not 0 < row["pressure_bytes"] <= 2 * 1024**3
                    ):
                        return False
                continue
            if job.get("terminal") is not True:
                return False
            if row["case"] not in {"success_copy", "save_as", "save_current", "replace"}:
                if job.get("state") not in {"FAILED", "CANCELLED"} or job.get("result") is not None:
                    return False
                if row["case"] == "reader_failure":
                    reader = row.get("reader_evidence")
                    if type(reader) is dict and "worker_receipt" in reader:
                        reader = reader["worker_receipt"]
                    if not _native_save_reader_receipt(reader, full, sources, succeeded=False):
                        return False
                    injection = row.get("injection")
                    if (type(injection) is not dict or injection.get("injected") is not True
                            or injection.get("kind") != "owned_expected_json_single_space"
                            or any(type(injection.get(key)) is not type(reader[key]) or injection.get(key) != reader[key]
                                   for key in ("process_id", "token", "saved_sha256", "projection_sha256"))
                            or reader["error"].get("type") != "ValueError"
                            or reader["error"]["failure_stage"] not in {"input_validation", "expected_projection"}
                            or reader["native_open_invoked"] is not False or reader["native_open_completed"] is not False
                            or reader["actual_projection_sha256"] is not None):
                        return False
                continue
            result = job["result"]
            if (job.get("state") != "SUCCEEDED" or type(result) is not dict
                    or result.get("fresh_process_reopen_verified") is not True or result.get("declared_source_verified") is not True
                    or type(result.get("native_save_interval_ms")) not in {int, float}
                    or not math.isfinite(result["native_save_interval_ms"]) or not 0 <= result["native_save_interval_ms"] <= 300_000):
                return False
            resources = row.get("source_resources")
            if type(resources) is not list or not 1 <= len(resources) <= 8 or not all(_native_save_resources(item) for item in resources):
                return False
            reader = result["reader_evidence"]
            if (not _native_save_reader_receipt(reader, full, sources, succeeded=True)
                    or ("reader_evidence" in row and row["reader_evidence"] != reader)):
                return False
            readers.append((reader["process_id"], reader["token"]))
        return len({item[0] for item in readers}) == len({item[1] for item in readers}) == 4
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return False


def _census_receipt_matches(payload: dict | None, temporary: Path, process_instance: str) -> bool:
    """Accept census metadata only with its complete owned, source-bound receipt."""
    try:
        if not isinstance(payload, dict):
            return False
        if (payload.get("completed") is not True or payload.get("profile") != "RNA_CENSUS_ONLY_V1"
                or payload.get("scope") != "class_metadata_only"
                or payload.get("lifecycle_functional_acceptance") is not False
                or payload.get("windows_qualified") is not False
                or payload.get("process_instance") != process_instance
                or type(payload.get("process_id")) is not int or payload["process_id"] <= 0):
            return False
        build_versions = {"62c1db4208e8": "4.5.14", "d13f752e3b9c": "5.2.2"}
        version = build_versions[payload["source_build"]]
        if payload.get("blender_version") not in {version, version + " LTS"}:
            return False
        binding = payload["full_receipt"]
        report = temporary / "current-pixels-census.json"
        if (type(binding) is not dict or set(binding) != {"path", "bytes", "sha256"}
                or binding["path"] != str(report) or report.is_symlink()
                or type(binding["bytes"]) is not int or not 0 < binding["bytes"] <= 2 * 1024 * 1024
                or report.stat().st_size != binding["bytes"]):
            return False
        with report.open("rb") as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        if len(data) != binding["bytes"] or hashlib.sha256(data).hexdigest() != binding["sha256"]:
            return False
        full = json.loads(data)
        fields = ("completed", "profile", "scope", "process_instance", "process_id", "blender_version",
                  "source_build", "source_snapshot_sha256", "lifecycle_functional_acceptance", "windows_qualified")
        if type(full) is not dict or any(type(full.get(key)) is not type(payload.get(key))
                                        or full.get(key) != payload.get(key) for key in fields):
            return False
        paths = [ROOT / "scripts/blender_current_pixels_lifecycle_smoke.py", ROOT / "scripts/run_blender_checks.py"]
        paths.extend(sorted((ROOT / "addon/blender_codex_bridge").rglob("*.py")))
        if not 3 <= len(paths) <= 512 or any(path.is_symlink() for path in paths):
            return False
        expected = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        if "addon/blender_codex_bridge/current_pixels_graph.py" not in expected:
            return False
        canonical = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        catalog = full["catalog"]
        return (full.get("source_fingerprints") == expected
                and payload["source_snapshot_sha256"] == hashlib.sha256(canonical).hexdigest()
                and type(catalog) is dict and catalog.get("schema") == "current_pixels_complete_class_census_v1"
                and catalog.get("build_hash") == payload["source_build"]
                and type(catalog.get("classes")) is dict and set(catalog["classes"]) == CURRENT_PIXELS_CENSUS_CLASSES)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _graph_receipt_matches(payload: dict | None, temporary: Path, process_instance: str) -> bool:
    """Accept complete native graph evidence without granting lifecycle scope."""
    try:
        if type(payload) is not dict:
            return False
        expected_flags = {"completed": True, "profile": "CURRENT_PIXELS_NATIVE_SOURCE_GRAPH_V1",
            "scope": "native_source_graph_read_only", "lifecycle_functional_acceptance": False,
            "current_pixels_origin_qualified": False, "windows_qualified": False, "process_instance": process_instance}
        if any(type(payload.get(key)) is not type(value) or payload.get(key) != value for key, value in expected_flags.items()):
            return False
        versions = {"62c1db4208e8": "4.5.14", "d13f752e3b9c": "5.2.2"}
        version = versions[payload["source_build"]]
        if (payload.get("blender_version") not in {version, version + " LTS"}
                or type(payload.get("process_id")) is not int or payload["process_id"] <= 0):
            return False
        binding, report = payload["full_receipt"], temporary / "current-pixels-source-graph.json"
        if (type(binding) is not dict or set(binding) != {"path", "bytes", "sha256"}
                or binding["path"] != str(report) or report.is_symlink()
                or type(binding["bytes"]) is not int or not 0 < binding["bytes"] <= 2 * 1024 * 1024
                or report.stat().st_size != binding["bytes"]):
            return False
        with report.open("rb") as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        if len(data) != binding["bytes"] or hashlib.sha256(data).hexdigest() != binding["sha256"]:
            return False
        full = json.loads(data)
        fields = (*expected_flags, "process_id", "blender_version", "source_build", "source_snapshot_sha256")
        if type(full) is not dict or any(type(full.get(key)) is not type(payload.get(key)) or full.get(key) != payload.get(key) for key in fields):
            return False
        paths = [ROOT / "scripts/blender_current_pixels_lifecycle_smoke.py", ROOT / "scripts/run_blender_checks.py"]
        paths.extend(sorted((ROOT / "addon/blender_codex_bridge").rglob("*.py")))
        if not 4 <= len(paths) <= 512 or any(path.is_symlink() for path in paths):
            return False
        expected = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        if not {"addon/blender_codex_bridge/current_pixels_graph.py", "addon/blender_codex_bridge/current_pixels_source.py"} <= expected.keys():
            return False
        canonical = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        if (full.get("source_fingerprints") != expected or payload["source_snapshot_sha256"] != hashlib.sha256(canonical).hexdigest()
                or type(full.get("assertions")) is not dict or set(full["assertions"]) != CURRENT_PIXELS_GRAPH_ASSERTIONS
                or any(value is not True for value in full["assertions"].values())
                or type(full.get("checks")) is not int or full["checks"] <= 0
                or type(full.get("foreign_callbacks")) is not int or full["foreign_callbacks"] != 0
                or type(full.get("peak_rss_bytes")) is not int or full["peak_rss_bytes"] <= 0):
            return False
        baseline = full["baseline"]
        if (type(baseline) is not dict or baseline.get("profile") != "FILE_F32_EXR_DATA_CURRENT_PIXELS_V1"
                or any(baseline.get(name) is not True for name in ("complete_pixels_verified", "snapshot_canonical_packed_verified", "original_canonical_packed_verified"))):
            return False
        for name in ("native_graph_sha256", "portable_graph_sha256", "full_native_prefix_sha256", "full_portable_prefix_sha256"):
            value = baseline.get(name)
            if type(value) is not str or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                return False
        setup, limits, intervals = full["setup"], full["limitations"], full["full_read_intervals"]
        if (type(setup) is not dict or setup.get("owned_empty_factory") is not True
                or setup.get("intentional_manual_edits_separate_from_observation") is not True
                or setup.get("production_files_written") is not False or setup.get("lifecycle_backup_files") != []
                or type(limits) is not dict or limits.get("current_pixels_origin_qualified") is not False
                or limits.get("public_tool_acceptance") is not False or limits.get("windows_qualified") is not False
                or limits.get("first_authorization_pixel_only_change_detection") is not False
                or limits.get("trusted_canonical_native_registry") is not True
                or limits.get("provider_source_refusal_is_owned_probe_guard_only") is not True
                or type(intervals) is not list or not 2 <= len(intervals) <= 16):
            return False
        return all(type(row) is dict and type(row.get("full_read_seconds")) in {int, float}
            and 0 <= row["full_read_seconds"] <= 300
            and type(row.get("memory_available")) is int and row["memory_available"] >= 512 * 1024 * 1024
            and type(row.get("disk_available")) is int and row["disk_available"] >= 64 * 1024 * 1024 for row in intervals)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _domain_binding(binding: object, root: Path, maximum: int, *, capture: bool = False,
                    allow_empty_staging: bool = False) -> bytes:
    if (type(binding) is not dict or set(binding) != {"path", "bytes", "sha256"}
            or type(binding["path"]) is not str or type(binding["bytes"]) is not int
            or not (0 if allow_empty_staging else 1) <= binding["bytes"] <= maximum
            or not _domain_hex(binding["sha256"])):
        raise ValueError("Malformed domain file binding")
    path = Path(binding["path"])
    if binding["bytes"] == 0 and (not _domain_staging_name(path.name)
                                  or binding["sha256"] != hashlib.sha256(b"").hexdigest()):
        raise ValueError("Empty domain evidence is not a declared staging artifact")
    raw, observed = _domain_regular(path, root, maximum, capture=capture, allow_empty_staging=allow_empty_staging)
    if observed != binding:
        raise ValueError("Changed domain file binding")
    return raw

def _domain_display() -> dict:
    """Attest the private Linux display before launching an interactive child."""
    if sys.platform != "linux" or os.environ.get("WAYLAND_DISPLAY"):
        raise ValueError("Domain UI qualification requires the private Linux display")
    path = Path(os.environ.get("BRIDGE_TEST_PRIVATE_UI_MANIFEST", ""))
    raw, binding = _domain_regular(path, path.parent, 16384, capture=True)
    manifest = json.loads(raw)
    if (type(manifest) is not dict or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1
            or any(manifest.get(key) is not True for key in ("input_disabled", "owned_process", "tcp_disabled"))
            or manifest.get("display") != os.environ.get("DISPLAY")):
        raise ValueError("Invalid private domain display attestation")
    for field, maximum in (("screen_width", 1600), ("screen_height", 1200)):
        if type(manifest.get(field)) is not int or not 640 <= manifest[field] <= maximum:
            raise ValueError("Invalid private domain display dimensions")
    profile = Path(manifest["profile"])
    runtime = Path(manifest["xdg_runtime_dir"])
    if (profile != path.parent or runtime != profile / "runtime"
            or str(runtime) != os.environ.get("XDG_RUNTIME_DIR")):
        raise ValueError("Unowned domain display profile")
    for directory in (profile, runtime):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("Private domain display directory changed")
    if any(runtime.glob("wayland-*")):
        raise ValueError("Private domain display has a Wayland endpoint")
    authority = Path(manifest["xauthority_path"])
    authority_info = authority.lstat()
    if (authority.parent != profile or str(authority) != os.environ.get("XAUTHORITY")
            or not stat.S_ISREG(authority_info.st_mode) or authority_info.st_uid != os.getuid()
            or stat.S_IMODE(authority_info.st_mode) != 0o600):
        raise ValueError("Private domain authority selector changed")
    # Match the reviewed launcher's fixed source identities, never cookie bytes.
    for field, expected in (("launcher", "d243355385d6179d85d3fe5adecd8c2e752f470b7d6cf686b71934f31e7e5aa9"),
                            ("config", "fd963752e6e6595d7f3c6602928d4daca3276ef76156f4713a84fc21569ba7c6")):
        source = Path(manifest["launcher_path"]) if field == "launcher" else profile / "xorg.conf"
        _data, observed = _domain_regular(source, source.parent, 65536 if field == "launcher" else 16384)
        if observed["sha256"] != expected or manifest[field + "_sha256"] != expected:
            raise ValueError("Private domain launcher/configuration changed")
    pid = manifest["server_pid"]
    if type(pid) is not int or pid <= 1 or pid == os.getpid():
        raise ValueError("Invalid private domain display PID")
    os.kill(pid, 0)
    descriptor = os.open(f"/proc/{pid}/cmdline", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        command = stream.read(16385)
    if not 0 < len(command) <= 16384:
        raise ValueError("Invalid private domain display command")
    arguments = [part.decode() for part in command.split(b"\0") if part]
    if Path(arguments[0]).name != "Xorg" or manifest["display"] not in arguments:
        raise ValueError("Private domain display process changed")
    for option, value in (("-config", str(profile / "xorg.conf")), ("-auth", str(authority)), ("-nolisten", "tcp")):
        if option not in arguments or arguments[arguments.index(option) + 1] != value:
            raise ValueError("Private domain display process options changed")
    return binding

def _domain_hex(value: object, length: int = 64) -> bool:
    return type(value) is str and len(value) == length and all(c in "0123456789abcdef" for c in value)

def _domain_regular(path: Path, root: Path, maximum: int, *, capture: bool = False,
                    allow_empty_staging: bool = False) -> tuple[bytes, dict]:
    """Open bounded owned regular files without following links or waiting on FIFOs."""
    if (not path.is_absolute() or not root.is_absolute() or not path.is_relative_to(root)
            or any(part in {".", ".."} for part in path.parts)):
        raise ValueError("Unowned domain evidence path")
    parts = path.relative_to(root).parts
    if not parts or len(parts) > 16:
        raise ValueError("Domain evidence path budget")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    directory = os.open(root, directory_flags)
    descriptor = None
    try:
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(descriptor)
        minimum = 0 if allow_empty_staging and _domain_staging_name(path.name) else 1
        if not stat.S_ISREG(before.st_mode) or not minimum <= before.st_size <= maximum:
            raise ValueError("Domain evidence must be a bounded regular file")
        digest, size, chunks = hashlib.sha256(), 0, []
        while True:
            block = os.read(descriptor, min(1024 * 1024, maximum + 1 - size))
            if not block:
                break
            size += len(block)
            if size > maximum:
                raise ValueError("Domain evidence grew beyond its budget")
            digest.update(block)
            if capture:
                chunks.append(block)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if size != before.st_size or any(getattr(before, key) != getattr(after, key) for key in fields):
            raise ValueError("Domain evidence changed while reading")
        return b"".join(chunks), {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)

def _domain_staging_name(name: str) -> bool:
    prefix, suffix = ".blender-codex-current-pixels-", ".staging"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return False
    token = name[len(prefix):-len(suffix)]
    return 1 <= len(token) <= 64 and all(character in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in token)

def _mesh_storage_identity(value: object) -> bool:
    if type(value) is dict and set(value) == {"name", "session_uid", "pointer"}:
        name, uid, pointer = value["name"], value["session_uid"], value["pointer"]
    elif type(value) is list and len(value) == 3:
        name, uid, pointer = value
    else:
        return False
    valid_uid = ((type(uid) is int and 0 < uid < 2**64) or (type(uid) is str and 0 < len(uid) <= 20
                 and uid.isascii() and uid.isdecimal() and 0 < int(uid) < 2**64))
    valid_pointer = ((type(pointer) is int and 0 < pointer < 2**64) or (type(pointer) is str
                     and 0 < len(pointer) <= 16 and all(char in "0123456789abcdef" for char in pointer)
                     and int(pointer, 16) > 0))
    return type(name) is str and 0 < len(name) <= 255 and valid_uid and valid_pointer

def _mesh_storage_journal(journal: object, oracle: dict) -> bool:
    flags = {"data_lookup_entered", "data_lookup_returned", "materialize_entered", "materialize_returned",
             "after_storage_observed", "verified", "baseline_conflict"}
    fields = flags | {"name", "action", "entry_kind", "before_storage", "after_storage", "readback_entries",
                      "readback_returns", "logical_values_sha256", "retained_physical_transition", "helper_attached"}
    if (type(journal) is not dict or journal.get("schema") != "mesh_storage_retained_effects_v1"
            or journal.get("sealed") is not True or type(journal.get("rows")) is not list or len(journal["rows"]) != 2
            or journal.get("verification_required") is not True or journal.get("requires_fresh_image_preview") is not True
            or any(journal.get(key) is not False for key in ("physical_cache_passivity_claimed", "inverse_attempted",
                "independently_measured_SINGLE_pre_values", "project_saved", "durable_backup"))):
        return False
    for row, name in zip(journal["rows"], (".uv_select_face", "UVSingle"), strict=True):
        if type(row) is not dict or row.get("name") != name or type(row.get("helper_attached")) is not bool:
            return False
        if row["helper_attached"] is False:
            if set(row) != {"name", "helper_attached"}:
                return False
            continue
        if (set(row) != fields or any(type(row[key]) is not bool for key in flags)
                or row["before_storage"] not in {"SINGLE", "ARRAY"} or row["after_storage"] not in {None, "ARRAY"}
                or type(row["readback_entries"]) is not int or type(row["readback_returns"]) is not int
                or not 0 <= row["readback_returns"] <= row["readback_entries"] <= 128):
            return False
        if row["action"] == "NOOP_ALREADY_ARRAY":
            if (row["before_storage"] != "ARRAY" or row["entry_kind"] != "NOOP_ALREADY_ARRAY"
                    or row["logical_values_sha256"] is not None or row["materialize_entered"] is not False):
                return False
        elif row["action"] == "MATERIALIZE_SINGLE":
            if row["before_storage"] != "SINGLE" or row["entry_kind"] != "FOREACH_GET":
                return False
            digest = row["logical_values_sha256"]
            if digest is not None:
                expected = hashlib.sha256(json.dumps(oracle[name], sort_keys=True, ensure_ascii=True,
                    allow_nan=False, separators=(",", ":")).encode("ascii")).hexdigest()
                if not _domain_hex(digest) or digest != expected:
                    return False
            if row["verified"] and (not row["materialize_returned"] or digest is None or row["readback_returns"] < 1):
                return False
        else:
            return False
        if ((row["data_lookup_returned"] and not row["data_lookup_entered"])
                or (row["materialize_entered"] and not row["data_lookup_returned"])
                or (row["materialize_returned"] and not row["materialize_entered"])
                or (row["after_storage_observed"] and row["after_storage"] != "ARRAY")):
            return False
    return (journal.get("materialization_entered") is any(row.get("materialize_entered", False) for row in journal["rows"])
            and journal.get("native_lookup_entered") is any(row.get("data_lookup_entered", False) for row in journal["rows"]))

def _mesh_storage_phase_cases(full: dict, bundle: Path) -> bool:
    """Independent typed preservation, RPC owner, journal and native-prefix checks."""
    accepted = {}
    local_terminals = {}
    for case_name, row in full["cases"].items():
        expected_assertions = ({"complete": True, "actual_undo_response_retained": True,
                                "before_after_measured": True, "restore_safety_qualified": False}
                               if case_name == "recovery" else dict.fromkeys(MESH_STORAGE_CASE_ASSERTIONS, True))
        if (type(row) is not dict or set(row) != {"requests", "assertions", "evidence"}
                or type(row["assertions"]) is not dict or row["assertions"] != expected_assertions
                or any(type(row["assertions"][key]) is not bool for key in expected_assertions)):
            return False
        exchange = _mesh_storage_requests(row["requests"])
        if exchange is None or set(accepted) & exchange[0].keys():
            return False
        accepted.update(exchange[0])
        local_terminals[case_name] = exchange[1]
    if not _mesh_storage_trace(full["native_trace"], full["cases"], accepted):
        return False
    for name, row in full["cases"].items():
        evidence = row["evidence"]
        required = {"before", "after", "oracle_values", "terminal", "journal", "stop_counts", "history", "recovery"}
        if (type(evidence) is not dict or not required <= evidence.keys()
                or not _mesh_storage_snapshot(evidence["before"]) or not _mesh_storage_snapshot(evidence["after"])):
            return False
        before, after, oracle = evidence["before"], evidence["after"], evidence["oracle_values"]
        if (type(oracle) is not dict or set(oracle) != {".uv_select_face", "UVSingle"}
                or any(not _mesh_storage_values(value, key, nonzero=True) for key, value in oracle.items())
                or any(type(evidence[key]) is not list or len(evidence[key]) > 256 for key in ("history", "recovery"))):
            return False
        if name != "recovery" and any(before[key] != after[key] for key in ("object_identity", "mesh_identity", "uv_roles", "protected")):
            return False
        if name != "recovery":
            for old, new in zip(before["selected_storage"], after["selected_storage"], strict=True):
                if old[:3] != new[:3] or old[4] != new[4] or (old[3] == "ARRAY" and new[3] != "ARRAY"):
                    return False
            if any(value != oracle[key] for key, value in after["selected_values"].items()):
                return False
        stop = evidence["stop_counts"]
        if (type(stop) is not dict or set(stop) != {"provider_before", "provider_after", "native_before", "native_after"}
                or any(type(value) is not int or not 0 <= value <= 10_000_000 for value in stop.values())
                or stop["provider_before"] != stop["provider_after"] or stop["native_before"] != stop["native_after"]):
            return False
        terminal, journal = evidence["terminal"], evidence["journal"]
        if terminal is None:
            if journal is not None or name not in {"permission_denial", "invalid_context", "stale_preview", "protected_scope_denial", "recovery"}:
                return False
        elif (type(terminal) is not dict or terminal.get("job_id") not in accepted
              or terminal != local_terminals[name].get(terminal["job_id"]) or terminal.get("storage_effects") != journal
              or not _mesh_storage_journal(journal, oracle)):
            return False
        if name in {"permission_denial", "invalid_context", "stale_preview", "protected_scope_denial"}:
            errors = [call["response"]["error"] for call in row["requests"] if call["response"]["ok"] is False]
            allowed = {"permission_denial": {"PERMISSION_DENIED"},
                       "invalid_context": {"INVALID_MODE", "BLENDER_CONTEXT_ERROR", "NOT_IMPLEMENTED"},
                       "stale_preview": {"NOT_IMPLEMENTED"}, "protected_scope_denial": {"INVALID_ARGUMENT"}}[name]
            if terminal is not None or not any(error["code"] in allowed for error in errors):
                return False
            if name == "protected_scope_denial" and not any(error.get("context", {}).get("protected_scope_violation") is True for error in errors):
                return False
        if name in {"cancel_after_first", "seed_cancel", "failure_after_second_native", "undelivered", "pause_revoke", "disconnect"}:
            matching = [stop_row for stop_row in full["native_trace"]["stops"]
                        if stop_row["case"] == name and terminal is not None and stop_row["job_id"] == terminal["job_id"]]
            if (len(matching) != 1 or stop["native_before"] != matching[0]["native_at_accept"]
                    or stop["provider_before"] != matching[0]["provider_at_accept"]):
                return False
        elif any(stop.values()):
            return False
        if name == "two_rows":
            if (terminal is None or terminal["state"] != "SUCCEEDED"
                    or any(row[3] != "SINGLE" for row in before["selected_storage"])
                    or any(row[3] != "ARRAY" for row in after["selected_storage"])
                    or any(item.get("verified") is not True or item.get("materialize_returned") is not True for item in journal["rows"])):
                return False
        elif name in {"cancel_after_first", "disconnect"}:
            if (terminal is None or terminal["state"] != "CANCELLED"
                    or [row[3] for row in after["selected_storage"]] != ["ARRAY", "SINGLE"]
                    or journal["rows"][0].get("verified") is not True or journal["rows"][1]["helper_attached"] is not False):
                return False
        elif name == "seed_cancel":
            if (terminal is None or terminal["state"] != "CANCELLED" or before != after
                    or evidence.get("history_setup_explicit_ARRAY") is not True
                    or [row[3] for row in before["selected_storage"]] != ["ARRAY", "ARRAY"]
                    or journal["rows"][0].get("action") != "NOOP_ALREADY_ARRAY"
                    or journal["rows"][0].get("verified") is not True or journal["rows"][1]["helper_attached"] is not False):
                return False
        elif name == "failure_after_second_native":
            if (terminal is None or terminal["state"] != "FAILED"
                    or [row[3] for row in after["selected_storage"]] != ["ARRAY", "ARRAY"]
                    or journal["rows"][0].get("verified") is not True
                    or journal["rows"][1].get("materialize_entered") is not True
                    or journal["rows"][1].get("materialize_returned") is not False):
                return False
        elif name == "recovery":
            recovery_calls = [call for call in row["requests"] if call["request"]["method"] == "checkpoint.undo_last"]
            if (len(recovery_calls) != 1
                    or recovery_calls[0]["request"]["params"].get("confirm_global_undo") is not True):
                return False
            if (not evidence["recovery"] or not any(type(measured) is dict
                    and set(measured) == {"kind", "request_id", "response", "before", "after", "safety_qualified"}
                    and measured.get("kind") == "authorized_native_undo_measurement" and measured.get("safety_qualified") is False
                    and _mesh_storage_snapshot(measured.get("before")) and _mesh_storage_snapshot(measured.get("after"))
                    and measured.get("before") == before and measured.get("after") == after
                    and measured.get("request_id") == recovery_calls[0]["request"]["id"]
                    and measured.get("response") == recovery_calls[0]["response"] for measured in evidence["recovery"])):
                return False
        elif name == "history_eviction":
            local = _mesh_storage_requests(row["requests"])
            successes = [result for job_id, result in local[1].items() if job_id in local[0] and result["state"] == "SUCCEEDED"]
            if (len(successes) != 33 or any(not _mesh_storage_journal(result.get("storage_effects"), oracle)
                    or any(item.get("action") != "NOOP_ALREADY_ARRAY" or item.get("verified") is not True
                           for item in result["storage_effects"]["rows"]) for result in successes)
                    or terminal is None or terminal.get("terminal_history_evicted") is not True
                    or evidence.get("history_setup_explicit_ARRAY") is not True
                    or not evidence["history"] or not evidence["recovery"]):
                return False
        elif name in {"undelivered", "pause_revoke"}:
            if (before != after or terminal is None
                    or terminal["state"] != ("FAILED" if name == "pause_revoke" else "CANCELLED")
                    or any(item["helper_attached"] is not False for item in journal["rows"])
                    or any(event["case"] == name and event["kind"] in {"prepare_enter", "materialize_enter"}
                           for event in full["native_trace"]["events"])):
                return False
        elif before != after or (terminal is not None and terminal["state"] not in {"FAILED", "CANCELLED"}):
            return False
    # Only bounded fixture-owned files may be retained in the phase bundle.
    files = list(bundle.rglob("*"))
    return (len(files) <= 32 and all(not path.is_symlink() for path in files)
            and all(path.is_dir() or (path.suffix in {".png", ".json"}
                    and _domain_regular(path, bundle, DOMAIN_MAX_REPORT)[1]["bytes"] <= DOMAIN_MAX_REPORT)
                    or (path.name == "fixture-image.exr" and _domain_regular(path, bundle, 65536)[1]["bytes"] <= 65536)
                    for path in files))

def _mesh_storage_receipt_matches(payload: object, temporary: Path, process_instance: str, phase: str,
                                  bundle: Path, pid: int, binary: dict, sources: dict, display: dict) -> bool:
    """Independently bind a complete private fixture receipt; no marker-only pass."""
    try:
        common = {"schema", "completed", "phase", "process_id", "process_instance", "runtime_nonce",
                  "source_build", "blender_version", "source_snapshot_sha256", "binary_sha256"}
        if (type(payload) is not dict or set(payload) != common | {"full_receipt"}
                or type(pid) is not int or pid <= 0 or phase not in MESH_STORAGE_PHASES):
            return False
        expected = {"schema": "MESH_STORAGE_OWNED_JOB_NATIVE_V1", "completed": True, "phase": phase,
                    "process_id": pid, "process_instance": process_instance, "source_build": "d13f752e3b9c",
                    "binary_sha256": binary["sha256"]}
        if (any(type(payload.get(key)) is not type(value) or payload[key] != value for key, value in expected.items())
                or type(payload.get("blender_version")) is not str
                or payload["blender_version"] not in {"5.2.2", "5.2.2 LTS"}
                or binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256 or not _domain_hex(payload["runtime_nonce"], 32)):
            return False
        binding = payload["full_receipt"]
        if type(binding) is not dict or binding.get("path") != str(temporary / "mesh-storage-job.json"):
            return False
        full = _native_save_json(_domain_binding(binding, temporary, DOMAIN_MAX_REPORT, capture=True))
        extras = {"source_fingerprints", "private_display", "transport", "resources", "hardware", "seconds",
                  "assertions", "cases", "native_trace", "limitations", "helper_sha256", "runtime_identity"}
        if (set(full) != common | extras
                or any(type(full[key]) is not type(payload[key]) or full[key] != payload[key] for key in common)):
            return False
        encoded = json.dumps(sources, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        if (full["source_fingerprints"] != sources or _mesh_storage_sources() != sources
                or full["source_snapshot_sha256"] != hashlib.sha256(encoded).hexdigest()
                or full["private_display"] != display or full["helper_sha256"] != MESH_STORAGE_HELPER_SHA256):
            return False
        identity = full["runtime_identity"]
        if (type(identity) is not dict or set(identity) != {"process_instance", "runtime_id", "registry_id", "queue_id"}
                or identity["process_instance"] != process_instance
                or any(type(identity[key]) is not int or not 0 < identity[key] < 2**64
                       for key in ("runtime_id", "registry_id", "queue_id"))
                or len({identity[key] for key in ("runtime_id", "registry_id", "queue_id")}) != 3
                or hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True, allow_nan=False,
                    separators=(",", ":")).encode("ascii")).hexdigest()[:32] != full["runtime_nonce"]):
            return False
        transport = {"host": "127.0.0.1", "socket_json": True, "runtime_timer_queue": True,
                     "direct_dispatch": False, "manual_scheduler_drain": False}
        if (type(full["transport"]) is not dict or full["transport"] != transport
                or any(type(full["transport"][key]) is not type(value) for key, value in transport.items())
                or type(full["limitations"]) is not dict or full["limitations"] != MESH_STORAGE_LIMITS
                or any(value is not False for value in full["limitations"].values())
                or type(full["assertions"]) is not dict or set(full["assertions"]) != MESH_STORAGE_ASSERTIONS
                or any(value is not True for value in full["assertions"].values())
                or type(full["seconds"]) not in {int, float} or not math.isfinite(full["seconds"])
                or not 0 <= full["seconds"] <= 300
                or any(type(full[key]) is not dict or not full[key] for key in ("resources", "hardware"))):
            return False
        if type(full["cases"]) is not dict or set(full["cases"]) != MESH_STORAGE_CASES[phase]:
            return False
        return _mesh_storage_phase_cases(full, bundle)
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError, UnicodeError):
        return False

def _mesh_storage_requests(exchanges: object) -> tuple[dict, dict] | None:
    """Return accepted owners and measured terminal replies from actual RPC envelopes."""
    if type(exchanges) is not list or not 1 <= len(exchanges) <= 4096:
        return None
    accepted, terminals, seen, previews = {}, {}, set(), {}
    for exchange in exchanges:
        if type(exchange) is not dict or set(exchange) != {"request", "response"}:
            return None
        request, response = exchange["request"], exchange["response"]
        if (type(request) is not dict or not {"id", "method", "params", "protocol_version"} <= request.keys()
                or set(request) - {"id", "method", "params", "protocol_version", "timeout_ms"}
                or type(request["id"]) is not str or not 0 < len(request["id"]) <= 128 or request["id"] in seen
                or type(request["params"]) is not dict or request["protocol_version"] != "1.0"
                or ("timeout_ms" in request and (type(request["timeout_ms"]) is not int or not 1 <= request["timeout_ms"] <= 60000))
                or request["method"] not in {"mesh.attribute_storage_prepare_preview", "mesh.attribute_storage_prepare_job_start",
                    "jobs.inspect", "jobs.cancel", "jobs.list", "checkpoint.undo_last", "bridge.status", "bridge.history",
                    "task.plan.set", "task.plan.enforce", "task.plan.clear"}):
            return None
        seen.add(request["id"])
        if (type(response) is not dict or response.get("id") != request["id"] or type(response.get("ok")) is not bool
                or response.get("protocol_version") != "1.0" or type(response.get("timestamp")) is not str
                or not 0 < len(response["timestamp"]) <= 128
                or set(response) != {"id", "ok", "protocol_version", "timestamp", "result" if response["ok"] else "error"}):
            return None
        if response["ok"] is False:
            error = response["error"]
            if type(error) is not dict or type(error.get("code")) is not str or not error["code"]:
                return None
            continue
        result = response["result"]
        if request["method"] == "mesh.attribute_storage_prepare_preview":
            params = request["params"]
            if (type(result) is not dict or not _domain_hex(result.get("expected_preparation_fingerprint"))
                    or type(params.get("object_name")) is not str or type(params.get("mesh_name")) is not str
                    or params.get("attribute_names") != [".uv_select_face", "UVSingle"]):
                return None
            previews[(params["object_name"], params["mesh_name"])] = result["expected_preparation_fingerprint"]
        if request["method"] == "mesh.attribute_storage_prepare_job_start":
            deadline = request["params"].get("time_limit_seconds", 60.)
            if type(deadline) not in {int, float} or not math.isfinite(deadline) or not 1 <= deadline <= 60:
                return None
            params = request["params"]
            if (params.get("attribute_names") != [".uv_select_face", "UVSingle"]
                    or type(params.get("object_name")) is not str or type(params.get("mesh_name")) is not str
                    or not _domain_hex(params.get("expected_preparation_fingerprint"))
                    or previews.get((params["object_name"], params["mesh_name"])) != params["expected_preparation_fingerprint"]
                    or params.get("confirm_materialize_storage") is not True
                    or params.get("confirm_retained_partial_preparation") is not True):
                return None
            job_id = result.get("job_id") if type(result) is dict else None
            if (type(job_id) is not str or not job_id.startswith("job_") or not _domain_hex(job_id[4:], 32)
                    or result.get("accepted") is not True or result.get("kind") != "mesh.attribute_storage_preparation" or job_id in accepted):
                return None
            accepted[job_id] = result
        if request["method"] == "jobs.inspect" and type(result) is dict and result.get("terminal") is True:
            job_id = result.get("job_id")
            if (request["params"] != {"job_id": job_id} or type(job_id) is not str
                    or result.get("kind") != "mesh.attribute_storage_preparation"
                    or result.get("state") not in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}):
                return None
            terminals[job_id] = result
    return accepted, terminals

def _mesh_storage_snapshot(snapshot: object) -> bool:
    keys = {"object_identity", "mesh_identity", "uv_roles", "selected_storage", "selected_values", "protected"}
    if (type(snapshot) is not dict or set(snapshot) != keys
            or any(not _mesh_storage_identity(snapshot[key]) for key in ("object_identity", "mesh_identity"))):
        return False
    roles = snapshot["uv_roles"]
    if (type(roles) is not list or len(roles) != 2 or type(roles[0]) is not int or not -1 <= roles[0] <= 0
            or roles[1] != [["UVSingle", True, False]]
            or any(type(value) is not bool for value in roles[1][0][1:])):
        return False
    rows, values = snapshot["selected_storage"], snapshot["selected_values"]
    if type(rows) is not list or len(rows) != 2 or type(values) is not dict:
        return False
    for row, expected in zip(rows, ((".uv_select_face", "FACE", "BOOLEAN", 1), ("UVSingle", "CORNER", "FLOAT2", 3)), strict=True):
        if (type(row) is not list or len(row) != 5 or row[:3] != list(expected[:3])
                or row[3] not in {"SINGLE", "ARRAY"} or type(row[4]) is not int or row[4] != expected[3]):
            return False
    if set(values) != {row[0] for row in rows if row[3] == "ARRAY"}:
        return False
    if any(not _mesh_storage_values(value, name) for name, value in values.items()):
        return False
    protected = snapshot["protected"]
    if (type(protected) is not dict or set(protected) != {"Main_ids", "image", "material_bindings", "original_ARRAY_values", "unselected_attribute_headers"}
            or type(protected["Main_ids"]) is not list or not 1 <= len(protected["Main_ids"]) <= 128
            or type(protected["material_bindings"]) is not list or not 1 <= len(protected["material_bindings"]) <= 64
            or type(protected["original_ARRAY_values"]) not in {dict, list} or not protected["original_ARRAY_values"]):
        return False
    collections = set()
    for collection in protected["Main_ids"]:
        if (type(collection) is not list or len(collection) != 2 or type(collection[0]) is not str
                or not 0 < len(collection[0]) <= 255 or collection[0] in collections
                or type(collection[1]) is not list or len(collection[1]) > 512):
            return False
        collections.add(collection[0])
        for row in collection[1]:
            if (type(row) is not list or len(row) != 5 or not _mesh_storage_identity([row[0], row[2], row[1]])
                    or type(row[3]) is not int or not 0 <= row[3] <= 65536 or type(row[4]) is not bool):
                return False
    image = protected["image"]
    image_keys = {"identity", "pixels_float32_le", "packed_sha256", "packed_bytes", "color_space", "alpha_mode", "is_dirty", "has_data"}
    if (type(image) is not dict or set(image) != image_keys or not _mesh_storage_identity(image["identity"])
            or not _domain_hex(image["pixels_float32_le"], 128) or not _domain_hex(image["packed_sha256"])
            or type(image["packed_bytes"]) is not int or not 0 < image["packed_bytes"] <= 1024**2
            or any(type(image[key]) is not str or not 0 < len(image[key]) <= 255 for key in ("color_space", "alpha_mode"))
            or type(image["is_dirty"]) is not bool or image["has_data"] is not True):
        return False
    arrays = protected["original_ARRAY_values"]
    if type(arrays) is not list or not 1 <= len(arrays) <= 32:
        return False
    headers = protected["unselected_attribute_headers"]
    if type(headers) is not list or not 1 <= len(headers) <= 32:
        return False
    by_name = {}
    for row in headers:
        if (type(row) is not list or len(row) != 5 or type(row[0]) is not str or not 0 < len(row[0]) <= 63
                or row[0] in by_name or row[0] in {".uv_select_face", "UVSingle"}
                or row[1] not in {"POINT", "EDGE", "FACE", "CORNER"}
                or row[2] not in {"BOOLEAN", "INT", "INT32_2D", "FLOAT2", "FLOAT_VECTOR"}
                or row[3] not in {"ARRAY", "SINGLE"} or type(row[4]) is not int
                or row[4] != (1 if row[1] == "FACE" else 3)):
            return False
        by_name[row[0]] = row
    names = set()
    for row in arrays:
        if (type(row) is not list or len(row) != 4 or type(row[0]) is not str or not 0 < len(row[0]) <= 63
                or row[0] in names or row[0] in {".uv_select_face", "UVSingle"}
                or row[1] not in {"POINT", "EDGE", "FACE", "CORNER"}
                or type(row[3]) is not list or len(row[3]) != (1 if row[1] == "FACE" else 3)
                or by_name.get(row[0]) != [*row[:3], "ARRAY", len(row[3])]):
            return False
        names.add(row[0])
        kind, values = row[2], row[3]
        if kind == "BOOLEAN":
            if any(type(value) is not bool for value in values):
                return False
        elif kind == "INT":
            if any(type(value) is not int or not -(2**31) <= value < 2**31 for value in values):
                return False
        elif kind in {"FLOAT_VECTOR", "FLOAT2", "INT32_2D"}:
            width = 3 if kind == "FLOAT_VECTOR" else 2
            if any(type(value) is not list or len(value) != width for value in values):
                return False
            scalars = [component for value in values for component in value]
            if kind == "INT32_2D":
                if any(type(value) is not int or not -(2**31) <= value < 2**31 for value in scalars):
                    return False
            elif (any(not _domain_hex(value, 8) for value in scalars)
                  or any(not math.isfinite(struct.unpack("<f", bytes.fromhex(value))[0]) for value in scalars)):
                return False
        else:
            return False
    if "position" not in names or names != {name for name, row in by_name.items() if row[3] == "ARRAY"}:
        return False
    for binding in protected["material_bindings"]:
        if (type(binding) is not list or len(binding) != 6
                or any(not _mesh_storage_identity(binding[index]) for index in (0, 1, 4))
                or type(binding[2]) is not str or not 0 < len(binding[2]) <= 255
                or type(binding[3]) is not int or not 0 < binding[3] < 2**64
                or binding[4] != image["identity"] or type(binding[5]) is not list or not 1 <= len(binding[5]) <= 32
                or any(slot != binding[0] or not _mesh_storage_identity(slot) for slot in binding[5])):
            return False
    return all(math.isfinite(value) for value in struct.unpack("<16f", bytes.fromhex(image["pixels_float32_le"])))

def _mesh_storage_sources() -> dict[str, str]:
    """Bind the complete private candidate and every imported fixture helper."""
    paths = [ROOT / name for name in (
        "scripts/blender_mesh_storage_job_smoke.py", "scripts/run_blender_checks.py",
        "scripts/blender_artist_sidebar_smoke.py", "scripts/native_resources.py")]
    paths.extend(sorted((ROOT / "addon/blender_codex_bridge").rglob("*.py")))
    if not 8 <= len(paths) <= 512 or any(path.is_symlink() for path in paths):
        raise ValueError("Incomplete owned storage job source inventory")
    result = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if not {"addon/blender_codex_bridge/mesh_storage_source.py",
            "addon/blender_codex_bridge/scene_jobs.py",
            "addon/blender_codex_bridge/tools/mesh_storage.py"} <= result.keys():
        raise ValueError("Missing owned storage job program")
    if result.get("addon/blender_codex_bridge/mesh_storage_prepare.py") != MESH_STORAGE_HELPER_SHA256:
        raise ValueError("Native-qualified storage primitive changed")
    return result

def _mesh_storage_trace(trace: object, cases: dict, accepted: dict) -> bool:
    keys = {"scope", "covered_boundaries", "counts", "events", "stops", "native_C_intervals",
            "status_RPC_authorization_excluded", "all_hidden_Blender_native_calls_claimed",
            "wrapper_exit_counts_include_exception", "prepare_exit_counts_include_exception"}
    if (type(trace) is not dict or set(trace) != keys or trace["scope"] != "BRIDGE_B2_ACTIVE_DOMAIN_ONLY"
            or trace["covered_boundaries"] != ["helper_access_field", "graph_catalog", "helper_prepare_C_foreach"]
            or trace["status_RPC_authorization_excluded"] is not True
            or trace["all_hidden_Blender_native_calls_claimed"] is not False
            or trace["wrapper_exit_counts_include_exception"] is not True
            or trace["prepare_exit_counts_include_exception"] is not True):
        return False
    fields = {"native_entries", "native_returns", "provider_entries", "provider_returns", "prepare_entries",
              "prepare_returns", "materialize_entries", "materialize_returns",
              "after_accepted_stop_native_entries", "after_accepted_stop_provider_entries"}
    counts, events, stops = trace["counts"], trace["events"], trace["stops"]
    if (type(counts) is not dict or set(counts) != fields
            or any(type(value) is not int or not 0 <= value <= 10_000_000 for value in counts.values())
            or any(counts[name + "_returns"] > counts[name + "_entries"] for name in ("native", "provider", "prepare", "materialize"))
            or any(counts[name + "_returns"] != counts[name + "_entries"] for name in ("native", "provider", "prepare"))
            or counts["native_entries"] < counts["materialize_entries"] or counts["provider_entries"] < counts["prepare_entries"]
            or counts["after_accepted_stop_native_entries"] != 0 or counts["after_accepted_stop_provider_entries"] != 0
            or type(events) is not list or not 1 <= len(events) <= 4096
            or type(stops) is not list or len(stops) > 256):
        return False
    event_fields = {"sequence", "case", "kind", "monotonic", "job_id", "native_count", "provider_count", "turn", "attribute", "boundary"}
    boundaries = {"prepare_enter": "helper_prepare", "prepare_return": "helper_prepare",
                  "materialize_enter": "helper_prepare_C_foreach", "materialize_return": "helper_prepare_C_foreach",
                  "materialize_exception": "helper_prepare_C_foreach", "turn_enter": "scene_turn",
                  "turn_return": "scene_turn", "stop_intent": "job_stop", "stop_accepted": "job_stop"}
    derived = dict.fromkeys(("prepare_entries", "prepare_returns", "materialize_entries", "materialize_returns"), 0)
    time_before, native_before, provider_before, turns, prepares, materializing, seen_turns = 0., 0, 0, [], [], [], set()
    for sequence, row in enumerate(events, 1):
        if (type(row) is not dict or set(row) != event_fields or type(row["sequence"]) is not int or row["sequence"] != sequence
                or row["case"] not in cases or row["kind"] not in boundaries or row["boundary"] != boundaries[row["kind"]]
                or type(row["monotonic"]) not in {int, float} or not math.isfinite(row["monotonic"])
                or row["monotonic"] < time_before or type(row["turn"]) is not int or row["turn"] < 0
                or type(row["native_count"]) is not int or not native_before <= row["native_count"] <= counts["native_entries"]
                or type(row["provider_count"]) is not int or not provider_before <= row["provider_count"] <= counts["provider_entries"]
                or row["attribute"] not in {None, ".uv_select_face", "UVSingle"}
                or (row["job_id"] is not None and row["job_id"] not in accepted)):
            return False
        time_before, native_before, provider_before = row["monotonic"], row["native_count"], row["provider_count"]
        kind, turn = row["kind"], row["turn"]
        if kind == "turn_enter":
            if turns:
                return False
            turns.append(turn)
        elif kind == "turn_return":
            if turns != [turn] or prepares or materializing:
                return False
            turns.pop()
        elif kind == "prepare_enter":
            if prepares or turns != [turn] or row["attribute"] is None or row["job_id"] is None:
                return False
            prepares.append((turn, row["job_id"], row["attribute"]))
            derived["prepare_entries"] += 1
        elif kind == "prepare_return":
            if prepares != [(turn, row["job_id"], row["attribute"])] or materializing:
                return False
            prepares.pop()
            derived["prepare_returns"] += 1
        elif kind == "materialize_enter":
            owner = (row["job_id"], turn)
            if owner in seen_turns or materializing or prepares != [(turn, row["job_id"], row["attribute"])]:
                return False
            seen_turns.add(owner)
            materializing.append((turn, row["job_id"], row["attribute"]))
            derived["materialize_entries"] += 1
        elif kind in {"materialize_return", "materialize_exception"}:
            if materializing != [(turn, row["job_id"], row["attribute"])]:
                return False
            materializing.pop()
            derived["materialize_returns"] += kind == "materialize_return"
    if (turns or prepares or materializing or any(counts[key] != value for key, value in derived.items())
            or events[-1]["native_count"] != counts["native_entries"]
            or events[-1]["provider_count"] != counts["provider_entries"]):
        return False
    intervals = trace["native_C_intervals"]
    if type(intervals) is not list or len(intervals) != counts["materialize_entries"]:
        return False
    for interval in intervals:
        if (type(interval) is not dict or set(interval) != {"case", "attribute", "seconds", "returned"}
                or interval["case"] not in cases or interval["attribute"] not in {".uv_select_face", "UVSingle"}
                or type(interval["seconds"]) not in {int, float} or not math.isfinite(interval["seconds"])
                or not 0 <= interval["seconds"] <= 300 or type(interval["returned"]) is not bool):
            return False
    if sum(interval["returned"] for interval in intervals) != counts["materialize_returns"]:
        return False
    stopped = set()
    for stop in stops:
        if (type(stop) is not dict or set(stop) != {"case", "job_id", "accepted_sequence", "native_at_accept", "provider_at_accept", "kind"}
                or stop["case"] not in cases or stop["job_id"] not in accepted or stop["job_id"] in stopped
                or type(stop["accepted_sequence"]) is not int or not 1 <= stop["accepted_sequence"] <= len(events)
                or type(stop["kind"]) is not str or not 0 < len(stop["kind"]) <= 128):
            return False
        event = events[stop["accepted_sequence"] - 1]
        if (event["kind"] != "stop_accepted" or event["case"] != stop["case"] or event["job_id"] != stop["job_id"]
                or type(stop["native_at_accept"]) is not int or stop["native_at_accept"] != event["native_count"]
                or type(stop["provider_at_accept"]) is not int or stop["provider_at_accept"] != event["provider_count"]
                or any(row["job_id"] == stop["job_id"] and row["kind"] in {"prepare_enter", "materialize_enter"}
                       for row in events[stop["accepted_sequence"]:])):
            return False
        stopped.add(stop["job_id"])
    return sum(row["kind"] == "stop_accepted" for row in events) == len(stops)

def _mesh_storage_values(values: object, name: str, *, nonzero: bool = False) -> bool:
    if type(values) is not list:
        return False
    if name == ".uv_select_face":
        return len(values) == 1 and type(values[0]) is bool and (not nonzero or values[0] is True)
    if name != "UVSingle" or len(values) != 3:
        return False
    if any(type(pair) is not list or len(pair) != 2 or any(not _domain_hex(component, 8) for component in pair)
           for pair in values):
        return False
    numbers = [struct.unpack("<f", bytes.fromhex(component))[0] for pair in values for component in pair]
    return all(math.isfinite(number) for number in numbers) and (not nonzero or any(number != 0. for number in numbers))

def _run_mesh_storage_case(blender: Path, output: Path, timeout: int) -> dict:
    """Five independent factory processes; unsupported binaries never pass."""
    started = time.monotonic()
    summary = {"case": MESH_STORAGE_CASE, "script": CASES[MESH_STORAGE_CASE][0], "status": "failed",
               "phases": [], "phase_sequence": [], "fresh_process_verified": False,
               "execution_mode": "private_interactive_display", "qualification_scope": dict(MESH_STORAGE_LIMITS)}
    try:
        display = _domain_display()
        executable = blender.resolve(strict=True)
        _raw, binary = _domain_regular(executable, executable.parent, 1024**3)
        if binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256:
            summary["unsupported_binary"] = True
            raise ValueError("Owned storage preparation is qualified only for the pinned 5.2.2 candidate")
        sources = _mesh_storage_sources()
        summary["binary"] = binary
        seen = {"process_instance": set(), "process_id": set(), "runtime_nonce": set()}
        for phase in MESH_STORAGE_PHASES:
            if _domain_display() != display or _mesh_storage_sources() != sources:
                raise ValueError("Owned storage job display or source changed between phases")
            _domain_binding(binary, executable.parent, 1024**3)
            bundle = output / f"{MESH_STORAGE_CASE}-{phase}-bundle"
            bundle.mkdir(mode=0o700)
            result = _run_process(executable, MESH_STORAGE_CASE, output, timeout, phase=phase, bundle=bundle,
                                  phase_marker=MESH_STORAGE_MARKER, domain_binary=binary,
                                  domain_sources=sources, domain_display=display)
            summary["phases"].append(result)
            summary["phase_sequence"].append(phase)
            summary["status"] = result["status"]
            if result["status"] != "passed":
                break
            evidence = result["evidence"]
            if any(evidence[key] in values for key, values in seen.items()):
                result["status"] = summary["status"] = "failed"
                result["identity_error"] = "Owned storage job phase reused a process or runtime identity"
                break
            for key, values in seen.items():
                values.add(evidence[key])
        phases = summary["phases"]
        if (len(phases) == len(MESH_STORAGE_PHASES) and all(row["status"] == "passed" for row in phases)
                and len({row["blender_version"] for row in phases}) == 1
                and _mesh_storage_sources() == sources and _domain_display() == display):
            summary["status"], summary["fresh_process_verified"] = "passed", True
        elif len(phases) == len(MESH_STORAGE_PHASES) and summary["status"] == "passed":
            summary["status"] = "failed"
        if phases:
            summary["blender_version"] = phases[-1]["blender_version"]
            summary["script_sha256"] = phases[0]["script_sha256"]
    except (OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError, RecursionError):
        summary["status"] = "failed"
        summary["admission_error"] = "Owned storage job evidence or private process admission refused"
    summary["duration_seconds"] = round(time.monotonic() - started, 3)
    return summary


def _mesh_storage_control_transcript(full: dict) -> bool:
    """Independently classify the one real preview/start/inspect RPC sequence."""
    requests, timings = full["requests"], full["timings"]
    parsed = _mesh_storage_requests(requests)
    if (parsed is None or type(timings) is not list or len(timings) != len(requests)
            or not 1 <= len(requests) <= 2048):
        return False
    params = {"object_name": full["before"]["object_identity"][0],
              "mesh_name": full["before"]["mesh_identity"][0],
              "attribute_names": [".uv_select_face", "UVSingle"]}
    methods = ("mesh.attribute_storage_prepare_preview", "mesh.attribute_storage_prepare_job_start", "jobs.inspect")
    previous = 0.
    for index, (exchange, timing) in enumerate(zip(requests, timings, strict=True)):
        request = exchange["request"]
        response = exchange["response"]
        if response["ok"] is False and (type(response["error"].get("message")) is not str
                or not 0 < len(response["error"]["message"]) <= 4096):
            return False
        stage = ("preview", "start", "inspect")[min(index, 2)]
        if (request["method"] != methods[min(index, 2)] or request.get("timeout_ms") != 60000
                or type(request.get("timeout_ms")) is not int
                or type(timing) is not dict
                or set(timing) != {"stage", "request_id", "sent_at", "received_at", "cpu_seconds"}
                or timing["stage"] != stage or timing["request_id"] != request["id"]
                or any(type(timing[key]) not in {int, float} or not math.isfinite(timing[key])
                       or timing[key] < 0 for key in ("sent_at", "received_at", "cpu_seconds"))
                or not previous <= timing["sent_at"] <= timing["received_at"]
                # Retain scheduling/transport overhead without extending the
                # unchanged 60-second socket, wire, job or polling bounds.
                or not 0 <= timing["received_at"] - timing["sent_at"] <= 65
                or not 0 <= timing["cpu_seconds"] <= 300):
            return False
        previous = timing["received_at"]
    if timings[-1]["received_at"] - timings[0]["sent_at"] > full["seconds"]:
        return False
    if requests[0]["request"]["params"] != params:
        return False
    preview = requests[0]["response"]
    if preview["ok"] is False:
        return (len(requests) == 1 and full["outcome"] == "PREVIEW_REFUSED" and full["terminal"] is None
                and full["product_success"] is False)
    if len(requests) < 2:
        return False
    start = requests[1]["response"]
    expected = {**params, "expected_preparation_fingerprint": preview["result"]["expected_preparation_fingerprint"],
                "confirm_materialize_storage": True, "confirm_retained_partial_preparation": True,
                "time_limit_seconds": 60}
    actual = requests[1]["request"]["params"]
    if (actual != expected or any(type(actual[key]) is not bool for key in
            ("confirm_materialize_storage", "confirm_retained_partial_preparation"))
            or type(actual["time_limit_seconds"]) not in {int, float}):
        return False
    if start["ok"] is False:
        return (len(requests) == 2 and full["outcome"] == "START_REFUSED" and full["terminal"] is None
                and full["product_success"] is False)
    accepted, terminals = parsed
    job_id = start["result"]["job_id"]
    if (len(requests) < 3 or set(accepted) != {job_id} or set(terminals) != {job_id}
            or full["outcome"] != "JOB_TERMINAL" or type(full["terminal"]) is not dict
            or type(full["terminal"].get("terminal")) is not bool or full["terminal"]["terminal"] is not True
            or full["terminal"] != terminals[job_id]
            or not _mesh_storage_journal(full["terminal"].get("storage_effects"), full["setup_oracle_values"])):
        return False
    for index, exchange in enumerate(requests[2:], 2):
        response = exchange["response"]
        if (exchange["request"]["params"] != {"job_id": job_id} or response["ok"] is not True
                or type(response["result"]) is not dict or response["result"].get("job_id") != job_id
                or response["result"].get("kind") != "mesh.attribute_storage_preparation"
                or type(response["result"].get("terminal")) is not bool
                or response["result"]["terminal"] is not (index == len(requests) - 1)
                or (response["result"]["terminal"] is False and response["result"].get("state") not in
                    {"QUEUED", "RUNNING", "PAUSED", "CANCELLING", "FINALIZING"})):
            return False
    return requests[-1]["response"]["result"] == full["terminal"]


def _mesh_storage_control_matches(payload: object, temporary: Path, process_instance: str,
                                  pid: int, binary: dict, sources: dict, display: dict) -> dict:
    """Validate retained diagnostic bytes without trusting fixture classifications."""
    result = {"diagnostic_completed": False, "qualified": False,
              "path": str(temporary / MESH_STORAGE_CONTROL_REPORT)}
    try:
        common = {"schema", "completed", "diagnostic_only", "process_id", "process_instance", "source_build",
                  "blender_version", "binary_sha256", "source_snapshot_sha256", "product_success"}
        if (type(payload) is not dict or set(payload) != common | {"full_receipt"}
                or type(pid) is not int or pid <= 0 or type(binary) is not dict):
            raise ValueError("CONTROL_MARKER_SHAPE")
        expected = {"schema": MESH_STORAGE_CONTROL_PROFILE, "completed": True, "diagnostic_only": True,
                    "process_id": pid, "process_instance": process_instance, "source_build": "d13f752e3b9c",
                    "binary_sha256": binary["sha256"]}
        if (any(type(payload.get(key)) is not type(value) or payload[key] != value for key, value in expected.items())
                or type(payload["product_success"]) is not bool
                or type(payload["blender_version"]) is not str or payload["blender_version"] not in {"5.2.2", "5.2.2 LTS"}
                or binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256
                or type(payload["full_receipt"]) is not dict
                or payload["full_receipt"].get("path") != str(temporary / MESH_STORAGE_CONTROL_REPORT)):
            raise ValueError("CONTROL_LAUNCH_IDENTITY")
        raw = _domain_binding(payload["full_receipt"], temporary, DOMAIN_MAX_REPORT, capture=True)
        full = _native_save_json(raw)
        extras = {"phase", "runtime_nonce", "runtime_identity", "helper_sha256", "source_fingerprints", "private_display",
                  "transport", "flags", "hooks", "requests", "timings", "before", "after", "setup_oracle_values",
                  "terminal", "outcome", "selected_values_match", "protected_sample_equal", "identities_sample_equal",
                  "settled", "seconds"}
        if (set(full) != common | extras
                or any(type(full[key]) is not type(payload[key]) or full[key] != payload[key] for key in common)
                or full["phase"] != "success"):
            raise ValueError("CONTROL_RETAINED_SHAPE")
        encoded = json.dumps(sources, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        if (full["source_fingerprints"] != sources or _mesh_storage_sources() != sources
                or full["source_snapshot_sha256"] != hashlib.sha256(encoded).hexdigest()
                or full["private_display"] != display or _domain_display() != display
                or full["helper_sha256"] != MESH_STORAGE_HELPER_SHA256):
            raise ValueError("CONTROL_SOURCE_OR_DISPLAY_CHANGED")
        identity = full["runtime_identity"]
        if (type(identity) is not dict or set(identity) != {"process_instance", "runtime_id", "registry_id", "queue_id"}
                or identity["process_instance"] != process_instance
                or any(type(identity[key]) is not int or not 0 < identity[key] < 2**64
                       for key in ("runtime_id", "registry_id", "queue_id"))
                or len({identity[key] for key in ("runtime_id", "registry_id", "queue_id")}) != 3
                or hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True, allow_nan=False,
                    separators=(",", ":")).encode("ascii")).hexdigest()[:32] != full["runtime_nonce"]):
            raise ValueError("CONTROL_RUNTIME_IDENTITY")
        transport = {"host": "127.0.0.1", "socket_json": True, "runtime_timer_queue": True,
                     "direct_dispatch": False, "manual_scheduler_drain": False}
        settled = {"job_active": False, "is_executing": False, "executing_mutators": 0,
                   "executor_frame_present": False, "main_thread": True}
        if (type(full["transport"]) is not dict or full["transport"] != transport
                or any(type(full["transport"][key]) is not type(value) for key, value in transport.items())
                or type(full["flags"]) is not dict or full["flags"] != MESH_STORAGE_CONTROL_FLAGS
                or any(value is not False for value in full["flags"].values())
                or type(full["hooks"]) is not dict
                or set(full["hooks"]) != {"main_before", "worker_before", "main_after", "worker_after"}
                or any(type(value) is not list or len(value) != 4 or any(hook is not None for hook in value)
                       for value in full["hooks"].values())
                or type(full["settled"]) is not dict or full["settled"] != settled
                or any(type(full["settled"][key]) is not type(value) for key, value in settled.items())
                or type(full["seconds"]) not in {int, float} or not math.isfinite(full["seconds"])
                or not 0 <= full["seconds"] <= 300):
            raise ValueError("CONTROL_HOOK_OR_SCOPE_OR_SETTLEMENT")
        before, after = full["before"], full["after"]
        oracle = {".uv_select_face": [True], "UVSingle": [["0000803e", "000000bf"]] * 3}
        if (not _mesh_storage_snapshot(before) or not _mesh_storage_snapshot(after)
                or any(row[3] != "SINGLE" for row in before["selected_storage"])
                or full["setup_oracle_values"] != oracle
                or any(not _mesh_storage_values(value, name, nonzero=True) for name, value in full["setup_oracle_values"].items())
                or not _mesh_storage_control_transcript(full)):
            raise ValueError("CONTROL_SNAPSHOT_OR_TRANSCRIPT")
        selected = after["selected_values"] == oracle
        protected = before["protected"] == after["protected"] and before["uv_roles"] == after["uv_roles"]
        identities = all(before[key] == after[key] for key in ("object_identity", "mesh_identity"))
        product = (full["outcome"] == "JOB_TERMINAL" and full["terminal"]["state"] == "SUCCEEDED"
                   and all(row[3] == "ARRAY" for row in after["selected_storage"]) and selected)
        for key, value in (("selected_values_match", selected), ("protected_sample_equal", protected),
                           ("identities_sample_equal", identities), ("product_success", product)):
            if type(full[key]) is not bool or full[key] is not value:
                raise ValueError("CONTROL_CLASSIFICATION")
        result.update(diagnostic_completed=True, product_success=product, outcome=full["outcome"],
                      selected_values_match=selected, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError, UnicodeError) as cause:
        result["reason"] = str(cause) if isinstance(cause, ValueError) else "CONTROL_RECEIPT_INVALID"
    return result



def _mesh_storage_atomic_catalog():
    import ast
    specs = (("preview", "tools/mesh_storage.py", None, "preview"),
        ("build_plan", "mesh_storage_source.py", None, "build_plan"),
        ("checkpoint_roles_init", "mesh_storage_source.py", "CheckpointRoles", "__init__"),
        ("checkpoint_plan_read", "mesh_storage_source.py", "_StorageCheckpointPlan", "_read"),
        ("protected_facts", "mesh_storage_source.py", None, "protected_facts"),
        ("bind_protected", "mesh_storage_source.py", "CheckpointRoles", "bind_protected"),
        ("roles_authored", "mesh_storage_source.py", "CheckpointRoles", "authored"),
        ("roles_check", "mesh_storage_source.py", "CheckpointRoles", "check_after_read"),
        ("driver_init", "tools/_mesh_storage_job.py", "MeshStorageDriver", "__init__"),
        ("driver_full_check", "tools/_mesh_storage_job.py", "MeshStorageDriver", "check_after_read"),
        ("start_admission_init", "scene_jobs.py", "_StartAdmission", "__init__"),
        ("start_admission_full_check", "scene_jobs.py", "_StartAdmission", "check_after_read"),
        ("turn_admission_full_check", "scene_jobs.py", "_TurnAdmission", "check_after_read"),
        ("array_inventory", "mesh_storage_source.py", None, "array_inventory"),
        ("material", "mesh_storage_source.py", None, "_material"),
        ("array_hash", "mesh_storage_source.py", None, "array_hash"))
    result = []
    for label, relative, owner, name in specs:
        filename = "addon/blender_codex_bridge/" + relative
        nodes = ast.parse((ROOT / filename).read_text()).body
        if owner is not None:
            nodes = next(node for node in nodes if isinstance(node, ast.ClassDef) and node.name == owner).body
        function = next(node for node in nodes if isinstance(node, ast.FunctionDef) and node.name == name)
        first_line = min([function.lineno, *[node.lineno for node in function.decorator_list]])
        result.append({"label": label, "filename": filename, "first_line": first_line})
    return result


def _mesh_storage_atomic_spans(observed, seconds):
    from scripts.blender_mesh_storage_job_smoke import TIMING_LABELS, TIMING_UNKNOWN
    if type(observed) is not dict:
        return False
    expected = {"backend": "sys.monitoring.local_START_RETURN", "tool_id": 4, "global_event_mask": 0,
        "local_event_mask": 5, "restored": True, "callbacks_restored": True, "local_events_restored": True,
        "tool_freed": True, "row_limit": 2048, "exact_unwind_observed": False,
        "unknown_open_elapsed_is_upper_bound": True, "observed_timings_are_untraced_timings": False,
        "speedup_qualified": False, "overlapping_nested_spans_may_not_be_added": True}
    if (set(observed) != set(expected) | {"catalog", "spans"}
            or any(type(observed.get(key)) is not type(value) or observed[key] != value for key, value in expected.items())):
        return False
    catalog, spans = observed["catalog"], observed["spans"]
    if type(catalog) is not list or len(catalog) != 16 or type(spans) is not list or not 1 <= len(spans) <= 2048:
        return False
    expected_catalog = _mesh_storage_atomic_catalog()
    for row, label, target in zip(catalog, TIMING_LABELS, expected_catalog, strict=True):
        if (type(row) is not dict or set(row) != {"label", "filename", "first_line", "code_sha256"}
                or row["label"] != label or any(row[key] != value for key, value in target.items())
                or type(row["first_line"]) is not int or not 1 <= row["first_line"] <= 20000
                or not _domain_hex(row["code_sha256"])):
            return False
    previous = 0.
    for row in spans:
        if (type(row) is not dict or set(row) != {"label", "entered_at", "ended_at", "elapsed_upper_bound_seconds",
                "duration_seconds", "depth", "end", "ambiguous_recursion"} or row["label"] not in TIMING_LABELS
                or type(row["depth"]) is not int or not 0 <= row["depth"] < 64
                or type(row["ambiguous_recursion"]) is not bool
                or any(type(row[name]) is not float or not math.isfinite(row[name]) or row[name] < 0 for name in ("entered_at", "ended_at"))
                or not previous <= row["entered_at"] <= row["ended_at"]
                or row["ended_at"] - row["entered_at"] > seconds):
            return False
        previous = row["entered_at"]
        elapsed = row["ended_at"] - row["entered_at"]
        if row["end"] == "RETURN_COMPLETED":
            if (row["ambiguous_recursion"] or type(row["duration_seconds"]) is not float
                    or row["duration_seconds"] != elapsed or row["elapsed_upper_bound_seconds"] is not None):
                return False
        elif row["end"] == TIMING_UNKNOWN:
            if (row["duration_seconds"] is not None or type(row["elapsed_upper_bound_seconds"]) is not float
                    or row["elapsed_upper_bound_seconds"] != elapsed):
                return False
        else:
            return False
    return True


def _mesh_storage_timing_matches(payload: object, temporary: Path, process_instance: str,
                                  pid: int, binary: dict, sources: dict, display: dict) -> dict:
    """Validate retained diagnostic bytes without trusting fixture classifications or observed timings as deadline proof."""
    result = {"diagnostic_completed": False, "qualified": False,
              "path": str(temporary / MESH_STORAGE_TIMING_REPORT)}
    try:
        common = {"schema", "completed", "diagnostic_only", "process_id", "process_instance", "source_build",
                  "blender_version", "binary_sha256", "source_snapshot_sha256", "product_success"}
        if (type(payload) is not dict or set(payload) != common | {"full_receipt"}
                or type(pid) is not int or pid <= 0 or type(binary) is not dict):
            raise ValueError("CONTROL_MARKER_SHAPE")
        expected = {"schema": MESH_STORAGE_TIMING_PROFILE, "completed": True, "diagnostic_only": True,
                    "process_id": pid, "process_instance": process_instance, "source_build": "d13f752e3b9c",
                    "binary_sha256": binary["sha256"]}
        if (any(type(payload.get(key)) is not type(value) or payload[key] != value for key, value in expected.items())
                or type(payload["product_success"]) is not bool
                or type(payload["blender_version"]) is not str or payload["blender_version"] not in {"5.2.2", "5.2.2 LTS"}
                or binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256
                or type(payload["full_receipt"]) is not dict
                or payload["full_receipt"].get("path") != str(temporary / MESH_STORAGE_TIMING_REPORT)):
            raise ValueError("CONTROL_LAUNCH_IDENTITY")
        raw = _domain_binding(payload["full_receipt"], temporary, DOMAIN_MAX_REPORT, capture=True)
        full = _native_save_json(raw)
        extras = {"phase", "runtime_nonce", "runtime_identity", "helper_sha256", "source_fingerprints", "private_display",
                  "transport", "flags", "hooks", "requests", "timings", "before", "after", "setup_oracle_values",
                  "terminal", "outcome", "selected_values_match", "protected_sample_equal", "identities_sample_equal",
                  "settled", "seconds", "atomic_timing", "checkpoint_roles"}
        if (set(full) != common | extras
                or any(type(full[key]) is not type(payload[key]) or full[key] != payload[key] for key in common)
                or full["phase"] != "success"):
            raise ValueError("CONTROL_RETAINED_SHAPE")
        encoded = json.dumps(sources, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        if (full["source_fingerprints"] != sources or _mesh_storage_sources() != sources
                or full["source_snapshot_sha256"] != hashlib.sha256(encoded).hexdigest()
                or full["private_display"] != display or _domain_display() != display
                or full["helper_sha256"] != MESH_STORAGE_HELPER_SHA256):
            raise ValueError("CONTROL_SOURCE_OR_DISPLAY_CHANGED")
        identity = full["runtime_identity"]
        if (type(identity) is not dict or set(identity) != {"process_instance", "runtime_id", "registry_id", "queue_id"}
                or identity["process_instance"] != process_instance
                or any(type(identity[key]) is not int or not 0 < identity[key] < 2**64
                       for key in ("runtime_id", "registry_id", "queue_id"))
                or len({identity[key] for key in ("runtime_id", "registry_id", "queue_id")}) != 3
                or hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True, allow_nan=False,
                    separators=(",", ":")).encode("ascii")).hexdigest()[:32] != full["runtime_nonce"]):
            raise ValueError("CONTROL_RUNTIME_IDENTITY")
        transport = {"host": "127.0.0.1", "socket_json": True, "runtime_timer_queue": True,
                     "direct_dispatch": False, "manual_scheduler_drain": False}
        settled = {"job_active": False, "is_executing": False, "executing_mutators": 0,
                   "executor_frame_present": False, "main_thread": True}
        if (type(full["transport"]) is not dict or full["transport"] != transport
                or any(type(full["transport"][key]) is not type(value) for key, value in transport.items())
                or type(full["flags"]) is not dict or full["flags"] != MESH_STORAGE_CONTROL_FLAGS
                or any(value is not False for value in full["flags"].values())
                or type(full["hooks"]) is not dict
                or set(full["hooks"]) != {"main_before", "worker_before", "main_after", "worker_after"}
                or any(type(value) is not list or len(value) != 4 or any(hook is not None for hook in value)
                       for value in full["hooks"].values())
                or type(full["settled"]) is not dict or full["settled"] != settled
                or any(type(full["settled"][key]) is not type(value) for key, value in settled.items())
                or type(full["seconds"]) not in {int, float} or not math.isfinite(full["seconds"])
                or not 0 <= full["seconds"] <= 300):
            raise ValueError("CONTROL_HOOK_OR_SCOPE_OR_SETTLEMENT")
        before, after = full["before"], full["after"]
        oracle = {".uv_select_face": [True], "UVSingle": [["0000803e", "000000bf"]] * 3}
        if (not _mesh_storage_snapshot(before) or not _mesh_storage_snapshot(after)
                or any(row[3] != "SINGLE" for row in before["selected_storage"])
                or full["setup_oracle_values"] != oracle
                or any(not _mesh_storage_values(value, name, nonzero=True) for name, value in full["setup_oracle_values"].items())
                or not _mesh_storage_control_transcript(full)):
            raise ValueError("CONTROL_SNAPSHOT_OR_TRANSCRIPT")
        cached = full["checkpoint_roles"]
        if (type(cached) is not dict or set(cached) != {"preview", "terminal", "source", "additional_RNA_reads",
                "failed_terminal_after_readback_retained"}
                or cached["source"] != "product_cached_literal_reports_only"
                or type(cached["source"]) is not str or type(cached["additional_RNA_reads"]) is not int
                or cached["additional_RNA_reads"] != 0 or cached["failed_terminal_after_readback_retained"] is not False):
            raise ValueError("ATOMIC_CACHED_ROLES_SHAPE")

        def role_literal(value, depth=0):
            if depth > 8:
                raise ValueError("ATOMIC_CACHED_ROLE_LITERAL")
            kind = type(value)
            if value is None or kind is bool:
                return value
            if kind is int and 0 <= value < 2**64:
                return value
            if kind is str and len(value) <= 256:
                return value
            if kind is list and len(value) <= 32:
                return [role_literal(item, depth + 1) for item in value]
            if (kind is dict and len(value) <= 32
                    and all(type(key) is str and len(key) <= 128 for key in value)):
                return {key: role_literal(item, depth + 1) for key, item in value.items()}
            raise ValueError("ATOMIC_CACHED_ROLE_LITERAL")

        def role_bytes(value):
            if value is not None:
                fields = {"profile", "initial_roles", "before_readback", "after_readback", "native_push_completed",
                          "after_readback_measured", "protected_scope_sha256", "foreign_previous_owner_supported",
                          "physical_cache_passivity_claimed"}
                if (type(value) is not dict or set(value) != fields
                        or value["profile"] != "B2_EXACT_CHECKPOINT_WEAK_ROLE_V1"
                        or type(value["profile"]) is not str
                        or any(value[name] is not False for name in ("foreign_previous_owner_supported", "physical_cache_passivity_claimed"))
                        or any(type(value[name]) is not bool for name in ("native_push_completed", "after_readback_measured"))
                        or value["after_readback_measured"] is not (value["after_readback"] is not None)
                        or not _domain_hex(value["protected_scope_sha256"])):
                    raise ValueError("ATOMIC_CACHED_ROLE_PROFILE")
            # Canonical JSON keeps nested bool/int distinct; ordinary dict== does not.
            return json.dumps(role_literal(value), sort_keys=True, ensure_ascii=True, allow_nan=False,
                              separators=(",", ":")).encode("ascii")

        preview_reply = full["requests"][0]["response"]
        delivered_preview = preview_reply["result"] if preview_reply["ok"] is True else None
        delivered_terminal = None if full["terminal"] is None else full["terminal"].get("result")
        for name, container in (("preview", delivered_preview), ("terminal", delivered_terminal)):
            if container is not None and type(container) is not dict:
                raise ValueError("ATOMIC_CACHED_ROLE_CONTAINER")
            delivered = None if container is None else container.get("checkpoint_roles")
            if role_bytes(cached[name]) != role_bytes(delivered):
                raise ValueError("ATOMIC_CACHED_ROLE_WIRE_MISMATCH")
        if not _mesh_storage_atomic_spans(full["atomic_timing"], full["seconds"]):
            raise ValueError("ATOMIC_TIMING_INVALID")
        selected = after["selected_values"] == oracle
        protected = before["protected"] == after["protected"] and before["uv_roles"] == after["uv_roles"]
        identities = all(before[key] == after[key] for key in ("object_identity", "mesh_identity"))
        product = (full["outcome"] == "JOB_TERMINAL" and full["terminal"]["state"] == "SUCCEEDED"
                   and all(row[3] == "ARRAY" for row in after["selected_storage"]) and selected)
        for key, value in (("selected_values_match", selected), ("protected_sample_equal", protected),
                           ("identities_sample_equal", identities), ("product_success", product)):
            if type(full[key]) is not bool or full[key] is not value:
                raise ValueError("CONTROL_CLASSIFICATION")
        result.update(diagnostic_completed=True, product_success=product, outcome=full["outcome"],
                      selected_values_match=selected, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError, UnicodeError) as cause:
        result["reason"] = str(cause) if isinstance(cause, ValueError) else "CONTROL_RECEIPT_INVALID"
    return result


def _inspection_plain(value, depth=0, remaining=None):
    if remaining is None:
        remaining = [65536]
    remaining[0] -= 1
    if depth > 32 or remaining[0] < 0:
        return False
    kind = type(value)
    if value is None or kind is bool:
        return True
    if kind is int:
        return value.bit_length() <= 64
    if kind is float:
        return math.isfinite(value)
    if kind is str:
        return len(value) <= 16384
    if kind is list:
        return len(value) <= 2048 and all(_inspection_plain(item, depth+1, remaining) for item in value)
    if kind is dict:
        return (len(value) <= 512 and all(type(key) is str and len(key) <= 255 for key in value)
                and all(_inspection_plain(item, depth+1, remaining) for item in value.values()))
    return False


def _inspection_equal(first, second):
    return (_inspection_plain(first) and _inspection_plain(second)
            and json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=True) ==
            json.dumps(second, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def _inspection_hex(value):
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _inspection_clock(value):
    return type(value) is float and math.isfinite(value) and value >= 0.


def _inspection_hooks(value):
    return _inspection_equal(value, {"python": [None]*4, "monitoring_tools": [None]*6,
                                      "monitoring_global_events": [0]*6})


def _inspection_summary(value, job_id, request_id, *, accepted=False):
    fields = {"job_id", "kind", "label", "request_id", "state", "terminal", "phase", "revision", "progress", "result", "error",
        "inspection_only", "ready", "invalidated_reason", "logical_write_capability", "native_reads_started",
        "physical_read_effects", "undo_boundary_created", "undo_boundary_finalized", "checkpoint", "created_at",
        "verification_required", "durable"}
    if accepted:
        fields |= {"accepted", "job_completed", "input_frozen_at_acceptance", "native_commit_interruptible"}
    if (type(value) is not dict or set(value) != fields or value["job_id"] != job_id or value["request_id"] != request_id
            or value["kind"] != "mesh.attribute_storage_inspection" or type(value["label"]) is not str
            or not value["label"].startswith("Inspect mesh attribute storage ") or type(value["revision"]) is not int
            or value["revision"] < 1 or value["invalidated_reason"] != "" or value["error"] is not None
            or type(value["created_at"]) is not str or not 1 <= len(value["created_at"]) <= 128):
        return False
    for name, expected in {"inspection_only": True, "logical_write_capability": False, "undo_boundary_created": False,
                           "undo_boundary_finalized": False, "verification_required": True, "durable": False}.items():
        if value[name] is not expected:
            return False
    if value["checkpoint"] != {}:
        return False
    progress = value["progress"]
    if (type(progress) is not dict or set(progress) != {"phase", "completed", "total"}
            or type(progress["completed"]) is not int or not 0 <= progress["completed"] <= 3
            or type(progress["total"]) is not int or progress["total"] != 3):
        return False
    completed = progress["completed"]
    phases = ("inspection_plan", "inspection_capture", "inspection_seal", "inspection_complete")
    if value["phase"] != phases[completed] or value["native_reads_started"] is not (completed > 0):
        return False
    if not _inspection_equal(value["physical_read_effects"],
            {"ARRAY_COW_or_tagging_possible": completed > 0, "image_buffer_cache_changes_possible": completed > 0}):
        return False
    terminal = completed == 3
    if (value["terminal"] is not terminal or value["ready"] is not terminal
            or (terminal and (value["state"] != "SUCCEEDED" or progress["phase"] != "succeeded"))
            or (not terminal and (value["state"] not in {"QUEUED", "RUNNING"} or value["result"] is not None
                or progress["phase"] != ("awaiting_start_delivery" if completed == 0 else phases[completed])))):
        return False
    invalid_acceptance = accepted and (completed != 0 or value["revision"] != 1 or any(value[key] is not expected for key, expected in
            (("accepted", True), ("job_completed", False), ("input_frozen_at_acceptance", True), ("native_commit_interruptible", False))))
    return not invalid_acceptance


def _inspection_sample_details(sample):
    scene = sample["context"]
    snapshot = sample["snapshot"]
    if (type(scene) is not dict or set(scene) != {"mode", "scene", "active", "selection", "scene_self_references", "particle_object"}
            or scene["mode"] != "OBJECT" or not _mesh_storage_identity(scene["scene"])
            or not _inspection_equal(scene["active"], snapshot["object_identity"])
            or not _inspection_equal(scene["selection"], [snapshot["object_identity"]])
            or type(scene["scene_self_references"]) is not int or not 0 <= scene["scene_self_references"] <= 65536
            or (scene["particle_object"] is not None and not _inspection_equal(scene["particle_object"], scene["active"]))):
        return False
    boundary = {"operation_history": [], "checkpoints": [], "undo_steps": 0, "pending": False, "owned_pending": 0,
                "editor_session": False, "recovery_ids": [], "reservation_owner": False, "retained_reservations": 0,
                "write_turns": 0, "read_turns": 0}
    if not _inspection_equal(sample["boundaries"], boundary):
        return False
    widths = {"BOOLEAN": 1, "INT": 4, "INT32_2D": 8, "FLOAT2": 8, "FLOAT_VECTOR": 12}
    arrays, image = snapshot["protected"]["original_ARRAY_values"], snapshot["protected"]["image"]
    expected = {"original_ARRAY_elements": sum(len(row[3]) for row in arrays),
                "original_ARRAY_payload_bytes": sum(len(row[3]) * widths[row[2]] for row in arrays),
                "image_float32_values": len(image["pixels_float32_le"]) // 8,
                "image_float32_bytes": len(image["pixels_float32_le"]) // 2, "packed_bytes": image["packed_bytes"],
                "selected_SINGLE_payloads_sampled": False,
                "scope": "Known fixture ARRAY/image payloads; not total native allocations or COW events"}
    if not _inspection_equal(sample["payloads"], expected):
        return False
    memory = sample["memory"]
    return (type(memory) is dict and set(memory) == {"supported", "resident_bytes", "peak_resident_bytes", "scope", "available_bytes"}
            and memory["supported"] is True and memory["scope"] ==
                "Whole isolated Blender process lifetime; Linux procfs RSS/high-water mark, not a cap or attribution"
            and all(type(memory[key]) is int and memory[key] > 0 for key in ("resident_bytes", "peak_resident_bytes", "available_bytes"))
            and memory["peak_resident_bytes"] >= memory["resident_bytes"])


def _inspection_cached_job(full):
    cached, terminal = full["after"]["runtime_job"], full["terminal"]
    fields = {"job_id", "request_id", "method", "kind", "state", "phase", "revision", "driver_retired", "ready_record_present",
        "original_runtime", "registry_match", "state_match", "delivered", "rejected", "connection_present", "disconnected",
        "job_deadline", "ready_deadline", "sampled_at", "cached_result_sha256", "inspection_fingerprint"}
    if (full["before"]["runtime_job"] is not None or type(cached) is not dict or set(cached) != fields
            or any(type(cached[key]) is not type(terminal[key]) or cached[key] != terminal[key]
                   for key in ("job_id", "request_id", "kind", "state", "phase", "revision"))
            or cached["method"] != "jobs._inspection_turn"
            or any(cached[key] is not True for key in ("driver_retired", "ready_record_present", "original_runtime",
                "registry_match", "state_match", "delivered", "connection_present"))
            or cached["rejected"] is not False or cached["disconnected"] is not False
            or not all(_inspection_clock(cached[key]) for key in ("job_deadline", "ready_deadline", "sampled_at"))):
        return False
    first, listed = full["timings"][0], full["timings"][-2]
    sample = full["after"]["measurement"]
    digest = hashlib.sha256(json.dumps(terminal["result"], sort_keys=True, ensure_ascii=True,
                                     allow_nan=False, separators=(",", ":")).encode("ascii")).hexdigest()
    return (cached["cached_result_sha256"] == digest
            and cached["inspection_fingerprint"] == terminal["result"]["inspection_fingerprint"]
            and first["sent_at"] + 300. <= cached["job_deadline"] <= first["received_at"] + 300.
            and full["timings"][-2]["sent_at"] < cached["ready_deadline"] == cached["job_deadline"]
            and cached["sampled_at"] < cached["job_deadline"]
            and sample["started_at"] <= cached["sampled_at"] <= sample["ended_at"]
            and listed["received_at"] <= sample["started_at"])


def _inspection_result(result, before):
    fields = {"schema", "policy", "object_name", "mesh_name", "attribute_names", "time_limit_seconds", "plan",
        "inspection_status", "inspection_fingerprint", "protected_logical_scope_sha256", "checkpoint_roles",
        "write_authorized", "native_calls_preemptible", "transient_intervening_edits_detectable",
        "edits_before_first_observation_detectable", "writer_handoff_supported", "physical_read_effects",
        "undo_boundary_created", "project_saved", "native_functional_qualified", "publicly_registered",
        "cached_at_completion", "native_state_revalidated", "permission_values_revalidated"}
    if (type(result) is not dict or set(result) != fields or result["schema"] != "mesh_storage_inspection_v1"
            or result["policy"] != "B2_PHASED_COHERENT_READ_ONLY_V1" or result["inspection_status"] != "COHERENT"
            or result["object_name"] != before["object_identity"][0] or result["mesh_name"] != before["mesh_identity"][0]
            or result["attribute_names"] != [".uv_select_face", "UVSingle"]
            or type(result["time_limit_seconds"]) is not float or result["time_limit_seconds"] != 300.
            or not all(_inspection_hex(result[name]) for name in ("inspection_fingerprint", "protected_logical_scope_sha256"))):
        return False
    flags = {"write_authorized": False, "native_calls_preemptible": False, "transient_intervening_edits_detectable": False,
        "edits_before_first_observation_detectable": False, "writer_handoff_supported": False, "undo_boundary_created": False,
        "project_saved": False, "native_functional_qualified": False, "publicly_registered": False,
        "cached_at_completion": True, "native_state_revalidated": False, "permission_values_revalidated": False}
    if any(result[name] is not expected for name, expected in flags.items()):
        return False
    if not _inspection_equal(result["physical_read_effects"],
            {"ARRAY_COW_or_tagging_possible": True, "image_buffer_cache_changes_possible": True}):
        return False
    roles = result["checkpoint_roles"]
    if (type(roles) is not dict or set(roles) != {"profile", "initial_roles", "before_readback", "after_readback",
            "native_push_completed", "after_readback_measured", "protected_scope_sha256",
            "foreign_previous_owner_supported", "physical_cache_passivity_claimed"}
            or roles["profile"] != "B2_EXACT_CHECKPOINT_WEAK_ROLE_V1" or roles["after_readback"] is not None
            or roles["protected_scope_sha256"] != result["protected_logical_scope_sha256"]
            or any(roles[key] is not False for key in ("native_push_completed", "after_readback_measured",
                "foreign_previous_owner_supported", "physical_cache_passivity_claimed"))):
        return False
    plan = result["plan"]
    if (type(plan) is not dict or set(plan) != {"schema", "build_hash", "fingerprint", "metadata", "targets", "start_admitted",
            "resource_facts", "SINGLE_pre_value_hash_available", "native_entries", "stage_B_registered",
            "dependency_protection_checkpoint_authority"} or plan["schema"] != "mesh_storage_preparation_plan_v1"
            or plan["build_hash"] != "d13f752e3b9c" or not _inspection_hex(plan["fingerprint"])
            or plan["start_admitted"] is not True or plan["SINGLE_pre_value_hash_available"] is not False
            or type(plan["native_entries"]) is not int or plan["native_entries"] != 0 or plan["stage_B_registered"] is not False
            or plan["dependency_protection_checkpoint_authority"] != "CALLER_SOURCE_QUALIFIED_GATE_REQUIRED"):
        return False
    metadata = plan["metadata"]
    if type(metadata) is not dict or set(metadata) != {"object", "mesh", "database_identity", "counts", "uv_roles", "attributes"}:
        return False
    for key, kind in (("object", "Object"), ("mesh", "Mesh")):
        rows = metadata[key]
        identity = before[key+"_identity"]
        expected = [["kind", kind], ["name", identity[0]], ["pointer", format(identity[2], "x")], ["session_uid", str(identity[1])]]
        if not _inspection_equal(rows, expected):
            return False
    targets = plan["targets"]
    if type(targets) is not list or len(targets) != 2:
        return False
    for target, row in zip(targets, before["selected_storage"], strict=True):
        if (type(target) is not dict or set(target) != {"name", "action", "header"}
                or target["name"] != row[0] or target["action"] != "MATERIALIZE_SINGLE"
                or type(target["header"]) is not list or len(target["header"]) != 9
                or target["header"][:3] != row[:3] or target["header"][5:7] != row[3:5]
                or type(target["header"][6]) is not int or not all(_inspection_hex(value) for value in target["header"][7:])):
            return False
    rows = metadata["attributes"]
    if (type(metadata["database_identity"]) is not str or not 1 <= len(metadata["database_identity"]) <= 16
            or any(char not in "0123456789abcdef" for char in metadata["database_identity"])
            or int(metadata["database_identity"], 16) == 0
            or not _inspection_equal(metadata["counts"], [["vertices", 3], ["edges", 3], ["polygons", 1], ["loops", 3]])
            or not _inspection_equal(metadata["uv_roles"], before["uv_roles"])
            or type(rows) is not list or not 2 <= len(rows) <= 32):
        return False
    headers = {}
    classes = {"BOOLEAN": ("BoolAttribute", "BoolAttributeValue"), "FLOAT2": ("Float2Attribute", "Float2AttributeValue"),
        "FLOAT_VECTOR": ("FloatVectorAttribute", "FloatVectorAttributeValue"), "INT": ("IntAttribute", "IntAttributeValue"),
        "INT32_2D": ("Int2Attribute", "Int2AttributeValue")}
    for row in rows:
        if (type(row) is not list or len(row) != 9 or any(type(value) is not str or not 1 <= len(value) <= 63 for value in row[:6])
                or row[0] in headers or type(row[6]) is not int or not 0 <= row[6] <= 131072
                or not all(_inspection_hex(value) for value in row[7:]) or row[2] not in classes
                or not _inspection_equal(row[3:5], list(classes[row[2]]))):
            return False
        headers[row[0]] = row
    supplied = sorted([[*row[:3], *row[5:7]] for row in rows])
    expected = sorted([*before["selected_storage"], *before["protected"]["unselected_attribute_headers"]])
    if not _inspection_equal(supplied, expected) or any(not _inspection_equal(target["header"], headers[target["name"]]) for target in targets):
        return False
    plan_digest = hashlib.sha256(json.dumps([metadata, [[row["name"], row["action"]] for row in targets]],
        sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")).hexdigest()
    if plan["fingerprint"] != plan_digest:
        return False
    resources = plan["resource_facts"]
    payload = sum(row[4] * (8 if row[2] == "FLOAT2" else 1) for row in before["selected_storage"])
    required = 64*1024**2 + 3*payload + 512*sum(row[4] for row in before["selected_storage"])
    invalid_resources = (type(resources) is not dict or set(resources) != {"known_array_payload_bytes", "required_available_memory_bytes",
            "required_preparation_memory_bytes", "available_memory_bytes", "available_memory_measurement_scope",
            "reserved_for_other_work_bytes", "admitted", "resources_reserved", "hard_total_memory_bound", "native_OOM_survival", "native_calls_preemptible"}
            or any(type(resources[key]) is not int or resources[key] != value for key, value in {
                "known_array_payload_bytes": payload, "required_available_memory_bytes": required,
                "required_preparation_memory_bytes": required, "reserved_for_other_work_bytes": 0}.items())
            or type(resources["available_memory_bytes"]) is not int or resources["available_memory_bytes"] < required
            or resources["available_memory_measurement_scope"] != "INITIAL_CALL_ARGUMENT_SNAPSHOT"
            or resources["native_OOM_survival"] != "UNPROVEN" or resources["admitted"] is not True
            or any(resources[key] is not False for key in ("resources_reserved", "hard_total_memory_bound", "native_calls_preemptible")))
    return not invalid_resources


def _inspection_roles(result, context):
    roles = result["checkpoint_roles"]
    def token(owner):
        return [None, None] if owner is None else [owner[2], owner[1]]
    scene, active, particle = token(context["scene"]), token(context["active"]), token(context["particle_object"])
    initial = [context["scene_self_references"], particle]
    readback = roles["before_readback"]
    if (not _inspection_equal(roles["initial_roles"], initial) or type(readback) is not dict
            or set(readback) != {"owners", "scene_self_references", "particle_object", "scene_object_references",
                "structural_memberships", "weak_object_references"}):
        return False
    owners = readback["owners"]
    weak = int(initial[0] == 1 and particle == active)
    return (type(owners) is list and len(owners) == 5 and _inspection_equal(owners[0], scene)
            and _inspection_equal(owners[3], scene) and _inspection_equal(owners[4], active)
            and all(type(value) is int and 0 < value < 2**64 for value in owners[1:3])
            and _inspection_equal(readback["particle_object"], particle)
            and all(type(readback[key]) is int and readback[key] == expected for key, expected in {
                "scene_self_references": initial[0], "scene_object_references": 1+weak,
                "structural_memberships": 1, "weak_object_references": weak}.items()))


def _inspection_fence(value, full):
    fields = {"blender_version", "addon_version", "connection_status", "server", "filepath", "mode", "scene", "active_object",
              "enabled_permissions", "permissions", "enabled_toolsets", "jobs", "agent"}
    if (type(value) is not dict or set(value) != fields or value["blender_version"] != full["blender_version"]
            or value["addon_version"] != "0.9.0"
            or value["connection_status"] != "connected" or value["filepath"] != "" or value["mode"] != "OBJECT"
            or value["scene"] != full["after"]["context"]["scene"][0]
            or value["active_object"] != full["after"]["snapshot"]["object_identity"][0]):
        return False
    terminal = full["terminal"]
    expected_job = {key: terminal[key] for key in ("job_id", "kind", "state", "terminal", "revision", "progress")}
    if not _inspection_equal(value["jobs"], {"active": None, "last_terminal": expected_job, "max_active": 1,
                                           "terminal_history_limit": 32, "durable": False}):
        return False
    server, permissions, agent = value["server"], value["permissions"], value["agent"]
    grants = {"INSPECT_SCENE": True, "CAPTURE_VIEWPORT": True, "TRANSFORM_OBJECTS": True, "EDIT_MESH": True,
        "EDIT_MATERIALS": True, "EDIT_ANIMATION": True, "EDIT_SCENE": False, "EDIT_RENDER": True,
        "DELETE_OBJECTS": False, "EXECUTE_PYTHON": False, "ACCESS_EXTERNAL_FILES": False, "SAVE_PROJECT": False,
        "NATIVE_SAVE_EFFECTS": False}
    invalid_fence = (type(server) is not dict or set(server) != {"running", "host", "port", "connected_clients"}
            or server["running"] is not True or server["host"] != "127.0.0.1"
            or type(server["port"]) is not int or not 1 <= server["port"] <= 65535
            or type(server["connected_clients"]) is not int or server["connected_clients"] != 1
            or not _inspection_equal(permissions, grants)
            or type(value["enabled_permissions"]) is not list or any(type(name) is not str for name in value["enabled_permissions"])
            or len(set(value["enabled_permissions"])) != len(value["enabled_permissions"])
            or not _inspection_equal(sorted(value["enabled_permissions"]), sorted(key for key, flag in permissions.items() if flag))
            or not _inspection_equal(value["enabled_toolsets"], ["core", "geometry"])
            or type(agent) is not dict or set(agent) != {"paused", "emergency_stopped", "current_task", "current_method", "is_executing", "undo_group", "recovery"}
            or agent["paused"] is not False or agent["emergency_stopped"] is not False
            or agent["current_method"] != "bridge.status" or agent["is_executing"] is not True or agent["undo_group"] is not None
            or type(agent["current_task"]) is not str or type(agent["recovery"]) is not dict)
    if invalid_fence:
        return False
    recovery = agent["recovery"]
    fields = {"native_undo_steps", "native_undo_memory_limit_mb", "global_undo_enabled", "mode", "tracked_operation_count",
        "expired_operations_pruned_since_clear", "tracked_checkpoint_count", "expired_checkpoint_count", "latest_operation",
        "checkpoints", "checkpoints_truncated", "native_history_introspection", "availability_guaranteed", "verification_required", "warning"}
    return (set(recovery) == fields and type(recovery["native_undo_steps"]) is int and recovery["native_undo_steps"] == 256
            and type(recovery["native_undo_memory_limit_mb"]) is int and 0 <= recovery["native_undo_memory_limit_mb"] <= 2**31-1
            and recovery["mode"] == "OBJECT" and recovery["global_undo_enabled"] is True
            and all(type(recovery[key]) is int and recovery[key] == 0 for key in ("tracked_operation_count",
                "expired_operations_pruned_since_clear", "tracked_checkpoint_count", "expired_checkpoint_count"))
            and recovery["latest_operation"] is None and recovery["checkpoints"] == []
            and all(recovery[key] is False for key in ("checkpoints_truncated", "native_history_introspection", "availability_guaranteed"))
            and recovery["verification_required"] is True and recovery["warning"] ==
                "Only bridge pushes are counted. Manual/operator snapshots, memory limits, preference changes and editor stacks can expire other targets. Global recovery can undo interleaved work; labels are not durable backups.")


def _inspection_wire(full):
    requests, timings = full["requests"], full["timings"]
    if (type(requests) is not list or not 7 <= len(requests) <= 256 or type(timings) is not list or len(timings) != len(requests)):
        return False
    accepted = requests[0]["response"]["result"]
    job_id, owner_id = accepted.get("job_id"), requests[0]["request"]["id"]
    if (type(job_id) is not str or len(job_id) != 36 or not job_id.startswith("job_")
            or any(char not in "0123456789abcdef" for char in job_id[4:])
            or not _inspection_summary(accepted, job_id, owner_id, accepted=True)
            or accepted["label"] != "Inspect mesh attribute storage " + full["before"]["snapshot"]["mesh_identity"][0]):
        return False
    expected_params = {"object_name": full["before"]["snapshot"]["object_identity"][0],
        "mesh_name": full["before"]["snapshot"]["mesh_identity"][0], "attribute_names": [".uv_select_face", "UVSingle"],
        "time_limit_seconds": 300.}
    seen, completed, previous, terminal_seen = set(), [0], 0., False
    for index, (exchange, timing) in enumerate(zip(requests, timings, strict=True)):
        if type(exchange) is not dict or set(exchange) != {"request", "response"}:
            return False
        request, response = exchange["request"], exchange["response"]
        if (type(request) is not dict or set(request) != {"id", "method", "params", "protocol_version", "timeout_ms"}
                or type(request["id"]) is not str or not 1 <= len(request["id"]) <= 128 or request["id"] in seen
                or request["protocol_version"] != "1.0" or type(request["timeout_ms"]) is not int or request["timeout_ms"] != 60000
                or type(response) is not dict or set(response) != {"id", "ok", "result", "timestamp", "protocol_version"}
                or response["id"] != request["id"] or response["ok"] is not True or response["protocol_version"] != "1.0"
                or type(response["timestamp"]) is not str or not 1 <= len(response["timestamp"]) <= 128):
            return False
        seen.add(request["id"])
        stage = "start" if index == 0 else "repeat" if index == len(requests)-3 else "list" if index == len(requests)-2 else "fence" if index == len(requests)-1 else "inspect"
        method = "mesh.attribute_storage_prepare_inspection_start" if stage == "start" else "jobs.list" if stage == "list" else "bridge.status" if stage == "fence" else "jobs.inspect"
        params = expected_params if stage == "start" else {} if stage in {"list", "fence"} else {"job_id": job_id}
        if (request["method"] != method or not _inspection_equal(request["params"], params)
                or type(timing) is not dict or set(timing) != {"stage", "request_id", "sent_at", "received_at", "cpu_seconds"}
                or timing["stage"] != stage or timing["request_id"] != request["id"]
                or not all(_inspection_clock(timing[key]) for key in ("sent_at", "received_at", "cpu_seconds"))
                or not previous <= timing["sent_at"] <= timing["received_at"] or timing["received_at"]-timing["sent_at"] > 60):
            return False
        previous = timing["received_at"]
        if stage == "inspect":
            summary = response["result"]
            if terminal_seen or not _inspection_summary(summary, job_id, owner_id):
                return False
            count = summary["progress"]["completed"]
            if (count < completed[-1] or count > completed[-1]+1 or summary["revision"] != count+1
                    or any(summary[key] != accepted[key] for key in ("label", "created_at"))):
                return False
            if count != completed[-1]:
                completed.append(count)
            terminal_seen = summary["terminal"]
            if terminal_seen and not _inspection_equal(summary, full["terminal"]):
                return False
        elif stage == "repeat" and (not terminal_seen or not _inspection_equal(response["result"], full["repeat"])
                                    or not _inspection_equal(full["repeat"], full["terminal"])):
            return False
        elif stage == "list":
            if not _inspection_equal(response["result"], full["listed"]):
                return False
            listing = full["listed"]
            if (type(listing) is not dict or set(listing) != {"jobs", "total", "truncated", "max_active", "terminal_history_limit",
                    "durable", "retained_native_saves", "retained_native_save_limit"}
                    or not _inspection_equal(listing["jobs"], [full["terminal"]]) or type(listing["total"]) is not int
                    or listing["total"] != 1 or listing["truncated"] is not False or listing["durable"] is not False
                    or type(listing["max_active"]) is not int or listing["max_active"] != 1
                    or listing["retained_native_saves"] != [] or type(listing["retained_native_save_limit"]) is not int
                    or listing["retained_native_save_limit"] != 4 or type(listing["terminal_history_limit"]) is not int
                    or listing["terminal_history_limit"] != 32):
                return False
        elif stage == "fence" and not _inspection_fence(response["result"], full):
            return False
    return (completed == [0, 1, 2, 3] and terminal_seen
            and _inspection_result(full["terminal"]["result"], full["before"]["snapshot"])
            and _inspection_roles(full["terminal"]["result"], full["before"]["context"]))


def _mesh_storage_inspection_matches(payload, temporary, process_instance, pid, binary, sources, display):
    """Cold validation of actual retained read-only success evidence."""
    result = {"passed": False, "path": str(temporary / MESH_STORAGE_INSPECTION_REPORT)}
    try:
        common = {"schema", "completed", "phase", "process_id", "process_instance", "source_build", "blender_version",
                  "binary_sha256", "source_snapshot_sha256"}
        if not _inspection_plain(payload) or type(payload) is not dict or set(payload) != common | {"full_receipt"}:
            raise ValueError("INSPECTION_MARKER_SHAPE")
        expected = {"schema": MESH_STORAGE_INSPECTION_PROFILE, "completed": True, "phase": "success", "process_id": pid,
                    "process_instance": process_instance, "source_build": "d13f752e3b9c", "binary_sha256": binary["sha256"]}
        if (type(pid) is not int or pid <= 0 or binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256
                or any(type(payload[key]) is not type(value) or payload[key] != value for key, value in expected.items())
                or payload["blender_version"] not in {"5.2.2", "5.2.2 LTS"}
                or payload["full_receipt"].get("path") != str(temporary / MESH_STORAGE_INSPECTION_REPORT)):
            raise ValueError("INSPECTION_PROCESS_BINDING")
        report_path = temporary / MESH_STORAGE_INSPECTION_REPORT
        report_before = report_path.lstat()
        if not stat.S_ISREG(report_before.st_mode) or report_before.st_uid != os.getuid() or report_before.st_nlink != 1:
            raise ValueError("INSPECTION_RECEIPT_LINKS")
        raw = _domain_binding(payload["full_receipt"], temporary, DOMAIN_MAX_REPORT, capture=True)
        report_after = report_path.lstat()
        if not stat.S_ISREG(report_after.st_mode) or report_after.st_uid != os.getuid() or report_after.st_nlink != 1:
            raise ValueError("INSPECTION_RECEIPT_LINKS")
        full = _native_save_json(raw)
        extras = {"runtime_nonce", "runtime_identity", "helper_sha256", "source_fingerprints", "private_display", "transport",
            "limitations", "requests", "timings", "terminal", "repeat", "listed", "worker_before", "worker_after", "before", "after",
            "extra_response_check", "setup_oracle_values", "process_cpu_seconds_at_completion", "seconds", "hardware"}
        if (not _inspection_plain(full) or type(full) is not dict or set(full) != common | extras
                or any(type(full[key]) is not type(payload[key]) or full[key] != payload[key] for key in common)
                or full["helper_sha256"] != MESH_STORAGE_HELPER_SHA256
                or not _inspection_equal(full["source_fingerprints"], sources) or _mesh_storage_sources() != sources
                or full["source_snapshot_sha256"] != hashlib.sha256(json.dumps(sources, sort_keys=True, ensure_ascii=True,
                    allow_nan=False, separators=(",", ":")).encode("ascii")).hexdigest()
                or not _inspection_equal(full["private_display"], display) or _domain_display() != display
                or not _inspection_equal(full["limitations"], MESH_STORAGE_INSPECTION_LIMITS)
                or not _inspection_equal(full["transport"], {"host": "127.0.0.1", "socket_json": True,
                    "runtime_timer_queue": True, "direct_dispatch": False, "manual_scheduler_drain": False})
                or not all(_inspection_clock(full[key]) for key in ("seconds", "process_cpu_seconds_at_completion"))
                or not 0 < full["seconds"] <= 300 or not _inspection_hooks(full["worker_before"]) or not _inspection_hooks(full["worker_after"])):
            raise ValueError("INSPECTION_SOURCE_OR_SCOPE")
        identity = full["runtime_identity"]
        if (type(identity) is not dict or set(identity) != {"process_instance", "runtime_id", "registry_id", "queue_id"}
                or identity["process_instance"] != process_instance
                or any(type(identity[key]) is not int or not 0 < identity[key] < 2**64 for key in ("runtime_id", "registry_id", "queue_id"))
                or len({identity[key] for key in ("runtime_id", "registry_id", "queue_id")}) != 3
                or full["runtime_nonce"] != hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]):
            raise ValueError("INSPECTION_RUNTIME_IDENTITY")
        hardware = full["hardware"]
        if (type(hardware) is not dict or set(hardware) != {"system", "machine", "processor", "cpu_count"}
                or hardware["system"] != "Linux" or hardware["machine"] not in {"x86_64", "AMD64"}
                or type(hardware["processor"]) is not str or len(hardware["processor"]) > 255
                or type(hardware["cpu_count"]) is not int or not 1 <= hardware["cpu_count"] <= 65536):
            raise ValueError("INSPECTION_HARDWARE")
        before, after = full["before"], full["after"]
        sample_keys = {"snapshot", "context", "boundaries", "hooks", "settled", "payloads", "memory", "runtime_job", "measurement"}
        settled = {"job_active": False, "is_executing": False, "executing_mutators": 0, "executor_frame_present": False, "main_thread": True}
        for sample in (before, after):
            if (type(sample) is not dict or set(sample) != sample_keys or not _mesh_storage_snapshot(sample["snapshot"])
                    or any(row[3] != "SINGLE" for row in sample["snapshot"]["selected_storage"])
                    or sample["snapshot"]["selected_values"] != {} or not _inspection_hooks(sample["hooks"])
                    or not _inspection_equal(sample["settled"], settled) or not _inspection_sample_details(sample)):
                raise ValueError("INSPECTION_NATIVE_SAMPLE")
            measurement = sample["measurement"]
            if (type(measurement) is not dict or set(measurement) != {"started_at", "ended_at", "cpu_seconds"}
                    or not all(_inspection_clock(value) for value in measurement.values())
                    or measurement["started_at"] > measurement["ended_at"]):
                raise ValueError("INSPECTION_SAMPLE_CLOCK")
        if (not _inspection_equal(before["snapshot"], after["snapshot"])
                or not _inspection_equal(before["context"], after["context"])
                or not _inspection_equal(before["boundaries"], after["boundaries"])):
            raise ValueError("INSPECTION_PRESERVATION")
        if not _inspection_wire(full):
            raise ValueError("INSPECTION_WIRE_OR_READY")
        extra = full["extra_response_check"]
        if (type(extra) is not dict or set(extra) != {"outcome", "bytes", "started_at", "ended_at", "timeout_seconds"}
                or extra["outcome"] not in {"SOCKET_TIMEOUT", "EMPTY_READ"} or type(extra["bytes"]) is not int or extra["bytes"] != 0
                or not all(_inspection_clock(extra[key]) for key in ("started_at", "ended_at", "timeout_seconds"))
                or extra["timeout_seconds"] != .1 or not full["timings"][-1]["received_at"] <= extra["started_at"] <= extra["ended_at"]
                or after["measurement"]["ended_at"] > full["timings"][-1]["sent_at"]
                or (extra["outcome"] == "SOCKET_TIMEOUT" and extra["ended_at"]-extra["started_at"] < .095)
                or not before["measurement"]["ended_at"] <= full["timings"][0]["sent_at"]
                or extra["ended_at"]-before["measurement"]["started_at"] > full["seconds"]
                or sum(row["cpu_seconds"] for row in full["timings"]) + before["measurement"]["cpu_seconds"] + after["measurement"]["cpu_seconds"] > full["process_cpu_seconds_at_completion"]
                or not _inspection_cached_job(full)):
            raise ValueError("INSPECTION_CLOCK_OR_CACHED_JOB")
        oracle = {".uv_select_face": [True], "UVSingle": [["0000803e", "000000bf"]]*3}
        if not _inspection_equal(full["setup_oracle_values"], oracle):
            raise ValueError("INSPECTION_SETUP_ORACLE")
        result.update(passed=True, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError, RecursionError, UnicodeError) as error:
        result["reason"] = str(error) if isinstance(error, ValueError) else "INSPECTION_RECEIPT_INVALID"
    return result


def _inspection_cost_catalog():
    import ast
    specs = (("driver_advance", "tools/_mesh_storage_inspection.py", "MeshStorageInspectionDriver", "_advance"),
        ("gate_pure", "mesh_storage_source.py", "Gate", "pure"),
        ("source_seal_verify", "mesh_storage_source.py", "SourceSeal", "verify"),
        ("metadata_plan", "mesh_storage_prepare.py", None, "build_plan"),
        ("collection_bindings", "mesh_storage_prepare.py", None, "qualify_collection_bindings"),
        ("checkpoint_roles_init", "mesh_storage_source.py", "CheckpointRoles", "__init__"))
    result = []
    for label, relative, owner, name in specs:
        path = ROOT / "addon/blender_codex_bridge" / relative
        tree = ast.parse(path.read_bytes())
        body = tree.body if owner is None else next(node.body for node in tree.body if type(node) is ast.ClassDef and node.name == owner)
        function = next(node for node in body if type(node) is ast.FunctionDef and node.name == name)
        result.append({"label": label, "filename": str(path.relative_to(ROOT)),
                       "first_line": function.decorator_list[0].lineno if function.decorator_list else function.lineno})
    return result


def _inspection_cost_aggregates(value, seconds):
    fields = {"backend", "tool_id", "global_event_mask", "local_event_mask", "restored", "callbacks_restored",
        "local_events_restored", "tool_freed", "exact_unwind_observed", "unknown_open_elapsed_is_upper_bound",
        "observed_timings_are_untraced_timings", "overlapping_inclusive_times_may_not_be_added", "product_success_qualified",
        "call_limit", "catalog", "aggregates"}
    if (type(value) is not dict or set(value) != fields
            or value["backend"] != "sys.monitoring.local_START_RETURN.aggregate"
            or any(type(value[key]) is not int or value[key] != expected for key, expected in
                {"tool_id": 4, "global_event_mask": 0, "local_event_mask": 5, "call_limit": 131072}.items())
            or any(value[key] is not True for key in ("restored", "callbacks_restored", "local_events_restored", "tool_freed",
                "unknown_open_elapsed_is_upper_bound", "overlapping_inclusive_times_may_not_be_added"))
            or any(value[key] is not False for key in ("exact_unwind_observed", "observed_timings_are_untraced_timings", "product_success_qualified"))):
        return False
    catalog, expected = value["catalog"], _inspection_cost_catalog()
    if type(catalog) is not list or len(catalog) != 6:
        return False
    for row, source in zip(catalog, expected, strict=True):
        if (type(row) is not dict or set(row) != set(source) | {"code_sha256"}
                or any(type(row[key]) is not type(item) or row[key] != item for key, item in source.items())
                or not _inspection_hex(row["code_sha256"])):
            return False
    aggregates = value["aggregates"]
    if type(aggregates) is not dict or set(aggregates) != set(MESH_STORAGE_COST_LABELS):
        return False
    count = 0
    for row in aggregates.values():
        fields = {"started", "returned", "completed", "completed_inclusive_seconds", "maximum_completed_seconds",
                  "unknown", "unknown_elapsed_upper_bound_seconds", "maximum_unknown_upper_bound_seconds"}
        if (type(row) is not dict or set(row) != fields
                or any(type(row[key]) is not int or not 0 <= row[key] <= 131072 for key in ("started", "returned", "completed", "unknown"))
                or not 0 <= row["completed"] <= row["returned"] <= row["started"]
                or row["completed"]+row["unknown"] != row["started"]):
            return False
        for prefix, number, total in (("completed", "completed", "completed_inclusive_seconds"),
                                      ("unknown", "unknown", "unknown_elapsed_upper_bound_seconds")):
            maximum = "maximum_completed_seconds" if prefix == "completed" else "maximum_unknown_upper_bound_seconds"
            if (not _inspection_clock(row[total]) or not _inspection_clock(row[maximum])
                    or not 0 <= row[maximum] <= min(row[total], seconds)):
                return False
            maximum_sum = row[number]*row[maximum]
            # Nonnegative incremental addition can round once per observation.
            roundoff = row[number]*math.ulp(maximum_sum)
            if (row[total] > row[number]*seconds or row[total] > maximum_sum+roundoff
                    or (row[number] == 1 and row[total] != row[maximum])
                    or (row[number] == 0 and (row[total] != 0. or row[maximum] != 0.))):
                return False
        count += row["started"]
    return (count <= 131072 and all(aggregates[key]["started"] > 0 for key in ("driver_advance", "gate_pure", "source_seal_verify")))


def _inspection_cost_cache(cache, stage, job_id, owner, first):
    fields = {"available", "stage", "non_atomic_cached_only", "sampled_at", "cpu_seconds", "truncated",
              "origin_identity_valid", "job", "active_is_expected", "inspection_turns", "pending_queue"}
    if (type(cache) is not dict or set(cache) != fields or cache["available"] is not True or cache["stage"] != stage
            or cache["non_atomic_cached_only"] is not True or cache["origin_identity_valid"] is not True
            or any(type(cache[key]) is not bool for key in ("truncated", "active_is_expected"))
            or not all(_inspection_clock(cache[key]) for key in ("sampled_at", "cpu_seconds"))):
        return False
    job = cache["job"]
    fields = {"job_id", "request_id", "method", "kind", "state", "phase", "revision", "progress", "error", "deadline",
              "in_tick", "in_commit", "native_reads_started", "cancel_reason", "ready_valid", "invalidated_reason"}
    if (type(job) is not dict or set(job) != fields or job["job_id"] != job_id or job["request_id"] != owner
            or job["kind"] != "mesh.attribute_storage_inspection" or job["method"] != "jobs._inspection_turn"
            or job["state"] not in {"QUEUED", "RUNNING", "PAUSED", "SUCCEEDED", "FAILED", "CANCELLED"}
            or job["phase"] not in {"inspection_plan", "inspection_capture", "inspection_seal", "inspection_complete"}
            or type(job["revision"]) is not int or not 1 <= job["revision"] <= 32
            or any(type(job[key]) is not bool for key in ("in_tick", "in_commit", "native_reads_started", "ready_valid"))
            or any(type(job[key]) is not str or len(job[key]) > 4096 for key in ("cancel_reason", "invalidated_reason"))
            or not _inspection_clock(job["deadline"]) or not first["sent_at"]+300 <= job["deadline"] <= first["received_at"]+300):
        return False
    progress = job["progress"]
    if (type(progress) is not dict or set(progress) != {"phase", "completed", "total"}
            or type(progress["phase"]) is not str or len(progress["phase"]) > 128
            or type(progress["completed"]) is not int or not 0 <= progress["completed"] <= 3
            or type(progress["total"]) is not int or progress["total"] != 3):
        return False
    error = job["error"]
    if error is not None and (type(error) is not dict or set(error) != {"code", "message", "context"}
            or type(error["code"]) is not str or not 1 <= len(error["code"]) <= 64
            or type(error["message"]) is not str or len(error["message"]) > 512 or type(error["context"]) is not dict):
        return False
    turns, queued = cache["inspection_turns"], cache["pending_queue"]
    if type(turns) is not list or len(turns) > 2 or type(queued) is not list or len(queued) > 8:
        return False
    for row in turns:
        if (type(row) is not dict or set(row) != {"phase", "revision", "used", "check_only", "inspection_deadline", "belongs_to_expected_job"}
                or row["phase"] not in {"inspection_plan", "inspection_capture", "inspection_seal", "inspection_complete"}
                or type(row["revision"]) is not int or not 1 <= row["revision"] <= 32
                or any(type(row[key]) is not bool for key in ("used", "check_only", "belongs_to_expected_job"))
                or not _inspection_clock(row["inspection_deadline"]) or not first["sent_at"] <= row["inspection_deadline"] <= job["deadline"]):
            return False
    for row in queued:
        if (type(row) is not dict or set(row) != {"request_id", "method", "deadline", "state", "stop_requested", "response_present"}
                or type(row["request_id"]) is not str or not 1 <= len(row["request_id"]) <= 128
                or type(row["method"]) is not str or not 1 <= len(row["method"]) <= 128
                or row["state"] not in {"pending", "running", "completed", "cancelled"}
                or not _inspection_clock(row["deadline"]) or any(type(row[key]) is not bool for key in ("stop_requested", "response_present"))):
            return False
    return True


def _inspection_cost_attempt(full):
    partial, failed = full["partial"], full["failed_call"]
    required = {"before", "worker_before", "requests", "timings", "terminal"}
    allowed = required | {"repeat", "listed", "after", "extra_response_check", "worker_after", "setup_oracle_values"}
    if type(partial) is not dict or not required <= set(partial) <= allowed:
        return False
    if full["failure"] is None:
        return (failed is None and full["worker_cached"] is None and full["supervisor_cached"] is None
                and _inspection_wire({**partial, "blender_version": full["blender_version"]}))
    if (type(full["failure"]) is not str or not 1 <= len(full["failure"]) <= 16384
            or type(failed) is not dict or set(failed) != {"stage", "method", "sent_at", "failed_at", "cpu_seconds",
                "response_received", "exception_type", "request_id"}
            or failed["stage"] != "inspect" or failed["method"] != "jobs.inspect"
            or failed["exception_type"] != "TimeoutError" or failed["response_received"] is not False
            or not all(_inspection_clock(failed[key]) for key in ("sent_at", "failed_at", "cpu_seconds"))
            or not 0 <= failed["failed_at"]-failed["sent_at"] <= 65):
        return False
    requests, timings = partial["requests"], partial["timings"]
    if (type(requests) is not list or not 2 <= len(requests) <= 256 or type(timings) is not list
            or len(timings) != len(requests)-1 or partial["terminal"] is not None):
        return False
    accepted, seen, previous = requests[0]["response"]["result"], set(), 0.
    owner = requests[0]["request"]["id"]
    job_id = accepted["job_id"]
    if (type(job_id) is not str or len(job_id) != 36 or not job_id.startswith("job_")
            or any(char not in "0123456789abcdef" for char in job_id[4:])
            or not _inspection_summary(accepted, job_id, owner, accepted=True)):
        return False
    params = {"object_name": partial["before"]["snapshot"]["object_identity"][0],
        "mesh_name": partial["before"]["snapshot"]["mesh_identity"][0], "attribute_names": [".uv_select_face", "UVSingle"], "time_limit_seconds": 300.}
    for index, row in enumerate(requests):
        if type(row) is not dict or set(row) != {"request", "response"}:
            return False
        request, response = row["request"], row["response"]
        if (type(request) is not dict or set(request) != {"id", "method", "params", "protocol_version", "timeout_ms"}
                or type(request["id"]) is not str or request["id"] in seen or not 1 <= len(request["id"]) <= 128
                or request["protocol_version"] != "1.0" or type(request["timeout_ms"]) is not int or request["timeout_ms"] != 60000
                or request["method"] != ("mesh.attribute_storage_prepare_inspection_start" if index == 0 else "jobs.inspect")
                or not _inspection_equal(request["params"], params if index == 0 else {"job_id": job_id})):
            return False
        seen.add(request["id"])
        if index == len(requests)-1:
            if response is not None or failed["request_id"] != request["id"] or not previous <= failed["sent_at"]:
                return False
            continue
        timing = timings[index]
        if (type(response) is not dict or set(response) != {"id", "ok", "result", "timestamp", "protocol_version"}
                or response["id"] != request["id"] or response["ok"] is not True or response["protocol_version"] != "1.0"
                or type(response["timestamp"]) is not str or not 1 <= len(response["timestamp"]) <= 128
                or type(timing) is not dict or set(timing) != {"stage", "request_id", "sent_at", "received_at", "cpu_seconds"}
                or timing["stage"] != ("start" if index == 0 else "inspect") or timing["request_id"] != request["id"]
                or not all(_inspection_clock(timing[key]) for key in ("sent_at", "received_at", "cpu_seconds"))
                or not previous <= timing["sent_at"] <= timing["received_at"] or timing["received_at"]-timing["sent_at"] > 60
                or (index and (not _inspection_summary(response["result"], job_id, owner) or response["result"]["terminal"]))):
            return False
        previous = timing["received_at"]
    for stage, cache in (("worker", full["worker_cached"]), ("supervisor", full["supervisor_cached"])):
        if not _inspection_cost_cache(cache, stage, job_id, owner, timings[0]):
            return False
    return (failed["failed_at"] <= full["worker_cached"]["sampled_at"] <= full["supervisor_cached"]["sampled_at"]
            and full["supervisor_cached"]["sampled_at"]-partial["before"]["measurement"]["started_at"] <= full["seconds"])


def _mesh_storage_cost_matches(payload, temporary, process_instance, pid, binary, sources, display):
    result = {"diagnostic_completed": False, "qualified": False, "path": str(temporary / MESH_STORAGE_COST_REPORT)}
    try:
        common = {"schema", "completed", "diagnostic_only", "phase", "process_id", "process_instance", "source_build",
                  "blender_version", "binary_sha256", "source_snapshot_sha256", "product_success_qualified"}
        if type(payload) is not dict or not _inspection_plain(payload) or set(payload) != common | {"full_receipt"}:
            raise ValueError("INSPECTION_COST_MARKER")
        expected = {"schema": MESH_STORAGE_COST_PROFILE, "completed": True, "diagnostic_only": True, "phase": "success",
                    "process_id": pid, "process_instance": process_instance, "source_build": "d13f752e3b9c",
                    "binary_sha256": binary["sha256"], "product_success_qualified": False}
        path = temporary / MESH_STORAGE_COST_REPORT
        if (type(pid) is not int or pid <= 0 or binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256
                or any(type(payload[key]) is not type(value) or payload[key] != value for key, value in expected.items())
                or payload["blender_version"] not in {"5.2.2", "5.2.2 LTS"} or payload["full_receipt"].get("path") != str(path)):
            raise ValueError("INSPECTION_COST_PROCESS")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1:
            raise ValueError("INSPECTION_COST_FILE")
        raw = _domain_binding(payload["full_receipt"], temporary, DOMAIN_MAX_REPORT, capture=True)
        after = path.lstat()
        if not stat.S_ISREG(after.st_mode) or after.st_uid != os.getuid() or after.st_nlink != 1:
            raise ValueError("INSPECTION_COST_FILE")
        full = _native_save_json(raw)
        extras = {"runtime_nonce", "runtime_identity", "helper_sha256", "source_fingerprints", "private_display", "transport",
            "failure", "secondary_failure", "failed_call", "worker_cached", "supervisor_cached", "partial", "cost_timing", "seconds"}
        if (type(full) is not dict or not _inspection_plain(full) or set(full) != common | extras
                or any(not _inspection_equal(full[key], payload[key]) for key in common)
                or full["helper_sha256"] != MESH_STORAGE_HELPER_SHA256 or full["secondary_failure"] is not None
                or not _inspection_equal(full["source_fingerprints"], sources) or _mesh_storage_sources() != sources
                or not _inspection_equal(full["private_display"], display) or _domain_display() != display
                or full["source_snapshot_sha256"] != hashlib.sha256(json.dumps(sources, sort_keys=True, ensure_ascii=True,
                    allow_nan=False, separators=(",", ":")).encode("ascii")).hexdigest()
                or not _inspection_equal(full["transport"], {"host": "127.0.0.1", "socket_json": True, "runtime_timer_queue": True,
                    "direct_dispatch": False, "manual_scheduler_drain": False})
                or not _inspection_clock(full["seconds"]) or not 0 < full["seconds"] <= 300
                or not _inspection_cost_aggregates(full["cost_timing"], full["seconds"])):
            raise ValueError("INSPECTION_COST_SOURCE_OR_COUNTERS")
        identity = full["runtime_identity"]
        if (type(identity) is not dict or set(identity) != {"process_instance", "runtime_id", "registry_id", "queue_id"}
                or identity["process_instance"] != process_instance
                or any(type(identity[key]) is not int or not 0 < identity[key] < 2**64 for key in ("runtime_id", "registry_id", "queue_id"))
                or len({identity[key] for key in ("runtime_id", "registry_id", "queue_id")}) != 3
                or full["runtime_nonce"] != hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]):
            raise ValueError("INSPECTION_COST_RUNTIME")
        sample = full["partial"]["before"]
        if (type(sample) is not dict or not _mesh_storage_snapshot(sample["snapshot"])
                or not _inspection_sample_details(sample) or not _inspection_hooks(sample["hooks"])
                or not _inspection_hooks(full["partial"]["worker_before"]) or not _inspection_cost_attempt(full)):
            raise ValueError("INSPECTION_COST_CACHED_ROUTE")
        result.update(diagnostic_completed=True, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                      outcome="TRANSPORT_TIMEOUT" if full["failure"] is not None else "OBSERVED_SUCCESS")
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError, RecursionError, UnicodeError, StopIteration) as error:
        result["reason"] = str(error) if isinstance(error, ValueError) else "INSPECTION_COST_RECEIPT_INVALID"
    return result


def _run_mesh_storage_cost(blender: Path, output: Path, timeout: int) -> dict:
    result = {"case": MESH_STORAGE_COST_CASE, "status": "failed", "diagnostic_only": True}
    try:
        display = _domain_display()
        executable = blender.resolve(strict=True)
        _raw, binary = _domain_regular(executable, executable.parent, 1024**3)
        if binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256:
            raise ValueError("Inspection cost diagnostic requires pinned5.2.2")
        sources = _mesh_storage_sources()
        bundle = output / f"{MESH_STORAGE_COST_CASE}-bundle"
        bundle.mkdir(mode=0o700)
        result = _run_process(executable, MESH_STORAGE_COST_CASE, output, timeout,
            phase="success", bundle=bundle, phase_marker=MESH_STORAGE_COST_MARKER,
            domain_binary=binary, domain_sources=sources, domain_display=display)
        _domain_binding(binary, executable.parent, 1024**3)
        if _mesh_storage_sources() != sources or _domain_display() != display:
            raise ValueError("Inspection cost diagnostic source or display changed")
    except (OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError, RecursionError):
        result["status"] = "failed"
        result["admission_error"] = "Inspection cost diagnostic admission refused"
    return result


def _run_mesh_storage_inspection(blender: Path, output: Path, timeout: int) -> dict:
    """One opt-in unobserved success probe, before the adverse native matrix."""
    started = time.monotonic()
    result = {"case": MESH_STORAGE_INSPECTION_CASE, "status": "failed",
              "script": CASES[MESH_STORAGE_INSPECTION_CASE][0], "qualification_scope": dict(MESH_STORAGE_INSPECTION_LIMITS)}
    try:
        display = _domain_display()
        executable = blender.resolve(strict=True)
        _raw, binary = _domain_regular(executable, executable.parent, 1024**3)
        if binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256:
            result["unsupported_binary"] = True
            raise ValueError("Phased inspection success requires the pinned 5.2.2 candidate")
        sources = _mesh_storage_sources()
        bundle = output / f"{MESH_STORAGE_INSPECTION_CASE}-bundle"
        bundle.mkdir(mode=0o700)
        result = _run_process(executable, MESH_STORAGE_INSPECTION_CASE, output, timeout,
            phase="success", bundle=bundle, phase_marker=MESH_STORAGE_INSPECTION_MARKER,
            domain_binary=binary, domain_sources=sources, domain_display=display)
        _domain_binding(binary, executable.parent, 1024**3)
        if _mesh_storage_sources() != sources or _domain_display() != display:
            raise ValueError("Phased inspection source, display or binary changed")
    except (OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError, RecursionError):
        result["status"] = "failed"
        result["admission_error"] = "Phased inspection success admission or retained evidence refused"
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def _run_mesh_storage_control(blender: Path, output: Path, timeout: int) -> dict:
    """One explicitly selected untraced diagnostic; never a qualification pass."""
    started = time.monotonic()
    result = {"case": MESH_STORAGE_CONTROL_CASE, "status": "failed",
              "script": CASES[MESH_STORAGE_CONTROL_CASE][0], "diagnostic_only": True,
              "qualification_scope": dict(MESH_STORAGE_CONTROL_FLAGS)}
    try:
        display = _domain_display()
        executable = blender.resolve(strict=True)
        _raw, binary = _domain_regular(executable, executable.parent, 1024**3)
        if binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256:
            result["unsupported_binary"] = True
            raise ValueError("Untraced storage control requires the pinned 5.2.2 candidate")
        sources = _mesh_storage_sources()
        bundle = output / f"{MESH_STORAGE_CONTROL_CASE}-bundle"
        bundle.mkdir(mode=0o700)
        result = _run_process(executable, MESH_STORAGE_CONTROL_CASE, output, timeout,
            phase="success", bundle=bundle, phase_marker=MESH_STORAGE_CONTROL_MARKER,
            domain_binary=binary, domain_sources=sources, domain_display=display)
        _domain_binding(binary, executable.parent, 1024**3)
        if _mesh_storage_sources() != sources or _domain_display() != display:
            raise ValueError("Untraced storage control source, display or binary changed")
    except (OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError, RecursionError):
        result["status"] = "failed"
        result["admission_error"] = "Untraced storage diagnostic admission or retained evidence refused"
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result



def _run_mesh_storage_timing(blender: Path, output: Path, timeout: int) -> dict:
    """One explicitly observed local-code coarse timing diagnostic; never a qualification pass."""
    started = time.monotonic()
    result = {"case": MESH_STORAGE_TIMING_CASE, "status": "failed",
              "script": CASES[MESH_STORAGE_TIMING_CASE][0], "diagnostic_only": True,
              "qualification_scope": dict(MESH_STORAGE_CONTROL_FLAGS)}
    try:
        display = _domain_display()
        executable = blender.resolve(strict=True)
        _raw, binary = _domain_regular(executable, executable.parent, 1024**3)
        if binary["sha256"] != MESH_STORAGE_EXECUTABLE_SHA256:
            result["unsupported_binary"] = True
            raise ValueError("Observed atomic phase storage control requires the pinned 5.2.2 candidate")
        sources = _mesh_storage_sources()
        bundle = output / f"{MESH_STORAGE_TIMING_CASE}-bundle"
        bundle.mkdir(mode=0o700)
        result = _run_process(executable, MESH_STORAGE_TIMING_CASE, output, timeout,
            phase="success", bundle=bundle, phase_marker=MESH_STORAGE_TIMING_MARKER,
            domain_binary=binary, domain_sources=sources, domain_display=display)
        _domain_binding(binary, executable.parent, 1024**3)
        if _mesh_storage_sources() != sources or _domain_display() != display:
            raise ValueError("Observed atomic phase storage control source, display or binary changed")
    except (OSError, ValueError, KeyError, TypeError, IndexError, UnicodeError, RecursionError):
        result["status"] = "failed"
        result["admission_error"] = "Observed atomic phase storage diagnostic admission or retained evidence refused"
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def _run_process(blender: Path, case: str, output: Path, timeout: int, *,
                 phase: str | None = None, bundle: Path | None = None,
                 phase_marker: str | None = None, domain_binary: dict | None = None,
                 domain_sources: dict | None = None, domain_display: dict | None = None) -> dict:
    filename, marker = CASES[case]
    if case == STORAGE_ROOT_APPROVAL_CASE:
        if phase != "registered_route" or bundle is None:
            raise ValueError("Registered root approval requires its owned phase")
        timeout = min(timeout, 300)
    if case == STORAGE_RUNTIME_CONTEXT_CASE:
        if phase != "runtime_context" or bundle is None:
            raise ValueError("Runtime context diagnostic requires its owned phase")
        timeout = min(timeout, 300)
    if case == STORAGE_ADAPTER_CASE:
        if phase not in STORAGE_ADAPTER_PHASES or bundle is None:
            raise ValueError("Storage adapter requires one explicit isolated phase")
        timeout = min(timeout, 300)
    if case == STORAGE_CLEANUP_CASE:
        if phase not in STORAGE_CLEANUP_PHASES or bundle is None:
            raise ValueError("Storage cleanup requires one explicit isolated phase")
        timeout = min(timeout, 300)
    if case == STORAGE_DISPATCH_CASE:
        if phase not in STORAGE_DISPATCH_PHASES or bundle is None:
            raise ValueError("Storage dispatch requires one explicit isolated phase")
        timeout = min(timeout, 300)
    script = ROOT / "scripts" / filename
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python-expr",
        "import sys; sys.dont_write_bytecode = True",
        "--python",
        str(script),
    ]
    if case in {"artist_quaternion_storage", "artist_quaternion", "uv_edit_storage", "uv_edit_boundary_probe", "large_surface_paint", "uv_edit_guard", "geometry_preview", "geometry_preview_populated_protection", "executor_history_containment", "animation_intent", "weight_edit_guard"}:
        command.insert(1, "--disable-autoexec")
    interactive = case in INTERACTIVE_CASES
    if case == "isolated_asset_preview_probe":
        interactive = phase == "writer"
    if interactive:
        command.remove("--background")
    if case == "glb_stage_structure":
        command.extend(["--", "--bridge-glb-structure"])
    label = case if phase is None else f"{case}-{phase}"
    if phase is not None:
        if bundle is None or phase_marker is None:
            raise ValueError("Phased cases require an owned bundle and success marker")
        command.extend(["--", "--bridge-phase", phase, "--bridge-bundle", str(bundle)])
        if case == "shader_remove_loaded_probe":
            command.append("--bridge-loaded-fixture")
        marker = phase_marker
    if case == STORAGE_RUNTIME_CONTEXT_CASE:
        command.append("--bridge-runtime-context")
    if case in PAIRED_RECOVERY_PROFILES:
        if phase not in {"writer", "reader"}:
            raise ValueError("Paired recovery requires an isolated writer or reader phase")
        command.extend(["--bridge-profile", PAIRED_RECOVERY_PROFILES[case]])
        timeout = min(timeout, 300)
    if case == MESH_STORAGE_CASE:
        if (phase not in MESH_STORAGE_PHASES or bundle is None or sys.platform != "linux"
                or any(type(value) is not dict for value in (domain_binary, domain_sources, domain_display))):
            raise ValueError("Owned storage jobs require a private Linux attested phase")
        timeout = min(timeout, 300)
    if case == MESH_STORAGE_COST_CASE:
        if (phase != "success" or bundle is None or sys.platform != "linux"
                or any(type(value) is not dict for value in (domain_binary, domain_sources, domain_display))):
            raise ValueError("Inspection cost requires private attested Linux success phase")
        command.append("--bridge-inspection-cost-timing")
        timeout = min(timeout, 300)
    if case == MESH_STORAGE_INSPECTION_CASE:
        if (phase != "success" or bundle is None or sys.platform != "linux"
                or any(type(value) is not dict for value in (domain_binary, domain_sources, domain_display))):
            raise ValueError("Phased inspection requires one private attested Linux success phase")
        command.append("--bridge-phased-inspection")
        timeout = min(timeout, 300)
    if case == MESH_STORAGE_TIMING_CASE:
        if (phase != "success" or bundle is None or sys.platform != "linux"
                or any(type(value) is not dict for value in (domain_binary, domain_sources, domain_display))):
            raise ValueError("Observed atomic phase storage control requires one private attested Linux success phase")
        command.append("--bridge-atomic-phase-timing")
        timeout = min(timeout, 300)
    if case == MESH_STORAGE_CONTROL_CASE:
        if (phase != "success" or bundle is None or sys.platform != "linux"
                or any(type(value) is not dict for value in (domain_binary, domain_sources, domain_display))):
            raise ValueError("Untraced storage control requires one private attested Linux success phase")
        command.append("--bridge-untraced-control")
        timeout = min(timeout, 300)
    if case == "geometry_preview_populated_protection":
        command.extend(["--", "--bridge-populated-protection"])
    # Blender writes quit.blend on normal UI exit. Keep it outside the user's temp recovery.
    temporary = output / f"{label}-temp"
    temporary.mkdir(mode=0o700 if case in CURRENT_PIXELS_READ_CASES or case in GLB_STAGE_CASES or case in {"native_project_saving_large", MESH_STORAGE_CASE, MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE, "system_storage_snapshot", STORAGE_ADAPTER_CASE, STORAGE_CLEANUP_CASE, STORAGE_DISPATCH_CASE, STORAGE_RUNTIME_CONTEXT_CASE, STORAGE_ROOT_APPROVAL_CASE} else 0o777)
    if case == MESH_STORAGE_CASE:
        command.extend(["--bridge-report", str(temporary / "mesh-storage-job.json")])
    if case == MESH_STORAGE_CONTROL_CASE:
        command.extend(["--bridge-report", str(temporary / MESH_STORAGE_CONTROL_REPORT)])
    if case == MESH_STORAGE_COST_CASE:
        command.extend(["--bridge-report", str(temporary / MESH_STORAGE_COST_REPORT)])
    if case == MESH_STORAGE_INSPECTION_CASE:
        command.extend(["--bridge-report", str(temporary / MESH_STORAGE_INSPECTION_REPORT)])
    if case == MESH_STORAGE_TIMING_CASE:
        command.extend(["--bridge-report", str(temporary / MESH_STORAGE_TIMING_REPORT)])
    if case == "native_project_saving_large":
        command.extend(["--", "--bridge-large", "--bridge-report", str(temporary / "native-save-large-evidence.json")])
        timeout = min(timeout, 300)
    if case in CURRENT_PIXELS_READ_CASES:
        flag, report_name = (("--bridge-census-only", "current-pixels-census.json") if case == "current_pixels_lifecycle_census"
                             else ("--bridge-source-graph", "current-pixels-source-graph.json"))
        command.extend(["--", flag, "--bridge-report", str(temporary / report_name)])
        timeout = min(timeout, 300)
    environment = dict(os.environ, TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
    process_instance = uuid.uuid4().hex
    environment["BRIDGE_TEST_PROCESS_TOKEN"] = process_instance
    for key, folder in (("BLENDER_USER_CONFIG", "config"), ("BLENDER_USER_SCRIPTS", "scripts"),
                        ("BLENDER_USER_DATAFILES", "datafiles")):
        if case == "installed_addon_probe" and key == "BLENDER_USER_SCRIPTS":
            folder = "installed scripts with spaces"
        directory = temporary / folder
        directory.mkdir()
        environment[key] = str(directory)
    launch_cwd = ROOT
    if (case in PORTABLE_BLEND_RESEARCH_PHASES or case in PAIRED_RECOVERY_PROFILES
            or case in {"isolated_asset_preview_probe", "native_project_saving", "native_project_saving_large", MESH_STORAGE_CASE, MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE, *CURRENT_PIXELS_READ_CASES, *GLB_STAGE_CASES, "system_storage_snapshot", STORAGE_ADAPTER_CASE, STORAGE_CLEANUP_CASE, STORAGE_DISPATCH_CASE, STORAGE_RUNTIME_CONTEXT_CASE, STORAGE_ROOT_APPROVAL_CASE}):
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
                           GSETTINGS_BACKEND="memory", NO_AT_BRIDGE="1")
        if case in PORTABLE_BLEND_RESEARCH_PHASES:
            environment["BRIDGE_TEST_PORTABLE_BLEND_PHASE"] = PORTABLE_BLEND_RESEARCH_PHASES[case]
        elif interactive and "BRIDGE_TEST_PRIVATE_UI_MANIFEST" in os.environ:
            # The reviewed display manifest binds its own private runtime path.
            # The fixture validates this before taking owned process-exit authority.
            environment["BRIDGE_TEST_PRIVATE_UI_MANIFEST"] = os.environ["BRIDGE_TEST_PRIVATE_UI_MANIFEST"]
            if "XDG_RUNTIME_DIR" in os.environ:
                environment["XDG_RUNTIME_DIR"] = os.environ["XDG_RUNTIME_DIR"]
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
            "private_interactive_display" if case in {MESH_STORAGE_CASE, MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE}
            else "private_windows_desktop" if interactive and sys.platform == "win32"
            else "interactive_display" if interactive else "background"
        ),
    }
    adapter_inputs = cleanup_inputs = dispatch_inputs = runtime_context_inputs = root_approval_inputs = None
    if case == STORAGE_ROOT_APPROVAL_CASE:
        result["qualification_scope"] = {"profile": "STOCK_REGISTERED_PREFERENCES_ROOT_APPROVAL_V1",
            "fixture_only_registration": True, "shipping_caller_qualified": False, "snapshot_writer_qualified": False,
            "post_C_root_check_qualified": False, "full_artist_target": "OPEN", "windows_testing_deferred": True}
        if sys.platform != "linux":
            result["preflight_error"] = "STORAGE_ROOT_APPROVAL_PLATFORM_DEFERRED"
            return result
        try:
            root_approval_inputs = _storage_root_approval_inputs(blender)
        except (OSError, ValueError) as error:
            result["preflight_error"] = str(error)[:256]
            return result
    if case == STORAGE_RUNTIME_CONTEXT_CASE:
        result["qualification_scope"] = {"profile": "STOCK_RUNTIME_JOBS_CONTEXT_QUEUED_REQUEST_DIAGNOSTIC_V1",
            "fixture_only_registration": True, "genuine_Runtime_jobs_context": True,
            "canonical_job_resumption_qualified": False, "shipping_caller_qualified": False,
            "full_artist_target": "OPEN", "windows_testing_deferred": True}
        if sys.platform == "win32":
            result["preflight_error"] = "STORAGE_RUNTIME_CONTEXT_WINDOWS_TESTING_DEFERRED"
            return result
        try:
            runtime_context_inputs = _storage_runtime_context_inputs(blender)
        except (OSError, ValueError) as error:
            result["preflight_error"] = str(error)[:256]
            return result
    if case == STORAGE_DISPATCH_CASE:
        result["qualification_scope"] = {"profile": "STOCK_OWNED_STORAGE_ACTUAL_DISPATCH_V1",
            "fixture_only_actual_dispatch": True, "shipping_caller_qualified": False,
            "full_artist_target": "OPEN", "windows_testing_deferred": True}
        if sys.platform == "win32":
            result["preflight_error"] = "STORAGE_DISPATCH_WINDOWS_TESTING_DEFERRED"
            return result
        try:
            dispatch_inputs = _storage_dispatch_inputs(blender)
        except (OSError, ValueError) as error:
            result["preflight_error"] = str(error)[:256]
            return result
    if case == STORAGE_CLEANUP_CASE:
        result["qualification_scope"] = {"profile": "STOCK_OWNED_STORAGE_CLEANUP_V1",
            "actual_cleanup_only": True, "runtime_retention_qualified": False, "cache_pairing_qualified": False,
            "full_artist_target": "OPEN", "windows_testing_deferred": True}
        if sys.platform == "win32":
            result["preflight_error"] = "STORAGE_CLEANUP_WINDOWS_TESTING_DEFERRED"
            return result
        try:
            cleanup_inputs = _storage_cleanup_inputs(blender)
        except (OSError, ValueError) as error:
            result["preflight_error"] = str(error)[:256]
            return result
    if case == STORAGE_ADAPTER_CASE:
        result["qualification_scope"] = {"profile": "STOCK_VIEW_LAYER_STORAGE_ADAPTER_V1",
            "actual_adapter_only": True, "runtime_retention_qualified": False, "cache_pairing_qualified": False,
            "full_artist_target": "OPEN", "windows_testing_deferred": True}
        if sys.platform == "win32":
            result["preflight_error"] = "STORAGE_ADAPTER_WINDOWS_TESTING_DEFERRED"
            return result
        try:
            adapter_inputs = _storage_adapter_inputs(blender)
        except (OSError, ValueError) as error:
            result["preflight_error"] = str(error)[:256]
            return result
    if case == "animation_intent":
        result["qualification_scope"] = {
            "authored_profile": "RAW_FREE_POINT_V1",
            "registered_future_key_raw_fields": ["co", "handle_left", "handle_right"],
            "current_pose_revision_qualified": False,
            "native_failure_compensation_qualified": False,
            "native_cancellation_disconnect_qualified": False,
            "persistent_non_ID_identity_qualified": False,
            "complete_hidden_state_qualified": False,
            "full_H05_C03_qualified": False,
            "windows_testing_deferred": True,
        }
    if case in GLB_STAGE_CASES - {"glb_stage_runtime"}:
        result["qualification_scope"] = {
            "profile": "GLB_PRIVATE_STRUCTURE_V1" if case == "glb_stage_structure" else "GLB_PRIVATE_STAGE_V1",
            "private_constructor_only": True, "depsgraph_evaluated_world_qualified": False,
            "canonical_cancel_guaranteed": False,
            "artist_destination_preservation_qualified": False, "public_import_qualified": False,
            "durable_recovery_verified": False, "transport_cancellation_disconnect_qualified": False,
            "windows_testing_deferred": True,
        }
    if case == "glb_stage_runtime":
        result["qualification_scope"] = {
            "profile": "GLB_RUNTIME_STAGE_PUBLISH_V1", "genuine_runtime_tcp_required": True,
            "complete_seventeen_scenarios_required": True, "public_import_qualified": False,
            "retained_fresh_runtime_groups_required": True,
            "actual_owner_postreturn_disconnect_required": True,
            "protected_logical_profile_with_read_effects_required": True,
            "owned_fixture_storage_preparation_is_not_product_api": True,
            "physical_cache_passivity_qualified": False,
            "depsgraph_evaluated_world_qualified": False, "durable_recovery_verified": False,
            "broader_images_skin_animation_FBX_qualified": False, "windows_testing_deferred": True,
        }
    if case == "geometry_preview_populated_protection":
        result["qualification_scope"] = {
            "selected_fields": ["mesh_geometry", "material_slots", "animation"],
            "actual_populated_baseline_required": True,
            "raw_idle_ui_preservation_qualified": False,
            "image_pixels_or_material_appearance_qualified": False,
            "full_H02_F04_or_protected_object_qualified": False,
        }
    if case == "current_pixels_lifecycle_census":
        result["qualification_scope"] = {"class_metadata_only": True, "lifecycle_functional_acceptance": False,
                                         "windows_qualified": False, "maximum_report_bytes": 2 * 1024 * 1024}
    if case == "current_pixels_source_graph":
        result["qualification_scope"] = {"native_source_graph_read_only": True, "lifecycle_functional_acceptance": False,
            "current_pixels_origin_qualified": False, "windows_qualified": False, "maximum_report_bytes": 2 * 1024 * 1024}
    if case == MESH_STORAGE_CASE:
        result["qualification_scope"] = dict(MESH_STORAGE_LIMITS)
        result["binary"] = domain_binary
    if case == MESH_STORAGE_COST_CASE:
        result["binary"] = domain_binary
        result["diagnostic_only"] = True
        result["qualification_scope"] = {"observed_costs_only": True, "untraced_timings": False, "product_success": False, "release_acceptance": False}
    if case == MESH_STORAGE_INSPECTION_CASE:
        result["binary"] = domain_binary
        result["qualification_scope"] = dict(MESH_STORAGE_INSPECTION_LIMITS)
    if case == MESH_STORAGE_TIMING_CASE:
        result["diagnostic_only"] = True
        result["binary"] = domain_binary
        result["qualification_scope"] = dict(MESH_STORAGE_CONTROL_FLAGS)
    if case == MESH_STORAGE_CONTROL_CASE:
        result["diagnostic_only"] = True
        result["binary"] = domain_binary
        result["qualification_scope"] = dict(MESH_STORAGE_CONTROL_FLAGS)
    if case == "native_project_saving_large":
        result["qualification_scope"] = {"profile": "NATIVE_SAVE_CLEAN_PACKED_4K_V1",
            "actual_queued_runtime_required": True, "fresh_reader_required": True,
            "full_project_or_H01_or_1_0_qualified": False, "windows_qualified": False,
            "maximum_report_bytes": 8 * 1024 * 1024, "maximum_native_phase_seconds": 300}
        large_sources = _native_save_sources()
        binary_path = blender.resolve(strict=True)
        large_binary = {"path": str(binary_path), "sha256": _native_save_file(binary_path, 1024**3)[0]}
    if case == "system_storage_snapshot":
        result["qualification_scope"] = {"profile": "STOCK_VIEW_LAYER_RAW_CYCLES_V1", "private_prerequisite_only": True,
            "canonical_runtime_qualified": False, "durable_backup_qualified": False,
            "dirty_current_pixel_backup_qualified": False, "native_memory_cap_claimed": False, "windows_qualified": False}
        timeout = min(timeout, 300)
    system_inputs = None
    glb_inputs = None
    with log.open("wb") as stream:
        try:
            if case in GLB_STAGE_CASES:
                glb_inputs = _glb_stage_inputs(blender, runtime=case == "glb_stage_runtime")
            if case == "system_storage_snapshot":
                system_inputs = _system_storage_inputs(blender)
            if case in {STORAGE_ADAPTER_CASE, STORAGE_CLEANUP_CASE, STORAGE_DISPATCH_CASE, STORAGE_RUNTIME_CONTEXT_CASE, STORAGE_ROOT_APPROVAL_CASE}:
                with subprocess.Popen(command, cwd=launch_cwd, stdout=stream,
                                      stderr=subprocess.STDOUT, env=environment) as process:
                    result["launched_process_id"] = process.pid
                    try:
                        process.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise
            elif interactive and sys.platform == "win32":
                from scripts.windows_test_process import run_isolated

                process = run_isolated(command, cwd=launch_cwd, stdout=stream,
                                       timeout=timeout, env=environment)
            elif case in {MESH_STORAGE_CASE, MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE}:
                process = subprocess.Popen(command, cwd=launch_cwd, stdout=stream, stderr=subprocess.STDOUT,
                                           env=environment, start_new_session=True)
                result["os_process_id"] = process.pid
                try:
                    result["exit_code"] = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    raise
            elif case in {"glb_stage_structure", "glb_stage_runtime", "system_storage_snapshot"}:
                # Capture the actual owned child PID; a positive marker PID alone
                # cannot attest which process produced the structural receipt.
                process = subprocess.Popen(command, cwd=launch_cwd, stdout=stream,
                    stderr=subprocess.STDOUT, env=environment)
                result["process_id"] = process.pid
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                    raise
            else:
                process = subprocess.run(
                    command, cwd=launch_cwd, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=timeout, check=False, env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            if case not in {MESH_STORAGE_CASE, MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE}:
                result["exit_code"] = process.returncode
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
            if case in {STORAGE_ADAPTER_CASE, STORAGE_CLEANUP_CASE, STORAGE_DISPATCH_CASE, STORAGE_RUNTIME_CONTEXT_CASE, STORAGE_ROOT_APPROVAL_CASE}:
                result.update(process_timeout=True, timeout_seconds=timeout,
                              native_terminal_outcome="UNKNOWN", owned_process_terminated=True,
                              native_call_preemption_qualified=False)
        except OSError as exc:
            result["launch_error"] = str(exc)
        except ValueError as exc:
            if case not in {*GLB_STAGE_CASES, "system_storage_snapshot"}:
                raise
            result["input_validation_error"] = str(exc)
    if case in {MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE}:
        payload = None
        try:
            raw_log, _binding = _domain_regular(log, output, 4 * 1024**2, capture=True)
            candidates = [line[len(marker):] for line in raw_log.decode("utf-8", errors="strict").splitlines()
                          if line.startswith(marker)]
            if len(candidates) != 1:
                raise ValueError("Untraced control marker cardinality")
            payload = _native_save_json(candidates[0].encode())
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            result["marker_validation_error"] = "MESH_STORAGE_CONTROL_MARKER_INVALID"
    elif case in {"glb_stage_structure", "glb_stage_runtime"}:
        payload = None
        try:
            _log_sha, raw_log = _glb_stage_file(log, 4 * 1024**2, retain=True)
            marked = [line[len(marker):] for line in raw_log.decode("utf-8", errors="strict").splitlines()
                      if line.startswith(marker)]
            if len(marked) != 1:
                raise ValueError("GLB_STRUCTURE_MARKER_CARDINALITY")
            payload = json.loads(marked[0], object_pairs_hook=_glb_stage_unique,
                                 parse_constant=_glb_stage_reject_constant)
            if type(payload) is not dict:
                raise ValueError("GLB_STRUCTURE_MARKER_OBJECT_REQUIRED")
        except (OSError, UnicodeError, ValueError, RecursionError):
            payload = None
            result["marker_validation_error"] = "GLB_RUNTIME_MARKER_INVALID" if case == "glb_stage_runtime" else "GLB_STRUCTURE_MARKER_INVALID"
    else:
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 65536))
            log_text = stream.read().decode("utf-8", errors="replace")
        if case in {"native_project_saving_large", MESH_STORAGE_CASE, MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE}:
            candidates = [line[len(marker):] for line in log_text.splitlines() if line.startswith(marker)]
            payload = None
            if len(candidates) == 1:
                with suppress(ValueError, TypeError, RecursionError):
                    payload = _native_save_json(candidates[0].encode())
        else:
            payload = (_public_cloth_payload(log_text, marker)
                       if case in {"system_storage_snapshot", STORAGE_ADAPTER_CASE, STORAGE_CLEANUP_CASE, STORAGE_DISPATCH_CASE, STORAGE_RUNTIME_CONTEXT_CASE, STORAGE_ROOT_APPROVAL_CASE}
                       else success_payload(log_text, marker))
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
    if case in PAIRED_RECOVERY_PROFILES:
        phase_evidence = phase_evidence and bool(payload and payload.get("profile") == PAIRED_RECOVERY_PROFILES[case])
    if case == "geometry_preview_populated_protection":
        phase_evidence = bool(payload and payload.get("variant") == "populated_data_baseline"
                              and payload.get("populated_protected_data_baseline_qualified") is True)
    if case == "current_pixels_lifecycle_census":
        phase_evidence = _census_receipt_matches(payload, temporary, process_instance)
    if case == "current_pixels_source_graph":
        phase_evidence = _graph_receipt_matches(payload, temporary, process_instance)
    if case == MESH_STORAGE_CASE:
        phase_evidence = _mesh_storage_receipt_matches(payload, temporary, process_instance, phase,
            bundle, result.get("os_process_id"), domain_binary, domain_sources, domain_display)
    if case == MESH_STORAGE_COST_CASE:
        phase_evidence = False
        validation = _mesh_storage_cost_matches(payload, temporary, process_instance,
            result.get("os_process_id"), domain_binary, domain_sources, domain_display)
        result["retained_evidence_validation"] = validation
        if result["exit_code"] == 0 and payload is not None and version and validation["diagnostic_completed"]:
            result["status"] = "diagnostic_completed"
    if case == MESH_STORAGE_INSPECTION_CASE:
        validation = _mesh_storage_inspection_matches(payload, temporary, process_instance,
            result.get("os_process_id"), domain_binary, domain_sources, domain_display)
        result["retained_evidence_validation"] = validation
        phase_evidence = False  # Success-only private probe, not all native acceptance scenarios.
        if result["exit_code"] == 0 and payload is not None and version and validation["passed"]:
            result["status"] = "diagnostic_completed"
    if case == MESH_STORAGE_TIMING_CASE:
        phase_evidence = False  # A diagnostic never qualifies the five native phases.
        validation = _mesh_storage_timing_matches(payload, temporary, process_instance,
            result.get("os_process_id"), domain_binary, domain_sources, domain_display)
        result["retained_evidence_validation"] = validation
        if result["exit_code"] == 0 and payload is not None and version and validation["diagnostic_completed"]:
            result["status"] = "diagnostic_completed"
    if case == MESH_STORAGE_CONTROL_CASE:
        phase_evidence = False  # A diagnostic never qualifies the five native phases.
        validation = _mesh_storage_control_matches(payload, temporary, process_instance,
            result.get("os_process_id"), domain_binary, domain_sources, domain_display)
        result["retained_evidence_validation"] = validation
        if result["exit_code"] == 0 and payload is not None and version and validation["diagnostic_completed"]:
            result["status"] = "diagnostic_completed"
    if case == "native_project_saving_large":
        phase_evidence = _native_save_large_receipt_matches(payload, temporary, process_instance, large_sources, large_binary)
    if case == "system_storage_snapshot":
        validation = _system_storage_validate(payload, temporary, process_instance, system_inputs, result.get("process_id"))
        result["retained_evidence_validation"] = validation
        phase_evidence = validation["passed"]
    if case == "glb_stage_runtime":
        validation = _glb_runtime_validate(payload, temporary, process_instance, blender, glb_inputs, result.get("process_id"))
        result["retained_evidence_validation"] = validation
        phase_evidence = validation["passed"]
    elif case in GLB_STAGE_CASES:
        validation = _glb_stage_validate(payload, temporary, process_instance, blender, glb_inputs,
            structure=case == "glb_stage_structure", process_id=result.get("process_id"))
        result["retained_evidence_validation"] = validation
        phase_evidence = validation["passed"]
    if result["exit_code"] == 0 and payload is not None and version and phase_evidence:
        result["status"] = "passed"
    if case == STORAGE_DISPATCH_CASE:
        validation = _storage_dispatch_validate(payload, phase, bundle, process_instance,
            result.get("launched_process_id"), dispatch_inputs)
        result["retained_evidence_validation"] = validation
        if not validation["passed"] and result["status"] != "timeout":
            result["status"] = "failed"
    if case == STORAGE_CLEANUP_CASE:
        validation = _storage_cleanup_validate(payload, phase, bundle, process_instance,
            result.get("launched_process_id"), cleanup_inputs)
        result["retained_evidence_validation"] = validation
        if not validation["passed"] and result["status"] != "timeout":
            result["status"] = "failed"
    if case == STORAGE_ADAPTER_CASE:
        validation = _storage_adapter_validate(payload, phase, bundle, process_instance,
            result.get("launched_process_id"), adapter_inputs)
        result["retained_evidence_validation"] = validation
        if not validation["passed"] and result["status"] != "timeout":
            result["status"] = "failed"
    if case == STORAGE_RUNTIME_CONTEXT_CASE:
        validation = _storage_runtime_context_validate(payload, phase, bundle, process_instance,
            result.get("launched_process_id"), runtime_context_inputs)
        result["retained_evidence_validation"] = validation
        if not validation["passed"] and result["status"] != "timeout":
            result["status"] = "failed"
    if case == STORAGE_ROOT_APPROVAL_CASE:
        validation = _storage_root_approval_validate(payload, phase, bundle, process_instance,
            result.get("launched_process_id"), root_approval_inputs)
        result["retained_evidence_validation"] = validation
        if not validation["passed"] and result["status"] != "timeout":
            result["status"] = "failed"
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["duration_seconds"] = round(time.monotonic() - start, 3)
    return result




def _runtime_bulk_sources() -> dict[str, str]:
    from scripts.blender_runtime_metadata_bulk_probe_smoke import SOURCES
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def _runtime_bulk_receipt(payload, temporary, token, pid, binary, sources):
    """Validate API feasibility only; neither product adoption nor speed proof."""
    from scripts.blender_runtime_metadata_bulk_probe_smoke import OWNERS, PROFILE, SCENARIOS
    try:
        expected_version, expected_build = RUNTIME_BULK_BUILDS[binary["sha256"]]
        if (type(payload) is not dict or set(payload) != {"profile", "process_instance", "process_id", "blender_version", "full_receipt"}
                or payload["profile"] != PROFILE or payload["process_instance"] != token
                or type(payload["process_id"]) is not int or payload["process_id"] != pid
                or payload["blender_version"] != expected_version
                or payload["full_receipt"]["path"] != str(temporary / "runtime-metadata-bulk.json")):
            return False
        raw = _domain_binding(payload["full_receipt"], temporary, 512 * 1024, capture=True)
        full = _native_save_json(raw)
        if (type(full) is not dict or set(full) != {"profile", "completed", "process_instance", "process_id", "blender_version",
                "source_build", "source_fingerprints", "rows", "scenarios", "payload_getter_calls", "runtime_field",
                "runtime_field_removed", "sentinel_before_sha256", "sentinel_after_sha256", "schema_before_sha256",
                "schema_after_sha256", "limitations"} or full.get("completed") is not True
                or any(full.get(key) != payload[key] for key in ("profile", "process_instance", "process_id", "blender_version"))
                or type(full.get("process_id")) is not int or type(full.get("source_build")) is not str
                or not full["source_build"].startswith(expected_build)
                or full.get("source_fingerprints") != sources or _runtime_bulk_sources() != sources
                or type(full.get("payload_getter_calls")) is not int or full["payload_getter_calls"] != 0
                or full.get("runtime_field") != "bcb_owned_metadata_bulk_runtime_probe"
                or full.get("runtime_field_removed") is not True):
            return False
        limits = full.get("limitations")
        if (type(limits) is not dict or set(limits) != {"product_adoption", "speedup_qualified", "mid_C_cancel",
                "all_native_callbacks_observed", "full_workflow", "windows", "probe_guard_source_stop_only", "post_C_faults_injected_by_probe"}
                or any(limits[name] is not False for name in ("product_adoption", "speedup_qualified", "mid_C_cancel",
                    "all_native_callbacks_observed", "full_workflow", "windows"))
                or limits["probe_guard_source_stop_only"] is not True or limits["post_C_faults_injected_by_probe"] is not True):
            return False
        for name in ("sentinel", "schema"):
            before, after = full.get(name + "_before_sha256"), full.get(name + "_after_sha256")
            if not _domain_hex(before) or before != after:
                return False
        rows = full.get("rows")
        if type(rows) is not list or len(rows) != len(OWNERS):
            return False
        for row, owner in zip(rows, OWNERS, strict=True):
            if (type(row) is not dict or set(row) != {"owner", "count", "metadata", "flags", "after_metadata", "interval",
                    "exact_native_collection", "original_method_descriptor", "owned_exact_list"} or row.get("owner") != owner
                    or type(row.get("count")) is not int or not 1 <= row["count"] <= 512
                    or any(row.get(name) is not True for name in ("exact_native_collection", "original_method_descriptor", "owned_exact_list"))):
                return False
            metadata, flags = row.get("metadata"), row.get("flags")
            if (type(metadata) is not list or len(metadata) != row["count"] or row.get("after_metadata") != metadata
                    or type(flags) is not list or len(flags) != row["count"] or any(type(flag) is not bool for flag in flags)):
                return False
            after_metadata = row.get("after_metadata")
            if type(after_metadata) is not list or len(after_metadata) != len(metadata):
                return False
            seen = set()
            for entry, flag, after_entry in zip(metadata, flags, after_metadata, strict=True):
                if (type(entry) is not list or len(entry) != 4 or type(after_entry) is not list or len(after_entry) != 4
                        or any(type(left) is not type(right) for left, right in zip(entry, after_entry, strict=True))
                        or not _domain_hex(entry[0], len(entry[0]))
                        or not 1 <= len(entry[0]) <= 16 or int(entry[0], 16) == 0
                        or type(entry[1]) is not str or not 1 <= len(entry[1]) <= 256
                        or type(entry[2]) is not str or not 1 <= len(entry[2]) <= 32
                        or type(entry[3]) is not bool or entry[3] is not flag or entry[0] in seen):
                    return False
                seen.add(entry[0])
            interval = row.get("interval")
            if (type(interval) is not dict or set(interval) != {"wall_seconds", "cpu_seconds"}
                    or any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 60
                           for value in interval.values())):
                return False
        if not any(entry[1] == full["runtime_field"] and entry[3] is True for entry in rows[0]["metadata"]):
            return False
        scenarios = full.get("scenarios")
        if type(scenarios) is not dict or set(scenarios) != set(SCENARIOS):
            return False
        for name, row in scenarios.items():
            if (type(row) is not dict or set(row) != {"bulk_calls", "reason", "flags_consumed", "later_inspection_attempts", "injected_probe_callback"}
                    or type(row["bulk_calls"]) is not int or row["bulk_calls"] != int(name.endswith("after"))
                    or row["reason"] != ("TIMEOUT" if name.startswith("stop") else "STORAGE_SOURCE_CHANGED")
                    or row["flags_consumed"] is not False or type(row["later_inspection_attempts"]) is not int
                    or row["later_inspection_attempts"] != 0 or row["injected_probe_callback"] is not name.endswith("after")):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError, UnicodeError):
        return False


def _run_runtime_bulk_probe(blender: Path, output: Path, timeout: int) -> dict:
    started = time.monotonic()
    result = {"case": RUNTIME_BULK_CASE, "status": "failed", "exit_code": None,
              "execution_mode": "background", "qualification_scope": {"private_API_feasibility_only": True,
                  "product_adoption": False, "speedup_qualified": False, "full_workflow": False, "windows": False}}
    try:
        display = _domain_display()
        executable = blender.resolve(strict=True)
        _raw, binary = _domain_regular(executable, executable.parent, 1024**3)
        if binary["sha256"] not in RUNTIME_BULK_BUILDS:
            raise ValueError("BULK_PROBE_BINARY_UNSUPPORTED")
        sources = _runtime_bulk_sources()
        temporary = output / (RUNTIME_BULK_CASE + "-temp")
        temporary.mkdir(mode=0o700)
        report = temporary / "runtime-metadata-bulk.json"
        token = uuid.uuid4().hex
        environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "DISPLAY", "XAUTHORITY",
            "LD_LIBRARY_PATH", "LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "MESA_LOADER_DRIVER_OVERRIDE", "LP_NUM_THREADS")
            if key in os.environ}
        for key in ("HOME", "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES",
                    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
            directory = temporary / ("worker-" + key.lower())
            directory.mkdir(mode=0o700)
            environment[key] = str(directory)
        working = temporary / "working"
        working.mkdir(mode=0o700)
        environment.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary),
            BRIDGE_TEST_PROCESS_TOKEN=token, GSETTINGS_BACKEND="memory", NO_AT_BRIDGE="1")
        command = [str(executable), "--background", "--factory-startup", "--disable-autoexec", "--python-exit-code", "1",
            "--python-expr", "import sys; sys.dont_write_bytecode = True", "--python",
            str(ROOT / "scripts" / CASES[RUNTIME_BULK_CASE][0]), "--", "--bridge-report", str(report)]
        log = output / (RUNTIME_BULK_CASE + ".log")
        result.update(command=command, log=str(log), binary=binary, source_fingerprints=sources)
        with log.open("wb") as stream:
            process = subprocess.Popen(command, cwd=working, env=environment, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            result["process_id"] = process.pid
            try:
                result["exit_code"] = process.wait(timeout=min(timeout, 300))
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
                result["status"] = "timeout"
        _domain_binding(binary, executable.parent, 1024**3)
        if _runtime_bulk_sources() != sources or _domain_display() != display:
            raise ValueError("BULK_PROBE_SOURCE_OR_DISPLAY_CHANGED")
        raw, _binding = _domain_regular(log, output, 1024**2, capture=True)
        marker = CASES[RUNTIME_BULK_CASE][1]
        candidates = [line[len(marker):] for line in raw.decode("utf-8", errors="strict").splitlines() if line.startswith(marker)]
        payload = _native_save_json(candidates[0].encode()) if len(candidates) == 1 else None
        result["evidence"] = payload
        accepted = _runtime_bulk_receipt(payload, temporary, token, process.pid, binary, sources)
        result["retained_evidence_valid"] = accepted
        if result["exit_code"] == 0 and accepted:
            result["status"] = "passed"
    except (OSError, ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError):
        result["admission_error"] = "Runtime metadata bulk API probe refused; inspect owned log/evidence"
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def run_case(blender: Path, case: str, output: Path, timeout: int) -> dict:
    if case == STORAGE_ROOT_APPROVAL_CASE:
        return _run_storage_root_approval_case(blender, output, timeout)
    if case == STORAGE_RUNTIME_CONTEXT_CASE:
        return _run_storage_runtime_context_case(blender, output, timeout)
    if case == STORAGE_DISPATCH_CASE:
        return _run_storage_dispatch_case(blender, output, timeout)
    if case == STORAGE_CLEANUP_CASE:
        return _run_storage_cleanup_case(blender, output, timeout)
    if case == STORAGE_ADAPTER_CASE:
        return _run_storage_adapter_case(blender, output, timeout)
    if case == MESH_STORAGE_COST_CASE:
        return _run_mesh_storage_cost(blender, output, timeout)
    if case == MESH_STORAGE_INSPECTION_CASE:
        return _run_mesh_storage_inspection(blender, output, timeout)
    if case == MESH_STORAGE_TIMING_CASE:
        return _run_mesh_storage_timing(blender, output, timeout)
    if case == RUNTIME_BULK_CASE:
        return _run_runtime_bulk_probe(blender, output, timeout)
    if case == MESH_STORAGE_CASE:
        return _run_mesh_storage_case(blender, output, timeout)
    if case == MESH_STORAGE_CONTROL_CASE:
        return _run_mesh_storage_control(blender, output, timeout)
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
    defaults = [case for case in CASES if case not in {"native_project_saving_large", MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE}
                and (args.include_interactive or case not in INTERACTIVE_CASES | OPT_IN_CASES)
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
    report["checks_passed"] = all(r["case"] not in {MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE} and r["status"] == "passed"
                                  for r in report["results"])
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    diagnostics_completed = all((r["case"] not in {MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE} and r["status"] == "passed") or
        (r["case"] in {MESH_STORAGE_CONTROL_CASE, MESH_STORAGE_TIMING_CASE, MESH_STORAGE_INSPECTION_CASE, MESH_STORAGE_COST_CASE} and r["status"] == "diagnostic_completed")
        for r in report["results"])
    return 0 if diagnostics_completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
