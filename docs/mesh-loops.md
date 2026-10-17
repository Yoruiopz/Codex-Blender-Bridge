# Loop modeling and a connected prop workflow (unreleased)

Main adds three structured mesh tools and a UV-coordinate capture. These are not in the
0.3.0 downloads. They extend the [repair primitives](mesh-repair.md) and
[UV authoring](uv-authoring.md); they do not imply complete modeling or artist coverage.

## Preview and cut a quad ring

`mesh.edge_ring_inspect(object_name, seed_edge_index, selection_id?, cuts=1, offset=0,
max_items=100)` is read-only and requires `INSPECT_SCENE` plus the enabled `mesh` toolset.
It walks opposite edges through a complete connected quad strip and returns open/closed
state, measured edge centers, counts, and expected topology for the proposed cuts. Pages
contain at most 256 edges; follow `next_offset` when `truncated` is true. The traversal is
complete even when its returned edge page is truncated. Preview does not reserve the mesh.

`mesh.loop_cut(object_name, seed_edge_index, selection_id, cuts=1)` inserts 1–32 evenly
spaced cuts through that **entire ring**, including unselected edges/faces. A fresh edge
selection reference containing the seed is mandatory. Preview first and resolve the full
propagation scope before authorizing the cut; selecting one edge does not limit it to one face.

Both require the named active single-object Edit Mode mesh, at most 4,096 ring edges and the
200,000-element component-inspection budget. Hidden affected geometry, non-quad termination,
non-manifold ring edges and self-crossing/non-simple strips are rejected explicitly. Cuts
also require `EDIT_MESH`, local/non-override/single-user mesh ownership and no shape keys.
The output budget and exact expected vertex/edge/face counts are checked. UVs, weights and
face attributes are interpolated by native BMesh; verify the attributes relevant to the task.
Spacing is even, with no edge slide, smoothing, modifier application or implicit mode change.
Unsupported non-quad/non-manifold routes return `NOT_IMPLEMENTED`, not a partial guessed cut.

## Bridge two loops

`mesh.bridge_loops(object_name, selection_id, twist_offset=0, material_index=0)` bridges
exactly two disjoint closed boundary/wire loops, each with 3–1,024 edges. Scope comes from
the fresh edge selection reference. Open/branched/interior-edge or more-than-two-loop input
is rejected. The same modifying ownership/context/permission requirements above apply.

Equal-sized loops produce native quads; unequal loops produce a native triangulated strip.
No vertices are merged. For equal loops, twist magnitude must be smaller than each loop's
size. **Nonzero twist for unequal loops returns `NOT_IMPLEMENTED`**: direct native probes
show Blender ignores it. Do not treat a successful native response as proof an option worked.
There is no automatic twist optimization, multi-loop pairing or explicit unequal correspondence.

New faces use the requested existing material slot (zero also works without slots), with
zero, unpinned UVs in every existing layer. Old face material/UV data is not replaced.
Vertex/edge/face growth and created-face area are checked; zero/non-finite-area output fails
with possible-mutation/recovery evidence. Non-planarity, crossings, normals and triangulation
still need structural and visual review. In particular, a nonzero twist can create an
undesirable hourglass/crossing shape even when its counts and face areas are valid.
Unexpected native output is not a local transaction: reinspect and recover the edit session.

## UV-coordinate visual evidence

`uv.capture_layout(object_name, uv_layer, selected_only=false, selection_id?, size=512,
view="UNIT_TILE")` creates a managed temporary PNG from measured base-mesh UV corners.
It requires `INSPECT_SCENE` and `CAPTURE_VIEWPORT` with the `uv` toolset enabled. It does
not change selection, mode, UI, scene data or Render Result and needs no external-path grant.

Blue lines are face edges, red squares are pinned corners, and gray lines show the 0–1 tile
and its quarters. U increases right and V increases up, with equal scale on both axes.
`UNIT_TILE` includes a small border and reports outside-view corners; `FIT` includes all
scoped coordinates, including tiled/UDIM-space UVs. Numeric view bounds are returned.

Limits are 256–1,024 square pixels, 4,096 faces, 16,384 corners, coordinate magnitude at most
1,000,000 and four million raster steps. Budget/invalid-data failures produce no partial
image; narrow selected/reference scope or reduce image size. Object and Edit Mode are supported;
selection references require Edit Mode. Images use the bridge's managed capture directory
and retention policy, never a caller-supplied output path.

This is a coordinate plot, **not a UV-editor screenshot, texture preview, overlap detector,
stretch or texel-density verdict**. Coincident edges can hide overlapping faces. Use numeric
inspection and surface/material captures alongside it; do not measure precise values from pixels.

## Verified connected recipe

`scripts/blender_prop_workflow_smoke.py` uses a disposable disconnected box-section prop and
a protected duplicate sharing its material. Through typed dispatcher calls it:

1. Captures protected baselines and starts a logical checkpoint; creates a working UV map.
2. Bridges the two boundary loops and previews/cuts the closed quad ring, checking exact
   topology, new vertex positions and retained dimensions/weights/source-map values.
3. Derives seams from inspected face normals/connectivity, unwraps and packs six
   non-degenerate islands, then captures the UV layout and wireframe.
4. Copies the finish for only the repaired object and edits Principled/checker inputs;
   checks protected numeric state and before/after material images.
5. Recovers five logical boundaries in reverse (shader edit, surface settings, material copy,
   grouped mesh/UV session, UV-map creation) and independently compares the original baseline.

Windows Blender 4.5.1/5.1.2 numeric and reviewed visual evidence shows the gap closed, a new
middle loop, six packed charts, a blue checker finish only on the repaired prop, unchanged
protected appearance, and the original gap restored on recovery. Additional cases cover
equal/unequal wire loops, an equal-loop twist that changes correspondence, and two evenly
spaced cuts in an open quad strip. The twisted example is a control test, not approved topology.

The fixture configures its view framing explicitly and restores temporary framing; this is
not a new scene-navigation feature. It invokes the actual Blender dispatcher but is not a
clean packaged MCP-client installation test. No user `.blend` is used or saved. Recipe recovery
is staged, confirmed global snapshot navigation, not an atomic transaction or durable backup.
Broader asset diversity, UV quality diagnostics, normals/crossing checks, production scale,
other modeling tools and release/install/upgrade acceptance remain in the 1.0 scope.
