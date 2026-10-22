# Rigid-body CREATE_NEW research

Status: **native research only; no setup tool or schema added**. This does not
close SIM-01, JOB-01 or a release acceptance gate. Existing cache interfaces and
permissions remain unchanged. The earlier failed setup/removal evidence remains
under `build/next3-rigid-setup-20261022-{1,2}/`. Its removal/restoration behavior
remains negative evidence. This experiment does not establish restoration of
pre-existing physics.

## Bounded contract for further review

The candidate operation creates physics in the exact current Scene, in Object
Mode and one actual current view layer. It requires no existing rigid world and
no rigid-body or rigid-body-constraint settings anywhere in that Scene. The
complete body list is explicit: 1–16 static independent local, editable,
single-user Mesh objects, at most 2,048 base vertices in total. Parenting,
animation, modifiers, constraints, shape keys, linked/override data and
unreviewed consumers remain outside this initial profile.

Reuse an explicitly named flat body collection and explicitly named empty
constraint collection, both direct children of the Scene root. The body
collection's exact membership must equal the requested body list; every body
belongs only to it and this Scene. No objects are moved between collections and
no pre-existing physics is replaced. Native Object/Mesh/Collection identity,
authored transforms in every rotation representation, mesh/custom data and
material bindings must be preserved.

The conservative Main dependency profile and descriptor checks remain required,
including unused animation owners, runtime/custom getters, aggregate budgets
and known handlers. The current `_rigid_snapshot_scope.preflight` assumes a world
and body settings exist. A future implementation needs a separate absent-physics
preflight; passing `None` through the existing helper or fabricating physics
placeholders is not a valid admission proof.

This experiment creates a fresh world, records its defaults, then explicitly
sets time scale 0.75, one substep, four iterations and a three-frame memory range
before binding bodies. It assigns two ACTIVE and one PASSIVE BOX body. These
numbers define this fixture, not a proposed public schema or unrestricted
solver guarantee. A future preview must disclose every requested/default setting
and every automatic allocation, including transient default body settings.

## Native allocation and cleanup findings

Both reviewed versions exhibit the same important callbacks:

1. `rigidbody.world_add` creates a world with both collection pointers unset.
   Native defaults are time scale 1, ten substeps and ten solver iterations.
2. Assigning a populated collection to `world.collection` immediately creates
   ACTIVE/CONVEX_HULL physics settings on **all** member objects. Explicit
   `object_add` is not the only allocator. Its subsequent calls retain the
   allocated settings pointer and can change the requested ACTIVE/PASSIVE role.
3. Removing a body while its collection remains bound unlinks that membership.
   Relinking it to the still-bound collection recreates default physics. The
   first naive reverse-body rollback is retained as failed research, even though
   the starting objects had no physics.
4. The measured successful cleanup first clears `world.constraints`, then
   `world.collection`, removes the fresh world, and finally removes every body
   setting created by the populated binding. No relink or transform/mesh
   compensation is needed in that order. Each call remains a separate owned
   write with a separate live boundary.

The existing collection counters change independently as follows on both builds:

| State | Native `collection.users` | Sole Scene `user_of_id(collection)` |
| --- | --- | --- |
| Direct root child before world binding | 1 | 2 |
| Bound to the fresh world | 2 | 3 |
| Pointer cleared, and after complete cleanup | 1 | 2 |

No Object, Mesh, Scene, Collection or Material ID appears during setup or cleanup.
The measured Object/Mesh/Scene/Collection/Material identities and body/collection
memberships, users and consumers remain identical. These checks cover the bodies,
a protected nonbody Mesh, named and root collections, Scene top-level writable
RNA and shared Material scalar/custom properties and bindings; they do not
establish preservation of every Main ID's contents or user counts. The isolated setup-success cases also pass the existing complete
cache-scope admission with the resulting world and bodies. This admission is not
a bake, motion, collision or artistic acceptance test. Those fixtures create a
new Scene; ordinary factory-startup compatibility is measured separately below.

The 15 cases per native version include success at frame 7.25 and frame 1,
failures after world creation, each binding, body creation/settings, detachment,
world removal and body removal, plus four cancellation controls. Every authorized
completed recovery exactly restores the authored scope and context. The fixture
uses nontrivial Euler, quaternion, axis-angle and delta channels, custom object
properties, Mesh attributes and nonempty shared Material bindings. The physically
active/selected sentinel is a protected Mesh outside the body collection, so an
operator ignoring its declared override cannot hide behind an Empty sentinel.
No transform or geometry restoration setter was
used. Every individual call immediately asserts protected authored state,
identity, membership, consumers and context before publishing its measured
physics-only outputs.

