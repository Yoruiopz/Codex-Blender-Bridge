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
establish preservation of every Main ID's contents or user counts. The ordinary setup-success cases also pass the existing complete
cache-scope admission with the resulting world and bodies. This admission is not
a bake, motion, collision or artistic acceptance test.

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
