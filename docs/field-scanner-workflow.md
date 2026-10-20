# Face attributes and the reference-scanner workflow

Unreleased on `main`, not in the published 0.3.0 packages. This increment connects modeling,
UVs, textures and look development on an original reference asset. It does not certify a
complete 3D artist, production delivery or all of scenario B in the [1.0 plan](plan-1.0.md).

## Structured face shading and slot assignment

`mesh.create` accepts optional `face_smooth`: exactly one strict boolean per input face,
up to the existing 100,000-face bound. Flags are prevalidated, copied, applied and read back
before the new object is linked. Omission keeps native flat-face defaults. Existing creation
permissions remain `EDIT_MESH` and `TRANSFORM_OBJECTS`. A failed readback uses scoped creation
cleanup. Inspect the returned smooth/flat counts and independently check geometry/appearance.

`mesh.set_face_attributes(object_name, selection_id, smooth?, material_index?)` changes one
or both reviewed attributes on 1–20,000 referenced, non-hidden faces. It requires the named
active single-object Edit Mode mesh, local non-override object/data and a single-user mesh.
A fresh face selection reference is mandatory; stale/empty references are not guessed.
`smooth` is a strict boolean. `material_index` is an integer from 0–255 identifying a
non-empty **existing object material slot**. Resolve that index from current inspection or
the slot-creation result: Boolean operations can produce different slot layouts across
Blender versions. Never assume slot 1 is the desired material.

The enabled `mesh` toolset and live `EDIT_MESH` grant are always required. A material-index
change additionally checks **Blender-side `EDIT_MATERIALS`**, immediately before assignment
and after update; MCP cannot grant it. Smooth-only edits do not need material permission.
The registry's static requirement is `EDIT_MESH`; the material requirement is conditional.
No materials are created/edited, no topology or UV edit is requested, and selection is retained.
These are polygon smooth flags, **not** custom/split-normal editing or automatic smoothing.

The operation participates in the existing logical mesh-edit session. It reads back target
flags and selection. On assignment/update/cancellation/readback failure it attempts to restore
the old attributes and reports measured `rollback_verified` / `possible_mutation` evidence.
The error still requires reinspection; a failed call is not a successful edit or a transaction.
Unresolved effects retain the edit-session recovery point. Reinspect attributes, geometry,
UVs and preserved scope, then capture the relevant appearance before accepting the result.

Face-region extrusion also now supplies the region's complete unique edge set to native
BMesh. This lets Blender remove an attached original base cap without deleting the base of
a standalone open region. Regression checks cover a cube's attached face and standalone
one-/two-quad regions, with closed edges, positive volume and confirmed native recovery.
This is not a general guarantee of intersection-free extrusion or outward/custom normals.

## Original reference and reproducible workflow

The owned [brief](../tests/fixtures/field_scanner/brief.json) and
[three-view vector reference](../tests/fixtures/field_scanner/reference.svg) specify metre units,
50-micrometre numeric tolerance, a chamfered orange shell, recessed telemetry display,
three controls, four cut grille pockets, four fasteners and an open carry handle.
The reference is a qualitative design target; numeric Blender state supplies measurements.

Run the native fixture only through the [non-interrupting runner](native-testing.md):

```powershell
.\.venv\Scripts\python.exe scripts/run_blender_checks.py --blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" --case field_scanner --output build/scanner-check
```

Use a new output folder. Windows UI fixtures run on a private, non-input desktop, never a
visible fallback. The scanner is built in a disposable factory scene through typed bridge
dispatch: 16 initial parts including four explicitly owned cutters, 12 final components,
wire-loop bridging/capping, inset/extrusion, exact Boolean pockets, selected face attributes,
UV authoring and non-destructive bevels. Cutter deletion has a negative permission test and
explicit fixture consent. Raw Python execution and project saving stay disabled. Native
Python in the test only prepares negative controls/owned texture files, injects faults and
independently measures results; it is not a client escape-hatch tool.

Evidence includes:

- Base world dimensions **144 × 51 × 260 mm**, closed positive-volume components and an
  evaluated **86 × 24 mm** handle opening with unobstructed depth rays.
- Full shell/display base-mesh UV maps: complete bounded analysis, no positive-area overlap,
  mirrored/folded or degenerate triangles. At 1024², shell density is approximately
  1,616 pixels/metre with near-unity directional stretch. The 500 × 350 display atlas is
  explicitly front-priority: roughly 3,543 pixels/metre in front and lower back/side density,
  a deliberate approximately 3.04 ratio, not a uniform whole-asset atlas.
- Nested materials with explicit UV Map nodes, sRGB color images and Non-Color roughness
  data. The reviewed shader map now includes `ShaderNodeUVMap.uv_map` / `from_instancer`;
  names do not create UV layers or prove every consuming mesh has them.
- Matched green calibration / blue telemetry variants through versioned `nodes.refresh_image`;
  original cached pixels retained, shader links/roles inspected, front/isometric/wire and
  UV-layout captures retained for actual visual review.
- Material denial before face assignment, a native post-update face failure with measured
  local restoration, and a real non-atomic material batch failure after one valid edit.
  Confirmed native undo restores independently compared meshes, UVs, nested graphs and pixels.
- Fourteen build stages recovered separately at unchanged **32-step** history; original
  object/mesh/material/group/image names and protected snapshot scope match afterward.
  Protected captures are compared before/after. This proves this small isolated workflow,
  not unlimited history, memory-pressure recovery, interleaved user edits or durable backup.

Visual refinement corrected a real extrusion interior cap and darkened the actual grille
walls as well as their floors: elevated views self-occlude these narrow deep pockets.
Numeric slot readback alone did not establish the intended dark appearance. Preview captures
are not final rendered production-delivery acceptance.

The fixture calls add-on dispatch directly. It does **not** replace MCP transport, packaged
installation/upgrade, production-scale performance, paint/sculpt/bake, full-asset evaluated
UVs, deep dependency/pixel lifecycle, character/animation/simulation, cinematic or export
acceptance. Temporary factory recovery files/captures are confined to the test output;
the user's project and preferences are not saved or changed. Fixture markers deliberately
leave `full_artist_acceptance_verified` false and require visual review. Reports record
Python source hashes plus explicit brief/reference and owned texture hashes.
