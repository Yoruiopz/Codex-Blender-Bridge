# Explicit Action lifecycle and save retention

These unreleased tools use the `animation` toolset. They add bounded Action
allocation, assignment, metadata and unused removal; full character acceptance
remains open. They run on Blender's main thread through normal operation history
and checkpoints. No lifecycle call saves a project or treats undo as a backup.
Existing timeline/key insertion/deletion safety is documented in
[guarded animation mutations](animation-mutations.md).

| Tool | Required Blender permissions | Bounded behavior |
| --- | --- | --- |
| `animation.action_inspect(action_name)` | `INSPECT_SCENE` | Exact Action content digest, OBJECT/other slot inventory, direct consumers, real/fake users and retention |
| `animation.action_create(action_name, slot_name, keep_on_save)` | `EDIT_ANIMATION` | Allocate one unbound layered Action with one OBJECT slot, one keyframe layer/strip and an empty channelbag |
| `animation.action_bind(object_name, action_name, expected_action_name, affected_objects, slot_identifier?, allow_session_only_previous=false)` | `EDIT_ANIMATION` | Bind one exact existing Action/OBJECT slot, or explicitly clear with `action_name=null`; compare the expected previous Action before writing |
| `animation.action_update(action_name, new_name?, keep_on_save?, allow_shared=false)` | `EDIT_ANIMATION`; also `DELETE_OBJECTS` when clearing an existing fake retention flag | Rename/change retention only; shared metadata requires explicit acknowledgement and preserves every source channel |
| `animation.action_remove(action_name, confirm=false)` | `EDIT_ANIMATION`, `DELETE_OBJECTS` | Confirm removal of one local unused, unretained Action with `do_unlink=False`; never unlink consumers or recreate an ID automatically |

Names resolve exactly across Blender's complete Action inventory; ambiguous local
and library names fail. New names fit 63 UTF-8 bytes, slot display names 61 bytes,
and occupied names are refused. Create requires an explicit `keep_on_save` choice.
An OBJECT slot identifier, such as `OBWalk`, is returned; callers must use the exact
identifier when binding a layered Action. Legacy Actions have no slot argument.

## Ownership and affected scope

Mutation requires local editable non-override Actions and object owners in one
current scene/view layer. Object collection ownership is checked. Binding requires
`affected_objects` to enumerate the complete dependent-object closure, including
skinned meshes or constraint/driver consumers where supported, with at most 32
objects including the target. An incomplete or unsupported dependency graph is
refused before assignment. Merely sharing an Action does not permit changing its
channels; binding preserves all Action content and protected references.

Bindings accept only existing own-object or pose-bone transform channels and exact
finite numeric object/pose custom controls. Bone names use canonical escaped RNA
paths; rotations must match the current rotation mode. Arbitrary RNA, shared-data
channels, duplicate layered channels, missing controls, active drivers and NLA tweak
mode are refused. Binding a new Action does not prove evaluated deformation or
motion; independently sample frames and inspect affected geometry.

The content inventory is limited to 1,024 curves, 16,384 total unsampled keys,
1,024 keys per curve, 256 total modifiers, 64 slots, 16 layers, 64 total layer strips
and channelbags, and 256 total groups. Per-layer strips are limited to 32 and
per-strip channelbags to 64. Asset-marked Actions, Action custom properties,
sampled curves, unaccounted native users and unsupported RNA shapes fail closed.
Inspection is complete only within these declared limits; it does not silently
truncate a mutation's ownership evidence.

## Retention, recovery and identity

`REFERENCED` means an actual consumer retains an Action. `FAKE_USER` means its
explicit fake-user retention flag is set without real users. `SESSION_ONLY` means
it has neither; it can disappear on saving and reopening. Clearing/replacing the
last active reference to an unpinned Action requires explicit
`allow_session_only_previous=true`, or first set retention through `action_update`.
Setting fake retention changes Blender data; durable storage still requires a
separately authorized `project.save` with `SAVE_PROJECT` and the appropriate
external-path permission. The lifecycle tools never grant those permissions.

Before every assignment and compensation, live permission, pause, emergency stop,
cancellation, toolset, scene/session, exact ID/session UID, slot, content, direct
consumers and NLA context are checked. A measured, known partial assignment can be
restored to the original Action and slot while that boundary remains valid. If
consent is revoked or manual edits replace content/bindings, compensation stops
and reports the observed partial state as possible mutation. Failed allocations
remain named for explicit inspection and cleanup. Removal reports uncertainty
truthfully and never claims identity preservation by recreating an Action.

## Development evidence

`action_lifecycle` is a two-process native runner case. On Linux Blender **4.5.14
LTS** and **5.2.2 LTS**, its writer exercises typed allocation, shared protected
source channels, exact slot binding, permission and invalid-slot denial, known
postwrite compensation, and post-assignment permission revocation. The writer then
uses an independently authorized project save. A distinct reader process verifies
sampled actor/protected motion, retained unbound Actions, omitted session-only
Actions, removed IDs and unchanged protected Action content.

Retained development reports are under
`build/next-wave-animation-guard-native-20261022-final-2/`. Unit fixtures additionally test
same-name ID replacement, consumer/content/context changes, and manual binding
interleaving. These are development checks, not Windows qualification or the full
character benchmark. Native undo/manual-history eviction, constrained memory,
production-scale character/deformation and reviewed visual acceptance remain open.
Run fixtures only through `scripts/run_blender_checks.py`.
