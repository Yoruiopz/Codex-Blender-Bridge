# 0.3.0 development: faster structured scene work

These additions are in source, **not in the published 0.2.0 packages**. Update both
add-on and MCP server when trying this development build. There are 108 remote tools
(109 add-on methods including local-only checkpoint recovery).

## New toolsets

| Toolset | Tools | Purpose |
| --- | ---: | --- |
| `batch` | 2 | Preflight and run up to 32 structured steps in one request |
| `interaction` | 4 | Object selection, explicit mode changes, paginated component evidence, component selection |
| `layout` | 4 | Filtered scene queries, up to 128 explicit transforms, origin alignment/distribution |
| `geometry_nodes` | 10 | Create/inspect graphs, add interface sockets/nodes, edit properties/defaults, link/unlink/remove, attach modifier |

Enable only needed toolsets. Blender permissions remain authoritative. No new Python
escape hatch is introduced, and the existing Python super-permission remains disabled by default.

## Batch without hiding failures

`batch.plan` accepts the same steps as `batch.execute` and checks structure, registered
methods, enabled toolsets, and static permissions. **It does not simulate Blender or
validate handler arguments/scene dependencies.** Dynamic gates still run in each handler.
Enable `batch` and every child toolset on both peers first.

```json
{
  "label": "Place two known props",
  "steps": [
    {"id": "left", "method": "transform.set", "params": {"object_name": "Prop.Left", "location": [-2, 0, 0]}},
    {"id": "right", "method": "transform.set", "params": {"object_name": "Prop.Right", "location": [2, 0, 0]}},
    {"id": "verify", "method": "scene.query", "params": {"name_pattern": "Prop.*"}}
  ],
  "time_limit_seconds": 10
}
```

Steps run serially on Blender's main thread. Every child is reauthorized immediately
before execution. The first error stops later steps. Results/history retain completed
steps and identify the failed step; **earlier edits remain**. No automatic rollback is
performed. A best-effort logical undo marker is created once before the first mutation,
not one per step. Blender operators/mode changes may create their own undo entries;
this is not a guaranteed single-step transactional undo.

The 0.1–30 second budget, caller deadline, and disconnect signal are checked between
steps. Long-running Blender C calls cannot be interrupted. Batch is for short actions,
not background jobs. Pause/emergency-stop gates are rechecked, but Blender's UI cannot
process clicks while a synchronous handler occupies the main thread.

There are no nested batches or result substitutions. Use exact names established by
inspection and inspect separately when a later decision depends on an earlier result.
Python, save, render/capture, lifecycle/toolset changes, and checkpoint recovery are
excluded. Each step's evidence is capped at 16 KiB; `result_truncated` means inspect
that result separately. The batch itself has conservative modifying/destructive MCP
annotations even when composed only of read tools.

## Measured selection and layout

Use `scene.query` to resolve targets by name glob, type, collection, visibility,
selection, and evaluated world-origin bounds. Follow `next_offset`; bounds refer to
**origins**, not surface intersection. Queries cover the current view layer.

`selection.set` changes selection intentionally in Object Mode. `context.set_mode`
targets one named object; entering an edit/paint/pose mode isolates its selection and
requires the corresponding mesh/animation permission. Entering paint/sculpt mode is
not a brush-stroke editing tool.

In single-object mesh Edit Mode, `mesh.components_inspect` returns up to 256 indexed
components per page, measured local/world centers, and bounded connectivity. Pass
its fresh selection ID to `mesh.select_components` to detect stale context/topology.
Reinspect after topology edits, mode changes, undo, or reload. Component selection
accepts up to 20,000 indices on meshes totaling at most 200,000 components.

`object.transform_batch` validates all requested edits before changing anything and
attempts snapshot rollback on failure. Alignment/distribution use measured **world
origins**, preserving other axes and selection. These tools deliberately reject
dependent objects (parents/children, constraints, animation/drivers/NLA, rigid bodies,
delta transforms, linked data, or incompatible locks) rather than guessing evaluated
placement. Ordinary transform tools remain available for other explicitly understood cases.

## Geometry Nodes

Use `geometry_nodes.*`, not material `nodes.*`. Graph editing needs `EDIT_MESH`;
attachment also needs `TRANSFORM_OBJECTS`. Graphs must be local and editable.
Shared/nested graph mutations require `allow_shared=true` after inspecting affected users.
Post-state reports direct users with truncation; nested graphs can affect additional objects.

Sockets are exact names/indices, properties are allowlisted direct RNA fields, and
pointer/file/script paths are not exposed. Node types use an exact reviewed allowlist
(returned by graph inspection), not an open-ended prefix. Editing or attaching a graph
with unreviewed nodes is rejected, preventing import-node string inputs from bypassing
external-file consent. Occupied single-input links require explicit
replacement, cycles are rejected, and graph/socket/result sizes are bounded.
This covers core graph authoring—not every node, simulation/repeat zone, nested group
assignment, modifier input override, bake, or specialist socket type.

## Verification

Run non-Blender tests, lint, type checking, and isolated factory-startup smoke scripts.
The interaction/layout/Geometry Nodes checks run on Blender 4.5.1 and 5.1.2 and verify
actual selection, topology, transforms, evaluated geometry, permission denial, and
failure behavior. They do not edit or save the user's live project.
