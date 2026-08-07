"""Registration entry point for built-in structured Blender tools."""

from __future__ import annotations

from ..tool_registry import ToolRegistry


def register_all(registry: ToolRegistry) -> None:
    """Register core and domain tools without enabling domain toolsets."""

    from . import (
        animation,
        constraints,
        core,
        materials,
        mesh,
        modifiers,
        nodes,
        objects,
        python_exec,
        render,
        rigging,
        scene_edit,
        transforms,
        uv,
    )

    core.register_tools(registry)
    objects.register_tools(registry)
    transforms.register_tools(registry)
    mesh.register_tools(registry)
    materials.register_tools(registry)
    nodes.register_tools(registry)
    uv.register_tools(registry)
    modifiers.register_tools(registry)
    constraints.register_tools(registry)
    animation.register_tools(registry)
    rigging.register_tools(registry)
    scene_edit.register_tools(registry)
    render.register_tools(registry)
    python_exec.register_tools(registry)


__all__ = ["register_all"]
