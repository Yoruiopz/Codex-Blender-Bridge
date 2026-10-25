# Stock Blender isolated asset preview research

This is a private, opt-in research prototype for unmodified Blender. It copies a
bounded named Mesh Object's authored geometry and XYZ transform values into a
small data transfer object (DTO). A fresh worker builds and renders its own
scene. It is not registered in the add-on or MCP server, does not enable protected
`viewport.capture`, and supplies no current-project save or delivery capability.
`project.save` remains unavailable under the [save safety contract](project-save-safety.md).

The selected isolated experiment passed on official Linux Blender 4.5.14 and
5.2.2 at source `ea1da49f7069ad3552c393b88148b56fc32b436d`, before integration.
Both writer/worker pairs completed; their measured source projections remained
unchanged, and both resulting PNGs received visual review. The source suite at
that commit passed 8,062 tests with three Windows-only skips. This qualifies only
the finite experiment below. It does not qualify a public tool, installed package,
current-viewport capture or an entire project. All 29 agreed completion
requirements and all 14 stable-release gates remain open; Windows remains
deferred. Source checks, native observations and reviewed visuals are separate
evidence.

## Data boundary

The research helper is `scripts/native_isolated_asset_preview.py`. Its pure DTO,
validation, framing and PNG routines are import-safe standard-library code;
importing the module must not import `bpy` or start a worker. The native capture
entry receives an explicit Object name rather than resolving the current
selection or active Object. Capture is limited to a local, static, Object-mode
Mesh and authored XYZ Euler transforms with default delta transforms. Object
admission checks native RNA class/descriptor metadata, library/override status,
parenting, animation, modifiers, constraints, mode and rotation mode. Mesh
admission checks its native descriptors, library/override status, animation,
shape keys, edit-buffer state and a single user. These checks and default-delta
validation precede geometry reads. MeshVertex, MeshEdge and MeshPolygon
descriptors are all preflighted before the first coordinate getter. Runtime
descriptors and unexpected numeric shapes refuse. These are finite admission
checks, not a general claim that
Python attribute access is passive or that every metadata/dependency kind was
enumerated.

On both pinned refs, `rna_mesh.cc` registers `MeshPolygon.vertices` with static
length 3, then marks it dynamic and supplies an instance-size callback.
`rna_Property_array_length_get` in `rna_rna.cc` returns `prop->totarraylength`
directly, with no dynamic-instance case. The descriptor guard therefore requires
3; the actual polygon's 3–64 corner count is validated separately. This source
distinction does not qualify native admission or capture behavior.

The capture path must not call `libraries.write`, copy Blender IDs, save a file,
evaluate the source scene, or read context selection/active-Object getters. It
does not copy a Main, Scene, ViewLayer, camera, material, image, animation,
modifier result or UI state. Custom properties, UVs, vertex attributes, material
bindings and source shading are outside the DTO. Authored source values are the
input; evaluated appearance is outside this profile. Represented transform
channels are location, XYZ Euler rotation, scale and default deltas. Inactive
Object quaternion and axis-angle channels are not copied or qualified by the
worker's raw-channel comparison. The worker never writes back to the active
Main. Capture does not enumerate unrelated Main IDs. The
absence of that traversal is not a complete preservation witness for unrelated
protected data.

The schema is `stock_geometry_preview_v1`, with exact keys and a 2 MiB canonical
serialized limit. Geometry requires 3–512 vertices, 3–1,024 unique undirected
edges, 1–512 polygons and at most 2,048 polygon corners. Each face has 3–64
distinct valid vertex indices and every boundary edge must occur in the edge
set. All scalar geometry and transform values use eight lowercase hexadecimal
characters containing little-endian Float32 bytes; exact encoding avoids
treating JSON numeric equality as a storage witness. Validation rejects
malformed, nonfinite, out-of-range and unsupported values before worker scene
creation. The Object name is exact, nonempty, free of control characters and at
most 63 UTF-8 bytes.

| Quantity | Profile bound |
| --- | --- |
| Object-local coordinates | Absolute value at most 1,024 |
| Authored location | Absolute value at most 8,192 |
| Authored XYZ rotation | Absolute value at most 16π radians |
| Authored scale | Absolute value from 0.0001 through 64 |
| Computed world coordinates | Absolute value at most 65,536 |

