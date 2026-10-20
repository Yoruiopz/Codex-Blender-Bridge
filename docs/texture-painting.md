# Structured texture canvases, brush versions and pixel evidence

Unreleased on `main`, not in the published 0.3.0 packages. These are actual Blender image
operations through typed bridge tools, not arbitrary Python or an embedded artist service.
They provide bounded **UV-image-space** painting, not full surface/viewport paint coverage.
The [full 1.0 artist scope](release-1.0-readiness.md) is unchanged.

## Tools and consent

Enable the `materials` toolset. Every image mutation requires Object Mode and live Blender
**Edit Materials** permission. These tools never change an existing image's pixels, color
space or binding. New image names must be unique non-control UTF-8, at most 63 bytes.

| Tool | Inputs beyond the exact image name | Blender permission |
| --- | --- | --- |
| `image.create` | `new_name`, `width`, `height`, optional `role="COLOR"`, `color=[0,0,0,1]` | `EDIT_MATERIALS` |
| `image.paint_version` | `image_name`, `new_name`, complete `strokes` | `EDIT_MATERIALS`; FILE sources also need `ACCESS_EXTERNAL_FILES` and approved-path preflight |
| `image.inspect_pixels` | `image_name`, optional `samples=[[x,y],...]` | `INSPECT_SCENE`; FILE sources also need `ACCESS_EXTERNAL_FILES` and approved-path preflight |

Successful generated image creation/painting needs no external-file, raw-Python, deletion or project-save grant.
Verification inside a mutator uses its editing grant; it does not secretly require the separate
inspection grant. Read-only pixel inspection requires its own inspection permission. FILE reads,
even of cached/packed buffers, use the same Blender-controlled [approved-source policy](image-assets.md).
No policy changes, implicit image loading, file writing, packing, saving or forced unlinking occur.

Painting/inspection accept already-loaded local single-view FILE or GENERATED RGBA images.
Blender labels generated image datablocks `UV_TEST` even for a blank generated canvas; that
native type is supported. Render Result, movies, sequences, UDIMs, multiview and other buffer
types are not guessed. Painting rejects actual image animation and non-STRAIGHT alpha roles.
New textures are generated floating-point, straight-alpha images with no fake user or node
binding. Bind the intended new version explicitly through `nodes.set_image`, isolating shared
materials/groups first. Reading a shared source does not change any of its consumers.

## Color and data interpretation

`COLOR` uses **Linear Rec.709** scene-linear RGB in `[0,16]` and straight alpha in `[0,1]`.
`DATA` uses **Non-Color** RGBA in `[0,1]`. The running OCIO configuration must expose the exact
reviewed space; other configurations return `NOT_IMPLEMENTED`, not a guessed conversion.

Painting infers the role from the source. Byte-buffer sRGB values are explicitly converted
with the standard sRGB transfer function; Linear Rec.709 and Non-Color values are copied
without that transform. Float-sRGB and other OCIO input spaces are unsupported. Native probes
on 4.5/5.1 confirmed `Image.pixels` returns encoded sRGB values, not automatically linearized
values. Treating those floats as scene-linear would produce an incorrect new texture.
Alpha is never gamma-transformed. HDR beyond the stated bound, negative/nonfinite painting
values, PREMUL/CHANNEL_PACKED/NONE input and broader color pipelines remain open requirements.

Conversion applies to the **whole new image**, including unpainted areas; it changes storage
encoding/identity, not the intended displayed color. Original stored pixels remain untouched.
`painted_pixels` counts changes relative to the converted baseline, not that encoding change.
Inspect role, new/original digests, untouched sample values and matched appearance separately.

## Brush contract

Each stroke has required `points`, `radius_pixels`, `color`, plus optional `opacity=1`,
`hardness=0.8`, `blend="MIX"`:

```json
{
  "points": [[0.1, 0.2], [0.9, 0.8]],
  "radius_pixels": 6.0,
  "color": [1.0, 0.35, 0.02, 0.7],
  "opacity": 0.8,
  "hardness": 0.8,
  "blend": "MIX"
}
```

