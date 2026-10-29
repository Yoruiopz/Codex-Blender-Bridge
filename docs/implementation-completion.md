# Full artist implementation checklist

Current direction, **2026-10-26**: finish the entire agreed artist workflow through
structured tools. The 29 items below define the remaining implementation work;
they are not a tool-count target, a scope reduction or release acceptance.
All fourteen [release requirements](release-1.0-ledger.json) remain **OPEN**.

The completion target remains normal human artist work in standard Blender.
Ordinary textured/rigged projects, existing animation and procedural data, 4K
textures and portable `.blend`/GLB/FBX delivery must be supported through the
required structured workflows. Treat alpha exclusions as implementation gaps
with explicit next steps. Closing an item requires useful operation and measured
preservation/recovery on representative projects at their original resolution.
Keep current save-profile limits separate from other tools' 4K evidence, and
include ordinary 4K save/reopen and current-pixel preservation in H01/A04/I02.

Use the available Linux Blender **4.5.14** (`62c1db4208e8`) and **5.2.2**
(`d13f752e3b9c`) for implementation checks. **Windows-specific compatibility and
testing are deferred until implementation is complete, remain unverified, and do
not block this implementation pass.** Windows 11 and installed-package acceptance
remain mandatory for the later stable 1.0 candidate.

Published [**0.9.0 alpha**](releases/0.9.0.md) dates to 2026-10-28 at
**16:09:45 UTC**, from `d756b68bc8b44a4da69862214a19ebb25034d1eb`. Its
[exact-source evidence](releases/0.9.0.md#verified-release-evidence) records seven
CI jobs, 10,795 tests plus three Windows-only skips per matrix cell, selected
Linux source/installed checks and all six anonymous download hashes. The finite
save profile supports clean, loaded, packed FILE images within 16,777,216
aggregate pixels, 80 MiB packed bytes and 256 MiB saved files. It does not qualify
current edited pixels, paired 4K recovery or complete artist-project delivery.
Earlier releases and evidence remain available.

The [current blocker plan](releases/0.9.0-blocker-plan.md) gives concrete work
beyond that profile. All 29 items and fourteen gates stay **OPEN**. Meaningful
tested prereleases are authorized, but elapsed time does not require publication,
and stable 1.0 criteria remain unchanged.

Current private work has three prerequisites: detached stored-setting snapshots
for cloth/render observation; bounded Mesh-storage preparation with retained
ownership/recovery; and GLB Runtime observation/creation/publication. Their native
integration and installed acceptance remain unqualified. Mesh-storage handlers
and current-pixel lifecycle controllers are not public registered tools. The
proposed paired 4K 640 MiB packed / 1 GiB saved-file profile remains private and
unqualified; preserve accepted public save limits until new evidence qualifies
an extension. These steps support H01/H03/A04/A07/P02, not closure of those items.

The private [structured GLB Runtime candidates](structured-glb-import.md) add
new-owned staging and explicit Scene publication entry points in development
source only. They remain **UNQUALIFIED** until matching Runtime, native and
installed acceptance; the earlier private constructor evidence does not qualify
registered import or delivery. Full textured/skinned/animated GLB, FBX, protected
consumer preservation and recovery remain required. All 29 items and fourteen
gates remain **OPEN**. Logical preservation permits only
source-qualified, declared bit-preserving ARRAY/COW/cache and empty deform-layer
observation effects; 5.2 SINGLE preparation and actual native/installed acceptance
remain separate explicit gates. Rich artist data must not be cleared or excluded.

## Current foundations and unfinished work

Repair, cuts/bridges/slides, base-surface projection, UV authoring/refinement,
nested materials, image jobs/recovery, orthographic surface strokes/stencils,
sculpt/color/weight tools, bounded rigs/animation, GN/rigid evaluation, plans,
receipts and target verification already exist within documented limits. Their
results are tied to specific sources; they do not establish complete current-source
workflow acceptance. Published 0.5.0 admits 4,096-square inputs for bounded
surface jobs and generated-image sculpt-mask reads; synchronous surface painting
retains its 1,048,576-pixel limit. Exact-source memory, interruption and installed
checks are retained in the [0.5.0 evidence](releases/0.5.0.md#verified-evidence);
visual, constrained-memory, durable and full-workflow acceptance remain required.
Those historical executions do not supply 0.6.0's separate qualification. Rigid evaluation
is not baking, and asset exchange remains limited.

The registered quaternion workflow at `c49cd0f` is a bounded authored-channel
foundation. UV storage/reader results at `e96362f` and `093aeb9` are historical
source-specific native research. The current source integrates a retained-intent
[guard for three direct UV tools](uv-edit-safety.md), with exact Float32 comparisons,
fresh leaf resolution and attempted-field compensation within a restricted profile.
The published 0.5.0 source has selected registered-tool native evidence; full F02,
native undo, durable recovery and appearance acceptance remain open. Published
0.4.0 export and weight corrections retain their bounded evidence and limits.
Later curve, direct-weight, cloth-job, material-recovery, native-save and private
GLB increments are excluded from published 0.6.0's claims. Their own current-source
evidence does not retroactively qualify the released packages; no operational
cloth-job or full character-workflow claim follows from this checklist.

Each item needs the relevant success, permission-denial, invalid-context,
protected/context-preservation, injected-failure, interruption/manual-interleaving
and measured-recovery cases on both Linux builds. Verify intended results
independently; retain reviewed matched visuals when appearance matters. Record
source/package identities, hardware, peak memory, native blocking intervals and
cancellation/deadline behavior. A known refusal does not fill a required missing
capability, and a fixture-only save is not safe product saving.

Implementation targets **official, unmodified Blender only**, without custom
builds, forks or distributions. The [native witness finding](release-1.0-readiness.md#current-native-witness-blocker)
limits the earlier strict same-Main/raw pending-Base guarantee; it does not block
ordinary unarmed capture or every useful verification workflow. Authorized stock
redesign options are explicit synchronization with clearly declared mutation
semantics, or a separate Scene/process snapshot preview. Each must qualify matched
parent authored-data/context preservation without clearing or rebasing armed
protection or restoring over manual edits. Current protected capture still
refuses. Safe-save catalog effects remain separately unresolved; H01/H02 and all
29 items remain mandatory.

The geometry-only preview in published 0.6.0 passed selected registered-tool checks on both
Linux builds, including denial, stale handles, cancellation and running-worker
revocation. Its measured source projection remained unchanged under real plan
enforcement with a null protected-data baseline. Original material/current viewport
appearance, a populated protected baseline and complete hidden preservation remain
unqualified. The exact ZIP also passed the bounded installed start/inspect/image
and upgrade/rollback routes described in the release evidence; complete installed
artist scenarios and restart/preference migration remain unqualified. Ten reviewed
images establish structural framing and silhouette only. Core history/reporting containment also
passed real native loopback failure cases on both builds, with no extra finalization
or work after a rejected job start. Neither increment closes a checklist item. Published 0.7
adds separate selected populated-data and raw-point/weight evidence; it does not
qualify full protected objects, original materials or the new native-save workflow.

## B0 — Safety, recovery and evidence

Complete these prerequisites for each touched domain. Unrelated domains can
advance in parallel; the final shared audit closes only after all are covered.

| ID | Requirements | Remaining contract and completion check | Scenarios |
| --- | --- | --- | --- |
| F01 | SAFE-01/02, EVID-01 | Finish the per-mutator ownership/consumer/mode/context matrix and pre-provider/checkpoint admission, per-write authority/CAS and recovery proof. Cover shared, linked, override and transitive dependencies in every modifying domain. | A–F |
| F02 | SAFE-02, REC-01, ASSET-01 | Finish the three existing UV mutators' retained-plan boundary: exact Float32/signed-zero CAS, qualified session/layer witnesses, complete unselected-map/geometry/selection/role preservation and field-only recovery/history. | B |
| F03 | REC-01, SAFE-02 | Finish measured domain recovery, conservative undo availability, manual interleaving, history eviction, memory pressure and durable restoration. Preserve unowned work; buffers and undo history are not backups. | A–F |
| F04 | EVID-02, SAFE-01, UX-01 | Complete required target/protected/dependency evidence for geometry/custom data, constraints/modifiers, images, rigs/motion, caches and Scene/render state. Unknown, stale or partial evidence cannot pass; disclose getter effects. | A–F |
| F05 | JOB-01, SIM-01, LOOK-01 | Finish owned long-operation adapters for required bake/render/procedural work: progress, deadlines, cancellation/disconnect, invalidation, retained effects and capacity limits. Measure native stalls and declared-scale memory. | B, D–F |
| F06 | EVID-01/02, REC-01 | Maintain complete coverage and exact-source evidence; run focused, full portable and final complete Linux native inventories, including interactive cases. Retain evidence beyond expiring CI without deleting user or sealed artifacts. | A–F |
| F07 | EVID-01, SAFE-02, JOB-01, UX-01 | Preserve loopback/main-thread/Blender authorization and request lifecycle under integrated workloads: malformed/oversized/duplicate requests, one terminal response, reconnect, stop and no untracked late writes. | A–F |

## B1 — Required safe alternatives for held blockers

Start concrete safe-design work alongside B0. Keep existing refusals and held
investigations intact; do not retry them or relax proof to meet a schedule. If no
supported safe alternative can fulfill the required contract, implementation is
still incomplete.

| ID | Requirements | Remaining contract and completion check | Scenarios |
| --- | --- | --- | --- |
| H01 | DELIVER-01, REC-01, UX-01 | Provide safe current-file Save, Save As and complete portable `.blend` delivery with bounded native callbacks/effects, approved paths, explicit overwrite policy and full fresh-process reopen. Legacy [save refusal](project-save-safety.md) stays held; extend the separately qualified finite native-save alternative to ordinary artist projects and edited pixels. | A–C, E–F |
| H02 | UX-01, EVID-02, LOOK-01 | Provide a supported protected visual-verification strategy with qualified native witnesses and predicted evaluation/isolation/restoration effects. Keep [protected capture](protected-capture-design.md) refused until then; solid-only evidence cannot certify materials. | A–C, E |
| H03 | DELIVER-01, SAFE-01 | Provide a separately qualified strategy for required 5.2 import workflows without invoking or bypassing the [exact-build quarantine](asset-import.md). Prove source/dependency consent, destination ownership, complete content and recovery. | F |
| H04 | SAFE-01, LOOK-01 | Complete required shader removal/conversion through a separately reviewed lifecycle/consumer-migration design. Held REMOVE work stays held; preserve declared nested users, identifiers, links, defaults, animation and recovery. | B, E |
| H05 | SAFE-02, CHAR-01, REC-01 | Provide required animation-authoring safety without retrying the held Timeline/provider reproduction. Qualify a supported writer's retained intent, live authority, descriptors/context and measured recovery; stored-curve inspection is insufficient. | C |

## B2 — Asset, UV, texture, paint and look development

| ID | Requirements | Remaining contract and completion check | Scenarios |
| --- | --- | --- | --- |
| A01 | ASSET-01 | Finish reference-constrained modeling/retopology, unequal/multiple/open correspondence, localized/cross-object/evaluated diagnostics and outward/custom normals. Verify repaired topology, silhouette/material preservation and recovery. | B |
| A02 | ASSET-01, SAFE-02 | Finish supported shared-data, shape-key and broader protected geometry edits with explicit affected consumers, identity/key correspondence and recovery. Refuse unsupported combinations before writes. | B–C |
| A03 | ASSET-01, EVID-02 | After F02, finish UV Editor corner scope, cross-object/evaluated atlases and overlap/stretch/density/unwrap quality. Preserve other maps/pins/geometry/materials; review atlas/checker results. | B |
| A04 | PAINT-01, LOOK-01, REC-01 | Finish production texture sources/formats/roles, original-byte versus current-pixel packing, dependencies and durable original-ID recovery at 4K/constrained memory. Reopen without external sources and compare complete pixels/roles/bindings. | B, F |
| A05 | PAINT-01 | Finish perspective/viewport strokes/stencils, 4K-square surface/stencil/sculpt masks, broader blends/source roles, multires and production sculpt/vertex/weight paint-bake feedback. Independently verify output, preservation, interruption and recovery. | B–C |
| A06 | LOOK-01, SAFE-01 | Finish nested material/interface lifecycle, animated maintenance, required nodes/properties and complete dependency preservation through the qualified H04 path. Review textured-asset revisions and protected aliases. | B, E |
| A07 | LOOK-01, JOB-01 | Finish compositor images/graphs/passes, color/output, render diagnostics/jobs and a safe supported 5.2 rendering path. Enumerate required contracts and verify matched renders; current hidden-SYSTEM refusal is not success. | B, E |

## B3 — Character and animation

| ID | Requirements | Remaining contract and completion check | Scenarios |
| --- | --- | --- | --- |
| C01 | CHAR-01 | Finish control-rig/IK authoring and animated-control revision beyond the static one-IK profile. Preserve skin/rest/constraint/shared consumers and independently verify reach, bend plane, deformation and recovery. | C |
| C02 | CHAR-01, PAINT-01, EVID-02 | Finish production skin/deformation diagnosis and weight-brush/mirror/transfer correction. Check all declared vertices and sampled poses, protected corresponding-frame state, larger/memory-limited cases and reviewed joint quality. | C |
| C03 | CHAR-01, SAFE-02 | Through H05, finish combined curve/handle/interpolation, bone/custom-property driver, Action and NLA transition/order revisions. Verify evaluated multi-frame motion and protected unrelated animation under failure/recovery. | C |

## B4 — Procedural simulation and cinematics

| ID | Requirements | Remaining contract and completion check | Scenarios |
| --- | --- | --- | --- |
| P01 | SIM-01 | Finish nested GN/interface/modifier lifecycle, repeat/simulation conversion and public bake/free/invalidate/rebake with evaluated diagnostics. Prove coverage, stable consumers/identifiers and approved disk-cache effects/recovery. | D |
| P02 | SIM-01, JOB-01, REC-01 | Finish representative cloth/rigid/fluid setup, solver/dependency combinations and memory/disk caches through bounded jobs. Prove actual bake coverage, repeated free/rebake, interruption and recovery at declared scale. | D |
| P03 | LOOK-01, UX-01, EVID-02 | Finish composition/navigation/scale/placement and camera/light/compositor variants around an animated protected character. Compare three meaningful matched variants, refine the chosen result and review appearance/preservation. | E |

## B5 — Integrated artist loop and delivery

| ID | Requirements | Remaining contract and completion check | Scenarios |
| --- | --- | --- | --- |
| I01 | UX-01, EVID-02 | Integrate references/plans/protected scope, previews/summaries, comparisons, variants/corrections and progress/cancel/history. The external agent completes brief → inspect → plan → checkpoint → edit → verify → refine → authorized save/delivery without operator-by-operator directions. | A–F |
| I02 | DELIVER-01, LOOK-01, CHAR-01 | Finish complete `.blend`, textured GLB/FBX import/export/packaging, units/transforms/materials/skin/animation/dependencies and declared losses/overwrite policy. Independently reopen/reimport in fresh processes; limited export/import and fixture-only save do not pass. | F |
| I03 | All except RC-01 | Complete source-integrated Linux scenarios A–F through actual structured MCP/addon flow and the common checks above. Bind final source/logs/visuals; any missing mandatory function or held path without a safe alternative keeps implementation incomplete. | A–F |
| I04 | EVID-01, RC-01, UX-01 | Replay required installed Linux workflows from matching ZIP/wheel/plugin/checksums without checkout imports. Verify fresh install, 0.3.0 upgrade/rollback, restart/reconnect and spaces in paths; retain the Python 3.10–3.12 × MCP 2.0.0/2.2.0 matrix. | A, F |

The [scenario definitions](plan-1.0.md#end-to-end-acceptance-scenarios) remain A:
install/control; B: repair/texture; C: character motion; D: procedural simulation;
E: cinematic variants; F: production delivery. B2–B4 can advance independently
after their domain safety. B5 depends on the actual preceding capabilities;
I03 establishes source integration and I04 verifies installed-package replay.

## Pre-release delivery and later stable qualification

1. Keep development documentation honest about implemented limits, holds and
   deferred/unverified Windows testing.
2. At a meaningful reviewed increment, choose matching three-integer component
   versions and build add-on ZIP, MCP wheel, plugin ZIP and checksums from one clean
   reviewed commit. Run appropriate focused/full portable and Linux checks.
3. Publish a versioned GitHub **pre-release**, retaining exact source/package
   evidence and clear verified limitations. Preserve previous releases. A merge
   requires its exact proposal first where the established flow needs it.
4. Verify downloaded bytes and the declared installed Linux behavior. Do not
   bypass the separate stable 1.0 workflow or promote a pre-release to acceptance.

After implementation completion, select exact supported Windows patches and run
both complete Windows 11/private-desktop native matrices and installed A–F,
upgrade/rollback/reconnect/path checks. Bind all fourteen accepted requirements,
reviewed visuals and retained evidence to exact candidate packages before stable
1.0 qualification. Pre-release authority does not change those gates.
