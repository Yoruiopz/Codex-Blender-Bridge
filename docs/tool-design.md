# Tool design

> This document records the published **0.2.0 baseline**. For the 20 additional tools and behavior in unreleased 0.3.0, see [agent workflows](agent-workflows.md).

A bridge tool is a stable contract between an agent intent and a permission-gated Blender handler. Structured tools are task-shaped, typed, bounded, context-honest, recoverable, and independently verifiable; they are not thin aliases for arbitrary `bpy` functions.

## Design rules

Every public tool should:

- represent one coherent inspection or operation;
- validate names, types, ranges, enums, list sizes, result limits, and finite numbers;
- state mode, selection, area, object/data type, units, and coordinate-space requirements;
- declare every required Blender permission and its toolset;
- identify affected data and return measured post-state;
- participate in checkpoint/history behavior in proportion to its risk;
- raise stable structured failures and retain detailed diagnostics locally;
- preserve temporary mode, selection, active object, view, visibility, and settings where practical.

Prefer a small set of composable operations over hundreds of fragile operator-shaped wrappers. Prefer direct data APIs and `bmesh` over `bpy.ops`; when an operator is necessary, establish and restore its complete context.

## Two registries, one contract

The MCP registry owns public names, wrappers, descriptions, annotations, lazy toolset exposure, and forwarding. It does not import `bpy` or authorize Blender access.

The Blender registry owns handlers, permissions, toolsets, mutation classification, pause/emergency behavior, checkpoint policy, local/remote visibility, and execution history. It is authoritative. Registry parity tests must catch missing names, mismatched permissions, duplicate registration, and the deliberate local-only exception.

Version 0.2.0 has **89 add-on methods** and **88 MCP tools**. `checkpoint.restore_last` is registered only for Blender's confirmed local recovery UI.

Conceptually:

```python
registry.register(
    "transform.translate",
    translate_object,
    toolset="objects",
    permissions=(Permission.TRANSFORM_OBJECTS,),
    modifies=True,
)
```

The executor performs exact lookup, verifies remote availability, toolset state, live permissions, pause/emergency state, and deadline, then runs the handler on Blender's main thread and records the outcome. There is no giant action-string dispatcher.

## Current surface

### Core

Core contains 16 remotely visible tools:

```text
bridge.status          bridge.task.set        bridge.task.clear
project.info           scene.inspect          scene.summary
selection.inspect      object.inspect         viewport.capture
checkpoint.create      checkpoint.undo_last   checkpoint.list
project.save           toolsets.list          toolsets.enable
toolsets.disable
```

Core availability does not bypass permissions. `viewport.capture` requires `CAPTURE_VIEWPORT`, inspections require `INSPECT_SCENE` where declared, and saving requires `SAVE_PROJECT`.

### Optional toolsets

All optional toolsets start disabled and are loaded/enabled as needed:

| Toolset | Count | Structured scope |
| --- | ---: | --- |
| `objects` | 11 | Object lifecycle, hierarchy/collections, exact transforms |
| `mesh` | 8 | Arbitrary bounded-topology creation, inspection, and selected normals/delete/dissolve/extrude/inset/bevel |
| `materials` | 8 | Material lifecycle, slots, assignment, Principled values |
| `nodes` | 7 | Material shader graph inspection and exact node/socket/link edits |
| `uv` | 4 | UV layers/islands, unwrap, Smart Project, packing |
| `modifiers` | 5 | Allowlisted modifier inspection/add/set/remove/apply |
| `constraints` | 4 | Allowlisted object constraint inspection/add/set/remove |
| `animation` | 5 | Bounded action/F-curve/key inspection, frame/range, key insert/delete |
| `rigging` | 9 | Armatures, edit bones, pose transforms/constraints, mesh binding |
| `scene_edit` | 7 | Scenes, collections, cameras, lights, and world background |
| `render` | 3 | Render inspect/configure/execute |
| `python` | 1 | Dangerous last-resort Blender Python |

