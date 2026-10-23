# Scene job kernel development fixture

Status: internal scheduling integration. Source `ff8b0f0` passed the five-scenario
fixture on both Linux development builds; see the
[2026-10-23 source/report checkpoint](artist-workflow-checkpoint-20261023.md).
This adds no public rigid-body job tool and does not close SIM-01,
JOB-01, whole-project recovery or full 1.0 acceptance.

The runtime now uses `SceneJobs`, preserving the `PaintJobs` image adapter and
single active-job controller. Its one additional Blender registry entry,
`jobs._scene_turn`, is local-only, nonbatchable and absent from the MCP registry.
It cannot be invoked through a local recovery flag or a copied context receipt:
the scheduler issues a fresh turn under a caller-local origin before any context
factory or provider. Structured callbacks cannot create that origin or release
the reservation. Actual work also requires the original delivered start handoff.

Start admission freezes authored driver inputs, the exact allowed status/control
specifications and the existing Scene marker inventory before providers. The
pending checkpoint claim is metadata only and refuses existing pending/editor
work. A caller-local start nonce can abort only untouched acceptance metadata;
it is burned when the job becomes active. Every later turn proves the exact
reservation, pending handle, runtime epoch and marker inventory. Marker witnesses
advance only by the checkpoint manager's planned marker writes, and weak native
roles advance only after authenticated canonical pushes. The push consumer and
invocation permit never survive a turn.

The accepted starter's exact ToolSpec, method, toolset and declared permissions
are retained before its driver factory or providers. The immutable admission
adds the driver's required grants; it cannot omit the starter's grants. Each
check-only turn, domain phase, checkpoint write and native-completion role hook
rechecks the original spec identity and domain enablement. Replacing the starter
with a same-name spec or disabling only its original domain stops the job even
though the internal turn method belongs to `core`.

Actual Scene-turn permission reads use the original PermissionManager and source
identity and a coherent union of the accepted grants, including helper subset
requests and registry preflight. Allowed nested readonly calls keep their own
permission requirements. Their coherent snapshots, including reads through a
fresh runtime context, retain any denied owner grant for the outer turn's next
pure safe point. A later positive snapshot cannot clear that denial. This adds
no provider call after the final proof and no new authority to a context receipt.
Between-turn status/control and the ordinary image adapter keep their existing
permission path.

Scene jobs run at most one checkpoint or domain phase per tick. Their fixed
budget does not call the image preference provider. Paused and undelivered jobs
still check consent under a fresh synchronous lease without entering a handler
or creating a native-push consumer. Evaluation-producing readonly tools are
blocked while reserved; only frozen status/control entries may interleave.

Stopped jobs retain measured marker/push counts even if BEFORE never returns.
They abandon only exact owned metadata after their turn unwinds, then retain a
cached receipt before releasing the reservation. No stopped driver cleanup,
context restore or AFTER push runs. The bounded unresolved-receipt ledger is
independent of the 32-entry terminal history and remains discoverable through
`jobs.inspect`/`jobs.list`; capacity exhaustion refuses new Scene jobs. History
failure preserves the primary denial. Ledger failure leaves the active owner
fenced. Successful terminal jobs release their driver/native references. These
receipts do not certify that a native cache or undo target is recoverable.

Context-factory failure inside an owned Scene tick uses the same terminal path,
including measured earlier checkpoint facts; a second failure while recording
history is annotated without replacing the first error. Failure to enter the
scheduler scope itself (reentry or lost exact owner) intentionally retains the
fence before context creation or native work. Inspection remains cached; this
increment supplies no authority to repair a lost owner record automatically.

Driver progress and result handoffs accept bounded plain JSON values only:
progress is limited to 8 KiB/512 items and results to 64 KiB/4,096 items, with
finite numbers and bounded nesting/strings. Native objects, cycles and oversized
reports fail after retaining possible-work/checkpoint facts. Inspector results
are detached copies. Terminal error context has its own 16 KiB bound; invalid
context retains the error code with an explicit incomplete-evidence flag.

The first terminal intent is latched. Failed ledger or retirement allocation
keeps the active reservation; later turns retry metadata finalization without
context capture, domain phases, cleanup or another operation-history attempt.
Literal completed-push counts advance immediately after native `FINISHED`, before
fallible undo-window bookkeeping. Failure there retains the completed count but
does not authenticate a weak-role completion callback.

The opt-in interactive `scene_job_kernel` runner case uses a new factory-process
Scene with the existing three-body, three-frame rigid-body benchmark. A socket
worker owns JSON and TCP only. Blender access, fixture controls and job phases
run on the main thread through the existing runtime executor.

The fixture requires a delivered start response before that job's checkpoint or
Scene writes, one domain phase per actual scheduler tick with the kernel's
constant four millisecond slice, independent `jobs.inspect`/`bridge.status` polls,
and rejection of
foreign mutation and evaluation-capable inspection before their providers or
handlers run. It observes the actual pending checkpoint marker across domain
phases. The driver freezes the existing bounded rigid-body authored scope before
providers and delegates only source-reviewed native checkpoint weak-role updates
to the existing `roles.Plan`; it never rebases protected state from readback.

One successful job resets and evaluates all three integer frames, compares every
body's complete matrix with the existing synchronous typed BAKE control, requires
nonzero falling motion, and restores the caller's fractional frame and active
context. This job performs evaluation only and does not claim a bake.
Scene construction and the separately retained synchronous reference control run
as explicit fixture setup before the socket scenario begins.

Four later jobs stop after the frame-2 setter: explicit cancellation, revoked
animation consent, owner disconnect and an authored external edit. Each requires
unchanged domain/native-call and undo-push counts after the stop and after later
polls. The partial frame remains explicit; the stopped owner performs no context
restoration, AFTER snapshot or native cleanup. The kernel may detach only its
exact pending metadata and retain the abandoned receipt in its ledger. Fresh
fixture actions reset caller time between finished owners and after the last
case; those actions are recorded separately and are not old-owner recovery.

The fixture pauses through its main-thread observer only after each actual job
tick returns. Its worker requests each next turn through an event/queue control,
so phase observation does not depend on TCP latency. This is a deterministic
integration test, not a throughput or unattended scheduling benchmark.
The image budget callback deliberately raises if touched during the Scene
scenario; success requires zero calls. Scene scheduling therefore exercises its
constant budget and one-phase cap without consulting image configuration.

Run only through `scripts/run_blender_checks.py --case scene_job_kernel` with an
explicit Blender executable and a new output directory. Follow
[native test isolation](native-testing.md), including the private non-input
desktop requirement on Windows. The fixture writes detailed evidence only in
the runner-owned temporary directory. The bounded success marker references
that file by SHA-256; an exit without that marker is not a pass. Progress and
failure evidence retain measured phase data; only the terminal evidence,
matching success marker and successful process exit establish completion.

Individual native evaluation, evidence and undo calls remain nonpreemptible.
The fixture does not establish a latency or memory ceiling, native cache-content
coverage, disk-cache durability, project saving, general simulation support,
installed-package acceptance or Windows qualification. A native process's
disposable exit recovery file is not a bridge project save or durable backup.
