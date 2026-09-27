# 1.0 execution plan

Status: active, **not release-ready**. Planning baseline: `3ad11a3`, 2026-09-27.
This is the current execution plan; `implementation-plan.md` describes the historical MVP.
The [readiness gates](release-1.0-readiness.md) remain the release acceptance contract.

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
The agent remains external to Blender; embedded model hosting is an unresolved product decision,
not an assumed requirement or a claim about the current bridge.

## Evidence baseline

- Main has working foundations in every recently requested specialist area, but only subsets.
  Exact contracts are in [artist tools](artist-tools.md); the registry is authoritative.
- Latest baseline CI succeeded; Python tests, lint, type checking and package CI exist.
- Existing isolated smokes cover portions of workflows on Windows Blender 4.5.1/5.1.2.
  They do not prove interactive UI installation, real undo interleaving or artistic quality.
- The manifest's 4.2 minimum is not verified by the local matrix. Test it or explicitly resolve
  supported versions before RC. Do not infer Linux/macOS Blender support from Python CI.
- Published 0.3.0 remains alpha. Do not replace its artifacts, publish 1.0 early, or change
  repository visibility; the user's latest instruction is to keep visibility unchanged.

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
No parallel-agent work is assumed or authorized by this plan.

## Prioritized execution backlog

All items below are open unless matching implementation and evidence are recorded below. “Implemented”
and “accepted for release” are separate states.

| Order / ID | Concrete next deliverable | Acceptance / dependency |
| --- | --- | --- |
| 1 / EVID-01 | Runner and machine-readable results for existing Blender smokes | Both installed versions; timeout/nonzero/missing-success-marker fail; report never labels 1.0 ready |
| 2 / SAFE-01 | Material/shader ownership audit, including node graph edits and forced unlink | Enumerate affected users, explicit shared-scope contract, library/override checks; no damage to protected duplicate; M1 |
| 3 / SAFE-02 | Audit remaining transforms/modifiers/rigs/scene/animation mutators | Per-tool ownership/mode/permission/recovery table with adversarial fixtures, not just a common guard |
| 4 / REC-01 | Verified recovery after partial failure and actual Blender undo | Measure restored state, not merely exception-free rollback; manual undo interleaving and file/session changes invalidate unsafe recovery |
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

Next implementation slice after EVID-01: SAFE-01 + its protected-material fixture, then
REC-01 for recently added multi-step edits. Work in coherent user workflows thereafter,
not an indefinite sequence of unrelated one-tool additions. Reprioritize using failed evidence
or dependency blockers; record why, and retain the unfinished target.

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

Before RC, run the entire claimed matrix from a clean checkout and retain evidence outside
ephemeral CI storage. Build add-on/wheel/plugin from that exact revision, test the packaged
files, verify checksums, and match all component versions. Run a requirement-by-requirement
completion audit against this plan and the readiness gates. Any missing or indirect evidence
keeps 1.0 unready. Privacy stays unchanged. Publication is the final step, not the definition
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
