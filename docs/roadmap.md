# Roadmap

The running registry and passing tests are authoritative. This roadmap separates shipped 0.2.0 behavior from planned breadth; a roadmap item is never a claim that a tool exists.

## Current release: 0.2.0 platform alpha

Version 0.2.0 establishes the end-to-end platform and a broad first structured surface.

Shipped foundation:

- installable Blender 4.2+ add-on and standalone local MCP server;
- repository Codex plugin with MCP launch configuration and a verification-first Blender skill;
- literal-loopback NDJSON transport, bounded framing/queue, and Blender main-thread dispatch;
- Blender-side toolsets and permissions, pause, emergency stop, current task, checkpoints, history, and diagnostics;
- project/scene/selection/object/mesh inspection and viewport evidence;
- object lifecycle, hierarchy, collections, deterministic transforms, arbitrary bounded-topology mesh creation, and basic selection-scoped mesh editing;
- material lifecycle, slots, Principled inputs, and bounded material shader-node editing;
- UV inspection, unwrap, Smart Project, and packing;
- allowlisted modifiers and object constraints;
- frame/range/keyframe animation operations;
- armature/bone/pose/constraint/binding rig operations;
- scene, collection, camera, light, world, and render settings/execution;
- save and external-path controls;
- disabled-by-default, explicitly acknowledged `python.execute` for unsupported Blender API work, gated as a super-permission by Python, delete, external-file, and save permission together.

The Python fallback provides long-tail reach, not equivalent maturity. Once armed it bypasses narrower structured `EDIT_*` gates, so its four broad permissions are explicit consent to that authority. It is an accident guard rather than a hard security sandbox and does not replace structured inspection, checkpoints, or verification.

Current gaps include advanced modeling/retopology, Geometry Nodes, compositor graphs, sculpt/paint, animation interpolation/driver/NLA editing, detailed weight workflows, simulations/bakes, many specialist data types, persistent semantic references, automatic structural diffs, and durable variants. Some shipped domains intentionally expose only a safe subset of settings or operations.

## Next: structured breadth and hardening

Focus: turn the broad alpha surface into a dependable daily workflow without making Python the default.

Planned work:

- expand deterministic mesh creation/editing, merge/subdivide/fill/bridge/loop operations, seams, and localized diagnostics;
- add texture/image path workflows with explicit path policy;
- add material-node coverage only through stable node/socket contracts;
- broaden camera/light/render settings and matched visual comparisons;
- add more Blender-version fixtures and dense/large-scene performance tests;
- improve cancellation safe points, progress, diagnostics, and operation-level evidence;
- continue parity, permission-denial, and real-Blender smoke coverage for every domain.

Exit gate:

Representative modeling, shading, UV, rigging, animation, scene, and render tasks complete through structured tools, prove intended post-state, preserve declared constraints, and undo coherently across the supported Blender matrix.

## Geometry Nodes and compositor

Focus: inspectable procedural and image-processing graphs.

Planned work:

- Geometry Nodes trees, interfaces, node groups, modifier relationships, sockets, links, attributes, dependencies, and evaluated summaries;
- compositor tree inspection and exact node/socket/link edits;
- session-stable node/socket references with invalidation rules;
- allowlisted node creation/configuration and schema-aware values;
- simulation/bake-state awareness and bounded evaluated-geometry diagnostics.

Exit gate:

Codex can explain an unfamiliar graph, make a scoped change without replacing unrelated structure, and compare evaluated state before and after.

## Advanced animation and rigging

Focus: channel-aware animation and production rig maintenance.

Planned work:

- interpolation/handle/extrapolation controls, action lifecycle, drivers, NLA, and sampled animation evidence;
- armature selection references and stronger mode-transition guarantees;
- vertex-group/weight inspection, assignment, normalization, symmetry, and diagnostics;
- broader pose/object constraint settings and dependency summaries;
- coherent undo/evidence for multi-frame and dependency-linked changes.

Exit gate:

Codex can diagnose and correct a scoped animation or rig issue while proving unrelated channels, bones, and weights remain unchanged.

## Systematic verification

Focus: make proof of success a platform feature rather than a prompt convention.

Planned work:

- declarative preconditions, postconditions, and preservation constraints;
- structural diffs for scenes, objects, meshes, materials, node graphs, animation, and rigs;
- repeatable matched multi-angle captures and bounded visual-comparison helpers;
- evidence bundles linking task, operations, checkpoints, metrics, images, and save state;
- correlated progress events and cooperative cancellation for long operations.

Exit gate:

Representative tasks produce a bounded evidence bundle that shows intended changes, preserved constraints, visual comparisons, and unresolved uncertainty.

## Persistent context and human-like references

Focus: safely interpret instructions such as "this," "the other side," and "do the same."

Planned work:

- persistent semantic object/region references with provenance and invalidation;
- spatial graph for bounds, centers, hierarchy, proximity, visibility, and camera relationships;
- operation-history semantics suitable for replay/mirroring;
- symmetry/counterpart detection with confidence and confirmation thresholds;
- user-visible protected scope and reference-resolution explanations.

Exit gate:

Codex resolves contextual references from current Blender evidence on a benchmark set and stops for clarification below a defined confidence threshold.

## Variants and durable project workflows

Focus: non-destructive creative exploration across sessions.

Planned work:

- named variants/branches with explicit base state and changed-data scope;
- lighting, material, camera, geometry, and animation variants;
- side-by-side structural/visual comparison, apply/merge/discard controls;
- provenance and explicit storage/cleanup behavior;
- recovery across sessions without silent backup sprawl.

Exit gate:

Codex can produce alternatives without destructively altering the primary state, present comparable evidence, apply the selected result intentionally, and clean up the rest.

## Cross-cutting release gates

Every increment must maintain:

- same-host loopback-only security and no remote shell;
- Blender-side permission checks and disabled dangerous defaults;
- no Blender API use from network threads;
- bounded schemas/results and explicit truncation;
- checkpoint/history participation and truthful post-state;
- non-Blender tests plus real-Blender smoke coverage where API/context matters;
- synchronized add-on, MCP, plugin, package, archive, and documentation versions;
- explicit `NOT_IMPLEMENTED` or documented limitations instead of simulated success.

Breadth does not advance the roadmap if the understand/plan/checkpoint/act/verify/compare/refine/report loop becomes unreliable.
