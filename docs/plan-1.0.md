# 1.0 execution plan

Status: active, **not release-ready**. Planning baseline: `3ad11a3`, 2026-09-27.
This is the current execution plan; `implementation-plan.md` describes the historical MVP.
The [readiness gates](release-1.0-readiness.md) remain the release acceptance contract.

**Native-save blocker:** `project.save` refuses both current-file
Save and Save As. Hidden C asset-catalog callbacks and runtime save effects are
not bounded by existing path/permission checks. Earlier typed-save results are
historical; current feature reopen fixtures use labeled owned setup serialization.
Safe authorized saving and portable `.blend` delivery remain mandatory open
requirements, with no scope reduction. See [the safety contract](project-save-safety.md).

## 0.7.0 alpha candidate — 2026-10-25

The [candidate notes](releases/0.7.0.md) cover retained direct-weight recovery,
`RAW_FREE_POINT_V1` and populated selected-field geometry-preview evidence.
Matching 0.7.0 component metadata prepares qualification; it is not publication.
Published 0.6.0 remains the recommended download. Exact candidate CI/packages,
installed checks and supported-profile native acceptance remain pending.
Reported preview image-review discrepancies must remain retained and resolved
before visual acceptance. All 29 implementation items and fourteen stable gates
remain open; Windows remains deferred. Unsupported non-FREE/current-pose/broad
curve operations have no arbitrary-Python fallback.

## Current implementation priorities — 2026-10-25

The [29-item implementation checklist](implementation-completion.md) is the
current finite worklist for the full agreed artist workflow. Finish the existing
safety/recovery boundaries and required save/protected-visual alternatives, then
complete asset/look/paint, character and procedural/cinematic workflows in
parallel as each domain becomes safe. Integrate scenarios A–F through actual
structured tools and installed packages; do not substitute tool counts, private
research or isolated happy paths for functional completion.

Implementation checks use available Linux Blender **4.5.14** and **5.2.2**.
**Windows-specific compatibility/testing is deferred until implementation is
complete, remains unverified, and is not a blocker to this implementation pass.**
It remains a mandatory future stable 1.0 qualification gate. Existing save,
protected-capture, shader REMOVE, animation-provider reproduction and exact-build
5.2 import holds remain; required capabilities need separately reviewed safe
designs/alternatives, not retries or weaker evidence.

