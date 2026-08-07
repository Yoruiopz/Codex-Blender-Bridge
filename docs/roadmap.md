# Roadmap

The roadmap grows from a reliable local inspection/edit loop toward human-like contextual workflows. Dates are intentionally omitted; each phase has capability and evidence gates. The running registry and test results—not this roadmap—are authoritative for current availability.

## Phase 1 — Local foundation and verified transforms

Focus: connection, inspection, screenshots, transforms, permissions, and undo.

Deliverables:

- Installable Blender 4.2+ add-on and visible Codex Bridge panel.
- Loopback-only NDJSON transport with a main-thread command queue.
- Local stdio MCP server and small registry-backed core tool surface.
- Bridge/project status; scene, selection, and object/mesh inspection.
- Viewport capture with view/shading options and state restoration.
- Blender-side permission enforcement, pause, emergency stop, and concise history.
- Checkpoint create/list/undo and permitted project save.
- Deterministic transform set/translate/rotate/scale/apply with post-state.
- Fake-bridge tests plus Blender smoke tests.

Exit gate:

Codex can inspect a disposable `.blend`, checkpoint it, perform a permitted transform, structurally reinspect, visually compare, undo, and demonstrate a Blender-side permission denial without corrupting the session.

## Phase 2 — Reliable modeling primitives

Focus: useful mesh editing without dependence on brittle viewport automation.

Deliverables:

- Selection-reference lifecycle and localized mesh-region inspection.
- Reliable `bmesh`-first normals, delete, dissolve, extrude, inset, bevel, merge, subdivide, fill/grid-fill, and basic bridge/loop operations where Blender APIs support deterministic context.
- Mesh diagnostics for loose/non-manifold geometry, ngons, normal inconsistencies, density, and connected islands.
- Symmetry/mirror helpers with explicit planes and verification.
- Operation-level topology metrics, preservation checks, and undo grouping.
- Performance limits for dense meshes and long-running cooperative progress.

Exit gate:

On a representative mesh suite, Codex can identify a selected/localized region, apply several modeling primitives, prove the intended topology changed, prove protected dimensions/silhouette constraints remain within tolerance, and undo the logical operation.

## Phase 3 — Materials, UVs, cameras, and lights

Focus: structured look-development and scene-composition controls.

Deliverables:

- Arbitrary material node-tree inspection with stable node/socket references.
- Principled helpers that preserve unrelated graph structure, plus material create/assign/connect operations.
- Permission-gated texture/path workflows with strict path policy.
- UV layer/island inspection, seam operations, unwrap helpers, packing diagnostics, overlap/stretch summaries.
- Camera and light inspection/creation/transforms/settings.
- Material-preview, camera, and lighting comparison captures.

Exit gate:

Codex can preserve existing materials while editing an explicitly selected subset, perform a bounded UV workflow, create a camera/light setup, and verify each result structurally and with matched visual captures.

## Phase 4 — Animation and rigging

Focus: time-aware inspection and reversible animation/armature edits.

Deliverables:

- Actions, F-curves, keyframes, drivers, NLA tracks, constraints, bones, pose, weights, and dependency summaries.
- Keyframe and interpolation tools with frame-range and channel scoping.
- Armature/bone selection references and safe pose/edit-mode transitions.
- Weight diagnostics and bounded assignment/normalization helpers.
- Animation previews or sampled visual evidence without full-quality rendering by default.
- Stronger checkpoint semantics for multi-frame and dependency-linked edits.

Exit gate:

Codex can diagnose and correct a scoped animation or rigging issue while preserving unrelated channels/bones and can verify the fix at relevant frames plus undo it as one logical operation.

## Phase 5 — Geometry Nodes and advanced procedural workflows

Focus: inspectable, composable procedural systems.

Deliverables:

- Geometry Nodes tree, interface, group, link, modifier, attribute, and dependency inspection.
- Stable node/socket identifiers across one session.
- Safe node create/connect/configure/group operations with schema-aware socket values.
- Procedural evaluation summaries and bounded geometry diagnostics.
- Domain extensions for modifiers, instances, simulations, and bake-state awareness.

Exit gate:

Codex can explain an unfamiliar node network, make a scoped procedural change without replacing the graph, and compare evaluated geometry/state before and after.

## Phase 6 — Agent verification and visual feedback loops

Focus: make verification systematic rather than prompt-dependent.

Deliverables:

- Declarative pre/post conditions and preservation constraints on task plans.
- Repeatable matched captures and automated multi-angle inspection.
- Structural diff summaries for scenes, objects, meshes, materials, and animation.
- Visual-comparison helpers for silhouette, composition, lighting, and material variants.
- Progress events, cooperative cancellation, and long-operation state.
- Evidence bundles linking operations, checkpoints, metrics, and images.

Exit gate:

For representative tasks, the bridge can produce a bounded evidence bundle showing intended changes, preserved constraints, structural diffs, matched visual comparisons, and any unresolved uncertainty.

## Phase 7 — Persistent scene semantics and contextual interaction

Focus: safely interpret instructions such as “this,” “the other side,” and “do the same.”

Deliverables:

- Persistent semantic object/region references with invalidation and provenance.
- Spatial graph containing bounds, centers, hierarchy, proximity, visibility, and camera relationships.
- Operation-history semantics suitable for replaying or mirroring prior intent.
- Symmetry/counterpart detection with confidence and user confirmation thresholds.
- User-visible current task/plan and protected-scope annotations in Blender.
- Reference-resolution explanations and ambiguity errors instead of guesses.

Exit gate:

Codex can combine current selection, structure, images, spatial relationships, and operation history to resolve contextual references on a benchmark set, while stopping for clarification below a defined confidence threshold.

## Phase 8 — Creative variants and project branching

Focus: non-destructive exploration across multiple alternatives.

Deliverables:

- Named variants and branches with explicit base checkpoint and changed-data scope.
- Lighting, material, camera, geometry, and animation variant workflows.
- Safe file/scene/collection strategies that avoid silent backup sprawl.
- Side-by-side structural and visual comparison, ranking, merge/apply, and discard.
- Provenance linking user intent, tool operations, artifacts, and saved outputs.
- Recovery across sessions and clear storage/cleanup controls.

Exit gate:

Codex can generate multiple named alternatives without destructively altering the primary state, show comparable evidence for each, apply the chosen variant intentionally, and cleanly discard the rest.

## Cross-phase work

Every phase continues to improve:

- Blender-version compatibility and clean enable/disable behavior;
- schema/protocol compatibility and migration tests;
- local-only security, permission granularity, and parser hardening;
- queue responsiveness, result limits, and large-scene performance;
- error quality, diagnostics, and supportability;
- non-Blender unit tests and Blender integration fixtures;
- honest documentation of supported and unsupported behavior.

Breadth does not advance a phase if the inspect → checkpoint → act → structural verify → visual verify → compare → refine loop is unreliable.
