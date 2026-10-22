# Development status

**Unreleased development; 1.0 is NOT_READY.** The published [0.3.0 alpha](releases/0.3.0.md)
contains 108 tools. The development registry currently contains **251 MCP tools**;
its packages retain 0.3.0 metadata until a qualified release is accepted. Always pair the
add-on and MCP server from one checkout. A matching version string alone does not identify
an unpublished build.

## What is being developed

The notes below describe increments on the development branch, not features available in
the published downloads. Follow each domain's linked contract for current limits and
failure/recovery behavior. Tool count and isolated fixture results do not prove complete
artist workflows. The [execution plan](plan-1.0.md), [readiness gates](release-1.0-readiness.md)
and [evidence rules](release-evidence.md) define the work needed for 1.0.

Linux development checks, including historical 4.3.2 increments and newer
4.5.14 LTS / 5.2.2 LTS results, are separate from historical Windows
reports for earlier increments. Windows 11 qualification on Blender 4.5 LTS and stable 5.x,
installed-package acceptance and scenarios A–F remain required. There is currently no
available Windows 11 test machine; those gates remain open.

Recent bounded additions include [mesh slides and UV refinement](mesh-uv-refinement.md),
[sculpt and vertex-color brushes](surface-brushes.md), [weight brushes and surface transfer](weight-brushes.md),
[rig properties and non-scripted drivers](rig-drivers.md), [nested Geometry Nodes](geometry-node-groups.md),
[object/layout scope and recovery hardening](object-lifecycle-safety.md),
[curved reference surface projection](mesh-surface-projection.md),
[orthographic surface paint and stencils](image-surface-paint.md),
[IK and measured deformation](rig-ik-deformation.md), and
[zone/interface lifecycle](geometry-zone-lifecycle.md).
The next bounded increment adds [cooperative packed recovery](image-recovery-jobs.md),
[shader interface previews and edits](shader-interface-lifecycle.md),
[guarded rig edits](rig-edit-boundaries.md),
[object property recovery](object-rna-safety.md) and
[saved two-bone NLA motion](character-nla.md).
See the [source-matched checkpoint](artist-workflow-checkpoint-20261022.md) for retained evidence.
Broader retopology/painting, character animation, procedural baking,
simulation and production delivery still have open acceptance work.

## Incremental workflow notes

The development branch includes **unreleased seam authoring**: `mesh.mark_seams`
and edge seam flags in component inspection, plus opt-in UV coordinate pages in `uv.inspect`.
These are not included in the 0.3.0 downloads.

