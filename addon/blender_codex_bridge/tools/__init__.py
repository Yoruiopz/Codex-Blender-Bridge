"""Registration entry point for built-in structured Blender tools."""

from __future__ import annotations

from ..tool_registry import ToolRegistry


def register_all(registry: ToolRegistry) -> None:
    """Register core and domain tools without enabling domain toolsets."""

    from . import core, materials, mesh, objects, transforms

    core.register_tools(registry)
    objects.register_tools(registry)
    transforms.register_tools(registry)
    mesh.register_tools(registry)
    materials.register_tools(registry)


__all__ = ["register_all"]
