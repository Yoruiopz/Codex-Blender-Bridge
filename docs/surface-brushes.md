# Explicit sculpt and vertex-color brushes

Unreleased development tools, not in 0.3.0. These tools perform actual bounded
geometry/color edits through typed APIs. They do not claim complete sculpting,
viewport/surface-projected texture painting, multires or full artist acceptance.

## Explicit base-mesh scope

All modifying tools require **Edit Mesh**, Object Mode, and an explicitly named
local, editable, single-user mesh. They reject shape keys, modifiers, linked or
override data and hidden target vertices. They do not silently enter a mode,
change selection, make data local or copy a protected duplicate.

Brushes accept unique `vertex_indices` and optional corresponding `mask_weights`
in `[0,1]`. Only those vertices, or their associated color entries, are eligible;
zero-mask and out-of-radius components remain unchanged. Indices refer to the
current base mesh, so reinspect after topology edits or file/session changes.
There is no guessed correspondence to evaluated geometry or a screenshot.

`space="LOCAL"` uses mesh coordinates and local radius/displacement units.
`space="WORLD"` uses measured world coordinates, correctly accounting for
nonuniform object transforms; singular matrices are refused. An unchanged world
point is never moved merely by a local/world round trip.

## Sculpting

`mesh.sculpt_brush(object_name, vertex_indices, strokes, space, mask_weights)`
supports a list of 1–32 strokes with an explicit center and radius:

- **PUSH** uses a nonzero direction, normalized in the chosen space, and signed
  displacement `strength`. It is an explicit geometric displacement rather than
  an inferred normal/inflate brush.
- **SMOOTH** uses `strength` in `[0,1]` to interpolate toward the mean of connected
  edge-neighbor coordinates. Each stroke reads a frozen pre-stroke mesh, so index
  order cannot feed updated coordinates into later neighbors. Isolated vertices
  remain unchanged. Protected neighbors can contribute measured positions while
  remaining unmodified themselves.

`SMOOTH`, `LINEAR`, or `CONSTANT` radial falloff multiplies the component mask and
strength. Stroke order is explicit. Full float32 coordinate readback verifies the
result, including all protected vertices. Topology, UV coordinates/pins and active
UV layer, material bindings, other color attributes, component flags, active/render
color roles and mode/selection/active-object context are checked independently.

## Color attribute lifecycle and painting

`color_attribute.create` creates a unique native **FLOAT_COLOR** attribute in
`POINT` or `CORNER` domain with complete verified initialization. RGBA values are
native scene-linear channels; the API performs no display/sRGB conversion. There
is no automatic shader/node binding. Existing active/render color indices are
preserved; the first attribute may become active.

`color_attribute.inspect` returns up to 64 entries, a complete raw float32 color
digest, explicit truncation and `next_offset`. It requires **Inspect Scene** and
permits bounded shared/library inspection. It rejects a changed attribute/name/ID
or values rather than mixing old pixels with new metadata.

`color_attribute.paint` uses the same explicit vertex mask and radial spaces.
POINT paints the corresponding vertex entries. CORNER paints every corner
associated with a scoped vertex, retaining each corner's distinct prior color.
Each stroke linearly mixes RGBA toward its requested `[0,1]` color using opacity,
falloff and mask. This is RGBA MIX, not alpha source-over or a complete brush blend
library. Geometry, UVs, materials, other colors and context are preserved and
complete color readback is verified.

`color_attribute.rename` requires an unused new name and
`acknowledge_named_consumers=true`. `color_attribute.remove` additionally requires
`confirm_remove=true` and **Delete Objects** permission. Neither rewrites material
or Geometry Nodes name references. Bounded direct material/nested shader consumers
are reported; shared trees are deduplicated, so additional material paths may be
omitted. Dynamic/transitive Geometry Nodes consumers may exist. The explicit
acknowledgment applies to those name-based effects, not permission to edit other
datablocks. Removal can change active color selection.

## Bounds, failure and recovery

The current synchronous limits are 100,000 vertices, 200,000 edges, 300,000 corners,
16 color attributes, 500,000 combined UV/color entries, 10,000 scoped vertices,
32 strokes, 500,000 brush candidate tests and 2,000,000 smoothing-neighbor tests.
Preservation also bounds selected-object context to 256 objects and named shader
inspection to 32 trees/1,024 nodes. Narrow a task instead of treating truncated
scope as safe.

Permission, stop/pause, ownership, original ID/data, context and complete input
evidence are rechecked before publication. Final deletion checks run before the
last frozen-scope validation, so callbacks cannot expand a deletion onto newly
shared data. Failed attribute initialization removes only the exact owned
attribute when live deletion/edit consent and original single-user scope still
allow it; otherwise its actual last-observed retained name is reported.

Native `foreach_set`/update/readback is synchronous. Cancellation, revocation or
an exception can arrive after part or all of a write. Such errors explicitly
return `execution_started`, `possible_mutation`, `rollback_verified=false` and
verification requirements. They do not perform a compensating edit after stop or
revocation and do not equate a canceled call with rollback. Reinspect and use
confirmed checkpoint recovery only when its actual availability is established.
No tool saves the project or claims native global undo has been accepted here.

## Native development evidence

The isolated `surface_brushes` fixture checks real PUSH/SMOOTH, world-space brushes
under nonuniform scale, POINT/CORNER painting, color lifecycle, actual shared-mesh
and shape-key denial, permission failure, protected duplicate/UV/material/context
and truthful late-cancellation evidence. Matched 96-pixel Cycles CPU captures show
a localized color/silhouette revision. This is visible functional evidence, not a
production artistic-quality review.

Linux Blender 4.3.2 development evidence does not qualify Windows 4.5/5.x. Native
UI undo/redo and manual interleaving, pressure/production-scale acceptance,
viewport projection, sculpt masks from painted textures, multires and the full
artist workflow remain open in the release ledger.
