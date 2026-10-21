# UV authoring (unreleased)

Scoped unwrap/Smart Project/packing preserve the actual native UV selection.
Blender 4.3/4.5 use per-layer BMLoopUV flags; Blender 5.2 uses mesh-wide
`BMLoop.uv_select_vert`, `uv_select_edge`, `BMFace.uv_select` and
`BMesh.uv_select_sync_valid`. The temporary scope sets and then restores those
fields, including a previously invalid sync state. Legacy-named `.vs`/`.es`
custom attributes are not substituted for the mesh-wide native flags.
Inspection identifies the storage and validity; an invalid native sync state
has no authoritative selected-loop count. Full context preservation is bounded
to 200,000 mesh elements and 200,000 corners. Operator, restoration and final
mesh-update failures retain separate evidence; inspect before retrying.

Main adds seven structured tools beyond unwrap, Smart Project, packing and inspection.
They are not included in the 0.3.0 downloads. All require Blender's `EDIT_MESH` permission
and the enabled `uv` toolset. No Python/file permissions or object deletion are needed.

## Coordinates, transforms and pins

These three tools require one explicitly named, active, local, non-override, single-user
mesh in **single-object Edit Mode** and an existing, explicitly named `uv_layer`.
They use BMesh directly: no operator, implicit layer activation or selection changes.

| Tool | Inputs and behavior |
| --- | --- |
| `uv.coordinates_set` | `updates`: records with `face_index`, `corner_index` and a two-number `uv`. Requires `selection_id`; every corner must belong to its referenced face scope. Duplicate corners, invalid/hidden scope and invalid coordinates reject the **whole** edit before mutation. Explicit coordinate placement can move a pinned corner, without changing its pin. |
| `uv.transform` | Two-component `offset`, `scale` and `pivot`, plus counterclockwise `rotation` in radians. Order: scale relative to pivot, rotate, then offset. Defaults are origin pivot, unit scale, zero rotation/offset. `respect_pins=true` skips pinned corners; set false explicitly to move them. |
| `uv.pin` | `pinned=true` pins the scoped corners; false unpins. Coordinates are unchanged. Use it to establish individual unwrap anchors or pin an entire face/island scope. |

Transform and pin default to every corner of the selected or referenced **mesh faces**, not
the UV editor's implicit selection. Both accept optional `corners`, a list of exact
`{face_index, corner_index}` records. Indexed corner scope requires a `selection_id` and must
stay within its faces. Use bounded `uv.inspect(include_coordinates=true)` pages to obtain
face/corner indices, and `mesh.select_components` for an explicit face reference.

At most 20,000 scoped face corners are accepted; index records must be unique. The containing
mesh must fit component inspection's 200,000-element budget. UV values, vector components
and transformed results must be finite within ±1,000,000. Blender stores float32 UVs; the tool
quantizes expected values and checks the resulting storage. UVs are not clamped to [0,1], so
explicit tiled/UDIM-space work is possible. Large requests also remain subject to transport
frame limits; submit smaller coherent edits when necessary. The new authoring MCP inputs reject
boolean/string coercion for numeric/boolean controls and reject extra corner-record fields;
Blender independently validates typed arguments immediately before execution.

Selection references protect geometry identity/topology and face scope, **not UV-value
concurrency**. Reinspect after UV edits, topology changes, scene/layer/mode changes or undo.
Do not reuse old coordinates as if the UV editor were locked.

All writes are precomputed. A failure or deadline during writing attempts a local restoration
of the targeted coordinates and pins, reporting `rollback_verified`; if recovery cannot be
verified, stop and reinspect. Session recovery remains available after returning to Object
Mode; these are not independent native undo steps inside an open editor. A no-op (including
all corners skipped because pinned) does not update mesh data.

Results report coordinate/pin change counts, targeted and skipped corners, target-only bounds,
bounded corner identifiers, and preservation/verification metadata. No result declares a UV
layout artistically acceptable or proves absence of overlap/distortion.

## Layer lifecycle

These four tools require a local, editable, non-override, single-user mesh and **Object Mode**.
They do not switch modes, affect topology or make the mesh single-user automatically. Limits:
eight UV layers and 200,000 mesh corners. Names are exact, non-empty and at most 63 UTF-8 bytes.
Collisions with mesh attributes and reserved UV companion attributes are rejected.

| Tool | Behavior |
| --- | --- |
| `uv.layer_create(object_name, new_name, copy_from?)` | Create zero, unpinned UV data or copy coordinates and pins from the explicitly named source. Existing active/render/clone roles are preserved; a first layer receives Blender's defaults. Copy buffers are independently read back. |
| `uv.layer_rename(object_name, uv_layer, new_name)` | Rename the layer. Shader/Geometry Nodes/other named consumers are **not rewritten**; inspect and update dependencies explicitly. |
| `uv.layer_activate(object_name, uv_layer, for_render=false, for_clone=false)` | Make it the active layer. True options additionally assign render/clone roles; false leaves those roles unchanged rather than clearing them. |
| `uv.layer_remove(object_name, uv_layer, confirm_remove=true)` | Explicitly discard that layer's coordinates, pins and applicable per-layer UV selection. Without confirmation, reject. Active roles may fall back. Named consumers are not rewritten. Checkpoint first. |

UV selection storage differs by Blender version. On 4.5, creation copies per-layer corner/edge
UV selection when copying a source, otherwise initializes it to false. On 5.1, UV selection is
mesh-global and is preserved, not duplicated/reset for a new map. The result's
`uv_selection_policy` distinguishes `COPY_PER_LAYER`, `ZERO_PER_LAYER` and
`PRESERVE_MESH_GLOBAL`. Mesh object/component selection remains unchanged in all cases.
Optional all-false pin storage can be absent; the implementation handles its native storage
without legacy per-corner mesh-RNA pin writes. Other versions still need release evidence.

Layer creation attempts removal of only its new layer and restoration of activation flags on
failure; rollback verification is explicitly scoped to that inventory/metadata. Rename and
activation attempt local restoration too. Removal relies on the native operation checkpoint,
not a promise of local transactional rollback.

## End-to-end work loop and evidence

Inspect ownership, scene/selection and UV state first; snapshot protected objects and fields.
Create/copy/rename the desired layer in Object Mode, activate intentionally, then create a
logical checkpoint and enter Edit Mode through `context.set_mode`. Resolve face/corner scope,
author UVs and pins, independently reinspect, return to Object Mode to finalize grouped
recovery, compare protected data and review a relevant visual capture. Save only if authorized.
See [recovery](mesh-edit-recovery.md) and [bounded scene comparisons](scene-evidence.md).

`blender_uv_authoring_smoke.py` exercises all seven tools and permission denials on Windows
Blender 4.5.1 and 5.1.2. It covers first/last layer lifecycle, source copy including versioned UV
selection, role preservation, name/companion collisions, confirmed removal recovery, individual
anchors, exact corner movement, pivot/scale/rotation, out-of-scope rejection, real BMesh update
fault rollback, protected geometry/materials/UV layers and grouped native recovery. A disposable
two-face checker surface is captured before and after: the deliberate mapping change is local
to the edited face, while the other face and geometry remain fixed. The distorted checker is an
intentional coordinate-edit test, not an approved unwrap or texel-density result. No user
project is used or saved. [UV-coordinate layout captures](mesh-loops.md#uv-coordinate-visual-evidence)
now provide atlas evidence, and [UV analysis](uv-analysis.md) adds bounded overlap/stretch/density
checks. UV-editor view/selection tooling, relax/stitch/alignment, cross-object/evaluated atlas
checks, broader quality coverage and production asset acceptance remain open.