Development is working toward **1.0.0** through explicit [release-readiness gates](release-1.0-readiness.md),
following the [milestones and prioritized execution plan](plan-1.0.md),
with a [full 3D-artist capability target](release-1.0-readiness.md#10-product-direction-a-full-3d-artist-workflow),
not a tool-count target or a claim that current releases already replace an artist.
Unreleased [mesh-quality inspection](mesh-analysis.md) now reports bounded topology,
adjacent winding and triangle crossing/contact evidence. It separates review findings from
incomplete budget/precision coverage; it is not an outward-normal or whole-scene certificate.
Main also hardens mesh/UV edits against implicit changes to linked
duplicates: selection-scoped mesh edits and UV unwrap/Smart Project/packing now reject shared,
library-linked or override data. Inspection remains available; no automatic data copying occurs.

Unreleased material-slot edits (`material.assign`, `material.unassign`, `material.slot_add`,
`material.slot_remove`) likewise require Object Mode and local, editable, non-override,
single-user object data, with a 256-slot limit. Shared data now returns `NOT_IMPLEMENTED`
before mutation, including OBJECT-linked slot cases not yet reviewed. This prevents implicit
changes to linked duplicates.

Unreleased shader edits (`material.set_principled` and modifying `nodes.*` tools) and
material deletion now check material ownership in Blender. Inspect `material.inspect` first:
shared use requires explicit `allow_shared=true`; linked/override/read-only materials remain
protected. Responses include bounded object-slot and direct datablock users. This is not a
complete transitive dependency graph—Geometry Nodes and collection instances need additional
inspection. Forced unlink also checks editable users and Object Mode. Ambiguous local/library
material names are rejected, and scopes above 100 users cannot be edited through these tools.
No material is copied or made local automatically. These changes are not in the 0.3.0 download.

To change only one object that shares a material, use the unreleased
`material.copy_for_object(object_name, slot_index, new_name)` tool first. It creates a named
material/root-shader-tree copy and an **OBJECT-level slot binding**, without copying the mesh
or changing another object's slots—even when both objects share mesh data. Then edit the new
material normally. The target must be local, editable, non-override and in Object Mode.
Nested groups, images and other referenced datablocks are **not deep-copied**. The tool verifies
its binding and attempts measured local recovery if copying or assignment fails; inspect any
failure before continuing. See the [scope and recovery limits](release-1.0-readiness.md#object-specific-material-copy-progress).

Unreleased recovery hardening invalidates bridge checkpoint bookkeeping after Blender-native
undo/redo, preventing reuse of stale labels. For measured operation-boundary recovery, call
`checkpoint.undo_last(confirm_global_undo=true, restore_snapshot=true)` from Object Mode.
The Blender recovery button uses this path. Omitting `restore_snapshot` keeps the legacy
single-global-undo behavior. Recovery can still affect interleaved manual work; inspect afterwards.
Internal `_codex_bridge_undo_marker` scene metadata identifies snapshots and may be saved with
your project; normal add-on shutdown removes this session's current marker. It is not a backup.
See [tested recovery cases and remaining 1.0 gates](release-1.0-readiness.md#native-undo-lifecycle-progress).

Checkpoint availability now reports finite undo limits in `checkpoint.list`, `bridge.status`
and the Blender panel. Known-expired operation boundaries are pruned; named checkpoints show
expiry, and recovery refuses if its guard would exceed the observed budget. Other points remain
**unverified**, since manual edits and memory limits can evict them too. No preferences are
expanded automatically. See [recovery availability and limits](native-recovery.md).

Structured single-mesh Edit Mode sessions now retain a recovery group from mode entry
through the return to Object Mode. The checkpoint panel and tool results show when that
group is deferred or finalized. Confirmed snapshot recovery restores the grouped interval;
see the [mode/edit/recovery workflow](mesh-edit-recovery.md) for its scope and limits.

Unreleased mesh repair adds `mesh.subdivide_selected`, `mesh.merge_by_distance` and
`mesh.fill_holes`: bounded edge subdivision, selected-only local-distance welding and closed
boundary-loop caps. They require one active, local, single-user Edit Mode mesh. Caps start with
zero UVs and need unwrapping; shared/linked/override and shape-key meshes are not supported.
See [tool limits and the verified repair/recovery workflow](mesh-repair.md).
Isolated viewport capture also now restores the selection of temporarily hidden objects.

Unreleased UV authoring adds exact face-corner coordinate edits, pivot/scale/rotation/offset
transforms, individual pin anchors, and UV-layer create/copy/rename/activation/confirmed removal.
Coordinate/pin tools use scoped Edit Mode data; layer lifecycle is explicit in Object Mode.
Other layers and mesh selection are preserved, and Blender 4.5/5.1 selection-storage differences
are reported. See [UV tools, limits and the verified workflow](uv-authoring.md).

Unreleased loop modeling adds a paginated quad-ring preview, evenly spaced ring cuts, and
bridging of two closed boundary/wire loops. UV layout PNGs now provide measured-coordinate
visual evidence without changing the viewport or Render Result. A connected test workflow
repairs a prop, unwraps it, gives it a separate finish and verifies staged recovery while
preserving a protected duplicate. See [scope, limits and workflow](mesh-loops.md).

Unreleased `uv.analyze` adds bounded numeric checks for overlap, mirrored/folded mappings,
pixel-direction stretch and texel density at a declared texture resolution. It uses native
base-mesh triangulation and world transforms, reports incomplete budgets honestly, and does
not alter UVs or selection. See [measurements, thresholds and limitations](uv-analysis.md).

Unreleased [texture-image tools](image-assets.md) inspect/load/remove image datablocks
and bind loaded images to material Image Texture nodes. Choose an **Approved Texture Folder**
in Blender and grant external-file access for reviewed PNG/JPEG/float-EXR reads; MCP cannot change the
folder. The workflow checks color/data roles, material isolation, texture revisions and undo.
Loading/binding never edits pixels; reviewed export/reimport is implemented, while broader
dependency lifecycle, packing and baking acceptance remain open. For bounded
copy-on-write brush edits, use the separate [texture-painting workflow](texture-painting.md).
Bounded [packed versions and raw snapshots](image-portability.md) distinguish original
FILE bytes from CURRENT_PIXELS and restore a matching loaded float original without changing
its ID or consumers. Their <=1M-pixel contract is separate from larger export jobs.

Unreleased [versioned texture refresh](image-revisions.md) adds `nodes.refresh_image`:
reread a changed texture or repair its source path through a newly named image version,
retaining the original image/buffer and the node's color/alpha role, sampling and wiring.
It works at root/nested paths with explicit scope and file consent, including missing sources.
This is not in-place image reload or a durable pixel backup; those remain 1.0 work.

Unreleased [texture-painting tools](texture-painting.md) create new linear-color/data
canvases, paint bounded UV-image strokes into separate versions, and inspect complete pixel
digests/ranges with selected samples. They support color source-over, alpha erasing and data
mixing without changing the original image or writing files. A painted scanner display and
native failure/recovery tests connect this to look development. Optional
[UV-image masks](texture-painting.md#uv-image-channel-masks) select raw R/G/B/A weights,
support inversion and bilinear sampling across different image sizes, and preserve/revalidate
both input images. FILE-mask reads require live approved-path consent. Viewport-projected
texture strokes/stencils, baking and durable production delivery remain open. Bounded
sculpt/vertex-color brushes have a separate [explicit-mask contract](surface-brushes.md).

Generated paint canvases now use independent raw RGBA with native CHANNEL_PACKED alpha, fixing
a Blender 4.5 Cycles transparency discrepancy while preserving requested channel values. Reviewed
associated linear float inputs normalize explicitly before painting; inspection/masks remain raw.
[Texture-delivery work](texture-delivery.md) adds internal PNG/float-EXR encoders, approved-folder
staging, no-overwrite publication and complete file-hash checks, including a 4K native round trip.
It requires live edit, external-file and save consent; cleanup never deletes the published file.
Reviewed plain RGBA FLOAT32 EXR and large PNG imports now use the shared bounded reader,
with explicit EXR color/alpha interpretation and complete file checks.
`image.export_job_start` adds frozen-source PNG8/PNG16/float-EXR export and verified reimport,
including the full 4K path. Poll image-job progress and terminal file/image evidence; publication
never overwrites a target, and **cancel or Blender undo does not delete a published file**.
Stored `//` image dependencies now resolve against saved local projects with live source and
approved-folder revalidation. A separate-process save/reopen fixture verifies eight small
format/role variants and a complete 4K raw DATA texture; this remains development evidence.
Durable edited-input recovery, broader packing and production delivery remain in progress;
see the [delivery contract](texture-delivery.md) and [import limits](image-assets.md).

Unreleased [cooperative painting jobs](painting-jobs.md) add `image.paint_job_start` and
`jobs.inspect/list/cancel`, with polled progress, sidebar CPU-budget/control/history, frozen
inputs and a single guarded publication boundary. Cancel/disconnect/pause/deadline behavior is
explicit; native transfers are not preemptible and late failures may retain an image for
confirmed recovery. One active bounded job, no batch nesting or durable/general bake queue.
This advances responsive artist workflows without claiming full 1.0 coverage.

The tiled kernel now supports 4K-square canvases and cooperative jobs, with at most 32 KiB of
coverage scratch, conservative diagonal bands and no whole-image baseline copy. Synchronous
painting/full channel statistics remain <=1M pixels; use `include_statistics=false` for complete
large digests/samples, with omitted statistics reported explicitly. Native transfers/undo still
block at bounded stages and memory estimates exclude Blender/GPU/undo storage. See the
[large-image workflow and limits](painting-jobs.md), not a production real-time guarantee.

Unreleased [nested shader-group tools](shader-groups.md) add group creation, typed interface
sockets, binding, one-instance copies and confirmed unused removal. Existing `nodes.*` tools now
accept an explicit `group_path`. Ownership checks follow parent groups to material users; copying
a material alone does not isolate its children. A matched texture-revision test uses one logical
batch and verifies protected data, partial-failure recovery and native undo without expanding the
default history. Native history remains finite; see the workflow and limitations before use.

Unreleased [shader-setting and Color Ramp tools](shader-settings.md) inspect native choices,
edit reviewed properties on 14 shader node types, and replace complete 1–32-stop palettes at
root or nested paths. Matched procedural-material variants verify protected group data and
measured failure recovery. The inspector distinguishes stored ramp interpolation from Blender's
effective RGB/HSV/HSL behavior. Broader properties, animation and production look acceptance
remain open; no arbitrary Python or file write is needed for these edits.

Unreleased [face shading and material assignment](field-scanner-workflow.md) adds per-face
smooth flags during mesh creation and `mesh.set_face_attributes` for fresh, bounded Edit Mode
face selections. A reference-constrained field-scanner fixture now combines structured modeling,
measured UVs, nested color/data textures, display variants and staged native recovery. It is
development evidence, not complete 1.0 artist acceptance; full painting, baking and delivery
acceptance remains open.

Unreleased `scene.snapshot` and `scene.compare` add bounded before/after evidence for named
objects: transforms, hierarchy, visibility, base mesh geometry, UVs, weights, material slots
and root shader socket values/links, reviewed properties and color ramps. They can detect edits that leave object or vertex counts
unchanged. Results identify changed fields, complete matching scope, or incomplete evidence
that needs further inspection. See [fields, limits and the protected-material workflow](scene-evidence.md).

Optional snapshot fields now include rig rest/current pose, active/layered animation,
drivers/NLA and nested shader dependencies. New [artist plans](task-plans.md) track bounded
steps and advisory protected objects across client reconnects; explicit scene persistence does
not save the project. The sidebar shows plan progress, and protected comparisons remain explicit.

Unreleased [Action/curve authoring](animation-curves.md) adds independent active-Action
copies and bounded interpolation/handle edits. [Nested Geometry Nodes](geometry-node-groups.md)
adds explicit group-instance isolation and stable-identifier modifier inputs. Their native
development fixtures do not close full character, procedural or simulation acceptance.

Unreleased [GLB/FBX delivery](asset-delivery.md) previews explicit static/skinned asset
scope, requires format-loss acknowledgement and publishes to a separate Approved Asset Folder
without overwrite. The current subset rejects materials/textures and other unsupported data;
full production exchange remains open. Published files survive undo/cancellation, and bounded
file effects remain in operation history with inspection-based redaction.

## Unreleased: structured UV seams


`mesh.mark_seams` marks or clears UV seams on selected edges, or on the edge scope of a
fresh `selection_id`. It requires `EDIT_MESH` and an explicitly named, active, single-user
mesh in single-object Edit Mode. Linked/override data, shared meshes, hidden targets,
empty selections and stale references fail explicitly. It preserves topology, UV coordinates,
materials and live selection; unwrapping remains a separate `uv.unwrap` operation.

Inspect indexed edges with `mesh.components_inspect` (each edge now includes `seam`),
select the intended edges, mark with `seam=true` or clear with `seam=false`, then reinspect.
The tool is batch-compatible and uses normal checkpoints/history. It returns bounded edge
indices, changed counts and total seam counts, and attempts to restore flags on failure.
Existing inspection bounds apply: at most 200,000 total mesh components and 100,000 targeted
edges, with at most 256 edge indices in a mutation response.

For exact unwrap evidence, call `uv.inspect` with `include_coordinates=true`.
`coordinate_offset` and `max_coordinates` (1–256, default 100) page over face corners
in the requested face scope. Each item identifies its face, corner and mesh vertex,
with UV coordinates and pin state; UV selection is reported when available in Edit Mode.
Object Mode and Edit Mode are supported without switching modes or active UV layers.
Follow `coordinates.next_offset` until null. `analysis_truncated` indicates the scoped
50,000-face/200,000-loop safety limit, not a complete result. Offsets are not persistent:
restart inspection after UV, selection, topology, mode, scene or layer changes. Default
inspection remains compact and omits coordinate pages; meshes without UV layers return null.

Unreleased UV inspection also corrects island counting: seam flags alone no longer split
an existing UV island. Connectivity uses matching UV coordinates at both endpoints of a
shared mesh edge (tolerance 1e-6); coincident but disconnected geometry stays separate.
Non-manifold edges with other than two scoped faces are not joined. Marking seams and
unwrapping are separate steps; this inspection describes current UVs, not a proposed unwrap.
Disconnected-island traversal now sorts seeds once instead of repeatedly scanning the
remaining faces, avoiding quadratic seed selection on highly fragmented UV layouts.

UV analysis now includes near-zero signed face-area diagnostics. Unwrap/project/pack results
include `verification.status` (`needs_review` or `basic_checks_passed`) and warnings; they never
set `user_goal_verified` to true. Non-finite coordinates/area yield incomplete-analysis evidence
instead of invalid JSON. These are basic numeric checks, not overlap, distortion or texel-density
certification. A collapsed unwrap can return from Blender without raising an exception, so
always inspect these fields and compare the result with the requested layout.


## Find the authoritative contract

- [Current registered inventory](../README.md#complete-tool-inventory--main-branch): available tool names and descriptions.
- [Artist-tool contracts](artist-tools.md): bounded sculpt, compositor, weight, NLA and simulation foundations.
- [Release execution plan](plan-1.0.md): priorities and source-specific verification history.
- [Readiness gates](release-1.0-readiness.md): product acceptance and remaining blockers.
- [Native test execution](native-testing.md): runner isolation, evidence and platform limits.
- [Contributing](../CONTRIBUTING.md): development setup and verification expectations.
