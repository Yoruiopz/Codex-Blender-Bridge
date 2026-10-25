# Bounded direct UV edits

This contract applies only to `uv.coordinates_set`, `uv.transform` and `uv.pin`.
The guard is included in published 0.5.0 and implements a conditional, partial,
material-free profile. Its [selected native evidence](releases/0.5.0.md#verified-evidence)
applies to that exact source; later source requires separate qualification. It does not qualify the remaining UV operators,
UV layer lifecycle, full F02/REC-01 workflows, Windows or release 1.0.

The public arguments, `uv` toolset and Blender-authoritative `EDIT_MESH`
permission remain the same. These are standalone calls: guarded UV children are
refused by `batch.plan` and `batch.execute` before child providers, capture or
checkpoint work. A batch-specific pre-provider capture design is separate work.
The guard adds no protected-scope resolver; existing refusal while artist
protection is armed remains in force.

## Admitted profile

Admission requires one explicitly named active local editable non-override
single-user Mesh in single-object Edit Mode, the same local editable Scene/view layer, a qualified live edit
session, and the explicitly named existing UV map. Selection references still
identify mesh-face scope; they do not lock UV values or create UV Editor scope.
The guard must retain complete supported authored state and reviewed incoming
Object/Mesh consumers. Unsupported ownership, dependencies, storage, native
descriptors or incomplete evidence refuse rather than being omitted.
The initial profile is material-free. Complete authored material/dependency
preservation is not qualified here; a material-bound target is refused rather
than stripped or accepted using only binding names.

The complete target mesh must fit all of these ceilings, even when the request
selects only a small subset:

| Boundary | Initial implementation |
| --- | --- |
| Native topology | 1–512 total corners; at most 512 vertices, 512 faces and 1,024 edges; current consecutive native indices |
| UV storage | 1–8 existing maps, at most 4,096 map/corner records, complete physical pin buffers and applicable legacy selection buffers |
| Context | One current Scene and single active Edit Mode target; at most 256 current-Scene objects and 200 Scenes for bounded metadata/marker reads |
| Ownership/consumers | 1–8 owning direct Scene leaf Collections with no nested children; incoming Object consumers only that Scene/its owning Collections, at most 16 literal consumers; Mesh consumed only by the target Object |
| Retained native evidence | At most 65,536 counted preservation/UV/reserved-marker values |
| Joint verification | Retained-value count × `(6 × planned field writes + 24 + 2 × marker Scene count)` + 65,536 ≤ 8,388,608; planner UV-value count × `max(1, planned writes)` ≤ 2,097,152 |

All limits apply together; the topology ceiling does not guarantee a request
fits the full-state comparison budget. The target has no material slots, vertex
groups, shape keys, color attributes, parent/children, modifiers, constraints,
Object/Mesh animation or instancing. All exposed BMesh custom-data families are
screened; any nonempty unreviewed family refuses. Mesh attribute metadata is
limited to the admitted UV maps and physical flag buffers. Existing global undo must be
enabled with a positive step count; the guard does not change preferences.
The marker Scene count comes from the complete frozen marker inventory. Every
actual full snapshot and each closed-leaf resolution are charged against the
8,388,608-value runtime budget, and another read requires a full 65,536-value
reservation. Exhaustion produces
a sticky refusal rather than an unbudgeted read or cleanup write.

The bundled `Mesh.cycles` declaration has a separate closed metadata policy for
the source-reviewed builds 4.5.14 (`62c1db4208e8`) and 5.2.2 (`d13f752e3b9c`).
It requires the exact runtime pointer signature and empty `CyclesMeshSettings`
schema. The guard never obtains `mesh.cycles`. On 4.5, bounded ordinary raw
IDProperties retain every stored group value, absence versus empty storage,
and native ghost/presence facts. On 5.2, SYSTEM storage has no reviewed public
raw reader: only a noncreating native presence check proving **no stored group**
is admitted. Any stored group, including ghost/default storage, refuses before
UV payload reads or writes. A normal custom key named `cycles` is not used as a
substitute for SYSTEM evidence. Unknown builds, missing/changed declarations,
added group fields and replaced native presence methods refuse. Factory native
qualification of this policy remains required; populated SYSTEM settings remain
an open preservation requirement.

Descriptor comparisons use Blender's declared metadata API shape. Boolean,
integer and float properties require explicit numeric array-length metadata;
string, enum, pointer and collection properties retain an explicit non-array
tag with no numeric length, without accessing an unavailable `array_length`.
This tag says nothing about physical UV buffers. Missing numeric metadata,
unknown property types and schema changes refuse before value or presence
reads; required UV buffer checks remain separate.

Mesh texture space uses an explicit projection rather than a general primitive
getter loop. The native `use_auto_texspace` Boolean is qualified and read first.
When AUTO is true, `texspace_location` and `texspace_size` are never obtained:
their native getters can calculate and write back texture space. Those vectors,
the automatic cache and hidden texture-space flags are excluded from preservation;
the guard creates no baseline for them. When AUTO is already false, the exact
native ensure short-circuits before calculation, so the public manual vectors
are copied as finite Float32 triples. The guard never changes the AUTO flag,
warms the cache or repairs these values. The flag, projection mode and explicit
omissions are retained in the native comparison; mode or admitted source drift
refuses rather than adopting a new baseline. Results and guarded writer errors
report the initial texture-space profile and explicitly leave automatic-cache
and hidden-state verification false. This material-free scope does not qualify
texture-space preservation for broader material/dependency consumers; F02,
A03 and F04 remain open.

UV selection synchronization must already be disabled. On the modern global
selection path, `BMesh.uv_select_sync_valid` must already be exactly false.
Broader synchronized storage is unsupported. All required physical pin/legacy
selection buffers must exist; missing storage refuses before payload getters,
without creating buffers or synthesizing false. The reader performs no Object
Mode flush, mode change, index repair or implicit layer activation.

Original native UV components must be exact Float32 values. Requested components
and rounded results must be signed zero or have magnitude from `2^-126` through
1,000,000. Requests need not already be exactly representable.
Nonzero subnormal, extreme/nonfinite or otherwise
unqualified storage refuses; invalid user arguments keep their validation error.
Vector pairs are rounded to Float32 before transform arithmetic, as in the
existing implementation; rotation/arithmetic precede final Float32 storage
rounding. Scale about pivot, rotate counterclockwise in radians, then offset.
Rotation is bounded to ±`2π × 1,000` radians. A signed-zero bit difference can
count as an authored coordinate change.
Explicit placement may move a pinned corner without changing its pin;
`respect_pins=true` skips pinned transform corners; pin edits preserve UVs.
Tiled coordinates are allowed within the admitted numeric range.

## One retained intent and exact preservation

Before permission/cancellation providers and automatic checkpointing, capture
bounded plain arguments, exact registered-call identity, scope and supported
authored state. Build one immutable expected plan from that original snapshot.
Later code consumes the same plan; it cannot adopt a changed scene as a new
baseline after a provider or checkpoint callback.

Retained ordinary BMesh/element/loop validity witnesses are checked before any
fresh UV payload is read. UV layers, BMLoopUV wrappers and vectors are resolved
afresh and copied to plain values inside one read. No such payload handle is
cached across providers. A removed/recreated map name or equal map contents do
not establish persistent native layer identity.

Before every owned field write or restoration, finish provider checks, full
native capture and exact expected-prefix comparison before acquiring its UV
target. Then a fresh bounded native leaf resolves the corner/field against the
expected corner, checking schema, physical buffers, exact owned-field bits and
ordinary witnesses. A canonical pure final gate immediately precedes the setter.
No provider, full snapshot or broad RNA getter runs while that UV leaf is held.
The writer clears its local target in `finally`; the resolver clears its layer
before return and both handles on failure. No local target/layer handle remains
for post-write full reads or providers, including exception/traceback paths.
Each snapshot corner-copy helper clears its UV/layer handles in `finally` before
other native getters. Native mesh updates have their own live-authority and
full-state gates.

The leaf's source-reviewed lack of authored side effects applies only to this
profile with complete physical buffers; internal temporary PYPTR allocation purity
remains unqualified. Preserve untouched corners, other supported maps, pins,
native selection/storage roles, geometry, material bindings and the admitted
consumer projection. Absent/unknown optional storage is never defaulted false.
The shared primitive reader intentionally skips other bundled runtime RNA
settings. The Mesh exception retains only the raw/absence facts described above;
it does not qualify general Cycles, UI/runtime settings, evaluated output or
appearance preservation.

Record each attempted owned setter before entering native code. Readback must
match a precomputed original/next state; arbitrary observed values never become
a new expected state. Native update attempts and completion are separate facts.
No-op edits issue no UV/pin setters or unnecessary mesh update, while normal
executor checkpoint/history bookkeeping remains visible.

## Failure, recovery and history

An ordinary failure permits compensation only for fields whose owned writes are
known, while authority and the complete expected state still match. Coordinate
edits never restore untouched pins; pin edits never restore untouched UVs.
Every restoration and its required native update are gated again.

Authority loss, cancellation, pause/stop, manual drift, ownership/session loss or
an unknown setter outcome makes the refusal sticky: **no further native writes**,
including cleanup or a mesh update. Retain the measured partial state and inspect
it before retrying. A returned error is not evidence that nothing changed.
`rollback_verified=true` requires measured equality with the complete original
supported authored state; an incomplete or refused restoration cannot claim it.
Measured checkpoint-marker bookkeeping can remain and is not an authored UV
field to restore. The flag does not certify hidden allocation or global native
runtime restoration.

Guarded writer results/failures carry bounded `kind=uv_mutation` facts, retained
by operation history when provided and valid as well as in the response:
method/target identity, stage, attempted/verified owned fields,
restoration and native-update counters, before/expected/observed digests, and
`execution_started`, `possible_mutation`, `state_known`, `retained_partial`,
`rollback_verified` and `verification_required`. Unknown state has no observed
digest. `restoration_refused` distinguishes authority loss, state drift, unknown
write outcome, invalid native scope and session invalidation. This flat evidence
grants no restoration authority. Existing `INSPECT_SCENE` denial redacts the
description and `recovery_evidence` payload; the surrounding operation record
can still retain `affected_objects` names. These are recorded observations,
not a certificate of the current scene after subsequent manual edits.
Early entry/capture refusals can retain an ordinary executor audit without a
UV writer payload.

The measured normal Edit Mode automatic-checkpoint route stamps a Scene marker
without creating/finalizing a per-operation native undo boundary. Earlier raw
NOOP evidence measured this route; it does not qualify a production UV writer,
native undo, whole-editor recovery or durable restoration. Returning to Object
Mode does not by itself prove that any of those recovery paths are safe.
An in-memory plan or undo history is not a backup. Safe saving remains a separate
open requirement.

## Verification and remaining gates

Independently reinspect the changed authored channels and protected data. Review
matched UV/checker evidence for layout quality; exact stored coordinates alone
do not establish overlap/stretch/density or artistic acceptance. Reinspect scope
after manual edits, topology/map changes, mode transitions, undo or reconnect.

Native research on exact Linux 4.5.14 (`62c1db4208e8`) and 5.2.2 (`d13f752e3b9c`)
measured exposed getter/index effects, four controlled schema changes, ordinary
loop invalidation and an actual registered fixture-only checkpoint NOOP.
Independent host checks retained literal capabilities/nulls and map/selection
continuity. That research does not prove internal temporary PYPTR allocation
purity, a persistent layer UUID, every schema/session path or this new guard.
The integrated guard at source `23d9fc0` added registered success/failure/recovery
fixtures and complete supported map/marker comparisons. Those selected checks
passed in the published `4a45b99` source; [retained evidence](releases/0.5.0.md#verified-evidence)
records the bounded verdict. Later-source native and installed checks remain
required; fixture presence alone establishes no result. Local dispatch cannot prove
transport behavior, native undo, durable recovery or reviewed visual quality.
Windows-specific qualification remains deferred and unverified.

See [UV authoring](uv-authoring.md), [the full implementation checklist](implementation-completion.md)
and [release readiness](release-1.0-readiness.md). The complete artist-workflow
target and all fourteen open release requirements remain unchanged.
