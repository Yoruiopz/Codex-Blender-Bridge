"""Run isolated Blender smokes and retain truthful, versioned execution evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import stat
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
    "current_pixels_lifecycle_census": ("blender_current_pixels_lifecycle_smoke.py", "BLENDER_CURRENT_PIXELS_LIFECYCLE_CENSUS_OK "),
    "current_pixels_source_graph": ("blender_current_pixels_lifecycle_smoke.py", "BLENDER_CURRENT_PIXELS_SOURCE_GRAPH_OK "),
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
    if case == "geometry_preview_populated_protection":
        command.extend(["--", "--bridge-populated-protection"])
    # Blender writes quit.blend on normal UI exit. Keep it outside the user's temp recovery.
    temporary = output / f"{label}-temp"
    temporary.mkdir(mode=0o700 if case in CURRENT_PIXELS_READ_CASES or case == "native_project_saving_large" else 0o777)
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
            or case in {"isolated_asset_preview_probe", "native_project_saving", "native_project_saving_large", *CURRENT_PIXELS_READ_CASES}):
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
            "private_windows_desktop" if interactive and sys.platform == "win32"
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
    if case == "native_project_saving_large":
        result["qualification_scope"] = {"profile": "NATIVE_SAVE_CLEAN_PACKED_4K_V1",
            "actual_queued_runtime_required": True, "fresh_reader_required": True,
            "full_project_or_H01_or_1_0_qualified": False, "windows_qualified": False,
            "maximum_report_bytes": 8 * 1024 * 1024, "maximum_native_phase_seconds": 300}
        large_sources = _native_save_sources()
        binary_path = blender.resolve(strict=True)
        large_binary = {"path": str(binary_path), "sha256": _native_save_file(binary_path, 1024**3)[0]}
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
        log_text = stream.read().decode("utf-8", errors="replace")
    if case == "native_project_saving_large":
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
    if case == "native_project_saving_large":
        phase_evidence = _native_save_large_receipt_matches(payload, temporary, process_instance, large_sources, large_binary)
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
