# Bounded rigid-body evaluation jobs

Status: unreleased development implementation with focused source-matched Linux
native evidence. This increment does not close SIM-01, JOB-01 or the full 1.0
acceptance gates. Earlier timer research and the Scene job kernel have separate
evidence; neither qualifies this public adapter by association.

These jobs evaluate an explicitly named whole rigid-body world over at most 32
integer frames and return measured trajectory summaries. They never call native
BAKE or `bake_from_cache`, set a baked flag, save the project or access external
files. A completed evaluation is not proof of complete hidden cache contents,
future cache freshness, physical correctness or artistic acceptance.

| Method | Required inputs | Authority |
| --- | --- | --- |
| `rigid_body.evaluate_preview` | `scene_name`, complete `body_names`, explicit empty `constraint_names`, `frame_start`, `frame_end` | `INSPECT_SCENE`; no range/reset/frame-set phase |
| `rigid_body.evaluate_job_start` | Identical proposal and `expected_fingerprint` | `INSPECT_SCENE`, `EDIT_SCENE`, `EDIT_ANIMATION`; modifying, nonbatchable |

Both methods accept `time_limit_seconds`, a strict integer from 1 to 300,
defaulting to 60. This job limit is part of the fingerprint: changing it requires
a new preview. Frames are strict integers from 1 to 1,048,574; Blender also
requires an ordered inclusive span of at most 32 frames. Body names must list
every ACTIVE and PASSIVE body exactly once, with 1–16 names. Constraints must be
an explicitly supplied empty list. The preview fingerprint binds the proposal,
native session identities, context, authored inputs and admitted dependencies.
It grants no permission and becomes stale when any measured input changes.

The initial profile retains the restrictions of the
[synchronous rigid-cache lifecycle](rigid-body-lifecycle.md): local editable,
independent single-user static BOX meshes, at most 2,048 total base vertices,
no kinematic bodies, parenting, constraints, modifiers, shape keys, force fields
or frame/dependency-graph handlers. The current world must use an idle unbaked
memory-only step-one cache, 1–4 substeps, 1–8 solver iterations and time scale
0.1–1. The complete bounded Main dependency admission includes unused IDs and
refuses animated, linked, override or unreviewed evaluation inputs.

Execution requires Object Mode, one actual current window/view layer and the
exact current Scene, with flat explicit body/constraint collections. The active
object must already be a plain local Empty without physics. The adapter does not
switch selection, active object or mode to obtain this context. Active task-plan
protection remains refused; these tools do not bypass enforcement or turn an
advisory plan into a preservation guarantee.

The proposal deliberately replaces the cache's configured frame range with the
requested range and resets existing unbaked memory state through the reviewed
same-value time-scale setter. The authored time scale remains unchanged. The
requested range remains on success; caller frame/subframe are separately restored
and verified. A failure can leave either range setter or a later native phase
completed. These effects must be inspected before retrying.

Start returns an acceptance receipt and job ID. Acceptance is not completion.
The first native checkpoint or domain phase starts only after the start response
has been delivered. Use `jobs.inspect` for progress and terminal evidence,
`jobs.list` for retained jobs and `jobs.cancel` for cancellation; bridge status
also reports the active job. The existing runtime permits one shared active job.
The persistent Scene reservation blocks competing mutators and evaluation-producing
inspection while permitting its exact cached status/control allowlist. Status
does not evaluate the world or mint native write authority.

Each main-thread timer turn performs at most one domain phase: one range setter,
reset, frame-set, view-layer update or dependency-graph sampling phase. Individual
Blender calls remain synchronous and nonpreemptible. Live permissions, the
original registered starter/toolset, request handoff, job deadline, checkpoint
ownership and the frozen domain comparison are checked before further work.
An expensive native call can overrun the deadline; a job limit is not a hard
native execution-time or memory bound.

The adapter compares protected inputs, owned values, checkpoint roles and the
frozen baseline through exact canonical digests, preserving distinctions between
`false`, integer zero, floating zero and signed zero. This is a domain-local
comparison contract; shared legacy rigid readers are unchanged and the remaining
per-mutator audit is open. Known context reads in preparation and driver
comparison/publication use the existing diagnostic
`mark_view_layer_sync_possible` before the rigid scope snapshot or active-object
getter. This records possible synchronization; it does not prevent native work
inside every RNA read or instrument all getters.

Successful output contains `matrix_samples_sha256`, `frames_sampled`,
`matrices_sampled` and one `endpoints` entry per body with `body_name`,
`first_matrix`, `last_matrix` and `displacement_xyz`. It reports
`all_requested_integer_frames_sampled` and `caller_time_restored`, with `baked`
and `bake_completed` both false. `cache_coverage`, `cache_freshness` and
`durability` remain `NOT_ASSESSED`. The digest/count covers the full sampled
trajectory; the result contains bounded endpoints rather than every matrix row.
Numeric sampling permits valid static and zero-gravity worlds; nonzero movement
is not a general success rule. Review appearance and physical suitability
independently.

