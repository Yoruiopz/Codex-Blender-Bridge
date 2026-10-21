# Scoped scene snapshots and comparisons

Unreleased on `main`; these methods are not in the published 0.3.0 packages.
Both require Blender-side `INSPECT_SCENE` and run on Blender's main thread.

`scene.snapshot(object_names, fields?, max_elements=200000)` captures a baseline for
1–32 unique, exact object names in the current scene. `scene.compare(snapshot_id,
max_elements?)` reads the same fields again and reports the measured differences.
Baselines are stored in the bridge's memory cache. Derived transform, visibility and
shader reads first evaluate pending dependencies. The tools do not select objects,
change modes, create undo entries, set scene properties or save a project.

## Fields

The original eight fields are selected by default. Pass a smaller list when the task only
needs particular invariants or a large object exceeds the evidence budget. The new
`rig`, `animation` and `shader_dependencies` fields are opt-in so existing callers keep
their previous scope and work budget.

| Field | Measured state |
| --- | --- |
| `transforms` | World/local matrices, location, scale, rotation representations, delta transforms, parent-inverse matrix and dimensions |
| `hierarchy` | Parent identity/type/bone, object-data identity and collection memberships |
| `visibility` | Object viewport/render hide flags, per-view-layer hide state and current visibility |
| `mesh_geometry` | Base mesh coordinates, edge endpoints/seam/sharp flags, loop connectivity and polygon ranges/material indices/smooth flags; numeric counts included |
| `uv` | UV layer names, active/render layer state, loop coordinates and pins |
| `weights` | Vertex-group definitions/locks and per-vertex group memberships/weights |
| `material_slots` | Ordered object material-slot bindings and DATA/OBJECT link mode |
| `shader_inputs` | Referenced material identities, node usage, root node names/types/mute state, root input/output defaults, referenced group/image identities and exact socket links; [reviewed root properties and Color Ramp modes/stops](shader-settings.md); root Image Texture interpolation/projection/extension and bound-image source/path/color space/alpha mode/packed state |
| `rig` (opt-in) | Armature identity/pose position; ordered rest-bone names/parents, head/tail/local matrices and reviewed deformation/inheritance settings; current pose transforms/matrices, transform locks and reviewed IK limits/weights |
| `animation` (opt-in) | Animation definitions on the object, its data and shape-key datablock: active legacy/layered action identity and routing, layer/strip/channel-bag order, slots, curves, keyframe values/handles/interpolation/easing, sampled points, driver definitions/targets, NLA track order/flags and strip settings/action bindings |
| `shader_dependencies` (opt-in) | Root plus reachable nested shader-tree state covered by `shader_inputs`, group-interface socket/panel order and reviewed defaults/settings, complete group reference edges and shared-tree identities |

Mesh geometry, UVs and weights apply to mesh objects. Other object types receive
an explicit `not_applicable` digest for those fields. `rig` similarly reports
`applicable=false` for non-armature objects. Curve, camera and light data remain outside
this comparison; armature data requires the explicit `rig` field. Mesh fields become incomplete while
that mesh's data is in Edit Mode, including shared data edited through another object.
Armature rest/pose evidence becomes incomplete in Armature Edit Mode.

The response always lists unmeasured state. It includes evaluated geometry,
modifiers/constraint definitions, simulation caches, shape-key geometry and unlisted rig/B-Bone settings,
other mesh attributes/custom normals, material/node settings beyond the reviewed state,
image pixels/file contents and unlisted image settings, scene/world/render settings,
custom properties, selection, viewport settings, transitive dependencies and visual appearance. For example,
`material_slots` alone does not cover polygon material indices; include `mesh_geometry`
to check those. These are specific field comparisons, not a whole-object guarantee.
Reviewed properties and complete ramps detect same-count edits; they do not cover
arbitrary node RNA, material/node-tree animation or image pixels. A ramp beyond the
32-stop evidence budget makes the field incomplete rather than returning a partial checksum.

For [nested shader edits](shader-groups.md), root group identities may match even when a child
changed. Include `shader_dependencies` to measure those contents, or separately inspect each relevant
group. Each material is limited to 32 distinct trees including its root, depth 8, 128 interface
items per tree and the same per-tree node/link limits. Shared groups are hashed once per material;
recursive dependencies or exhausted budgets make evidence incomplete rather than silently skipping
a child. The inspector does not access image dimensions/pixels, decode buffers or follow file paths.