Delta location/XYZ rotation must have the exact Float32 bits for positive zero;
delta scale and WXYZ quaternion must have the exact default bits `(1, 1, 1)`
and `(1, 0, 0, 0)`. A signed-zero delta differs and refuses. The largest world
axis extent must be at least `max(0.0001, maximum_absolute_world_coordinate *
2**-16)`. This precision floor does not prove that every admitted polygon has
visible area from the fixed camera. These bounds define an experiment, not a
general asset format or an authorization policy for a future public tool.

## Process boundary

The source integrates the opt-in runner case `isolated_asset_preview_probe`, through
`scripts/run_blender_checks.py` and the isolation policy in
[native testing](native-testing.md). It has two processes:

| Process | Intended measurement |
| --- | --- |
| Private interactive writer | Construct the disposable counterexample fixture, capture the admitted named Object into the DTO, and compare independently retained source observations. |
| Fresh background worker | Validate the DTO, construct only worker-owned geometry and a new camera/scene, render a fixed preview, and validate its image evidence. |

The runner's existing `PHASED_CASES` interface calls the second phase `reader`.
For this case, **`reader` means the isolated render worker**, not a third process
reopening a saved `.blend`. No `.blend` serialization or reopening is part of
this experiment. A phase marker or process exit alone does not demonstrate
source preservation or a correct image.

The fixture accepts only Linux Release builds with the configured 4.5.14 or
5.2.2 upstream source identities. Before acquiring owned-process exit authority,
it checks the main thread, factory startup, disabled auto-execution, the phase's
background flag, process token, task-owned profile/bundle paths and an empty
project filepath. The writer also validates its private-display manifest.
The runner supplies a small environment allowlist, dedicated HOME/Blender/XDG
profile paths and working directory. These operational checks are not an OS
filesystem/network sandbox or qualification of any native binary.

Exclusive, read-only evidence files bind the DTO hash to the writer receipt and
then bind the writer receipt hash to the worker receipt. The worker requires
different process tokens/PIDs and matching native version/build/source identity
and fixture/helper hashes. Each phase fingerprints its executable before its
measured work; the writer does so before the source baseline. The record contains
the resolved executable path, byte count and SHA256, hashing in 1 MiB chunks with a
1 GiB file cap and a before/after size/mtime/inode check. The worker requires that
complete `binary_identity` record to equal the writer's. Both selected native
pairs passed this comparison. The helper additionally requires background mode,
a canonical absolute output path and a nonexistent output before worker ID
creation. These are research checks, not a public approved-path publication or
overwrite policy.

The worker requests a fixed 128×128 Cycles CPU preview with eight samples, seed
zero, denoising/adaptive sampling disabled and a transparent film. It creates
its own flat, opaque material, world and area light. Its orthographic camera fit
uses DTO world bounds, the normalized back direction `(1.5, -2.5, 1.8)` and a
1.3 framing margin; it reports projected bounds in normalized `[-1, 1]` image
coordinates. It does not borrow a source camera or source evaluation. Explicit
`ViewLayer.update` occurs only in the worker.

Worker checks compare reconstructed vertex and transform Float32 bits, polygon
ordering and the complete undirected edge set. Native edge identity/order is
outside that comparison. Independently composed XYZ world points are compared
with evaluated worker points using `max(1e-5, abs(expected) * 2**-19)` tolerance.
The PNG parser requires noninterlaced 128×128 RGBA8 data and validates CRCs,
filters 0–4, bounded decompression and an alpha-at-least-128 foreground bounding
box with a two-pixel border. It reports inclusive bounds and
`visual_review_performed: false`; a later root review records human-readable
observations separately. Both selected native workers passed geometric framing,
reconstruction and PNG checks. The reviewed images show the rotated box fully
inside the frame with visible top and side faces, separated flat shading and a
transparent background. This reviews the fixture's geometry preview, not source
material appearance or arbitrary asset quality.

## Preservation counterexamples