Blender 4.5 refreshes previously stale derived matrices/dimensions during world
creation despite preflight view-layer/depsgraph updates: 85 read-only component
differences remain after cleanup, with no raw channel or authored-data changes.
These differences are retained separately and are not labeled exact full-state
recovery. Blender 5.2 restores the entire captured snapshot exactly. Derived
evaluation caches are not authored transform backups.

The cancellation controls are **research-harness boundary checks**. They prove
zero later writes under that canceled harness owner and retain the exact partial
world/body state. A separately identified fresh harness owner then verifies
cleanup. They do not qualify the production request queue, consent providers,
native interruption, native undo or durable recovery. A typed implementation
still needs the canonical final request/lifetime gates, per-call protection,
provider-side-change tests and truthful retained-effect responses.

## Source-matched evidence

Final report: `build/rigid-create-new-20261022-9/report.json`, **2/2 passed**, with
15 cases on each Linux x64 native build:

- Blender 4.5.14 LTS, build `62c1db4208e8`.
- Blender 5.2.2 LTS, build `d13f752e3b9c`.

Dirty base is `dc19b2a0efe91dfccc16479bf95767b0fcae8735`; the 274-file Python
source fingerprint is
`c2e1bc7d53793739f360fc131f2fbeddc71ca0a793d1cc67d1245febe0e291eb`.
Probe SHA256 is
`160f6ff1312608524bb537f31bca8c10488c711c576b134818a2caeea74a68aa`.
Reports retain detailed hashed JSON snapshots and every native log. Owned source
bytes are archived beside reports 1–9; the original report-1 fixture was recovered
from its exact successor and verified against its original runner hash.

Reports 1–8 remain independently identified. Report 1 retains the failed
remove/relink strategy; its oversized marker also prevented the 4.5 runner from
accepting its version/marker. Report 2 separates authored recovery from derived
matrix changes. Report 3 fails closed when the fixture itself exceeds the
16-Scene Main inventory budget. Reports 4–5 add fault/cancellation cleanup and
immediate protected-output assertions respectively. Report 6 adds nonempty shared
Material bindings and a protected Mesh sentinel. Reports 7–8 retain a fixture
comparison error: raw Cycles IDPropertyGroup wrappers were compared instead of
immutable custom-property projections. Report 9 corrects that comparison and
also captures Scene/root-collection authored settings. Passing research markers do
not imply full-state restoration where the retained measurements say otherwise.

Native operator execution peaks in report 9 are approximately 0.77 ms on 4.5 and
1.09 ms on 5.2. The enclosing operation intervals, including repeated complete
scope comparisons inside operator overrides, reach approximately 77 ms and
92 ms respectively. These tiny measurements do not establish a general latency
bound. All native tails are synchronous and nonpreemptible.

The focused runner/cache-evidence tests pass (32 cases), followed by the full
non-Blender suite on MCP SDK 2.2.0 (4,111 passed, three Windows-only skips). Ruff,
MCP typing, inventory generation and whitespace checks pass. The three owned
files and validation hashes are pinned by
`build/rigid-create-new-validation-20261022-final/source-freeze-receipt.json`.

Windows, installed packages, reviewed appearance, large/constrained-memory
workloads, pre-existing physics restoration, constraints/collisions, rigid disk
caches, fluid, Geometry Nodes and long owned jobs remain unqualified/open. No
project or preferences were saved, disk-cache flags were not changed, and no
global cancellation operator was used.

## Ordinary interactive startup and complete default vectors

The opt-in interactive `rigid_startup_defaults_probe` preserves the original
factory Scene, Cube, Camera and Light. It adds only owned body/constraint
collections and 1 or 16 owned Mesh bodies. It neither replaces nor empties that
Scene. The unique runner case records native setup, a native undo checkpoint,
the existing cache-scope admission result and detach-first cleanup on each exact
build. It performs no bake, project/preference save or public setup dispatch.

