# Isolated authored-geometry previews

The prospective source adds `preview.geometry_start` and `preview.geometry_image`.
Native and installed-package qualification for these public methods is pending.
The earlier private DTO experiment is separate evidence. Windows remains deferred;
this source profile admits only the exact qualified official Linux Blender 4.5.14
and 5.2.2 builds. No custom Blender build is required.

Start with an explicit Object name, then poll `jobs.inspect` for a terminal result
and retrieve its `preview_id` with `preview.geometry_image`. Blender requires
INSPECT_SCENE, CAPTURE_VIEWPORT and ACCESS_EXTERNAL_FILES. The fixed worker creates
its own scene; it never opens the source project. The source Main, its Render
Result, existing task-plan baseline (when present) and protection are not edited. Starting this external
job deliberately advances the framework's operation/evidence bookkeeping; that
is distinct from changing protected source data. Status and cancel remain usable
while stopped. Pause cancels a running geometry job. A rejected/undelivered start,
disconnect, timeout, lost permission, source/policy change, undo/load or shutdown
prevents publication and triggers owned child termination/reaping and cleanup.
Unknown cleanup is an explicit failure with retained effects.

The preview is a 128x128, eight-sample, single-thread Cycles CPU image with fixed
framing, a new opaque material and transparent background. It shows bounded
**authored geometry**, not evaluated appearance or the current viewport. The named
Object must be a local static Object-mode Mesh, use XYZ rotation and default delta
transforms, and have no parent, animation, modifiers, constraints or shape keys.
Shared and Edit Mode Mesh buffers refuse. The DTO contains complete vertices,
undirected edges, faces and represented XYZ channels. It excludes source materials,
UVs/attributes/custom properties/ID references, children/instances and inactive
rotation channels.
Limits are 512 vertices, 1024 edges, 512 polygons, 2048 corners, 2 MiB DTO/image,
Float32-safe values and the documented prototype magnitude/precision bounds.

A successful image is retained in memory for at most five minutes, with four
preview slots and an 8 MiB PNG limit. Newer previews may evict older handles.
Every retrieval rechecks source identity/content, semantic plan/session identity,
live permissions and stop/lifetime state. Stale handles fail; they are not silently
refreshed. No user output path or overwrite option exists. Private worker files are deleted only after the process is reaped and ownership checks pass. These
files and the cache are temporary resources, not project saves or durable backups.
The MCP method returns actual image content without reading an arbitrary path.

Parent source-capture/launch intervals, worker timings and worker self peak RSS
are distinct evidence. Missing OS-launch/parent-native measurements are explicitly
unqualified. Individual native-call blocking intervals are unmeasured; worker render/validation
wall time includes Python and native work. Parent launch wall time covers only
Popen return, excluding child initialization and rendering.
The worker reports Linux RUSAGE_SELF ru_maxrss in KiB, a process peak
rather than an operation delta. Native work is isolated in a process; no universal
preemption, crash containment or real-time guarantee is claimed.

Full hidden-state/unsynchronized Base identity and permission-provider purity are
not inferred from source-only reads or a matching PNG. The registered acceptance
fixture must establish real task-plan enforcement and pending hidden selection /
dirty unrelated animation before the public entry, then measure declared source
fields without adopting a changed baseline. Broader callback/provider effects
remain unqualified outside direct evidence. Existing protected `viewport.capture`
and `project.save` refusals remain unchanged. This geometry profile does not close
material, animation, cinematic, delivery, H02/F01 or 1.0 acceptance requirements.

The registered fixture records whether a protected-data baseline is actually
present. Real enforcement can exist with `baseline: null`; unchanged identity of
that null slot does not prove that a populated protected-data snapshot was taken.
Its independent before/after projection covers target topology/represented raw
transforms, protected Object channels/raw visibility, Action keys/handles/identity/
bindings and known material/USER-reference identities. It does not use synchronizing
getters after creating the pending Base state or claim complete hidden storage.

The first registered native attempt on both pinned builds stopped during real
`task.plan.enforce`, before any geometry-preview entry: newly linked fixture
Objects had not yet been materialized in the ViewLayer. That failed evidence is
retained separately. The corrected fixture updates its owned ViewLayer during
initial setup, before plan references, dirty-animation setup and pending hidden
selection. It performs no ViewLayer update after establishing that pending state.
The correction is not a passing native result; qualification remains pending.

Resource effects remain bounded when cleanup cannot be proved: the manager
retains at most four unresolved staging resources and refuses another worker
while an owned child remains unreaped. Subsequent authorized starts retry only
these exact retained resources; unknown entries remain retained. This is ordinary
process/directory ownership with race detection, not isolation against arbitrary
same-user filesystem interference or host process death.