Aliases such as `transforms`, `rig`, `cameras`, and `lights` map to their owning MCP toolset. `toolsets.list` is authoritative for the connected build.

This table is not a promise that every Blender operation has a structured tool. Geometry Nodes graph editing, compositor graphs, sculpt/paint, advanced weights/NLA, simulations, baking, retopology, and other specialist operations remain additional tool work or exceptional Python use.

## Permissions

| Permission | Current examples | Default posture |
| --- | --- | --- |
| `INSPECT_SCENE` | Project, scene, object, mesh, material, node, UV, animation, rig, modifier, constraint, render reads | on |
| `CAPTURE_VIEWPORT` | Viewport/camera capture and still-render result replacement | on |
| `TRANSFORM_OBJECTS` | Object lifecycle/transforms, modifiers, object constraints, some rig operations | on |
| `EDIT_MESH` | Mesh and UV mutations | on |
| `EDIT_MATERIALS` | Material lifecycle, Principled inputs, shader nodes | on |
| `EDIT_ANIMATION` | Frame/range, keys, armatures, bones, pose/rig constraints | on |
| `EDIT_SCENE` | Scene, collection, camera, light, world configuration | on |
| `EDIT_RENDER` | Render settings and still execution | on |
| `DELETE_OBJECTS` | Explicit object/data/material/collection/bone deletion paths | off |
| `EXECUTE_PYTHON` | Dangerous Python super-permission; every call also requires deletion, external-file, and save permission | off |
| `ACCESS_EXTERNAL_FILES` | Explicit save/render paths outside managed artifacts | off |
| `SAVE_PROJECT` | Save current project or approved new path | on |

A tool may require several permissions. Examples:

- `mesh.create` requires `EDIT_MESH` and `TRANSFORM_OBJECTS`;
- `rig.create` requires `EDIT_ANIMATION` and `TRANSFORM_OBJECTS`;
- `rig.bone_remove` requires `EDIT_ANIMATION` and `DELETE_OBJECTS`;
- `collection.delete` requires `EDIT_SCENE` and `DELETE_OBJECTS`;
- `render.execute` requires `EDIT_RENDER` and `CAPTURE_VIEWPORT`;
- an explicit render/save path additionally checks `ACCESS_EXTERNAL_FILES` inside Blender.
- `python.execute` requires `EXECUTE_PYTHON`, `DELETE_OBJECTS`, `ACCESS_EXTERNAL_FILES`, and `SAVE_PROJECT` together; narrower structured `EDIT_*` permissions do not contain raw `bpy` once armed.

Toolset enablement is an attention/reachability control, not authorization. Permission checks run immediately before execution so a revocation during queue wait takes effect. Denial returns `PERMISSION_DENIED` with bounded `missing_permissions` and performs no handler mutation.

## Naming and schemas

Names use lowercase `domain.verb`: `scene.inspect`, `material.set_principled`, `rig.bone_add`. Use `inspect` for bounded detail, `summary` for a compact LLM-oriented overview, and concrete verbs such as `create`, `set`, `add`, `remove`, `apply`, `capture`, and `execute` for mutations.

Request rules:

- named JSON objects, never positional arrays at the protocol boundary;
- exact object/data references for mutation; no fuzzy targeting;
- explicit units and spaces, with radians for programmatic rotations unless named otherwise;
- bounded strings, lists, traversal depth, image size, samples, frame ranges, code, and output;
- reject booleans where numeric values are expected, non-finite values, invalid combinations, and unknown mutation fields;
- treat `selection_id` as opaque and validate its session, object, mode, mesh fingerprint/revision, and component bounds.

MCP-side validation improves feedback; Blender-side validation protects current state. Never remove the latter.

Read results report compact facts and truncation. Mutations additionally report affected object/data identities, changed counts/properties, warnings, checkpoint/operation metadata, and measured post-state. Do not return Blender RNA objects, bytes, sets, NaN/infinity, or giant coordinate/node dumps.

