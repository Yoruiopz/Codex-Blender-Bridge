# Stored rig editing and live write boundaries

The existing `rig.create`, `rig.bone_add`, `rig.bone_update`, `rig.bone_remove`,
`rig.pose_transform`, `rig.constraint_add` and `rig.constraint_remove` now use
Blender-side live boundaries throughout their multi-write operations. These are
bounded unreleased capabilities. They do not close the full character, recovery,
Windows qualification or visual acceptance gates for 1.0.

## Scope and permissions

Every object-bound method accepts optional `affected_objects`, an array of exact
dependent-object names. Omission preserves the existing call shape and accepts
only an independent rig. A skinned rig ordinarily needs its skin objects listed;
bone-parented objects and other incoming Object consumers also belong in the
complete transitive closure. The list must match the measured closure exactly,
with at most 31 dependent objects. Objects must be local and editable in the
current view layer and one current scene, with reviewed collection ownership.
Linked, override, cross-scene and unexplained non-Object consumers fail closed.

Same-object driver references are also outside this generic rig-edit boundary,
including a supported numeric property driving a bone on its own rig. Listing
every skin does not make that self-reference reviewed. Use the separate typed
control/driver tools for their documented operations; combined pose/rest editing
with those self-drivers remains an open character-workflow requirement. Removing
a driver retains its last evaluated channel value. A separately authorized pose
reset is accepted after those self-references are removed, with all skins listed.

For example, a pose revision can preserve an existing Action while changing its
current stored pose channel:

```json
{
  "object_name": "CharacterRig",
  "bone_name": "Forearm.L",
  "location": [0.0, 0.0, 0.1],
  "affected_objects": ["CharacterSkin"]
}
```

The tool does not insert a keyframe. Use the typed animation tools for an intended
key revision; changing frame can reevaluate the existing Action.

| Method | Required permissions |
| --- | --- |
| `rig.create` | `EDIT_ANIMATION`, `TRANSFORM_OBJECTS` |
| `rig.bone_add`, `rig.bone_update` | `EDIT_ANIMATION` |
| `rig.bone_remove` | `EDIT_ANIMATION`, `DELETE_OBJECTS` |
| `rig.pose_transform` | `EDIT_ANIMATION`, `TRANSFORM_OBJECTS` |
| `rig.constraint_add`, `rig.constraint_remove` | `EDIT_ANIMATION` |

The `rigging` toolset must remain enabled. No method saves a project. Internal
RNA changes do not require `SAVE_PROJECT`; an authorized `project.save` is a
separate operation. Removing a scoped pose constraint removes that RNA component,
and does not delete an Object or Armature ID.

## Context and preservation receipts

Rest editing requires Object Mode, a visible selectable rig, and single-user
local Armature data. Pose and pose-constraint operations accept Object or Pose
Mode, and do not enter Edit Mode. Stored-state comparison is bounded to 256 bones.
Unknown writable descriptor kinds or excessive dependency/mesh/animation budgets
return `NOT_IMPLEMENTED` before the next write.

Before every write, the boundary rechecks cancellation, required permissions,
enabled toolset, pause/emergency state, exact Scene/view-layer/project/mode, frame,
selection and active object, exact Object/data identities, complete declared
incoming closure, owned content and protected stored content. A final permission
provider cannot silently change that frozen session or disable the toolset.
Setters require requested-field readback and a measured receipt for unrelated
fields. No-op setters still require live authority.

Stored rig receipts include rest coordinates/matrices and writable settings,
hierarchy, B-Bone settings, custom properties, bone collection memberships and
hierarchy, bone/pose colors including custom color values, pose channels and
constraints, and object/data Actions, NLA and drivers within their supported
bounded readers. Explicit skins use bounded raw mesh/topology/attribute,
vertex-group/weight, binding and material-slot comparisons. Derived pose matrices
are not mistaken for stored channels. These receipts do not establish complete
transitive material/image/simulation preservation or visual deformation quality.

Blender's `object.mode_set` targets the actual ViewLayer active object; overriding
`object` and `active_object` alone did not redirect it on either researched
runtime. Rest tools therefore use explicit, individually guarded context changes.
Successful operations restore the original object selection, active object and
mode, plus original existing-bone selection flags. Native parenting can clear a
parent's tail-selection flag; that measured side effect is restored through the
same live boundary.

Editing a connected child's tail or roll can also synchronize the parent's tail
envelope radius with the child's head radius. The boundary predicts that native
side effect, then restores the original distinct radii through individually
guarded Bone RNA writes after leaving Edit Mode. This avoids EditBone radius
setters, which themselves propagate to connected neighbours. Revocation can
retain the intermediate radii and is reported as an incomplete operation.

## Unsupported propagation is refused before context changes

Native bone renaming rewrites vertex-group names, Action paths, bone-parent names
and constraint subtargets. Renaming or removing a consumer-bound or animated rig
therefore requires a broader reviewed propagation transaction and currently
returns `NOT_IMPLEMENTED`. Pose constraints or custom bone-handle/shape-transform
references also block these legacy rename/removal operations. Independent rig
rename, removal and explicitly acknowledged child reparenting remain supported.

Updating a bone's geometry/parent/connectivity while it has connected children
also returns `NOT_IMPLEMENTED`: native parent-tail changes can move a connected
child's head. This is an explicit open artist-workflow requirement, not a
completed structural-preservation gate.

## Failure and recovery

Rest topology edits do not pretend to roll back by recreating bones from names.
After native partial failure, revoked consent, cancellation, changed context or
manual interleaving, the current operation is retained and reports current mode,
completed writes and recovery instructions. If consent disappears in Edit Mode,
the failed request performs no late mode or selection cleanup. Reinspect the
actual current state before explicit checkpoint recovery or a separately
authorized correction. Pose/constraint failures likewise retain measured partial
results instead of claiming verified rollback.

Failed creation never silently removes a new Object or Armature ID. It reports
the exact known allocated IDs and any bounded newly observed IDs whose ownership
was not established. Explicit deletion needs fresh scope and `DELETE_OBJECTS`.
An orphan retained only in memory may disappear when saving/reopening; retained
buffers, orphan IDs and undo history are not durable backups.

The official runner cases are `rig_edit_probe` (native behavior research),
`rig_edit_boundaries` (typed success/refusal/interruption receipts), and opt-in
`rig_edit_reopen` (separate writer/reader processes with authorized save and file
hash verification). The latter checks stored rig, raw skin and Action content
after reopening; it does not claim durable identity-preserving rollback,
interactive undo, constrained-memory qualification or human visual approval.
Run through [the isolated native runner](native-testing.md). Linux 4.5.14 and
5.2.2 evidence does not qualify Windows 11.
