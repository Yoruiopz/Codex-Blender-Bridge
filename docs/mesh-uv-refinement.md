# Explicit rail slides and UV refinement

Unreleased structured modeling/UV foundations. These tools support a measured prop-panel
revision; full retopology, surface projection, automatic rail correspondence, UV-editor
selection, global self-intersection and production artist acceptance remain open.

On a local single-user active Edit Mode mesh, inspect topology and create a fresh selection
reference. `mesh.slide_preview` accepts `mode="VERTEX"` or `"EDGE"`, explicit
`targets=[{"vertex_index": ..., "target_vertex_index": ...}]`, `factor` in `[0,.95]` and a
positive `max_distance` in **local mesh units**. Each target must be one stationary visible
neighbor joined by an existing edge. No side or surface correspondence is guessed.

Vertex mode moves only the explicitly mapped vertices inside the referenced vertex scope.
Edge mode requires exactly one rail for every vertex of one complete connected, nonbranching
selected chain or loop. The preview returns measured coordinates/displacements and a
fingerprint of geometry, selection, UV layers/pins and material assignment. Repeat its exact
inputs and `expected_fingerprint` through `mesh.vertex_slide` or `mesh.edge_slide`; changed
coordinates, topology, selection or UV state require a new preview.

Slides reject shape keys, unsupported ownership, hidden/nonmanifold rails and affected
triangle/quad fan degeneration or inversion. They preserve topology, non-target vertices,
UV coordinates/pins, selection and material slots. Fan checks do not prove collision freedom,
global surface quality or arbitrary ngon safety. Snapshots are bounded to 500000 UV corners
across layers; targets are bounded to 4096 vertices.

The `uv` toolset adds three operations, each requiring exact UV-layer names and a fresh face
selection reference:

- `uv.align(corners, axis, value)` places explicit corners on one U/V line. A pinned target
  off that line rejects the request before writes; pins are never silently cleared.
- `uv.stitch(pairs, max_distance)` copies fixed anchor corners to explicitly paired target
  corners of the **same mesh vertex**, within the UV distance bound. Anchors cannot also be
  moving targets. This changes corner coordinates; it does not weld topology or infer a
  complete seam/island correspondence.
- `uv.relax(face_indices, iterations, strength, max_displacement)` smooths one explicitly
  enumerated complete UV island. Exact matching endpoint UVs across shared manifold edges
  define continuity. Island boundaries and any pinned UV node stay fixed. Uniform Laplacian
  planning is limited to 4096 corners, 50 iterations and 200000 node-iterations; the requested
  displacement bound and per-face fan orientation are checked before any UV write. Edge
  energy is numeric evidence, not a conformal unwrap, texel-density or artistic certificate.

UV operations preserve geometry, all other layers, pin flags, selection and active-layer
roles. They reject triangle/quad fan collapse or inversion rather than claiming a valid UV
result after a degenerate edit. Near-matching islands are not silently welded by relaxation.

All mutations run through Blender's main-thread structured dispatch and live mesh-edit
permission, pause/stop and cancellation checks. Failure attempts local restoration only
while editing permission remains enabled and the owned output has not been replaced.
Denied recovery or interleaved edits report possible mutation; use independently verified
native recovery. A checkpoint is not a durable backup and no tool automatically saves.

The `mesh_uv_refinement` native case revises a checker-textured prop panel while preserving
its frame/materials, verifies coordinates and UVs independently, injects a UV publication
failure, captures matched material/wire/UV evidence, and restores the actual whole Edit Mode
session through native checkpoint recovery. Run it through the isolated native runner; it is
a UI-dependent case. Review captures for silhouette/topology/checker appearance separately
from numeric evidence. Windows and Blender-version qualification remain release gates.
