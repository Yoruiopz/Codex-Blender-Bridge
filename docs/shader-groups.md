# Reusable and nested shader groups

Unreleased on `main`; not in the published 0.3.0 packages. Structured shader-group authoring,
instance isolation and explicit nested paths extend look development without arbitrary Python.

## Enter a graph explicitly

All `nodes.*` tools accept optional `group_path`: up to eight exact **group-node instance names**
starting at `material_name`'s root. These are node names, not node-group datablock names. For example,
`group_path=["Surface", "Finish"]` enters `Surface.node_tree`, then `Finish.node_tree`.
Omit it or pass an empty list for the original root behavior. Inspect each level first;
node summaries now identify referenced group and image names. Missing, unbound, wrong-type,
recursive or oversized paths are rejected rather than guessed.

Nested inspection returns the chosen tree, path and ownership evidence. It does not recursively
expand every referenced group's contents. Nested mutations require **Object Mode**, local editable
non-override trees, complete ownership evidence and `EDIT_MATERIALS`. Root behavior is otherwise
unchanged. Nested graphs are limited to 256 nodes / 1,024 links / 128 interface items; existing
inspection socket and total-output budgets still apply. `nodes.add` additionally admits
`NodeGroupInput` and `NodeGroupOutput` inside a group. Normal node inspection/add/remove/rename,
input/link/unlink and image-binding tools work at the selected level.

The newer [reviewed shader-property and Color Ramp tools](shader-settings.md) also work at
root/nested paths. They require Object Mode even at the root, reject direct material/target
tree animation, and add full ramp/settings state to bounded node inspection. This is a
separate reviewed subset, not generic property access or an extension of every legacy tool's gate.

## Lifecycle tools

All tools belong to the existing `nodes` toolset. Toolset availability never grants permission.

| Tool | Contract | Blender permissions |
| --- | --- | --- |
| `shader_group.inspect(group_name, max_nodes=100, max_links=300, max_sockets_per_direction=32)` | Exact ShaderNodeTree, bounded nodes/links/interface and incoming ownership evidence | `INSPECT_SCENE` |
| `shader_group.create(group_name)` | Unique empty local group with named Group Input/Group Output nodes; no implicit reuse/attachment | `EDIT_MATERIALS` |
| `shader_group.interface_add(group_name, name, in_out="INPUT", socket_type="NodeSocketFloat", default_value?, allow_shared=false)` | Append one unique name/direction socket, up to 128 interface items | `EDIT_MATERIALS` |
| `shader_group.interface_preview(group_name, socket_identifier, operation, new_name?, to_index?, value?)` | Read-only full bounded scope/fingerprint for one exact rename, same-direction move or definition-default edit | `INSPECT_SCENE` |
| `shader_group.interface_edit(..., expected_fingerprint, allow_shared=false)` | Apply the exact preview with live full-scope comparisons and guarded measured compensation | `INSPECT_SCENE`, `EDIT_MATERIALS` |
| `shader_group.bind(material_name, node_name, group_name, group_path?, allow_shared=false)` | Bind an exact unlinked ShaderNodeGroup instance, or explicit null to clear; clear a different previous binding first | `EDIT_MATERIALS`; FILE dependencies also require `ACCESS_EXTERNAL_FILES` |
| `shader_group.copy_for_node(material_name, node_name, new_name, group_path?, allow_shared=false)` | Copy the group bound to one exact instance, preserving that instance's input defaults and parent-tree links | `EDIT_MATERIALS`; FILE dependencies also require `ACCESS_EXTERNAL_FILES` |
| `shader_group.remove(group_name, confirm_unused=false)` | Confirmed unused local group only, no fake user, forced unlink, nested-data removal or file deletion | `EDIT_MATERIALS`, `DELETE_OBJECTS` |

Mutations require Object Mode; inspection does not. Names are non-control UTF-8 of at most
63 bytes. Supported new interface types are Float, Int, Bool, Vector, Color and Shader
(`NodeSocket*` identifiers shown by inspection). Socket defaults use typed/native value validation;
Shader sockets have no editable scalar default. A zero-user group is not a durable library asset:
bind it before relying on normal project persistence. No fake user, asset marking or save is implied.

The stricter preview/edit pair requires Object Mode even for preview, flat interfaces,
complete reviewed local unanimated scope and explicit consent for all reported shared
owners. It preserves stable identifiers, existing instance defaults, links and active
interface selection. Definition defaults and current instance values are separate.
See the [interface contract and measured native hazards](shader-interface-lifecycle.md)
for exact limits, permissions, failure/recovery behavior and conversion/animation gaps.

## Shared users and isolation

