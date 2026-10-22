# Bounded rigid-body lifecycle

Status: **three tools registered in the development checkout, unreleased**. This
increment does not close SIM-01, JOB-01 or any 1.0 acceptance gate. Native evidence
must be recorded separately from the frozen candidate and installed packages.

The cache owner is the current `Scene.rigidbody_world`, including every active
and passive body and every constraint. Naming one body cannot narrow that scope.
The initial memory-only contract rejects constraints, animated inputs, parenting,
modifiers, force fields, shared or linked data, external consumers, disk caches,
and frame/dependency-graph handlers. Those are remaining implementation targets,
not waived requirements.

Frame changes can evaluate scripted drivers on materials, worlds and nested node
groups even when body inputs are static and bridge Python execution is disabled.
Admission therefore inventories every native Main ID family, including unused
data, and rejects any `animation_data`, linked or override ID, or noneditable ID.
It separately inventories all Scene,
Material, World, Light and line-style node-tree bindings, standalone node groups
and nested groups. Only reviewed canonical built-in RNA classes and non-runtime
property descriptors are read. Custom nodes, unknown dependencies, nonempty
sequencers, recursive groups and unreviewed socket kinds are refused before any
owned frame/cache write. Socket default values and evaluated getters are not read
during admission. This conservative profile can reject an unused animated
material or linked data unrelated to the current Scene; it is not a sandbox for the Blender
host process or proof of full shader/material preservation.

The aggregate limits are 512 Main IDs, 96 graph owners, 64 standalone/embedded
node trees, 1,024 nodes, 4,096 links, 512 interface items and eight group edges.
Per-tree limits are 256 nodes, 1,024 links and 128 interface items. The session
fingerprint includes the inventory, bindings and topology. Every later write
rechecks them, so newly added drivers or changed dependencies invalidate the
proposal before reset, frame evaluation or native cache execution.

The generic structural comparisons have their own descriptor-only preflight.
It closes Object, Mesh, world/collection settings, mesh elements, custom
attribute values, vertex groups, memberships and material-slot records before
the first generic getter is read. Unknown writable runtime RNA properties are
refused, including properties added after the preview or by a live provider.
The bundled `Object.active_selection_set` UI index is the sole exception:
its exact scalar integer/default-zero descriptor and absent raw storage are
checked, and the later Object comparison excludes it without invoking its
getter. It does not affect independent Mesh rigid bodies. This exception is
an internal literal; callers cannot supply excluded property names. Unexpected
stored UI state or descriptor changes require a broader reviewed profile.

## Registered interfaces

All names below use the `simulation` toolset. No file access, project saving or
arbitrary Python is involved.

| Method | Inputs | Permission and behavior |
| --- | --- | --- |
| `rigid_body.inspect` | Exact current `scene_name` | `INSPECT_SCENE`; bounded world/body/constraint/cache inventory; reports unsupported scope explicitly |
| `rigid_body.cache_preview` | `scene_name`, `operation`, explicit complete `body_names`, explicit complete `constraint_names`, optional BAKE `frame_start`/`frame_end` | `INSPECT_SCENE`; requires complete supported scope; returns a session-only fingerprint binding the proposed operation, range, context, identities, dependencies and authored content |
| `rigid_body.cache` | Same proposal plus `expected_fingerprint` | `INSPECT_SCENE`, `EDIT_SCENE`, `EDIT_ANIMATION`; nonbatchable; checks the exact preview again before mutation |

`operation` is `BAKE`, `FREE` or `INVALIDATE`. The initial bounds are 16 bodies,
2,048 total base vertices, 32 integer frames, four substeps and eight solver
iterations. BAKE refuses an already baked cache. FREE clears the native baked
flag; it does not claim memory deletion, freshness, undo recovery or durability.
INVALIDATE invokes the independently proven native reset callback while keeping
the authored time scale unchanged, then evaluates the integer start frame.

Setup requires separate native proof of exact allocation, ownership and cleanup
before adding `setup_preview`/`setup`. Initial removal research failed exact
authored-state restoration on both builds; report
`build/next3-rigid-setup-20261022-1/report.json` and its source fixture under
`build/rigid-setup-research-pending/` remain negative evidence. That unfinished
fixture is outside the registered cache increment. A cache API alone does not
complete the rigid-body authoring workflow.

## Verification and recovery

BAKE first resets and computes an unbaked sequential reference at every requested
integer frame for every body. It resets again, performs the bounded native bake,
then samples every full evaluated 4×4 body matrix starting with the last frame.
Every sample must match the separately computed reference. `FINISHED`,
`is_baked`, cache information strings and visible displacement are insufficient
on their own. These checks establish numeric playback against fresh native
evaluation; they do not establish physical correctness or artistic acceptance.

