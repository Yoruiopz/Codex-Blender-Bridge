# Working toward 1.0.0

Status: **not release-ready**. This is an acceptance plan, not a feature announcement
or a promise of a release date. [Published 0.5.0](releases/0.5.0.md)
(25 October, 07:54:54 UTC) remains alpha. Exact-source CI, selected Linux native
and installed checks and verified downloads are retained; they do not complete
any stable gate. Earlier releases remain available. The prospective
[0.6.0 source](releases/0.6.0.md) is unqualified and unpublished. Meaningful,
reviewed increments are authorized for versioned GitHub
prereleases at roughly a 2–3 hour cadence, with matching packages, checksums and
source-specific validation. Tool counts and elapsed time do not establish readiness.
Prereleases do not bypass any stable 1.0 gate.

Follow the [1.0 execution plan](plan-1.0.md) for milestone dependencies, prioritized work,
end-to-end scenarios and evidence requirements. The [implementation completion
checklist](implementation-completion.md) defines the finite remaining functional work
and its Linux completion checks. This document defines the stable-release acceptance gates.

The [machine-readable ledger](release-1.0-ledger.json) records all fourteen mandatory
requirements as open. Use the [evidence qualification gate](release-evidence.md) to check
exact-commit/package provenance, complete Windows 11 native matrices on Blender 4.5 LTS
and stable 5.x, and installed-package scenarios A–F on both selected versions. The current
ledger deliberately fails qualification; no historical smoke count or runner verdict
can promote it to release-ready.

## 1.0 product direction: a full 3D-artist workflow

The intended target is an agent that can carry a brief through a complete Blender art
workflow: understand references and constraints, plan, create/edit assets, inspect its work,
make aesthetic revisions, recover from mistakes and prepare deliverables. It should work
autonomously within the user's authorized scope, not require the user to issue every operator.
Ambiguous targets, destructive scope expansion and new permissions still require clarification.

This is broader than the current implementation. The bridge supplies Blender tools and evidence
to an AI client; it does not currently embed an independent model or run an unattended artist
service inside Blender. Embedded model hosting is outside the agreed release scope.
No current release should be described as a complete human-equivalent artist.

### Capability coverage required by that direction