Copying a material does **not** copy its nested groups or images. A child with `users=1` can still
affect many materials/objects through its parent group. The ownership reader follows up to 32
incoming parent shader groups and 100 distinct owner IDs, then reports material-slot object users
and direct World/Light/other owners. Object-slot usage across all reached materials is collected
in one traversal. Same-named object users do not suppress numeric shared-consent checks.

Complete scope is required before mutation; `allow_shared=true` cannot override an evidence budget
or linked/override/read-only owners. Shared use requires explicit consent covering every affected
user. The evidence is not a transitive scene/instance dependency graph or whole-look guarantee;
World/Light owners can affect a much wider scene than the material-slot object list.

To edit only one object:

1. Inspect scene/selection/mode, material users and relevant groups; record protected objects and
   group contents. Create a logical checkpoint.
2. Use `material.copy_for_object` when its material is shared.
3. Use `shader_group.copy_for_node` on the outer instance. If a child remains shared, enter the
   isolated parent with `group_path` and copy that child instance too. Copies are **one level**:
   deeper groups and images remain shared until explicitly isolated/rebound.
4. Edit the isolated level through `nodes.*`. Build new reusable groups by creating them, adding
   interface sockets, binding an unlinked group instance, then authoring its body at that path.
5. Reinspect changed/protected groups and objects, capture matched material/rendered views, compare
   and refine/recover. Save only when the user agreed and `SAVE_PROJECT` is granted.

Binding/copying reviews up to 32 outgoing local group dependencies, rejects recursive references
and Script/IES dependencies, and admits at most 16 distinct loaded simple images. FILE images
require the same approved-folder, live permission, supported PNG/JPEG and size/header checks as
[image binding](image-assets.md). No implicit buffer reload, source write or pixel edit occurs.
Generated images need no file grant. Source hashes at binding are not proof of buffer/file currency.

## Logical batches and recovery

Use `batch.plan` / `batch.execute` for a coherent known-name revision, with inspection/capture
between revisions. For example, creating a variant group, exposing sockets, adding its shader and
texture, wiring it and connecting its output can be a single 12-step batch. This uses one logical
before/after undo boundary instead of a separate pair for every tool call, reducing both request
overhead and native undo-history consumption.

Batches support 1–32 explicit steps and check live child gates before each execution. Planning
checks shape/static permissions, **not** Blender arguments, dynamic file permission or dependencies.
They are not transactions: failures retain audited partial work. Inspect the failure and use
confirmed snapshot recovery when appropriate. Group creation/isolation/binding attempt measured
scoped restoration on failure. Interface cleanup explicitly does **not** claim global rollback,
because native interface updates may also rebuild external instances.

Native history is finite and shared with manual Blender work. A controlled disposable probe on
both installed versions recovered only 16 of 17 separately checkpointed steps with 32 native undo
steps, versus 17/17 with 128. The shipped workflow fixture passes at the unchanged default of 32
by grouping its 12-step variant into one logical batch. This is not a history-capacity fix or
permission to change user preferences. Capacity/availability reporting and longer manual-interleaved
recovery remain 1.0 work. Checkpoints are not durable backups; an old tracked label need not still
have a reachable native snapshot.

## Verification and limits

`blender_shader_groups_smoke.py` uses disposable factory scenes and isolated profiles on Windows
Blender 4.5.1/5.1.2. It verifies transitive sharing when the child has only one direct user, nested
copy/default/link preservation, typed fresh-group/interface/body construction, approved nested
image binding, denied scope/file/edit permissions, pause/stop, deliberate partial-batch failure,
unused removal and staged native recovery. Protected group contents and source bytes are checked
independently, with matched orange/blue/green/recovered/protected captures. No user project or
preferences are saved, and the main recipe does not expand undo history.

`scene.snapshot` / `scene.compare` still hash root shader state, not nested group contents. A root
match alone cannot prove nested preservation: inspect and compare each relevant group's bounded
nodes/interface/links separately. Inspect any truncation rather than treating partial state as complete.
The fixture demonstrates iteration and recovery, not production-material or full artist acceptance.

A newer [interface preview/edit contract and native proof](shader-interface-lifecycle.md)
provides bounded typed rename/reorder/default editing and fresh reopen on Linux
4.5.14/5.2.2. The underlying research also
records real type-conversion default loss and an animation-index alias on 4.5 that
5.2 repairs natively; typed edits reject affected animation and type conversion.

Interface socket removal, panels, type conversion and animated maintenance,
shader properties beyond the reviewed subset,
animated ramps and other curve/collection controls,
deep copies, asset marking, root World/Light editing, compositor groups/images, broader image
lifecycle/formats, complete nested structural snapshots and production-scale latency/quality
acceptance remain open in the [1.0 plan](plan-1.0.md). No new release is implied.