Points are explicit UV coordinates in `[0,1]`, bottom-left origin. Pixel `(x,y)` is sampled
at its center `(x+0.5,y+0.5)`. Radius is **image pixels**, so non-square images still use a
circular pixel-space brush. Strokes are round-ended connected capsules; one point is a dot.
The hard core extends to `radius × hardness`, then cubic smoothstep coverage falls to zero
at the radius. `hardness=1` has a hard edge. Image borders clip the stroke; there is no wrapping.
Coverage uses the maximum across segments **within each stroke**, preventing repeated points
and joins from multiplying opacity. Separate strokes accumulate in supplied order.

For COLOR, MIX is straight-alpha source-over. Effective source alpha is geometric coverage ×
opacity × brush alpha; output RGB is correctly unassociated after compositing. ERASE_ALPHA
reduces existing alpha by that coverage while preserving stored RGB. For DATA, only MIX is
reviewed: it interpolates all four channels by geometric coverage × opacity, without color
conversion or interpreting the fourth data channel as compositing coverage.

There are no viewport coordinates, guessed surface targets, brush pressure/spacing/time,
screen-to-surface projection, UV seam wrapping, image masks, stencils, texture layers or
arbitrary brush RNA. Those are still needed for full painting acceptance, as are sculpt,
vertex/weight brush workflows and baking; do not describe this subset as all paint modes.

## Bounds, failure and verification

Dimensions are 1–4,096 each, at most **1,048,576 pixels** total. A request accepts 1–32
strokes, 1–128 points per stroke, 256 total segments and **2,000,000 candidate pixel tests**
summed from clipped segment bounding rectangles. Even overlapping rectangles count against
the work budget. Shape/count/role/footprint validation precedes allocation. Split larger
logical work explicitly; these bounds are not an accepted production-scale ceiling for 1.0.

CPU painting checks cancellation/live grants during source normalization, coverage and pixel
application. Native buffer transfers/allocation/update are bounded but not interruptible.
The tools still run synchronously on Blender's main thread; this is not a responsive background
job. Progress, tiled/large-image work, memory-pressure/canceled-client acceptance and long
native bakes remain in JOB-01, not silently moved out of 1.0.

Complete float32 output readback is compared with the computed image. The original buffer is
independently re-read and hashed after creating a paint version. Creation failure attempts
cleanup of **only** the owned zero-user, non-fake-user image and checks live `DELETE_OBJECTS`
immediately before removal. A missing deletion grant retains that image and reports
`cleanup_permission_denied=true`, `rollback_verified=false` and `possible_mutation=true`.
Inspect the retained image and use explicitly confirmed native recovery, or obtain consent
for `image.remove`; the agent cannot grant itself deletion permission. Unexpected consumers prevent
cleanup even when deletion is permitted. Failed postallocation source
verification retains the new image for reinspection/recovery instead of claiming rollback.
Detailed errors stay local; structured failures retain normal logical history/checkpoint data.

`image.inspect_pixels` returns a SHA-256 digest of every stored RGBA float in little-endian
float32 representation, complete finite-channel ranges/nonfinite counts, and at most 64
requested integer samples. Nonfinite sample/range values become null, never invalid JSON.
It does not return full pixel arrays or silently convert raw storage values to display colors.
A complete digest is not an artistic verdict or proof that a FILE buffer matches its current
disk source. Metadata inspection remains separate through `image.inspect`.

Checkpoint the coherent operation; create/paint, inspect samples/digests, bind only the intended
new version, reinspect node/ownership state, capture the relevant material view, compare with
the brief and protected scope, then refine or recover. A successful call is not visual approval.
Verified native undo of independent versions is not durable backup, image-identity-preserving
pixel undo, packing or save/reopen delivery. Saving still requires an agreed path and permission.

## Native evidence

`blender_texture_paint_smoke.py` exercises color/data canvases, independent standard-sRGB and
source-over sample values, a conversion-only material preview, alpha erasing, original/shared
consumer preservation, permission/pause/stop/mode denial, post-write faults, cancellation,
deletion-denied and unexpected-user cleanup refusal and confirmed native recovery. A 1024² workload checks the
full pixel bound and records create/paint/inspect times rather than asserting a universal latency.
The [reference scanner](field-scanner-workflow.md) batches blue-image revision, painted readiness
accents and exact nested-node binding into one recoverable stage, retaining all source buffers.
Factory scenes/preferences remain isolated; use the [private-desktop runner](native-testing.md).
