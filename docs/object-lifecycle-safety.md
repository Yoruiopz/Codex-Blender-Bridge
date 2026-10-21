# Object lifecycle and layout safety

Object lifecycle edits now preflight local, editable, non-override objects in Object Mode
in the current view layer. Objects shared between scenes are rejected. Collection changes
require local current-scene containers and unshared ancestry; collection instances and shared
parents are not silently edited or made local. Creation validates its collection before
allocating an object. Duplication retains referenced dependencies: copying object data does
not recursively copy materials, Actions, images or node groups.

Rename, deletion, parenting, collection membership and bulk layout reject incoming consumers
outside ordinary collection/scene ownership. This includes another object's driver or
constraint reference. Blender reports the current Scene as a user of ordinary objects through
view-layer bases and embedded root links. The guard checks native `user_of_id` counts against
those exact memberships; an active-camera/custom-property/other extra Scene reference does
not pass as an ordinary link. RNA identity uses native pointers across Python wrappers.
Collection traversal, incoming users and view layers have explicit finite budgets; incomplete
scope is refused before mutation.

Apply and compensation boundaries retain the caller context and recheck cancellation,
live toolset/permission/pause/stop state, and frozen scene/view-layer/project/target identity.
Scope is checked again after dependency-graph updates, which can run third-party handlers.
New consumers, replaced IDs and changed ownership therefore cannot reuse stale preflight.

`object.set_parent` supports object parenting of independent targets without children,
animation, constraints, rigid bodies, collection instances, locked transform channels or
non-default delta transforms.
It refuses bone/vertex parent
contexts. The chosen parent may have other children, whose transforms are not edited.
World-preserving changes verify the resulting world matrix; local-preserving changes verify
the basis. Failure recovery restores and measures parent, parent type, parent inverse, basis,
raw transform channels and world only while the current output still exactly matches the
operation's own writes and live grants permit compensation. Newer hierarchy/transform or
selection/active-object changes are retained and reported for reinspection. Normal operations
preserve selection and active object. Singular parent transforms and unrepresentable results are
refused or fail with measured recovery evidence. Object deletion refuses children rather
than implicitly unparenting them.

Collection move/link failure recovery only restores attempted original unlinks and removes
the operation's own newly added target link; unrelated new links are retained. It measures
world/context state rather than claiming success after an unverified compensation.
Bulk layout now rejects collection instances and incoming consumers, and verifies evaluated
origins during rollback as well as raw transform channels. Only attempted requested channels
whose current values exactly match observed owned outputs are restored; untouched/newer
channels are retained. Failed create/duplicate operations retain their known allocated IDs
for explicit permission-checked recovery and report possible unknown allocation effects.
They never implicitly delete objects or datablocks under the creation/transform grant.
Failures carry
`execution_started`, `rollback_verified` and explicit uncertainty; callers must reinspect
when recovery is incomplete. Selection IDs/checkpoints remain session-local, not backups.

These are conservative compatibility restrictions on previously under-checked operations.
Wider multi-scene, instanced, constrained, animated or dependent edits require a separately
reviewed scope contract. No new tool, schema, protocol version, permission or save behavior
is introduced. This increment does not complete the mutator audit: automated consent-checked
cleanup of retained allocations, irreversible delete failures, ambiguous global ID
name resolution and whole-project dependency coverage remain open.

## Development evidence

`scripts/blender_layout_smoke.py`, executed through the native runner, now exercises actual
object creation, duplication, rename/deletion, current-scene collection moves, parent/clear
world preservation, post-mutation fault recovery, protected-child refusal, instanced
collection refusal and incoming-constraint refusal. The local Linux Blender 4.3.2 run at
`build/object-scope-native-20261022-5/report.json` passed expanded layout and core cases,
including restoration of original Euler values beyond a full turn. Earlier runs 1 and 2
failed; runs 3 and 4 passed earlier sources. These are distinct development reports.
Unit coverage includes
linked/override/read-only/shared-container refusal, late membership failure, failed recovery,
Scene reference counts, RNA wrapper identity, live grant/cancel/stop boundaries, allocation
retention without delete consent, newer external state retention, evaluated rollback drift,
and lock/rotation-mode changes at the final write and recovery gates.

This is development-source evidence, not clean-commit/package acceptance or a Windows 11
4.5 LTS/stable-5.x matrix. Source fingerprints must be refreshed after any later source edits.
No project was saved, existing user session touched, release published, or minimum changed.

## Other audit findings for follow-up

- The initial `simulation.cache` audit found frame restoration could replace the primary
  failure. The root implementation fixed that in this wave: primary error information and
  separately measured frame/range recovery are retained (`tests/test_simulation_recovery.py`).
  `cloth_add` and `configure` still need allocation/partial-assignment recovery review.
- `animation_layers.driver_add` can lose its primary failure if rollback removal or clearing
  animation data fails. Dependency updates and result inspection occur outside its recovery
  block. NLA strip creation binds Actions rather than editing keys: shared/linked Action scope
  must distinguish an allowed reference from an edit, with failure and retention evidence.

The object/layout changes do not alter animation driver cleanup or cloth allocation/configuration.