`build/rigid-startup-defaults-20261022-2/report.json` records **2/2 research
passes** on Blender 4.5.14 LTS `62c1db4208e8` and Blender 5.2.2 LTS
`d13f752e3b9c`. Report SHA256 is
`2203e56b64d8da787e4661d05149418be4e674b24d95422b225faf28181ed119`.
The probe source SHA256 is
`f36e3733de3afecfdf5427d03301a69c458754eeaf99cf4d62a97ea27a23ae01`.
The respective complete research JSON hashes are
`500e97c0493adc34500e5446bcdfb334a6eb4095001b1e6bb4e774621bdca30e`
and `2f4e879364f752e25cbaca8e5ac0e93fec807ccdc3879c6e61d882a744a4f59d`.
The source before native execution is pinned against base
`3ac7b63d36b857307a4ac9e1a2ecbec989f80f65` in
`build/rigid-startup-defaults-20261022-validation-v2/source-before-native.json`
(SHA256 `7504e81c11cf6a01e211b5edcfdaf3b87e04241d4a986335b4d812af356911f9`).
Report 1 and its original source freeze remain separate historical evidence:
the authored projection was checked after setup/checkpoint but not again after
cleanup. Report 2 adds those final comparisons and requires complete default
vectors plus the expected compatibility refusal before emitting success.

All six sampled physics states per version have complete native scalar, array
and pointer vectors: unbound constructor defaults, populated-binding defaults
and configured settings, for both body counts. Descriptor-screened values cover
RigidBodyWorld, EffectorWeights, PointCache, every PointCache entry, the
PointCaches container selectors including `active_index`, and every allocated
RigidBodyObject. Pointer values establish identity; nested content is qualified
only for these explicitly traversed owners. The only separately traversed collection is `point_caches`;
the reports list no remaining unread native fields. Populated binding again
allocates ACTIVE/CONVEX_HULL settings on every body before role/BOX changes.
Original ID identities, the captured authored Object projection, context and
body collection membership survive detach-first cleanup. These projections
still do not qualify complete shader values/ramps, UV selectors, custom normals,
nested light-linking or every Main owner's content.

The result also retains an explicit **compatibility failure**. In all four
body-count/version combinations, the unchanged cache helper refuses the
ordinary Scene before and after the checkpoint with `NOT_IMPLEMENTED`:
"The simulation Scene has external consumers outside the current window
context." Research success requires retaining that refusal; it does not mean
setup followed by the existing cache tool is available to ordinary users.

The measured native WindowManager reference count is two, while real Scene
users remain one. There is exactly one Main Scene and one actual Window,
the workspace is unpinned, the WindowManager is the sole external Scene consumer,
and raw WindowManager/Window/WorkSpace custom properties contain no ID aliases.
The exact Scene has its non-evaluated read-only `original` loopback, one
self-reference and `use_extra_user=true`. The pinned upstream WindowManager
visitor assigns `win.scene` the `USER_ONE` role and `win.unpinned_scene` the
non-user `NOP` role; the latter is not publicly exposed through Window RNA.
Source roles are pinned to upstream commits
`62c1db4208e862312bc36db5bc15d4a6dbcfa3e3` and
`d13f752e3b9c4f8c261cda552b1021f8bcc0382c`, with exact saved-byte receipt
`build/native-source-review-20261022/receipt-exact-bytes.json`
(SHA256 `7bd654cff7f1ff7eafda0096b6701eba0d2fa9de2f514a64f48c8d606093dcfe`).
This experiment performs no counter normalization; attribution of the two
measured references to those source roles remains a research inference. A
future shared consumer adapter must also pin query traversal flags, exclude
other conditional UI/global-area paths and reject extra aliases, including
WorkSpace sequencer bindings where present;
merely accepting a count of one or two is insufficient.

The focused runner/cache-evidence checks pass (32 tests). The full non-Blender
suite passes on MCP SDK 2.0.0 and 2.2.0 (4,369 passed and three Windows-only skips
on each), as do Ruff, MCP typing, generated inventory and whitespace checks.
The research-only probe, runner registration and this documentation are frozen
with the native/validation evidence under
`build/rigid-startup-defaults-20261022-validation-v2/`.

A production setup/cleanup contract remains unimplemented. It still requires
separate absent/owned-partial/complete preflights, aggregate identity-memoized
geometry budgets, proven preservation projections or explicit refusals, a
session-owned non-evicting record store, and canonical live request/checkpoint
admission. Existing `rigid_body.cache` also needs the shared admission adapter
before this follow-up can qualify production safety. Cancellation, disconnect,
manual undo, large inputs and Windows are not tested by this tiny research case.

## Private Mesh projection and external Scene roles

