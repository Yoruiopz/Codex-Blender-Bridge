# Structured mesh repair (unreleased)

Main adds three typed tools, not included in the 0.3.0 download:

| Tool | Behavior | Important limits |
| --- | --- | --- |
| `mesh.subdivide_selected` | Split selected edges, with quad grid fill where supported and no smoothing or fractal displacement | `cuts`: 1–32; conservative growth estimate must fit 200,000 total mesh elements. Adjacent faces also change. This is not a subdivision-surface modifier. |
| `mesh.merge_by_distance` | Find and weld coincident/nearby **selected vertices only** | `distance`: 1e-12 to 1e6 in mesh-local units, default 0.0001. Object scale changes the world-space meaning. Incident geometry may collapse and UV/weight/other attributes may reconcile. |
| `mesh.fill_holes` | Cap each complete, disjoint boundary loop with one n-gon | 3–1,024 sides per loop; boundary edges must have exactly one incident face. Open/branched, wire and interior-edge selections are rejected. Not grid fill, loop bridging or nested-hole triangulation. |

All require an explicit `object_name`, enabled `mesh` toolset and Blender's `EDIT_MESH`
permission. The named mesh must be the sole active Edit Mode object, local, non-override,
single-user and within the component-inspection budget (200,000 vertices + edges + faces).
At most 20,000 selected components and 100,000 affected face corners are accepted. Hidden
selected or affected face geometry is rejected. Shape-key meshes return `NOT_IMPLEMENTED`.
No implicit copying, mode switching, object deletion, external files, saving or Python execution
occurs. `DELETE_OBJECTS` is not needed for vertex welding: it does not remove objects/datablocks.

An optional `selection_id` scopes the operation to a previously inspected selection. A successful
topology change invalidates old selection references; inspect again. A merge with no matching
vertices returns `changed:false` without flushing the selection or updating mesh data.

`fill_holes.material_index` defaults to zero and must address an existing slot (zero also works
when no material slots exist; at most index 255). Existing faces retain their assignments.
Every new face's UV coordinates in every existing UV layer are explicitly initialized to zero and unpinned;
unwrap the new faces afterwards. A cap is not a promise of planarity or good triangulation.

## Recommended workflow

1. Inspect scene, mode, selection, object ownership and bridge permissions. Resolve the exact
   mesh and protected objects. In Object Mode, use `scene.snapshot` for their relevant fields.
2. Create one logical checkpoint for the repair. Use `context.set_mode` to enter Edit Mode;
   this starts the single-mesh recovery group, with the permissions that tool requires.
3. Read bounded `mesh.components_inspect` pages and use `mesh.select_components` with a fresh
   inspection reference. Choose vertices for merging or edges for subdivision/capping.
4. Call the relevant repair tool. Reinspect topology, counts, coordinates and face assignments.
   Refresh the selection reference between topology edits. Inspect corner UVs/weights wherever
   preservation matters; do not infer attribute preservation from counts alone.
5. Return to Object Mode to finalize the recovery group. Compare the scoped scene baseline;
   require complete evidence for protected objects. Capture wireframe for topology and solid
   or material shading for the surface; compare against the requested result and refine.
6. If necessary, use confirmed snapshot recovery, then independently compare the baseline.
   See [recovery limitations](mesh-edit-recovery.md). Save only when explicitly authorized.

Results include affected object, before/after mesh counts, selection counts, local coordinate
space, operation-specific counts, reference invalidation and verification reminders. A native
failure can follow partial mutation; the dispatcher retains the edit-session recovery evidence.
These tools are not local transactions or per-primitive undo within an open Edit Mode session.

## Development evidence

`scripts/blender_mesh_repair_smoke.py` runs a disposable open-box repair through the actual
dispatcher: weld one selected pair while retaining an unselected coincident vertex, reject an
incomplete boundary, cap the top, then subdivide it into four quads. It measures cap materials,
existing/interpolated UVs, weights, dimensions, a protected duplicate, and grouped snapshot
recovery including selection/active object/mode. All three tools are tested with `EDIT_MESH`
revoked, then operate without the four raw-Python super-permissions.

The fixture captures before/after wireframe and a solid surface. These have been reviewed on
Windows Blender 4.5.1 and 5.1.2: the cap grid is visible and the box silhouette is retained.
This is a small modeling fixture, not broad artistic/retopology acceptance or packaged-RC proof.
No user `.blend` is used or saved. Generated evidence stays under the runner's build directory.

The workflow also exposed isolated capture deselecting temporarily hidden peers. Viewport
capture now restores their selection after visibility on success and partial isolation failure;
restoration errors are logged locally and reported rather than silently returning success.
