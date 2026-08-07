# Tool design

Blender Codex Bridge exposes a deliberately small, typed tool surface. A tool is a stable contract between agent intent and a permission-gated Blender handler—not a thin alias for a `bpy` function or operator.

## Design rules

Every tool should be:

- **Task-shaped:** represent a meaningful Blender action or inspection, not arbitrary code execution.
- **Typed and bounded:** validate explicit inputs, ranges, result size, and enum options.
- **Context-honest:** state mode, selection, area, active-object, and data-type requirements.
- **Permission-declared:** list every required Blender-side capability.
- **Verifiable:** return affected identities and relevant post-operation state.
- **Recoverable:** participate in checkpoint/history behavior in proportion to mutation risk.
- **Observable:** produce structured errors and local timing/failure logs.
- **Extensible:** live in a domain toolset without requiring transport or server rewrites.

Prefer a handful of composable operations over hundreds of fragile operator-shaped tools.

## Two registries, one contract

The bridge has two aligned registries because the MCP process and Blender process have different responsibilities.

### MCP registry

The MCP registry owns:

- public tool name and description;
- JSON/MCP input schema;
- read-only/destructive/idempotence annotations where supported;
- toolset membership and exposure state;
- adapter function that forwards validated parameters to the Blender client.

It does not authorize Blender access and must not import `bpy`.

### Blender registry

The Blender registry owns:

- protocol method name;
- handler callable;
- required permission set;
- toolset membership;
- mutating and destructive classification;
- pause/emergency-stop behavior;
- checkpoint/history policy;
- optional result limits and execution metadata.

This registry is authoritative. If MCP metadata says a tool is read-only but the Blender descriptor requires mutation permission, Blender's policy wins and the metadata bug must be fixed.

Registry consistency should be testable: names, toolsets, permission expectations, and schema versions must not silently drift between processes.

## Tool descriptor

A conceptual Blender descriptor contains:

```python
ToolDescriptor(
    name="transform.translate",
    toolset="objects",
    handler=translate_object,
    required_permissions={Permission.TRANSFORM_OBJECTS},
    mutates=True,
    destructive=False,
    history=True,
)
```

This is illustrative, not a requirement for exact class names. Registration should fail fast on duplicate names, invalid dotted names, missing handlers, unknown permissions, or a mutating tool with inconsistent metadata.

Avoid a giant `if method == ...` dispatcher. The executor looks up a descriptor, verifies control state/toolset/permissions, runs the handler on Blender's main thread, records history, and serializes its result.

## Layers and toolsets

### Core surface

The always-available surface stays compact and focuses on orientation, inspection, recovery, saving, and tool discovery:

```text
bridge.status
project.info
scene.inspect
scene.summary
selection.inspect
object.inspect
viewport.capture
checkpoint.create
checkpoint.list
checkpoint.undo_last
project.save
toolsets.list
toolsets.enable
toolsets.disable
```

“Always available” means discoverable without a domain toolset. Permissions still apply. In particular, `viewport.capture` and `project.save` require their Blender permissions.

### Domain surfaces

Domain groups can include:

```text
objects, mesh, uv, materials, animation, rigging,
camera, lighting, render, geometry_nodes
```

Toolset enablement is an attention and reachability control: it keeps Codex's active schema surface small and makes user intent visible. It is not authorization. Enabling `mesh` does not grant `EDIT_MESH`; both conditions must pass.

The running `toolsets.list` result is authoritative. Documentation may describe planned groups, but it must not imply that an unregistered tool exists.

### Suggested enablement semantics

- Core starts enabled.
- MVP domain defaults should be conservative.
- `toolsets.enable`/`toolsets.disable` update Blender first and mirror the change in the MCP registry; a local loader failure attempts to roll Blender back so the two sides do not silently diverge.
- Disabling a toolset prevents new requests. It must not interrupt an active Blender operation at an unsafe point.
- Reconnect/restart behavior must be explicit; do not assume toolset state persists unless the add-on preferences intentionally persist it.

## Permissions

Use narrow capability names:

| Permission | Examples | Default posture |
| --- | --- | --- |
| `INSPECT_SCENE` | scene, selection, object, mesh/material reads | enabled for normal use |
| `CAPTURE_VIEWPORT` | viewport/camera image capture | enabled only with visual access consent |
| `TRANSFORM_OBJECTS` | set/translate/rotate/scale/apply | explicit write consent |
| `EDIT_MESH` | normals, bevel, inset, topology changes | explicit write consent |
| `EDIT_MATERIALS` | material/node edits | explicit write consent |
| `EDIT_ANIMATION` | keys, actions, constraints if classified | explicit write consent |
| `DELETE_OBJECTS` | object/data deletion | off by default |
| `EXECUTE_PYTHON` | restricted future fallback | off by default; dangerous |
| `ACCESS_EXTERNAL_FILES` | paths outside controlled bridge artifacts | off by default |
| `SAVE_PROJECT` | write current or explicitly approved project path | explicit consent |

