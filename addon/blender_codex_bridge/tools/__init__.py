"""Registration entry point for built-in structured Blender tools."""

from __future__ import annotations

from ..tool_registry import ToolRegistry


def register_all(registry: ToolRegistry) -> None:
    """Register core and domain tools without enabling domain toolsets."""

    from . import (
        animation,
        animation_curves,
        animation_layers,
        animation_lifecycle,
        asset_delivery,
        asset_import,
        batch,
        compositor,
        constraints,
        core,
        deformation,
        face_attributes,
        geometry_node_groups,
        geometry_nodes,
        geometry_zone_lifecycle,
        image_delivery,
        image_paint,
        image_portability,
        image_recovery,
        image_recovery_jobs,
        image_revisions,
        image_surface_paint,
        images,
        interaction,
        layout,
        materials,
        mesh,
        mesh_analysis,
        mesh_loops,
        mesh_repair,
        mesh_slide,
        mesh_surface,
        modifiers,
        nla_lifecycle,
        nodes,
        objects,
        paint_jobs,
        python_exec,
        render,
        rig_drivers,
        rig_ik,
        rigging,
        scene_edit,
        scene_variants,
        shader_groups,
        shader_interface,
        shader_settings,
        simulation,
        surface_brushes,
        task_plan,
        transforms,
        uv,
        uv_analysis,
        uv_capture,
        uv_edit,
        uv_layers,
        uv_refine,
        weight_brushes,
        weights,
    )

    core.register_tools(registry)
    task_plan.register_tools(registry)
    animation_curves.register_tools(registry)
    animation_lifecycle.register_tools(registry)
    asset_delivery.register_tools(registry)
    asset_import.register_tools(registry)
    for module in (animation_layers, compositor, simulation, weights):
        module.register_tools(registry)
    nla_lifecycle.register_tools(registry)
    weight_brushes.register_tools(registry)
    batch.register_tools(registry)
    interaction.register_tools(registry)
    layout.register_tools(registry)
    geometry_nodes.register_tools(registry)
    geometry_node_groups.register_tools(registry)
    geometry_zone_lifecycle.register_tools(registry)
    objects.register_tools(registry)
    transforms.register_tools(registry)
    mesh.register_tools(registry)
    face_attributes.register_tools(registry)
    mesh_analysis.register_tools(registry)
    mesh_loops.register_tools(registry)
    mesh_repair.register_tools(registry)
    mesh_slide.register_tools(registry)
    mesh_surface.register_tools(registry)
    surface_brushes.register_tools(registry)
    materials.register_tools(registry)
    images.register_tools(registry)
    image_paint.register_tools(registry)
    image_surface_paint.register_tools(registry)
    image_portability.register_tools(registry)
    image_recovery.register_tools(registry)
    image_recovery_jobs.register_tools(registry)
    paint_jobs.register_tools(registry)
    image_delivery.register_tools(registry)
    image_revisions.register_tools(registry)
    nodes.register_tools(registry)
    shader_groups.register_tools(registry)
    shader_interface.register_tools(registry)
    shader_settings.register_tools(registry)
    uv.register_tools(registry)
    uv_analysis.register_tools(registry)
    uv_capture.register_tools(registry)
    uv_edit.register_tools(registry)
    uv_layers.register_tools(registry)
    uv_refine.register_tools(registry)
    modifiers.register_tools(registry)
    constraints.register_tools(registry)
    animation.register_tools(registry)
    rigging.register_tools(registry)
    rig_drivers.register_tools(registry)
    rig_ik.register_tools(registry)
    deformation.register_tools(registry)
    scene_edit.register_tools(registry)
    scene_variants.register_tools(registry)
    render.register_tools(registry)
    python_exec.register_tools(registry)


__all__ = ["register_all"]
