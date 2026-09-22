---
name: blender-studio
description: Inspect, create, edit, shade, UV, rig, animate, render, or troubleshoot a live Blender project through Blender Codex Bridge.
---

# Blender Studio workflow

Use the Blender Codex Bridge MCP tools whenever the user wants work performed in a live Blender project. Treat Blender's current data as authoritative and act like a careful artist or technical director: inspect first, make scoped changes, and verify the result instead of trusting a successful tool response.

## Establish the session

1. Call `bridge.status` before scene work. Confirm that Blender is connected, note the current file, scene, mode, active object, enabled permissions, and enabled toolsets.
2. Call `bridge.task.set` with a short user-level description so progress is visible in Blender.
3. Call `toolsets.list` when the needed domain is not already enabled. Enable only the toolsets required for the task.
4. If the user refers to “this,” “selected,” “here,” or another context-dependent target, call `selection.inspect` before planning.
5. If a permission is disabled, explain exactly which switch the user must enable in Blender's **3D Viewport → Sidebar → Codex Bridge → Permissions**. Never claim the MCP side can grant it.

## Work loop

For each meaningful change:

1. Understand: inspect the relevant objects, mesh, material graph, UVs, rig, animation, camera, lights, and render state.
2. Plan: identify explicit datablock names, preservation constraints, required toolsets and permissions, and the evidence that will prove success.
3. Checkpoint: call `checkpoint.create` before topology changes, deletion, material replacement, rigging, parenting, applied modifiers, broad scripts, or batch edits.
4. Act: prefer the narrowest structured tool. Use explicit object, material, node, bone, action, and layer names.
5. Verify structurally: reinspect every changed datablock and important invariant.
6. Verify visually: use `viewport.capture` when silhouette, composition, shading, lighting, UV appearance, posing, or render look matters.
7. Refine: correct only what the evidence shows is wrong, then verify again.
8. Save only when the user asks, and report whether the `.blend` was saved.

## Tool selection

- Use object and transform tools for lifecycle, hierarchy, placement, and applied transforms.
- Use selection IDs plus mesh tools for topology edits. Reinspect after topology changes, undo, file reload, mode changes, or scene switches.
- Use material and node tools for materials, shader graphs, socket values, and links.
- Use UV tools for UV layers, unwrap, projection, and packing.
- Use modifier and constraint tools instead of applying ad-hoc operators.
- Use rigging and animation tools for armatures, bones, poses, keyframes, actions, and frame settings.
- Use scene, viewport, and render tools for cameras, lights, output configuration, previews, and final render work.

Current optional toolsets are `objects`, `mesh`, `materials`, `nodes`, `uv`, `modifiers`, `constraints`, `animation`, `rigging`, `scene_edit`, `render`, `interaction`, `layout`, `geometry_nodes`, `batch`, and `python`. The Blender panel can enable all structured toolsets at once while leaving Python disabled.

## Efficient structured workflows (0.3.0+)

- Resolve targets with filtered, paginated `scene.query`. Its bounds refer to world origins, not surface intersections.
- Use `selection.set` and `context.set_mode` for intentional context changes. Entering edit/paint/pose modes isolates the target selection; entering paint mode is not itself painting.
- In single-object mesh Edit Mode, use `mesh.components_inspect` to choose indices from measured evidence. Pass its fresh selection ID to `mesh.select_components`; reinspect after topology or context changes.
- Prefer `object.transform_batch` for up to 128 independent object edits, and origin-based `object.align`/`object.distribute` for layout. Dependent/animated/parented objects are intentionally rejected.
- Use `geometry_nodes.*` for Geometry Nodes and `nodes.*` for material shaders. Inspect shared/nested graph users before acknowledging `allow_shared`; direct-user summaries may not enumerate indirect effects.
- Use `batch.plan` then `batch.execute` for short known sequences, up to 32 explicit `{id?, method, params}` steps, with all child toolsets enabled. Preflight checks shape/static gates, not handler arguments or scene dependencies. There are no result substitutions: inspect separately when the next decision depends on output.
- Batch stops on the first error or cooperative deadline/disconnect boundary. Prior edits remain; never blindly retry. Check failed-step evidence, history, and current Blender state. One best-effort logical undo marker does not guarantee atomic rollback or single-step undo across mode/operator boundaries. Reinspect any `result_truncated` step separately (16 KiB limit).
- Keep Python, render/capture, save, lifecycle changes, and undo outside batches. Perform structural and visual verification afterward; batching does not replace the work loop.

## Python fallback

`python.execute` is a last resort for Blender API work that has no suitable structured tool. Before using it:

1. State why structured tools are insufficient.
2. Keep the script small and limited to the named task.
3. Require the `python` toolset plus all four Blender permissions: `EXECUTE_PYTHON` (**Execute Python**), `DELETE_OBJECTS` (**Delete Objects**), `ACCESS_EXTERNAL_FILES` (**Access External Files**), and `SAVE_PROJECT` (**Save Project**). Also require a truthful `expected_effect` and `confirm_dangerous=true`.
4. Do not use Python for shell commands, networking, secret access, or unrelated filesystem work.
5. Treat the returned result and data-count delta as audit evidence, not proof. If `result_truncated` is true, the result exceeded its global 4,000-item, depth-8, 4,000-integer-digit, no-cyclic/shared-reference, or 256 KiB serialized budget—or conversion failed—and was replaced by `__truncated__` metadata; request a compact acyclic result or use structured inspection. Result-conversion failure degrades to metadata so audit/recovery remains available. Captured stdout has a separate 64 KiB cap. Reinspect affected datablocks and capture a view when appearance matters.

Python execution is cooperatively time-bounded, but a long Blender C operation may not be interruptible. If the caller loses a response or reports `outcome_unknown`, inspect current Blender state before considering a retry.

Once armed, raw `bpy` is a super-permission that bypasses narrower structured `EDIT_*` gates and can delete data, use Blender file APIs, and save. The import and syntax policy reduces accidents; it is not a security sandbox. If execution starts and fails, use its digest/effect/output/delta evidence, `mutation_outcome_unknown`, and `verification_required` fields, inspect immediately, and treat its finalized tracked undo step as recovery evidence rather than proof of isolation.

## Reporting

Call `bridge.task.clear` when work is complete or abandoned. Conclude with the objects and datablocks changed, the structural checks performed, the visual evidence captured, any remaining limitations, and whether the project was saved. Never say that an unsupported or unverified operation succeeded.
