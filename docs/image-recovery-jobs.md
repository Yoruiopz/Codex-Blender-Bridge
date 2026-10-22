# Cooperative image snapshots and recovery

**Save availability:** `project.save` currently refuses Save and Save As before
native/path access; see [the safety change](project-save-safety.md). Fresh-process
results below establish feature serialization through owned fixture setup, not a
safe bridge project-save capability. Earlier typed-save reports are historical.

Three typed tools extend current-pixel recovery to ordinary RGBA images up to
4096 x 4096 pixels, with a 288 MiB packed payload limit. The synchronous
`image.pack_version`, `image.restore_pixels`, `image.recovery_preview` and
`image.restore_packed_snapshot` keep their existing 1,048,576-pixel / 20 MiB
limits. The larger tools use the shared image-job scheduler; increasing a
synchronous bound is not the implementation.

| Tool | Result |
| --- | --- |
| `image.snapshot_job_start` | Accept a job that retains complete current pixels in a new raw packed recovery Image, with a native reference to the exact original Image ID. |
| `image.recovery_job_preview` | Inspect the current original, retained snapshot, direct consumers and loaded-versus-unloaded mode; return a fingerprint for this measured state. |
| `image.restore_snapshot_job_start` | Accept recovery against that exact fingerprint, with explicit packed-byte replacement confirmation when reconstruction requires it. |

Enable the materials toolset. Starting jobs requires Inspect Scene and Edit
Materials, Object Mode, and live Access External Files for FILE originals.
Read-only preview requires Inspect Scene and the FILE grant, without Edit
Materials. No tool reads a backing file or automatically saves a project.

Snapshot inputs must already have a complete loaded local FILE or GENERATED
buffer, four channels and a supported ordinary image role. A loaded FILE image
whose backing path has disappeared can still be snapshotted. This stores
**current edited channels**. Use the separate `image.pack_version` FILE_BYTES
contract when the required evidence is **original file bytes**.

Keep the connection that started the job alive and poll `jobs.inspect` until a
terminal state. An accepted start response is not completion. The existing
one-active-job limit, progress revisions, pause, cancel, deadline, disconnect,
native checkpoint and operation history apply. Job deadlines range from 1 to
300 seconds and include input freezing. Private channel validation, encoding
and raw snapshot decoding yield through the main-thread scheduler.
After the final permission source, a separate pure job safe point checks owner
Events, cancellation, the job deadline and current toolset membership. Native
publication additionally rechecks stop/pause flags. It does not call permission
providers again. File staging shares this check before publication; cleanup of
exact owned staging remains separately subject to live grants.

Full native pixel capture, hashing, allocation, pack, decode, pixel publication
and readback can block. Cancellation cannot interrupt those calls. A timer
budget is a cooperative scheduling target, not a real-time or memory guarantee.
The workload exposes a private pixels/payload estimate and explicitly excludes
native/GPU/undo buffers and allocator overhead. Full arrays and encoded payloads
remain in memory: this is not streaming out of core or a resource reservation.

Preview checks complete bounded packed bytes and metadata, the original-ID
reference, native identities, target metadata and current pixels or old packed
bytes, and bounded direct-consumer identities. It intentionally reports
`snapshot_pixels_verified: false`: canonical raw layout, complete finite
channels, digest and exact byte representability are checked privately before
publication. Preview does not certify a successful restoration. Any measured
change requires another preview; names cannot substitute for original IDs.

Loaded restoration writes every channel into the original loaded float or byte
Image ID and preserves its existing packed payload. Unloaded FILE restoration
requires `confirm_replace_packed_bytes: true`, deliberately replaces the
payload with canonical PNG8 or raw EXR, and preserves the original ID, stored
path, color/alpha roles and direct bindings. Unloaded byte roles are sRGB,
Linear Rec.709 or Non-Color with STRAIGHT or CHANNEL_PACKED alpha. Unloaded float
roles are Non-Color with STRAIGHT or CHANNEL_PACKED alpha, and Linear Rec.709
with CHANNEL_PACKED alpha. Associated float color reconstruction is refused;
no conversion is guessed. Unloaded GENERATED images require an explicitly
allocated generated buffer before loaded recovery.

Both workflows recheck frozen evidence after the native checkpoint and before
publication, and compare all restored channels afterward. New consumers of a
new snapshot stop further writes. Recovery observes a bounded list of direct
consumers, not universal transitive dependency preservation. More than one
reference requires `allow_shared: true`; linked direct consumers are rejected.

`recovery_evidence` is separate from filesystem `external_effects`. Terminal
records retain snapshot presence, mode, packed hashes and complete-pixel
verification where observed. Late cancellation, permission loss or native
errors can leave a partial new Image or a written original. The job retains
that evidence and finalizes its checkpoint; it does not blindly overwrite or
delete data to claim rollback. If observation itself fails, the job and its
operation record expose `evidence_observation_unknown`; cached facts may be
stale. Terminal cleanup releases private work and the connection owner even
when evidence or operation recording fails.

A source buffer, private array, fake user or undo history alone is not a backup.
Successful snapshot jobs retain a complete packed payload in Blender memory.
Durability requires a safe separately authorized project save, which remains blocked. Save
again after restoration when the restored result must survive reopening.

The phased interactive native cases `image_recovery_jobs` and
`image_recovery_jobs_large` exercise the public socket/timer lifecycle and a
fresh-process reader using a runner-owned bundle. The large case requires at
least 8 GiB measured Linux cgroup-v2 headroom; this is not constrained-memory
acceptance. Reports retain full digests, native publication times, poll latency,
memory high-water marks and source fingerprints. A lightweight native panel
draw checks recovery-workload keys; it does not establish visual acceptance.
Windows, constrained-memory, crash recovery, reviewed appearance and complete
1.0 artist-workflow qualification remain open.

Development evidence from Linux on 2026-10-22 passed both phased cases on Blender
4.5.14 LTS and 5.2.2 LTS: eight isolated writer/reader processes. The 4K case used
the default 4 ms scheduler budget, 300-second deadline and measured 8 GiB
headroom. It verified a 268,501,384-byte raw packed snapshot, every signed HDR
channel including negative zero, current-session original identity, direct
material binding and fresh-process native original-ID reference. Small cases
cover nine unloaded byte/float color/alpha combinations, native creation undo
with an interleaved manual transform, late permission revocation and sixteen
provider-triggered write-boundary faults per Blender version. The latter use
direct driver boundary injection; the separate real socket jobs exercise
handoff, cancellation, disconnect, deadline, progress and checkpoints.

| Measured 4K operation | Blender 4.5.14 | Blender 5.2.2 |
| --- | ---: | ---: |
| Snapshot job completion | 92.66 s | 98.25 s |
| Loaded restoration completion | 19.52 s | 23.41 s |
| Fresh-process restoration completion | 18.32 s | 24.43 s |
| Longest native publication block | 1.70 s | 6.59 s |
| Writer process peak RSS | 3.19 GiB | 3.27 GiB |
| Reader process peak RSS | 2.55 GiB | 2.40 GiB |

These are development measurements on an AMD EPYC 9V74 host, not a responsiveness
or memory guarantee. A deliberately slower 1 ms budget run reached its
300-second deadline before publication at 90.3% encoding, with no native
execution, checkpoint or retained snapshot. That negative evidence is retained;
neither the public deadline nor the headroom preflight was relaxed. Reports
also retain synchronous acceptance/preview latency, which can exceed one second.
The combined-source clean native matrix and packaged acceptance remain separate
release requirements; source changes after an experiment keep it historical.
