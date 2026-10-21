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
| `image.create` | `new_name`, `width`, `height`, optional `role="COLOR"`, `color=[0,0,0,1]`; up to 4K square | `EDIT_MATERIALS` |
| `image.paint_version` | `image_name`, `new_name`, complete `strokes`, optional `mask` | `EDIT_MATERIALS`; FILE sources/masks also need `ACCESS_EXTERNAL_FILES` and approved-path preflight |
| `image.paint_job_start` | Same brush inputs plus `time_limit_seconds=60`; inspect/cancel by returned job ID | Same edit/file grants; separate polling needs `INSPECT_SCENE` |
| `image.inspect_pixels` | `image_name`, optional `samples=[[x,y],...]`, `include_statistics=true`; explicit false for larger digest-only reads | `INSPECT_SCENE`; FILE sources also need `ACCESS_EXTERNAL_FILES` and approved-path preflight |

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
screen-to-surface projection, UV seam wrapping, viewport stencils, texture layers or
arbitrary brush RNA. Those are still needed for full painting acceptance, as are sculpt,
vertex/weight brush workflows and baking; do not describe this subset as all paint modes.

## UV-image channel masks

Both painting entry points accept one optional operation-level mask:

```json
{"image_name":"Paint Mask", "channel":"R", "invert":false}
```

`channel` is exactly `R`, `G`, `B` or `A` (default `R`); inversion defaults to false.
The mask must be an already-loaded, local, simple four-channel FILE/GENERATED image without
animation. **Non-Color is recommended**, but sampling explicitly uses the selected stored raw
channel: no sRGB transfer, luminance inference, unpremultiply or alpha-role reinterpretation.
Other stored channels are not used as weights; they may contain HDR/nonfinite values. The
**entire selected channel** must be finite in `[0,1]`, including pixels outside the stroke.
The full RGBA digest still detects changes to any channel. No implicit load/reload occurs.

Mask dimensions can differ from the canvas. For target pixel `(x,y)`, sampling uses
`fx=(x+0.5)/canvas_width*mask_width-0.5` (and the corresponding `fy`), clamped to the mask edges,
then bilinear interpolation. Equal dimensions read the exact corresponding stored pixel.
Inversion is `1-weight`. This weight multiplies each stroke's maximum geometric coverage ×
opacity, before COLOR brush alpha or DATA RGBA mixing. Zero weight prevents a brush edit;
whole-image byte-sRGB-to-linear conversion still happens in the output even with a zero mask.
There is no UV wrapping, surface projection or sculpt/vertex masking in this contract.

Both source and mask are read-only. A source may also serve as its own mask. Synchronous
painting limits **each** input to 1,048,576 pixels; jobs allow each up to 16,777,216 pixels and
4,096 per axis, with a packed float32 selected-channel array. Jobs validate that channel in
cooperative slices and freeze/revalidate the mask identity, metadata, animation, approved-file
evidence and full pixel digest before/after checkpoint setup and after publication. FILE
**masks** require live external-file consent even with a generated canvas. New result metadata
includes `mask` (null when absent), sampling/value-space details and independent preservation
digests. Masked memory estimates conservatively include source/output/readback, mask RGBA
revalidation/channel arrays and coverage scratch; native/GPU/undo/allocator costs remain excluded.

A stale mask fails publication; a change observed after allocation retains truthful possible-
mutation and finalized-boundary evidence. Confirmed undo can remove the new output, but native
global undo **does not reliably restore externally edited existing image pixels**. Reinspect both
inputs; never silently overwrite the user's external mask edit using the frozen weights.
Durable full-image recovery remains open 1.0 work. These are UV-image masks, not full paint-mode
acceptance or a reason to drop viewport stencils, sculpt/vertex masks or surface painting.

## Bounds, failure and verification

Dimensions are 1–4,096 each. Generated canvas creation and cooperative paint jobs support
**16,777,216 pixels** (4K square). Synchronous `image.paint_version` remains limited to
**1,048,576 pixels**; use jobs above that size. Full inspector channel statistics retain the
same 1M limit; explicit `include_statistics=false` permits complete 16M digests/samples without
the channel-range/nonfinite scan. Native copying/allocation/readback and checkpoint calls remain
non-preemptible, even when CPU painting is cooperative. Larger work can need a longer explicit
job deadline; do not confuse it with the Blender-only CPU-slice setting.

A request accepts 1–32 strokes, 1–128 points per stroke, 256 total segments and
**2,000,000 candidate pixel tests**, summed from clipped segment rectangles within conservative
64×64 tile-row bands. A long diagonal no longer scans its entire enclosing rectangle. Repeated/
overlapping segment regions still count separately. Shape/count/role/footprint validation and
cancellation checks precede the owned pixel copy. This is not a distance-based approximation:
each retained candidate uses the same pixel-center capsule and maximum-coverage math.

Coverage scratch is at most **32 KiB** of float64 values, preserving the prior double-precision
stroke semantics. There is no full normalized baseline array: only union tiles are compared
against the frozen source, with explicit float32 sRGB normalization when needed. Examples keep
global row-major order. Digests hash the contiguous array buffer without making a second whole
bytes image on little-endian hosts. Pixel-buffer estimates exclude Python plan metadata,
Blender/native/GPU/undo/file storage and allocator overhead; they are not memory caps.
Split work exceeding the candidate budget explicitly. 8K/UDIM, memory-pressure and broader
production throughput acceptance remain required 1.0 work, not an accepted final ceiling.

CPU painting checks cancellation/live grants during source normalization, coverage and pixel
application. Native buffer transfers/allocation/update are bounded but not interruptible.
`image.paint_version` remains synchronous. Optional [cooperative painting jobs](painting-jobs.md)
yield CPU work between main-thread timer slices, with polled progress and guarded publication.
Native transfers, complete final validation and undo are not preemptible. Tiled/large-image work,
memory-pressure/production-scale canceled-client acceptance and long native bakes remain in JOB-01,
not silently moved out of 1.0.

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
Ordinary canvas/version mutation safe points recheck live pause/emergency state too, including
immediately after native allocation and after readback/hash verification. A reentrant stop is
not reported as success; denied cleanup retains possible-mutation and finalized-boundary evidence
for explicitly confirmed recovery. Read-only pixel inspection remains available while paused.

`image.inspect_pixels` returns a SHA-256 digest of every stored RGBA float in little-endian
float32 representation, optional complete finite-channel ranges/nonfinite counts, and at most
64 requested integer samples. Default `include_statistics=true` keeps the existing complete
statistics contract. Explicit false returns `pixel_digest_complete=true`,
`statistics_included=false`, `analysis_complete=false`, null ranges/nonfinite count and an
explicit scope description. It does not certify all pixels finite. Nonfinite samples/ranges
become null, never invalid JSON.
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

The `image_masks` fixture adds independent RGBA-channel and bilinear boundary samples on a
128×64 canvas/16×8 mask, raw byte-sRGB FILE-mask weights, zero/inverted masks, a larger
1,025×1,024 mask in an actual socket/timer job, stale-mask/live-file-grant refusal, cancellation,
protected material captures and interleaved-transform-preserving native output recovery.
Post-publication canvas identity/metadata and animation are checked as well as complete pixels;
a reentrant alpha-role change cannot be falsely reported as preserved input.
Native undo after such an external alpha-role change can also invalidate a generated image's
loaded pixel buffer; the fixture records `has_data` without implicitly regenerating it. Restored
RNA settings or output removal alone do not prove recovery of existing input pixels.
An injected external mask-pixel edit is explicitly observed to survive global undo; only the
fixture then restores its own injected edit. This is not claimed as input-pixel recovery.