The writer fixture must retain an unrelated animated Object with deliberately
dirty authored transform channels and a legal pending hidden-and-selected Base.
It must measure them before and after capture without frame evaluation,
ViewLayer update or a synchronizing selected/active/mode helper in between. A
source reader that normalizes the state before taking its baseline cannot prove
preservation.

The source fixture privately arms a standalone `TaskPlanStore` with protected
Object names and a literal-field baseline; it does not call the public
protection-admission path. The positive interval compares target geometry/raw
channels, the unrelated Action/raw actor channels, material bindings, selected
fixture identities and task-plan metadata, including baseline/protection Python
identity. Its receipt records zero source serialization, evaluation, context
getter calls and restoration writes **within that positive interval**. This
does not prove hidden storage or full-Main purity. Public task-plan admission,
complete H02/F01 acceptance, current viewport, source material appearance,
whole-project saving and Windows qualification all remain explicitly false.

Setup also assigns the known USER property `target["preview_keep_ref"]` to the
protected Object. The fixture's direct read of that one known property records
the owner/referenced identities and both ID user counts before and after
capture; its positive receipt includes the corresponding preservation flag.
Capture itself does not traverse source properties or references, and the
worker reports `user_properties_or_ID_references_copied: false`. This is a
fixture-only comparison of one known USER reference, not a SYSTEM-storage,
private-flag or general ID-reference preservation witness. That finite comparison
passed in both selected native writers.

After the positive comparison, a separate `context.selected_objects` control is
expected to clear the pending hidden selection. That destructive control is
neither repaired nor adopted as a new positive baseline; the disposable writer
then exits before the render worker starts. The control is not a permissible
operation on an artist's protected session.

The raw selected-Object collection is a fixture-only diagnostic on the exact
source-pinned Release builds. It has a native debug-only precondition and is
neither a complete Base witness nor a production fallback. The existing
[getter counterexample](protected-capture-design.md#getter-counterexample-to-qualify)
records this restriction. A prospective public feature needs its own supported
admission and preservation proof; this prototype does not relax existing
protected-context refusals.

The earlier [portable `.blend` worker experiment](portable-blend-worker-research.md)
used a factory-reset, globally static fixture and a different serialization
contract. Its camera compatibility conversion, fake-user restoration, pixel
cache loads and passing historical reads do not qualify this DTO path or an
arbitrary active project.

## Evidence required before further admission

Focused standard-library tests should cover malformed DTOs, byte encoding,
numeric and topology limits, transform/framing calculations, strict PNG
validation, native descriptor guards, and refusal before geometry reads for
unsafe metadata, delta transforms and Edit Mode. Passing those tests proves
only the tested Python contracts.

Separate isolated native results are required on each exact supported build for
accepted capture, refused capture, preservation of the two counterexamples,
fresh-worker construction/rendering, camera bounds and image validation. Retain
the exact source/build identities, phase receipts, DTO/image hashes and any
failure evidence. Native rendering remains a synchronous operation; this
prototype has no production job ownership, cancel/reconnect, permission race,
approved-path publication, durable recovery or installed-package acceptance
contract. It does not complete the artist interaction loop, scenarios A–F or
1.0 readiness.

The retained exact reflection source is
`source/blender/makesrna/intern/rna_rna.cc`:

- Blender 4.5.14, commit `62c1db4208e862312bc36db5bc15d4a6dbcfa3e3`,
  [getter at line 847](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/makesrna/intern/rna_rna.cc#L847),
  Git blob `ef3ea78c52421be9c8aa42cdb432ea64bc4e6c06`,
  SHA256 `b327f5a2ab3598b327cbd35a264db5fbdd9f37c84a191d3d910be74f28f4de9f`.
- Blender 5.2.2, commit `d13f752e3b9c4f8c261cda552b1021f8bcc0382c`,
  [getter at line 872](https://github.com/blender/blender/blob/d13f752e3b9c4f8c261cda552b1021f8bcc0382c/source/blender/makesrna/intern/rna_rna.cc#L872),
  Git blob `3b1dbf553c8cd2a5a11e35182b1db75f1815cf38`,
  SHA256 `7e03739d2d78790bbdca47864538e5c30aefdb024392d6b15b40ded3215624ab`.
