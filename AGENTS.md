# AGENTS.md

This repository builds a consent-first bridge between Codex and Blender. These instructions apply to both repository changes and any live Blender work performed through the bridge.

## Product priorities

When priorities compete, use this order:

1. Reliability over breadth.
2. Structured tools over arbitrary scripts.
3. Inspection over assumptions.
4. Reversible changes over destructive changes.
5. Verification over blind execution.
6. Measured scene state over visual inference.

Never claim that an unimplemented capability works. Return or document `NOT_IMPLEMENTED` instead of fabricating a result.

## Non-negotiable Blender work loop

For every task that may inspect or modify a live `.blend`, follow the complete loop below. A short task may make a stage brief, but must not silently skip a relevant verification stage.

### 1. UNDERSTAND

Inspect the relevant project, scene, mode, active object, and selection before deciding what the user's words refer to. Treat the current `.blend` as the source of truth. Check bridge status and available permissions/toolsets when they affect feasibility.

### 2. PLAN

Choose the smallest safe sequence of operations that can satisfy the request. Identify the objects and data blocks in scope, what must remain unchanged, required permissions, likely context dependencies, verification evidence, and the recovery point.

### 3. CHECKPOINT

Create a logical checkpoint before meaningful mutation, especially deletion, topology edits, material replacement, parenting, applied transforms, batch operations, or changes with a wide blast radius. Prefer one checkpoint per coherent user-level operation, not one per trivial tool call.

### 4. ACT

Use typed, structured Blender tools. Prefer direct Blender data APIs and `bmesh` implementations over context-sensitive operators. Make no unrelated edits. Do not use arbitrary Python as a shortcut; it requires explicit Blender-side permission and is a last-resort capability, not the normal workflow.

### 5. VERIFY STRUCTURALLY

Reinspect every changed object or data block. Confirm returned and independently observed state: transforms, dimensions, hierarchy, object counts, selection, topology metrics, materials, modifiers, visibility, or other relevant invariants. A successful transport response alone does not prove the requested outcome.

### 6. VERIFY VISUALLY

When appearance, silhouette, composition, lighting, shading, materials, camera framing, or topology flow matters, capture an appropriate viewport or camera image after the structural check. Match view and shading to the question; use wireframe for topology and material/rendered modes for look development when supported.

### 7. COMPARE

Compare the verified result with the request and with pre-change evidence. Check explicit preservation constraints such as “keep the materials,” “do not touch the character,” or “do not change the silhouette.” Do not equate “tool returned success” with “user goal achieved.”

### 8. REFINE

If evidence shows an error or incomplete result, make the smallest correction and repeat structural and visual verification. Restore or undo when the current approach has violated constraints rather than layering compensating edits on top.

### 9. SAVE

Save only when the user asked for it or saving is clearly part of the agreed workflow, and only with `SAVE_PROJECT` permission. Do not overwrite a project unexpectedly, invent output paths, or scatter backup copies. An unsaved checkpoint is not a durable backup.

### 10. REPORT

State what changed, which objects/data were affected, what was verified structurally, what was checked visually, whether the project was saved, and any limitations or uncertainty. Mention permission denials or unsupported steps plainly.

## Context and reference resolution

Natural-language references are evidence requirements, not permission to guess.

- If the instruction includes “this,” “these,” “that,” “here,” “there,” “selected,” “current,” “active,” “that side,” or similar deictic language, call `selection.inspect` and inspect the current mode before acting.
- Combine `selection.inspect`, `object.inspect`, and `viewport.capture` when the reference depends on both geometry and appearance.
- Resolve explicit object names against scene inspection. If the name is missing or ambiguous, stop before mutation and report candidates.
- “Do the same on the other side” requires evidence for symmetry, the prior logical operation, and the intended counterpart. Do not infer a mirror plane or counterpart from a screenshot alone.
- A temporary selection ID is valid only for the bridge session and context that issued it unless the protocol explicitly says otherwise. Reinspect after mode changes, topology edits, undo, file reload, or scene switches.
- Operation history can support context, but current Blender state wins if history and the `.blend` disagree.
- Preserve negative scope constraints. Record objects or collections that must not change and recheck them when the operation could affect dependencies.
- When uncertainty could materially alter the result, ask the user rather than choosing a target by visual proximity.

## Structural and visual evidence rules

