# Explicit sculpt masks and vertex-color brushes

Bounded structured tools introduced after 0.3.0, with the 4K mask-read profile in
the published 0.5.0 alpha. These tools perform actual bounded
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

## Sample a painted UV image into a sculpt mask

`mesh.sculpt_mask_sample(object_name, uv_layer, vertex_indices, image_name,
corner_reduction, channel="R", invert=false)` reads an explicit base mesh and UV
layer into ordered numeric `mask_weights`. It requires **Inspect Scene** and
Object Mode. Inspection can read shared or library meshes; the later sculpt edit
still applies its own local, single-user ownership checks.

The image must be local, loaded, unanimated **GENERATED** four-channel RGBA data,
with each dimension from 1 to 4,096 and at most 16,777,216 total pixels (4,096²). The complete
chosen raw R/G/B/A channel must be finite in `[0,1]`. File images, UDIMs, sequences and evaluated image animation are
outside this bounded contract; no file is loaded and no external path is read.
Stored channel values receive no color-space or alpha conversion.

Name the UV layer and provide 1–1,024 distinct vertex indices in the desired
output order. Each requested vertex must have at least one UV corner, and every
relevant stored UV must be finite in `[0,1]`. Sampling aligns UVs with image pixel
centres, interpolates bilinearly and clamps at the edges. At seams, the tool
samples every corner separately and applies optional inversion before the
required `corner_reduction`: **MIN**, **MAX** or **MEAN**. This makes the choice of
protecting or including a split UV vertex explicit.

The result returns the matching `vertex_indices` and `mask_weights`, corner/seam
observations and image/UV/topology fingerprints. Pass these lists explicitly to
`mesh.sculpt_brush` to use the sampled region. Weights are a snapshot of that
read, not a live image binding or a backup: resample after image, UV or topology
changes. A later sculpt call does not revalidate the earlier image fingerprint.

Sampling changes no image, geometry, selection, frame or checkpoint. It refuses
changed input/context rather than returning a mixture of old pixels and newer
UVs. Mesh inspection is bounded to 100,000 vertices, 200,000 edges and 300,000
corners. Complete RGBA and selected-channel hashes cover the entire image, not
only sampled UV corners. Selected-channel copying uses bounded chunks of at most
4,096 Float32 values; validation also checks the complete channel at pure request
safe points. The original RGBA copy is released before the independent final
full-image read and mesh/UV/context comparison.

This remains a **synchronous read**, with no job ID, asynchronous progress or
`jobs.cancel` support. Cancellation, disconnect and deadline flags are checked
between bounded CPU steps. Native pixel capture, allocation, bulk copying and
complete hashing can block until their current call returns; these checks do
not make them preemptible. Inspection remains available while edits are paused
or emergency-stopped. Pure checks retain the exact read-only tool identity and
toolset; they do not invoke permission providers during the final frozen proof.

At 4,096², the RGBA copy is 256 MiB and the selected channel is 64 MiB, plus
bounded copy scratch and mesh/UV evidence. This roughly 320 MiB array estimate
excludes Blender/native/GPU buffers, Python/allocator overhead and unrelated
images; it is not a process-memory guarantee or an out-of-core algorithm.
Published 0.5.0 has selected [4K native evidence](releases/0.5.0.md#verified-evidence).
Later-source qualification, constrained-memory acceptance, reviewed production
sculpt quality and complete artist/recovery acceptance remain open; this admission
profile does not close PAINT-01 or A05.

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

Publication finishes live permission providers and cancellation callbacks before
the final target, ownership, context and protected-state comparisons. A
callback-free caller/deadline, toolset and pause/stop check then runs immediately
before writing. Sculpt and color operations use their exact registered method;
attribute identity/content and create/rename destinations are checked again at
the same boundary. A provider's newer coordinates, changed mesh consumers or occupied
destination cause refusal rather than a stale write or automatic overwrite.

The negative `surface_publication_probe` at local source `13668d2` reproduced
the previous ordering gap on Linux Blender 4.5.14 and 5.2.2. Four controls and five
provider probes per build showed writes after pause or changed input/scope,
including an overwritten coordinate and removal from a newly shared consumer.
Those reports explicitly reject guard acceptance. Corrected source requires its
own positive, source-matched results; the historical negative probe is retained.

Initial corrected-source testing at `ec821d8` exposed an incorrect allocation
prediction despite passing portable tests. Both Linux builds directly measured
new POINT and CORNER `FLOAT_COLOR` layers as white RGBA `(1, 1, 1, 1)`. The failed
native reports and early complete-value captures are retained. Allocation
verification and the test doubles now use that measured literal state; an
unexpected allocation remains an explicit failure with retained-state evidence.

The current synchronous limits are 100,000 vertices, 200,000 edges, 300,000 corners,
16 color attributes, 500,000 combined UV/color entries, 10,000 scoped vertices,
32 strokes, 500,000 brush candidate tests and 2,000,000 smoothing-neighbor tests.
Preservation also bounds selected-object context to 256 objects and named shader
inspection to 32 trees/1,024 nodes. Narrow a task instead of treating truncated
scope as safe.

Permission, stop/pause, ownership, original ID/data, context and complete input
evidence are rechecked before publication. Final deletion checks run before the
last frozen-scope validation, so callbacks cannot expand a deletion onto newly
shared data. Coordinate and owned-color comparisons preserve Float32 bytes,
including signed zero. Creation also checks the prior active/render color roles
after callbacks, before restoring any captured role.

Failed creation attempts cleanup only with a previously verified owned attribute
state, matching complete colors/roles, live deletion/edit consent and the original
single-user scope. Unknown partial initialization or a newer manual edit retains
the allocation with its last-observed name. Permission, toolset, caller-lifetime,
pause or stop loss latches cleanup off for that failed operation, including after
a later regrant. Errors retain the original failure and explicit cleanup evidence.

Native `foreach_set`/update/readback is synchronous. Cancellation, revocation or
an exception can arrive after part or all of a write. Such errors explicitly
return `execution_started`, `possible_mutation`, `rollback_verified=false` and
verification requirements. They do not perform a compensating edit after stop or
revocation and do not equate a canceled call with rollback. Reinspect and use
confirmed checkpoint recovery only when its actual availability is established.
No tool saves the project or claims native global undo has been accepted here.
CustomData wrapper addresses are session-local and can change during allocation;
these bounded checks do not establish durable identity across undo or reload.

## Native development evidence

The isolated `surface_brushes` fixture checks real PUSH/SMOOTH, world-space brushes
under nonuniform scale, POINT/CORNER painting, color lifecycle, actual shared-mesh
and shape-key denial, permission failure, protected duplicate/UV/material/context
and truthful late-cancellation evidence. Matched 96-pixel Cycles CPU captures show
a localized color/silhouette revision. This is visible functional evidence, not a
production artistic-quality review.

Linux Blender 4.3.2 development evidence does not qualify Windows 4.5/5.x. Native
UI undo/redo and manual interleaving, pressure/production-scale acceptance,
viewport projection, production-scale painted sculpt masks, multires and the full
artist workflow remain open in the release ledger. The generated-image mask
sampler requires its own source-matched native workflow evidence before acceptance.