A tool may require several permissions. For example, a future render-to-user-path tool may require capture/render permission plus external file access. Do not broaden one permission to avoid declaring another.

Permission checks occur immediately before handler execution on Blender's main thread. Validate again after queue wait because the user may revoke permission while a command is pending.

Denial returns `PERMISSION_DENIED` with bounded `missing_permissions` context and performs no partial mutation.

## Naming and scope

Use lowercase `domain.verb` names:

- `scene.inspect`, not `getAllSceneInformation`;
- `transform.translate`, not `object_bpy_ops_transform_translate`;
- `mesh.bevel_selected`, not a generic `mesh.execute` action enum.

Use verbs consistently:

- `inspect` returns detailed structured state.
- `summary` returns an LLM-oriented bounded overview plus structured fields.
- `list` enumerates compact identities/metadata.
- `create`, `delete`, `set`, `apply`, `capture`, and `undo_last` imply concrete behavior.

One tool should have one coherent permission and recovery story. Split an option into another tool when it makes an otherwise safe operation destructive, introduces filesystem access, or changes context requirements materially.

## Input schemas

- Inputs are named JSON objects, not positional arguments.
- Reject unknown fields for modifying tools unless a versioned compatibility reason says otherwise.
- Use enums for view, shading, transform space, axis, mode, and operation variants.
- Bound names, counts, traversal depth, bevel segments, image dimensions, and all list inputs.
- Reject non-finite numbers and invalid ranges.
- Document units and spaces. Use radians for programmatic rotations unless a field explicitly says degrees.
- Object/collection/material references must be unambiguous. Accepting a fuzzy name is appropriate for search, not mutation.
- Treat a `selection_id` as opaque and validate its object, mode, mesh revision/session, and expiry.
- Avoid flags whose combinations create many hidden modes. Separate tools or tagged unions are clearer.

Validation occurs on both sides for different reasons: MCP validation gives fast agent feedback, while Blender validation protects the trust boundary and current state.

## Result schemas

Read tools return compact facts with stable field names. Modify tools additionally return:

- `operation_id` when recorded;
- affected object/data identifiers;
- relevant post-operation state;
- warnings or skipped subparts;
- truncation/approximation indicators;
- checkpoint association where useful.

For example, a transform operation should return the resulting location/rotation/scale, not just the requested delta. A mesh operation should return selected/affected counts and a fresh aggregate mesh summary where practical.

Do not return Blender objects, RNA values, sets, bytes, NaN/infinity, or other non-JSON values directly. Serialization is an explicit boundary.

## Read tools

Read-only means the user's project data is not intentionally changed. Some inspections may need temporary mode/view/evaluation work; that state must be snapshot and restored in `finally`.

Keep default payloads small:

- object pages instead of unlimited scenes;
- aggregate mesh statistics instead of vertices;
- key material-node summaries instead of an unlimited graph;
- explicit diagnostic sampling;
- filters such as object name/type/collection;
- `truncated`, counts, cursors, and omitted-field notes.

A read handler must not hide an expensive full render or topology analysis behind a “summary” name.

## Mutating tools

A mutation handler should follow this internal pattern:

1. Resolve exact targets and validate current mode/context.
2. Confirm toolset, pause/emergency state, and permissions.
3. Capture minimal state needed for result comparison/history.
4. Begin or join the logical checkpoint/undo group.
5. Perform the smallest direct data or `bmesh` operation.
6. Update meshes/dependency state as required.
7. Produce fresh post-state and affected identities.
8. Close history as success or failure, preserving useful local diagnostics.

Avoid `bpy.ops` when direct data access is deterministic. When an operator is necessary, explicitly establish and restore its mode, active object, selection, area, region, and view layer requirements. Never assume the user's last-used UI context matches the request.

If an operation can partially apply before an exception, either make it atomic/recover it or report the partial state clearly and retain a usable undo path. Do not convert partial failure into success.

## Checkpoints and history

Checkpoint policy belongs in descriptor/executor metadata, not scattered ad hoc across handlers.

- Read-only tools do not create undo steps.
- A low-risk transform may join a caller-created logical checkpoint.
- Destructive or topology operations should require/recommend a checkpoint and form one coherent undo step.
- Batch handlers should record one user-level operation with affected members, not spam a history entry per internal loop iteration.
- Failed attempts receive failure history where useful but not a success checkpoint.
- Blender does not expose reliable undo-entry ownership. Remote global undo requires `confirm_global_undo=true`; the Blender panel uses a confirmation dialog. Results describe global-undo scope and never claim agent-only isolation.

