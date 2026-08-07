# Implementation plan

This plan turns the product brief into independently testable increments. It is intentionally ordered so no Blender mutation is exposed before the local transport, main-thread handoff, schemas, and Blender-side permission boundary exist.

Status in this document is conservative: a phase is complete only when its exit checks pass. File presence alone is not completion.

## Principles and constraints

- Target Blender 4.2 LTS as the minimum supported Blender generation and smoke-test newer installed Blender releases without claiming them until checks pass.
- Keep the Blender add-on dependency-light and compatible with Blender's bundled Python.
- Bind the Blender listener to `127.0.0.1` only.
- Network workers enqueue; only Blender's main thread may access or mutate `bpy` data.
- Expose small typed toolsets through MCP; do not expose raw `bpy` or a remote shell.
- Enforce permissions inside Blender immediately before execution.
- Bound and summarize inspection results. Report truncation.
- Group meaningful modifications into checkpoints/history entries and return post-operation state.
- Verify structurally after every mutation and visually when appearance matters.

## Step 1 — Repository and design baseline

Deliverables:

- Root project metadata, ignore rules, license, and package layout.
- `addon/blender_codex_bridge/`, `mcp_server/`, `tests/`, and `docs/` boundaries.
- This implementation plan plus architecture, protocol, tool, security, and roadmap documents.

Exit checks:

- The standalone package can be imported without Blender or `bpy`.
- Documentation distinguishes implemented MVP behavior from roadmap behavior.
- No design requires arbitrary Python for normal operations.

## Step 2 — Add-on registration and control surface

Deliverables:

- Blender add-on metadata, deterministic `register()`/`unregister()`, preferences, operators, and a **Codex Bridge** 3D Viewport N-panel.
- Connection controls, status, pause and emergency-stop controls, current-task placeholder, permission toggles, recent activity, and checkpoint actions.
- Minimal persistent state with no background work left behind after unregister.

Exit checks:

- A ZIP containing `blender_codex_bridge/__init__.py` at its root installs and enables in Blender 4.2.
- Repeated enable/disable cycles do not duplicate classes, timers, or listeners.
- The panel visibly distinguishes stopped, listening, connected, paused, active, and error states where applicable.

## Step 3 — Local transport and main-thread queue

Deliverables:

- TCP listener restricted to literal `127.0.0.1`.
- UTF-8 NDJSON framing with message-size and parse limits.
- Thread-safe command queue and response rendezvous.
- Blender timer/main-thread pump with bounded work per tick.
- Clean shutdown that unblocks sockets and rejects unfinished work deterministically.

Exit checks:

- A network worker never imports scene data or calls Blender mutation APIs.
- Malformed, oversized, disconnected, duplicate-ID, and shutdown paths do not hang Blender.
- Slow/no client does not block Blender's main thread on socket I/O.

## Step 4 — Versioned request/response contract

Deliverables:

- Typed request, success, error, and reserved event envelopes.
- Stable error taxonomy and exception-to-public-error translation.
- Request ID preservation, timestamps where useful, protocol version negotiation/validation, timeouts, and structured local logging.

Exit checks:

- Valid messages round-trip without losing IDs or JSON-safe result types.
- Invalid envelopes produce one bounded structured error when a response is possible.
- Internal tracebacks remain in local diagnostics rather than normal responses.

## Step 5 — MCP adapter

Deliverables:

- Local MCP server over stdio.
- Blender client with connect/disconnect behavior, correlated request futures, serialized writes, timeout handling, and clean error mapping.
- Registry-backed MCP tool definitions and instructions that emphasize inspect/checkpoint/verify.

Exit checks:

- Codex can launch the server as a local stdio command.
- MCP stdout contains only protocol output; diagnostics use stderr/logging.
- Blender unavailable, response timeout, malformed response, and mid-request disconnect become useful MCP errors.

## Step 6 — Core structural inspection

Deliverables:

- `bridge.status`, `project.info`, `scene.inspect`, `scene.summary`, `selection.inspect`, and `object.inspect`.
- Stable object references where practical and a session-scoped selection-reference abstraction.
- Compact scene/object serialization with explicit limits and truncation metadata.

Exit checks:

- Scene summary and detailed inspection agree on current scene, mode, active object, and selection.
- Mesh inspection reports useful aggregate diagnostics without dumping all coordinates.
- Edit-mode selection reports counts, center, and approximate bounds where supported.
- Unsupported object/data types degrade to bounded generic inspection rather than failing the whole scene.

## Step 7 — Visual inspection

Deliverables:

- `viewport.capture` with supported view, shading, overlay, object-isolation, and resolution inputs.
- A safe artifact/result representation that Codex can inspect.
- State snapshot/restore around temporary viewport and visibility changes.

Exit checks:

- Current and deterministic orthographic/camera views work in supported UI contexts.
- Capture failures restore viewport, active object, selection, shading, overlays, and visibility on a best-effort basis.
- Headless or missing-area limitations return structured errors rather than fake images.

## Step 8 — Blender-side permissions

Deliverables:

