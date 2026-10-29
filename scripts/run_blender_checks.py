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
CASES = {
    MESH_STORAGE_CASE: ("blender_mesh_storage_job_smoke.py", MESH_STORAGE_MARKER),
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


def _run_process(blender: Path, case: str, output: Path, timeout: int, *,
                 phase: str | None = None, bundle: Path | None = None,
                 phase_marker: str | None = None, domain_binary: dict | None = None,
                 domain_sources: dict | None = None, domain_display: dict | None = None) -> dict:
    filename, marker = CASES[case]
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
    if case == "geometry_preview_populated_protection":
        command.extend(["--", "--bridge-populated-protection"])
    # Blender writes quit.blend on normal UI exit. Keep it outside the user's temp recovery.
    temporary = output / f"{label}-temp"
    temporary.mkdir(mode=0o700 if case in CURRENT_PIXELS_READ_CASES or case in GLB_STAGE_CASES or case in {"native_project_saving_large", MESH_STORAGE_CASE} else 0o777)
    if case == MESH_STORAGE_CASE:
        command.extend(["--bridge-report", str(temporary / "mesh-storage-job.json")])
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
            or case in {"isolated_asset_preview_probe", "native_project_saving", "native_project_saving_large", MESH_STORAGE_CASE, *CURRENT_PIXELS_READ_CASES, *GLB_STAGE_CASES}):
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
            "private_interactive_display" if case == MESH_STORAGE_CASE
            else "private_windows_desktop" if interactive and sys.platform == "win32"
            else "interactive_display" if interactive else "background"
        ),
    }
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
    if case == "native_project_saving_large":
        result["qualification_scope"] = {"profile": "NATIVE_SAVE_CLEAN_PACKED_4K_V1",
            "actual_queued_runtime_required": True, "fresh_reader_required": True,
            "full_project_or_H01_or_1_0_qualified": False, "windows_qualified": False,
            "maximum_report_bytes": 8 * 1024 * 1024, "maximum_native_phase_seconds": 300}
        large_sources = _native_save_sources()
        binary_path = blender.resolve(strict=True)
        large_binary = {"path": str(binary_path), "sha256": _native_save_file(binary_path, 1024**3)[0]}
    glb_inputs = None
    with log.open("wb") as stream:
        try:
            if case in GLB_STAGE_CASES:
                glb_inputs = _glb_stage_inputs(blender, runtime=case == "glb_stage_runtime")
            if interactive and sys.platform == "win32":
                from scripts.windows_test_process import run_isolated

                process = run_isolated(command, cwd=launch_cwd, stdout=stream,
                                       timeout=timeout, env=environment)
            elif case == MESH_STORAGE_CASE:
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
            elif case in {"glb_stage_structure", "glb_stage_runtime"}:
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
            if case != MESH_STORAGE_CASE:
                result["exit_code"] = process.returncode
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
        except OSError as exc:
            result["launch_error"] = str(exc)
        except ValueError as exc:
            if case not in GLB_STAGE_CASES:
                raise
            result["input_validation_error"] = str(exc)
    if case in {"glb_stage_structure", "glb_stage_runtime"}:
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
        if case in {"native_project_saving_large", MESH_STORAGE_CASE}:
            candidates = [line[len(marker):] for line in log_text.splitlines() if line.startswith(marker)]
            payload = None
            if len(candidates) == 1:
                with suppress(ValueError, TypeError, RecursionError):
                    payload = _native_save_json(candidates[0].encode())
        else:
            payload = success_payload(log_text, marker)
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
    if case == "native_project_saving_large":
        phase_evidence = _native_save_large_receipt_matches(payload, temporary, process_instance, large_sources, large_binary)
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
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["duration_seconds"] = round(time.monotonic() - start, 3)
    return result


def run_case(blender: Path, case: str, output: Path, timeout: int) -> dict:
    if case == MESH_STORAGE_CASE:
        return _run_mesh_storage_case(blender, output, timeout)
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
    defaults = [case for case in CASES if case != "native_project_saving_large"
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
    report["checks_passed"] = all(r["status"] == "passed" for r in report["results"])
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report_path)
    return 0 if report["checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
