# Structured Mesh Edit Mode recovery

Unreleased on `main`. A single-mesh edit interval can now form one logical recovery
group through the normal dispatcher. Named checkpoints remain available across the
mode transition.

Enable the `interaction` and `mesh` toolsets on both peers. The demonstrated workflow
needs `INSPECT_SCENE`, `TRANSFORM_OBJECTS` and `EDIT_MESH`, with Global Undo enabled.
Individual operations retain their own permission and ownership checks; mesh editing
requires the supported local, non-override, single-user mesh context.

## Workflow

1. In Object Mode, inspect the relevant objects and selection. Capture complete
   `scene.snapshot` evidence for the intended preservation checks and create a
   `checkpoint.create` recovery point.
2. Call `context.set_mode(object_name, mode="EDIT")`. This isolates the named object's
   selection as documented by the context tool. The result identifies a deferred
   `operation.undo_group` with an `edit_…` ID.
3. Inspect components with `mesh.components_inspect`, then select explicit indices
   with `mesh.select_components`. The current selection reference is under
   `selection.mesh_selection.selection_id`. Reinspect after topology changes.
4. Perform the scoped mesh edits. They share the session's Object Mode before-point;
   they do not each claim a separate global native snapshot.
5. Call `context.set_mode(object_name, mode="OBJECT")`. A matching scene/object identity
   finalizes the group's native after-point. Inspect the resulting geometry and use
   `scene.compare` to check the protected fields.
6. When recovery is required, call
   `checkpoint.undo_last(confirm_global_undo=true, restore_snapshot=true)` from Object
   Mode. It returns `recovered_scope="mesh_edit_session"` after reaching the group's
   before-marker. Reinspect and compare the result before continuing.

The group covers the edit interval, including other edits made during that interval.
Its `object` identifies the entry mesh. Global snapshot recovery includes all edits
in that interval, including interleaved manual work. Close a coherent session before
starting an unrelated task when independent undo granularity is needed.

The legacy default `restore_snapshot=false` still performs exactly one native global
undo; use the explicit snapshot path for the grouped operation.

## Status and failure behavior

`bridge.status.agent.undo_group` and Blender's checkpoint panel expose pending session
information. Modifying results and applicable errors include `undo_group` metadata:

| State | Meaning |
| --- | --- |
| `deferred` | The before-point exists; return to Object Mode to finalize the group |
| `finalized` | The after-point was recorded and the grouped operation is tracked |
| `invalidated` | A detected scene/active-object mismatch prevented finalization |
| `unavailable` | Native finalization failed; no new recoverable group is promised |

On mode exit, `undo_boundary_created` may be false while `undo_boundary_finalized` is
true: the before-point belongs to the earlier entry call. The nested group records
`before_boundary_created=true`, its entry tool/object and checkpoint-managed operation
attempts. A batch counts as a logical attempt rather than one attempt per child step.

Permissions, pause and emergency gates are checked for each dispatched operation.
Denied calls do not complete a mode transition or bypass those gates. A handler that
partly modifies the mesh and fails can retain a deferred group; return to Object Mode,
inspect the partial result and request confirmed recovery when appropriate.

Cancellation is checked again after checkpoint preparation and before the handler
starts. A canceled recovery does not finalize an editor session before checking its
signal. If cancellation follows native finalization, the error retains that group's
evidence. A native call already running cannot be preempted.

Pending groups are transient. File replacement, unregister and native user undo/redo
invalidate tracking. Detected scene/target changes can invalidate a group while keeping
earlier named checkpoint candidates. Native history may evict a target; the existing
bounded guard/redo recovery contract still applies. Checkpoints do not save project files.

## Current coverage

Automatic grouping covers a single Mesh Edit Mode session entered from a tracked Object
Mode before-point. It does not establish individual Edit Mode-operation undo, multi-object
editing, Armature/Pose/Sculpt/Paint undo or durable recovery. An editor entered outside the
tracked path may have only an earlier named checkpoint candidate. Final marker verification
continues to require structural and relevant visual checks against the user's request.

`blender_mesh_edit_recovery_smoke.py` uses the dispatcher for mode entry, measured face
inspection/selection, extrusion, mode exit and confirmed recovery. It independently checks
the complete scoped baseline, protected mesh/materials, selection, active object and mode.
It also checks permission revocation, pause/emergency blocking, partial editor failure
recovery and separate recovery of an earlier object transform on Windows Blender 4.5.1/5.1.2.
This fixture verifies recovery mechanics and numeric preservation; artistic appearance and
the wider 1.0 workflow gates remain open.
