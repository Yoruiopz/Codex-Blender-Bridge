"""Explicit MCP wrappers grouped by Blender domain."""

from __future__ import annotations

from collections.abc import Iterable

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding
from .animation import AnimationTools
from .constraints import ConstraintTools
from .core import CoreTools
from .materials import MaterialTools
from .mesh import MeshTools
from .modifiers import ModifierTools
from .nodes import NodeTools
from .objects import ObjectTools
from .project import ProjectTools
from .python_exec import PythonTools
from .render import RenderTools
from .rigging import RiggingTools
from .scene import SceneTools
from .scene_edit import SceneEditTools
from .transforms import TransformTools
from .uv import UVTools
from .viewport import ViewportTools


def iter_bindings(registry: ToolRegistry) -> Iterable[MCPToolBinding]:
    """Yield every static MCP wrapper in stable domain order."""

    bundles = (
        CoreTools(registry),
        ProjectTools(registry),
        SceneTools(registry),
        ViewportTools(registry),
        SceneEditTools(registry),
        ObjectTools(registry),
        TransformTools(registry),
        MeshTools(registry),
        UVTools(registry),
        ModifierTools(registry),
        ConstraintTools(registry),
        MaterialTools(registry),
        NodeTools(registry),
        RiggingTools(registry),
        AnimationTools(registry),
        RenderTools(registry),
        PythonTools(registry),
    )
    for bundle in bundles:
        yield from bundle.bindings()


__all__ = ["MCPToolBinding", "iter_bindings"]
