# Bounded weight brushes, geometric mirrors and surface transfer

These unreleased structured tools extend vertex-group authoring with an explicit
skinning workflow. They require `EDIT_MESH`, the `weights` toolset, Object Mode and
local, editable, non-override, single-user target mesh data. Targets and source
regions are named explicitly; active selection is not interpreted as consent.
They never change topology, normalize weights, create groups or save the project.

## Explicit brush strokes

`weights.brush_stroke(object_name, group_name, vertex_indices, strokes,
coordinate_space, blend_mode, falloff, protected_groups=[])` applies bounded
spherical strokes only to listed vertices of one existing unlocked group.
Each stroke specifies a three-component `center`, positive `radius`, `strength`
and target `weight`. Coordinate space is explicitly `LOCAL` or `WORLD`; the brush
uses base-mesh positions, not posed or modifier-evaluated surfaces. Reviewed blend
modes are `MIX`, `ADD` and `SUBTRACT`; falloffs are `CONSTANT`, `LINEAR` and `SMOOTH`.
Inspect resulting totals and use explicit normalization if the intended skinning
requires it. This is numeric spatial weight painting, not a viewport cursor stroke.

## Geometric mirroring

`weights.mirror_geometric(object_name, source_vertex_indices, vertex_indices,
group_mapping, axis, plane_offset, coordinate_space, max_distance,
protected_groups=[])` reflects explicit source vertices through the chosen axis
plane and resolves each target to one unambiguous nearest reflected source within
the stated distance. `group_mapping` contains explicit `source_group` and
`target_group` names; no `.L`/`.R` naming or symmetry plane is inferred.
Ambiguous ties, missing correspondence and unsupported scope fail before edits.
Source weights are frozen before writing, including overlapping mappings.

## Closest-surface transfer

`weights.transfer_surface(source_object, object_name, source_polygon_indices,
vertex_indices, group_mapping, coordinate_space, max_distance,
protected_groups=[])` finds the closest point on the explicitly selected source
base-mesh polygons and barycentrically interpolates the mapped source groups.
It uses Blender loop triangles and the chosen metric, without evaluated topology
or automatic source-region inference. `WORLD` includes each object's transform.
`LOCAL` transforms source world coordinates into the target object's local frame;
the target matrix must be invertible. The distance threshold uses that chosen
frame, so non-uniform scale can change correspondence relative to `WORLD`.

All geometry-aware weight tools are bounded to 4,096 base vertices and polygons
per object, 16,384 edges and the existing 128-group budget. Brushes accept 1–1,000 explicit
vertices and 1–32 dabs. Mirrors accept at most 1,024 explicit source vertices
and 256 targets. Surface transfer accepts at most 256 source polygons, 2,048
selected loop triangles and 256 targets; source inspection is capped at 8,192
loop triangles. Mirror/surface correspondence is capped at 262,144 pair tests.
Group mapping contains 1–16 explicit pairs. An over-budget request is rejected
rather than silently sampled.
Target groups must exist, be unlocked and not be named as protected. Locked source
groups may be read. Unmapped groups, vertices outside the target list, source
objects, geometry and editor context must remain unchanged. Protected group names
make an explicit preservation requirement; they do not expand mutation authority.

## Verification and limits

Writes are permission/state checked, read back and tracked with partial-failure
and measured recovery evidence. Frozen evidence includes mesh identity, ownership,
base topology, coordinates and memberships; per-write and compensating-recovery checks revalidate ownership, group locks
and complete base geometry before each membership write. These synchronous
checks prioritize preservation; no hard latency or production-scale throughput
promise is made. An error requires reinspection; a checkpoint or
attempted local restoration is not a transaction or durable backup. Native undo,
Windows, production-scale character acceptance and full CHAR-01 remain open.

The disposable `weight_brushes` native runner fixture corrects a small skinned
character through brush, geometric mirror and barycentric surface transfer.
It measures actual evaluated vertex motion, preserves a locked detail group and
other objects, and checks permission and lock denial. Run only through
`scripts/run_blender_checks.py`; no user scene or project save is involved.
Record the actual Blender version and report before claiming native support.
