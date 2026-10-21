# Reference surface projection

`mesh.surface_projection_preview` and `mesh.project_to_surface` fit an explicit
working patch to explicitly named base reference polygons. This is a bounded
manual retopology aid, with measured correspondence and protected-data checks.
The caller supplies the working topology using the existing mesh creation,
repair, cuts and slide tools.

Both tools take `object_name`, a fresh vertex `selection_id`, `source_object`,
`source_polygon_indices`, and `max_distance`. Apply also requires the exact
current preview's `expected_fingerprint`.

The working mesh must be the active local, editable, single-user Edit Mode mesh.
Its object/owning collection ancestry must belong only to the current scene,
with no incoming consumers outside ordinary scene/collection membership.
The separate visible reference must be a local Object Mode mesh in the current
view layer; a read-only second consumer of its data is permitted. Both meshes
must have no modifiers, shape keys or custom shading normals. The tools never
switch modes or infer a source from visual proximity. Distances use world
coordinate units, which are not necessarily meters.

The fixed policy is nearest point on the explicit **base** surface, with zero
normal offset. There are no evaluated polygon mappings or guessed vertex rails.
An equally near result with a different position is ambiguous and rejected;
shared-edge triangles producing the same position are allowed. Source triangles
must be nondegenerate and the object matrices must be finite and invertible.

## Bounds and proof

- 1–256 fresh referenced moving vertices and 1–256 explicit source polygons.
- At most 20,000 vertices + edges + faces per mesh, 2,048 selected source
  triangles, 2,048 whole working-mesh fan triangles and 262,144 geometric pairs.
- At most 300,000 protected custom-layer entries, plus the existing bounded UV
  snapshot. Unsupported attribute domains/types or native custom-layer families
  return a structured unsupported result before writing.
- Repeated per-write source/target preservation proof is bounded to 2,000,000
  aggregate items; deform influences count toward the custom-data budget.
- Per mesh: 64 attributes, 256 vertex groups/material slots and 16 UV layers.
- At most 64 correspondence records in a response; truncation is explicit.

Preview computes proposed world hits, converts them to native float32 local
coordinates, then checks actual stored displacement and residual world surface
distance. The residual must be at most `1e-6`; `max_distance` bounds the actual
displacement. The fingerprint covers current source/target geometry, identities,
transforms, ownership, selection, context, protected data and operation policy.

The entire working mesh must contain triangle/quad faces. Its proposed fan
triangles must preserve orientation and nonzero area and pass the bounded
triangle contact check completely. Existing unrelated contacts or uncertainty
also reject this conservative working-mesh contract. Point-only contacts and
ordinary topological joins follow the diagnostic kernel's documented exclusions.
This does not certify solid containment, clearance, other objects, evaluated
geometry or artistic quality.

Supported protected state includes untouched vertex coordinates, topology,
selection/hide flags, seams/sharpness/smoothing, material bindings, UV layers and
pins, native UV selection, deform weights, supported color and generic custom-data layers, their
active roles, group definitions and object transforms. Unsupported protected
data is rejected rather than silently dropped from the proof. Material shader
contents and unrelated scene objects require separate scene evidence.

## Mutation and recovery

Preview requires `INSPECT_SCENE`; apply requires `EDIT_MESH`. Every write follows
live consent, exact native Edit-session and ownership checks, and complete frozen
source/protected-target revalidation. A Python BMesh wrapper address is not used
as a persistent native session identity. Native dependency-graph refresh may run
the user's handlers; those handlers are not sandboxed by this tool.

The tool records attempted targets before assignment. Failure/cancellation
attempts local coordinate restoration only with live edit permission, the
original session/ownership, unchanged protected data and still-owned outputs.
Revoked permission, replaced source/session or interleaved output prevents that
restoration. Errors report `execution_started`, `rollback_verified` and
`possible_mutation`; inspect current state and use the explicit logical/native
checkpoint recovery path when necessary. No project is saved automatically.

## Acceptance and remaining work

The `mesh_surface_projection` native fixture builds a curved reference with a
second shared-data consumer and a separate displaced working patch. It measures
the resulting distance with Blender's independent triangle helper, preserves the
outer boundary, UV pins/spare map, POINT/CORNER colors, scalar data, weights and
material. Named `.vs`/`.es` BOOLEAN custom data is measured separately from
Blender 5.2's actual mesh-global `BMLoop.uv_select_vert`/`uv_select_edge`,
`BMFace.uv_select` and `BMesh.uv_select_sync_valid` flags. The fixture varies the
actual flags over all faces, verifies true/false sync-valid states through
failure/application, and proves native undo restores the original serialized
state. Earlier Blender versions preserve their actual per-layer UV flags.
It also exercises denied consent, publication-failure restoration and an
actual native Edit-session undo. Matched material and wire captures require
visual review. Platform/version results belong in the runner's report; this
document alone is not evidence of a passing run.

Full ASSET acceptance still requires explicit open/unequal/multi-loop cells,
evaluated reference inspection and diagnostics, corner-normal editing/outward
orientation, explicit shared-data isolation and keyed coordinate ownership,
and reviewed production-quality retopology workflows. These remain required
follow-on contracts, not capabilities supplied by projection.
