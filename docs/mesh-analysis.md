# Measured mesh quality (unreleased)

`mesh.analyze` is a read-only structured tool in the `mesh` toolset, requiring only
`INSPECT_SCENE`. It diagnoses the **whole explicitly named base mesh** in Object/Edit Mode,
including unflushed Edit BMesh data reached through a linked Object Mode alias. It uses
each object's own refreshed world transform. No selection, active layer, geometry or
viewport is changed by the tool. Inspection remains available while paused or stopped.

It is unreleased development, not part of published 0.3.0. It complements the compact
`mesh.inspect`; it does not silently change that older tool's result contract. Neither
tool alone certifies a production asset or replaces structural and visual iteration.

## Topology and face orientation

The result reports measured vertex/edge/face/corner counts, plus bounded index examples for:

- Loose vertices (no incident edges), and other non-manifold vertices.
- Boundary edges (one incident face), wire edges (zero), over-connected edges (more than
  two), and the aggregate of edges without exactly two incident faces.
- Inconsistent winding across two-face manifold edges, using Blender's native contiguous
  edge flag. This is adjacent face-order consistency, **not outwardness or shading normals**.
- Edges at or below the caller's world-space distance tolerance. N-gons are counted but
  are not automatically defects.

Categories can overlap; do not sum them as unique defects. Boundaries and wire geometry may
be intentional. A completely inward but consistently wound closed shell can pass the winding
check. Custom/split normals, normal-map tangents, evaluated modifiers, shape-key poses,
clearance, solid containment, other objects and artistic topology flow are not assessed.

## Crossing and contact candidates

Blender's native BMesh `calc_loop_triangles()` tessellates the base faces, including concave
n-gons; no UV fan or visual inference is used. A bounded adaptive spatial grid supplies
candidate pairs, with a separately budgeted fallback for large triangle bounds. Pair-local
double-precision math classifies:

- `crossing`: positive-length intersection segments cutting through both triangle interiors.
- `boundary_contact`: positive-length segments on one or both triangle boundaries, including
  possible unwelded joins or T contacts. These are not necessarily crossings.
- `coplanar_overlap`: positive projected-area overlap within the declared near-coplanar
  tolerances; the reported area is projected, not surface/union/solid volume.
- `near_parallel_ambiguous`: non-separated near-parallel pairs not resolved as coplanar.
  These prevent completeness rather than being silently skipped.

Topologically shared non-coplanar edges are ordinary joins and excluded. Shared-vertex
pairs are still tested, as are coplanar overlaps across a shared edge and self-overlap
between triangles of the same face. Point-only contacts and sub-threshold intersections
are excluded by definition. Examples identify current native triangle and base-face indices;
unique face-pair counts are separate from triangle-pair counts. These are candidates to
inspect, not a robust solid Boolean or universal self-intersection certificate.

`distance_tolerance` defaults to `1e-6`, allowed `1e-12`–`1e-2`, in **world coordinate units,
not meters**. Areas at or below its square are near-zero; those triangles are skipped and
make intersection coverage incomplete. Near-parallel normals use sine tolerance `1e-8`.
Coplanar clipping also has projected area tolerance
`max(distance_tolerance², 1e-12 * pair_projected_extent²)`, computed through normalized
pair-local clipping rather than imposing a fixed world-area floor on small assets.
Nearly coincident separate surfaces can be reported within tolerance. Choose tolerances
for the asset scale; do not weaken them merely to get a pass.

## Completeness and resource limits

Only objects in the current view layer are supported; other modes or off-layer world-state
evaluation return `NOT_IMPLEMENTED`. Local/world positions must be finite and at most `1e12`
in magnitude. Unsafe local positions are rejected with bounded indices before native
conversion/evaluation. Dependency-graph refresh can run normal user handlers; this is not
a promise to suppress arbitrary add-on callbacks.

Global limits are 200,000 vertices+edges+faces and 200,000 corners. The caller can set:

- `max_triangles`: default 8,192, at most 20,000.
- `max_pair_tests`: default 250,000, at most 1,000,000; counts unique broadphase candidates,
  including candidates subsequently rejected by their bounds.
- `max_reports`: default 64, at most 256 examples per category.

When the triangle budget is exceeded, topology remains available but intersection metrics
are not computed. Exhausted pair budgets retain findings so far but never imply zero
remaining crossings. Missing tessellation, skipped near-zero triangles, near-parallel
ambiguity or coordinate precision too coarse for the requested tolerance also prevent
completeness. A triangle is precision-limited when a world coordinate's floating-point ULP
exceeds `distance_tolerance / 8`. Empty surface meshes are incomplete, not clean.

Detail truncation (`examples_truncated`) is separate from incomplete computation.
`analysis_complete`, `analysis_truncated`, and `verification.status` explain the outcome;
`numeric_checks_passed` only means these declared checks passed. `user_goal_verified`
always remains false. Indices must be refreshed after edits, undo, mode or file changes.
There is no selected-region or cross-object collision mode yet; exceeding whole-mesh limits
must not be worked around by pretending partial geometry is a complete asset check.

## Practical workflow and evidence

Inspect the object and relevant selection first. Run `mesh.analyze`, narrow the issue using
its bounded indices and existing component inspection, and capture an appropriate wireframe
or surface view. Preserve protected data with [scoped baselines](scene-evidence.md).
Checkpoint before using [repair](mesh-repair.md), [loop tools](mesh-loops.md), or normal
recalculation; reanalyze and compare actual attributes, review the image and recover if
constraints were violated. Save only with the user's authorization and permission.

`blender_mesh_analysis_smoke.py` diagnoses a deliberately reversed cube face, repairs it
through typed tools and independently recovers the original winding and complete baseline.
It checks a protected duplicate, crossing/stacked triangles, an over-connected edge,
concave tessellation, degenerate/empty/wire meshes, unsafe data, precision limits, revoked
permissions, pause/stop and separate computation/detail budgets. Same-timer object scale
and live linked-data reads are independently asserted. A tiny stacked-triangle fixture at
`1e-8` scale verifies the caller's smaller tolerance rather than inheriting a world-area floor.
The winding repair independently preserves positions, vertex/edge/face membership, per-vertex
UVs/pins, material slots/indices and transforms. Matched Object Mode captures show
shape/protected-state preservation; winding correctness is numeric, not inferred from wire
colors. The connected prop recipe also checks contacts and adjacent winding after its cut.
On the tested Windows fixtures, 8,192 clean-grid triangles required 98,056 candidate tests
and roughly 1.70–1.85 seconds for full analysis. Those are host/fixture observations, not a
production latency or scale guarantee.
No user `.blend` is used or saved. Broader assets, outward/custom-normal diagnosis,
localized checks and full release acceptance remain open.
