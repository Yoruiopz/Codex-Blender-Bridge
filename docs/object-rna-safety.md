# Object RNA mutation boundaries

The compatible `transform.*`, `modifier.*` and object `constraint.*` tools now
recheck Blender authority at each direct field write, allocation, removal,
verification and attempted compensation. Object-owned settings require
`TRANSFORM_OBJECTS`. Native `modifier.apply` and `transform.apply` additionally
require `EDIT_MESH`, because they permanently change the base Mesh. This is an
intentional permission tightening: clients that previously enabled only object
transforms must also obtain Mesh editing authorization before either apply tool.
Ordinary transform channels and modifier settings retain their existing gate.
A stopped request does not finish configuring a partially
created component or automatically remove it. A separate authorized request may
inspect, repair or remove that retained component.

These tools require a live tool context and Object Mode in one current scene and
view layer. Exact object/component identities, current project, frame, active
object and selection are compared after permission providers run. Local Object
consumers are followed up to 32 objects and returned in `affected_objects`.
Unexplained non-Object consumers, linked/override owners, shared scene ownership
and shared collection ancestry fail closed. Ordinary camera bindings and the
measured particle-edit context reference are accounted for locally; the shared
object-deletion policy is unchanged. Shared or linked Mesh data still permits an
object-owned transform or modifier/constraint setting change.

Direct writes compare protected writable RNA fields, other transform channels,
component order/identities, custom-property values, Action/driver/NLA content,
pose/rest-bone state, vertex-group metadata, material bindings, and bounded base
Mesh/attribute/shape-key content. Pointer settings also freeze local source
objects and their outside consumers. Self references and incoming dependency
cycles are refused. Limits include 100 components, 128 custom properties, 256
pose/rest bones, 131,072 Mesh structural elements and 262,144 attribute/shape-key
values. Larger scopes require a separately bounded workflow.

A setter may change only its predicted field delta. Demonstrated native aliases
are modeled explicitly: constraint `mute`/`enabled`, Bevel `width`/`width_pct`,
component activation on allocation, and automatic Mesh texture-space bounds.
Unexpected setter coupling is retained for inspection rather than adopted as
owned output. Ordinary failures can restore prevalidated field values only while
fresh authority and the exact expected state still hold. `rollback_verified`
requires the complete measured baseline to match. Pause, emergency stop,
permission loss and request expiry latch the operation against later automatic
writes. RNA comparison snapshots and checkpoint history are not durable backups.

Native modifier/transform application uses `temp_override` without changing
persistent selection, active object or mode. It checks the coherent live grant
set again after operator polling, followed by the complete context
and content comparison outside the temporary selection override. No permission
provider runs between that comparison and the pure final gate/native write.
It currently qualifies the bounded,
local, single-user Mesh path without shape keys; transform application additionally
refuses animated owners. Non-Mesh application, bone/vertex-parented world deltas,
non-default delta channels and unrepresentable matrix shear report explicit
unsupported contexts. Transform component locks are respected. Native calls can
block; they cannot be interrupted inside Blender's operator. Failure, cancellation
or a changed protected state after application reports possible retained mutation
and checkpoint recovery, never successful Mesh rollback. Mesh ID/ownership,
metadata, bindings, group metadata and other objects remain compared separately
from the allowed topology result.

Boolean application accepts one exact static, local Mesh Object cutter using
the EXACT solver and INDEX material mode. Target and cutter must each have one
nonnull DATA-linked slot containing the **same Material ID**, and every polygon
must have material index zero. Collection/empty operands, parented, animated, constrained,
modifier-bearing, shape-keyed, instanced or physics-driven cutters are refused
before the native apply call. The existing cutter's full bounded stored state,
exact identity and outside reference counts are frozen before live permission
callbacks and rechecked immediately before application. A changed cutter is
retained for inspection; it is never adopted as a new baseline.

