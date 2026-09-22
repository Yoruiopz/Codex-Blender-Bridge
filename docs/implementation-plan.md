# Implementation plan and release status

> This document records the historical **0.2.0 baseline**. For the 20 additional tools and behavior shipped in 0.3.0, see [agent workflows](agent-workflows.md) and [release notes](releases/0.3.0.md).

This document records what the 0.2.0 platform implements and the checks required before calling it releasable. Presence of a module is not completion: a public path must be registered on both sides, permission-gated, recoverable in proportion to risk, tested, documented, and verified in Blender where API/context behavior matters.

## Invariants

- Blender 4.2 LTS is the minimum compatibility target.
- The add-on listener accepts only literal `127.0.0.1`.
- Network workers enqueue; Blender API access runs on Blender's main thread.
- The MCP server imports and tests without `bpy`.
- Structured, typed tools are preferred over Python.
- Blender-side live permission checks are authoritative.
- Inspection, images, code, messages, queues, and history are bounded.
- Meaningful changes participate in logical checkpoint/history behavior and return post-state.
- Every mutation is structurally verified; appearance-dependent work is also checked visually.

## Implemented platform layers

### Repository, packaging, and Codex plugin

- Python package metadata and `blender-codex-mcp` console script.
- Deterministic Blender add-on ZIP builder targeting `dist/blender_codex_bridge-0.2.0.zip`.
- Blender extension manifest and 4.2+ add-on registration lifecycle.
- Repository Codex plugin at `plugins/blender-codex-bridge` with manifest, MCP configuration, workflow skill, and doctor script.

Release checks:

- install the Python package in a clean 3.10+ environment and run `blender-codex-mcp --help`;
- validate the plugin manifest/package;
- build the archive and confirm `blender_codex_bridge/__init__.py` is at its root;
- install/enable/disable the ZIP in a fresh supported Blender profile without duplicate classes, timers, or listeners.

### Local transport, protocol, and MCP lifecycle

- Versioned UTF-8 NDJSON over local TCP with a 4 MiB payload cap.
- Exact string request IDs, required object params, stable success/error envelopes, and structured errors.
- Thread-safe bounded queue, Blender timer pump, serialized socket writes, lifecycle-safe stop/unregister, timeout-before-start rejection, and unknown-outcome handling after send.
- Official MCP server integration over stdio by default, correlated Blender client, lazy registry, annotations, and stderr-only logs.

Release checks:

- malformed, partial, oversized, non-finite, duplicate-ID, disconnect, cancellation, timeout, queue-saturation, and shutdown cases do not hang or late-mutate untracked state;
- all terminal responses preserve the exact ID and protocol version;
- MCP stdout contains protocol output only;
- add-on and MCP method parity passes except the documented local-only recovery method.

Read [protocol](protocol.md) before changing this layer.

### Blender control surface and permissions

- Sidebar connection status/configuration, current task/method, queue depth, toolsets, permissions, history, diagnostics, checkpoint recovery, pause, and emergency stop.
- `bridge.task.set` and `bridge.task.clear` for visible human oversight.
- Blender-owned permissions for inspection, capture, transforms, mesh, materials, animation, scene, render, deletion, Python, external files, and saving.
- Optional domain toolsets start disabled; core is always enabled; Python additionally defaults to disabled permission.

Release checks:

- the panel distinguishes stopped/listening/connected/executing/paused/emergency/error states;
- every modifying handler declares and enforces current permissions immediately before execution;
- denial produces `PERMISSION_DENIED` with `missing_permissions` and no partial mutation;
- pause blocks mutations while inspection/recovery policy remains available; emergency stop closes the listener and cancels queued/not-started work.

### Inspection, evidence, checkpoints, and saving

- Project, scene, scene summary, selection, object, mesh, material, node, UV, modifier, constraint, animation, rig, and render inspection with explicit limits.
- Session-scoped selection IDs with context/fingerprint validation.
- Viewport/camera capture with bounded images and best-effort state restoration.
- Logical checkpoint create/list/global undo plus local UI restore and bounded operation history.
- Permissioned project save and approved external path handling.

Release checks:

- related summaries agree on scene, mode, active object, and selection;
- truncation/omitted counts are explicit;
- captures restore temporary selection, visibility, view, shading, and render settings where Blender permits and report Render Result replacement;
- global undo requires explicit confirmation and does not claim agent-only ownership;
- save never invents a path or overwrites unexpectedly.

## Implemented structured domains

The running `toolsets.list` output is authoritative. Current domains include:

- object creation/deletion/duplication/rename/parenting/collections and deterministic transforms;
- arbitrary mesh creation from fully prevalidated bounded vertices/edges/faces plus selection-scoped inspection, normals, delete, dissolve, extrude, inset, and bevel;
- material lifecycle/assignment/slots/Principled values and exact material shader-node graph edits;
- UV layer/island inspection, unwrap, Smart Project, and packing;
- allowlisted modifier and object-constraint inspection/add/set/remove/apply behavior;
- frame/range settings, action/F-curve/key inspection, and keyframe insertion/deletion;
- armature creation/inspection, bone add/update/remove, pose transforms/constraints, and mesh binding;
- scene configuration, collection lifecycle, camera, light, world, and render inspection/configuration/execution.