- Permission enum and policy for inspection, capture, transforms, mesh/material/animation edits, deletion, Python, external files, and saving.
- Tool metadata declaring all required permissions.
- Panel controls and concise denial history.

Exit checks:

- Every handler is checked in Blender; bypassing the MCP wrapper does not bypass policy.
- Denied handlers do not begin mutation and return `PERMISSION_DENIED` with missing permissions.
- Dangerous permissions default off, especially arbitrary Python and external files.

## Step 9 — Checkpoints and operation history

Deliverables:

- `checkpoint.create`, `checkpoint.list`, and `checkpoint.undo_last`.
- Logical operation IDs and bounded history containing tool, affected objects, timestamp, description, and success/failure.
- Blender undo integration with clearly documented session limits.

Exit checks:

- A supported mutation can be undone as one logical agent operation.
- Failed operations are recorded but are never advertised as successful checkpoints.
- No checkpoint silently writes project copies to arbitrary filesystem paths.

## Step 10 — Object and transform operations

Deliverables:

- Object create/delete/duplicate/rename/parent/collection operations in an `objects` toolset as feasible.
- Deterministic transform set/translate/rotate/scale/apply operations.
- Post-operation transforms and affected-object references in results.

Exit checks:

- Direct data APIs are used where safer than context-sensitive operators.
- Missing/ambiguous object, invalid transform, locked data, permission denial, and mode mismatch are structured failures.
- Deletion is separately gated and never enabled merely by enabling general object edits.

## Step 11 — Basic mesh and material inspection operations

Deliverables:

- Initial `mesh` toolset for inspection, normals, selected delete/dissolve/extrude/inset/bevel where reliable.
- `bmesh`-first edit implementation with explicit selection and mode requirements.
- `material.inspect` preserving arbitrary node-tree structure in bounded summaries.

Exit checks:

- Mesh operations reject stale/empty/invalid selections and report affected geometry.
- Geometry-changing operations update the mesh and return enough summary state to recheck topology.
- Normals repair and topology edits can be checkpointed and undone.
- Material inspection does not pretend every material is only a Principled BSDF.

## Step 12 — Automated tests

Deliverables:

- Unit tests for message models, framing, malformed inputs, serialization, registry metadata, permission policy, timeout/error propagation, IDs, connection lifecycle, and fake scene responses.
- A fake Blender server/client boundary for MCP tests.
- Separately marked Blender integration tests or a documented manual smoke-test script.

Exit checks:

- The normal Python suite runs without importing `bpy` or launching Blender.
- Tests cover success and failure paths, including late timeout responses and permission denial.
- Platform-dependent networking tests use ephemeral loopback ports and deterministic cleanup.

## Step 13 — User and contributor documentation

Deliverables:

- README setup, ZIP installation, Codex configuration, local security, examples, and honest limitations.
- Architecture, protocol, tool-design, security, troubleshooting, agent behavior, and roadmap documents.

Exit checks:

- Every documented current tool exists in the registry or is explicitly labeled planned/conceptual.
- Commands, package names, defaults, and environment options match code.
- A new contributor can identify where to add a tool and which tests are required.

## Step 14 — Verification and defect pass

Run in this order:

1. Formatting/static checks configured by the project.
2. Focused unit tests for changed modules.
3. Full non-Blender test suite.
4. Fresh Blender 4.2 add-on ZIP install/enable/disable.
5. Loopback connect/disconnect and malformed-request smoke tests.
6. Read-only status/scene/selection/object inspection.
7. Viewport capture with state-restore check.
8. Permission-denied mutation check.
9. Permitted transform and mesh operation with structural reinspection.
10. Checkpoint undo and save-permission checks on a disposable `.blend`.

Record exact versions and failures. Do not mark V1 complete on unit tests alone.

## Step 15 — Architecture review

Review for:

- accidental `bpy` use off the main thread;
- authorization gaps or tool metadata drift;
- unbounded serialization/rendering;
- context-sensitive operator use without restoration;
- request lifecycle races, duplicate terminal responses, or late edits after timeout;
- MCP stdout logging corruption;
- tight coupling that would make a new domain toolset require transport rewrites;
- documentation that describes roadmap behavior as current behavior.

Address structural issues before adding breadth.

## V1 acceptance scenario

On a disposable Blender 4.2 project, a local Codex client must be able to:

1. Connect and read bridge/project status.
2. Inspect the scene, active selection, and one mesh without giant raw payloads.
3. Capture a usable viewport image without permanently changing the workspace.
4. Observe a Blender-side denial for a disabled permission.
5. Enable an appropriate permission and toolset, create a checkpoint, and perform a transform.
6. Perform several supported basic mesh operations with explicit selection/context.
7. Reinspect structural state and capture visual evidence.
8. Undo the logical agent operation.
9. See concise operation history in Blender.
10. Save only after explicitly enabling/using `SAVE_PROJECT`.
11. Recover from malformed input, handler exceptions, timeout, and disconnect without restarting Blender.

The final acceptance report must identify any step that remains partial; partial support is not silently promoted to complete.
