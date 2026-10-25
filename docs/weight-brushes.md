# Bounded weight brushes, geometric mirrors and surface transfer

These unreleased structured tools extend vertex-group authoring with an explicit
skinning workflow. They require `EDIT_MESH`, the `weights` toolset, Object Mode and
local, editable, non-override, single-user target mesh data. Targets and source
regions are named explicitly; active selection is not interpreted as consent.
They never change topology, normalize weights, create groups or save the project.

The separate [direct assign/normalize guard](weight-edit-safety.md) retains
pre-provider intent and field-only recovery in source. Its bounded ordinary
stock native call window is implemented but awaits native qualification. It does not change or qualify
the three geometry-aware brush/mirror/transfer handlers described here.

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
Evidence also has a joint bound: at most 65,536 scalar values across the target
and distinct source snapshots, and 8,388,608 comparison values for the conservative
forward-write, maximum-compensation and native-update/readback schedule. Polygon
corner counts and dense memberships count toward the aggregate snapshot budget.
The individual argument maxima above remain unchanged; some combinations exceed
the joint evidence budget and return `NOT_IMPLEMENTED` before a weight setter.

Target groups must exist, be unlocked and not be named as protected. Locked source
groups may be read. Unmapped groups, vertices outside the target list, source
objects and base geometry are compared completely within the admitted snapshot.
Protected group names
make an explicit preservation requirement; they do not expand mutation authority.

## Verification and limits

Each handler retains its method, registry/spec and caller lifecycle services before
its first permission callback. Its immutable original is captured inside the
admitted handler, before later planning callbacks. This does **not** provide
pre-provider checkpoint admission: changes made by earlier executor/checkpoint or
initial permission providers are outside this original. That entry-admission gap
remains open and blocks a complete SAFE/CHAR preservation claim.

Before every membership setter, restoration setter, mesh update, object update-tag
and view-layer update, live permission/cancellation providers run first. Native
callables are resolved afresh after those providers; complete target/source
comparison and the canonical pure lifetime/toolset/spec/stop gate follow. No
permission provider runs between that comparison and its native call. Object,
Mesh and Scene identities require positive native pointers and session UIDs;
Python object identity is not a fallback. Declared context comparison covers the
Scene, Object Mode and current frame/subframe. Selection, active object, editor
layout, view-layer identity and unrelated scene dependencies are outside this
snapshot; these tools do not intentionally set selection.
Vertex-group checks use fresh resolution and unchanged name/index/lock inventory;
persistent native identity and remove/recreate detection for these non-ID groups
remain unqualified.

All memberships, including protected and not-yet-written values, must match the
expected owned prefix using exact Blender Float32 storage bits. Expected new
weights are computed before native readback. Every attempted setter is journaled;
its result must match the complete precomputed old or new candidate. An unknown
partial result, newer manual edit or changed ownership refuses compensation.
Lost permission, lifetime, tool identity or stop authority is sticky and prevents
later setters and native update/cleanup calls. Recovery restores only verified
owned writes while the complete prefix and current authority still match.

Success and failure include bounded, plain `weight_mutation` recovery facts with
attempted/verified write and update counts and original/expected/observed hashes.
Unknown current state has no observed hash; retained partial edits require
reinspection. History retention of these typed facts must be integrated and
verified separately from handler results. These synchronous checks make no hard
latency or production-scale throughput promise. A checkpoint, undo history or
attempted local restoration is not a transaction or durable backup. Native undo,
Windows qualification, production-scale character acceptance and full CHAR-01
remain open; Windows work is deferred until implementation is complete.

The disposable `weight_brushes` native runner fixture corrects a small skinned
character through brush, geometric mirror and barycentric surface transfer.
It measures actual evaluated vertex motion, preserves a locked detail group and
other objects, and checks permission and lock denial. Run only through
`scripts/run_blender_checks.py`; no user scene or project save is involved.
Record the actual Blender version and report before claiming native support.
