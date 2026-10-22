# Native simulation-cache research

Status: **historical fixture research, retained separately from newer typed tools**.
The research fixture itself adds no public cache API. The cloth follow-up below
strengthens existing cache guards; its tool surface and permissions remain compatible.
The shared image-job scheduler is unchanged by this research. This work does
not complete SIM-01, JOB-01 or the 1.0 acceptance gates.

A separate [bounded rigid-body lifecycle increment](rigid-body-lifecycle.md)
adds stronger same-value reset, ownership, complete sampled playback, conservative
static Main dependency admission and recovery proof. Three typed methods are registered in the development checkout. The
historical results and negative evidence below remain independently identified.

The isolated interactive `simulation_cache_probe` case runs
`scripts/blender_simulation_cache_probe_smoke.py`. Its success marker is
`BLENDER_SIMULATION_CACHE_PROBE_OK `. Every scene, cache and deletion sentinel is owned
by the runner. Detailed RNA inventories, operator parameters, evaluated values, file hashes
and timings are retained in a hashed `simulation-cache-probe.json` referenced by the marker.
The report remains `release_readiness: NOT_ASSESSED`.

## Source-matched development evidence

Final strengthened report: `build/simulation-cache-probe-20261022-6/report.json`, **2/2 passed**:

| Native build, Linux x64 | Hash | Result |
| --- | --- | --- |
| Blender 4.5.14 LTS | `62c1db4208e8` | Passed bounded rigid-body memory and gas disk-cache probes |
| Blender 5.2.2 LTS | `d13f752e3b9c` | Passed the same probes; fluid FREE execution differs |

The run used the repository's native runner under a separate authenticated dummy Xorg
display, with input devices and TCP disabled. No user session was inspected or changed.
No project was explicitly saved in the final probe; Blender's normal `quit.blend` recovery
file stays in the runner's disposable directory. This is dirty-source Linux development
evidence, not installed-package, fresh-process, Windows 11 or artistic acceptance.

Earlier experiments remain separate evidence:

- Run 1 failed when FREE followed by BAKE retained the earlier motion after a gravity edit.
- Run 2 reached a native SIGSEGV on both builds during rigid-body disk-cache setup after an
  owned project save. The failing line assigned
  `cache.use_disk_cache, cache.use_library_path = True, False`. The individual crashing
  setter was not isolated. Crash receipts remain under each result's
  `simulation_cache_probe-temp/owned-rigid-cache.crash.txt`. This path was removed from
  subsequent probes and was not repeated. **Rigid-body disk caching remains unproven.**
- Runs 3 and 4 passed forward-evaluation checks and the fluid lifecycle, but those checks
  were insufficient to prove a complete rigid-body bake.
- Run 5 added last-frame-first playback and correctly failed both builds: a bake requested
  at subframe 0.25 reported success while the last frame still showed initial positions.
- Run 6 retains that negative observation, then explicitly invalidates/normalizes the
  fixture and proves correct last-frame-first playback. Earlier passing markers do not
  substitute for this stronger check.

## Rigid-body ownership and native semantics

The cache belongs to `Scene.rigidbody_world.point_cache`, not an individual rigid body.
The fixture's one cache controls two independently positioned active bodies. Their
evaluated world positions are checked at frames 3, 1 and 2, so forward evaluation cannot
silently populate missing frames and conceal an incomplete bake.

`ptcache.bake("EXEC_DEFAULT", bake=True)` and `ptcache.free_bake("EXEC_DEFAULT")`
accept a context `point_cache` override. The cache RNA exposes frame range/step,
`is_baked`, `is_baking`, `is_outdated`, disk/external flags and path/name information.
The override must refer to the exact scene-owned cache; substituting an object name does
not reduce the world-wide affected scope.

Two native behaviors matter:

1. **FREE clears the baked flag rather than establishing deletion or freshness.**
   After a gravity change, the fixture observed `is_outdated=true`; FREE followed by BAKE
   still replayed the earlier motion on both builds. Explicit world-setting invalidation
   and evaluation at the start frame produced the changed result. The fixture uses a
   reviewed native world-setting reset callback for that research step; it does not
   introduce a public promise to change simulation settings silently.
2. **A nonzero caller subframe can produce a false bake-success signal.**
   At frame 1/subframe 0.25, both builds returned FINISHED and set the baked flag, yet
   last-frame-first inspection found no simulated displacement at frame 3. Setting the
   fixture to subframe zero and invalidating the cache before the bake produced complete
   motion. A future tool must explicitly normalize time, restore frame and subframe with
   measured error handling, and verify native cache coverage independently of flags.

The final probe created no files during its memory-cache sequence. It does not prove
disk/external cache writes, cache-directory selection, removal, project persistence,
constraints, collisions, animated inputs, linked/shared worlds or production-scale behavior.
The disk-setup crash is a blocker, not a reason to assume another untested flag combination
is safe.

## Fluid ownership, invalidation and file effects