Each domain release check includes valid inputs, boundary validation, disabled toolset, every permission denial, wrong target/type/mode/selection, handler failure mapping, checkpoint/history metadata, measured post-state, MCP/add-on parity, and real-Blender smoke coverage for context-sensitive paths.

The structured surface is intentionally not exhaustive. Geometry Nodes, compositor, sculpt/paint, advanced animation/NLA/drivers, detailed weight tools, simulations/bakes, retopology, and many specialist types remain future domain work.

## Python long-tail capability

`python.execute` is implemented only as a last resort for an unsupported Blender API task. It is not used internally by ordinary structured tools.

Required controls:

- explicitly enabled `python` toolset;
- all four Blender-side super-permissions: `EXECUTE_PYTHON`, `DELETE_OBJECTS`, `ACCESS_EXTERNAL_FILES`, and `SAVE_PROJECT`;
- `confirm_dangerous=true` and non-empty `expected_effect` per call;
- 64 KiB source/stdout caps; a result-conversion budget of 4,000 global items, depth 8, 4,000 integer digits, no cyclic/shared-reference expansion, and 256 KiB serialized; AST/input bounds; safe import roots; denied dangerous names/introspection; and a 0.1-30 second cooperative deadline;
- bounded audit result with digest, expected effect, duration, output, coarse data-count/object deltas, and `verification_required: true`.

The policy rejects obvious filesystem/process/network/dynamic-code paths but is an accident guard, **not a security sandbox**. Raw `bpy` bypasses normal structured `EDIT_*` permission gates once the four broad permissions arm it; it can delete data, use Blender file APIs, and save. The bridge exposes no shell or network tool. Long Blender C operations cannot always be interrupted. Every call must be followed by domain inspection and visual evidence where relevant, then the toolset and four broad permissions should return to least privilege.

Release checks:

- verify denial unless the `python` toolset and all four broad permissions are enabled;
- test import/name/introspection, size, AST, input, output, syntax, runtime failure, and cooperative deadline behavior;
- confirm an oversized, over-depth, over-item, over-integer-digit, cyclic, shared-reference, or unexpectedly unconvertible result is replaced before transport encoding with `__truncated__`, `result_truncated: true`, and `result_limit_bytes: 262144`, preserving audit/recovery while stdout keeps its independent 64 KiB bound;
- confirm trace state is restored and public errors contain no raw traceback;
- confirm started runtime/deadline failures return digest/effect/output/deltas with unknown mutation outcome, remain in history, and finalize a usable undo step;
- confirm execution remains on Blender's main thread and is recorded as modifying/destructive.

## Test and release sequence

Run in this order:

1. `python -m ruff check .`
2. `python -m mypy mcp_server`
3. focused tests for changed modules;
4. full `python -m pytest` suite;
5. plugin validation and add-on ZIP build/layout validation;
6. fresh Blender 4.2+ install/enable/disable;
7. baseline TCP/main-thread smoke and permission denial;
8. core inspection, checkpoint, viewport capture, transform, mesh, material/node, UV/modifier/constraint, animation/rig, scene/render, and save-path smoke checks on disposable projects;
9. structural reinspection and visual comparison for every changed domain;
10. undo/recovery and shutdown/reconnect checks;
11. documentation/registry/version/stale-claim audit.

Record exact Python, Blender, operating system, test commands, and failures. Unit tests alone do not establish Blender compatibility.

## 0.2.0 acceptance scenario

On a disposable supported `.blend`, a local Codex client must be able to:

1. connect, report status, and show a high-level task in Blender;
2. inspect scene, selection, and relevant data without giant raw payloads;
3. enable only needed structured toolsets and permissions;
4. create one logical checkpoint and perform representative edits across requested domains;
5. prove intended structural post-state and capture matched visual evidence where appearance matters;
6. observe authoritative denial for a disabled permission;
7. recover one logical step with acknowledged global-undo scope;
8. render/save only with the required permissions and explicit path/overwrite intent;
9. use Python only for a demonstrably unsupported operation through the full dangerous arming chain, then verify and disable it;
10. show concise status/history/diagnostics in Blender and clear the task;
11. recover from malformed input, handler failure, timeout, cancellation, disconnect, and shutdown without restarting Blender where reasonable.

Any partial or unsupported step must be reported as such. Saving, a successful protocol envelope, or a Python script return value is not a substitute for verification.

## Next implementation focus

See [roadmap](roadmap.md). Near-term work prioritizes structured breadth and hardening, then Geometry Nodes/compositor, advanced animation/rigging, systematic evidence, persistent context, and durable variants. Reliability and structured tools continue to take priority over merely increasing operation count.