Every write, compensation and native invocation rechecks live permissions,
toolset, owner lifetime, pause/stop and exact compare-and-swap state. Providers run
before the final pure checks. A newer manual edit, expired owner or revoked
authority stops further edits, including compensation. Changes from frame
handlers are rejected at preflight rather than treated as owned publication.

The caller's frame and subframe are independently restored and measured. An
otherwise successful bake with failed context restoration is an operation
failure. Recovery evidence distinguishes range, time scale, frame context and
cache effects. A retained native cache, RNA snapshot or undo step is not a durable
backup. No cache FREE is attempted as an implicit rollback of a failed bake.

The terminal check runs again after potentially expensive native scope/content
reads. It uses only request/job ownership Events and deadlines plus local
toolset/pause/stop state; it does not call live permission or generic cancellation
providers after that comparison. The runtime supplies the canonical queue's
pure final request hook, independently of its earlier cooperative callback.

Each native bake, frame evaluation and invalidation interval is timed. These are
synchronous main-thread tails: cancellation is checked at boundaries and cannot
preempt a running Blender call. No progress percentage or owner-specific native
cancellation is fabricated. Long fluid/GN jobs still need an explicit global
mutator interlock and authoritative ownership/completion/cancellation design.

## Remaining solver and cache work

The rigid disk-cache setup crash on both reviewed native versions remains negative
evidence. Disk flags are not retried in this increment. Persistent project and
cache delivery, collisions and constraints, animated inputs, broader dependency
closure, large scenes and Windows qualification remain mandatory open work.
Fluid FREE's asynchronous global UI lock and lack of a public owner-job query
remain blockers to a truthful typed fluid lifecycle. Global pause/cancel operators
are not substitutes for an owned job handle.

## Earlier source-matched development evidence

The isolated runner's opt-in `rigid_lifecycle_probe` research fixture uses fresh
writer and reader processes. Earlier combined research/product report
`build/next3-rigid-native-20261022-18/report.json` passes on Linux x64 Blender
4.5.14 LTS (`62c1db4208e8`) and 5.2.2 LTS (`d13f752e3b9c`). The strengthened fixture
retains both fractional-time false success and stale FREE/BAKE observations,
then proves same-value reset and toggle/restore against independent control
Scenes. The same-value reset preserves authored time scale 0.75, and complete
unbaked-reference/baked-playback matrix error is 0 at all three frames for all
three bodies. The earlier failure reports remain separate negative evidence.

The fresh reader starts from saved frame 1 and samples frames 3, 1 and 2. This tiny
project retains all three memory-cache frames and exact evaluated playback after
reopen. Its native `is_outdated` flag becomes true despite matching motion.
Neither that flag nor this one fixture establishes general cache durability.

Earlier typed product report, before the evaluation-dependency follow-up,
`build/next3-rigid-native-20261022-18/report.json` passes both native versions
using the registered add-on runtime, executor, native checkpoint/history and
permission services. Source state is dirty base
`790586ce50836a9303f4191a98788e958a7ee362`; the 269-file source fingerprint is
`db99782512d03d27fc876d7dfe6c10654d6a0675fb3ffceaa8ce8998604a1197`.
The runner retains individual source hashes and all native logs and responses.
Product smoke SHA256 is
`af1215dd980b5412e7d356bf91deaee0ccc3b2f0094e9d37acf488688d569ca1`.

The product fixture covers inspect/preview/BAKE/FREE/INVALIDATE, changed-gravity
rebaking, all matrix components and bodies, exact frame 7.25 and actual active
selection preservation. Ownership rejection covers omitted passive bodies,
duplicates, cross-Scene body/constraint collections, collection instances,
external Object consumers, unexplained WindowManager Scene references,
parenting, handlers and protected mesh edits. Native user counters are measured
separately: the one Scene holds root, world and ViewLayer references to each
world collection, giving `Scene.user_of_id(collection)=3` while native users=2.
Shared and instanced consumers fail the combined ownership proof.

Actual registered-runtime tests additionally found a native checkpoint detail:
`undo_push` exposes one Scene loopback through its read-only `original` pointer,
while the native pointer/session UID remain the same, `is_evaluated=false`,
`use_extra_user=true` and real Scene users stay 1. Only that exact one-reference
native combination is normalized from the fingerprint. The actual current
WindowManager must remain the sole external Scene consumer with one reference;
other Scenes and additional WindowManager ID-property references are rejected.

Live denial, pause, stop, cancellation and toolset disable retain possible
effects and refuse compensation. Real owner disconnect/undelivered expiry and
pure scheduler cancellation/deadline are also revoked inside the live permission
provider, then caught before native BAKE. An injected failure after native BAKE
preserves the primary error and retained baked cache; authorized, exact-state
frame recovery is verified independently. These tests measure boundary behavior,
not interruption of a running C call.

