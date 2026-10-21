"""Explicit MCP wrappers grouped by Blender domain."""

from __future__ import annotations

from collections.abc import Iterable

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding
from .animation import AnimationTools
from .animation_curves import AnimationCurveTools
from .artist import ArtistTools
from .asset_delivery import AssetDeliveryTools
from .batch import BatchTools
from .constraints import ConstraintTools
from .core import CoreTools
from .geometry_node_groups import GeometryNodeGroupTools
from .geometry_nodes import GeometryNodeTools
from .image_portability import ImagePortabilityTools
from .interaction import InteractionTools
from .layout import LayoutTools
from .materials import MaterialTools
from .mesh import MeshTools
from .mesh_slide import MeshSlideTools
from .modifiers import ModifierTools
from .nodes import NodeTools
from .objects import ObjectTools
from .project import ProjectTools
from .python_exec import PythonTools
from .render import RenderTools
from .rig_drivers import RigDriverTools
from .rigging import RiggingTools
from .scene import SceneTools
from .scene_edit import SceneEditTools
from .surface_brushes import SurfaceBrushTools
from .task_plan import TaskPlanTools
from .transforms import TransformTools
from .uv import UVTools
from .uv_refine import UVRefineTools
from .viewport import ViewportTools
from .weight_brushes import WeightBrushTools


def iter_bindings(registry: ToolRegistry) -> Iterable[MCPToolBinding]:
    """Yield every static MCP wrapper in stable domain order."""

    bundles = (
        ArtistTools(registry),
        WeightBrushTools(registry),
        AssetDeliveryTools(registry),
        CoreTools(registry),
        TaskPlanTools(registry),
        BatchTools(registry),
        InteractionTools(registry),
        LayoutTools(registry),
        GeometryNodeTools(registry),
        GeometryNodeGroupTools(registry),
        ProjectTools(registry),
        SceneTools(registry),
        ViewportTools(registry),
        SceneEditTools(registry),
        ObjectTools(registry),
        TransformTools(registry),
        MeshTools(registry),
        MeshSlideTools(registry),
        SurfaceBrushTools(registry),
        UVTools(registry),
        UVRefineTools(registry),
        ModifierTools(registry),
        ConstraintTools(registry),
        MaterialTools(registry),
        ImagePortabilityTools(registry),
        NodeTools(registry),
        RiggingTools(registry),
        RigDriverTools(registry),
        AnimationTools(registry),
        AnimationCurveTools(registry),
        RenderTools(registry),
        PythonTools(registry),
    )
    for bundle in bundles:
        yield from bundle.bindings()


__all__ = ["MCPToolBinding", "iter_bindings"]
