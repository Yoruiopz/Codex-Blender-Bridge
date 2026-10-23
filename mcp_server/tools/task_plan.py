"""Typed MCP wrappers for artist plans, references and opt-in protection."""

from __future__ import annotations

from typing import Any, Literal

from typing_extensions import TypedDict

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params
from .scene import EvidenceField

StepStatus = Literal["pending", "in_progress", "completed", "blocked"]
ReferenceSource = Literal["selection", "objects"]
RotationMode = Literal["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX", "QUATERNION", "AXIS_ANGLE"]


class _RequiredStep(TypedDict):
    id: str
    description: str


class PlanStep(_RequiredStep, total=False):
    status: StepStatus
    note: str


TOOL_DATA = (
    ("task.plan.set", False, ("INSPECT_SCENE",), "Create/correct a bounded artist plan with advisory protected objects; replacement requires current revision."),
    ("task.plan.inspect", False, ("INSPECT_SCENE",), "Inspect runtime plan steps, revision and current protected-scope policy."),
    ("task.plan.update", False, ("INSPECT_SCENE",), "Correct an exact step's status/note at the expected plan revision."),
    ("task.plan.capture", False, ("INSPECT_SCENE",), "Capture bounded structural evidence for exact protected scope without enabling enforcement."),
    ("task.plan.compare", False, ("INSPECT_SCENE",), "Explicitly compare protected scope with its transient baseline; incomplete coverage is not preservation proof."),
    ("task.plan.persist", True, ("INSPECT_SCENE", "EDIT_SCENE"), "Explicitly store validated plan JSON in a scene property; never saves the project."),
    ("task.plan.load", False, ("INSPECT_SCENE",), "Explicitly validate/load saved scene JSON as plan data; never executes text or restores session baselines."),
    ("task.plan.clear", False, ("INSPECT_SCENE",), "Clear runtime plan only; scene-stored JSON remains until explicitly replaced."),
    ("task.plan.enforce", False, ("INSPECT_SCENE",), "Explicitly enable/disable runtime protected scope; unreviewed modifying tools fail closed while enabled."),
    ("task.reference.resolve", False, ("INSPECT_SCENE",), "Resolve exact object names/current selection to bounded runtime references without granting authority."),
    ("task.plan.preview_transform", False, ("INSPECT_SCENE",), "Preview exact transform channels and reviewed affected consumers without editing or acquiring edit authority."),
    ("task.plan.apply_preview", True, ("INSPECT_SCENE", "TRANSFORM_OBJECTS"), "Apply an exact runtime transform preview once after renewed permission, identity, context and consumer checks."),
)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, modifying=modifies, required_permissions=permissions, description=description) for name, modifies, permissions, description in TOOL_DATA)


class TaskPlanTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def task_plan_set(self, goal: str, steps: list[PlanStep], protected_objects: list[str] | None = None, expected_revision: int | None = None) -> Any:
        """Create/correct 1-32 plan steps and up to 32 exact protected objects. Scope is advisory; capture/compare explicitly. Plans survive MCP reconnect; replacement requires expected_revision."""
        return await self.registry.call("task.plan.set", params(goal=goal, steps=steps, protected_objects=protected_objects, expected_revision=expected_revision))

    async def task_plan_inspect(self) -> Any:
        """Inspect the bounded runtime plan; stored project text is never automatically executed."""
        return await self.registry.call("task.plan.inspect")

    async def task_plan_update(self, step_id: str, expected_revision: int, status: StepStatus | None = None, note: str | None = None) -> Any:
        """Correct one step's status/note at an expected revision; this does not prove its Blender outcome."""
        return await self.registry.call("task.plan.update", params(step_id=step_id, expected_revision=expected_revision, status=status, note=note))

    async def task_plan_capture(self, fields: list[EvidenceField] | None = None, max_elements: int = 200000) -> Any:
        """Capture exact current protected objects for explicit structural comparison; scope is advisory and evidence can be incomplete."""
        return await self.registry.call("task.plan.capture", params(fields=fields, max_elements=max_elements))

    async def task_plan_compare(self, max_elements: int | None = None, step_id: str | None = None, expected_revision: int | None = None) -> Any:
        """Compare the plan's protected baseline. Optional step_id plus current expected_revision attaches this protected-objects-only observation to that step's latest retained outer operation receipt. Receipt observations are historical facts, may become stale/unknown, and never verify target edits, appearance or completion."""
        return await self.registry.call("task.plan.compare", params(max_elements=max_elements, step_id=step_id, expected_revision=expected_revision))

    async def task_plan_persist(self, expected_revision: int, confirm: bool = False) -> Any:
        """With explicit confirmation and EDIT_SCENE, store validated JSON in the scene for a later authorized save. Does not save or write external files."""
        return await self.registry.call("task.plan.persist", {"expected_revision": expected_revision, "confirm": confirm})

    async def task_plan_load(self, expected_revision: int | None = None) -> Any:
        """Explicitly load bounded schema-v1 plan data from this scene; require revision when replacing an active plan. No baseline or authority is loaded."""
        return await self.registry.call("task.plan.load", params(expected_revision=expected_revision))

    async def task_plan_clear(self, expected_revision: int) -> Any:
        """Clear the current runtime plan at its expected revision; the stored scene property is retained."""
        return await self.registry.call("task.plan.clear", {"expected_revision": expected_revision})

    async def task_plan_enforce(self, enabled: bool, expected_revision: int) -> Any:
        """Explicitly enable/disable live protected scope. Enabled plans deny unreviewed modifying tools; saved plans never restore enforcement."""
        return await self.registry.call("task.plan.enforce", {"enabled": enabled, "expected_revision": expected_revision})

    async def task_reference_resolve(self, source: ReferenceSource, object_names: list[str] | None = None) -> Any:
        """Resolve current selection or exact object names to a bounded runtime token; visual/pronoun intent is never guessed and no edit authority is granted."""
        return await self.registry.call("task.reference.resolve", params(source=source, object_names=object_names))

    async def task_plan_preview_transform(self, reference_id: str, expected_revision: int, object_name: str | None = None,
                                          location: list[float] | None = None, rotation: list[float] | None = None,
                                          scale: list[float] | None = None, rotation_mode: RotationMode | None = None, step_id: str | None = None) -> Any:
        """Preview one referenced object's exact transform.set channels and affected-consumer scope. Optional step_id freezes provenance for this exact current step/runtime generation; apply cannot retarget it. Status/note corrections do not imply completion. Read-only; never grants or requires transform authority."""
        return await self.registry.call("task.plan.preview_transform", params(reference_id=reference_id, expected_revision=expected_revision,
                                        object_name=object_name, location=location, rotation=rotation, scale=scale, rotation_mode=rotation_mode, step_id=step_id))

    async def task_plan_apply_preview(self, preview_id: str, expected_revision: int) -> Any:
        """Consume and apply one current preview after live permission and exact authored/context/consumer checks; stale previews fail closed."""
        return await self.registry.call("task.plan.apply_preview", {"preview_id": preview_id, "expected_revision": expected_revision})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        return tuple(MCPToolBinding(name, getattr(self, name.replace(".", "_")), getattr(self, name.replace(".", "_")).__doc__ or "") for name, _modifies, _permissions, _description in TOOL_DATA)