Do not silently create filesystem copies as checkpoint implementation.

## Errors

Handlers raise or return typed domain failures that map to stable protocol codes. Prefer precise errors such as `OBJECT_NOT_FOUND`, `INVALID_SELECTION`, or `INVALID_MODE` over `OPERATION_FAILED`. Preserve exception chains in local logs while returning concise public messages.

Useful error context includes:

- available/similar object names;
- expected/current Blender mode;
- missing permissions;
- supported enum values;
- safe result/argument limits;
- a diagnostic ID for local log correlation.

Never embed a giant stack trace, full scene dump, environment variables, or filesystem inventory in an MCP error.

## Adding a tool

Use this checklist.

### 1. Define the user-level contract

Write the intended operation, non-goals, target resolution, context requirements, units, preservation guarantees, expected post-state, failure cases, and result limits. Decide whether an existing tool can compose the behavior safely.

### 2. Classify it

Choose core or a named domain toolset. Declare read/mutate/destructive behavior, all permissions, checkpoint/history policy, and whether it can run while paused (normally only status/recovery/control reads can).

### 3. Add shared schema concepts

Define bounded request/result models without importing Blender. Reuse stable vector, object-reference, pagination, truncation, and error conventions. Version breaking changes rather than silently altering meaning.

### 4. Implement the Blender handler

Put domain code under the appropriate add-on tool/service module. The handler assumes main-thread execution but still validates live context. Prefer data APIs/`bmesh`, preserve temporary user state, and return JSON-safe data.

### 5. Register Blender metadata

Register the exact protocol name, handler, permissions, toolset, mutation flags, and history behavior. Add fail-fast duplicate/metadata tests.

### 6. Add the MCP adapter

Define the public MCP schema/description and forward parameters through the Blender client. Keep it thin. Do not duplicate Blender semantics or manufacture success in the adapter.

### 7. Test each boundary

At minimum test:

- valid input/result serialization;
- missing/invalid/boundary arguments;
- registry discovery and toolset disabled state;
- every required permission denied in Blender;
- wrong mode/type/selection and missing target;
- handler failure/error mapping;
- timeout/disconnect behavior through the fake bridge;
- post-state and history for mutation;
- Blender integration for API/context-sensitive behavior.

### 8. Document and verify the agent loop

Update current-tool documentation only after registration works. Add an example showing inspect/checkpoint/act/verify, including what evidence proves success and what remains unsupported.

## Specialized guidance

### Mesh

Use `bmesh` where it avoids UI-context coupling. Define whether a tool consumes live selection or a selection ID, which component types are allowed, and what happens to selection afterward. Recalculate/update meshes explicitly and return changed counts plus aggregate diagnostics. Never default to serializing complete geometry.

### Materials

Materials are arbitrary node graphs. A useful inspector may identify output nodes, major shaders, textures, links, and Principled values when present, but must not model every material as one Principled node. Future edits should address nodes/sockets explicitly and preserve unrelated graph structure.

### Viewport/render

Capture operations declare view, shading, overlays, isolation, resolution, color/image format, and artifact behavior. Snapshot and restore temporary view, visibility, and render settings. V1 caps preview capture sampling at 16 samples and reports the effective values. Blender's supported render operators replace the session's Render Result buffer; V1 reports that side effect, requires `CAPTURE_VIEWPORT`, and conservatively advertises capture as modifying/destructive. A capture result is not a numeric measurement.

### Project/files

Saving requires `SAVE_PROJECT`; choosing an external/new path also requires the path policy and may require `ACCESS_EXTERNAL_FILES`. Normalize paths in Blender. Never accept shell fragments, implicit home-directory expansion, or arbitrary directory traversal.

### Arbitrary Python

`python.execute` is a future emergency escape hatch only. It is disabled by default, requires explicit dangerous permission, must capture bounded stdout/errors, and never replaces a missing structured tool. It must not provide shell execution or bypass path/permission controls.

## Anti-patterns

Do not add:

- a generic `bpy.call`, `operator.execute`, `eval`, shell, or expression tool;
- a single method with hundreds of action strings;
- MCP-only permission checks;
- handlers that mutate from a socket thread;
- unbounded deep scene/mesh/node serialization;
- success results that echo requested values without reading resulting Blender state;
- “read-only” captures that permanently alter selection, visibility, or viewport state;
- fuzzy target matching for mutation;
- undocumented silent fallback to another mode, object, camera, or render engine.

The best new tool makes one important workflow safer and easier to verify without widening the bridge's trusted surface unnecessarily.