The cached `native_effects` receipt is bounded to 8 KiB. It retains
`counts_by_operation`, `last_entered`, `last_returned`, `last_verified`,
`sample_recorded_count`, `evidence_incomplete` and `snapshot_allocation_failed`;
it contains no full interval-row dump. These are selected declared intervals,
not an inventory of every Blender side effect or proof of hidden cache contents.
The `evaluated_get` interval precedes the coarse `matrix_capture` interval,
which includes the native matrix getter and complete 16-float copy. An allocation
failure during that copy can leave the
interval entered without a recorded return; it does not prove that the getter
never ran or that no native effects occurred. No automatic native retry or
rollback follows an uncertain interval.

Cancellation, timeout, disconnect, permission loss or a changed input stops at
the next safe boundary. Already published frame/range/cache effects remain.
Stopped jobs perform no automatic frame restoration, cache FREE/reset or cleanup.
Their cached terminal/recovery evidence survives ordinary display-history
eviction; unresolved recovery capacity can refuse new work. An owned checkpoint
is not a durable backup, and cache recovery by global undo is not guaranteed.
Use new, separately authorized inspection and existing explicit
`rigid_body.cache_preview` / `rigid_body.cache` FREE or BAKE operations when
appropriate; a recovery request is not continuation of the canceled authority.

Failure to allocate an effect snapshot makes the incomplete-evidence flag sticky,
retains the reservation fence and preserves the first primary error. Subsequent
attempts only finish terminal bookkeeping; they do not resume the driver,
recreate its context, call permission providers or start native work after lost
authority. Evidence allocation failure must not turn uncertain effects into
zero-effect or recovered claims.

Frozen production source `aacb39d70b76d0533473f9fb1d154d75ac8ae605` passes
496 focused and 6,365 full non-Blender tests, with three Windows-only skips, plus
static checks. Its 329 Python source files have fingerprint
`1f086f3dee9bb5cb16b8bf81aa093372be57cd63cafa6ab7e67f1fb258b95eb5`.
Raw portable logs are retained under `build/rigid-evaluation-native-20261023/portable/`.

The opt-in `rigid_evaluation_jobs` fixture passes on Linux Blender 4.5.14 LTS and
5.2.2 LTS. Each build completes two successful three-body/three-frame jobs and
eight early/late stopped jobs: cancellation, permission loss, disconnect and an
authored external edit. Moving and zero-gravity trajectories match the complete
fresh matrix references with maximum error `0.0`. The moving ACTIVE bodies each
fall by `0.028728008270263672`; static motion is valid. The fixture replaces the
default 1–250 range with 5–7, retains the requested range, restores successful
caller time and checks one domain phase per tick. Stopped jobs retain partial
effects without later driver restoration/cleanup; eight retained recovery receipts
cause the next start to refuse at capacity.

The native report is `build/rigid-evaluation-native-20261023/native/report.json`
(SHA-256 `09c902a40549091c2876e57f3733314be1328c27133db97a375edcaccdacd3d3`).
The separate byte/source and detailed-evidence audit is
`build/rigid-evaluation-native-20261023/framing-independent-audit.json`
(SHA-256 `834c76566211a94268789da4f7271632e107437f391fbb69f4147d51827b2b9c`).
At the same frozen source, eight existing composition cases pass on each Linux
build: Scene kernel, painting jobs, artist loop, undo lifecycle, Scene checkpoint
admission, rigid-body scope, evaluation dependencies and exclusive mutation.
Their raw 16-result report is
`build/rigid-evaluation-composition-native-20261023/native/report.json`
(SHA-256 `98243ef00b156a26a7c8b3ae13634c97ed05ddc7deb46fdf92d40f6e6c57c696`).
Its independent source/marker/artifact audit passes and is retained at
`build/rigid-evaluation-composition-native-20261023/framing-independent-audit.json`
(SHA-256 `80beaffa803705e5f4b423bee59e8b41d57d22d4ab1f899c0d95e6ad25dc9adc`).
Both runner reports select only those cases and mark release readiness `NOT_ASSESSED`.

The public fixture uses standard-library TCP to exercise the actual typed public
Blender RPC. Portable official MCP SDK schema and forwarding tests are a separate
route; these results are not native MCP end-to-end evidence. The Blender fixture
uses no external MCP helper or Pydantic dependency. Complete hidden-cache state,
the full 16-body/32-frame limits, broader solver inputs, constrained-memory and
production latency/recovery remain unqualified. Windows and full installed
MCP-to-Blender artist A–F acceptance remain mandatory and open. No project was
saved and no bake was requested or certified.