The unwired private helpers `_rigid_authored_scope.snapshot_meshes` and
`_rigid_scene_consumers.external_scene_roles` have separate bounded contracts.
Neither is a setup tool or an admission exception for existing cache tools.
The Mesh reader captures each supplied Mesh ID once, including unused data,
and records every supplied Mesh Object binding. Geometry and attribute values,
material ID bindings, UV buffers, UV active/render/clone/stencil selectors and
attribute/color selectors use structural child indices and values. Only ID data
blocks use native pointer/session identities. Budgets apply across the whole
supplied inventory, and every nested descriptor is admitted before generic
scalar projection begins. Shape keys and custom split normals are refused.
Raw custom-property scalar values carry explicit exposed type tags; finite
custom floats use hexadecimal strings, distinguishing `False`, `0`, `0.0` and
signed zero. Native fixed-RNA fields retain their existing semantic projection.
This is not complete Mesh content
preservation: Skin-layer contents, nested asset metadata and IDProperty UI
metadata remain outside the projection. The caller must separately exclude or
qualify them, prove the consumer inventory and cover non-Mesh authored data.
Container storage kinds and hidden IDProperty storage metadata are also
unqualified; exposed scalar type tags do not prove their preservation.
The comparison records are not recovery backups.

The external-role reader requires an exact canonical native class and native
descriptors for every field it reads. It never evaluates unrelated UI runtime
fields, including Blender's bundled `WindowManager.preset_name`; it grants no
named getter exemption. Raw WindowManager/Window/WorkSpace ID aliases, extra
Scenes/windows/consumers, workspace pinning and sequencer Scene bindings are
refused. The two accepted raw WindowManager reference counts remain distinct:
one identifies `win.scene` with `IDWALK_CB_USER_ONE`; two additionally identifies
`win.unpinned_scene` with `IDWALK_CB_NOP`. Exact source roles and query traversal
flags are pinned by the 20-file upstream receipt
`build/rigid-consumer-source-review-20261022/receipt-exact-bytes-v5.json`
(SHA256 `8acfb9bf95c0ecf25f2784015d8ada386f3669a121164e0db353d79f2a0ecc87`).
Raw counts are retained without subtraction or normalization. Scene self and
dependency roles remain unqualified, and `scene_self_scope_qualified` is always
false. Separate source research identifies a hidden `ParticleEdit.scene` write
through undo polling and exposes the related read-only `ParticleEdit.object`;
the `Scene.original` loopback does not explain that role. This helper does not
authorize or absorb that transition.

The unique small interactive `rigid_scope_profile_probe` passes on both pinned
Linux builds in `build/rigid-scope-profile-20261022-6/report.json` (SHA256
`bb777c7e3406b2242fd21e01c9b051b000924952f5784bc4e73ac3a5f0c42e8c`).
The ordinary factory Scene, Cube, Camera and Light remain in place. The captured
Mesh projection matches across the fixture-owned native checkpoint; shared Mesh
memoization, UV/material/color-selector edit detection, raw UI alias refusal,
custom-normal refusal and refusal before a runtime Mesh getter are exercised.
Actual Mesh and WindowManager custom properties independently exercise distinct
`False`, integer zero, floating zero and negative floating zero comparisons;
all owned test keys are removed afterward.
Both versions retain WindowManager count two, Scene users one and Scene self
count one before and after that checkpoint. These observations do not prove a
general Scene self-role transition. The fixture creates and removes only owned
temporary test data and saves no project or preferences; Blender's disposable
exit-recovery files remain in the runner evidence.

Reports 1–4 and their exact input archives are retained as negatives. Report 1
refuses the unrelated bundled UI runtime descriptor. Report 2 reveals that native
StringProperty and EnumProperty descriptors have no numeric-array metadata.
Report 3 reveals non-ID UV selector pointers, now projected structurally. Report
4 reveals the native dynamic `MeshPolygon.vertices` array: its descriptor's
default width is three even on quads. The corrected reader captures its measured,
bounded topology directly. None of those failed pairs reached the checkpoint.
The separately retained report 5 passes its original bounded checks. Subsequent
review identified Python equality collisions between bare custom bool/int/float
values and signed zero. Report 6 adds explicit custom scalar type/float encoding
and regression checks in both private readers; it preserves the report 5 source
freeze and receipt as historical evidence. The final native source fingerprint
covers 283 Python files, SHA256
`431a2cc7604e4c760bb2fa156297438993c4d4d2342df6abe3cf4cfc68684750`.

The focused checks pass 117 tests (55 Mesh projection, 30 external-role and 32
runner/evidence tests). The full non-Blender suite passes on MCP SDK 2.0.0 and
2.2.0, each with 4,454 passed and three Windows-only skips. The source freeze,
native reports, checks and qualification limits are pinned under
`build/rigid-scope-profile-validation-20261022-6/`. No full Main, shader,
light-linking, production cache/setup, canonical request recovery, visual or
Windows qualification follows from this structural research. All release gates
remain open.
