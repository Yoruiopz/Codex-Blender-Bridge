"""Explicit MCP wrappers grouped by Blender domain."""

from __future__ import annotations

from collections.abc import Iterable

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding
from .core import CoreTools
from .materials import MaterialTools
from .mesh import MeshTools
from .objects import ObjectTools
from .project import ProjectTools
from .scene import SceneTools
from .transforms import TransformTools
from .viewport import ViewportTools


def iter_bindings(registry: ToolRegistry) -> Iterable[MCPToolBinding]:
    """Yield every static MCP wrapper in stable domain order."""

    bundles = (
        CoreTools(registry),
        ProjectTools(registry),
        SceneTools(registry),
        ViewportTools(registry),
        ObjectTools(registry),
        TransformTools(registry),
        MeshTools(registry),
        MaterialTools(registry),
    )
    for bundle in bundles:
        yield from bundle.bindings()


__all__ = ["MCPToolBinding", "iter_bindings"]