The proven subset is one local gas domain with one Fluid modifier, an explicit flow
collection containing one geometry smoke source, an explicit empty effector collection,
resolution 16, frames 1–3, MODULAR cache and UNI data files. The native operator is selected
through the active object; it has no named-modifier parameter. The underlying operator
finds the object's first Fluid modifier, so a future wrapper must refuse ambiguous stacks.

The probe measured 54 cache files and complete 4,096-value density grids at every frame.
Changing flow density from 1 to 2 left the already baked data available: shuffled playback
still matched the old density hashes and `has_cache_baked_data` remained true. After an
explicit FREE and rebake, all frame hashes changed and total density increased. A baked
flag therefore does not prove freshness relative to current inputs. A future tool needs
a complete reviewed dependency receipt or must label freshness unassessed.

`fluid.free_data` also removes dependent noise, mesh and particle caches. Both native
builds recursively deleted the owned `config`, `data`, `script`, `noise`, `mesh` and
`particles` children, including arbitrary fixture sentinels inside those directories.
The first FREE removed 60 owned files: the 54 native cache files and six sentinels.
The owned `guiding` sentinel, a root-level sentinel and another cache directory survived.
This proves the tested deletion scope; it does not authorize applying that deletion to
an existing user cache or directory.

The native path validator can create directories and can replace an empty/invalid path
with a default. A wrapper must validate the complete approved path before invoking even
a native FREE operation; an empty path is not a safe no-op. The probe supplies a newly
created absolute path inside its owned runner directory before evaluation or baking.
It never enables Manta script export.

## Completion and cancellation differ by version

| Operation | Blender 4.5.14 | Blender 5.2.2 |
| --- | --- | --- |
| `ptcache.bake` EXEC | Synchronous native call | Synchronous native call |
| `ptcache.free_bake` EXEC | Clears baked bit synchronously | Same observed behavior |
| `fluid.bake_data` EXEC | Synchronous native call | Synchronous native call |
| `fluid.free_data` EXEC | Starts a WM job, returns FINISHED while interface remains locked | Performs FREE synchronously, returns after unlock |

In run 6, the tiny gas bake blocked for about **79 ms / 130 ms** on 4.5/5.2. The first
FREE returned after **0.157 ms**, with the 4.5 interface still locked, and the fixture
observed unlock after **29.451 ms** total. On 5.2 it returned after **47.942 ms** with
the interface already unlocked. These are observations of this tiny workload, not upper
bounds, responsiveness guarantees or a cancellation/deadline contract.

The 4.5 fixture yields to the UI event loop and waits for the owned job's interface unlock
before reading graph/cache state, hashing files or starting the rebake. The private
factory process has no competing jobs. Interface-lock state is global and would not by
itself establish ownership in a user's session. Both builds reject
`bpy.app.is_job_running("OBJECT_SIM_FLUID")` and `"POINTCACHE"`; their public query enum
only includes render/preview, object bake, compositor and shader compilation categories.

The native `fluid.pause_bake` sets the global `G.is_break` flag. It is not an
ownership-specific cancellation handle. The fixture does not call it, press Escape,
cancel unrelated work or manipulate another Blender process. No owner-specific native
cancel behavior has been proven. Native point-cache bake also uses the global break
mechanism internally. A caller deadline/disconnect cannot be advertised as rollback or
as a guarantee that an already-running native bake has stopped.

## Smallest feasible next public contract

Start with bounded **inspection and a non-mutating preview**, then implement a separately
reviewed mutation contract. The existing cloth/cache API and image jobs should not be
reused by renaming their labels.

- A rigid-body preview identifies the exact scene/world/cache, all bodies and constraints,
  ownership and cross-scene consumers, solver settings, complete dependencies, frame range
  and cache state. Initially refuse disk/external caches and unsupported dependencies.
- An eventual memory-bake operation needs explicit whole-world scope, a fingerprinted
  preview, reviewed invalidation, integer-subframe normalization, live gates immediately
  before native work, measured context recovery, and last-frame-first evaluated evidence.
  FREE must describe retained storage and freshness honestly. Do not expose rigid disk
  writes until the native setup crash is understood and a safe lifecycle is proved.
- A fluid preview identifies the exact domain/first modifier, all flows/effectors/guides,
  geometry/animation/settings dependencies and every dependent cache child affected by
  FREE. Begin with the proven small gas subset; liquids, noise/meshing/particles, guiding,
  REPLAY/ALL modes, resumption and large workloads require separate native proof.
- Fluid mutations need a separately approved simulation-cache folder chosen locally,
  exclusive per-operation directory ownership, bounded inventory/hashes and explicit
  write/deletion intent. Texture and asset approvals do not authorize cache deletion.
  Define the permission contract before implementation. Do not overwrite, rename or
  recursively clear an existing user's cache, follow links, or silently adopt a default
  native path. FREE/rebake is destructive disk lifecycle and has no transactional undo.
- Supporting the 4.5 asynchronous FREE path requires a retained exclusive job owner,
  executor interlocks, correct native completion observation and auditable terminal file
  effects. The current shared image scheduler does not establish that contract. Safe
  cancellation, resource limits, deadline/disconnect behavior and lifecycle cleanup remain
  prerequisites; do not promise owner-specific cancellation using global pause.

