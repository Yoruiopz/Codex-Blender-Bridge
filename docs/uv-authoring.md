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

The seven authoring/lifecycle tools below were added after the published 0.3.0 alpha.
All require Blender's `EDIT_MESH` permission
and the enabled `uv` toolset. No Python/file permissions or object deletion are needed.

## Coordinates, transforms and pins

These three tools require one explicitly named, active, local, non-override, single-user
mesh in **single-object Edit Mode** and an existing, explicitly named `uv_layer`.
They use BMesh directly: no operator, implicit layer activation or selection changes.
The new [bounded edit guard](uv-edit-safety.md) restricts the complete native mesh,
storage and consumer profile. Published 0.5.0 has selected registered-tool native
checks within that profile; see [its exact-source evidence](releases/0.5.0.md#verified-evidence).
Later source needs its own qualification. The bounded implementation does not
complete F02, native undo or durable recovery.
Use standalone calls. These guarded children are refused by `batch.plan` and
`batch.execute`; the public argument shapes and permission requirements are unchanged.

| Tool | Inputs and behavior |
| --- | --- |
| `uv.coordinates_set` | `updates`: records with `face_index`, `corner_index` and a two-number `uv`. Requires `selection_id`; every corner must belong to its referenced face scope. Duplicate corners, invalid/hidden scope and invalid coordinates reject the requested UV edit before its field writes. Explicit coordinate placement can move a pinned corner, without changing its pin. |
| `uv.transform` | Two-component `offset`, `scale` and `pivot`, plus counterclockwise `rotation` in radians. Order: scale relative to pivot, rotate, then offset. Defaults are origin pivot, unit scale, zero rotation/offset. `respect_pins=true` skips pinned corners; set false explicitly to move them. |
| `uv.pin` | `pinned=true` pins the scoped corners; false unpins. Coordinates are unchanged. Use it to establish individual unwrap anchors or pin an entire face/island scope. |

Transform and pin default to every corner of the selected or referenced **mesh faces**, not
the UV editor's implicit selection. Both accept optional `corners`, a list of exact
`{face_index, corner_index}` records. Indexed corner scope requires a `selection_id` and must
stay within its faces. Use bounded `uv.inspect(include_coordinates=true)` pages to obtain
face/corner indices, and `mesh.select_components` for an explicit face reference.

Index records must be unique. Native admission is narrower than the former 20,000-corner
authoring path and generic component-inspection limits; use the complete-mesh, map and
joint verification bounds in the [guard profile](uv-edit-safety.md#admitted-profile).
Source, request and result values must fit that numeric/storage profile. Vector pairs
are rounded to Float32 before transform arithmetic, and resulting stored values are
independently checked by Float32 bits, including signed zero. UVs are not clamped to [0,1],
so admitted tiled coordinates are possible. Requests also remain subject to transport
frame limits. The authoring MCP inputs reject
boolean/string coercion for numeric/boolean controls and reject extra corner-record fields;
Blender independently validates typed arguments immediately before execution.

Selection references identify geometry/topology and face scope; they do not lock UV values.
The guard freezes one original plan before providers/checkpointing and compares the complete
supported authored state and expected write prefix before each native edit. Reinspect after
UV edits, topology/map changes, scene/layer/mode changes or undo; old references are not locks.

Only known owned field writes can be compensated while live authority and the complete
expected state still match. Authority loss, cancellation, stop, drift or an unknown native
outcome stops further writes, including restoration and mesh updates. Inspect reported partial
state before retrying; `rollback_verified` requires measured original-state equality. Coordinate
edits never restore untouched pins, and pin edits never restore untouched UVs. No-op edits
(including all corners skipped because pinned) issue no UV/pin writes or unnecessary mesh update;
normal checkpoint/history bookkeeping remains visible. The measured Edit Mode marker-only
checkpoint is not an independent native undo boundary or a durable backup. See the
[failure/history contract](uv-edit-safety.md#failure-recovery-and-history).

Results report coordinate/pin change counts, targeted and skipped corners, target-only bounds,
bounded corner identifiers, and preservation/verification metadata. No result declares a UV
layout artistically acceptable or proves absence of overlap/distortion.

## Layer lifecycle

These four tools require a local, editable, non-override, single-user mesh and **Object Mode**.
The new three-mutator edit guard does not qualify this separate lifecycle path.
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
author admitted UVs and pins, independently reinspect, compare protected data and review a
relevant visual capture. A mode change does not itself verify native recovery. Recheck recovery
capabilities and evidence explicitly; save only through a supported authorized save path.
See [recovery](mesh-edit-recovery.md) and [bounded scene comparisons](scene-evidence.md).

Historical runs of `blender_uv_authoring_smoke.py` exercised the earlier seven-tool
implementation and permission denials on Windows Blender 4.5.1 and 5.1.2. They covered
first/last layer lifecycle, source copy including versioned UV
selection, role preservation, name/companion collisions, confirmed removal recovery, individual
anchors, exact corner movement, pivot/scale/rotation, out-of-scope rejection, real BMesh update
fault rollback, protected geometry/materials/UV layers and grouped native recovery. A disposable
two-face checker surface is captured before and after: the deliberate mapping change is local
to the edited face, while the other face and geometry remain fixed. The distorted checker is an
intentional coordinate-edit test, not an approved unwrap or texel-density result. No user
project is used or saved. [UV-coordinate layout captures](mesh-loops.md#uv-coordinate-visual-evidence)
now provide atlas evidence, and [UV analysis](uv-analysis.md) adds bounded overlap/stretch/density
checks. Bounded [alignment/stitch/island relaxation](mesh-uv-refinement.md) also exist under
their separate profiles. UV-editor view/selection tooling, cross-object/evaluated atlases,
broader quality coverage and production asset acceptance remain open. None of these historical
results accepts the new direct-edit guard, its recovery or current Windows compatibility.
