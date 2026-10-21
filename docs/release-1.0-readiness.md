# Working toward 1.0.0

Status: **not release-ready**. This is an acceptance plan, not a feature announcement
or a promise of a release date. Published 0.3.0 remains alpha; `main` contains unreleased work.
No version bump or publication happens merely because the tool count increases.

Follow the [1.0 execution plan](plan-1.0.md) for milestone dependencies, prioritized work,
end-to-end scenarios and evidence requirements. This document defines the acceptance gates.

## 1.0 product direction: a full 3D-artist workflow

The intended target is an agent that can carry a brief through a complete Blender art
workflow: understand references and constraints, plan, create/edit assets, inspect its work,
make aesthetic revisions, recover from mistakes and prepare deliverables. It should work
autonomously within the user's authorized scope, not require the user to issue every operator.
Ambiguous targets, destructive scope expansion and new permissions still require clarification.

This is broader than the current implementation. The bridge supplies Blender tools and evidence
to an AI client; it does not currently embed an independent model or run an unattended artist
service inside Blender. Self-contained model hosting is a separate architectural decision.
No current release should be described as a complete human-equivalent artist.

### Capability coverage required by that direction

| Artist responsibility | Existing foundation | Remaining structured-workflow gaps |
| --- | --- | --- |
| Understand a brief and references | Scene/selection/object inspection, task display | Reference management, persistent constraints, scene units/scale checks, ambiguity resolution benchmarks |
| Model and repair assets | Primitives, arbitrary meshes, selection-scoped edits, modifiers; [repair primitives](mesh-repair.md), [quad-ring preview/cuts and two-loop bridging](mesh-loops.md), [bounded topology/winding/contact diagnostics](mesh-analysis.md) | Edge slide, open/multi-loop bridging, explicit unequal correspondence, retopology, localized/cross-object/evaluated diagnostics, outward/custom normals, shape-key/shared-data workflows and protected-scope editing |
| Sculpt and paint | Mode entry; [bounded copy-on-write UV-image brushes and raw-channel masks](texture-painting.md), inversion/bilinear sampling, canvas creation and pixel inspection | Viewport/surface-projected texture strokes/stencils, sculpt/vertex masks, broader blends/roles, sculpt/vertex painting, multires and full workflow feedback |
| UV and textures | Seams, unwrap/project/pack, bounded coordinate/island evidence; [authoring](uv-authoring.md), [layout PNGs](mesh-loops.md#uv-coordinate-visual-evidence), [scoped overlap/pixel-stretch/density checks](uv-analysis.md); [approved PNG/JPEG loading/binding](image-assets.md), [versioned root/nested refresh and relocation](image-revisions.md), [bounded generated canvases/paint versions and complete pixel digests](texture-painting.md) | UV-editor selection, relax/stitch/alignment, cross-object/evaluated atlas checks, broader quality acceptance, full painting/baking, in-place reload/identity-preserving pixel recovery, packing and broader image formats |
| Materials and look development | Principled controls, shader graphs, isolated copies, approved images, [nested paths/group lifecycle/instance isolation](shader-groups.md), [reviewed properties on 14 node types and complete Color Ramps](shader-settings.md), with matched fixture revisions and an [integrated reference-prop fixture](field-scanner-workflow.md) | Interface editing/conversion, properties beyond the reviewed subset, animated ramps/curve collections, deep asset lifecycle, nested snapshots, production materials and broader look-development acceptance |
| Procedural modeling | Allowlisted Geometry Nodes graph authoring/attachment; paired simulation/repeat zones and scoped item rename/reorder/removal | Nested groups, modifier inputs, zone-item type conversion/disk baking, evaluated diagnostics and broader node types |
| Rig and skin | Armatures, bones, pose transforms, constraints, binding; numeric weight inspection/editing/normalization, edge smoothing and explicit mapped transfer | Weight brushes, geometric mirroring/surface transfer, skinning diagnostics, robust IK/control-rig workflows |
| Animate | Frames/ranges/keyframes, inspection; non-scripted transform drivers, action-backed NLA clips and track rename/mute/lock/solo/empty removal | Curve interpolation/handles, action lifecycle, bone/custom-property drivers, NLA reordering/transition workflows, multi-frame revisions |
| Simulate | Scoped cloth setup/configuration and bounded in-memory bake/free | Fluid/rigid-body/other solvers, dependencies, disk caches, asynchronous progress/cancellation and production-scale validation |
| Stage and light | Collections, world, camera/light settings, layout | Camera composition/navigation, iterative lighting comparisons, asset-scale and placement constraints |
| Render and composite | Render settings/execution, captures; reviewed compositor graph editing | Broader nodes/image assets, passes, color/output workflows, render diagnostics and job/progress management |
| Deliver production assets | Permission-controlled project save | Reviewed import/export, dependencies/packing, formats and asset validation, explicit deliverable paths |
| Operate interactively | Status/task/history, permissions, stop/pause; [bounded source-frozen painting jobs with polled progress/cancel](painting-jobs.md) | Persistent plan, visual target resolution, preview/change summaries, user corrections, larger/tiled painting and general long-operation/bake jobs |
| Work safely and improve results | Checkpoints, bounded inspection, batch partial-failure evidence | Consistent preservation contracts, recoverability audits, structural diffs, aesthetic iteration and whole-project benchmarks |

Each row needs representative end-to-end tasks with observable success, failure and recovery
before claiming full coverage. Capability names are not equivalent to complete editor/property
coverage. Any narrower 1.0 scope must be explicitly agreed and documented, not silently substituted
for the requested full-artist target. Raw Python is not a substitute for completing these rows.

## Reliability promise underneath that target

The current [artist-tools increment](artist-tools.md) adds 25 structured tools across compositor,
weights, drivers/NLA, cloth caches and Geometry Nodes zones. Factory-startup evidence on Blender
4.5.1 and 5.1.2 includes evaluated motion/geometry, cloth deformation and a measured compositor
render. These bounded foundations do not close the remaining capability or recovery gates.

A dependable, consent-first local bridge for the documented structured Blender workflows:
inspect, resolve targets, checkpoint, edit, structurally verify, visually verify where relevant,
and save only with permission. Arbitrary Python stays a disabled-by-default super-permission,
not evidence that every Blender feature has a dependable structured implementation.

The exact supported Blender versions and operating systems must be decided from release
evidence. The present declared minimum (4.2) is broader than the locally exercised matrix
(4.5.1 LTS and 5.1.2 on Windows). Do not call all platforms/versions verified by inference.

## Release gates

| Gate | Required acceptance evidence | Current gap / next work |
| --- | --- | --- |
| Target and data ownership | Every modifying domain documents shared data, linked libraries, overrides, active/multi-object modes and hidden scope; rejects unsupported cases before mutation | Mesh/UV and material-slot ownership guards added on main; shader/material datablock editing, modifiers, rigs, nodes, transforms and other mutators still need auditing |
| Recoverable edits | Deliberate mid-operation faults, canceled callers, operator failures and manual undo interleaving leave truthful history and verifiable recovery state | Checkpoints/batches are not transactions. [Conservative capacity reporting/pruning](native-recovery.md) and a long/manual-eviction fixture exist; memory-pressure, production-scale mixed-editor/domain, durable recovery and UI acceptance remain open. Never expand user preferences silently |
| Preserved context | Each representative workflow proves unchanged mode, selection, active object, visibility, UV layer and unrelated data where promised | Selection preservation has coverage; UV layer activation and operator context need broader audit |
| Bounded evidence | Explicit truncation, stable pagination rules, large-scene fixtures and measured time/memory reports | Hard limits exist; add performance baselines and inspect partial-result handling across domains |
| End-to-end workflows | Modeling, materials/nodes, UVs, rigging, animation, scene layout and rendering each have an install-to-result scenario with pre/post evidence | Current factory-startup smokes cover portions, not complete production acceptance |
| Visual verification | Retained, matched viewport/render evidence for appearance-sensitive acceptance scenarios | Isolated preview exists; add repeatable comparisons and interactive viewport coverage |
| Protocol and authorization | Versioned compatibility, reconnect, malformed/oversized frames, duplicate IDs, timeout/cancel, pause/stop and Python gates pass adversarial tests | Core tests exist; expand live disconnect and recovery scenarios; no LAN listener |
| Installation and upgrade | Fresh ZIP/wheel/plugin installation, previous-release upgrade, rollback, paths with spaces and disconnected/restarted Blender tested on claimed platforms | Package/metadata/checksum/clean-wheel CI exists; interactive install and platform matrix remain open |
| Public contracts | Registry, schemas, README, permission matrix, error codes, limitations and migration notes agree for the release commit | Generated inventory is checked; audit full parameter/error contracts and freeze supported surface before RC |
| Release provenance | Packages built from one tested commit; all checks green; checksums verified; downloadable assets and reproducible test report retained | Packaging gates exist; combine Blender acceptance evidence with CI for each release candidate |

No row is complete merely because its happy path passes. Permission denial, unsupported
context, preservation constraints and recovery are part of the acceptance criteria.

## Delivery sequence

1. **Safety baseline:** close ownership/context gaps, add regression fixtures, strengthen failure evidence.
2. **Daily workflows:** finish targeted structured editing gaps and add whole-task acceptance scenarios.
3. **Compatibility and usability:** exercise installation/upgrades and Blender/platform matrix; align UI and docs.
4. **Release candidate:** freeze supported contracts, run the complete matrix from a clean checkout,
   review remaining known issues, and package a candidate. Fix release blockers before 1.0 publication.

The capability matrix is part of the 1.0 target, alongside these safety gates. Specialist
features and exact editor/property coverage require explicit scope decisions and honest
limitations; they must not be silently claimed through Python or omitted without agreement.

## Current increment: shared mesh ownership

Selection-scoped mesh edits (normals, delete, dissolve, extrude, inset, bevel, seam marking)
and UV unwrap/Smart Project/packing now require local, non-override, single-user mesh data.
Unsupported ownership returns `NOT_IMPLEMENTED` before editing or creating a UV layer.
Inspection remains available for shared meshes. This does not silently copy data or make
linked assets local; those are separate user decisions. Other editing domains are not
covered by this guard and still require the audit above.

## Cooperative painting lifecycle progress

The [tile-bounded 4K increment](plan-1.0.md#2026-10-21--tile-bounded-coverage-4k-paint-jobs-and-explicit-inspection-scope)
adds 4096² canvases/jobs, complete large digest-only inspection, scoped memory estimates and
direct canvas pause/emergency safe points. Both 1,278-test SDK suites and the source-matched
60-case Windows Blender matrix pass. Native 4K jobs still measured roughly 37–42 s and
status-poll tail stalls near eight seconds here; full source/output arrays and native/GPU/undo
memory remain. Tile scratch and logical release are not production latency or memory-pressure
acceptance. Surface projection/stencils, sculpt/vertex masks, out-of-core/UDIM, broad paint and full artist gates remain open.

The newer [UV-image channel masks](texture-painting.md#uv-image-channel-masks) extend synchronous
and cooperative painting with raw R/G/B/A weights, inversion, different-resolution bilinear
sampling, source/mask preservation and authoritative live FILE-mask consent. This does not
provide surface/sculpt masks or durable input-pixel recovery: externally edited existing image
pixels can survive native global undo even when the owned output is successfully recovered.

For the newer bounded painting lifecycle, see [cooperative painting jobs](painting-jobs.md)
and the dated [execution evidence](plan-1.0.md#2026-10-20--cooperative-paint-jobs-transport-ownership-and-guarded-publication).
Actual loopback/timer tests on Windows Blender 4.5.1/5.1.2 prove source-frozen progress,
disconnect/cancel, paused deadline expiry, live permission/source checks and guarded native
publication/recovery, including post-write pause and denied cleanup. A prior interleaved transform
survives job undo. The source-matched 58-case matrix and both 1,218-test SDK suites pass.
This does not close general long-operation/native bake, large/tiled-image, memory-pressure,
full painting or any full-artist/RC gate; native transfers remain non-preemptible.

## Material-slot ownership progress

`material.assign`, `material.unassign`, `material.slot_add` and `material.slot_remove` now
require Object Mode and local, editable, non-override, single-user object data. This applies
even to OBJECT-linked slots on shared data: that specialized workflow has not been reviewed,
so it is rejected conservatively rather than silently changing slot ownership. Nothing is
automatically copied or made local. Inspection and use of a shared material on distinct,
single-user object data remain available. Slot editing is capped at 256 slots.

`blender_material_ownership_smoke.py` proves all four shared-data edits fail before mutation,
then verifies all four on explicitly separated test data with the other object's material
preserved, on Blender 4.5.1 and 5.1.2. Unit tests cover library/override/read-only ownership,
Edit Mode and capacity rejection. This is structural slot evidence, not visual shader QA or
completion of the whole material-ownership audit. Shared material datablock/node editing and
forced material unlinking were subsequently hardened as described below.

## Material shader scope progress

`material.set_principled`, all six shader node mutators, and `material.delete` now enforce
local/editable/non-override material and root-tree ownership. Shared references require
`allow_shared=true`; this acknowledges all users, not just the selected object. Inspection
and mutation evidence includes material reference counts, bounded direct datablock users and
object-slot users. Above 100 direct or object users, mutation is refused rather than operating
on truncated evidence. Inspection batches user-map computation and slot traversal.

Forced unlink additionally rejects noneditable/linked/override direct users and object users
outside Object Mode. Local/library material name collisions are rejected before lookup can
silently choose a different datablock. Usage accounting uses datablock identity, not names.
The isolated ownership smoke verifies all eight guarded operations, explicit shared edits,
Edit Mode rejection, real linked-library rejection and ambiguous-name rejection on 4.5.1/5.1.2.

This is structural scope evidence, not visual shader quality or complete SAFE-01 acceptance.
Transitive dependencies (including node-group consumers and collection instances), a protected
scope contract, intentional per-object material copies and partial-failure recovery remain open.
`indirect_users_possible` flags non-slot datablock kinds; even when false the object list is
only slot usage, not an assertion that every dependency was enumerated.

## Object-specific material copy progress

`material.copy_for_object(object_name, slot_index, new_name)` requires `EDIT_MATERIALS` and
participates in normal main-thread history/checkpoint handling. It explicitly copies a material
and its root shader tree, then binds it to one object slot with `link=OBJECT`. Shared mesh data,
polygon indices, other objects and the source material are untouched. This is the intentional
isolation route; the existing general slot edits still reject shared object data.

The object and its data must be local/editable/non-override and in Object Mode. Existing names,
empty/out-of-range slots, ambiguous object names, more than 256 slots, or root graphs above
256 nodes/1024 links are rejected. Referenced node groups, images, animation resources and other
datablocks are not recursively copied; editing those dependencies requires separate scope checks.

Success returns the source/copy names, old/new binding, slot state and direct ownership evidence.
Failure attempts to restore both the visible binding and a latent OBJECT override, removes only
the newly created unused material, and reports `rollback_verified`. Every runtime failure is
marked `execution_started=true` so the existing executor retains its finalized recovery boundary
when available. A false recovery verdict requires reinspection, not a success claim.

The real Blender ownership smoke independently verifies isolation across shared mesh data,
root-tree independence, unchanged nested-group references and source roughness, plus a forced
post-binding failure restoring the old visible/latent bindings and material count. It preserves
selection, active object and geometry. This is not verification of artistic appearance, durable
saving, interactive undo interleaving or the full transitive protected-scope workflow.

## Native undo lifecycle progress

Persistent native `undo_pre`/`redo_pre` handlers clear process-local checkpoint labels and
selection references. Bridge-invoked undo suppresses only this invalidation while its native
operator runs; the suppression flag resets on success or failure. Registration is idempotent,
unregister removes both handlers, and existing file-load invalidation remains in place.

`blender_undo_lifecycle_smoke.py` runs in a separate factory-startup **interactive** Blender
process because background mode cannot execute `ed.undo` in the tested versions. It verifies
native undo/redo, stale bridge undo refusal without mutation, and handler re-registration/
cleanup on Windows Blender 4.5.1/5.1.2. The [runner](native-testing.md) uses a non-visible private desktop on Windows and gives it
isolated TEMP/TMP/TMPDIR paths so Blender's exit recovery stays in test output.

Run it explicitly with `--case undo_lifecycle`, or add `--include-interactive` to the full
matrix command. Interactive checks require a desktop/display; they are excluded by default.
`all_cases_selected=false` reports that omission.

An isolated native probe also exposed the before-only snapshot gap: with snapshots at x=0
and x=1 followed by an unsnapshotted x=2 edit, native undo restored x=0, not x=1; redo restored
x=1. This prompted the following replacement for count-based recovery.

The current manager pushes distinct before/after native snapshots and uses an undoable scene
marker to find the requested boundary. Live markers are advanced immediately after named
checkpoints and restored boundaries so later native snapshots cannot reuse those target tokens.
The snapshot path is opt-in: `checkpoint.undo_last(confirm_global_undo=true, restore_snapshot=true)`.
The default remains exactly one native global undo for compatibility; that legacy path discards
tracking afterwards because the resulting logical position is unverified. Blender's recovery
button opts into snapshot navigation. Local named-checkpoint restoration also uses markers.

Navigation captures a guard snapshot, checks cancellation between undo steps, and permits at
most 256 undo hops. Missing/evicted targets, cancellation and traversal failures attempt bounded
redo back to the guard; errors expose `return_to_guard_verified`, never fabricated restoration.
Cancellation retains its error code, and a redo failure remains an explicit uncertain state.
Raw and structured handler failures now finalize possible-mutation snapshots; successful
operations and batches report `undo_boundary_finalized` separately from boundary creation.

This path starts in **Object Mode**, on a local editable scene, with Global Undo enabled and
at most 200 scenes. Editor-specific operations do not claim per-operation global boundaries;
earlier named global checkpoints remain identifiable. The native fixture independently checks
consecutive transforms, an internal native snapshot/operator, multiple-operation checkpoint
restore, vertex coordinates after an Edit Mode round trip, an unexpected partial handler
failure, and recovery to the guard after history eviction. Object Mode is restored when native
history navigation passes through Edit Mode. Other editor stacks and broad cross-mode cases
remain unverified; do not generalize this fixture to full recovery acceptance.

`_codex_bridge_undo_marker` is internal scene ID-property metadata, not a security token or a
durable backup. It can mark a project dirty and be included in an explicitly saved project;
no file is saved by checkpoint creation/recovery. Normal shutdown removes current-session
metadata; older saved files/native undo snapshots may retain stale values, which do not grant
recovery authority. Unrelated values in the reserved property are rejected, not overwritten.
Checkpoint creation now obeys mutation pause/emergency gates on both sides.

The [native availability ledger](native-recovery.md) counts observed bridge snapshots, prunes
known-expired operation targets and labels expired named checkpoints separately. It budgets
the guard before navigation and rewinds branch accounting after measured restore. It does not
inspect Blender's private stack or guarantee unverified targets; manual/operator/memory eviction
can occur earlier. The `undo_capacity` fixture verifies 16 retained operations out of 17 at 32
steps, all 17 at the test profile's 128 steps, guard-budget refusal without navigation, manual
eviction with return to unsnapshotted work, protected data and live permission/stop checks.
Factory preferences are restored in that isolated process; no user preferences are changed.
That is evidence about these fixtures, not broad native-history or durable recovery acceptance.

`snapshot_marker_verified=true` proves reaching the native marker, not all user constraints
or visual quality. Responses retain `logical_restore_verified=false` and `verification_required=true`.
Interleaved manual edits can still be affected by confirmed global recovery. Protected-scope
comparisons, broader editor/domain tests, durable recovery, UI acceptance and performance on
production scenes remain mandatory REC-01 gates. No full 1.0 acceptance is claimed here.

## Scoped structural comparison progress

`scene.snapshot`/`scene.compare` now expose session-local, bounded field comparisons with
Blender-side inspection permission, immutable cached baselines, exact target resolution,
explicit incomplete coverage and cooperative cancellation. Their [contract](scene-evidence.md)
defines all eight measured fields, record/byte limits, identity/lifecycle behavior and exclusions.

The protected-material fixture checks independent before/after hashes for a shared-mesh
duplicate while another object's material is isolated and edited. It also detects shared
shader, same-count coordinate, UV and weight changes and rejects permission bypass. Native
recovery is followed by a complete baseline comparison in the interactive undo fixture.

This implements the first EVID-02 evidence slice. It does not automatically enforce protected
scope or cover modifier/constraint settings, rigs/animation, nested shader contents, image
pixels, evaluated geometry or appearance. Those remain requirements for full preservation
and artist-workflow acceptance. `unchanged_within_scope` is never a whole-scene/user-goal verdict.

The structured `context.set_mode` gap is now corrected for tracked single-mesh Edit Mode
sessions. The dispatcher retains a deferred before-point, preserves named checkpoints and
finalizes a grouped after-point on return to Object Mode. The [workflow contract](mesh-edit-recovery.md)
describes the metadata and scope. A dedicated native fixture now checks the actual structured
mode/face-selection/extrusion/recovery path, including partial failure, stop/permission gates,
protected-object evidence and restoration of selection/active object/mode. Other editor
stacks, per-operation Edit Mode undo and broader production acceptance remain open.

## UV result verification progress

[Unreleased UV authoring](uv-authoring.md) now includes exact coordinate writes, scoped
transforms and individual pins plus Object Mode layer lifecycle. Native 4.5.1/5.1.2 cases
verify layer/selection-storage differences, localized checker changes, preservation, injected
fault rollback and recovery. This does not close UV-atlas visual inspection, automatic
overlap/stretch or production asset acceptance gates.

Main also has a [bounded mesh-repair workflow](mesh-repair.md): selected-only welding,
boundary-loop capping and edge subdivision are measured together with protected data and
grouped recovery on 4.5.1/5.1.2. Caps receive zero, unpinned UVs, not an automatic unwrap.
The small box fixture and reviewed captures close only these cases; loop bridging/cuts,
production retopology and broader modeling/UV acceptance remain open.

`blender_uv_modifier_constraint_smoke.py` currently passes even when Blender prints
`Unwrap failed to solve 1 of 1 island(s)`. Its later Smart Project checks do not prove
that the earlier unwrap produced the intended result. Keep this script as a domain
dispatch smoke test, not proof of a successful unwrap workflow.

`blender_uv_workflow_smoke.py` now adds both cases on Blender 4.5.1 and 5.1.2: an
unseamed collapsed result is flagged `needs_review`, then a seamed cube is unwrapped and
independently measured as six non-degenerate islands with geometry/materials/selection preserved.
UV inspection reports signed polygon-area diagnostics; modifying UV responses expose
`verification.status` and always keep `user_goal_verified=false`. Passing basic numeric checks
does not prove absence of overlap, self-intersection or distortion, nor acceptable texel density.
These broader checks and visual/artistic acceptance remain open gates.
