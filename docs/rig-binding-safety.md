# Armature binding safety increment

**Save availability:** `project.save` currently refuses Save and Save As before
native/path access; see [the safety change](project-save-safety.md). Fresh-process
results below establish feature serialization through owned fixture setup, not a
safe bridge project-save capability. Earlier typed-save reports are historical.

`rig.bind_mesh` retains its existing `EMPTY_GROUPS` / `AUTOMATIC` arguments and
adds optional `affected_objects`. The named mesh and rig are the two explicit
roots; list every additional direct or transitive Object consumer, up to 30.
Omitted scope retains the old payload shape and succeeds only when the two roots
have no additional consumers. Local ownership, current Scene/ViewLayer membership,
collection ownership and exact native reference counts are checked before writes.
Incoming cycles that the new binding would close are refused.

Binding now requires `EDIT_MESH` as well as `EDIT_ANIMATION` and
`TRANSFORM_OBJECTS`, in both Blender and MCP metadata. This is a stricter safety
requirement for the unreleased implementation: existing clients must enable the
mesh-edit grant before binding because the tool writes vertex groups and weights.
The protocol envelope and existing argument meanings are unchanged. Safe authorized project saving is a separate blocked requirement; the native backend is unavailable.

## Bounded supported inputs

- Object Mode; one local, editable, single-user Mesh without shape keys or custom split normals,
  constraints or animation. The mesh must be unparented or already object-parented
  to this exact rig. Existing world transforms are verified after binding.
- At most 4,096 vertices, 128 output vertex groups, 32,768 existing memberships,
  128 source bones and 128 original per-group weight buckets for recovery.
  Protected mesh readers additionally enforce their element, attribute and custom
  data budgets. Dependent preservation currently reads bounded Mesh, Armature and
  Empty objects; unsupported readers fail before mutation.
- No modifier, or one existing Armature modifier targeting this exact rig.
  Preexisting modifier settings and native identities remain protected.
- `AUTOMATIC` additionally requires a static, independent rest rig without
  animation, constraints, modifiers or changed pose channels. Locked existing
  deform groups are refused; locked unrelated groups remain protected.
- Installed dependency-graph/frame-change handlers are refused because their
  arbitrary mutations have no reviewed prediction in this transaction.

`EMPTY_GROUPS` can preserve existing rig Actions while creating missing deform
groups. Animation/Action content, stored rest/pose descriptors, nested bone colors,
collection memberships and hierarchy, base mesh/custom data, UV/color roles,
material bindings and explicit dependent content are comparison evidence. These
checks do not certify arbitrary outgoing dependency contents or artistic quality.

## Write and recovery boundaries

Every structured write rechecks live grants, toolset, pause/emergency state,
cancellation, exact IDs/consumer closure, stored content and physical context.
The final provider is followed by another canonical cancellation check and
callback-free state verification; a scheduler can also perform its pure final
lifetime check after the complete comparison. Authority and comparison failures
are latched for this binding attempt.

Automatic weights use a natively verified `temp_override` for `parent_set`,
preserving the physical selection and active object. The synchronous heat solver
cannot be interrupted internally. Its measured native blocking interval is
returned separately from total operation time. Cancellation/revocation detected
after it returns retains the observed result and performs no late cleanup.

The immediate native output is captured before completion providers. Success
requires the expected appended groups, exact preexisting identities/settings,
protected unrelated memberships and positive finite deform coverage on every
vertex. Native heat weights do not necessarily sum to one; the result reports the
observed minimum/maximum totals and does not certify authored normalization or
deformation quality.

For a recoverable ordinary fault after a verified output, compensation restores
all original exact float32 memberships, group identities/locks, parent and stored
transform channels, active group and modifier configuration. Sparse membership
storage order is canonicalized by `(group index, weight)`; every membership is
compared. Compensation removes only exact measured allocations and checks the
complete receipt before each write. Manual edits, replaced IDs/components,
changed scope, cancellation or lost authority stop compensation. Unknown native
partial output is retained rather than inferred to be owned from matching names.
Only an exact final comparison sets `rollback_verified=true`. Retained buffers,
logical checkpoints and native undo are not durable backups.

## Retained development evidence

The official isolated runner provides:

- `rig_binding_probe`: native heat behavior and complete membership restoration
  research, including an existing modifier and locked unrelated group.
- `rig_binding`: typed AUTO and empty-group success, complete compensation after
  injected ordinary/memory faults, explicit consumer scope and permission/lock
  refusals; late permission/toolset/pause/emergency/cancel/disconnect and manual
  changes retain the measured result.
- `rig_binding_reopen`: separately launched writer/reader processes. Typed AUTO
  binding preserves UVs and pins, seams, color/custom attributes, material graphs
  and protected weights; typed pose/key authoring creates sampled deformation.
  Authorized `.blend` save and fresh reopen compare complete stored evidence and
  every sampled vertex/bone matrix, with file hashes and distinct process tokens.

These are Linux development checks on Blender 4.5.14 and 5.2.2. They do not qualify
Windows, large production meshes, general animated heat weighting, appearance,
memory-pressure operation or the full character acceptance scenario. Full 1.0
safety/workflow, durable recovery and Windows gates remain open. See
[rig edit boundaries](rig-edit-boundaries.md) for rest/pose/constraint limits and
[release readiness](release-1.0-readiness.md) for the requirement ledger.
