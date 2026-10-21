# Cooperative painting jobs

Unreleased on `main`; not in the downloadable 0.3.0 packages. These are structured,
source-frozen [image brush](texture-painting.md) jobs, not arbitrary scripts, generic
background Blender execution, native bake cancellation or complete JOB-01 acceptance.

## Start, inspect, cancel

Enable `materials` in Blender and MCP. Keep the owning MCP/Blender connection open.

```text
image.paint_job_start(
  image_name="Canvas", new_name="Painted Canvas",
  strokes=[{points:[[0.2,0.2],[0.8,0.8]], radius_pixels:32,
            color:[0.8,0.2,0.05,1], opacity:0.75, hardness:0.8}],
  time_limit_seconds=60
)
jobs.inspect(job_id="<exact returned job_id>")
jobs.list(limit=10)
jobs.cancel(job_id="<exact returned job_id>")
```

The examples are tool-call notation, not Python or commands for Blender's console.
Start returns `accepted=true`, **not a finished painting**. Poll the exact `job_id` until
`terminal=true`. Only `SUCCEEDED` carries the final paint result. Independently inspect the
new image pixels and unchanged source digest, bind the version explicitly, capture its
appearance and compare with the brief/protected scope. No automatic binding or saving occurs.
Do not issue dependent work against the output name before completion and verification.