Meaningful versioned GitHub **pre-releases are authorized**, on an approximately
two-to-three-hour review cadence. The latest published
[**0.6.0 alpha**](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.6.0)
dates to 2026-10-25 at **14:29:56 UTC** from
`73cad805903fcd0be9175b49a5ecf78505ecd4a5`. Its
[exact-source evidence](releases/0.6.0.md#verified-evidence) includes all seven CI
jobs, 8,403 tests with three Windows-only skips per matrix cell, eight selected
interactive source processes, four installed background processes with sixteen
phase observations, ten reviewed geometry images and all six anonymous download
hashes. Those checks do not qualify later development increments or complete
artist workflows. The [published blocker plan](https://github.com/Yoruiopz/Codex-Blender-Bridge/blob/codex/release-0.6-publication-evidence/docs/releases/0.6.0-blocker-plan.md)
records the ordered next implementation and verification milestones. All 29
implementation items and fourteen stable gates remain **OPEN**. Build matching components
and checksums from a clean reviewed increment, disclose limits and unverified
Windows status, and verify downloaded bytes. Preserve previous releases. Present
an exact merge proposal where required; merge permission is not blanket. The
[stable release gates](release-evidence.md) and historical evidence below are
unchanged. See the checklist for current foundations and work still in progress.

The architecture uses **official, unmodified Blender only**: no custom build, fork
or distribution. The [native witness finding](release-1.0-readiness.md#current-native-witness-blocker)
blocks the earlier strict same-Main/raw pending-Base guarantee, not ordinary
unarmed screenshots or useful visual verification. Stock redesign work may use
explicit synchronization with declared mutation semantics, or a separate
Scene/process snapshot preview. Protected capture remains refused until the new
profile is qualified. It may not clear or rebase armed protection, restore over
manual edits, or omit matched parent authored-data/context checks. Safe-save
catalog effects remain a separate unresolved requirement.

## Outcome and scope

Ship a downloadable, installable, consent-first bridge that lets an agent complete full
3D-artist workflows through structured tools, measured scene state and visual iteration.
Do not replace this target with “all current tests pass”, a tool count, or raw Python access.
The original installation/inspection/mesh/undo/UI/save requirements remain mandatory, and
the subsequent full-artist request adds advanced modeling, sculpt/paint, UV/texture, material/
compositor, rig/weights, drivers/NLA, simulation/baking and Geometry Nodes zone workflows.
Preserve the user's scope, permissions, recoverability, interactive control and explicit saving.

No finite tool list alone proves “everything”. Maintain a coverage ledger of editor/data
families and uncovered properties/workflows. Do not silently move difficult features past 1.0.
Any proposed scope reduction requires an explicit user decision, not a roadmap wording change.
The agent remains external to Blender; embedded model hosting is outside the agreed 1.0 release.

## Confirmed release decisions — 2026-10-22

The user authorized implementation of the full ten-step release plan. The target remains
full artist-workflow 1.0 with Windows 11 x64 qualification first, Blender 4.5 LTS and the newest
compatible stable 5.x at candidate freeze. Portable `.blend`, GLB and FBX delivery are mandatory.
Other desktop platforms remain unqualified for 1.0; the current development manifest is not
yet a newly qualified support claim. Prefer reliable bounded jobs with measured native stalls,
visible progress and truthful cancellation/recovery. The user's later direction is to make
the repository public-facing, using GitHub as needed; this supersedes the earlier visibility
constraint. Prepare public documentation and contributor/support entry points and make the
GitHub repository public. The user subsequently made it public; anonymous repository,
documentation and existing release downloads were verified. This is separate from qualifying or publishing 1.0. Distribute
matched packages through GitHub releases. Preserve all earlier releases, including
0.3.0, 0.4.0, 0.5.0 and 0.6.0; no stable release date has been set.

The machine-readable [requirement ledger](release-1.0-ledger.json) deliberately starts open.
The [qualification checker](release-evidence.md) validates source/package provenance and retained
acceptance evidence; native smoke reports themselves remain `NOT_ASSESSED`.

## Evidence baseline

- Main has working foundations in every recently requested specialist area, but only subsets.
  Exact contracts are in [artist tools](artist-tools.md); the registry is authoritative.
- Latest baseline CI succeeded; Python tests, lint, type checking and package CI exist.
- Existing isolated smokes cover portions of workflows on Windows Blender 4.5.1/5.1.2.
  They do not prove interactive UI installation, real undo interleaving or artistic quality.
- The manifest's 4.2 minimum is not verified by the local matrix. Test it or explicitly resolve
  supported versions before RC. Do not infer Linux/macOS Blender support from Python CI.
- Published 0.6.0 remains alpha, with older releases still available. Do not
  replace accepted artifacts or publish 1.0 early.
  Public-facing repository work is now authorized; it does not close any release gate.

## Milestones and dependencies

| ID | Deliverable | Dependencies | Exit evidence |
| --- | --- | --- | --- |
| M0 | Repeatable evidence collection and coverage ledger | None | Every existing smoke runnable with explicit Blender paths; per-case logs, source/version identity, timeout/failure state; gaps remain visible |
| M1 | Ownership, preservation and recovery contracts | M0 | Audit every mutator; linked/shared/override/context cases; injected failures and actual undo/cancel/reconnect tests; no untracked late edits |
| M2 | Complete asset-creation workflow | M0; each touched domain passes M1 | Model/repair, UV edit/pins/diagnostics, texture assets, material/nested-node workflows, sculpt/paint: create a reference-constrained prop and revise it without losing protected data |
| M3 | Complete character and animation workflow | M0; domain safety from M1; required M2 primitives | Rig, constraints/IK, weight brush/mirror/transfer, deformation diagnostics, curves/actions, bone/custom-property drivers, NLA transitions/reordering; motion and deformation benchmark |
| M4 | Complete procedural/environment workflow | M0; M1 job/path contracts; required M2 primitives | GN group/modifier/zone lifecycle, rigid-body/fluid/cloth and bake/cache workflows, cameras/lighting, compositor/passes; verified multi-frame results and recoverable long jobs |
| M5 | Integrated artist loop and interactive UX | Starts with M0/M1; finishes after M2–M4 | Persistent task/protected scope, reference resolution, previews/diffs, matched captures, revisions, variants, progress/cancel/history and approved save/export work end to end |
| M6 | Release candidate and publication | M1–M5 complete; all readiness gates | Clean-checkout matrix, fresh install/upgrade/rollback, reviewed visual acceptance, matched packages/checksums, truthful docs, final requirement audit |

These are dependency gates, not calendar promises. M2–M5 may advance by independent domain
once their safety prerequisites pass; do not wait for every unrelated M1 audit to finish.
Independent domain implementation and review may proceed in parallel after their safety
prerequisites, with explicit file ownership and integration checks.

## Prioritized execution backlog

All items below are open unless matching implementation and evidence are recorded below. “Implemented”
and “accepted for release” are separate states.
Use the [current implementation checklist](implementation-completion.md) for
cross-domain dependencies and concrete completion checks; the fourteen IDs below
remain the requirement ledger.

| Order / ID | Concrete next deliverable | Acceptance / dependency |
| --- | --- | --- |
| 1 / EVID-01 | Runner and machine-readable results for existing Blender smokes | Both installed versions; timeout/nonzero/missing-success-marker fail; report never labels 1.0 ready |
| 2 / SAFE-01 | Material/shader ownership audit, including node graph edits and forced unlink | Enumerate affected users, explicit shared-scope contract, library/override checks; no damage to protected duplicate; M1 |
| 3 / SAFE-02 | Audit remaining transforms/modifiers/rigs/scene/animation mutators | Per-tool ownership/mode/permission/recovery table with adversarial fixtures, not just a common guard |
| 4 / REC-01 | Verified recovery after partial failure and actual Blender undo | Measure restored state, not merely exception-free rollback; report/prune known native-history capacity limits and stale availability; manual undo, file/session changes and memory limits remain explicit |
| 5 / JOB-01 | Responsive long-operation lifecycle | Read protocol first; correlated progress, queued-vs-running cancellation, late-result tracking; native uninterruptible operations must be honestly constrained or isolated |
| 6 / EVID-02 | Scoped structural snapshots/diffs and protected-data assertions | Bounded mesh/material/hierarchy/animation deltas; stale references, truncation and shared dependencies explicit |
| 7 / ASSET-01 | Missing modeling and UV editing primitives | Merge/subdivide/fill/bridge/loop workflows, UV layers/coordinates/pins; prop repair with silhouette/material preservation |
| 8 / LOOK-01 | Texture assets, broader shader/compositor graphs and passes | Approved paths, ownership, socket/version compatibility, renders and preserved unrelated data |
| 9 / PAINT-01 | Sculpt, texture/vertex/weight painting workflows | Real brush/stroke/mask tests and visual/deformation evidence; merely entering a mode does not pass |
| 10 / CHAR-01 | Rig/skin/animation completion | IK/control rigs, geometric mirror/surface transfer, curves/handles, driver dependency validation, NLA/action lifecycle and transitions |
| 11 / SIM-01 | Production simulation and procedural completion | GN nested groups/modifier inputs/zone conversion and bakes; rigid-body/fluid/cloth lifecycle, disk cache path consent and cancellation/recovery; JOB-01 |
| 12 / UX-01 | Task plans, references, comparison and variants | User can see scope/progress, interrupt, inspect before/after and choose variants; no unexpected saves; starts after EVID-02 |
| 13 / DELIVER-01 | Import/export, dependencies and durable saves | Approved exact paths, reopen and reimport checks, no silent overwrite, dependency/asset validation |
| 14 / RC-01 | Compatibility, installation, upgrade and release audit | Resolve claimed matrix, test packaged bits and old-release upgrade; requires all capability and reliability evidence |

The original sequence began with EVID-01, SAFE-01 and REC-01; their development increments
are recorded below, not blanket release acceptance. Historical focus (2026-10-21): ASSET-01 has
bounded repair, loop modeling, UV authoring, measured UV-quality and mesh-winding/contact analysis,
and a connected repair/unwrap/material fixture. LOOK-01 adds approved images, nested shader paths,
group lifecycle and measured instance isolation. A logical-batch revision works at default undo
capacity; longer separate operations exposed an eviction gap. REC-01 now has conservative
capacity reporting/pruning and long/manual-eviction native cases, not guaranteed history access.
LOOK-01 now includes reviewed scalar/enum settings on 14 shader node types, complete Color Ramp
replacement and sampled RGB/HSV/HSL interpretation with measured local/native failure recovery.
LOOK-01 also adds versioned node texture refresh/relocation with explicit file consent and
original-buffer retention. Native probes show in-place reload is not recovered by global undo;
identity-preserving edits and durable pixel recovery remain mandatory, not silently dropped.
An [original reference-constrained scanner](field-scanner-workflow.md) now integrates structured
modeling, shell/display UVs, nested materials, texture variants and staged native recovery.
PAINT-01 now includes generated linear/data canvases, bounded copy-on-write UV-image strokes,
raw-channel image masks with inversion/bilinear resampling, pixel digests/samples and a painted
display revision in the reference workflow. Bounded orthographic surface strokes/stencils,
sculpt/color/weight brushes and generated-image sculpt masks are now implemented.
Perspective and 4K-square surface/mask workflows, broader paint/sculpt feedback and
complete artist acceptance remain open.
JOB-01 now has source-frozen [cooperative painting jobs](painting-jobs.md): progress/cancel,
live source/consent revalidation, guarded publication and tile-bounded coverage for 4K canvases.
Full source/output arrays remain; measured native tail stalls prevent real-time/production acceptance.
DELIVER-01 now has internal streaming PNG/float-EXR codecs and native alpha/4K raw round-trip
fixtures, plus an explicit [delivery execution contract](texture-delivery.md). Internal approved-folder
staging now seals complete stream hashes and publishes without overwrite, with live edit/file/save
grants, Windows directory pins and scoped cleanup. The registered
`image.export_job_start` uses the cooperative delivery path;
reviewed public plain FLOAT RGBA EXR/large PNG import now uses the shared streaming reader.
Typed cooperative export/reimport now joins the codecs, staging and shared reader, with
complete decoded-channel checks and explicit external effects in terminal jobs/history.
It shares the paint scheduler and preserves the no-overwrite and file/native-undo distinction;
fresh-process, packing/save, scale/latency and broader delivery acceptance remain open. The
probes exposed a 4.5 generated-float transparency error that numeric readback missed; new
independent CHANNEL_PACKED buffers preserve requested RGBA and render consistently on the
tested versions. Existing images are never silently relabeled; masks/inspection remain raw.
Next extend acceptance under memory pressure, broader scale and mixed-editor interleaving before general native bake jobs; extend
surface painting and dependency/durable-pixel lifecycle while retaining
the remaining memory-pressure, mixed-editor/domain and durable recovery acceptance work.
Keep SAFE-02/JOB-01 and the remaining
capability/UX/delivery/RC work open. Work in coherent user workflows, not an indefinite series
of unrelated one-tool additions. Reprioritize using failed evidence or dependencies and retain
the unfinished full-artist target.

## End-to-end acceptance scenarios

| Scenario | Required observable result |
| --- | --- |
| A / Install and control | Fresh add-on + MCP setup; inspection/selection/mesh/capture, transforms/basic mesh edits, visible history, permission denial, pause/stop, undo, allowed save and malformed-request recovery |
| B / Repair and texture | Repair a localized shoulder/prop region, UV and texture it; materials, silhouette and protected regions checked before/after; intentional failure recovered |
| C / Character motion | Rig and skin a character, fix deformation, edit drivers/actions/NLA, compare sampled poses and animation; preserve unrelated animation |
| D / Procedural simulation | Build/edit nested GN + repeat/simulation states, run representative cloth/rigid-body/fluid bakes, invalidate/free/rebake, interrupt safely and verify multiple frames |
| E / Cinematic variants | Keep character untouched; create three lighting/camera/compositor variants, compare matched views, refine chosen variant and save only agreed outputs |
| F / Production delivery | Explicit import/export/packing, reopen/reimport and validate units/materials/animation/dependencies; upgrade from 0.3.0 and roll back in fresh profiles |

Each scenario needs success, permission denial, invalid context, preservation and recovery
cases. Fixtures use disposable scenes, never the user's live project. Record seed, brief,
expected numeric tolerances, image views and review rubric before running. Numeric truth comes
from Blender; screenshots assess silhouette/composition/shading. Artistic review cannot be
replaced by a red-pixel test or a “tool returned success” response.

## Evidence and progress rules

For each backlog item record: requirement IDs, touched code/schema/UI, implemented limits,
commands, commit/source fingerprint, Blender/OS/SDK versions, artifact paths, observed results,
preservation/recovery evidence and remaining limitations. States: planned → implementing →
implemented → accepted; blocked requires a concrete external dependency. A failing test is
evidence to fix, not permission to weaken the acceptance criterion.

Use `scripts/run_blender_checks.py` for the existing isolated smoke matrix. Its JSON report is
an execution record, **not** a release-readiness verdict. Read warnings and review artifacts.
The UV modifier smoke's success marker does not establish unwrap quality; the dedicated UV
workflow test and later distortion/overlap/visual checks serve different purposes.

Use Graphify in the primary workflow for codebase navigation: inspect index freshness first,
query narrowly for the relevant subsystem, then use exact file/symbol neighbors and linked tests
before opening full source. Check the current worktree for unindexed edits. Retrieval and static
test links are navigation evidence, not proof of complete runtime behavior or coverage. Prefer
bounded outlines first; refine noisy/broad queries instead of flooding context. Maintain the
local map using [the documented workflow](architecture-map.md); neither map replaces tests.

Before RC, run the entire claimed matrix from a clean checkout and retain evidence outside
ephemeral CI storage. Build add-on/wheel/plugin from that exact revision, test the packaged
files, verify checksums, and match all component versions. Run a requirement-by-requirement
completion audit against this plan and the readiness gates. Any missing or indirect evidence
keeps 1.0 unready. Follow the latest public-facing repository decision above. Release
publication is the final step, not the definition
of success.

## Decisions to resolve before RC (not blockers to current work)

Supported Blender versions/OSes; production scene-size/latency benchmarks; exact image-quality
rubrics and fixture licensing; supported import/export formats; and whether “standalone” also
means an embedded model runtime. Collect technical evidence and propose choices to the user
when implementation genuinely depends on them. Do not invent dates, silently lower scope,
or stop all independent progress while these decisions are open.

## Execution log

### 2026-09-27 — EVID-01 implemented, development baseline collected

Added `scripts/run_blender_checks.py` and tests for registry coverage, success markers,
exit-code failures, missing versions and timeouts. Ran all 13 existing smoke scripts on
both installed Blender versions: **26/26 passed**. Python suite: **470 passed**; lint/type
checks passed. This is smoke execution evidence, not full capability or release acceptance.

Local report: `build/acceptance-baseline-20260927/report.json` with per-case logs alongside it.
Source revision was `3ad11a3259d508b4d71f250507249111e499b28f` plus the new runner; the report
correctly records a dirty worktree and fingerprints Python sources. It is **not** clean-RC
evidence. The source fingerprint was
`70d6e042e75e47459f18e0436353559a9a4d0f5d64d90ea3f99d3d3407bc9b0e`.
Reports live locally in ignored build output; release evidence must later be retained with
the candidate artifacts. Existing user-owned unrelated changes were not modified.

Reproduce on a machine with these installations, choosing a new output directory each run:

```powershell
.\.venv\Scripts\python.exe scripts/run_blender_checks.py `
  --blender "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" `
  --blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" `
  --output build/acceptance-new-run --timeout 120
```

Use repeated `--case` flags for focused runs; `all_cases_selected=false` makes partial
coverage explicit. Each process uses factory startup and Python error exit codes; a pass
also requires the script's structured success marker with Blender version evidence.
Timed-out runs are terminated by the runner and remain failures even if a marker was printed.
The report always labels release readiness `NOT_ASSESSED`. Next work: **SAFE-01**.

### 2026-09-27 — SAFE-01 direct ownership implemented; acceptance still open

Material Principled edits, all six shader mutators and material deletion now have a shared
Blender-side ownership guard and MCP `allow_shared=false` default. Users explicitly acknowledge
shared edits after inspection; linked/override/read-only materials cannot be armed. Forced
unlink additionally checks all enumerated direct users and object modes. Exact-name resolution
rejects local/library collisions discovered in the real Blender fixture. Batched material
inspection uses datablock identity rather than names and computes the user map once.

The expanded ownership smoke checks denied edits preserve the duplicate, intentional shared
edits work, forced unlink in Edit Mode fails, and actual linked materials/name collisions fail
safely. The full 26-case Windows Blender 4.5.1/5.1.2 development matrix passed at
`build/shared-material-final-evidence/report.json` (dirty-worktree evidence, not an RC).
Python suites passed **502 tests** on both MCP SDK 2.0.0 and 2.2.0; lint, type checks and
README registry validation passed. No user project was opened or saved. These are structural
safety regressions, not visual material-quality acceptance.

SAFE-01 is not accepted in full: transitive dependencies, protected-scope assertions,
intentional per-object material copies and verified partial-failure recovery remain open.
Do not treat a bounded direct-user list as full scene scope. Next: finish the protected-material
workflow and REC-01, then apply the same audit to remaining domains without reducing the
full-artist acceptance target.

### 2026-09-27 — Explicit object material isolation and scoped failure recovery

Added `material.copy_for_object(object_name, slot_index, new_name)` to both registries and MCP
schemas with Blender-side `EDIT_MATERIALS` gating. It creates a local material/root-tree copy
and binds only the selected object's slot at OBJECT level, including when objects share mesh
data. It never copies the mesh or recursively duplicates referenced groups/images/actions.
Linked source materials can be read into a local copy without editing the library.

The real ownership fixture verifies the protected duplicate, source values, mesh, polygon
indices, selection and active object remain unchanged. Injected post-binding failure verifies
restoration of visible and latent OBJECT bindings and removal of the unused copy; runtime
errors carry `execution_started` and an explicit measured `rollback_verified` result.
Unit tests also exercise a failed recovery and ensure it is never reported as successful.

Validation: **517 tests** passed with MCP SDK 2.0.0 and 2.2.0; lint/type checks and README
registry validation passed. All **26 Blender smoke checks** passed on Windows 4.5.1/5.1.2 in
`build/material-copy-final-matrix/report.json`. This is dirty-worktree development evidence,
not RC acceptance; no user project was opened or saved. No visual-quality claim is made.

This completes the explicit per-object material-copy slice of SAFE-01 and gives REC-01 one
measured recovery case. Transitive protected scope, interactive Blender undo/manual-edit
interleaving, durable recovery and the remaining full-artist workflow gates remain open.
Next priority: actual Blender undo/recovery lifecycle evidence, not another tool-count increase.

### 2026-09-27 — Native history invalidation verified; snapshot-ordering gap reproduced

Added persistent native undo/redo hooks that invalidate stale checkpoint labels and selection
references, with scoped suppression for bridge-invoked undo and complete unregister cleanup.
Undo responses explicitly require verification and do not claim logical restoration.
The new interactive factory-startup fixture verifies native navigation, stale bridge undo
refusal without mutation, and handler re-registration on both installed Blender versions.

The first isolated native probe demonstrated that before-only snapshots can skip the latest
intended pre-state: snapshots x=0/x=1 followed by unsnapshotted x=2 yielded undo x=0 and redo
x=1. This is a concrete **open REC-01 release blocker**, not a passed logical-undo test.
Next implementation must correct snapshot ordering and verify multi-operation restoration,
native operator boundaries and manual edit interleaving. Keep the full recovery target intact.

Runner addition: `--case undo_lifecycle` runs the desktop-dependent case;
`--include-interactive` includes it in the full matrix. Default background-only runs now
truthfully report `all_cases_selected=false`. Windows UI launches initially requested
`SW_HIDE`; Blender could override that hint. The [private-desktop runner](native-testing.md)
now replaces that insufficient approach without switching the user's desktop. Child TEMP/
TMP/TMPDIR directories isolate exit recovery files under the evidence output. The initial
diagnostic probe used Blender's default temporary `quit.blend` location before this isolation
was added; subsequent runs verified the isolated path. No open user project was used.

Validation: **522 tests** passed on both MCP SDK versions, lint/type checks and README registry
validation passed. **28/28** Windows Blender 4.5.1/5.1.2 checks passed at
`build/native-undo-full-matrix/report.json`, including the two interactive lifecycle cases.
Their payload explicitly says `logical_undo_restoration_verified=false`. This is development
evidence, not full REC-01 or 1.0 acceptance.

### 2026-09-27 — Marker-based snapshot navigation and measured restoration

Replaced count-based logical recovery with distinct before/after native snapshots and bounded
navigation to a session-specific scene marker. Checkpoint target markers are never left live
for later manual/native snapshots to reuse. A recovery guard captures the current state;
target eviction, bounded traversal failure and cancellation attempt redo back to that guard
and expose whether its marker was reached. Unknown handler failures now finalize possible-
mutation snapshots, as do structured failures and batches. Finalization is reported separately
from pre-boundary creation.

Compatibility: `checkpoint.undo_last` remains one global undo by default. Explicit
`restore_snapshot=true` opts into the verified boundary path, and the Blender recovery button
uses that option. Local named checkpoint restore navigates to its marker. Checkpoint creation
is mutation-gated because it writes internal scene metadata; no hidden project file is saved.
The metadata/save/shutdown behavior and all known limits are documented in the readiness gates.

Native tests now verify consecutive transforms, internal native operator/undo steps, named
multi-operation restore, mesh vertex restoration and Object Mode after an Edit Mode round
trip, unexpected partial handler failure recovery, and return to the guard after native
history eviction. Unit tests cover bounded navigation, failed redo, cancellation, namespace
collision preservation, cleanup and unchanged legacy one-step semantics.

Validation: **534 tests** passed on MCP SDK 2.0.0 and 2.2.0; lint/type and README registry checks
passed. **28/28** Windows Blender checks passed on 4.5.1/5.1.2 at
`build/snapshot-final-verified/report.json` (dirty-worktree development evidence, not RC).
The previously reproduced before-only ordering gap is corrected for these measured global
snapshot cases; broad REC-01 acceptance remains open.

Native recovery starts in Object Mode; editor-specific operations do not claim individual
global boundaries, but earlier named global checkpoints remain identifiable. Manual edits
may be affected by confirmed global recovery. Snapshot provenance is not a proof of every
user invariant or visual quality. Next work should establish protected-scope before/after
comparisons and broader editor/domain recovery cases, then continue the full asset/character/
procedural artist workflows. No gate or full-artist requirement is removed by this increment.

### 2026-10-17 — Scoped comparison tools and protected material evidence

Added `scene.snapshot` and `scene.compare` to the core add-on/MCP registries with authoritative
`INSPECT_SCENE` checks. They capture explicitly named objects and eight defined field families,
return compact hashes/numeric summaries, preserve immutable in-memory baselines and report
changed, matching scope or unknown evidence. The [contract](scene-evidence.md) records exact
field definitions, identity/context rules, per-call limits, cache lifetime and unmeasured data.
Shared mesh/UV/material reads are reused; cancellation and incomplete captures remain explicit.

The protected-material fixture independently compares a shared-mesh duplicate while another
object's material is isolated and edited. It detects shared shader, same-count coordinate,
UV and weight changes, and tests permission denial, non-mesh applicability and project cache
invalidation. The interactive recovery fixture now follows native undo with a complete numeric
baseline comparison. Snapshot capture itself does not modify/save Blender data or create undo
entries; none of these fixtures opens a user project or claims visual-quality acceptance.

Validation: **559 tests** passed with MCP SDK 2.0.0 and 2.2.0; lint/type checks and generated
README validation passed. **30/30** Windows Blender checks passed on 4.5.1/5.1.2, including
interactive recovery, at `build/scene-evidence-reviewed-matrix-20261017/report.json`.
The report records source revision `18e513c690b602bd1ac3a27cc2c8029b04ce61bd` plus this work,
a dirty worktree and Python source fingerprint
`726408dc409a0e17530b027c421ecffe1d1cc7c83c003b914e8bdff7e746c85c`.
This is development evidence, not clean-RC acceptance. Unrelated user changes were preserved.

This is the first implemented EVID-02 slice, prioritized to give SAFE-01/REC-01 independent
before/after evidence. Automatic protected-scope enforcement, modifiers/constraints, rig/
animation state, evaluated geometry, nested shader contents and visual comparison remain open.

Next concrete REC-01 check: exercise `context.set_mode` through the dispatcher. Source audit
shows `after_modification` clears tracking when native finalization fails outside Object Mode;
the existing native round-trip fixture changes mode directly and does not prove preservation
of checkpoints through the structured mode tool. Resolve and verify that path before claiming
automated Edit Mode recovery, then use these comparisons in the ASSET-01 prop-repair workflow
and implement its missing modeling/UV primitives. The full 3D-artist target remains unchanged.

### 2026-10-17 — Structured Mesh Edit Mode recovery verified

Reproduced the dispatcher regression: `context.set_mode(..., mode="EDIT")` completed, but
post-tool finalization rejected Edit Mode and erased the named checkpoint. The new native
fixture failed on the missing checkpoint before the repair.

The manager now retains a deferred single-mesh edit interval from its Object Mode before-
point, keeps earlier checkpoints/operations, and finalizes one grouped snapshot on return
to Object Mode. Results/errors and `bridge.status` expose group state and attempt counts;
the Blender panel shows the pending interval. The [workflow contract](mesh-edit-recovery.md)
defines its scope, legacy compatibility and limits. Successful named restoration clears
pending session state; native undo/redo and project/session invalidation still discard it.

The fixture uses actual dispatcher calls for mode entry, bounded face inspection, selection,
extrusion, mode exit and confirmed snapshot recovery. It independently compares geometry/
material evidence, the protected mesh, selection, active object and mode, then verifies a
partial editor failure and separate recovery of an earlier object transform. Permission
revocation, pause and emergency gates remain effective during the deferred interval.

A separate deterministic test exposed cancellation during checkpoint preparation still
allowing a handler to start. The dispatcher now rechecks cancellation immediately before
the handler. Recovery checks cancellation before editor finalization and retains group
evidence if cancellation follows finalization. Tests verify no scene handler starts in the
pre-edit cancellation case and that pre-canceled recovery creates no finalization snapshot.

Validation: **568 tests** passed with MCP SDK 2.0.0 and 2.2.0; lint/type and README registry
checks passed. **32/32** Windows Blender checks passed on 4.5.1/5.1.2 at
`build/mesh-session-reviewed-matrix-20261017/report.json`. The report records source revision
`2b2aaa344741a4f4ee7574fc50642371ded2d2ea` plus this work, a dirty worktree and Python fingerprint
`ebe383df6c510b45c20e7fd0a21ea7c4e82e8726a00b37937262bdf8fdffad2c`.
No user project was used or saved. This is development evidence, not clean-RC or artistic QA.

The specific structured mode-transition gap is closed for these single-mesh cases. Per-edit
primitive undo within an open editor, other editor stacks, multi-object work, protected manual
interleaving and durable recovery remain open. Next implement ASSET-01 repair primitives
(subdivide/merge/fill/bridge and UV editing) in a prop-repair workflow using this recovery path
and scoped comparisons, while retaining all broader 1.0 capability/acceptance gates.

### 2026-10-17 — Bounded prop-repair primitives

Implemented `mesh.subdivide_selected`, `mesh.merge_by_distance` and `mesh.fill_holes` through
a separate typed BMesh domain module and thin MCP bindings. Explicit single-object Edit Mode,
local/single-user ownership, hidden geometry, shape-key rejection, selection handles, finite
parameters and growth/corner budgets are checked before mutation. Topology changes require
`EDIT_MESH`; no object/datablock deletion, raw Python or file permissions are needed. A no-op
merge does not flush selection or update mesh data. New cap UVs are zero-initialized and unpinned.
See [the actual tool contract](mesh-repair.md); bridging/loop cuts and broader modeling remain open.

A disposable prop workflow welds one selected pair without touching an unselected coincident
vertex, rejects incomplete boundaries, caps a hole, then subdivides its cap into four quads.
It independently checks materials, UVs/pins, weights, dimensions, protected-object evidence,
selection/active object/mode and grouped recovery. Before/after wireframe and solid captures
were reviewed on Windows Blender 4.5.1 and 5.1.2: the cap grid and retained box silhouette are visible.
No user project was used or saved; this is a bounded fixture, not full artistic acceptance.

That workflow exposed temporary capture isolation dropping selection on hidden peers.
Capture now restores selection after visibility, including partial isolation failure, and
surfaces restoration failure. Deterministic tests reproduce Blender's deselection side effect.
An initial pinned-UV fixture using legacy per-corner mesh RNA writes crashed Blender 4.5.1
natively twice (`tbbmalloc.dll`); its logs remain under `build/repair-pin-*`. Constructing the
fixture UV data through BMesh passes both versions. The precise native crash cause is not
established; this does not claim a general legacy-RNA fix.

Validation: **627 tests** passed with both MCP SDK 2.0.0 and 2.2.0; lint, type checks and README
registry checks passed. The final complete matrix passed **34/34** cases, including pinned UVs,
at `build/repair-final-matrix-20261017/report.json`. It records commit
`52aae485a762447752db2aebc40b6b0146eb75d1` plus this work, a dirty worktree, and Python fingerprint
`f9025827059b70ed1e4354706f2d152aa77fc0e7c5e1080b908565e955e05d99`.
This is development evidence, not a clean packaged release candidate.

Next continue ASSET-01 with explicit UV coordinate/layer/pin authoring and loop bridging,
then a fuller prop-repair/unwrap acceptance workflow. Keep all character, sculpt/paint,
procedural, simulation, delivery, UI and production-reliability gates in the 1.0 scope.
1.0 remains unreleased; repository visibility and 0.3.0 assets are unchanged.

### 2026-10-17 — Exact UV authoring and layer lifecycle

Implemented seven structured UV tools: exact face-corner coordinate updates, pivot/scale/
rotation/offset transforms, individual corner or face-scope pins, and Object Mode layer
create/copy/rename/activation/confirmed removal. They use bounded direct data/BMesh operations,
explicit target/layer names, existing Blender permissions and logical recovery. Indexed
edits require face selection references; all coordinates/results are prevalidated. UV write
faults and deadlines attempt measured local rollback. Shared/linked/override meshes and
unsupported context are rejected rather than implicitly copied or mode-switched.

Native tests exposed version-specific storage: 4.5 has per-map UV selection; 5.1 has mesh-global
UV selection and optional, initially absent pin backing attributes. Layer copying now preserves
the applicable selection model, allocates only its new pin storage when required, reads back
copied values, and reports its policy. Name checks include companion-attribute collisions.
The test also covers first/last layer roles, pinned-layer rename/removal/recovery and unchanged
named shader consumers. Unexpected native new-layer names are cleaned up using the actual
created name; deterministic fault coverage checks that no orphan layer remains.

An MCP validation probe found boolean indices converted to integers and extra record fields
dropped before Blender validation. The new UV record schemas now forbid extra keys and coercion;
new numeric/boolean authoring controls are strict too. Tests cover both schema and authoritative
Blender validation. Existing unrelated tool schemas still need a broader coercion audit.

The native workflow checks exact corner math, individual anchors, default pin skipping,
out-of-scope rejection, a real injected BMesh-update failure, other UV maps, protected mesh/
materials, native snapshot recovery and context restoration. Reviewed checker captures on
4.5.1/5.1.2 show deliberately changed mapping only on the edited face. This is localization
evidence, not artistic UV approval, overlap/stretch proof or a complete prop unwrap acceptance.
No user project was used or saved. See [the tool contract and workflow](uv-authoring.md).

Validation: **708 tests** passed with both MCP SDK 2.0.0 and 2.2.0; lint/type/README registry
checks passed. The complete Windows Blender matrix passed **36/36** at
`build/uv-author-strict-final-matrix-20261017/report.json`, recording commit
`505790254461eb44eca94837dc48a0c702d4a403` plus this work, a dirty worktree and Python fingerprint
`b64703843b2b8cd82fc99a5923e603912c2ef14cfc7e03377436f6a378a686b5`.
These are development-source checks, not a clean packaged release-candidate installation.

Next continue ASSET-01 with loop bridging/cuts and a combined repair/unwrap/material workflow,
including UV-atlas visual evidence and quality diagnostics. Keep all remaining full-artist
capability, installation/upgrade, UI, preservation, performance and release gates in scope.
1.0 remains unreleased; repository visibility and published 0.3.0 assets remain unchanged.

### 2026-10-17 — Loop modeling, UV plots and connected prop workflow

Implemented a read-only, paginated `mesh.edge_ring_inspect` plus structured `mesh.loop_cut`
and `mesh.bridge_loops`. Preview returns measured ring edges and expected topology; cuts
require a fresh seed-containing reference and explicitly propagate through unselected quad
faces. Whole-strip/ownership/hidden/resource checks and post-operation counts prevent guessed
or partial-route success. Two-loop bridging supports boundary/wire cycles, equal-loop quads
and native unequal-loop triangulation, with no vertex merge. New faces receive explicit
material and zero/unpinned UV policy; unexpected topology or zero/non-finite face area fails
with possible-mutation/recovery evidence. Nonzero unequal-loop twist is `NOT_IMPLEMENTED`:
native probes showed Blender silently ignores it, while equal-loop twist changes correspondence.
Sliding, non-quad routes, open/multi-loop bridging and explicit unequal correspondence remain open.

Added `uv.capture_layout`: a bounded standard-library PNG plot of measured coordinates and
pins, requiring inspection/capture permissions but no scene/UI/Render Result mutation or
arbitrary path. It preserves UV aspect, supports unit-tile/FIT views, reports clipping and
numeric bounds, checks face/corner/coordinate/pixel-work limits, and never emits partial
budget-failed evidence. It is not an editor screenshot or overlap/stretch/texel-density verdict.

A new connected native fixture repairs a disconnected box-section prop, previews/inserts a
middle ring, authors seams from inspected normals/connectivity, unwraps/packs six non-degenerate
charts, isolates its material and edits the finish. It checks exact topology/positions,
dimensions, weights, original UV corners/interpolation, and protected duplicate/material state.
It then recovers five logical boundaries in reverse and independently matches the original
baseline, including mode/selection/active object. Other native cases verify equal/unequal wire
loops, equal-loop twist, and two even cuts through an open quad strip. Permission revocation,
stale references and unsupported twist are explicit failures. Raw-Python/file/save/delete
super-permissions remain disabled during the recipe.

Reviewed before/after wireframe, material, UV-coordinate, protected and recovery images on
Windows Blender 4.5.1/5.1.2: the intended gap closes, a middle loop appears, six charts pack,
the repaired object gains a blue checker finish, protected appearance is unchanged, and recovery
restores the gap. The twist control can produce an undesirable crossing/hourglass shape; it
tests correspondence, not approved topology. The fixture configures/restores its own framing;
no new scene-navigation capability is claimed. No user project was used or saved. See
[scope and workflow](mesh-loops.md). This is progress toward scenario B, not full acceptance
of reference-constrained texture assets, arbitrary props, diagnostics, or packaged client setup.

Validation: **762 tests** passed with both MCP SDK 2.0.0 and 2.2.0; lint/type/README registry
checks passed. **38/38** native cases passed at
`build/prop-workflow-final-matrix-20261017/report.json`, recording commit
`9ad6ae081adcde24bbb6cc4bb81dbd18961dd693` plus this work, a dirty worktree and Python fingerprint
`76feed78b3fe6b896621398c2ea75ac4bda503fd638741cbba0db24fb116241e`.
The prior reviewed prop run has the same Python fingerprint, and all 20 final prop PNGs match
the reviewed artifacts byte-for-byte. This evidence does not qualify a clean release candidate.

Next implement bounded UV overlap/stretch/texel-density and mesh validity evidence, then
permission-controlled image assets and a richer LOOK-01/ASSET-01 workflow. Keep all other
full-artist capability, safety, UX, performance, install/upgrade and delivery gates in scope.
1.0 remains unreleased; repository visibility and published 0.3.0 assets are unchanged.

### 2026-10-19 — Measured UV quality and local architecture map

Committed/pushed `1e565e1`: `uv.analyze` measures native BMesh triangles for positive-area
overlap, mirrored/folded winding, pixel-direction anisotropy and density in pixels per world
coordinate unit. Resolution is caller-declared (hypothetical 1024 default), not inferred
from images or interpreted as meters. World transforms are refreshed and local geometry is
checked before native tessellation. Scope, triangle, overlap-pair and output-detail limits
are separate; incomplete/invalid evidence never becomes a clean-map verdict. Per-triangle
density checks avoid hiding variation behind face averages. A spatial-grid broadphase keeps
the clean 8,192-triangle fixture within its default pair budget; it is not a scale guarantee.

UV inspection, capture and analysis now recognize live Edit BMesh data through linked
Object Mode aliases, including unflushed coordinates and new layers. Readers retain the
actual owner's BMesh and each alias's own world transform; selection references still need
the named Edit owner and shared-data mutations remain unsupported. Broader inspector and
mutator ownership/state audits are not thereby complete.

The new native recipe diagnoses known stacking, stretch and mirroring, refines four charts,
independently measures density/anisotropy, compares protected data and recovers snapshots.
Concave/folded tessellation, non-finite input, revoked inspection permission, paused/stopped
inspection, honest budget failure and mixed-mode linked data are covered. The prop recipe
also checks UV quality. Reviewed structural evidence and before/after/recovered layouts are
consistent; all 28 final UV/prop captures match the reviewed artifacts byte-for-byte.
No user project was used or saved; coordinate plots are not texture/look-development approval.

Validation: **812 tests** passed on both MCP SDK 2.0.0 and 2.2.0, with lint, typing and README
inventory checks passing. Native Windows Blender 4.5.1/5.1.2 passed **40/40** at
`build/uv-quality-graphify-matrix-20261019/report.json`. It records `8a15205` plus the then-dirty
changes, fingerprint `bb0461a34ad8a20e9732525f258814e4ea6277c8aef5b2bff0f81a1458c9b4d1`;
the frozen source hashes were independently matched against the committed `1e565e1` files.
These are development-source results, not packaged installation or full scenario acceptance.

Used the requested Graphify skill and an authorized documentation sub-agent to map 194 files
into 2,714 nodes / 8,645 edges / 97 named communities. The map highlights shared validation,
error/context and documented authoring/evidence/recovery dependencies. It also reports 883
raw dangling references, 8 self-loops and 766 undirected edge collapses, so it is not a
complete call/dependency proof. Semantic token usage is unavailable, not claimed as zero.
Generated artifacts stay local/ignored; [mapping workflow and limitations](architecture-map.md)
explain refresh, provenance, cost estimates and the separate cloud-connector requirement.

Next implement bounded mesh-validity/normal/crossing evidence and permission-controlled
image assets, then prove a more representative textured-prop revision. Preserve the full
character/paint/simulation/interactive/delivery and install/upgrade/release scope. Nothing in
this increment accepts 1.0, changes repository visibility or replaces published 0.3.0 assets.

### 2026-10-19 — Mesh quality and verified winding repair

Implemented `mesh.analyze`: a bounded read-only whole-base-mesh inspection requiring
`INSPECT_SCENE`, not edit/Python/delete/file/save permissions. It measures topology categories,
adjacent manifold face-winding consistency and native-triangle contact candidates. Crossings,
boundary contacts and near-coplanar overlaps are distinguished; near-parallel ambiguity,
degenerate/empty surfaces, insufficient coordinate precision, missing tessellation and
exhausted budgets remain incomplete. Index examples and computation limits are independent.
World-space tolerance is explicit, not meters; refreshed transforms and live shared Edit data
are used. Shared live-data detection moved to a common mesh helper, preserving UV behavior.

The triangle kernel uses pair-local double-precision tests and a bounded adaptive grid with
a large-AABB fallback. A final scale review replaced a fixed world-area clipping floor with
normalized pair-relative tolerance, verified by small/large unit tests and a native `1e-8`
stacked-triangle case. The 8,192-triangle grid completes within the default 250,000 pair
budget (98,056 tests), measured about 1.70–1.85 seconds locally, not a scale guarantee.
Open boundaries/wire geometry can be intentional; passing checks is not an artistic,
outward/custom-normal, evaluated-geometry, containment, cross-object or printability verdict.

The native recipe diagnoses a reversed cube face, applies typed normal recalculation and
independently checks exact positions, topology membership, per-vertex UVs/pins, material
bindings/indices and transforms. It verifies protected-data preservation and snapshot recovery
of the original winding/context. Further cases cover crossings, stacked faces, non-manifold
incidence, concave tessellation, unsafe positions, near-zero edges, empty/degenerate meshes,
precision limits, same-timer scale, shared live aliases, denial and pause/stop behavior.
The connected prop recipe now checks winding and contact candidates after bridge/cut edits.
Reviewed close-framed wire captures show unchanged shape/protected state and restored
geometry; winding itself is established numerically. All 32 final mesh/prop images match
the reviewed artifacts byte-for-byte. No user project was used or saved.

Validation: **847 tests** passed with both MCP SDK 2.0.0 and 2.2.0; lint, typing and README
inventory checks passed (153 registered MCP tools). The complete native Windows Blender
4.5.1/5.1.2 matrix passed **42/42** at
`build/mesh-quality-scale-final-matrix-20261019/report.json`, recording baseline `665cb54`
plus this then-dirty work and Python fingerprint
`c3d4697396f441e07b576ee8ea8006db52386fde93d30abdaf03eee978e69bbe`.
All recorded Python source hashes were matched against the frozen worktree. An additional
local diagnostic checked 1,000 seeded random triangle pairs against Blender's independent
native segment/triangle intersections on both versions: all agreed, with 287 contacts.
That probe is supplemental evidence, not universal collision proof or a release gate waiver.

Graphify's partial navigation query located the existing normal/repair entry points, which
were then inspected directly. The local map is flagged for refresh after this new source;
no complete dependency proof or refreshed graph is claimed. See [the tool contract](mesh-analysis.md).
Next advance LOOK-01 with permission-controlled image assets and a richer textured-prop
revision. Retain localized/evaluated/cross-object diagnostics, outward/custom normals,
character, painting, simulation, UX, delivery and install/upgrade/RC gates. This is another
development increment, not full scenario or 1.0 acceptance. Published 0.3.0 and repository
visibility remain unchanged.

### 2026-10-19 — Approved image assets and measured texture revision

LOOK-01 now implements `image.inspect`, `image.load`, `image.remove` and `nodes.set_image`.
Blender's user-controlled Approved Texture Folder and live external-file permission gate
supported PNG/JPEG reads. Loading creates distinct named/color-role datablocks, checks bounded
source bytes/headers before and after native decoding and verifies loaded metadata. Binding uses
the existing material ownership guard, preserves graph links and verifies scoped restoration on
failure. Unused-image deletion is explicit, separately permissioned and never deletes a file.
Object Mode checkpoint/recovery behavior and strict schemas are documented in [image assets](image-assets.md).

The connected native fixture isolates a material on one of two objects sharing mesh data, binds
color and Non-Color roughness images, revises orange to blue and independently verifies protected
data, exact staged recovery, original image IDs/pixels, source file hashes and context. All 16
final texture captures match the reviewed before/revision/recovered/protected artifacts byte for
byte. Blender config/scripts/datafiles now join temporary recovery paths in per-case isolation;
the real add-on preference tests neither use nor save the user's preferences or project.

Validation: **913 tests** passed on both MCP SDK 2.0.0 and 2.2.0, plus lint, typing and the generated
README inventory (**157 tools**). Full native Windows Blender 4.5.1/5.1.2 passed **44/44** at
`build/image-assets-final-matrix-20261019/report.json`, recording baseline `286dcc7` plus this
then-dirty work and Python fingerprint
`3a1aba028360b1a2b651bdef7785f7e6410dd0ec459738c274b71f1158d02ee2`.
Every recorded Python source hash was independently matched to the frozen worktree. The first
full unit run exposed an old test's assumption that one module owned all material/node handlers;
it now registers the image domain and checks metadata semantically rather than by tuple position.

Graphify MCP is verified in `dino-s-workspace`; it lists the bridge as queryable at `286dcc7`.
A broad safety query returned partially useful/noisy recovery seeds. An exact material-scope
outline and linked-test query localized `editable_material_scope` and `test_material_scope.py`;
current source inspection verified reuse of shared-consent/100-user/library guards. That remote
index does not include these uncommitted image tools. The local primary-checkout map is refreshed
separately with honest extraction/health limits; query results are not a preservation certificate.

This is still a bounded fixture, not full scenario B or 1.0 acceptance. Image reload/relocation,
packing/saving, broader formats, nested shader/compositor images and responsive native decoding
remain open, alongside representative prop/character/paint/simulation/UX/delivery/install gates.
Next: extend typed image lifecycle and nested shader support, then integrate repair/UV/texture
revisions on a representative prop with reference constraints. Keep the full artist target,
published 0.3.0 assets and repository visibility unchanged.

### 2026-10-19 — Nested shader authoring, instance isolation and logical revision batches

LOOK-01 adds six `shader_group.*` lifecycle tools and optional explicit `group_path` to existing
`nodes.*`. Transitive ownership traces parent shader groups to material-slot users and direct
World/Light/other owners, bounded to 32 groups / 100 owner IDs. Shared scope requires acknowledgement;
incomplete evidence or read-only owners block mutation. Object slots for all reached materials are
scanned once. Numeric per-material object counts still enforce consent when object names coincide.
Nested mutations require Object Mode; root behavior remains otherwise compatible.

Group creation, six typed interface socket types, unlinked instance binding/clearing, one-instance
copies and confirmed unused removal compose with normal node authoring. Copies preserve instance
defaults and parent links but do not deep-copy nested groups/images. Outgoing binding/copy dependencies
are bounded, reject cycles and Script/IES nodes, and route loaded FILE images through the existing
approved-source policy. No raw Python, file write, forced unlink or implicit buffer reload is needed.
See [the full contract and remaining gaps](shader-groups.md).

Graphify MCP localized the existing material graph/socket helpers and the structured batch path;
current files were inspected before reuse. Its index advanced to `cce4bf0` during this work, not the
new uncommitted group code. The local map remains explicitly stale after these source/doc additions.
No refreshed graph or complete static dependency proof is claimed. In particular, retrieval/test
links are navigation aids, not runtime coverage or permission guarantees.

The first long standalone-call native recipe exposed finite undo history. Rather than expand user
preferences or weaken recovery assertions, the final recipe uses the existing 12-step logical batch
for a coherent new finish. Every child gate still runs; a deliberately invalid interface default
also proves audited partial work and measured native batch recovery. Both installed versions pass
the final default-32 workflow. Separate disposable probes recovered 16/17 standalone operations at
32 native undo steps and 17/17 at 128. Native-capacity/availability reporting is now next in REC-01;
batching reduces history consumption but is not a general eviction fix or durable backup.

The native fixture independently compares protected group nodes/interface/links and root scene
evidence across orange, blue, green-texture and recovered variants. It verifies original instance
values/links, material/group IDs, selection and source bytes after recovery. Root `scene.compare`
alone does not cover child contents. All 16 final shader captures match reviewed artifacts byte for
byte; no user project or preferences are saved. Simple fixture cubes are not production-art approval.

Validation: **960 tests** passed on both MCP SDK 2.0.0 and 2.2.0, plus lint, typing and README inventory
checks (**163 tools**). The full Windows Blender 4.5.1/5.1.2 matrix passed **46/46** at
`build/shader-groups-final-matrix-20261019/report.json`, baseline `cce4bf0` plus then-dirty work,
Python fingerprint `3ecdacfca26552a2f854e11634b7c61c2aff877b0f2a7f69c501351883e5fbd2`.
All recorded Python source hashes match the frozen worktree. Supplemental capacity probes and their
isolated logs remain under `build/undo-capacity-probes/` and `build/undo-capacity-probes45/`.

Next: REC-01 native-capacity reporting/pruning and longer/manual-interleaved recovery, then broader
shader properties/color ramps, image lifecycle and representative reference-constrained prop work.
Interface editing/conversion, deep asset lifecycle, nested snapshots, character, painting, simulation,
UX, delivery and install/upgrade/RC gates remain open. This increment does not accept scenario B or
1.0, publish a release, replace published 0.3.0 assets or change repository visibility.

### 2026-10-20: observed native-history availability and guard budgets

REC-01 now has a bounded branch-aware ledger of bridge-owned snapshot pushes. It reports
native step/memory settings, explicitly **unverified** targets, observed expiry and guard-budget
refusal through `checkpoint.list`, `bridge.status` and the Blender panel. Known-expired operation
targets are pruned; named labels retain their existing shape and separate expiry by ID. The
ledger never enumerates the private undo stack or silently increases preferences. Manual/operator
snapshots and memory eviction remain unknown until measured navigation. See [the contract](native-recovery.md).

Guard-budget refusal occurs before navigation, not after evicting the target to make a guard.
Successful recovery rewinds known branch positions so discarded future pushes do not age older
targets. Expired labels do not resurrect after a preference increase. Zero undo steps cannot
claim native snapshots. A finalized Edit Mode group retains possible-mutation/finalization
evidence even when its before-point expires and recovery refuses an empty queue.

The new native fixture uses real add-on preferences and structured tools in isolated factory
profiles. At 32 steps it recovers 16/17 separate operations, prunes the expired oldest boundary
and refuses another restore without undo; at an explicitly isolated 128-step test setting it
recovers all 17. It also checks new branches, named guard-budget refusal, unknown manual eviction
and return to unsnapshotted work, delayed group finalization, live permission/remote stop gates,
protected data, selection and matched viewport captures. Fixture-only mode-selection context
is explicitly restored. It does not assert production art, complete history access or durable recovery.

Graphify was used directly on the primary agent to locate checkpoint recovery, runtime/core
entry points and linked tests. The MCP index still described `cce4bf0`; relevant original files
were checked against the checkout before editing. A whole-file test query returned noisy,
truncated name matches, so exact source/tests and actual native fixtures—not that query—proved
behavior. New availability code is beyond the cached local/cloud map and needs a later refresh.

Validation: **974 tests** passed on each of MCP SDK 2.0.0 and 2.2.0; lint, typing and the
README inventory (**163 tools**) also passed. Final Windows Blender 4.5.1 LTS/5.1.2 results:
**48/48**, `build/undo-capacity-final-matrix-20261019-3/report.json`, baseline `65be9d9`
plus the then-dirty implementation. All 123 recorded Python source hashes match the frozen
worktree; fingerprint `cb185489c7914a1ceb33d42098e7e1d82c3c6362a0589bd53137fb347f77b77f`.
Four recovery captures and 16 existing shader-workflow captures match previously reviewed
artifacts byte for byte. No user project or preferences were saved. Earlier fixture failures
remain in ignored build logs; the final checks do not substitute for the open release gates.

Next: broader shader properties/color ramps and image lifecycle, followed by a representative
reference-constrained textured prop with preservation/revision evidence. Memory-pressure,
mixed-editor/domain and production-scale recovery, protected transitive dependencies, paint,
character/animation, simulations/jobs, interactive UX, delivery and installation/upgrade/RC gates
remain mandatory. This increment does not accept all REC-01, scenario B or 1.0.

### 2026-10-20 — Reviewed shader properties, complete palettes and measured revision recovery

LOOK-01 adds `nodes.inspect_properties`, `nodes.set_properties` and `nodes.set_color_ramp`,
using explicit root/nested paths and existing transitive ownership gates. A passive shared
state reader keeps inspection and root `shader_inputs` evidence consistent. The reviewed
13-type scalar/enum map is not arbitrary RNA access; Image Texture properties stay behind
their file-policy-aware tool. Exact limits and exclusions are in [shader settings](shader-settings.md).

Complete replacement accepts 1–32 ordered scene-linear RGBA stops, ties and HDR with native
float32 normalization. Mutations require Object Mode and reject direct material/target-tree
animation. All links and target socket structure/defaults are compared before/after. Local
restoration is attempted and measured after a partial failure; unresolved state retains
possible-mutation evidence and a finalized native recovery boundary when available.

Native evidence changed the visual test: a stored CONSTANT setting with HSV produced a smooth
palette, not the intended hard step. Blender's evaluator uses linear interpolation in HSV/HSL.
Inspection now distinguishes stored/effective interpolation and active hue wrapping; a native
red/blue midpoint verifies magenta even with stored CONSTANT. The final hard-step variant uses
RGB CONSTANT and was visually checked on both installed versions. This is refinement from
evidence, not a passing property-assignment claim.

The factory fixture independently reinspects all 13 types, one/32 stops, tied positions/HDR,
root same-count evidence, nested isolation, protected group content, permission/pause/stop and
direct-animation gates. Injected transient and persistent partial ramp failures prove measured
local restoration versus unresolved mutation, then confirmed native recovery. Coherent revision
batches and staged restore pass at unchanged default 32-step history, preserving active object,
selection and mode. No user project or preferences are saved. Only the connected Noise/ramp
palette receives visual look review; unconnected probe types prove properties, not rendered QA.

Graphify was queried on the primary agent in `dino-s-workspace`. Its verified cloud index
advanced to `7e18031`, while the local map remains older. Broad sharing/truncation retrieval
localized existing scope tests but did not index the new shader implementation or prove
preservation. Current source and actual native fixtures supplied that evidence; the map is
navigation, not runtime acceptance.

Validation: **1,026 tests** passed on each of MCP SDK 2.0.0 and 2.2.0; lint, mypy (34 files)
and generated README inventory (**166 tools**) passed. Windows Blender 4.5.1 LTS/5.1.2 passed
**50/50** at `build/nonfocus-full-native-20261020/report.json`: 28 background cases and
22 UI cases on private, non-visible desktops. The report records baseline `7e18031` plus
then-dirty source, including the runner subsequently pushed as `f6a98a3`. All 128 recorded
Python hashes match this implementation; fingerprint
`cdf2d952c6175d2f715a794094b43c98875dba2c7c678e0413e942d6a22c9c2c`.
All 16 shader captures match the focused artifacts; representative warm/cool/hard-step and
protected/recovered views are reviewed separately. Test UI no longer interrupts the user's
desktop; isolation failures have no visible fallback. See [native testing](native-testing.md).

Next: image reload/relocation and dependency lifecycle, then integrate on a representative
reference-constrained textured prop. Broader shader/compositor contracts, nested evidence,
painting, character/animation, simulations/jobs, interactive UX, delivery and install/upgrade/
RC acceptance remain open. No published assets, version or visibility are changed; LOOK-01,
scenario B and the full 1.0 goal remain unaccepted.

### 2026-10-20 — Versioned texture revisions and native buffer-recovery evidence

LOOK-01 adds `nodes.refresh_image`, a coherent new-image/load-and-bind operation at explicit
root/nested image nodes. It rereads an approved FILE source or accepts a new approved path,
including missing/unloaded-source repair. The original image/buffer remains untouched, with
explicit new identity, inherited color/alpha role and measured sampler/socket/link preservation.
The [contract](image-revisions.md) distinguishes this workflow from in-place reload, pixel
editing, packing or durable backup; those remain full 1.0 work.

Native probes changed the implementation decision: after `Image.reload()`, global undo retained
the new pixels on both installed versions. Independent image versions recovered the original
binding and cached pixels. The committed native fixture records that diagnostic without
requiring future Blender versions to retain the limitation. This is an evidence-driven
versioned revision, not a claim that identity-preserving reload is implemented or unnecessary.

Alpha interpretation is selected during authorized loading/verification, not after a buffer
was declared ready: native alpha changes invalidate the cache. New image metadata is guarded
too. The first full matrix exposed `Image.is_float` lazily loading an unloaded outside source;
the corrected inspector returns null for unavailable buffer flags and never calls that getter
unless the exact simple image is already loaded. Unit and native regressions cover repeated
unloaded inspection. Earlier failing runs remain in local logs, not reported as passes.

The versioned native workflow checks shared-group rejection, file/permission/pause/stop/mode/
direct-animation gates, all four alpha roles, orange/blue/green variants, unloaded missing
sources and dirty generated/packed FILE originals. Complete small fixture pixel/packed-byte
hashes, protected group content and native restored state are measured independently. Scoped
failure cleanup never force-unlinks unexpected users; unresolved leftovers remain explicit and
are checked after confirmed global recovery. Factory profiles preserve user projects/preferences
and run off the input desktop. No generic Python command or source-file write is added.

Graphify was queried in the primary workflow in `dino-s-workspace`. Its approved-load/source-
change tests directed reuse of existing file checks and cleanup contracts; current files were
inspected before extracting the shared image-node target resolver and semantic graph guard.
Cloud indexing advanced to `7810b8b` during this increment, not the new image-revision code.
An empty recall is not invented prior guidance; local/cloud graph freshness remains explicit.

Validation: **193 focused tests**, then **1,058 tests** on each of MCP SDK 2.0.0 and 2.2.0,
lint, mypy (34 files), and README inventory (**167 tools**) passed. The final Windows Blender
4.5.1 LTS/5.1.2 matrix passed **52/52**, including the guarded unloaded-source inspection and
new revision fixture, at `build/image-revisions-final-matrix-20261020-3/report.json`.
It records baseline `7810b8b` plus this then-dirty implementation, 130 independently matched
Python source hashes and fingerprint
`5e8470c7b25916189586c5f63f6a7fb855a9ba9bb099fa39dcccdbba5de5c4cb`.
There are 28 background and 24 private-desktop UI cases. All 14 new revision captures match
the focused artifacts; six orange/blue/green views were reviewed and all protected/recovered
views match their original baseline bytes. Existing shader/image/group captures are also
compared with previously reviewed evidence. Earlier failures are retained under the same
local build prefix; neither green markers nor this development matrix accept the full artist
or clean-RC gates. No user project/preferences, published release assets or visibility changed.

Next executable deliverable is a representative reference-constrained prop, not another
unbounded sequence of unrelated tools:

1. Commit an original field-scanner brief/reference with world-unit dimensions, component and
   silhouette constraints, a protected comparison object and a numeric/visual review rubric.
2. Model body, inset panel, controls and handle through structured tools with coherent logical
   stages; retain scoped topology/material evidence and a deliberate partial-failure case.
3. Author seams/UVs and measure overlap/stretch/density; build a reusable nested material and
   approved texture/data roles, then use versioned image revisions without changing protected data.
4. Review matched orthographic/isometric/material/UV views, refine at least one evidenced
   design mismatch, and measure staged recovery. Do not call a fixture marker artistic acceptance.
5. Record which scenario-B requirements are met and keep painting/baking, deep dependency/
   durable-pixel lifecycle, production scale and remaining modeling gaps explicit. Save/export
   only when agreed; delivery/install/upgrade/RC acceptance is a separate mandatory stage.

SAFE-02, JOB-01, remaining shader/compositor and nested evidence work, painting, character/
animation, simulations, interactive UX, delivery and the full release audit remain open.
Published 0.3.0 assets, version and repository visibility are unchanged.

### 2026-10-20 — Reference-constrained scanner integrates modeling, UVs and nested textures

ASSET-01 / LOOK-01 now have an original owned numeric brief and three-view SVG reference,
plus a reproducible [field-scanner workflow](field-scanner-workflow.md). A disposable factory
scene builds twelve final components through structured bridge tools: wire-ring bridge/caps,
inset/extrusion, real Boolean grille pockets, smooth-sided controls, an open carry handle,
seams/unwrapping/packing, an explicit display atlas and nested image materials. Colors use
sRGB; roughness uses Non-Color. Explicit UV Map settings extend the reviewed shader subset
to fourteen types. Versioned green/blue display revisions retain original cached pixels.
The fixture uses direct add-on dispatch, not an end-to-end packaged MCP installation.

Two bounded additions support this workflow: creation-time `face_smooth`, and selected
`mesh.set_face_attributes` for polygon shading/existing material-slot indices. Fresh references,
active single-object local/single-user Edit Mode scope, typed bounds, dynamic Blender-side
material consent, cancellation and measured local restoration are enforced. No arbitrary RNA
or custom-normal access is introduced. The new tool has public schema/registry documentation.

Evidence changed the implementation. An extruded recessed fascia initially retained its base
cap and created eight non-manifold edges. Supplying native BMesh with the full region edge set
fixed attachment cleanup while preserving standalone-region bases. Native regressions measure
attached-cube and standalone one-/two-quad counts, manifold edges, signed volume and actual undo.
Visual review then exposed orange grille walls in elevated views: these narrow deep pockets
hide their floors. Actual inner walls now get the dark finish, and slot indices come from
current results rather than assuming index 1 (the two Blender versions return different layouts).

Measured base world bounds are 144 × 51 × 260 mm within 50 micrometres; evaluated handle rays
verify an open 86 × 24 mm clearance. Complete shell/display UV analysis reports no positive-area
overlap, degenerate/mirrored/folded mappings and near-unity pixel-direction stretch. Shell
density is approximately 1,616 pixels/metre at 1024². The display's 500 × 350 atlas deliberately
prioritizes its front; the approximately 3.04 density ratio is explicit, not uniform-atlas acceptance.
Auxiliary solid-color components are not a fully mapped production asset.

Native faults test material denial before face assignment, a post-update face-attribute failure
with independently checked restoration, and a real non-atomic shader batch failure after one
valid edit. Confirmed native recovery compares geometry/UVs, nested graphs and complete fixture
pixel buffers separately; root snapshots alone do not prove nested shader coverage. All fourteen
logical build/context operations then recover separately at unchanged default 32-step history,
restoring original datablock names and protected scope. This is a small isolated-case result,
not memory-pressure, interleaving, durable recovery or unlimited-history acceptance.

Graphify was used on the primary agent in `dino-s-workspace`: file outlines localized modeling
primitives, and a narrowed recovery query located current capacity/finalization contracts and
their tests. An earlier broad query was noisy; the narrowed response was capped/skeletonized,
not an exact complete call chain. Cloud indexing reached `f029d27` (2026-10-20T12:42:59Z), while
the local map remains at `cce4bf0`; neither contains these new edits. Current source and native
evidence remained authoritative. Useful retrieval feedback and the stale marker are local.

Validation: **88 focused tests**, then **1,098 tests on each** of MCP SDK 2.0.0 / 2.2.0; lint,
mypy (34 files), generated README inventory (**168 tools**) and whitespace checks passed.
Windows Blender 4.5.1 LTS / 5.1.2 passed the complete **54/54** native matrix at
`build/field-scanner-final-matrix-20261020-1/report.json`: 28 background cases, 26 private-desktop
UI cases, baseline `f029d27` plus this then-dirty implementation. All 133 Python hashes and the
actual source file set match; fingerprint
`d7c0fb4c78d0c1270a1cf40b71eab7b8a17edf5c6ddf8f1a7c1077e985790227`.
Brief/reference and generated texture hashes are also independently checked.

Twenty scanner captures were retained and front/isometric/wire, green/blue and UV views reviewed.
Fourteen match the focused run byte-for-byte. Six Blender 5.1 captures differ slightly between
runs: 133 changed shell-layout pixels, at most 1,018 material-preview pixels with maximum channel
difference 5/255, and five wire pixels with maximum difference 2/255. Those current artifacts
were re-reviewed, not labeled identical; the underlying rerun variation is not yet isolated.
Protected and within-run recovered views match baseline bytes exactly on both versions.
All 62 earlier image/shader/group/revision captures match previously reviewed artifacts.
Earlier failed modeling/injection/recipe runs remain local evidence, not reported as passes.

Next complete the missing prop paint/bake and approved dependency/durable-pixel workflows,
starting with explicit ownership, file and long-operation recovery contracts before mutating
production data. Extend representative repair/preservation and evaluated/full-asset UV tests;
keep SAFE-02/JOB-01, character/animation, simulations, UX, delivery and packaged upgrade/RC
acceptance mandatory. Scenario B, LOOK-01 and the full 1.0 artist goal remain unaccepted.
No user project/preferences, published release assets, version or repository visibility changed.

### 2026-10-20 — Copy-on-write texture brushes, pixel evidence and deletion-consent recovery

PAINT-01 / LOOK-01 now include three structured tools: `image.create` for new generated float
color/data canvases, `image.paint_version` for bounded UV-image strokes in a new named version,
and `image.inspect_pixels` for complete stored-buffer digests/ranges plus selected samples.
The [contract](texture-painting.md) specifies 1,048,576 pixels, 32 strokes / 128 points each,
256 segments and two million candidate pixel tests. COLOR supports source-over and alpha erase;
DATA uses weighted RGBA mixing. Smoothstep coverage uses the maximum across segments within
each stroke, avoiding repeated-point/join overdraw. Explicit node binding remains separate.

Native evidence informed the implementation: `Image.pixels` returned encoded byte-sRGB values,
not automatically linearized values, on both versions. Painting converts supported sRGB
sources to a new Linear Rec.709 float image; alpha is not gamma-transformed. Independent
standard-sRGB/source-over values and untouched samples are checked, not only calls back into
the conversion being tested. Generated image type is native `UV_TEST`, including blank canvases;
the first native attempt exposed and corrected an overly narrow IMAGE-only check. Unknown
OCIO/float-sRGB, animated and non-STRAIGHT-alpha sources are rejected explicitly. No in-place
painting, source-file write or durable pixel recovery is claimed.

The reference scanner's blue-display revision is now one batch: approved image refresh, a
painted cyan readiness underline/green indicator and exact nested binding. Pixel inspection
follows the batch. Old calibration
and scan buffers remain unchanged. Structural/UV evidence and all fourteen logical build/context
restores still pass at unchanged 32-step history. This extends a real connected workflow rather
than treating new tool names as artistic acceptance.

Consent review found that owned-image failure cleanup must not bypass deletion permission.
A shared helper now requires live `DELETE_OBJECTS` immediately before removing a newly allocated
zero-user, non-fake-user image; image loading, source revisions and painting all use it. Normal
successful creation/loading/painting still need no deletion grant. Denied cleanup retains the
image with `cleanup_permission_denied=true`, `rollback_verified=false`, `possible_mutation=true`
and tracked recovery. Explicit unused removal also rechecks live grants just before execution.
Unit/native faults distinguish granted cleanup, denied cleanup, unexpected consumers and
post-write cancellation; confirmed global recovery removes the retained allocation and restores
independently compared source pixels, protected consumers and material bindings. Other domain
cleanup/ownership/recovery audits remain SAFE-02 work, not implicitly accepted by this helper.

Graphify ran on the primary agent in `dino-s-workspace`. The verified cloud index remains
`f029d27` (2026-10-20T12:42:59Z); the local map remains `cce4bf0`. A narrow image query and exact
file outline localized `binding_source`, bounded metadata inspection and cancel-after-decode
tests. Current source exposed the cleanup-consent gap and supplied the implementation; the
new brush code and scanner changes were not claimed indexed. Query feedback and the stale marker
are kept locally; no rebuild, watcher or new external service was installed.

Validation: **185 focused tests**, then **1,166 tests on each** of MCP SDK 2.0.0 / 2.2.0; lint,
mypy (35 files), generated README inventory (**171 tools**) and whitespace checks passed.
The final Windows Blender 4.5.1 LTS / 5.1.2 matrix passed **56/56** at
`build/texture-paint-final-matrix-20261020-2/report.json`, including the stricter cleanup policy:
28 background and 28 private, non-input-desktop UI cases. Baseline `b411d75` plus this then-dirty
implementation, 137 independently matched Python files and fingerprint
`36885c788279e6cf3c9911010a90af55040954a12a9a193d094cc96b2fa67731`.
The actual source-file set and scanner brief/reference/texture hashes also match. Earlier runs,
including the first registration-test omission and pre-consent matrix, remain local; they are
not substituted for this final evidence.

A 1024² workload changed 192,124 pixels across 794,624 candidate tests: creation measured about
0.13–0.14 s, painting 1.73 s and full inspection 0.59–0.86 s here. These synchronous main-thread
measurements are not a responsive-job or universal latency promise; memory pressure, larger
images and production-scale throughput remain unaccepted. Native buffer transfers/update are
not interruptible, while CPU brush phases poll cancellation and live permissions.

Thirty-six scanner/paint captures were retained; front/isometric, brush/erase, conversion-only
and UV views were reviewed. Twenty-five match the focused artifacts byte-for-byte. Eleven scanner
captures show rerun variation: up to 4,531 changed UV-layout pixels and 17,743 material-preview
pixels with maximum channel difference 6/255; current views were re-reviewed, not labeled
identical. The underlying rerun variation remains unisolated. Conversion-only previews differ
from their byte-source baseline in 31 / 30 pixels, maximum channel difference 5 / 4, with mean
channel differences below 0.00006; this is not a pixel-identical OCIO guarantee. Protected and
within-run recovered views match their own baselines exactly on both versions. All 62 earlier
image/shader/group/revision captures match previously reviewed artifacts.

Next prioritize JOB-01: read the protocol/lifecycle contracts, design source-frozen owned painting
jobs with bounded cooperative work, correlated progress, queued/running cancellation, disconnect
policy and a single verified commit/recovery boundary. Prove that canceled callers cannot leave
untracked allocations before scaling images or adding native baking. Then add surface/viewport
stroke projection, masks/stencils and the remaining brush/color/alpha workflows on this asset;
continue sculpt/vertex/weight painting, full atlas/bake/dependency/durable-delivery acceptance.
SAFE-02, character/animation, simulation, UX, installation/upgrade and clean-RC gates stay mandatory.
No complete PAINT-01, scenario B, full artist or 1.0 release acceptance is claimed. User projects,
preferences, published 0.3.0 assets, package versions and repository visibility are unchanged.

## 2026-10-20 — cooperative paint jobs, transport ownership and guarded publication

Implemented `image.paint_job_start` and core `jobs.inspect/list/cancel`, with typed stroke/
deadline/ID schemas, one active source-frozen job, revisioned phase-local progress and 32
bounded terminal summaries. Network threads set only lifetime flags; the main-thread timer
services normal requests before bounded CPU slices. No computation advances before the start
success is flushed to its owning socket. Independent job deadlines, disconnect/rejected
handoff, pause, cancellation, emergency stop, file load, undo/redo and shutdown have explicit
behavior. Source/metadata/animation/pixel/file/context/grant/name checks precede publication.
An independent finalized native undo boundary is required, at commit rather than acceptance.
The sidebar now shows progress, cancellation, retained-image warnings and accepted/terminal
history, with a Blender-only 1–8 ms CPU-budget setting. Polling does not evict operation records;
minimal control/status responses do not expose detailed results without inspection consent.

Cancellation before commit allocates no image. A post-write stop or pause can retain a new
image when deletion is not consented: truthful possible-mutation/finalized-boundary evidence
and confirmed recovery are verified. Pause during publication reports `AGENT_PAUSED`, not a
false success or suspended half-commit. Reentrant stop does not release an executing generator's
buffers. Native transfers/allocation/validation/checkpoint calls remain bounded but not preemptible.
No scripts, automatic binding, file writes or durable/general bake queue were added.

The socket reader now retains bounded partial bytes across idle timeouts, avoiding the poisoned
`socket.makefile().readline()` state on a live job connection. Framing, IDs and one terminal RPC
response are unchanged; progress is polled, not emitted as NDJSON events. MCP registration now
retains `Annotated` metadata: real SDK tests prove strict types/ranges and nested brush limits
are advertised and rejected before forwarding, rather than stripped by `get_type_hints`.

Validation: **82 focused tests**, then **1,218 on each** of MCP SDK 2.0.0 / 2.2.0; lint, mypy
(35 files), generated README (**175 tools**), compilation, whitespace and a development add-on
ZIP's layout/CRC/new-module checks passed. The final Windows Blender 4.5.1 LTS / 5.1.2 matrix
passed **58/58**, 28 background and 30 private-desktop UI cases, at
`build/paint-jobs-final-matrix-20261020-2/report.json`. Baseline `2a62da6` plus this then-dirty
implementation; all **141** Python source paths/bytes independently match fingerprint
`12e2495a874f688d2749b08445b367d52d197faf87d643a1fbf1e675689d9160`.
Earlier runs, including the initial pause-state observation race, missing annotation metadata
and the deliberately failing post-publication pause regression, are retained, not substituted
for the final source-matched evidence.

The new native fixture uses real loopback requests and the runtime timer. It independently
checks full pixel hashes/numeric samples, protected state and recovery that preserves a transform
completed while painting was pending. Fourteen new captures were retained; painted views were
reviewed and each version's pre-binding/recovered and protected before/after/recovered pairs
are byte-identical. The pre-acceptance view has different framing because the interleaved
transform is intentionally retained; it is not mislabeled as the matched recovery baseline.
Of 156 prior PNG-path pairs, 142 are byte-identical, two render outputs are pixel-identical
despite different PNG bytes, and 12 scanner views vary. Scanner UV changes reach 4,538 pixels;
material-preview changes reach 18,198 pixels with maximum channel difference 6/255. Current
front/isometric/wire/UV variants were re-reviewed. This previously observed rerun variation
remains unisolated, not production UV/look-quality acceptance.

For the 512² job fixture at a 1 ms CPU setting, 950 / 875 status polls measured medians about
15.7 / 8.5 ms and maxima about 360 / 375 ms here. These include bounded uninterruptible work,
not a real-time guarantee or production throughput/memory-pressure acceptance. Graphify on
the primary agent located the existing disconnect, cancellation fixture and executor timer;
cloud navigation was at `2a62da6`, local map `cce4bf0`. Current source was authoritative,
feedback was saved and the stale marker updated; no graph rebuild or subagents were used.

Next: extend JOB-01 under memory pressure, larger/tiled images, canceled clients and mixed-editor
interleaving; add surface/viewport stroke projection and masks, then exercise them in the
reference workflow. Native simulation/bake isolation, sculpt/vertex/weight workflows, remaining
SAFE-02/character/animation/UV/asset lifecycle, persistent UX, delivery, install/upgrade and clean
RC gates remain mandatory. This closes neither JOB-01 nor PAINT-01 nor the requested full-artist
1.0 target. No user project/preference was saved, published 0.3.0 asset changed, version bumped,
release published or repository visibility changed.

## 2026-10-21 — tile-bounded coverage, 4K paint jobs and explicit inspection scope

Replaced whole-stroke coverage dictionaries with 64×64 float64 coverage tiles (at most 32 KiB
raw coverage), and whole-image normalized baselines with comparison over union tiles. Conservative
segment-row bands prune a long diagonal's enclosing rectangle without approximating its pixel-center
capsule. Stroke accumulation, join maxima, color/data/alpha math, exact float32 results and global
row-major changed-pixel examples match the pre-tiled reference in 45 deterministic adversarial cases.
Preparation checks cancellation; little-endian digests hash the contiguous buffer without a second
whole bytes image. Scoped estimates are exposed in job workload/results and the panel, not asserted
as process/GPU/undo caps. A controlled allocation-failure test proves no precommit scene image, not
real host-memory-pressure acceptance. This is not out-of-core: two 4K float32 arrays still total 512 MiB.

Canvas creation and cooperative painting now permit 4096²/16,777,216 pixels. Synchronous painting and
default channel statistics remain <=1M. Explicit `image.inspect_pixels(include_statistics=false)`
returns a complete large digest/samples with null statistics, `pixel_digest_complete=true` and
`analysis_complete=false`; it never substitutes omitted ranges/nonfinite counts for a full analysis.
Source identity/metadata/animation/pixels/file evidence, permissions, context/name conflict and
checkpoint revalidation remain authoritative. Native readback compares complete float32 digests.

A final regression exposed pre-existing direct canvas safe-point gaps: pause/emergency set during
native publication could report success, and metadata edits could follow an allocation-time stop.
Image mutator checks now observe live flags after allocation and at subsequent safe points, not
only job gates. Native tests retain denied-cleanup images with truthful possible-mutation/finalized-
boundary evidence and explicitly restore them. Read-only verification remains usable while paused.
No deletion grant is invented, no unexpected consumer is unlinked, and no project/preference is saved.

Validation: **190 focused tests**, then **1,278 tests on each** MCP SDK 2.0.0/2.2.0; lint, mypy
(35 files), generated README inventory (**175 tools**), compilation, ZIP layout/CRC/new-module
checks and whitespace validation passed. The final Windows Blender 4.5.1 LTS / 5.1.2 matrix passed
**60/60** (28 background, 32 private-desktop UI) at
`build/paint-tiles-final-matrix-20261021-2/report.json`. Baseline `8136ed9` plus this then-dirty
implementation; all **143** Python source paths/bytes independently match fingerprint
`97466e4fd56c630a2080c6bb4bfeb175d1d369ea986a673d65b8d648d72b8215`.
Earlier passing matrices and deliberately failing stop regressions remain local, not substituted
for the final source-matched evidence. Test UI never falls back onto the user's input desktop.

The new 4K fixture uses real sockets/timers, independent center/outside samples and complete source/
output digests, explicit material binding, protected scene assertions, cancellation after observed CPU
progress and verified undo preserving an interleaved transform. Its 14 new captures were retained;
painted views were reviewed, and protected before/after/recovered and pre-binding/recovered pairs
are byte-identical on both versions. Of 170 prior PNG-path pairs, 157 are byte-identical, two render
outputs are pixel-identical with differing PNG bytes, and 11 scanner views show the known rerun
variation (133 changed UV pixels; material previews up to 1,002 changed pixels, max 5/255; wire
up to five pixels/max 2). Those variants were re-reviewed; the underlying nondeterminism and
production UV/look acceptance are not claimed resolved.

At an explicit 8 ms CPU setting and 300 s deadline, the 4K stroke changed **531,832 pixels** across
**937,980 candidates**. Full job wall times here were about **41.5 / 37.0 s**, creation **4.0 / 4.1 s**,
status-poll medians **11.9 / 13.8 ms** but maxima **7.75 / 7.99 s**. Whole isolated-process peak working
sets reached **1,614,106,624 / 1,739,960,320 bytes**; these include native/undo/staging and lifetime
setup, not just array memory, and do not prove a cap or RSS return under pressure. The fixture
requires 8 GiB available Windows host RAM before starting and fails rather than hiding insufficient
headroom. No global pressure is induced. Replacing numeric readback comparison with hashing is
byte-level verification, not evidence of a throughput improvement: native tail latency remains open.

Graphify ran on the primary agent in `dino-s-workspace`. The broad query was clipped and mixed
render code; exact `pixel_brush.py` symbols narrowed it to `prepare`, `digest` and `paint` in cloud
`2a62da6`, while current source at/after `8136ed9` governed implementation. Local map `cce4bf0`
remains stale, feedback was saved and the marker updated; no rebuild, extra agents or dependencies.

Next prioritize measured native/source-copy/normalization tail latency and memory-pressure cases,
then surface/viewport projection and masks in the reference workflow. Also retain 8K/UDIM,
identity-preserving/durable pixels, sculpt/vertex/weight painting, full character/animation,
procedural simulation/baking, SAFE-02, persistent UX, delivery and clean install/upgrade/RC gates.
Neither JOB-01 nor PAINT-01 nor scenario B nor the full artist target is closed. Published 0.3.0
assets, package versions and repository visibility are unchanged; no 1.0 release was published.

### 2026-10-21 — Raw-channel UV-image masks and preserved-input paint jobs

PAINT-01 now has one operation-level typed `mask` on synchronous paint versions and cooperative
jobs: exact image name, R/G/B/A channel (default R), optional strict boolean inversion. It uses
raw stored `[0,1]` channel values, not luminance, implicit color transfer or unpremultiply.
Different canvas/mask resolutions use normalized UV pixel-centre bilinear edge-clamped sampling;
equal dimensions read exact corresponding pixels. The weight modulates maximum per-stroke
coverage before COLOR alpha or DATA mixing. A zero mask still permits the explicit whole-output
byte-sRGB conversion; changed-pixel counts exclude that encoding-only change.

New small `image_masks.py` and `pixel_mask.py` modules separate Blender input freeze/revalidation
from pure sampling math. Source and mask remain read-only, including an image used as its own
mask. Jobs freeze complete RGBA digest/identity/metadata/file evidence plus a packed float32
selected channel; validation yields every 256 channel values. All selected-channel pixels must
be finite `[0,1]`, not just the brush footprint. Non-selected channels do not supply weights but
are included in the full preservation digest. Both input names must remain unambiguous. Live
FILE-mask consent is required even with a generated canvas. Revalidation runs before and after
checkpoint setup and after publication; terminal jobs release all channel arrays/handles.

Each input retains the current 1M synchronous / 16,777,216-pixel, 4,096-axis job bounds. Masked
memory estimates conservatively include source/output/readback, mask RGBA/channel buffers and
coverage scratch; native/GPU/undo/allocator memory is excluded, not capped. The existing 175
tools are extended compatibly rather than claiming completeness from a larger tool count.

The `image_masks` native fixture connects structured 128×64 painting and a 16×8 pattern, all
four channels, independent bilinear boundary samples, raw sRGB FILE weights, zero/inverted masks,
a 1,025×1,024 job mask, real socket/timer publication, interleaved transform, explicit binding,
protected captures and confirmed output recovery. It rejects a stale mask and live FILE consent
loss before allocation, cancels private work, and injects a mask change after native publication.
It also injects a canvas alpha-role change after publication: source identity/metadata/animation
are verified again after allocation/readback, not only its complete pixel digest.
Native undo of that external alpha-role edit can invalidate the existing generated canvas buffer;
the fixture records `has_data` without implicit regeneration. Metadata/output recovery is not
accepted as input-pixel restoration.
That fault is detected with `input_preservation_verified=false`, possible-mutation and finalized
boundary evidence, not reported as success. **Native undo removes the owned output but does not
restore the externally edited existing mask pixels.** The fixture verifies that retained edit,
then explicitly restores only its own injected change. Never silently replace a user's mask edit
with frozen weights. Durable/identity-preserving image-pixel recovery remains mandatory 1.0 work.

Primary-agent Graphify in `dino-s-workspace` located `_read`, `prepare_paint`, `finish_paint` and
`paint_version` in the cloud `8136ed9` outline. The index predates `9e69ddd` tiled 4K work and this
mask increment; current source and tests governed implementation. No graph rebuild, added agents,
dependency install, version bump or release/visibility change was performed.

Validation: **217 focused tests**, then **1,321 tests on each** MCP SDK 2.0.0/2.2.0; lint,
mypy (35 files), compilation, generated README inventory (175 tools), and development ZIP
layout/CRC/new-module source checks passed. `AGENTS.md` now requires the private non-input
Windows desktop runner, fail-closed isolation and disposable factory scenes/preferences/recovery
paths for future native work.
The final Windows Blender 4.5.1 LTS / 5.1.2 matrix passed **62/62** (28 background and 34 private-
desktop UI cases) at `build/image-masks-final-matrix-20261021-3/report.json`. It records baseline
`9e69ddd` plus this then-dirty increment; independent byte/path verification matches all **146**
Python sources and fingerprint
`75cddbb06ac1a2b7c9140a9b594e60679d6cb81eee6aea8a0b0d69c4c9bd1168`.
Earlier mixed-source/failing probes remain local and are not substituted for final evidence.

All **16** new mask captures match the focused source-reference fixture byte-for-byte; masked/
inverted views were reviewed, and protected before/after/recovered and pre-binding/recovered pairs
match on both versions. Of **184** prior PNG-path pairs, **176** are byte-identical, two renders
are pixel-identical with different PNG bytes, and six Blender 4.5 scanner captures retain known
rerun variation: 133 UV pixels (max 215/255), preview differences up to 997 pixels (max 5/255)
and five wire pixels (max 2/255). Those UV/front/calibration/isometric/wire variants were reviewed;
this does not resolve packing/render nondeterminism or establish production artistic acceptance.
Both versions explicitly report the external mask pixel edit retained after native output undo,
and `has_data=false` after undo of the external canvas alpha-role edit. Input-pixel recovery is
**not verified**; no implicit regeneration or save conceals that limitation. All 74 packaged add-on
Python modules match current source; the development archive is not a replacement for 0.3.0 assets.
Surface/viewport projection and stencils, sculpt/vertex masks/brushes, pressure/spacing/layers,
weight painting, broader roles/blends, memory-pressure/native tail latency, 8K/UDIM, durable pixel
delivery and the complete character/procedural/simulation/UX/install/upgrade/RC gates remain open.
This increment does not close PAINT-01, JOB-01, scenario B or the full 1.0 artist target.

### 2026-10-21 — Texture codec foundations and cross-version alpha correctness

DELIVER-01/LOOK-01/REC-01 continue under the full artist target. The
[delivery contract](texture-delivery.md) sequences bounded codecs → approved path/staging →
atomic no-clobber publication → typed source-frozen export/reimport jobs → numeric/visual
reopen proof → packing/save/reopen/delivery acceptance. This increment implements the codec/
interpretation foundation and a discovered rendering fix, **not** the export API. Public
`image.load` remains PNG/JPEG only; export and public EXR import are `NOT_IMPLEMENTED`.

New standard-library `pixel_codecs.py` borrows immutable float32 RGBA and yields bounded
PNG8/PNG16 or uncompressed float EXR blocks, plus CPU safe points every 256 pixels. COLOR
uses explicit linear/sRGB interpretation, PNG refuses HDR/signed data without clipping, EXR
supports finite HDR/signed data, and raw EXR retains hidden zero-alpha RGB only with explicit
channel-packed reopening. Conventional COLOR EXR premultiplies, so it is not raw-channel
recovery. These encoders perform no path access/publication or permission changes; staging,
large-file preflight, lifecycle, consent and durable recovery remain required work.

Native probes found that PNG16 COLOR exposes linear associated floats, unlike PNG8's encoded
channels, and straight-alpha float EXR loading can discard hidden zero-alpha RGB. Exact file-
byte/parser tests are separate from native decoder checks; the latter explicitly bound native
PNG16 color/OCIO variation against an independent standard-sRGB reference. A 4096² raw DATA
EXR, with signed/HDR values and distinct corner markers, reopens with a complete matching
float32 digest on both installed versions; no file-sized encoded bytes duplicate is required.

The actual transparent/emission camera fixture then exposed **Blender 4.5 generated float
COLOR rendering too bright despite correct raw RGBA readback**. New bridge canvases and paint
versions now retain independent straight RGBA under native CHANNEL_PACKED. Existing image
datablocks are never relabeled. COLOR remains scene-linear color, not Non-Color data, and hidden
RGB survives. Typed paint normalization supports explicit associated linear float sources,
including generated PREMUL and reviewed linear float FILE buffers, before straight source-over.
The conversion is reported separately and excluded from brush-change counts. Inspector/mask
reads remain raw; additive associated zero-alpha RGB is not fabricated as straight color.
The new normalized FILE render/complete source-digest check exercises the real typed path.

Validation: **263 focused tests**, then **1,356 tests on each** MCP SDK 2.0.0/2.2.0; lint, mypy
(35 files), compilation, generated README inventory (175 tools), development ZIP layout/CRC and
all **75** packaged Python modules against source passed. The full Windows Blender 4.5.1 LTS /
5.1.2 matrix passed **66/66** (30 background, 36 private-desktop UI cases) at
`build/pixel-codecs-final-matrix-20261021-1/report.json`. Baseline `5788548` plus this then-dirty
increment; all **149** Python source paths/bytes independently match fingerprint
`5b6c3d0310bdc015923e8cd112bff45558afc0ef602f121ff962b9d9bd514651`.
The earlier failing interop/render probes are retained locally, not hidden or substituted for
the final source-matched run. All test windows stay off the user's input desktop.

The 4K raw float file is **268,501,384 bytes**, full native decoded/source digest
`6dc7792b679699077adadaf4c6aa88a921909d390e605fb1ebbc5e555cb8dbfb` on both versions.
There are 90,113 emitted byte/CPU steps, maximum block **33,160 bytes**, and encoding here took
about **13.45 / 13.12 s**. These are codec/native readback measurements, not a publication/job,
process-memory cap, memory-pressure or production throughput verdict. The native fixture requires
8 GiB available Windows RAM before its 4K allocation and induces no global memory pressure.

Ten new Cycles CPU camera images were retained/reviewed. Center samples match for generated,
PNG8, PNG16, conventional EXR and the typed normalized FILE. Full-image conventional EXR and
generated pixels match; PNG8 differs at 911 of 1,024 pixels by at most 1/255, PNG16 at ten pixels,
and normalized FILE at three, also at most 1/255, on each version. PNG-byte identity is not claimed
because render metadata differs. The existing material-preview byte-to-float conversion differs
only at 31/30 edge pixels (max 5/4 per channel), re-reviewed on both versions; Alpha is explicitly
connected, not assumed in an alpha-unused graph. Of **200** prior PNG-path pairs, **192** are
byte-identical, two render outputs pixel-identical with different PNG bytes, and six 4.5 scanner
captures retain known rerun variation: 4,538 UV pixels (max 215/255), previews up to 18,204 pixels
(max 6/255), wire two pixels (max 1/255). UV/front/calibration/isometric/wire variants were reviewed;
packing/render nondeterminism and production artistic acceptance remain unresolved. Protected/
recovered mask pairs remain byte-identical. These are bounded evidence, not full artist approval.

Primary-agent Graphify in `dino-s-workspace` identified `preflight_file` / `approved_file` and
Save-As path helpers in cloud `9e69ddd`. The broad query was clipped, so exact `image_files.py`
symbols/current source governed follow-up. Native evidence, not stale graph assumptions, changed
the next action to alpha correctness before public delivery. Feedback is saved locally; no graph
rebuild, extra agent, new dependency, version bump or published-release change was performed.

Next implement approved-path owned staging/no-clobber publication, streamed reviewed-file
preflight and source-frozen export/reimport jobs, then complete durable delivery/recovery tests.
Full approved
export/reimport, fresh-process delivery, durable input-pixel recovery, source-copy/native tail
latency, memory pressure/8K/UDIM, surface/sculpt/vertex/weight paint and all character/procedural/
simulation/UX/install/upgrade/RC gates remain open. No full artist, DELIVER-01, REC-01, JOB-01,
PAINT-01 or scenario acceptance is inferred from these foundations. Published 0.3.0 assets,
versions and repository visibility remain unchanged.

### 2026-10-21 — Approved owned texture staging and no-clobber publication

DELIVER-01/LOOK-01/REC-01 now have an internal `texture_staging.TextureStaging` resource
connecting the bounded encoder to an exact approved output path. It is **not** a registered
export tool, generic file writer, public EXR loader or completed delivery workflow. See the
[file contract and remaining sequence](texture-delivery.md#internal-approved-file-staging).
The existing 32 MiB PNG/JPEG reader remains unchanged; a 256 MiB EXR needs a separately
reviewed shared streaming preflight, not merely a bigger constant or a private import bypass.

The resource requires live edit/external-file/save grants before path probes and each write/read
action. It rejects unsafe/nonlocal/escaping paths, missing parents, volume roots, link/reparse
ancestry and name/extension ambiguity. It creates only owned staging in an existing approved
parent, bounds codec blocks and total bytes, flushes/fsyncs and independently hashes the entire
file in 64 KiB read steps before sealing. Publication is an atomic hard-link create-if-absent,
with no overwrite/rename/copy fallback; competing target bytes survive unchanged. Published
file proof is separate from native decode/pixel/appearance verification and crash durability.

Windows directory read handles deny rename/deletion while the resource owns staging. Initial
attribute-only handles failed a native rename test; the corrected read-handle test now verifies
both exclusion and release. Non-Windows identity checks are not hostile namespace-race exclusion
or a security sandbox. Cancel/pause/stop and IO failures leave only private work until explicit
publication. Cleanup unlinks only the exact unchanged owned staging entry, with live grants,
and closes handles on every path. Revoked consent or changed identity/location retains the
explicit staging path; a final published file is never silently removed. Short/partial failed
writes report observed file bytes separately from bytes accepted into the encoder hash.
Read proofs recheck folder approval before every slice. Publication attempts are tracked
before the system call: a signal/IO error after a possible effect sets
`publication_outcome_unknown`, never a false negative existence promise.

Validation: **156 focused tests** passed, then **1,412 on each** MCP SDK 2.0.0/2.2.0, with
one Windows skip for the POSIX symlink fixture. Lint, mypy (35 files), compilation, the unchanged
175-tool generated inventory and development ZIP CRC/layout checks passed; all **76** packaged
Python modules match source. Development package:
`build/texture-staging-package-20261021-4/blender_codex_bridge-development.zip`.
The Windows Blender 4.5.1 LTS / 5.1.2 matrix passed **66/66** (30 background,
36 private-desktop UI) in `build/texture-staging-final-matrix-20261021-2/report.json`.
Baseline `e60ead2` plus this then-dirty increment; all **150** Python source paths/bytes matched
that run's `3fb76945b55f2194446fe7237f9ac190021ee406acfd84d4bf6c21ac7c2d4ffa` independently.
Final review then added per-read folder revalidation and uncertain-publication tracking.
Only `texture_staging.py` differs between that full matrix and the final source: the other
**149** paths/bytes are unchanged, and only the codec fixture imports this new resource.
Both affected native cases passed again in
`build/texture-staging-read-consent-20261021-2/report.json`, with all current 150 source paths/
bytes independently matching `cf0c599335000a2f2f227aa385e322f82dce2a57a0622a04ea3a251f9e8b5bc8`.
These are explicitly **66 broad checks plus two current-source affected reruns**, not a claim
that the earlier full report has the final global fingerprint. Earlier intermediate reports
are retained, not substituted for final evidence. No test windows touched the input desktop.

Each version stages, seals, no-clobber publishes, completely rehashes and natively reopens the
4096² raw float DATA file: **268,501,384 bytes**, file SHA-256
`276b6e3f57d5cf8e6c4c282290ca116e8f8cff9546313178e65b30d7cdd34ab2`, complete decoded/source
float32 digest `6dc7792b679699077adadaf4c6aa88a921909d390e605fb1ebbc5e555cb8dbfb`.
The codec emits 90,113 byte/CPU steps, maximum **33,160 bytes**. Encoding plus file staging,
sealing, publication and rehash took **42.04 / 41.47 s** in the final affected rerun, including
per-slice consent/path revalidation; those timings are not native decode,
job responsiveness, process-memory caps, memory-pressure or production throughput acceptance.
All eight smaller encoding/role combinations still pass native numeric interpretation checks.
Fixture files are explicitly disposable; helper cleanup removes staging, not the final file.

Of **210** prior PNG-path pairs, **193** are byte-identical, **12** render outputs have identical
pixels with different PNG bytes, and five 4.5 scanner captures retain known rerun differences:
4,531 UV pixels (max 215/255), calibration/front/recovered views 17,749 pixels (max 6/255),
isometric 16,568 (max 6/255). Changed views were reviewed; silhouette/material presentation
remains consistent, but UV/render reproducibility and artistic acceptance are not resolved.
Protected/recovered mask pairs remain byte-identical on both versions. Existing input-pixel
undo limitations are unchanged, not repaired by a file hash or external publication.

Primary Graphify queries in `dino-s-workspace` used cloud `e60ead2` (indexed
2026-10-21T11:44:13.958576Z). A clipped bounded path query was narrowed to exact
`image_files.py` symbols/current source. The new unindexed resource is verified from source
and tests, not invented graph edges. Local feedback/staleness notes are retained; no graph
rebuild, delegation, dependency install or release/version/visibility change occurred.

Next: shared bounded large PNG/EXR structural preflight, typed source-frozen 4K export/reimport
jobs, external-effect terminal history and guarded native image publication, then complete
numeric/visual/fresh-process/packing/save/upgrade acceptance. Keep durable input-pixel recovery,
source/native tail latency, memory pressure/8K/UDIM, surface/sculpt/vertex/weight painting and
all character/procedural/simulation/UX/install/RC gates open. This does not complete DELIVER-01,
REC-01, JOB-01 or the full 1.0 artist objective.

### 2026-10-21 — shared streaming texture preflight and registered EXR import

DELIVER-01 / LOOK-01 now share complete bounded file reads across loading, binding,
revision, pixel inspection and painting. The standard-library reader hashes every byte
with at most **64 KiB/read**, without a file-sized encoded copy. PNG additionally validates
CRC, bounded inflation and exact scanline/filter framing, including Adam7; JPEG retains
reviewed 8-bit frame-header checks, not independent entropy certification. Format budgets
are **129 MiB PNG / 32 MiB JPEG / 257 MiB EXR**, with the existing 8,192-axis and
16,777,216-pixel limits. Tests reject malformed, truncated, inflated, misordered, oversized
and unsupported layouts rather than passing them to native decode unchecked.

Registered `image.load` now admits a reviewed plain FLOAT32 RGBA EXR subset: version-2,
single-part uncompressed contiguous increasing scanlines, unit-sampled A/B/G/R channels,
equal zero-origin windows and bounded known metadata. Explicit Linear Rec.709/PREMUL or
Linear Rec.709/CHANNEL_PACKED color, or Non-Color/CHANNEL_PACKED data, is required; file hints
do not choose interpretation. Half/compressed/tiled/deep/multilayer/non-Rec.709 variants remain
unsupported. The same source policy now applies to downstream FILE-image workflows.
Live file consent/folder checks occur before reads; edit/pause/stop/root checks guard native
allocation and later mutation. Post-callback grant checks also protect staging IO. File
identity and full hashes are rechecked across native loading. Cleanup remains limited to
owned zero-user/no-fake-user images with live deletion consent, reporting retained names
and possible mutation on denial. These are point-in-time guards, not hostile filesystem-race
exclusion or a native-decoder security sandbox.

Validation: **300 focused tests**, then **1,508 tests on each** MCP SDK 2.0.0/2.2.0 passed;
the sole Windows skip is the POSIX symlink fixture. Lint, mypy (35 files), compilation and
the generated 175-tool inventory pass. Development ZIP CRC/layout and all **77** packaged
Python modules match source at
`build/image-stream-preflight-package-20261021-1/blender_codex_bridge-development.zip`.
The full Blender 4.5.1 LTS / 5.1.2 matrix passes **68/68** at
`build/image-stream-preflight-final-matrix-20261021-1/report.json`: 30 background and 38
private-desktop UI cases, never a visible fallback. Baseline `fc9d3e3` plus this increment;
all **152** current Python source paths/bytes independently match fingerprint
`b7cebd00cf457b0d62b5ef9791e390c5b45fbeaac1b23f8bc0286cc960e9a725`.

The registered load/inspect/bind/native-undo path verifies an independent high-entropy
2048² PNG16 DATA file (**33,591,359 bytes**, above the former 32 MiB cap) and a 4096² raw
DATA EXR (**268,501,384 bytes**). Every native PNG channel is compared with an independent
U16-to-float reference using the predeclared **2^-23** absolute allowance; measured maximum
error is **2^-24** on both versions, not a claim of exact reference float bits. Complete
EXR source/native float32 digests match:
`6dc7792b679699077adadaf4c6aa88a921909d390e605fb1ebbc5e555cb8dbfb`.
Both loaded buffers retain their complete native digests through binding undo, and load undo
removes the new datablock while leaving external source bytes unchanged. Existing scene,
mode, selection and active object are independently preserved. Typed PNG/EXR COLOR loading
also passes the existing transparent/emission render comparison. This does not prove
durable recovery of an edited pre-existing input buffer.

Of **210** prior PNG-path pairs, **186** are byte-identical and **12** pixel-identical with
different PNG bytes. The 12 changed scanner captures were reviewed: UV layout differs at
4,531 pixels (max 215/255) on each version; calibration/front/recovered views differ at
17,755 / 17,698 pixels (max 6/255), isometric at 16,849 / 16,854 (max 6/255), and wire at
4 / 7 (max 3/255). Shape/material presentation remains consistent; packing/render
reproducibility and full artistic acceptance remain open. Protected/recovered mask pairs
are byte-identical on both versions. Earlier intermediate runs remain diagnostic artifacts,
not substitutes for the final source-matched report.

Primary Graphify queries used `dino-s-workspace`, cloud `fc9d3e3` indexed
2026-10-21T12:23:54.443264Z; clipped retrieval was narrowed to exact file outlines and current
source. The new reader is unindexed, not an invented graph relationship. No graph rebuild,
delegation, dependency install, release/version or repository-visibility change occurred.

Next: source-frozen typed cooperative export/reimport jobs, connecting existing codecs,
staging and the shared reader to external-effect terminal history and guarded image
publication. Current public loading is still synchronous and native decode is non-preemptible;
internal yielded preflight steps do not establish responsive jobs. Keep fresh-process,
packing/save/reopen, memory-pressure/scale, durable input-pixel recovery, mixed-editor
interleaving and all remaining M1–M6/full-artist gates open. No registered export API or
1.0 release readiness is claimed.

### 2026-10-21 — cooperative texture export/reimport and explicit file effects

DELIVER-01 / LOOK-01 / JOB-01 now have registered `image.export_job_start`: one explicit
loaded image version, PNG8/PNG16/EXR32/EXR32_RAW, exact unused approved file path and unique
reimport name. Live `EDIT_MATERIALS`, `ACCESS_EXTERNAL_FILES` and `SAVE_PROJECT` are required;
there is no implicit overwrite, rename, directory creation, node binding, packing or project
save. The existing paint scheduler now shares its single-active limit, transport handoff,
owner/deadline/cancel controls, bounded retention and CPU slices with delivery. The sidebar
shows image-job progress/configuration and published-file/retained-staging warnings.

The driver freezes source identity, complete metadata/pixels and permitted FILE evidence;
revalidates before publication, after checkpoint setup and before success; encodes/seals
owned staging; publishes without clobber; cooperatively rehashes/parses the file; performs
one synchronous native checkpoint-guarded reimport; compares **every decoded channel** with
independently computed encoding/native references; then revalidates source/file/output.
Associated linear color normalization changes only the private copy. Original and encoder-input
digests are distinguished; normalized/byte-sRGB conversion is not advertised as raw input-bit
recovery. Raw float references include signed zero; PNG/native color allowances are declared
in the [delivery contract](texture-delivery.md), not relaxed after a failing sample.

Cancellation before publication cleans only unchanged owned staging with live grants.
Published or uncertain file effects survive all terminal paths, cleanup failures and native
undo. They remain in bounded jobs and operation history, separate from native image recovery.
Failed allocation cleanup still needs deletion consent. Once the native checkpoint is finalized,
later verification yields to other work: late failures retain the image for explicitly confirmed
recovery, never delete a potentially interleaved edit outside that checkpoint. Generator/resource
failures retain evidence and release owned handles. Acceptance history explicitly says delivery
is incomplete. Detailed history evidence is redacted without `INSPECT_SCENE`, while recovery
controls remain available and the local audit is unchanged. No transport events/version change,
arbitrary Python shortcut or network-thread Blender execution was added.

Validation: **165 focused tests**, then **1,562 tests on each** MCP SDK 2.0.0/2.2.0 passed;
the sole Windows skip is the POSIX symlink fixture. Lint, mypy (35 files), compilation and
the generated **176-tool** inventory pass. Development ZIP CRC/layout and all **79** packaged
Python modules match current source:
`build/texture-delivery-package-20261021-2/blender_codex_bridge-development.zip`.

The full Windows Blender 4.5.1 LTS / 5.1.2 matrix passes **70/70** (30 background,
40 private-desktop UI) at `build/texture-delivery-final-matrix-20261021-1/report.json`.
Baseline `63c8690` plus this increment; all **155** Python paths/bytes independently matched
`6eede6af2d7836e066bbf0c89dfa6c6100cb38afc05bf3bede8a09951e0b004b` before final review.
The review found that unguarded recovery history could expose new detailed job evidence.
After that frozen run completed, the history handler, its MCP documentation and the delivery
fixture were updated. Only `addon/blender_codex_bridge/tools/core.py`,
`mcp_server/tools/core.py` and `scripts/blender_image_delivery_smoke.py` differ; the other
**152** paths/bytes are unchanged. Both affected native cases (`core`, `image_delivery`) pass
again on both versions at `build/texture-delivery-history-guard-native-20261021-1/report.json`,
matching all current 155 sources at
`c3fbc9e369dc64d4ef9962e4fc3f7697a196a45193e2cda69e7b28ec0d0ef025`.
That run explicitly verifies inspection-denied history redaction, preserved local audit and
minimal status on real sockets. These are **70 broad checks plus four current-source affected
reruns**, not one full current-fingerprint 70-case run. All Blender windows remain off the input
desktop, without a visible fallback; user projects/preferences remain untouched.

Each delivery fixture exercises all eight small format/role combinations and a complete
4096² raw DATA path with independent source markers: **67,108,864 channels**, file size
**268,501,384 bytes**, file SHA-256
`276b6e3f57d5cf8e6c4c282290ca116e8f8cff9546313178e65b30d7cdd34ab2` and exact native/source
float32 digest `6dc7792b679699077adadaf4c6aa88a921909d390e605fb1ebbc5e555cb8dbfb`.
Native undo removes reimport/binding while preserving the earlier interleaved transform and
source pixels; full external bytes persist unchanged. Cancel/disconnect, paused expiry,
permission loss, post-file and post-native cancellation are exercised on real sockets/timers.
The final 4K jobs took **118.19 / 123.00 seconds** at an 8 ms CPU setting, with maximum observed
inspection-call stalls **9.00 / 10.07 seconds**. This is measured synchronous source/reimport/
preflight/native latency, not a hard CPU-slice/cancellation ceiling or production throughput
acceptance. Full 4K acceptance here is the raw DATA encoding, not universal format/scale,
memory-pressure or 8K/UDIM acceptance. The fixture requires 8 GiB host headroom, not a process
cap or a global pressure test.

Ten controlled 32px color/alpha camera outputs are retained. PNG8 differs from the generated
reference at 295 pixels, PNG16 at five, at most 1/255 per channel; both EXR variants have
identical pixels on both versions. Quantization/appearance measurements are separate from
native channel references; representative captures were viewed. This is not full artistic
acceptance. Of **212** prior PNG-path pairs in the broad run, **188** are byte-identical,
**12** pixel-identical with different PNG bytes, and **12** scanner captures retain reviewed
packing/render rerun variation. UV differences are 4,531 / 4,538 pixels (max215/255),
calibration/front/recovered 17,757 / 18,237 (max6), isometric16,859 /17,536 (max6), wire7 /6
(max3). Shape/material presentation remains consistent, not a reproducibility fix. Protected/
recovered mask pairs remain byte-identical. Earlier fixture Path/str and oversized success-line
failures remain diagnostic evidence; compact final markers passed the unchanged runner gates.

Primary Graphify used `dino-s-workspace`, cloud `fc9d3e3` indexed2026-10-21T12:23:54.443264Z;
capped retrieval was narrowed to the exact jobs outline and current code/tests. New delivery
symbols are unindexed, not invented graph edges. No graph rebuild, agents, dependency install,
release/version or visibility changes occurred.

Next: fresh-process delivery reopening, packing/approved save/reopen and durable edited-input
pixel recovery; measure/shorten synchronous tails and broaden format/scale/memory-pressure
acceptance. Keep all remaining ownership, sculpt/surface/vertex/weight painting, character/
animation, compositor/procedural/simulation, interactive UX, compatibility/install/upgrade and
RC gates within the full 1.0 artist objective. This is implemented bounded texture delivery,
not completed DELIVER-01/REC-01/JOB-01 or a human-equivalent 1.0 release.

### 2026-10-22 — Release implementation resumed; bounded foundations integrated

The user explicitly authorized the full release plan. Current checkout `041aceb` lacked
the handoff's 17-path saved-relative-source increment and its Windows reports; only three
pre-existing guidance/documentation edits were present. The missing source behavior was
reimplemented and independently tested, rather than treating the handoff's 1,656-test result
or Windows runs as current-checkout evidence. Existing user edits are preserved separately.

Implemented increments:

- Stored FILE `//` dependencies resolve against saved local projects with canonical alias,
  project-anchor, approved-folder and live-consent revalidation. Explicit caller paths remain
  absolute. Default texture refresh, binding, painting/masks and export share that contract.
- Native runner writer/reader phases use separate profiles/logs/process instances and only
  owned artifact bundles. Failed writers never start readers; timeout applies per phase.
  Fresh-profile Save As/reopen checks include eight encoding/role variants, complete 4K raw
  DATA channels and matched RGBA8 camera evidence. This does not certify edited generated
  input buffers, crash durability, artistic quality or UI undo.
- Object/data/Action ownership guards cover concrete transform/modifier apply, constraints,
  armature/keyframe and scene camera/light/World gaps. Ordinary per-object changes still
  permit shared mesh data. Collection lifecycle, parenting restoration, broad dependencies,
  mixed-editor/memory-pressure recovery and Windows acceptance remain open.
- Optional scene evidence measures rig rest/pose, active/layered animation/driver/NLA state
  and nested shader/interface dependencies. Bounds and unsupported coverage remain explicit.
- Explicit FILE_BYTES packing differs from CURRENT_PIXELS raw snapshots. Matching loaded
  float originals can recover exact pixels without changing their ID or consumers, within
  1M-pixel/20MiB limits. Byte/unloaded/4K/UI-undo and broad durable recovery remain open.
- Named active-Action copies and bounded existing curve interpolation/handles; reviewed
  nested GN instances/copies and stable modifier inputs; revisioned artist plans with explicit
  persistence and advisory protected comparisons; sidebar plan progress.
- Previewed, approved-path, no-clobber GLB/FBX export for reviewed material-free static/skinned
  assets. Explicit format-loss acknowledgement, fresh-process geometry/deformation fixtures,
  bounded external-effects history and inspection-based redaction. Materials, general imports
  and production exchange remain open.
- Machine-readable open requirement ledger, exact committed-source/package qualification,
  retained hashed evidence and an explicitly dispatched publication workflow. The workflow
  cannot publish without accepted Windows/installed A–F evidence and a matching existing tag.

Validation before integration commit: both complete non-Blender suites passed **2,056 tests**
on MCP SDK **2.0.0** and **2.2.0**, with **three Windows-only skips** each. Ruff, mypy (40
standalone files), compilation, generated **198-tool** inventory, dependency and diff checks
passed. Per-increment Linux Blender 4.3.2 reports are dirty-source development evidence;
they are not combined into a Windows or full-release verdict. Final source/package evidence
is retained under `build/release-implementation-20261022/` with separate logs and hashes.

At this checkpoint the user reported no available Windows 11 test machine. The later
2026-10-23 direction pauses Windows testing at the user's request. All fourteen requirement
acceptance entries stay open. Full modeling/retopology, sculpt/surface/vertex/weight painting,
character/driver/NLA, simulation/cache/bake, production materials/import/delivery, full artist
interaction, constrained-memory, installed upgrade/rollback and Windows version acceptance
remain mandatory. This increment is substantial implementation progress, not completion of
the full ten-step plan. No 1.0 version bump, tag, workflow dispatch, publication or repository
visibility change is justified by these results.

The first clean-checkout Linux run at integration commit `844d771` selected 21 non-UI
cases and finished **20/21**, not a passing matrix. The pre-existing artist fixture assumed
layered Action slots on Blender 4.3 and a Cycles denoiser omitted from this build. Its fixture
now checks slot identity only when that API exists and explicitly disables denoising; all
motion, protection and measured red compositor assertions remain. A focused native artist
rerun passed at `build/release-implementation-20261022/artist-legacy-render-check/report.json`.
The earlier failed runs remain separate diagnostic evidence. Repeat the whole selected-case
matrix after this fixture change; do not combine the old 20 passes and focused pass as a
single current-commit matrix. Packaged-install acceptance remains separate from source smokes.

Final clean-source verification at `90997f5` completed **21/21 selected Linux Blender 4.3.2
native cases**, including all four fresh-process workflows, with the complete 175-file Python
inventory matched to the committed source. All development package bytes/checksums match
that checkout, and an isolated installed wheel exposes 198 tools over stdio. See the
[retained checkpoint summary](release-implementation-20261022.md) for fingerprints, exact
evidence paths and limitations. These are 21 of 41 registered cases, not Windows or installed
full-artist acceptance. All release ledger requirements remain open.

### 2026-10-22 — Opt-in protected static-prop iteration (development)

Four typed core tools add explicit runtime protection, exact selection/name references,
nonmutating transform previews and single-use preview application. Default plans remain
advisory and saved schema-v1 text never restores live policy, identity, reference or baseline
authority. While armed, only the reviewed Object-channel transforms and preview application
can modify Blender; unreviewed mutators, context/undo/save/persistence remain denied before
their handler/checkpoint. Every accepted field and compensation rechecks protected identities,
policy generation, authored/context state and bounded incoming Object consumers after callbacks.
The first static profile rejects unknown callbacks, drivers, implicit physics/procedural roles
and larger/complex affected structures; see [the exact contract](task-plans.md).

Dirty-source development validation on base `91cf622` passed **3,807 tests and three Windows
skips on each MCP SDK 2.0.0/2.2.0**, Ruff, mypy (57 standalone files), inventory and compilation.
The registry has **255 tools**. Matching **267-file** Python inventory SHA-256:
`98ef5b9ddef5d5968bbccfbf06b390d2179f1ee5b15dc4d9ffd60fa6edc1f78e`.
Official Linux Blender **4.5.14 LTS** and **5.2.2 LTS** each passed the selected `artist_loop`,
`object_rna_mutations` and two-process `task_plans` cases through the isolated native runner.
Reports/logs are under `build/artist-loop-freeze-{45,52}-20261022/`; retained validation and
log hashes are in `build/artist-loop-freeze-validation/summary.json` in the isolated feature
worktree. These are **3 of 80** cases, not the complete native inventory or installed acceptance.

The fixture proves exact-reference placement/correction, protected comparisons, permission and
unknown-tool denial, late context/consumer/identity changes, explicit disable audit, cancellation/
disconnect partials without illegal compensation, and native handler/getter rejection without
invocation. It neither renders nor saves. The full UX-01 benchmark, visual reference understanding,
wider protected authoring, protected authorized save/delivery, Windows and all release acceptance
remain open. No version, release, package publication or requirement acceptance changes here.


### 2026-10-22 — Retained checkpoint admission and bounded delivery research

Scene and render increments retain request identity and one authored comparison plan
before callbacks, through native checkpoint pushes and handler finalization. Marker
updates compare exact ownership and preserve newer values. Custom-property evidence
retains exposed scalar types and finite float signs. Production guarded batches
require reviewed composition; current Scene/render composition refuses before writes.
See [Scene scope](scene-edit-safety.md) and [render scope](render-boundaries.md).
Scene success still reports unread bundled runtime settings; the exact reviewed
Blender 5.2 render profile refuses because a supported read-only hidden-storage
reader is not proven. These changes advance safety without closing the mutator audit.

Three typed rigid-body inspect/preview/cache tools remain bounded to their documented
whole-world profile. Private Mesh/UV and external WindowManager-role projections are
comparison research and do not expand production admission or provide backups.
The [fresh-worker serialization probe](portable-blend-worker-research.md) restores
original per-ID fake-user flags and compares a tiny static asset with packed 2×2
images after a fresh reopen. Blender 4.5 camera serialization's compatibility
conversion is reported explicitly. This is neither complete-project preservation nor
an OS/network-contained production save backend; public project.save stays unavailable.

The combined development registry has 258 tools. Per-increment receipts retain their
own source fingerprints, failures and selected Linux results. Combined clean-source,
package and CI checks require separate receipts; previous source passes are not
combined into a current full native verdict. All fourteen release requirements remain
open, including Windows 11, installed scenarios A–F, safe saving, production delivery,
memory-pressure recovery and visual artist acceptance. No release date or 1.0 publication.


### 2026-10-23 — Open-chain modeling and exact-build import containment

Development adds paired `mesh.bridge_chains_preview` / `mesh.bridge_chains` tools with
explicit equal-chain correspondence, retained pre-checkpoint admission, measured original
and already-published data, live per-write guards and truthful partial effects. A native
partial-edit recovery failure exposed missing derived-cache synchronization; each verified
face now receives guarded normal/tessellation updates before later allocation. The connected
prop fixture passes on Linux Blender 4.5.14/5.2.2, including the demonstrated injected failure
and two actual recovery paths. Retained captures receive limited technical review. See
[the bounded contract and evidence](mesh-loops.md).

The known Blender 5.2.2 build `d13f752e3b9c` now refuses typed asset import before checkpoint,
source/staging or scene allocation; preview remains available. A proposed global-cycle
release fix failed native validation and is not integrated. The original full import fixture
remains unchanged and unsupported on that build. The separate passing admission case
verifies containment only. [Import details](asset-import.md) retain the unresolved gate.

The combined development source passes 5,370 non-Blender tests with three Windows-only
skips using MCP SDK 2.2.0, plus Ruff, mypy, compilation, generated inventory and whitespace
checks. The registry has 260 MCP tools. Existing Python 3.10–3.12 / SDK 2.0.0 and 2.2.0 CI
coverage is retained. The focused native results are not a complete native inventory or
installed-package acceptance. Failed source variants remain retained independently.

Windows compatibility work is paused at the user's request while implementation proceeds.
All fourteen release gates remain open, including whole-project safe saving and production
import/recovery. Component versions remain 0.3.0; no release is published by this increment.


### 2026-10-23 — Exclusive native-import mutation ownership (development)

`asset.import` now acquires an internal registry-owned lease before admission,
permission callbacks and automatic checkpoints. It retains ownership through native
work, compensation and finalization. New nested mutators cannot borrow its context,
request identity or recovery flag; the canonical handler continuation is single-use.
Read-only inspection/status retains the outer execution display. Guarded import writes
and cleanup prove exact ownership after callbacks, and only the owning scope releases
its own lease. Other batch, artist-transform and painting-job composition is unchanged.
This interlock neither constrains arbitrary Python/native callbacks nor preempts native
calls, implements safe project saving, or removes the known 5.2 import quarantine.

Validation: 68 focused and 5,438 full non-Blender tests pass with three Windows-only
skips; Ruff, mypy, compilation, generated inventory and whitespace checks pass. The
native fixture at `526ec0e` passes on Linux Blender 4.5.14 and 5.2.2, proving 36 nested
rejections per runtime across admission/provider/checkpoint/handler/finalizer callbacks,
actual edits and undo, scope release on success/failure, and a subsequent admitted edit.
The separate existing 4.5.14 GLB/FBX import writer/reader fixture passes with injected
failure cleanup and fresh reopen; its serialization remains explicitly fixture-only.
An earlier `ff60d6c` fixture failure is retained: its final control operation returned no
reviewed checkpoint guard. The correction changes only the fixture, not production code.

The 308-file native source fingerprint is
`e3d2b08083d61525bd082c8ea4af6e4f7752efeb4b4fe2c09eb2839cd77ce13c`.
Local source, logs, reports, unit receipt and negative evidence are retained in
`build/exclusive-mutation-evidence-20261023.tar.gz` (SHA-256
`c7a4340cdd9d7755333757e339bf8673bc183f9f37b75800c263e4ec66a3c61c`).
These focused checks do not establish a complete current native matrix, Windows,
installed-package or full workflow acceptance. Windows work stays paused; all fourteen
release gates remain open and component versions remain 0.3.0.


### 2026-10-23 — Step-linked artist execution evidence (development)

Existing transform previews can bind an exact current plan step. A bounded runtime
journal links the finalized outer executor operation ID and measured checkpoint/error
facts to that preview, including rejected and failed attempts. Explicit step-linked
comparison records protected-object observations only; it never certifies the edited
target, appearance, user goal or completion. Reconnect preserves the journal; undo/redo
marks observations stale and operations historical; plan replacement/load/reset clears
it even when IDs are reused. Saved schema-v1 remains passive and unchanged.

Portable regressions exercise callback retargeting, reused IDs, finalized failure
receipts, direct/nested writer invalidation, bounded retention and recording failures.
At preparation the extended artist-loop native fixture was unexecuted. Subsequent
source-matched Linux runs now cover the extended artist loop, multi-target pushes
and interactive undo; see the [2026-10-23 checkpoint](artist-workflow-checkpoint-20261023.md).
UX-01, full visual/artist acceptance and all release gates remain open.

### 2026-10-23 — Scene ownership, truthful entry effects and loaded shader research

Frozen production source `ff8b0f06e2cc2614eb9192b7d90ea4a6f414b517` passes
**6,169 non-Blender tests with three Windows-only skips** and static checks.
Its 324 production/runner Python files have fingerprint
`7d552d3e032a5d8af58893b57137bff71a8a723492f68817644958bc80cd46a1`.
The registry remains **260 MCP tools**, component versions remain **0.3.0 alpha**,
and Windows testing is paused at the user's request.

The integrated internal Scene kernel retains exact reservations, starter/driver
authority, scheduler-local turns and owned pending checkpoints. One domain or
checkpoint phase runs per tick; status is cached. Both Linux builds pass a
five-scenario fixture: successful three-body matrix evaluation and stopped
cancel/permission/disconnect/external-edit cases, retaining partial receipts
without stopped-owner cleanup, context restoration or AFTER pushes. This is
evaluation evidence and adds no public rigid-body job or bake API.

Fourteen further selected runs cover artist entry/loop/multi-target, interactive
undo, Scene checkpoint admission, painting jobs and exclusive import ownership
on both builds. The total **16 selected results** is not a full native inventory.
Public permission-denial cases retain exact four-boolean possible-context-effect
metadata in errors/history; portable regressions verify rejected-step receipt
timing before terminal recording. Primary errors, legacy
flag presence, requested transforms, protected geometry and zero native-entry
counts remain intact. Selection can still normalize before denial. This
diagnostic does not prevent the native getter effect, and armed capture still
refuses. Earlier exact-object framing/pixel evidence remains source-specific.

Separate research source `31eb64d4f26c7bc223464c8c099c1cd49547f895`
passes twelve unused interface-socket removal/actual undo/redo cases per Linux
build and fresh-process reader checks. It requires explicit owned loaded setup
and literal `is_runtime_data=False` on every participant, with no runtime-field
exclusion. Native active interface identifiers change in all twelve cases on
each build; no public UI-preservation or production REMOVE/conversion claim
follows. The original fresh-created and immediate-post-load failures remain
retained, separate from the corrected post-load timer result.

The [dated checkpoint](artist-workflow-checkpoint-20261023.md) records exact
sources, report/audit hashes, retained archive and limitations. Safe project save,
the exact Blender 5.2 import quarantine, protected visual verification, public
simulation jobs, Windows/installed A–F acceptance and all fourteen release gates
remain open. Next work must complete those bounded contracts and native proofs;
no gate is waived or closed by these selected passes.

### 2026-10-23 — Public bounded rigid evaluation jobs

Frozen production source `aacb39d70b76d0533473f9fb1d154d75ac8ae605` adds
`rigid_body.evaluate_preview` and `rigid_body.evaluate_job_start` in the disabled-by-default
simulation toolset, bringing the development registry to **262 MCP tools**.
Component versions remain **0.3.0 alpha**. The exact preview binds the complete
bounded static world, proposed cache range and job deadline. The Scene kernel
owns the pending checkpoint and reservation across yielded native phases;
successful evaluation retains the requested range and restores caller time.
Cancellation, permission loss, disconnect or authored drift retains partial
effects without automatic stopped-owner restoration or cleanup. Selected native
interval receipts are bounded; they do not prove complete native/cache state.
This adapter performs evaluation only, without BAKE or cache conversion.

The source passes **496 focused and 6,365 full non-Blender tests**, with three
Windows-only skips and static checks. Its 329 Python files have fingerprint
`1f086f3dee9bb5cb16b8bf81aa093372be57cd63cafa6ab7e67f1fb258b95eb5`.
The source-matched public RPC fixture passes on Linux Blender 4.5.14 LTS and
5.2.2 LTS: two successful jobs and eight early/late stop cases per build, with
retained-receipt capacity refusal. Moving and zero-gravity three-body/three-frame
trajectories match fresh complete matrix references with zero error. The
independent source/evidence audit passes. A separate same-source composition
report passes eight existing cases per build, with its independent source,
marker and artifact audit also passing. Exact report/audit hashes and raw-log paths are retained in the
[evaluation-job contract](rigid-body-evaluation-jobs.md).

The native fixture uses standard-library TCP and the actual public typed Blender
RPC. Portable official MCP SDK/schema tests are separate, and neither route
establishes an installed MCP-to-Blender artist scenario. The earlier `ff8`/260-tool
results above remain historical source-specific evidence. Hidden cache coverage,
cooperative bake, setup/broader solver work, the full 16-body/32-frame bounds,
memory/latency and whole-workflow recovery remain open, alongside safe project
save, protected visual verification, native MCP end-to-end, Windows and installed
A–F acceptance. All fourteen release requirements remain OPEN; the full 1.0
target is unchanged.

### 2026-10-23 — Read-only exact F-curve evidence before authoring

`animation.curve_inspect` adds explicit-object active-Action/assigned-slot
inspection under `INSPECT_SCENE`. It returns stored extrapolation and complete
finite keyframe/Bezier-handle coordinates and types in indexed pages: 64 points
by default, at most 256 per page and 1,000,000 points per curve. Exact selectors
refuse missing or ambiguous curves; shared/linked data remains readable. Sampled
curves and unsupported layered APIs fail explicitly. Inspection never updates or
evaluates animation. Use these pages before an intended `curve_edit` and afterward
to compare authored values; separate sampled-motion and deformation evidence is
still required.

The development registry now contains **263 MCP tools** and component versions
remain **0.3.0 alpha**. This bounded read-only increment does not complete full
character/animation acceptance (`CHAR-01`) or any other release requirement.
Native fixture results must be retained for the exact qualified source; all
fourteen release requirements remain OPEN, including Windows and installed A–F
acceptance.

### 2026-10-23 — Explicit manual camera focus distance

The existing `camera.configure` adds optional finite `focus_distance` from 0 to
1,000,000,000 in Blender coordinate units, with no scene-unit conversion. A final
focus object is incompatible with manual distance; existing focus targets require
explicit clearing. Distance-only edits retain the existing static Scene admission,
sole-camera-data ownership, per-write authority, native Float32 prediction and
measured recovery contract. Neither focus clearing nor depth-of-field enabling is
implicit. Configuration and object inspection report stored distance even when
it is inactive, supporting inspect → edit → compare before matched visual review.

This extends an existing schema: the registry remains **263 MCP tools**, component
versions remain **0.3.0 alpha**, and all fourteen release requirements remain OPEN.
Source-matched native and visual evidence is still required; this bounded change
does not complete cinematic variants, installed A–F or full artist acceptance.

### 2026-10-23 — Bounded stored F-curve value sampling

`animation.curve_sample` complements stored key/handle inspection with native
values at 1 to 128 explicit Action-coordinate frames. It selects exactly one
active-Action/assigned-slot curve, reports Float32-effective evaluation times and
keeps scene time, context and authored animation unchanged. The initial bounded
contract supports 1 to 1,024 finite, ordered keys with constant, linear or Bezier
interpolation and constant or linear extrapolation. Modifiers, drivers, sampled
curves and unsupported native state fail explicitly before evaluation.

This is numeric stored-curve evidence, excluding NLA blending, constraints,
drivers and deformation. It supports inspect → edit → compare easing without
claiming complete sampled character motion. The development registry contains
**264 MCP tools**; component versions remain **0.3.0 alpha**. Exact-source native
and installed-package qualification remain separate evidence requirements. All
fourteen release requirements remain OPEN and Windows testing remains paused.

### 2026-10-23 — Surface publication callbacks and protected scope

A source-matched negative probe at local `13668d2` reproduced a surface-brush
ordering gap on Linux Blender 4.5.14 and 5.2.2: the last permission provider ran
after the final preservation comparison. Five measured cases per build published
sculpt/color effects after pause or changed coordinates/ownership; sculpting
overwrote a newer coordinate and color removal affected a newly shared consumer.
The research reports explicitly keep `production_guard_accepted=false`.

The first corrected-source native run at `ec821d8` failed because its allocation
prediction assumed zeroed color layers. Complete native captures on both Linux
builds instead measured white RGBA for new POINT and CORNER `FLOAT_COLOR` layers.
That failed run remains separate evidence. The prediction and portable test
doubles were corrected to the measured literal state before further acceptance.

The bounded correction finishes callbacks before callback-free scope/content
validation and the canonical pure caller/stop gate. Exact operation names,
attribute checks and create/rename destination checks remain part of admission.
Source-matched positive native proof, portable regressions and full validation
are required before accepting that correction. This advances SAFE-01 and base
sculpt/color workflows without claiming complete mutator recovery, durable
backups, visual artist acceptance or any closed release requirement. The public
surface remains **264 MCP tools**, components **0.3.0 alpha**, with all fourteen
requirements OPEN and Windows testing paused.

### 2026-10-23 — Generated UV-image sculpt mask sampling

`mesh.sculpt_mask_sample` connects a painted local generated image to the existing
explicit sculpt brush without adding an image dependency to the mutation
boundary. Under `INSPECT_SCENE`, it reads a named Object Mode base mesh/UV layer,
samples a raw R/G/B/A channel at each requested vertex's UV corners and returns
ordered numeric weights. The caller explicitly chooses MIN, MAX or MEAN for UV
seams; inversion applies to each corner sample before reduction. The bounded
profile supports 1–1,024 distinct vertices, finite `[0,1]` UVs and a loaded,
unanimated four-channel generated image with each dimension from 1 to 4,096 and
at most 1,048,576 total pixels. It performs no
color/alpha conversion or image, geometry, selection, frame or checkpoint write.

The returned image/UV/topology fingerprints describe a snapshot, not a live
binding or durable backup. Resample after image, UV or topology changes, then
pass the resulting `vertex_indices` and `mask_weights` explicitly to
`mesh.sculpt_brush`, whose independent edit/ownership gate remains authoritative.
Portable analytical/schema tests and exact-source native paint → sample → sculpt
preservation/visual evidence are separate completion requirements.

This advances the painted-mask portion of PAINT-01 and the asset workflow. The
development registry contains **265 MCP tools**, component versions remain
**0.3.0 alpha**, and all fourteen release requirements remain OPEN. Production
sculpting, 4K/constrained-memory masks, durable recovery, Windows and installed
A–F acceptance remain required; Windows testing remains paused.

### 2026-10-23 — Integrated character weight repair and IK reach benchmark

The opt-in background `character_revision` fixture connects existing registered
tools around one character revision: inspect a poor elbow-weight patch, configure
one static two-bone IK branch, repair explicit memberships with a weight brush,
revise reachable target poses, then author an Action on the independent target
with the rig/skin consumer scope declared explicitly. Stored curve inspection and
sampling remain separate from current-frame evaluated deformation evidence.

Its completion contract requires all-vertex independent skinning calculations,
separate endpoint/bend-plane expectations, complete protected authored data and
corresponding-frame comparisons for an independently animated shared-rest alias.
Permission/locked-group refusal and known static IK post-write compensation must
be measured, with matched 512px fixture-only captures retained for review. Exact
source native results remain required; no pass is inferred from runner wiring or
this planned evidence contract. See [the benchmark](character-revision.md).

Static-only IK mutation and the one-IK-per-rig limit remain authoritative; this
does not add animated-control IK reconfiguration or general control rigs. It
neither saves a project nor qualifies native global undo or durable recovery.
The registry remains **265 MCP tools**, components **0.3.0 alpha**. All fourteen
release requirements remain OPEN, including full CHAR-01, installed A–F and
Windows qualification; Windows testing remains paused.

### 2026-10-23 — Explicit target verification for step-linked transforms

`task.plan.verify_transform` adds a distinct target-result observation to the
artist loop. A step-linked preview retains an immutable independent Float32
expectation before application. The explicit read-only method compares that
expectation with the exact native target's authored core channels and attaches
the result to the current step's latest successful completed outer receipt.
Protected-data comparison, a claimed step mark and artistic acceptance remain
separate evidence.

The first profile compares location, unchanged rotation mode, all three stored
rotation representations and scale, including inactive channels and signed zero.
Mode conversion and unqualified numeric storage profiles remain explicitly
unavailable without changing the existing preview/apply contract. Frozen
provenance is checked after live callbacks and static native reads; changed
receipts, generations, plan revisions and intervening writers refuse. The reader
uses no context/selection getter, view-layer update or evaluated/world transform.
No checkpoint, native write, save or automatic completion is performed.
Successful calls add no operation-history entry; failed or rejected calls handled
by the executor retain its existing failure audit.

The completion gate requires portable provenance/schema checks and the isolated
`artist_target_verification` fixture on both Linux development builds, with
independent Float32 values and complete declared protected/context preservation.
Source-matched reports remain required; documentation or wiring alone establishes
no native pass. See [the contract](artist-target-verification.md).

This advances UX-01 while retaining **266 MCP tools**, component versions
**0.3.0 alpha**, all fourteen requirements OPEN and Windows testing paused.
Broader target/dependency/visual evidence, protected save, native undo/durable
recovery, whole artist scenarios and installed A–F remain mandatory.

### 2026-10-23 — Historical target evidence in the artist sidebar

The artist sidebar presents the latest displayed step receipt's existing public
target observation under a **Target core channels:** heading, with the status on
the next line. The fixed historical and step-claim reminders each use two short
lines. These line breaks change presentation only. Recorded matches, differences,
missing targets and replacements remain historical;
protected comparison and claimed completion retain their separate meanings.
Stale evidence takes priority over a previous recorded result. Unavailable
expectations and targets not yet verified remain distinct, while missing legacy
fields or unsupported record contents display uncertainty rather than success.

The presentation formats the receipt already available to the sidebar. It adds
no plan inspection, native/context read, verification, capture, mutation or save.
Portable formatter and sidebar-wiring checks are the completion gate for this
bounded UI increment; they do not establish current-scene, visual, installed or
full artist-workflow acceptance. See [the display boundary](artist-target-verification.md#sidebar-evidence).

This advances UX-01 with **266 MCP tools**, components **0.3.0 alpha**, all fourteen
release requirements OPEN and Windows testing paused. Protected save, durable
recovery, broader target/dependency/visual evidence and installed A–F remain
required.

### 2026-10-23 — Bounded authored quaternion assignments

`transform.set` and `task.plan.preview_transform` gain optional
`rotation_quaternion=[W, X, Y, Z]` for an already-`QUATERNION` target. The new field
excludes Euler rotation inputs and every `rotation_mode` argument. It retains
independent Float32 expectations without normalization, mode conversion or sign
canonicalization. A complete qualified immutable six-channel intent is required
before writing. The bounded numeric and static single-user Mesh
[mutation profile](object-rna-safety.md#quaternion-assignments) applies only to the
new field; ordinary transform inputs retain their existing contracts.

Seven-case native-storage research at `112f7d6` is historical prerequisite
evidence, not typed-workflow acceptance. Source-matched portable checks and
native setter/preview/application/explicit-verification evidence remain required,
with measured protected/context preservation and refusal/recovery behavior.
Authored core-channel results do not establish evaluated orientation, artistic
acceptance, native global undo or durable recovery.

This advances the bounded transform portion of UX-01 with **266 MCP tools**,
components **0.3.0 alpha**, all fourteen release requirements OPEN and Windows
testing paused. Protected save, wider character/dependency/visual workflows and
installed scenarios A–F remain required.