## Read and mutation handlers

A read may perform temporary evaluation or view setup, but it must restore temporary state in a `finally` path. Keep default payloads small: pages, aggregates, bounded node graphs, capped keyframes/bones/islands, and explicit omitted counts.

A mutation follows this pattern:

1. Resolve exact targets and validate live context.
2. Let the executor check toolset, deadline, pause/stop, and permissions.
3. Capture minimal before-state and establish the logical checkpoint/undo boundary.
4. Perform the smallest deterministic operation.
5. Update Blender data/dependency state and restore temporary context.
6. Measure post-state and identify affected data.
7. Record success or structured failure honestly.

If an operation can partially apply, recover it or return the partial state and leave a usable undo path. A successful transport response is not verification.

## Checkpoints, history, and task state

Read-only tools do not create undo steps. Modifying handlers automatically participate in logical checkpoint/history behavior unless their descriptor says otherwise; callers should still create one user-level checkpoint before a coherent meaningful edit.

Blender's undo stack is global and exposes no reliable entry ownership. `checkpoint.undo_last` requires `confirm_global_undo=true`; the local panel confirms undo and multi-step restore. These controls can affect interleaved user edits and are not durable backups.

`bridge.task.set` displays a bounded high-level task in Blender. `bridge.task.clear` removes it when work is completed or abandoned. Task text supports human oversight; it grants no permission and is not an execution instruction by itself.

## Domain guidance

### Mesh and UV

`mesh.create` accepts fully prevalidated arrays of at most 100,000 vertices, 200,000 explicit edges, 100,000 faces, and 500,000 total face corners. It validates names, finite coordinates, every index, duplicate/self edges, repeated/duplicate face vertex sets, collection, transform, and Euler rotation mode before allocating Blender data. Failure cleans up partially allocated object/mesh data; success returns counts, local bounds, transform, and fresh mesh post-state without changing selection. It requires `EDIT_MESH` and `TRANSFORM_OBJECTS`.

Use `bmesh` when it avoids UI context for selection-scoped edits. Define whether the operation consumes live selection or a selection ID, which component types it supports, and what selection remains afterward. Reinspect topology or UV state after every change. Unwrap/projection/packing use Blender operators where required, with explicit object, mode, selection, and context restoration.

### Materials and shader nodes

Materials may contain arbitrary shader graphs. Inspect bounded node/link/socket state and address nodes and sockets explicitly. Principled helpers preserve unrelated graph structure; they do not model every material as one Principled node. Current `nodes.*` tools edit material shader trees only—not Geometry Nodes or the compositor.

### Modifiers and constraints

Only allowlisted types and direct RNA properties are writable. Do not accept reflective dotted traversal. Applying/removing a modifier or removing a constraint is classified conservatively and checkpointed.

### Animation and rigging

Inspect bounded curves, keys, bones, pose state, and constraints. Address explicit object/bone/data paths and frames. Restore mode/active/selection around armature edit or pose transitions. Current tools do not provide full NLA, driver editing, weight-paint diagnostics, or every constraint setting.

### Scene, camera, light, world, and render

Use explicit scene/object/collection names. Camera/light/world settings are bounded typed fields. Render configuration uses `EDIT_RENDER`; execution additionally uses `CAPTURE_VIEWPORT` because it replaces Render Result. Managed temporary output needs no arbitrary path permission, while user-provided output requires `ACCESS_EXTERNAL_FILES`. Captures/renders are visual evidence, not structural measurement.

### Projects and files

Saving requires `SAVE_PROJECT`; a new path also checks `ACCESS_EXTERNAL_FILES`. Normalize paths in Blender, require absolute approved destinations, reject unsafe/network-style paths and implicit expansion, and avoid overwrite unless explicitly allowed.

## Python fallback

`python.execute` is shipped as the exceptional long-tail path, not an implementation shortcut. It requires the `python` toolset; all four high-risk permissions `EXECUTE_PYTHON`, `DELETE_OBJECTS`, `ACCESS_EXTERNAL_FILES`, and `SAVE_PROJECT`; `confirm_dangerous=true`; and a non-empty `expected_effect` on each call.