`animation` reads definitions without evaluating driver expressions or resolving arbitrary data paths.
It follows referenced active/NLA actions, including Blender 4.4+ layered actions, but does not follow
driver target state or collect arbitrary material/node-tree animation. Future motion/deformation still
needs independent sampled-frame verification. F-Curve modifiers currently make animation evidence
incomplete because their type-specific settings/control points are not covered. Arbitrary action
custom properties and unlisted NLA/action settings remain outside the measured contract. Rig evidence
is a current rest/pose comparison, not a skinning/deformation or complete constraint certificate.

## Results and limits

`schema_version=1` identifies the evidence format. Large collections are streamed
into SHA-256 digests; full vertex/UV/weight arrays are not returned or retained.
Transforms also return their numeric values, and mesh evidence includes counts.
Floats are compared exactly; there is no hidden tolerance or visual inference.

Each comparison reports one of:

- `unchanged_within_scope`: every selected field was captured completely and matched.
- `changed`: at least one measured field, object identity/type or name resolution changed.
  Read `coverage_complete` as well; other fields may still be incomplete.
- `unknown`: no confirmed difference was found, but coverage is incomplete. This is not a pass.

Missing/ambiguous targets are rejected at baseline creation. Later deletion, rename,
replacement or name ambiguity is reported during comparison. A scene rename is allowed
when its session identity still matches; switching scenes or view-layer names is rejected.
Before/current scene metadata and frame numbers let the caller assess context changes.
Missing Blender session-identity support makes coverage incomplete.

The per-call record budget defaults to 200,000 and accepts 1–1,000,000. Encoded record
bodies are also limited to 16 KiB each and 64 MiB total. Material root graphs are capped
at 256 nodes/1,024 links and object material slots at 256. Exhaustion or a value that
cannot be represented faithfully produces `complete=false` with a reason, without a
misleading checksum. Cancellation is checked during traversal; Blender's native dependency
update itself cannot be preempted. Data-only mesh checks avoid unnecessary dependency updates.

Shared mesh/UV and material data are hashed once per call where possible. The cache keeps
the latest eight baselines in FIFO order. Baselines survive undo so restored state can be
compared, but file replacement and add-on shutdown clear them. They belong to the add-on
runtime/project, not an individual TCP connection. A reconnect still requires current
status/context inspection. Expired, evicted or foreign IDs return `INVALID_ARGUMENT`.

Comparison defaults to the original record budget. Increase its `max_elements` when the
current object grew beyond that budget; this can verify against a complete earlier baseline.
It cannot recover evidence missing from an incomplete baseline. Capture a complete baseline
before an edit when the selected invariants must be checked afterwards.

## Protected material workflow

1. Inspect the scene, selection and relevant objects. Create a logical checkpoint for the edit.
2. Call `scene.snapshot` for the protected mesh objects and keep the returned `snapshot_id`.
3. Use `material.copy_for_object` to isolate the intended object's material, then edit that copy.
4. Call `scene.compare` with the protected baseline. Require complete coverage of the needed
   fields and `unchanged_within_scope`; inspect any difference or unknown field.
5. Reinspect changed data, capture a matched view for appearance, and refine or recover if
   the result violates the request. Save only through the agreed save workflow.

The same sequence can compare numeric state after explicit snapshot recovery. The tools
provide evidence; they do not automatically authorize, block, roll back or save edits.
`user_goal_verified=false` remains explicit because the user goal and visual quality require
the broader inspection/comparison loop.

## Verification

`blender_scene_evidence_smoke.py` checks material isolation with a protected shared-mesh
duplicate; shared shader edits; same-count geometry edits; UV and weight changes; incomplete
budgets; inspection-permission denial; cache lifecycle; and preserved selection/mode.
`blender_undo_lifecycle_smoke.py` additionally compares a complete numeric baseline after
native snapshot recovery. These are disposable fixtures on Windows Blender 4.5.1/5.1.2.
The [image-asset recipe](image-assets.md) also compares binding/sampler/source metadata across
material isolation, texture revision and recovery without reading pixels through evidence tools.
The [shader-settings recipe](shader-settings.md) independently detects same-count root
property/ramp edits and checks recovery, while separately comparing nested group content.
They do not establish full protected-character or production-scene acceptance.

The extended `scene_evidence` fixture additionally detects nested shader changes, keyframe edits,
NLA scaling, driver target changes and current rig poses with the opt-in fields. A focused Linux
Blender 4.3.2 background run passed at
`build/scene-evidence-rig-animation-20261022-b/report.json`; this is dirty-source development
evidence with `release_readiness=NOT_ASSESSED`, not Windows 4.5/5.x or release qualification.