- Use Blender's numeric state for dimensions, transforms, counts, distances, frame ranges, and topology. Never infer precise measurements from pixels.
- Use images for silhouette, composition, occlusion, lighting, shading, material appearance, and qualitative topology flow.
- Inspect before and after. Do not assume a Blender operator or data assignment succeeded.
- Request compact summaries first. Do not flood context with full vertex arrays, every dependency-graph value, or unbounded node trees.
- Prefer localized mesh inspection, selected-component summaries, bounding boxes, warnings, and pagination/truncation metadata.
- If a response is truncated, acknowledge it and narrow the next inspection instead of treating partial data as complete.
- Restore temporary viewport, visibility, selection, camera, shading, and overlay state used only for capture.

## Safety and permissions

- Never bind the Blender transport beyond the literal loopback address `127.0.0.1`.
- Never mutate Blender from a network thread. Enqueue requests and execute through the main-thread scheduler.
- Blender-side permission checks are authoritative and must run immediately before execution. The MCP server cannot grant or bypass them.
- Do not delete objects or data blocks without `DELETE_OBJECTS` and clear task scope.
- Do not execute Python without `EXECUTE_PYTHON`; it must remain disabled by default.
- Do not access external paths without `ACCESS_EXTERNAL_FILES`. Normalize and constrain any permitted path.
- Never add a remote shell tool or tunnel the local listener as part of a normal feature.
- Pause and emergency-stop state must prevent new mutations. A canceled or timed-out caller must not cause an untracked late edit.
- Redact secrets and avoid returning raw tracebacks to MCP clients. Keep detailed diagnostics local.

## Repository architecture invariants

Keep these concerns separated:

- `mcp_server/`: MCP lifecycle, schemas, small/lazy tool registry, and local Blender client.
- `addon/blender_codex_bridge/transport.py` and `server.py`: loopback networking and framing only.
- `command_queue.py` and `executor.py`: request lifecycle and Blender main-thread dispatch.
- `permissions.py`: Blender-side authorization policy.
- inspectors and `viewport.py`: bounded structural and visual evidence.
- `checkpoints.py` and state/history modules: reversible logical operations and audit state.
- domain modules under `tools/`: typed Blender operations.

Do not import `bpy` into the standalone MCP process. Do not couple MCP schemas to Blender UI classes. Do not place permission enforcement solely in MCP wrappers. Avoid giant dispatch chains; register handlers and metadata through a registry.

Every modifying tool must:

1. declare its toolset and required Blender permissions;
2. validate bounded, typed input;
3. identify affected objects/data where practical;
4. run on Blender's main thread;
5. participate in logical operation history/checkpoint behavior;
6. return enough post-operation state for verification;
7. surface structured errors without swallowing the underlying failure locally.

## Protocol rules

- Blender transport is versioned newline-delimited JSON over local TCP. One JSON object equals one UTF-8 line.
- Preserve request IDs exactly and produce at most one terminal response per accepted request.
- Keep success and error envelopes stable. Add optional fields compatibly; use a protocol-version change for breaking semantics.
- Treat malformed JSON, oversized frames, duplicate active IDs, invalid arguments, unavailable methods, permission denial, timeout, and Blender exceptions as explicit structured failures.
- Serialize socket writes. Blender execution remains serial even if the MCP process accepts concurrent calls.
- Do not log protocol messages to an MCP stdio server's stdout. Use stderr or configured logging.
- If adding progress events, make them correlated, ordered, non-terminal messages; the final response still determines completion.

Read [`docs/protocol.md`](docs/protocol.md) before changing framing or lifecycle behavior.

## Engineering and tests

- Use typed Python, small modules, explicit interfaces, and descriptive domain errors.
- Prefer standard-library dependencies in the Blender add-on; Blender cannot assume the MCP environment's packages exist.
- Avoid context-sensitive `bpy.ops` where a data API or `bmesh` operation is safer. When an operator is necessary, validate and document its mode/area/selection requirements.
- Preserve the user's mode, selection, active object, viewport settings, and visibility when an operation only needs to change them temporarily.
- Bound expensive inspection and image sizes. Report truncation explicitly.
- Add non-Blender tests for schemas, malformed frames, request IDs, timeout/error propagation, connection lifecycle, registry metadata, and permission behavior.
- Keep Blender-dependent integration tests separate and mark their environment requirements.
- Run the focused tests after a change, then the full non-Blender suite. Do not report success without the command result.
- Keep documentation aligned with the actual registry. Planned tools belong in the roadmap, not in current-feature claims.

## Completion standard

A change is complete only when the code path is implemented, permission-gated where necessary, recoverable in proportion to risk, tested at the appropriate layer, documented if public, and verified against the current Blender state for live tasks. Save/reporting is not a substitute for the verification loop.