Before a public mutator, add negative scope/consent tests, changed dependencies and replaced
IDs, canceled callers, pre-existing/shared/symlinked paths, partial native writes, failed
context restoration, repeated FREE/rebake, saved-project reopen and retained-effect history.
Then run source-matched native and installed acceptance on the required platforms. The
unavailable Windows 11 machine remains a release blocker.

## Evidence support and upstream references

`scripts/native_cache_evidence.py` hashes complete owned cache trees within explicit file,
byte and directory budgets; it refuses symlinks/special files and detects same-count content
changes. Its 10 focused tests include refusal/budget cases. It is fixture support, not a
production approved-path guard or protection against hostile filesystem races. Snapshot
collection occurs after the native writer/free job is finished.

Pinned source inspected through GitHub:

- [4.5 fluid operators](https://github.com/blender/blender/blob/v4.5.14/source/blender/editors/physics/physics_fluid.cc)
  and [5.2 fluid operators](https://github.com/blender/blender/blob/v5.2.2/source/blender/editors/physics/physics_fluid.cc):
  active-object/first-modifier resolution, path validation, EXEC/INVOKE behavior and global pause.
- [4.5 point-cache operators](https://github.com/blender/blender/blob/v4.5.14/source/blender/editors/physics/physics_pointcache.cc)
  and [5.2 point-cache operators](https://github.com/blender/blender/blob/v5.2.2/source/blender/editors/physics/physics_pointcache.cc):
  context cache selection, baked-bit FREE and job invocation.
- [4.5 point-cache implementation](https://github.com/blender/blender/blob/v4.5.14/source/blender/blenkernel/intern/pointcache.cc):
  bake frame loop and global break handling.
- [4.5 fluid cache deletion](https://github.com/blender/blender/blob/v4.5.14/source/blender/blenkernel/intern/fluid.cc)
  and [5.2 fluid cache deletion](https://github.com/blender/blender/blob/v5.2.2/source/blender/blenkernel/intern/fluid.cc):
  recursive child-directory removal and dependent cache flags.
- [4.5 rigid-body RNA](https://github.com/blender/blender/blob/v4.5.14/source/blender/makesrna/intern/rna_rigidbody.cc):
  explicit world-setting reset callbacks.

See [protocol cancellation semantics](protocol.md#timeouts-and-cancellation),
[native test isolation](native-testing.md) and [release evidence rules](release-evidence.md).

## Cloth follow-up: preserve observed timing, guard live boundaries

The rigid-body fractional-time result was **not reproduced in the existing public cloth
tool**. In `build/cloth-fractional-baseline-20261022-2/report.json`, both 4.5.14 and 5.2.2
passed matched fresh 16-vertex cloth fixtures: a call from frame 7/subframe 0.25 and an
integer-frame control produced exactly the same frame-3 vertex coordinates, inspected
last-frame first. Both had minimum Z `1.9760749340057373`, with coordinate delta zero.
The original frame/subframe was restored. Cloth time normalization was therefore not added.
Sharing a point-cache operator does not establish that two solvers have the same defect.

The concrete cloth fix concerns previously unchecked live boundaries. `simulation.cache`
now freezes scene/view-layer/project and object/mesh/modifier/cache identities, checks local
single-user mesh ownership, current owning collections and incoming consumers, visibility
and its existing memory-only budget. It rechecks live permissions, pause/stop and cancellation
before each range write, after operator polling immediately before native execution, after
the native call, and before/after compensation. A replacement target, newly shared container,
external consumer or disk-cache switch prevents further writes. This conservatively refuses
scopes that the earlier cache implementation did not establish as safe.

Range recovery only acts after attempted range edits and while the current values still
match the operation's own output; newer ranges are retained. A final gate that changes the
frame prevents overwriting that newer context. Unstarted failures do not introduce range or
frame writes. The primary native error remains separate from measured range/frame recovery;
late permission and cancellation codes remain visible. Successful responses explicitly say
`cache_coverage: NOT_ASSESSED` and require independent verification.

Final strengthened artist report: `build/cloth-cache-guarded-20261022-2/report.json`,
**2/2 passed** on the same native builds. It confirms identical fractional/control cloth
motion and restoration of frame 7.25. A real frame handler revokes EDIT_SCENE during the
native bake: Blender still visits frames 1, 2 and 3, then the bridge reports PERMISSION_DENIED,
retains the baked cache and refuses compensation until consent is restored for an explicit
FREE. This verifies late-effect reporting, not native preemption or transactional rollback.
The original five recovery tests remain, with additional live-denial, replaced/shared scope,
newer-state and unstarted-failure regressions in `tests/test_simulation_recovery.py`.

Frame evaluation can run arbitrary existing Blender handlers and other scene dependencies.
These guards do not sandbox those handlers or certify all external simulation inputs,
cache durability, native undo or complete bake coverage. `cloth_add`/`configure` allocation
and partial-assignment recovery remain separate audit work.
