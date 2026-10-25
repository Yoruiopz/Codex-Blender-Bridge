# Orthographic surface texture painting

`image.paint_surface_version` projects explicit world-plane strokes through a
named mesh onto its explicit base UV layer, and creates a new float image.
`image.paint_surface_job_start` accepts the same operation for the existing
single-owner image scheduler. Acceptance is not completion: retain the connection
and poll `jobs.inspect` or `jobs.list` for the final result and recovery evidence.
Both tools require live `EDIT_MATERIALS` and `INSPECT_SCENE` grants. FILE source or
stencil reads also require live external-file consent and an approved texture path.

The projector specifies `origin`, `direction`, `up`, `width`, `height`, `near` and
`far` in world space. Direction and up must be independent; the bridge normalizes
the frame. Stroke points are normalized bottom-left projector coordinates;
`radius_world` measures distance in its world plane. Smoothstep hardness and the
maximum coverage of a stroke's segments avoid overpainting joins. Strokes then
accumulate in order. This is an explicit orthographic projector, independent of
the current viewport, camera, selection and Blender paint mode.

Supply the source `image_name`, unique `new_name`, `object_name`, `uv_layer`,
`face_indices`, `projector` and `strokes`. Optional `occluder_objects` names the
additional opaque base meshes that block projection. The complete target mesh
also occludes itself. Other scene objects and material transparency are not
inferred. Only geometrically front-facing texel centres are painted. Positive-area
UV overlap touching a scoped face, distinct surface points at a shared UV boundary,
and coincident target/occluder or target-triangle interiors fail closed. Shared
triangulation boundaries mapping to the same surface point with consistent
front-facing classification are deduplicated; disagreement fails in either order.

An optional `stencil` selects `image_name`, raw `channel` R/G/B/A (default R), and
`invert` (default false). Its entire selected channel must be finite within [0,1].
The stencil spans the projector, using normalized pixel-centre bilinear sampling
and edge clamping inside its footprint. Outside the projector is zero, including
inverted stencils. Sampling does not infer luminance, transform colors or undo
alpha association. A Non-Color stencil is usually easiest to reason about.

The source/stencil must be loaded local unanimated simple RGBA buffers. COLOR
uses reviewed byte-sRGB conversion or linear Rec.709 data, straight-alpha
source-over MIX or ERASE_ALPHA; reviewed associated linear float sources normalize
explicitly in private memory. DATA uses Non-Color RGBA [0,1], MIX only. Generated
outputs use native CHANNEL_PACKED to retain independent straight RGBA, including
hidden RGB. Original images, all existing consumers and mesh geometry/UVs remain
unchanged; binding the new result is a separate explicit typed operation. There
are no file writes, packing or project saves.

The implemented limits are:

- Object Mode, visible independent unanimated base meshes, no parenting,
  constraints, modifiers or shape keys; positive nonsingular world transforms.
- Synchronous versions allow at most 1,048,576 pixels in each source and stencil.
  The job variant admits up to 16,777,216 pixels in each (4096 square); dimensions
  remain at most 4096 per axis. Final combined-source 4K deadline, memory and
  interruption qualification is pending; dimension admission alone does not
  establish it. Constrained-memory and reviewed appearance acceptance are separate.
- At most 4096 vertices, 2048 polygons, 12288 loops, 8192 edges and 128 material
  slots per mesh; complete native base tessellation, at most 512 target triangles
  and 1024 triangles across the target plus at most eight explicit occluders.
- One explicit UV layer entirely within [0,1], with 1–256 distinct nonhidden
  target base faces. No UDIM, wrapping or inferred evaluated correspondence.
- At most 32 strokes, 128 points per stroke and 256 total segments. Synchronous
  work retains two million each UV candidate, ray/triangle and segment tests.
  Jobs have explicit caps of 33,554,432 for each counter. A full-UV two-triangle
  4096-square quad alone needs 33,554,432 candidate visits and at least 16,777,216
  segment tests. More complex geometry, occlusion or strokes can exceed a cap
  after acceptance; narrow or explicitly split logical work and restart.