Four canonical queued-request cases run through the real executor's pure final
hook: cancellation and expiry each occur after the complete pre-write comparison
and after the first owned range publication. All return TIMEOUT before native
BAKE, report whether an owned write started, and refuse compensation after owner
loss. The fixture requires this hook and fails closed if it is unavailable.
Preflight, scope comparisons, publication readbacks, reset setters, frame
evaluations and native cache calls are timed separately. The retained 48 focused
Python tests include stale previews, incomplete matrix playback, recovery
failures, provider side effects, final queue/job deadlines and strict MCP schemas.

That original 13-file freeze and receipt remain separately retained under
`build/next3-rigid-validation-20261022-final/`, including an archive of the exact
owned source bytes. Those results do not validate the later dependency changes.

## Evaluation-dependency follow-up

`rigid_evaluation_dependencies` uses harmless native driver-namespace counters
to prove that frame evaluation runs Material, nested shader-group, World,
World-tree and compositor drivers on both reviewed versions. Each corresponding
preview/cache admission denial, plus a late-provider driver injection, must leave
the counters, cache, context and handlers unchanged, with no owned write or
native evaluation. A custom-node getter control establishes the getter works,
then verifies admission rejects its class without calling it. Blender 5.2's
`BlendData.all_ids` alias is accepted only when its pointer set exactly equals the
reviewed concrete Main-family union.

The 49 additional Python cases cover unused animation/nonlocal owners, nested groups,
cycles, exact depth limits, aggregate budgets, runtime/custom getter refusal,
version-specific compositor bindings and newly introduced animation or data
references during the live provider call. Earlier failed native attempts remain
negative evidence for the corrected empty-sequencer, interface descriptor and
5.2 aggregate-alias handling.

Final follow-up report
`build/next3-rigid-evaluation-20261022-5/report.json` passes all three cases on
both native builds (6/6), including the registered runtime/queue/history fixture
and fresh writer/reader lifecycle fixture. The 271-file source fingerprint is
`518f45c9cc2994b0c0321010a77e29622452e0984b8c8e44c343e07b7dd26d3c`
on dirty base `790586ce50836a9303f4191a98788e958a7ee362`. Dependency-fixture
SHA256 is
`86ac6bf778ba2035343574cbc0266798cf54a7befd9f6838783c0b3f9a31d687`;
the revised product-fixture SHA256 is
`0225c89c760873ac2d301a94614764962214b4fe21fa0aa8ba70e397bd6611d6`.
The original product fixture remains archived with its earlier receipt.
MCP SDK 2.0.0 and 2.2.0 each pass 3,876 tests with three Windows-only skips;
Ruff, MCP typing, generated inventory and whitespace checks pass. The exact
16-file owned freeze, source map, reports and test-log hashes are retained in
`build/next3-rigid-evaluation-validation-20261022-final2/source-freeze-receipt.json`.

The development tests do not qualify Windows, installed artifacts, large or
constrained-memory workloads, native undo interleaving or reviewed appearance.
Those remain release requirements. The add-on registration, MCP simulation lazy
loader, static wrappers and generated inventory include these three methods. The
simulation toolset remains disabled by default. The published 0.3.0 release is
unchanged.

## Generic-getter follow-up

Review of the 16-file freeze found that generic RNA comparisons could invoke a
writable runtime property's Python getter before admission completed. The
rigid-only descriptor preflight now closes that separate traversal before the
first generic Object, Mesh or settings snapshot. Direct identity and transform
channel descriptors are checked too, including readonly fields. Blender's
bundled computed `users_collection` and `users_scene` properties remain trusted
host APIs; the bridge does not claim to sandbox modifications to Blender's
Python process.

`rigid_runtime_getters` registers actual writable getter/setter properties on
Object, Mesh and Collection. Both native versions prove inspect-only preview,
execution and late-provider registration are rejected with zero getter calls,
zero owned write entries and preserved geometry, context, cache and handlers.
An explicit read proves each getter works. Blender does not admit runtime RNA
registration on the eleven other probed Struct classes; those limitations are
recorded rather than counted as native successes. Unit fixtures exercise their
nested descriptor guards, including attribute values, memberships and slots.

A separate writable getter/setter control replaces the bundled
`active_selection_set` UI field with the same admitted descriptor. Preview and a
real INVALIDATE operation leave its counter unchanged, while an explicit read
increments it. Stored raw zero and a mismatched float descriptor are refused.

Report `build/rigid-getter-fix-20261022-6/report.json` passes all four selected
cases on both Linux builds: getter admission, the registered runtime/queue
fixture, evaluation dependencies and the fresh-process lifecycle probe. Its
273-file source fingerprint is
`d9317aadae9345619912704152ecd8806821e47019c8daeb40bf2940bb942ee3`.
The reports from earlier attempts remain separate, including corrections to
getter-only readonly test properties and the inapplicable RNA requirement for
the bundled Python `users_collection` property. This is bounded development
evidence; setup authoring, installed qualification and Windows remain open.
