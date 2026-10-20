# Shader properties and color ramps

Unreleased on `main`; not included in the published 0.3.0 downloads. These structured tools
edit reviewed native shader properties and complete Color Ramp definitions at a material
root or an explicit [nested group path](shader-groups.md). No arbitrary Python is required.

## Tools and scope

All three tools belong to the `nodes` toolset. Names identify exact datablocks/nodes; no
selection, visual proximity or dotted RNA path is used to guess a target.

| Tool | Parameters beyond `material_name`, `node_name` | Blender permission |
| --- | --- | --- |
| `nodes.inspect_properties` | Optional `group_path`, `sample_positions` | `INSPECT_SCENE` |
| `nodes.set_properties` | Required `settings`; optional `group_path`, `allow_shared=false` | `EDIT_MATERIALS` |
| `nodes.set_color_ramp` | Required complete `stops`; optional `interpolation`, `color_mode`, `hue_interpolation`, `group_path`, `allow_shared=false` | `EDIT_MATERIALS` |

Inspection returns normal bounded node/ownership state plus reviewed property availability,
types, read-only flags and native enum identifiers. Use identifiers from the installed
Blender version, not guessed display labels. Enum lists are bounded to 128 entries and
report truncation; empty separator entries are not useful editing choices. For a ramp,
inspection returns all supported stops/modes and up to 32 native sampled RGBA values.
Default sample positions are `[0, 0.25, 0.5, 0.75, 1]`; pass `[]` to omit sampling.
Sampling is numeric shader evidence, not a rendered-appearance verdict.

Both mutations require Object Mode, local editable non-override material/target trees and
complete ownership evidence. Root and nested targets use the existing material/shared-group
guards. Sharing through parent groups still counts: `users=1` does not establish isolation.
Explicit `allow_shared=true` acknowledges all reported users; it does not bypass linked data
or incomplete scope. Isolate material/group instances first when other objects must not change.
The target tree is limited to 256 nodes / 1,024 links / 128 interface items. Direct animation
on the chosen material or target tree (action, drivers or NLA tracks) returns `NOT_IMPLEMENTED`.
This is not a claim to inspect every transitive animated/evaluated dependency.

## Reviewed properties

`settings` is a nonempty map of at most 32 direct scalar properties. Blender validates the
available property, type, enum and native bounds before any assignment. Unsupported node
types return `NOT_IMPLEMENTED`; unknown properties/values on a reviewed type are rejected.

| Node type | Reviewed properties |
| --- | --- |
| `ShaderNodeMath` | `operation`, `use_clamp` |
| `ShaderNodeVectorMath` | `operation` |
| `ShaderNodeTexNoise` | `noise_dimensions`, `noise_type`, `normalize` |
| `ShaderNodeTexVoronoi` | `voronoi_dimensions`, `distance`, `feature`, `normalize` |
| `ShaderNodeTexWave` | `wave_type`, `bands_direction`, `rings_direction`, `wave_profile` |
| `ShaderNodeTexGradient` | `gradient_type` |
| `ShaderNodeMixRGB` | `blend_type`, `use_alpha`, `use_clamp` |
| `ShaderNodeMix` | `data_type`, `blend_type`, `factor_mode`, `clamp_factor`, `clamp_result` |
| `ShaderNodeMapRange` | `data_type`, `interpolation_type`, `clamp` |
| `ShaderNodeClamp` | `clamp_type` |
| `ShaderNodeNormalMap` | `space`, `uv_map` |
| `ShaderNodeUVMap` | `uv_map`, `from_instancer` |
| `ShaderNodeVectorTransform` | `vector_type`, `convert_from`, `convert_to` |
| `ShaderNodeBsdfPrincipled` | `distribution`, `subsurface_method` |

Normal Map and UV Map `uv_map` accept an empty name or validated non-control UTF-8 text up to 63 bytes.
It does not create a UV layer or prove that every consuming mesh has that layer. Inspect the
relevant mesh UV data before using a named map. Other shader settings, pointers, attributes,
Script/IES and file paths are not exposed by this tool. Image Texture settings remain in
`nodes.set_image`, including its approved-source/file-permission checks.

Before/after verification compares all target socket identifiers/types/defaults and semantic
tree links (including mute state). A native setting with an incompatible structural/default
side effect fails rather than silently rewiring the graph. This does not certify all
evaluated effects or appearance; use `nodes.set_input` for explicit socket values and
normal structured link tools for intentional wiring.

## Complete Color Ramp replacement