Job acceptance freezes bounded complete image, stencil and geometry facts; it
does not rasterize or build the large stroke footprint. UV overlap checks,
geometry/stencil validation, texel projection, pure frozen triangle visibility
tests, source normalization and private painting yield after start delivery. The
shared scheduler handles owner disconnect, pause, cancellation, emergency stop and
the explicit 1–300 second deadline. Pause holds private work while the deadline
continues. Prepublication cancellation discards private work. No BVH or generic
bake queue is added.

UV ownership uses 64×64 tiles, retaining at most 16 KiB of int32 ownership scratch.
Each tile checks every selected triangle intersecting it in the original triangle
order, including shared-boundary ambiguity outside a brush's actual coverage.
No full-image ownership map or normalized baseline is retained. Changed-pixel
comparison reconstructs the normalized source through Float32 scratch and keeps
global row-major examples; source color/alpha normalization is not counted as
brush work. Packed stencil channels are copied with bounded 4,096-value temporary
slices and pure request checks; complete channel allocation remains blocking.

Blender buffer reads, bounded dependency updates/tessellation, image allocation,
copy/update/readback, full input verification and native undo are not preemptible.
The reported pixel-buffer estimate includes source/output arrays, selected stencil
channel, tile scratch and conservative simultaneous input/output readbacks during
guarded publication. Source validation releases its temporary RGBA before reading
a distinct stencil. At equal 4096-square sizes, kernel arrays are about 576 MiB
plus scratch, while the conservative publication estimate is about 1,088 MiB plus
scratch. These are private-buffer estimates: Python plan/geometry allocations,
native/GPU/undo/file buffers and allocator overhead remain additional. The design
is not out-of-core. A CPU slice is neither a hard latency limit nor a process cap.
Inputs and live grants are rechecked after cancellation/checkpoint callbacks and
immediately before native new-image writes. Stale geometry, UVs, authored/derived
transforms, source/stencil identity/metadata/pixels or FILE proof stop publication.
The actual allocated output must retain its exact identity/name, local editable
unanimated generated role/dimensions, zero users and no native incoming ID
consumers before each further metadata/pixel/update write and final success.
Acquired consumers or output drift stop publication; guarded cleanup retains
such outputs. Native incoming-ID scans are also uninterruptible and their cost
depends on the project. Late failures report the actual retained allocation name
and identity where its handle remains valid, including renamed outputs.

Each job publishes through one finalized native checkpoint. Failures can retain
an allocated output, especially when live `DELETE_OBJECTS` cleanup consent is
absent. Inspect `execution_started`, `possible_mutation`, requested/retained image
names, `external_effects`, and boundary flags; CANCELLED does not promise rollback.
No late scheduler cleanup deletes a published image. Reinspect inputs and output,
then use explicit confirmed native recovery where appropriate. Session history
and unsaved images are not durable delivery.

The private analytic fixture verifies complete independent quad pixels, split UV
seam islands, explicit opaque occlusion, raw bilinear/inverted/outside stencil
sampling and UV overlap rejection. The typed UI fixture checks synchronous/job
pixel agreement, real socket/timer progress, protected consumers, stale UV,
cancel/disconnect, explicit binding, captures and measured output-creation
recovery. It also injects a real material-node consumer immediately after image
allocation and measures that no subsequent output metadata or pixel write occurs;
the fixture then explicitly restores its own injected binding. Evidence must
record the Blender version and actual runner result.
The larger source/stencil admission, tiled scratch and baseline-free comparison
have focused Python coverage. Actual 4096-square native source/stencil/output
hashes, appearance, peak memory, cancellation and completion within the existing
300-second maximum deadline still require a separately retained isolated run.
These bounded fixtures do not establish full PAINT artist acceptance, universal
pixel undo, save/reopen durability, Windows 11 support, arbitrary evaluated meshes,
perspective stencils, multi-material paint slots or production-scale baking.
