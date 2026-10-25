"""Explicit MCP wrappers grouped by Blender domain."""

from __future__ import annotations

from collections.abc import Iterable

from ..tool_registry import ToolRegistry
from ._common import MCPToolBinding
from .animation import AnimationTools
from .animation_curve_inspection import AnimationCurveInspectionTools
from .animation_curve_sampling import AnimationCurveSamplingTools
from .animation_curves import AnimationCurveTools
from .animation_lifecycle import ActionLifecycleTools
from .artist import ArtistTools
from .asset_delivery import AssetDeliveryTools
from .asset_import import AssetImportTools
from .batch import BatchTools
from .constraints import ConstraintTools
from .core import CoreTools
from .deformation import DeformationTools
from .geometry_node_groups import GeometryNodeGroupTools
from .geometry_nodes import GeometryNodeTools
from .geometry_preview import GeometryPreviewTools
from .geometry_zone_lifecycle import GeometryZoneLifecycleTools
from .image_portability import ImagePortabilityTools
from .image_recovery import ImageRecoveryTools
from .image_recovery_jobs import ImageRecoveryJobTools
from .image_surface_paint import ImageSurfacePaintTools
from .interaction import InteractionTools
from .layout import LayoutTools
from .materials import MaterialTools
from .mesh import MeshTools
from .mesh_chains import MeshChainTools
from .mesh_slide import MeshSlideTools
from .mesh_surface import MeshSurfaceTools
from .modifiers import ModifierTools
from .nla_lifecycle import NlaLifecycleTools
from .nodes import NodeTools
from .objects import ObjectTools
from .project import ProjectTools
from .python_exec import PythonTools
from .render import RenderTools
from .rig_drivers import RigDriverTools
from .rig_ik import RigIKTools
from .rigging import RiggingTools
from .rigid_body import RigidBodyTools
from .scene import SceneTools
from .scene_edit import SceneEditTools
from .scene_variants import SceneVariantTools
from .shader_interface import ShaderInterfaceTools
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
        RigidBodyTools(registry),
        WeightBrushTools(registry),
        AssetDeliveryTools(registry),
        AssetImportTools(registry),
        NlaLifecycleTools(registry),
        CoreTools(registry),
        TaskPlanTools(registry),
        BatchTools(registry),
        InteractionTools(registry),
        LayoutTools(registry),
        GeometryNodeTools(registry),
        GeometryNodeGroupTools(registry),
        GeometryZoneLifecycleTools(registry),
        ProjectTools(registry),
        SceneTools(registry),
        ViewportTools(registry),
        GeometryPreviewTools(registry),
        SceneEditTools(registry),
        SceneVariantTools(registry),
        ObjectTools(registry),
        TransformTools(registry),
        MeshTools(registry),
        MeshChainTools(registry),
        MeshSlideTools(registry),
        MeshSurfaceTools(registry),
        SurfaceBrushTools(registry),
        UVTools(registry),
        UVRefineTools(registry),
        ModifierTools(registry),
        ConstraintTools(registry),
        MaterialTools(registry),
        ImagePortabilityTools(registry),
        ImageRecoveryTools(registry),
        ImageRecoveryJobTools(registry),
        ImageSurfacePaintTools(registry),
        NodeTools(registry),
        ShaderInterfaceTools(registry),
        RiggingTools(registry),
        RigDriverTools(registry),
        RigIKTools(registry),
        DeformationTools(registry),
        AnimationTools(registry),
        AnimationCurveInspectionTools(registry),
        AnimationCurveSamplingTools(registry),
        AnimationCurveTools(registry),
        ActionLifecycleTools(registry),
        RenderTools(registry),
        PythonTools(registry),
    )
    for bundle in bundles:
        yield from bundle.bindings()


__all__ = ["MCPToolBinding", "iter_bindings"]