`stops` contains 1–32 objects with exactly `position` and `color`:

```json
[
  {"position": 0.0, "color": [0.005, 0.015, 0.06, 1.0]},
  {"position": 0.5, "color": [0.015, 0.32, 0.3, 1.0]},
  {"position": 1.0, "color": [0.8, 0.95, 0.9, 1.0]}
]
```

Positions must be finite numbers from 0 to 1 in nondecreasing order. Tied positions preserve
the requested color-index order. Colors are four finite **scene-linear RGBA** components
between 0 and 1,000,000; HDR values are supported, not silently clamped to display RGB.
Inputs are normalized to native float32 before comparison. Booleans, malformed colors,
unknown keys, unsorted stops and invalid modes are rejected before replacement.

This replaces the **entire** definition, not selected stops. Omitting a mode preserves its
current stored value. Only an exact `ShaderNodeValToRGB` node is accepted. Complete replacement
has a destructive MCP annotation because omitted stops are removed; it does not delete
objects/datablocks or require `DELETE_OBJECTS`. Like other material edits, it requires consent
and an appropriate logical recovery point.

The inspector distinguishes stored settings from their native interpretation:

- RGB uses the stored `interpolation`; hue wrapping is inactive.
- HSV/HSL use effective linear interpolation and the stored hue-wrapping mode. The stored
  interpolation remains visible but is inactive, even if it says `CONSTANT`.

`interpolation_active`, `effective_interpolation` and `hue_interpolation_active` make this
explicit. Verify actual samples and a matched material/rendered capture; property names alone
do not establish the requested hard edge, gradient or material appearance.

## Revision and recovery workflow

1. Inspect scene/mode/selection, target node, native settings/samples and all affected users.
   Capture the current appearance and relevant protected group contents. Create a checkpoint.
2. Isolate material/group instances where needed. Use `batch.plan` / `batch.execute` for a
   coherent revision, e.g. Noise dimensions, its W input and a new palette in one batch.
3. Reinspect changed settings, complete stops, semantic links and socket defaults. Compare
   protected data independently, then capture a matched view and refine if required.
4. On failure, inspect `rollback_verified`, `possible_mutation`, `execution_started` and
   `verification_required`. Ramp failures also retain `before_color_ramp` evidence. Scoped
   restoration is attempted and **measured**, not guaranteed. Use confirmed native snapshot
   recovery and repeat structural/visual comparison when needed.
5. Save only in the agreed workflow with `SAVE_PROJECT`. These tools do not save files,
   change user preferences, load external images or grant permissions.

Mutations run through the main-thread dispatcher with live permission/pause/stop gates and
normal history/checkpoints. A batch is not a transaction. Finite native undo and manual edits
still matter; see [recovery availability](native-recovery.md).

Root `shader_inputs` [snapshots](scene-evidence.md) now include the reviewed properties and
root ramp modes/stops, detecting changes even when node/stop counts match. Nested contents
are still **not hashed**: separately inspect and compare each relevant group's settings,
ramps, sockets and links. Neither field comparison nor a successful tool response proves the
whole user goal or transitive scene preservation.

## Native evidence and remaining work

`blender_shader_settings_smoke.py` exercises all 14 reviewed node types on Windows Blender
4.5.1/5.1.2, root same-count comparisons, nested group isolation, native enums, one/32 stops,
tied positions/HDR, permission/pause/stop and direct-animation rejection. It injects real
partial ramp failures, measures local restoration versus unresolved mutation, and verifies
confirmed native recovery with protected source data and selection/active object/mode intact.
The connected Noise/ramp fixture has matched warm, cool, RGB hard-step and recovered captures;
the other reviewed node types have property/state evidence, not individual rendered QA.
The fixture keeps default undo capacity and does not save user projects or preferences.
Run it through the [non-interrupting Windows runner](native-testing.md), not as a direct UI script.

This is a bounded look-development increment, not complete LOOK-01, scenario B or 1.0
acceptance. Broader shader properties/curves/collections, animated ramp lifecycle, group
interface editing/conversion, nested snapshots, image lifecycle/painting/baking, compositor
coverage and representative reference-constrained asset workflows remain mandatory work in
the [full 1.0 plan](plan-1.0.md).

Native semantics: [ColorRamp API](https://docs.blender.org/api/4.5/bpy.types.ColorRamp.html)
and [Blender's color-band evaluator](https://raw.githubusercontent.com/blender/blender/v4.5.1/source/blender/blenkernel/intern/colorband.cc).