| Artist responsibility | Existing foundation | Remaining structured-workflow gaps |
| --- | --- | --- |
| Understand a brief and references | Scene/selection/object inspection, task display; [revisioned plans, scene persistence, exact references and opt-in protected transforms](task-plans.md); [explicit target core-channel observations](artist-target-verification.md) | Visual references, wider enforced constraints, broader target/dependency verification, protected save/delivery, scene units/scale checks, ambiguity resolution benchmarks |
| Model and repair assets | Primitives, arbitrary meshes, selection-scoped edits, modifiers; [repair](mesh-repair.md), [cuts/closed bridges and previewed equal open-chain bridges](mesh-loops.md), [diagnostics](mesh-analysis.md), [previewed explicit-rail vertex/edge slides](mesh-uv-refinement.md), [scoped base-reference projection](mesh-surface-projection.md) | Broader open/multi-loop bridging and native qualification, explicit unequal correspondence, broader retopology, localized/cross-object/evaluated diagnostics, outward/custom normals, shape-key/shared-data workflows and broad protected editing |
| Sculpt and paint | [UV-image brushes and raw masks](texture-painting.md), canvas/pixel inspection; [explicit-mask PUSH/SMOOTH and POINT/CORNER colors](surface-brushes.md), [generated-image sculpt masks](surface-brushes.md#sample-a-painted-uv-image-into-a-sculpt-mask), [weight brushes](weight-brushes.md), [bounded orthographic surface strokes/stencils](image-surface-paint.md), with published bounded 4K job/mask evidence in 0.5.0 | Current-source 4K qualification, visual/constrained-memory acceptance, viewport/perspective painting, broader texture sources/blends/roles, multires and full production sculpt/paint feedback |
| UV and textures | [Authoring and the bounded direct-edit guard](uv-authoring.md), [UV evidence](uv-analysis.md), [align/stitch/island relax](mesh-uv-refinement.md), [approved loading/binding](image-assets.md), [refresh/relocation](image-revisions.md), [paint/digests](texture-painting.md), stored-relative FILE reopen, [loaded/unloaded FILE recovery](image-portability.md) and [cooperative 4K snapshots/recovery](image-recovery-jobs.md) | UV-editor selection, cross-object/evaluated atlases, broader quality acceptance, full painting/baking, broader formats and production durable-pixel acceptance |
| Materials and look development | Principled controls, isolated copies, approved images, [nested paths/groups](shader-groups.md), [reviewed properties/ramps](shader-settings.md), [interface preview/rename/reorder/default](shader-interface-lifecycle.md), bounded nested evidence and [reference-prop fixture](field-scanner-workflow.md) | Interface conversion/removal and animated maintenance, broader properties, deep asset lifecycle, complete nested dependency preservation, production materials/look development |
| Procedural modeling | Reviewed GN graphs/zones; [nested instances/copies and modifier constants](geometry-node-groups.md), [identifier-preserving zone conversion/interface edits](geometry-zone-lifecycle.md) | Broader nested/interface lifecycle, disk baking, evaluated diagnostics and broader node types |
| Rig and skin | Armatures/bones/poses/constraints/binding; numeric weights; [brushes, geometric mirror and barycentric surface transfer](weight-brushes.md), [bounded IK controls and current-frame deformation measurements](rig-ik-deformation.md), [implemented protected character benchmark](character-revision.md) | Broader skinning/deformation diagnosis, control-rig authoring and current-source production character qualification; an implemented benchmark is not complete acceptance |
| Animate | Frames/keyframes, NLA clips/tracks; [Action copies, curve handles/interpolation and direct stored-curve samples](animation-curves.md), [numeric controls and non-scripted bone drivers](rig-drivers.md), [bounded Action lifecycle](action-lifecycle.md) and [NLA clips/transitions/reordering](nla-lifecycle.md) | Broader Action/constraint/control-rig combinations, complete mutator safety audit, evaluated character motion and protected multi-frame revisions |
| Simulate | Scoped cloth setup/configuration, bounded in-memory bake/free, three rigid-body cache tools and two public [bounded evaluation job tools](rigid-body-evaluation-jobs.md) using the [Scene job kernel](scene-job-kernel.md) | Cooperative bake/coverage proof, broader solvers/dependencies, disk caches, native scale/memory/recovery and installed end-to-end qualification |
| Stage and light | Collections, world, camera/light settings, layout; [persistent static-scene variants and matched previews](cinematic-variants.md) | Broader composition/navigation and lighting workflows, asset-scale and placement constraints, reviewed artistic acceptance |
| Render and composite | Render settings/execution, captures; reviewed compositor graph editing | Broader nodes/image assets, passes, color/output workflows, render diagnostics and job/progress management |
| Deliver production assets | Safe native project saving is [blocked](project-save-safety.md); [cooperative texture export/reimport](texture-delivery.md), fresh texture/project reopen, [packed recovery](image-portability.md), [material-free static/skinned GLB/FBX export and fresh reimport](asset-delivery.md), [approved-source static GLB/material-free FBX import](asset-import.md) | Safe authorized project save and portable `.blend` delivery; broader skinned/animated/material asset import, textured FBX exchange, complete dependency packaging, broader recovery/formats and production validation |
| Operate interactively | Status/history/permissions/stop/pause; [4K painting jobs](painting-jobs.md), [bounded rigid evaluation jobs](rigid-body-evaluation-jobs.md); [persistent plans/exact references/guarded transform previews and corrections](task-plans.md) and [static-scene variants](cinematic-variants.md) | Visual references, wider protected authoring/previews, protected save, broad durable variants and general long-operation/bake jobs |
| Work safely and improve results | Checkpoints, batch failure evidence, bounded [structural comparisons](scene-evidence.md) including optional rigs/animation/nested shaders; per-domain ownership guards | Enforced complete preservation, remaining mutator/recovery audits, mixed-editor/pressure evidence, aesthetic iteration and whole-project benchmarks |

Each row needs representative end-to-end tasks with observable success, failure and recovery
before claiming full coverage. Capability names are not equivalent to complete editor/property
coverage. Any narrower 1.0 scope must be explicitly agreed and documented, not silently substituted
for the requested full-artist target. Raw Python is not a substitute for completing these rows.

## Reliability promise underneath that target

The original [artist-tools increment](artist-tools.md) added 25 structured tools across compositor,
weights, drivers/NLA, cloth caches and Geometry Nodes zones. Factory-startup evidence on Blender
4.5.1 and 5.1.2 includes evaluated motion/geometry, cloth deformation and a measured compositor
render. Later bounded foundations are linked in the coverage table. Historical Windows
results do not qualify the current source; no capability or recovery gate is closed by tool count.

A dependable, consent-first local bridge for the documented structured Blender workflows:
inspect, resolve targets, checkpoint, edit, structurally verify, visually verify where relevant,
and save only with permission. Arbitrary Python stays a disabled-by-default super-permission,
not evidence that every Blender feature has a dependable structured implementation.

The confirmed 1.0 qualification target is Windows 11 x64 on Blender 4.5 LTS and the newest
compatible stable 5.x at candidate freeze, with exact patch versions recorded. The current
development manifest still declares 4.2; this is not a newly qualified 1.0 support claim.
Historical Windows checks exercised 4.5.1 LTS and 5.1.2, while this implementation session
uses Linux development runners for 4.5.14 LTS and 5.2.2. Their results remain
separate from Windows qualification; source-matched outcomes and failures are retained in
the historical [development checkpoint](artist-workflow-checkpoint-20261022.md) and
the [2026-10-23 checkpoint](artist-workflow-checkpoint-20261023.md). Windows-specific
compatibility and testing are **DEFERRED until the full functionality is implemented**
on the available Linux 4.5.14/5.2.2 runners. Windows remains **unverified** and is not
a blocker to this implementation pass. Complete Windows native and installed-package
acceptance remains a future stable-release gate; Linux development results do not qualify
Windows or other platforms for 1.0. Align the manifest and support claims only at
candidate qualification.

## Current native witness blocker

The source-only acquisition/entry review at receipt SHA-256
`a5936fdd28a81ce6f682a77bfbf056ee012f8a28e89b4c97af5cd2451b314aff`
finds that Python scheduler phase, epoch and mutation leases cannot certify the
lifetime of cached Main for an external raw reader. Cached `bpy.data.as_pointer()`
has no validity check, and native reset can release Python references before its
later refresh. This is source evidence, not a reproduced crash or native acceptance.

This gap applies to the earlier strict same-Main/raw pending-Base witness
guarantee. It does not block ordinary screenshots or the whole useful product:
ordinary `viewport.capture` works with artist protection unarmed. Its framing
evidence does not establish the older passive raw-state guarantee.

The architecture is **official, unmodified Blender only**, with no fork, custom
build or distribution. The proposed Blender-owned snapshot API is absent from
the reviewed binaries; custom-API implementation work is stopped outside the
candidate, with its analysis retained as history rather than a product prerequisite.
Python phase/epoch/lease checks still cannot stand in for the missing witness.

Authorized stock redesign options are explicit synchronization with declared
effects, or a separate Scene/process snapshot preview. `GPUOffScreen` still
reaches dependency-graph evaluation, context getters can ensure synchronization,
and explicit `ViewLayer.update` must be treated as an authorized mutation rather
than a passive read. No new profile is qualified by this decision. Current
protected capture remains refused until matched parent authored-data/context
preservation is demonstrated. A redesign may not clear or rebase armed
protection, accept a changed baseline after synchronization, or restore over
intervening manual edits. The 29 items and 14 gates remain unchanged.

Safe saving has a separate blocker: asset-catalog `SAVE_POST` effects extend
outside authored Main. A snapshot witness alone cannot establish approved-path
filesystem effects or complete project delivery. See [capture design](protected-capture-design.md)
and [save safety](project-save-safety.md). Existing holds remain in place.

## Release gates

| Gate | Required acceptance evidence | Current gap / next work |
| --- | --- | --- |
| Target and data ownership | Every modifying domain documents shared data, linked libraries, overrides, active/multi-object modes and hidden scope; rejects unsupported cases before mutation | Mesh/UV/material, object/data/Action and collection/parenting guards exist with bounded regressions; complete per-tool/dependency audit, protected enforcement and recovery acceptance remain |
| Recoverable edits | Deliberate mid-operation faults, canceled callers, operator failures and manual undo interleaving leave truthful history and verifiable recovery state | Checkpoints/batches are not transactions. [Conservative capacity reporting/pruning](native-recovery.md) and a long/manual-eviction fixture exist; memory-pressure, production-scale mixed-editor/domain, durable recovery and UI acceptance remain open. Never expand user preferences silently |
| Preserved context | Each representative workflow proves unchanged mode, selection, active object, visibility, UV layer and unrelated data where promised | Bounded restoration has coverage, but known preflight getters can normalize selection before denial; entry diagnostics report possibility and do not prevent it. UV layer activation/operator context and full preservation remain open |
| Bounded evidence | Explicit truncation, stable pagination rules, large-scene fixtures and measured time/memory reports | Hard limits exist; add performance baselines and inspect partial-result handling across domains |
| End-to-end workflows | Modeling, materials/nodes, UVs, rigging, animation, scene layout and rendering each have an install-to-result scenario with pre/post evidence | Current factory-startup smokes cover portions, not complete production acceptance |
| Visual verification | Retained, matched viewport/render evidence for appearance-sensitive acceptance scenarios | Exact-object framing has matched captures and independent projection/pixel checks; protected capture still refuses, and complete appearance-sensitive artist acceptance remains open |
| Protocol and authorization | Versioned compatibility, reconnect, malformed/oversized frames, duplicate IDs, timeout/cancel, pause/stop and Python gates pass adversarial tests | Core tests exist; expand live disconnect and recovery scenarios; no LAN listener |
| Installation and upgrade | Fresh ZIP/wheel/plugin installation, previous-release upgrade, rollback, paths with spaces and disconnected/restarted Blender tested on claimed platforms | Package/metadata/checksum/clean-wheel CI exists; interactive install and platform matrix remain open |
| Public contracts | Registry, schemas, README, permission matrix, error codes, limitations and migration notes agree for the release commit | Generated inventory is checked; audit full parameter/error contracts and freeze supported surface before RC |
| Release provenance | Packages built from one tested commit; all checks green; checksums verified; downloadable assets and reproducible test report retained | Packaging gates exist; combine Blender acceptance evidence with CI for each release candidate |

No row is complete merely because its happy path passes. Permission denial, unsupported
context, preservation constraints and recovery are part of the acceptance criteria.

The [frozen 246-tool static audit](development-evidence/mutator-audit-20261022.json)
inventories that increment's 184 modifying handlers (183 remote), with manual priority screening
of 20 rig/transform/modifier/constraint handlers. Missing direct context use is a screening
signal, not proof that entry authorization is absent. Nine open findings include automatic
binding's missing pre-existing weight recovery, context-free multi-write compensation and
incomplete rest-rig consumer scope. Subsequent [rig](rig-edit-boundaries.md) and
[object-property](object-rna-safety.md) increments add bounded weight/rest/pose and
per-write compensation checks. They do not retroactively close this historical inventory:
current-source adversarial proof and the remaining per-tool/dependency audit are still required.

## Delivery sequence

The current UX-01 increment adds optional immutable step links to existing transform
previews, bounded runtime receipts from the actual finalized outer operations, and
explicit protected-only comparison observations. Reconnect retains them; undo/redo
invalidates observation currency, and plan replacement/load/reset discards them.
Sidebar execution evidence remains separate from claimed completion. The saved-v1
document stays passive. Portable boundary tests and the extended native artist-loop
fixture are described in [task plans](task-plans.md). Both Linux builds have passed
the extended artist, multi-target native-push and interactive undo fixtures; their
source-specific evidence is recorded in the [dated checkpoint](artist-workflow-checkpoint-20261023.md).
Object framing also has independent projection/pixel evidence. Capture while
protection is armed still refuses. Native context getters can normalize selection
before a permission denial; [bounded entry diagnostics](entry-context-effects.md)
report that possibility and do not prevent it. The Scene reservation and
owned-checkpoint kernel now supports public bounded rigid evaluation. Its exact
`aacb39d` public RPC fixture passes on both Linux builds with two successful jobs,
eight stopped jobs and retained-receipt capacity refusal per build. This evaluates
three-body/three-frame worlds; it does not establish cache coverage, asynchronous
baking, the full 16-body/32-frame bounds, production memory/latency or installed
MCP-to-Blender acceptance. Portable official SDK tests are separate evidence.
See the [adapter contract and source/report](rigid-body-evaluation-jobs.md).
This does not close SIM-01, JOB-01, UX-01 or any full-artist release gate.

1. **Safety baseline:** close ownership/context gaps, add regression fixtures, strengthen failure evidence.
2. **Daily workflows:** finish targeted structured editing gaps and add whole-task acceptance scenarios.
3. **Compatibility and usability:** exercise installation/upgrades and Blender/platform matrix; align UI and docs.
4. **Release candidate:** freeze supported contracts, run the complete matrix from a clean checkout,
   review remaining known issues, and package a candidate. Fix release blockers before 1.0 publication.

The capability matrix is part of the 1.0 target, alongside these safety gates. Specialist
features and exact editor/property coverage require explicit scope decisions and honest
limitations; they must not be silently claimed through Python or omitted without agreement.

## Current increment: shared mesh ownership

The progress sections below retain historical implementation and fixture results. Their
test counts and Windows versions belong to those source increments. Current development
verification is tracked in the execution log and its source-matched checkpoint reports;
historical results do not establish current or full-release acceptance.

Selection-scoped mesh edits (normals, delete, dissolve, extrude, inset, bevel, seam marking)
and UV unwrap/Smart Project/packing now require local, non-override, single-user mesh data.
Unsupported ownership returns `NOT_IMPLEMENTED` before editing or creating a UV layer.
Inspection remains available for shared meshes. This does not silently copy data or make
linked assets local; those are separate user decisions. Other editing domains are not
covered by this guard and still require the audit above.

## Cooperative painting lifecycle progress

[Texture-delivery foundations](texture-delivery.md) now distinguish PNG storage, native float
association and raw recovery. Internal stream encoders, approved-folder owned staging,
no-clobber publication and complete file-hash proofs are integrated into a typed job. Reviewed uncompressed
RGBA FLOAT32 EXR and large PNG now use shared streaming preflight in the registered import/
binding/pixel-inspection paths, with explicit EXR interpretation. Cooperative export/reimport now
retains file effects in terminal jobs/history and uses guarded native image publication with
complete pixel comparison. Fresh-process/durable edited-input recovery, packing/save/reopen
and broader production delivery remain open. Windows directory
pinning and adversarial cleanup/consent tests advance the path contract, not general filesystem
security, crash durability or release acceptance. Generated-buffer alpha handling is render-verified against file references on
the tested versions; correctness of readback alone had missed a Blender 4.5 transparency issue.

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
defines the eight default measured fields, optional extensions, record/byte limits,
identity/lifecycle behavior and exclusions.

The protected-material fixture checks independent before/after hashes for a shared-mesh
duplicate while another object's material is isolated and edited. It also detects shared
shader, same-count coordinate, UV and weight changes and rejects permission bypass. Native
recovery is followed by a complete baseline comparison in the interactive undo fixture.

The default fields implement the first EVID-02 evidence slice. Optional bounded rig, animation
and nested shader-dependency fields now extend coverage; unsupported/budget-limited evidence
stays incomplete. Snapshots do not enforce protected scope or fully cover modifier/constraint
settings, image pixels, evaluated geometry or appearance. Those remain requirements for full preservation
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