Blender 5.2 native Boolean application can append a cutter's Material binding,
or a null slot for a cutter with no slots, even with `material_mode=INDEX`.
The researched 4.5 case retains the target bindings. The shared single-slot
profile preserves the target bindings on both runtimes; zero slots, multiple
slots, null slots, Object-linked overrides and broader material transfer remain
unsupported until their conversion semantics have direct evidence. No materials
are silently remapped, removed or accepted by name. The scanner benchmark assigns
its private cutters the shell's current DATA-bound material through explicit typed
calls, completes geometry, then isolates and edits the final shell finish.
Broader Boolean material transfer remains an open 1.0 requirement.

`verified` refers to these structural comparisons. It does not establish visual
acceptance, arbitrary nested RNA/profile/NodeTree/material dependency preservation,
all modifier-specific conversion semantics, durable topology recovery, large-scene
latency, Windows behavior or full release acceptance. Those broader gates remain
open. In particular, Mesh material bindings are frozen; complete shader graph and
texture content are not proven by this helper. A dependency closure identifies
consumers; it does not by itself qualify every affected workflow.

Validation is retained by the official `object_rna_mutations` background fixture
on Blender 4.5 LTS and 5.2, with Python adversarial tests in
`tests/test_object_rna_mutation.py`. The fixture checks successful transforms and
component lifecycle, live stops between fields, measured ordinary-failure
compensation, native application, protected objects and context. Linux evidence
does not qualify Windows or the release acceptance scenarios.

## Quaternion assignments

The optional `rotation_quaternion=[W, X, Y, Z]` field on `transform.set` and
`task.plan.preview_transform` assigns four authored components without
normalization, conversion or sign canonicalization. The target must already use
`QUATERNION` mode. Omit Euler `rotation`, the setter's legacy `rotation_euler`
alias and `rotation_mode` when supplying it. The restriction applies only to the
new field; existing transform inputs retain their previous behavior and
permissions.

Use a standalone registered `transform.set` call or the explicit
`task.plan.preview_transform` / `task.plan.apply_preview` sequence for this field.
`batch.plan` and `batch.execute` return `NOT_IMPLEMENTED` for any `transform.set`
entry containing `rotation_quaternion`, before child preparation, permission
providers, factories, checkpoints or handlers run. The batch's own entry
permission providers retain their normal behavior. Existing Euler, location and
scale batches retain their previous contracts.

The request contains exactly four finite numbers; booleans are not numbers for
this contract. Both the requested values and their independent Float32 rounding
must satisfy `abs(sqrt(sum(component^2)) - 1) <= 1e-6`. Component magnitudes cannot
exceed one. Raw and rounded nonzero magnitudes must be at least `2^-126`; either
signed zero is supported. Malformed shape, booleans, nonfinite, zero-length and
nonunit requests return `INVALID_ARGUMENT`. Finite requests outside the supported
storage profile return `NOT_IMPLEMENTED`.

The new field also requires a complete qualified immutable intent for all six
authored core channels before a write. Every captured original/requested numeric
component must meet the [target expectation profile](artist-target-verification.md#compared-channels-and-expectation-profile):
normal Float32 or signed zero, magnitude at most 1,000,000 and native hard ranges
without clamping. An unavailable intent returns `NOT_IMPLEMENTED` before
assignment, rather than allowing an edit without complete independent expected
channels.

This new-field profile requires a local editable static Mesh Object with one Mesh
data user and one scene owner. Every rotation-axis, W and four-dimensional
rotation lock flag must be clear, even for an unchanged value. Parenting,
children, constraints, modifiers, animation and shape keys are unsupported;
delta transforms must be identity. Incoming consumers remain subject to the
reviewed mutation boundary. The Blender-side gate remains authoritative for
direct calls and preview/apply; the optional argument grants no additional
permission. These restrictions do not qualify general rig, dependency or
rotation-conversion workflows.

Independent Float32 prediction and complete measured preservation remain
required. Raw channel agreement is separate from evaluated orientation and
artistic acceptance; neither an in-memory snapshot nor checkpoint history is a
durable backup. Seven-case native-storage research at `112f7d6` is historical
prerequisite evidence, not acceptance of the typed setter/preview workflow.
