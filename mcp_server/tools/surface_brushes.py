"""Typed explicit-mask base sculpt and point/corner color workflows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding

Number = Annotated[StrictFloat, Field(ge=-1e9, le=1e9, allow_inf_nan=False)]
Vector = Annotated[list[Number], Field(min_length=3, max_length=3)]
Direction = Annotated[list[Annotated[StrictFloat, Field(ge=-1e6, le=1e6, allow_inf_nan=False)]], Field(min_length=3, max_length=3)]
Unit = Annotated[StrictFloat, Field(ge=0., le=1., allow_inf_nan=False)]
Color = Annotated[list[Unit], Field(min_length=4, max_length=4)]
Radius = Annotated[StrictFloat, Field(ge=1e-8, le=1e6, allow_inf_nan=False)]
Indices = Annotated[list[Annotated[StrictInt, Field(ge=0, lt=100_000)]], Field(min_length=1, max_length=10_000)]
Masks = Annotated[list[Unit], Field(min_length=1, max_length=10_000)]


def _distinct_indices(value: list[int]) -> list[int]:
    if len(set(value)) != len(value):
        raise ValueError("Mask sampling vertex indices must be distinct")
    return value


SampleIndices = Annotated[
    list[Annotated[StrictInt, Field(ge=0, lt=100_000)]],
    Field(min_length=1, max_length=1_024, strict=True, json_schema_extra={"uniqueItems": True}),
    AfterValidator(_distinct_indices),
]


def _name(value: str) -> str:
    if not value.strip() or any(ord(char) < 32 for char in value) or len(value.encode("utf-8")) > 63:
        raise ValueError("Names must be nonblank and fit 63 UTF-8 bytes without control characters")
    return value


Name = Annotated[StrictStr, Field(min_length=1, max_length=63), AfterValidator(_name)]


class SculptStroke(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    center: Vector
    radius: Radius = 1.
    operation: Literal["PUSH", "SMOOTH"] = "PUSH"
    direction: Direction | None = None
    strength: Annotated[StrictFloat, Field(ge=-1e6, le=1e6, allow_inf_nan=False)] = .1
    falloff: Literal["SMOOTH", "LINEAR", "CONSTANT"] = "SMOOTH"

    @model_validator(mode="after")
    def valid_operation(self):
        if self.operation == "SMOOTH":
            if self.direction is not None or not 0. <= self.strength <= 1.:
                raise ValueError("SMOOTH needs strength [0,1] and no direction")
        elif self.direction is None or sum(component * component for component in self.direction) < 1e-24:
            raise ValueError("PUSH needs a nonzero explicit direction")
        return self


class ColorStroke(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    center: Vector
    radius: Radius = 1.
    color: Color
    opacity: Unit = 1.
    falloff: Literal["SMOOTH", "LINEAR", "CONSTANT"] = "SMOOTH"


TOOL_DATA = (
    ("mesh.sculpt_brush", "Apply explicit-mask base-mesh PUSH/SMOOTH strokes with protected topology/UV/material evidence.", True, ("EDIT_MESH",)),
    ("mesh.sculpt_mask_sample", "Sample a generated UV image into explicit sculpt-mask weights without changing mesh or image data.", False, ("INSPECT_SCENE",)),
    ("color_attribute.create", "Create a distinct FLOAT_COLOR POINT/CORNER attribute with verified full initialization.", True, ("EDIT_MESH",)),
    ("color_attribute.inspect", "Inspect paginated FLOAT_COLOR entries and a complete raw color digest.", False, ("INSPECT_SCENE",)),
    ("color_attribute.paint", "Paint linear RGBA MIX on explicit vertex-associated POINT/CORNER entries.", True, ("EDIT_MESH",)),
    ("color_attribute.rename", "Rename a color attribute with explicit named-consumer acknowledgment; consumers are not rewritten.", True, ("EDIT_MESH",)),
    ("color_attribute.remove", "Remove a color attribute only with data-loss and named-consumer acknowledgment plus deletion permission.", True, ("EDIT_MESH", "DELETE_OBJECTS")),
)


class SurfaceBrushTools:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def mesh_sculpt_brush(self, object_name: Name, vertex_indices: Indices,
                                strokes: Annotated[list[SculptStroke], Field(min_length=1, max_length=32)],
                                space: Literal["LOCAL", "WORLD"] = "LOCAL", mask_weights: Masks | None = None) -> Any:
        """Object Mode, explicit local editable single-user unmodified base mesh, no shape keys. Bounded geometric brush, not mode entry: PUSH uses a normalized explicit LOCAL/WORLD direction and signed displacement strength; SMOOTH interpolates toward frozen edge-neighbor mean with strength [0,1]. Radius is in the selected coordinate space, under nonuniform transforms too. Explicit unique vertex_indices <=10k; optional matching [0,1] masks protect zero-mask/out-of-scope vertices. 32 strokes, <=500k point tests/2M smoothing neighbor tests; 100k mesh vertices/200k edges/300k corners, <=500k UV/color entries. Hidden scope, modifiers, shared/linked/override data and shape keys fail before publication. Direct coordinate publication verifies complete float32 readback, protected vertices, topology/UVs/materials/other colors and context. Native copies/publication are synchronous. Late failure/cancel may follow a write and retains truthful possible_mutation/checkpoint evidence; no compensating edit after revocation, implicit save or full sculpt/viewport/multires acceptance."""
        values = {"object_name": object_name, "vertex_indices": vertex_indices,
                  "strokes": [stroke.model_dump(exclude_none=True) for stroke in strokes], "space": space}
        if mask_weights is not None:
            values["mask_weights"] = mask_weights
        return await self.registry.call("mesh.sculpt_brush", values)

    async def mesh_sculpt_mask_sample(self, object_name: Name, uv_layer: Name, vertex_indices: SampleIndices,
                                      image_name: Name, corner_reduction: Literal["MIN", "MAX", "MEAN"],
                                      channel: Literal["R", "G", "B", "A"] = "R", invert: StrictBool = False) -> Any:
        """Read a named Object Mode base mesh/UV layer and a local loaded unanimated GENERATED RGBA image into ordered numeric mask_weights for 1-1,024 explicit distinct vertices. Every requested vertex must have a UV corner; each relevant stored UV must be finite in [0,1]. Sample the raw R/G/B/A channel using normalized-UV pixel-centre bilinear interpolation with edge clamping, then explicitly reduce seam corners by MIN, MAX or MEAN. No color/alpha conversion. The complete chosen channel must be finite in [0,1], with each image dimension in1-4,096 and at most16,777,216 total pixels (4,096 squared); mesh bounds are100k vertices/200k edges/300k corners. Shared/library mesh reads remain available; images must be local generated data. Return weights, corner/seam observations and frozen image/UV/topology fingerprints; stale input or context causes refusal. No image, geometry, selection, frame or checkpoint write. Weights are a snapshot, not a live image binding: resample after image/UV/topology changes, then explicitly pass the returned vertex_indices and mask_weights to mesh.sculpt_brush under its own edit/ownership checks. Complete image/channel hashes and bounded channel-copy/validation safe points retain the exact readonly tool identity. Synchronous read only: no job ID, asynchronous progress or jobs.cancel; allocation/native pixel copying/complete hashing can block until return, with cancellation/disconnect/deadline checks between steps. At4K, RGBA plus selected channel use about320MiB before native/GPU/geometry/allocator overhead; not a process cap or out-of-core read. Actual native4K, constrained-memory, full sculpt, durable backup and release acceptance remain unqualified."""
        return await self.registry.call("mesh.sculpt_mask_sample", {
            "object_name": object_name, "uv_layer": uv_layer, "vertex_indices": vertex_indices,
            "image_name": image_name, "corner_reduction": corner_reduction, "channel": channel, "invert": invert,
        })

    async def color_attribute_create(self, object_name: Name, attribute_name: Name,
                                     domain: Literal["POINT", "CORNER"] = "POINT", initial_color: Color | None = None) -> Any:
        """Create a unique native FLOAT_COLOR attribute on a local single-user unmodified Object Mode mesh without shape keys. POINT stores one scene-linear RGBA per vertex; CORNER stores one per face corner. Optional initial_color [0,1], default opaque black; all values are read back. No overwrite or material binding; geometry/UV/material/other-color/context preserved. Max16 color attributes/500k combined UV+color entries. Existing active/render indices are preserved; the first attribute may become active. Failed owned allocation cleanup additionally requires DELETE_OBJECTS and live edit state; otherwise exact retained attribute and possible mutation are reported. No save or full vertex-paint acceptance."""
        values: dict[str, Any] = {"object_name": object_name, "attribute_name": attribute_name, "domain": domain}
        if initial_color is not None:
            values["initial_color"] = initial_color
        return await self.registry.call("color_attribute.create", values)

    async def color_attribute_inspect(self, object_name: Name, attribute_name: Name,
                                      offset: Annotated[StrictInt, Field(ge=0, le=300_000)] = 0,
                                      max_entries: Annotated[StrictInt, Field(ge=1, le=64)] = 32) -> Any:
        """Read FLOAT_COLOR POINT/CORNER data in Object Mode, including shared/library mesh inspection. Bounded pages (<=64) plus complete raw float32 digest; explicit truncation/next_offset. Native scene-linear RGBA, no display conversion, mode mutation or appearance certificate. INSPECT_SCENE required, at most100k vertices/300k corners and500k UV/color entries."""
        return await self.registry.call("color_attribute.inspect", {"object_name": object_name, "attribute_name": attribute_name,
                                                                    "offset": offset, "max_entries": max_entries})

    async def color_attribute_paint(self, object_name: Name, attribute_name: Name, vertex_indices: Indices,
                                    strokes: Annotated[list[ColorStroke], Field(min_length=1, max_length=32)],
                                    space: Literal["LOCAL", "WORLD"] = "LOCAL", mask_weights: Masks | None = None) -> Any:
        """Object Mode explicit-mask vertex-color painting on local single-user unmodified base meshes without shape keys. FLOAT_COLOR POINT/CORNER only; every corner associated with a scoped vertex receives the same geometric influence while retaining its prior color. Strokes MIX scene-linear RGBA [0,1] using opacity, radius, falloff and optional per-vertex masks; no implicit sRGB conversion, alpha-over or viewport projection. Out-of-scope/zero-mask/out-of-radius entries are protected. <=10k indices/32strokes/500k entry-tests, complete full-attribute readback plus geometry/UV/material/other-color/context checks. Late publication failure retains possible mutation for inspection/checkpoint recovery. No material node creation or project save; verify appearance independently."""
        values = {"object_name": object_name, "attribute_name": attribute_name, "vertex_indices": vertex_indices,
                  "strokes": [stroke.model_dump() for stroke in strokes], "space": space}
        if mask_weights is not None:
            values["mask_weights"] = mask_weights
        return await self.registry.call("color_attribute.paint", values)

    async def color_attribute_rename(self, object_name: Name, attribute_name: Name, new_name: Name,
                                     acknowledge_named_consumers: StrictBool = False) -> Any:
        """Rename one FLOAT_COLOR attribute without overwriting another attribute or rewriting material/GN references. Explicit acknowledge_named_consumers=true is mandatory: direct material/nested shader consumers are listed within32trees/1024nodes, while dynamic/transitive GN consumers may also exist. Object Mode single-user local unmodified unkeyed mesh only. Complete values and other protected geometry/attributes/context verified; no binding or save."""
        return await self.registry.call("color_attribute.rename", {"object_name": object_name, "attribute_name": attribute_name,
            "new_name": new_name, "acknowledge_named_consumers": acknowledge_named_consumers})

    async def color_attribute_remove(self, object_name: Name, attribute_name: Name, confirm_remove: StrictBool = False,
                                     acknowledge_named_consumers: StrictBool = False) -> Any:
        """Remove one FLOAT_COLOR attribute only with confirm_remove=true and acknowledge_named_consumers=true. Requires EDIT_MESH+DELETE_OBJECTS on local single-user unmodified Object Mode unkeyed mesh. Named material/GN consumers are not rewritten; bounded direct material evidence and unknown transitive scope are explicit. Other attributes/geometry/UV/material/context verified; active color may change. Native checkpoint recovery is not guaranteed; no project save."""
        return await self.registry.call("color_attribute.remove", {"object_name": object_name, "attribute_name": attribute_name,
            "confirm_remove": confirm_remove, "acknowledge_named_consumers": acknowledge_named_consumers})

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        methods: tuple[Callable[..., Any], ...] = (self.mesh_sculpt_brush, self.mesh_sculpt_mask_sample, self.color_attribute_create, self.color_attribute_inspect,
                                                self.color_attribute_paint, self.color_attribute_rename, self.color_attribute_remove)
        return tuple(MCPToolBinding(data[0], method, method.__doc__ or "") for data, method in zip(TOOL_DATA, methods, strict=True))


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(remote_tool(name, toolset="mesh", description=description, modifying=modifies,
                             required_permissions=permissions) for name, description, modifies, permissions in TOOL_DATA)
