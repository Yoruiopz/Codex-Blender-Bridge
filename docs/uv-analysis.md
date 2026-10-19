# Measured UV quality (unreleased)

`uv.analyze` adds read-only overlap, winding, pixel-stretch and texel-density evidence to
the [authoring tools](uv-authoring.md) and [layout images](mesh-loops.md#uv-coordinate-visual-evidence).
It is on main, not in the published 0.3.0 download. It requires `INSPECT_SCENE` and the `uv`
toolset, not edit/capture/Python/file/save permissions. Inspection also works while paused/stopped.

## What it measures

The tool uses Blender's **BMesh `calc_loop_triangles()`** tessellation, not a fan from UV corner
zero. This matters for concave n-gons and folded maps. It reads the named base mesh/UV layer
in Object or Edit Mode without activating the layer, changing selection, applying modifiers
or writing geometry. It refreshes the dependency graph so a preceding transform assignment
is reflected in `matrix_world`. Blender may evaluate its normal user handlers during refresh.
The object must belong to the current view layer; evaluated/modifier/sculpt/paint states and
off-layer world transforms are not covered.

Shared mesh data can be in live Edit Mode even when the named linked object reports Object
Mode. UV inspection, layout capture and analysis read the owning live BMesh in that case,
not the stale Object Mode mesh copy. `mesh_data_state` identifies the source; each object's
own world transform still determines its density. Newly added, unflushed UV layers appear
in inspection. Render/clone flags are `null` when no matching RNA layer exists yet.
Selection references still require the actual named Edit Mode owner; this read support
does not enable shared-data UV mutation or borrow another object's selection reference.

For each native triangle it measures:

- Positive-area UV intersections, including self-overlap between triangles of one face.
  Shared edges/vertices are not overlap. Intentional stacked islands still appear as overlap.
- UV signed winding: negative triangles are mirrored relative to their corner order;
  mixed positive/negative winding inside a face is flagged as folded. Mirroring may be intentional.
- World surface area and UV/pixel area, using the object's complete world transform.
- The singular values of the local world-surface-to-pixel mapping. Their ratio is
  `max_pixel_anisotropy` (1 is isotropic). Face reports expose directional density extrema
  and a worst native triangle index; this is not a claim of equivalence to Blender's overlays.
- Scalar triangle density, `sqrt(UV area * width * height / world area)`: the geometric mean
  of directional densities, in **pixels per world coordinate unit, not meters**. Rectangular
  images and non-uniform object scale affect the results. Scene-unit conversion is not inferred.

`texture_resolution` is caller-declared, defaulting explicitly to a hypothetical 1024×1024.
No image/material resolution is guessed. Set it to the actual texture dimensions before
using density for a delivery decision. `density_target` is optional; `density_tolerance`
defaults to ±20%. Every measured triangle is checked against it, not only a face average
that could hide local variation. Face `density` remains an area-based aggregate, while the
global density min/max and per-face triangle-density extrema expose variation.
`anisotropy_warning` defaults to 4 and must be at least 1; these are review thresholds, not
universal artistic rules.

## Scope, completeness and limits

Required: exact `object_name` and `uv_layer`. Optional `selected_only` / `selection_id`
restrict the mesh-face scope. `face_indices` can narrow it further without altering selection;
indices must exist within the selected/referenced scope. Selection references require Edit Mode.
Excluded faces, other objects and other UV layers are **not checked for collisions**. Indices
are current base-mesh/tessellation indices, not durable identifiers across edits/undo/mode changes.

Global safety limits are 200,000 vertices+edges+faces and 200,000 corners. Scope is bounded
to 10,000 faces / 40,000 corners. `max_triangles` defaults to 8,192, at most 20,000;
`max_pair_tests` defaults to 200,000, at most 1,000,000; `max_reports` defaults to 64, at most 256.
The overlap broadphase uses a spatial grid and a budgeted large-AABB fallback; it does not
materialize every possible triangle pair. Dense/large checks can still exhaust the budget.

If the triangle budget is exceeded, **no partial metric summary is presented**. If the overlap
pair budget is exhausted, already-measured metrics and found overlaps remain useful but
`analysis_complete=false`, `analysis_truncated=true`, and verification is `incomplete`.
Invalid data or missing native tessellation also prevents completeness. Never interpret
“zero overlaps found so far” as proof of a clean map. In contrast, `face_reports_truncated`
or overlap `examples_truncated` limits returned details, not the already-computed aggregate
coverage. Increase report limits or narrow scope for more detail.

UV/world near-zero area cutoffs are each 1e-12 in their respective units; tiny valid triangles
can fall below them. Directional metrics at those cutoffs are undefined (`null`), not zero.
Overlap area tolerance is `max(1e-12, 1e-12 * pair_UV_extent²)`. Coordinates are normalized
for clipping to reduce cancellation. UV magnitude must be at most 1e6; local/world coordinate
magnitude at most 1e12. Unsafe local positions are rejected before native tessellation with
bounded vertex-index evidence. Invalid UV/world metric data is reported without NaN/Infinity
in the JSON response. Small/sub-threshold intersections may be ignored by design.

Overlap area is a **sum of triangle-pair intersections, not union area or occupied texture
coverage**; triple stacks can be counted multiple times. Face UV/pixel areas also sum native
triangles and can double-count folded/overlapping regions. Padding/bleeding, uniqueness across
objects/UDIM atlases, image content, normals, evaluated geometry and artistic suitability
still require other evidence. `numeric_checks_passed` only means these scoped checks passed
at their declared limits/thresholds. `user_goal_verified` always remains false.

## Practical loop and current evidence

Inspect the relevant layer, run `uv.analyze` with the real resolution and intended thresholds,
then compare its localized face reports with `uv.capture_layout` and a material/texture view.
Treat intentional stacks/mirrors according to the brief. Checkpoint before changing anything;
use scoped UV transforms/coordinates/pins to refine, repeat analysis/captures, compare protected
data, and save only with authorization. Do not weaken thresholds solely to make a test pass.

`blender_uv_analysis_smoke.py` diagnoses a known stacked pair, stretched chart and mirrored
chart, then transforms them into four separate padded square charts at 471.04 pixels/world
unit for a declared 1024×1024 texture. It independently verifies the numbers, unchanged
protected data/other layer/active layer, same-timer non-uniform world scale, and snapshot recovery.
It also checks concave L-face tessellation, a folded/self-overlapping quad, invalid UVs,
permission denial, paused/stopped inspection, and honest triangle/pair/report limits.
It also verifies linked Object Mode aliases against unflushed Edit Mode coordinates and a
new UV layer, without freeing the live BMesh, changing the active layer or losing recovery.

On the tested Windows 4.5.1/5.1.2 fixtures, an 8,192-triangle clean grid completes within the
default overlap budget (96,256 candidate pair tests). Early local runs measured roughly
0.19–0.22 seconds for the full analysis; those are fixture/host observations, not a latency
guarantee or production-scale acceptance. A regression test guards against the earlier sweep
approach exhausting 200,000 tests on the same clean grid. The connected prop workflow now
also analyzes its initial incomplete UV map and verifies its repaired six-chart result.
No user `.blend` is used or saved. Other platforms, broader assets and release acceptance
remain open.