Optional `mask={image_name:"Mask", channel:"R", invert:false}` adds a frozen raw RGBA channel
with normalized UV pixel-centre bilinear sampling, including different mask/canvas dimensions.
See the [complete mask contract](texture-painting.md#uv-image-channel-masks). Inspect both input
digests after success. FILE masks need live external-file/path consent independently of the
canvas. No color transform/luminance/unpremultiply is applied to the mask channel.
Paint source normalization is separate: reviewed associated linear float input normalizes to
straight color, while new buffers use native CHANNEL_PACKED for independent requested RGBA.
This fixes measured transparent shading across the tested versions; mask and inspector values
remain raw. `source_associated_converted_to_straight` reports source normalization explicitly.

| Tool | Blender permission | Contract |
| --- | --- | --- |
| `image.paint_job_start` | `EDIT_MATERIALS`; FILE sources/masks also need approved-path and `ACCESS_EXTERNAL_FILES` consent | Typed brushes and optional raw-channel mask, up to 16,777,216 pixels/4,096 per axis per image, finite 1–300 second job deadline; sync painting stays <=1M |
| `jobs.inspect` | `INSPECT_SCENE` | State, monotonic revision, phase-local progress, final result or structured failure/recovery evidence |
| `jobs.list` | `INSPECT_SCENE` | 1–32 summaries, newest active then terminal; explicit truncation |
| `jobs.cancel` | No scene-edit grant | Requests internal cancellation, including while paused; does not authorize deletion or promise rollback |

One job may be active globally. The manager retains at most 32 terminal summaries, releasing
all private pixel buffers, generators and Blender handles at termination. IDs/history are
runtime-session-local, not durable storage, ownership locks or proof of current scene state.
Historical results may precede undo/file changes: inspect the current `.blend` again.
Start and job-control calls cannot nest in `batch.execute`. Polling does not displace meaningful
operation history. A start record says accepted/not committed; a separate terminal record
identifies completion, cancellation or failure and the requested image name.

## Scheduling and ownership

All Blender access and painting execution stay on Blender's main thread. Network threads only
set thread-safe ownership/delivery flags. Start validates and copies the bounded loaded source
and strokes. CPU painting does not advance until the success response has been written/flushed
to the owning socket. This is a transport handoff, not an application-level receipt or guarantee
that a remote process is still alive. Disconnect is observed asynchronously.

The normal request queue is serviced before each CPU slice. Blender's sidebar/preferences
provide a **Paint Job CPU Budget (ms)** setting: 1–8 ms, default 4; MCP cannot change it.
This budget is cooperative, not a hard latency ceiling. Work yields approximately every 256
pixels/candidates in mask validation, normalization, coverage, application and comparison. `revision` orders
observations; `completed/total` is local to its phase/stroke, not a global percentage.
The sidebar shows recent jobs, progress, cancellation, errors and possible retained-image warnings.
Minimal `bridge.status.jobs` control summaries do not expose full results or bypass inspection
consent. Detailed diagnostics remain local.

The RPC's deadline governs start handoff; after delivery, the job's own deadline governs work.
Pause holds private work but does not stop that deadline. Explicit cancellation, emergency stop,
owner disconnect, failed/expired delivery, bridge/executor stop, add-on unregister, file load and
native undo/redo stop pending work. Idle socket timeouts preserve incomplete frame bytes while
an active request/job owns the connection; ordinary idle connections still close. No framing,
request-ID, terminal-response or protocol-version semantics change. Progress is polled; no
NDJSON progress events are emitted.

## Guarded commit and recovery

Before allocation, jobs recheck live permissions/toolset/pause/emergency/ownership/deadline,
Object Mode, exact image identity, complete relevant metadata and pixels, approved FILE evidence,
and output-name availability. A mask gets equivalent complete revalidation, including its
non-selected channels. Source/mask changes or name conflicts fail without creating a version.
Metadata comparison excludes only the source's consumer count: adding a read-only consumer does
not change the frozen source. No source locking or overwrite is implied.

The native undo boundary is created **at publication**, not acceptance. Edits completed while
private calculations were pending therefore precede this boundary. A missing boundary refuses
publication; finalization failure never reports success. Context/source validation runs again
after checkpoint setup. Subsequent edits can still be affected by global undo; never treat this
as independent per-object undo. Inspect current recovery availability and explicitly confirm
snapshot restoration; [native history is finite](native-recovery.md), not a durable backup.

Before publication, cancellation releases private work without allocating an image. During native
publication, a stop can be observed only at the next safe point. **CANCELLED does not imply no
scene effects.** Inspect `execution_started`, `possible_mutation`, `rollback_verified`,
`cleanup_permission_denied`, `undo_boundary_created` and `undo_boundary_finalized`.
Removing a failed owned zero-user/non-fake-user allocation requires live `DELETE_OBJECTS`.
Pause during publication stops at the next safe point and fails with `AGENT_PAUSED` rather
than holding a partially created image or falsely reporting success; resume explicitly before
remote confirmed recovery. The same possible-mutation/cleanup evidence applies.
Denied cleanup retains the new image with truthful evidence; explicitly confirmed recovery
or separately consented `image.remove` is needed. Unexpected consumers prevent forced cleanup.

Copying source/native buffers, array allocation, complete final source/file validation, image
creation/update/readback and undo operations are bounded but **not preemptible**. Their time
is outside the CPU-slice target. There is no real-time UI, maximum cancellation-latency or memory-
pressure guarantee. Jobs and canvas creation now support 16,777,216 pixels (4K square),
4,096 per axis. Synchronous paint and default full inspector statistics remain capped at 1M;
explicit `image.inspect_pixels(include_statistics=false)` reads complete large digests/samples
without a range/nonfinite scan. A large digest is complete evidence of stored bytes, not proof
of finite values or artistic correctness. Candidate work remains capped at 2,000,000, using
conservative 64×64 segment bands with maximum per-stroke float64 coverage, at most 32 KiB
coverage scratch and no whole-image normalized baseline. Changed-pixel examples remain in
global row-major order. `workload` and final results expose scoped pixel-buffer estimates,
excluding plan metadata/native/GPU/undo/file/allocator memory; these are not process caps.
This is tile-bounded brush scratch, not out-of-core storage: full frozen source and output
arrays remain. At 4K square those two float32 RGBA arrays alone total 512 MiB.

Use an explicit longer deadline when needed; e.g. `time_limit_seconds=300` for the 4K fixture.
The CPU-slice preference is a responsiveness/work-share choice, not permission to exceed the
job deadline. 8K/UDIM, real memory-pressure and broader production throughput remain mandatory
1.0 work, not an accepted final ceiling. This does not implement surface-projected painting, viewport stencils,
sculpt/vertex/weight brushes, native bake jobs, packing or durable pixel delivery.

## Evidence

The `paint_jobs` native fixture uses actual loopback NDJSON sockets and the runtime timer, not
only manual `tick()` calls. A network-only worker polls while Blender performs CPU slices.
It verifies complete pixel digests, independent numeric samples, protected material/scene state,
matched material captures, and native undo that removes publication while preserving an earlier
interleaved transform. It also tests cancellation, owner disconnect, paused deadline expiry,
permission loss, stale source and post-write denied cleanup followed by confirmed recovery.
Run it through the [non-interrupting test runner](native-testing.md); user projects/preferences
must remain untouched. Unit tests separately cover handoff/write/encoding failures, bounded
retention, main-thread/reentrant cancellation, source identity/mode changes, missing/failing undo
boundaries, schemas, permission separation, batch exclusion and history preservation.

These fixtures prove the documented bounded painting lifecycle, not all JOB-01, full PAINT-01,
full artist capability or release readiness. Broader lifecycle/production/artist gates remain
in the [1.0 plan](plan-1.0.md) and [acceptance ledger](release-1.0-readiness.md).

The `large_paint` fixture adds a real 4096² canvas/job, complete digest-only inspection and
independent numeric samples, explicit material binding, protected-state/capture comparisons,
interleaved-transform-preserving undo and cancellation after observed CPU progress. It probes
the whole isolated process's resident/peak memory rather than substituting array estimates.
On Windows it refuses the test before allocation if less than 8 GiB host RAM is available;
it never forces global memory pressure or opens a visible fallback. This headroom guard is a
test requirement, not a guarantee about all user scenes or an accepted production RAM minimum.
Run with `--case large_paint --timeout 480` through the non-interrupting runner. An actual
native error/insufficient headroom is a failed check, not evidence that the workflow passed.

The `image_masks` fixture extends real socket/timer acceptance to raw channel masks, inversion,
different-resolution bilinear sampling, a mask larger than the synchronous limit, stale-mask and
live FILE-mask consent failures, cancellation and confirmed output recovery. Complete input
preservation is independently checked on success. An externally changed existing mask pixel
survives native output undo: input-pixel rollback is not promised or silently attempted.
