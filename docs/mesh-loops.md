# Loop modeling and a connected prop workflow (unreleased)

Development adds structured mesh tools and a UV-coordinate capture. These are not in the
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

## Preview and bridge two open chains

`mesh.bridge_chains_preview(object_name, selection_id, rail_a_start, rail_a_end,
rail_b_start, rail_b_end, material_index=0)` previews two disjoint equal-length open
boundary/wire chains, each with **2–64 vertices**. A fresh edge selection reference must
contain exactly those two selected chains. Supply all four endpoint vertex indices;
the tool follows each selected chain from its explicit start to end. It never chooses
endpoint correspondence, twists, reverses winding or merges vertices automatically.

For ordered rails `a` and `b`, the proposed quads are
`[a[i], a[i+1], b[i+1], b[i]]`. Preview returns every ordered rail vertex and face,
the exact topology delta and a session-bound fingerprint of the operation, native
identities, complete bounded original mesh data, selection and context. The result is
read-only and requires `INSPECT_SCENE`. It does not reserve the mesh.

`mesh.bridge_chains(..., expected_fingerprint)` requires `EDIT_MESH` and the exact current
preview fingerprint. It is nonbatchable and retains the same admission state through
checkpoint setup. With `k` vertices per rail it adds `k` connecting edges and `k−1` quads,
retaining all vertices and original topology. New faces use the existing requested
material slot (or zero without slots), flat shading and verified zero, unpinned UVs
in all existing layers. New mesh and UV components are deselected. New non-UV custom
data uses native initialization; existing supported values are compared independently.
Unwrap new faces separately.

Both methods require one named active, visible, local, editable, single-user Edit mesh
in the current Scene, without modifiers, shape keys or custom normals. The complete
mesh must fit the **20,000 output-element** and supported custom-data bounds inherited
from [base-surface evidence](mesh-surface-projection.md); an additional conservative
two-million-value domain-work estimate limits repeated preservation checks. These are
bounded evidence limits, not latency or process-memory guarantees.

Admission rejects branches, cycles, unequal lengths, shared vertices, hidden affected
geometry, interior selected edges, existing connecting edges/faces and degenerate or
folded quad fans. A surface rail vertex must have one connected manifold boundary face
fan with exactly two boundary edges and no wire attachments. Wire chains must be
complete, with no incident faces, branches or unselected wire extensions. Existing boundary winding
must oppose the new face direction; reverse endpoints explicitly when needed. This
checks affected vertex stars, not manifoldness of the whole project. General crossings,
clearance, evaluated correspondence and artistic quality still require separate review.

Original coordinates, topology, supported custom/deform/color values, all UVs/pins and
UV selection/active/render/clone roles, material bindings, group definitions and
mode/selection/active-object context are measured before and after. Literal comparison
distinguishes scalar types and signed zero. Each new allocation also protects every
earlier published bridge face/edge. Every further write checks live permission,
toolset/caller lifetime, pause/stop, exact native ownership and the retained state,
then runs the pure final request gate after the expensive reads.

After each fully verified face and requested material assignment, the tool updates
normals and synchronizes native edit-mesh tessellation with `loop_triangles=true`,
before attempting the next face. Each native interval has a separate live gate
and complete post-operation proof. This keeps already verified faces synchronized
when a later allocation fails before adding output. It does not run a repair in
the error handler or waive any authority check.

A failure or interruption can retain partial topology. Errors explicitly report
`execution_started`, `possible_mutation`, `created_faces_verified`,
`created_faces_count_complete` and `rollback_verified=false`; an allocation that failed
verification may exist beyond the verified-face count. No implicit deletion or compensating update runs after lost
authority. Reinspect and, once authorized, use existing confirmed **whole Edit-session**
checkpoint recovery when its availability is established. This is neither a local
transaction nor a durable backup. No project is saved.

The additive `derived_cache_sync` receipt distinguishes normal/update calls that
started and returned from complete verified syncs and the last verified face
count. On failure, `current_topology_sync_verified=false` remains conservative:
cancellation during allocation, unverified native output or lost authority before
synchronization can leave **unsynchronized partial topology**. Earlier completed
sync counters do not certify the current topology, safe dependency-graph evaluation
or native recovery. Restoring permission does not by itself establish those facts.
This increment does not complete cancellation/recovery qualification.

Portable tests cover this contract. The connected prop fixture includes open-boundary
repair, protected UV/pin/material/weight data, stale/permission/stop rejection, an
injected second-face failure, native Edit-session recovery and matched wire/checker
captures. Native execution and artistic review are separate evidence; no passing result
is claimed by adding the fixture. Open-wire/native-scale qualification, unequal and
multi-chain bridging, explicit unequal correspondence and the full ASSET-01 gate remain open.

The first source-frozen `80709d` run failed with native SIGSEGV on both reviewed
Linux versions after the injected second-face fault and before any successful
open-chain capture. That source synchronized only on success, without synchronizing
the retained first face before returning the injected error. The per-face follow-up
addresses the stale derived-cache hypothesis, pending native verification. The fixture retains all
protected comparisons, captures and native recovery assertions, with explicit stage
markers around post-fault comparison, mode exit and undo; none are bypassed.

### 2026-10-23 development verification

The source-matched connected-prop fixture at `a5baefc65cebc530f0ff9346f121a91020dd481b`
passed in two isolated UI processes on Linux Blender 4.5.14 LTS and 5.2.2 LTS.
It verifies the injected second-face failure, preservation, actual Edit-session recovery,
successful bridging and a second recovery. Report SHA-256:
`f2eacfa3c3803445339ff8a869b45e7430fa3a1016d988753aad5541d4824e6f`.
Retained wire/checker captures receive limited technical review; the new zero-UV faces
still need UV authoring and this is not artist acceptance.

The earlier `80709d4` fixture crashed on both runtimes during partial-edit recovery.
Its byte-verified negative archive is retained with SHA-256
`214db9dc990607c772dbd25720088ce00a8257220a47ea96b6b4b257e0b1fedc`.
The subsequent implementation synchronizes each verified face before another allocation,
with fresh authority checks and explicit synchronization receipts. Successful bounded
recovery does not qualify cancellation during allocation or all production recovery paths.

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