This is intentionally a super-permission. Raw `bpy` can change mesh, material, animation, scene, render, and other domains without re-entering their structured `EDIT_*` gates. It can also delete data, use Blender file APIs, and save. The four broad permission toggles acknowledge that full authority; enabling or disabling narrower domain permissions does not sandbox the script.

The handler:

- caps source/stdout at 64 KiB each, result conversion at 4,000 global items/depth 8/4,000 integer digits with cyclic/shared container rejection, serialized `result` at 256 KiB, AST complexity at 8,000 nodes, and inputs at 1,000 entries;
- exposes `bpy`, JSON-safe `inputs`, bounded `print`, and a JSON-safe `result`;
- allows imports rooted at `bpy`, `bmesh`, `mathutils`, and `math`;
- rejects obvious filesystem/process/network/dynamic-code and double-underscore introspection paths;
- enforces a cooperative 0.1-30 second trace deadline and reports that long Blender C calls may not be preemptible;
- returns a code digest, expected effect, duration, bounded output, before/after data counts, object additions/removals, and `verification_required: true`.

`stdout_truncated` reports whether the independent 64 KiB print buffer filled. Script `result` conversion has one global 4,000-item budget, maximum depth 8, a 4,000-digit integer guard that rejects huge integers before stringification, and identity tracking that rejects cyclic or shared container references before recursively expanding them. The converted value is then measured against its dedicated 256 KiB budget. Any graph/scalar/byte-budget violation replaces the value with a small object containing `__truncated__: true`, a reason, original type, `maximum_bytes`, and `maximum_items`; the response also returns `result_truncated: true`, `result_bytes: null`, and `result_limit_bytes: 262144`. Unexpected post-execution conversion or size-check exceptions also degrade to this placeholder, so the audit/recovery envelope still returns. Callers must not interpret the placeholder as the script's intended result; narrow the returned summary or inspect Blender state directly.

This is an accident-prevention policy, **not a security sandbox**. Enabling Python means trusting the caller with broad access to the open Blender project. The bridge exposes no shell or network tool.

If execution starts and then raises or reaches the deadline, the error preserves the digest, expected effect, duration/stdout, coarse data-count/object deltas, `mutation_outcome_unknown: true`, and `verification_required: true`. The executor records a failed-possible-mutation history entry and finalizes the pre-created Blender undo step. Pre-execution validation or permission rejection does not claim that the script ran. After any started execution, inspect every affected data block and capture visual evidence when appearance matters before retry or confirmed global undo; then disable the toolset and return all four permissions to least privilege.

## Adding a tool

1. Define intent, target resolution, context, units, preservation constraints, post-state, limits, and unsupported cases.
2. Choose core/domain, permissions, mutation/destructive annotations, checkpoint policy, and verification evidence.
3. Add bounded non-Blender request/result concepts.
4. Implement the main-thread Blender handler in its domain module.
5. Register exact Blender metadata.
6. Add the thin MCP wrapper and lazy registry metadata without `bpy`.
7. Test schemas, boundaries, permissions, disabled toolset, wrong context, error mapping, timeout/disconnect, history/post-state, surface parity, and real Blender behavior where relevant.
8. Update current documentation only after registration and verification work.

## Anti-patterns

Do not add:

- a remote shell, raw operator-name dispatcher, generic reflective RNA traversal, or unacknowledged code path;
- MCP-only authorization;
- socket-thread `bpy` access;
- unbounded scene, mesh, node, animation, rig, image, or script output;
- fuzzy mutation targets;
- success that merely echoes requested values;
- hidden mode/selection/visibility/render-state changes;
- silent fallback to another object, camera, engine, or operation;
- ordinary handlers implemented by calling `python.execute`.

The best new tool makes a real workflow safer and easier to verify without unnecessarily widening the trusted surface.
