# Scene editing boundaries

Status: **unreleased contract draft; integrated validation is pending**. This
document describes the guarded `scene_edit` increment, including mandatory static
dependency checks still being integrated. Its final source, complete tests and
native evidence must agree before these behaviors become current-feature claims.
Published 0.3.0 downloads are unchanged. No 1.0 acceptance gate is closed here.

## Interfaces and admission

The existing typed arguments and protocol envelopes remain compatible. The
admitted ownership and context are narrower than the earlier unguarded handlers.
Unsupported scope returns `NOT_IMPLEMENTED` before an owned write instead of
silently changing other consumers or discarding their data.

| Method | Required Blender permissions | Initial admitted operation |
| --- | --- | --- |
| `scene.configure` | `EDIT_SCENE` | Current Scene camera binding, units and gravity, within the admitted static scope |
| `camera.configure` | `EDIT_SCENE` | Optics, clipping, depth of field and explicit current-Scene camera assignment |
| `light.configure` | `EDIT_SCENE` | Settings present on the existing native Light subtype |
| `world.configure` | `EDIT_SCENE` | Explicit World creation/assignment, color and a reviewed Background graph |
| `collection.create` | `EDIT_SCENE` | A new empty collection under one supported current-Scene parent |
| `collection.rename` | `EDIT_SCENE` | Exact collection identity and an unused destination name |
| `collection.delete` | `EDIT_SCENE`, `DELETE_OBJECTS` | Explicitly confirmed removal of an empty ordinary collection |

Compensation that removes any allocated datablock also requires live
`DELETE_OBJECTS`, including cleanup after a failed create. A successful create
does not grant that permission. If cleanup is unauthorized, the allocation is
retained and reported for a later authorized inspection or repair.

All operations require Object Mode and the actual current Scene, window and view
layer. The tools do not switch mode, selection, active Object or window to make a
request admissible. Linked, override, noneditable, shared or unexplained target
ownership is refused where it would expand the mutation scope.

## Static dependency contract

The integrated increment must inventory all native Main ID families before any
generic RNA content reader. Descriptors and exact native owner classes are checked
before property getters. Animation owners anywhere in that inventory invalidate
the initial static profile; inspecting only the named camera or light is
insufficient. An unused or apparently unrelated owner must not be assumed safe
without admission evidence. The global inventory and its bindings are rechecked
at subsequent write boundaries.

Camera, light and focus targets must be unanimated, unparented, unconstrained plain
Objects with supported current-Scene membership and dependencies. Camera/light
data edits require a sole proven Object consumer. Assigning an existing camera
without editing its data remains a separate read-only source-binding case; it
does not authorize edits to another Object's shared camera data. Gravity and unit
changes refuse existing physics whose wider effects have not been qualified.

Unknown runtime properties and custom node classes are refused before their
getters. Reviewed bundled UI/Cycles descriptors may be skipped without resolving
their getters; their presence is not permission to accept arbitrary similarly
named properties. The known Object UI selection field requires its exact reviewed
descriptor and absent stored value. Frame-change and dependency-graph handlers
with unreviewed effects prevent admission.

This is a bounded bridge admission contract. It is not a sandbox for Blender's
host process or a proof that third-party Python cannot affect Blender. Broader
animated, rigged, instanced, procedural and physics workflows remain mandatory
implementation and acceptance work.

## Per-write authority and preservation

Each field setter, allocation, link, removal and compensation rechecks live
Blender authority. Registry checks and callback-backed permission reads finish
before the frozen comparison. Cleanup resolves the complete permission set after
the narrower ToolSpec check, so a provider cannot revoke deletion permission
during that check unnoticed.

The comparison binds native identities and storage lookups, Scene/window/layer,
project filepath, mode, selection, active Object, supported content and consumer
references. A same-name replacement, changed binding, new consumer or newer manual
edit is not adopted as a fresh baseline. Only the exact predicted owned delta may
advance the expected state.

The readonly factory captures and caches each prepared plan and authored boundary
before the first arbitrary cancellation callback or permission provider. The same
boundary remains active through BEFORE, handler writes and AFTER. Bounded capture
diagnostics are deferred until live authorization succeeds, preserving permission
and cancellation denial precedence.

Native undo polling also writes the weak ParticleEdit Scene/Object roles. This
requires a non-null, plain frozen active Object without particle or soft-body
cache sources; null active Objects are refused before checkpoint writes. A
descriptor-first plan admits only zero self references with a null particle Object,
or one self reference with the exact frozen active Object. Only notification after
an actual successful native checkpoint push advances that expectation to one and
the same active Object; a mandatory provider-free comparison follows. Extra aliases
are refused. `Scene.original` remains its frozen exact identity. Marker CAS owns
only the actual checkpoint Scene's validated reserved slot.

These results do not certify preservation of unread bundled runtime settings,
including Cycles SYSTEM properties. In particular, Blender 5.2 can retain those
values outside ordinary custom-property keys. Successful results expose
`preservation_scope.complete: false` and
`preservation_scope.unread_bundled_runtime_settings: true`; `verified` describes
the literal fields, identities, consumers and graph projection actually compared.
The full authored Scene/Main preservation and protected artist acceptance gates
remain open.

Production guarded Scene tools refuse `batch.execute` before its first write.
Whole-plan authored composition has not been qualified; framework tests using
explicit synthetic reviewed specs do not grant production batch admission.

After content reads, the final pure request/job lifetime, cancellation, deadline,
toolset, pause and emergency-stop checks run immediately before the write. No
permission provider or arbitrary cancellation callback runs after that comparison.
Authority loss latches the operation against later writes and automatic recovery.
Native calls remain synchronous and cannot be preempted while running inside
Blender; cancellation is enforced at their boundaries.

Native Float32 storage is compared against its predicted stored values, rather
than requiring a Python decimal to round-trip unchanged. Pointer restoration uses
the original native object identity, not a name lookup or encoded snapshot tuple.
Recursive raw custom-property comparisons retain each exposed scalar type and
the exact finite float spelling, including signed zero. This custom encoding is
separate from the native RNA field and setter prediction representation.
`verified` concerns the admitted structural projection; it is not complete Scene
or mesh-content preservation, rendered appearance or artistic acceptance.

## Collections

The target and every ancestor must have one supported current-Scene path, local
editable data and ordinary native membership. Instance users, extra parents,
cross-Scene sharing and unexplained direct ID references are refused. The embedded
Scene root is a parent for creation; it cannot be renamed or removed through these
tools.

Admission compares actual bounded LayerCollection occurrences and independent
native reference counts. It does not equate `Collection.users` with all references
or force a dependency-graph update to manufacture a valid result. Blender 5.2 can
expose unsynchronized view-layer references immediately after a link; the actual
native tree and counters must agree with the admitted membership.

A new collection is tracked by its returned native identity and exact empty
content before publication. Only that proven owned child may be projected from
the parent's readback. Other settings, consumers and existing memberships remain
compared. Cleanup never removes a foreign allocation selected by name alone.

Deletion requires `confirm_delete=true` and no Objects or child collections. A
nonempty request is refused before removal; no contents are implicitly orphaned.
Native removal has no automatic identity-preserving local rollback. The response
reports `automatic_rollback_available=false`. Checkpoint recovery requires a
separate explicit recovery operation and its own measured verification.

## Cameras, lights and Worlds

Camera edits preserve the guarded native settings and focus/source bindings.
Derived camera angle aliases are accounted for separately from owned lens/sensor
fields. An admitted camera type change must preserve the rest of that measured
native projection; broader conversion behavior is not inferred from it.

Light subtype conversion is currently refused before changing type or settings.
Native research found that setting `Light.type` can leave the existing Python
wrapper at its old subtype, while other subtype settings become hidden. Silently
skipping a requested shape field is not success. Use a supported existing subtype;
complete conversion and hidden-setting recovery remain open work.

The initial World graph admits one built-in Background connected directly to one
active World Output, without custom, nested, muted or parented nodes. Existing
node/socket identities, links, active state and protected settings are compared.
An unrelated shader graph is not reconstructed or simplified to fit this profile.
A shared World may be assigned as an unchanged source where its bindings are
proved; editing it requires sole ownership by the target Scene.

Blender 4.5 creates a new World without a node tree, then initializes the default
Background/Output graph when nodes are enabled. Blender 5.2 creates that graph
immediately and reports nodes enabled; requesting `use_nodes=false` is refused on
5.x. A strength edit requires nodes and cannot be combined with an explicit
disable request.

Constructor output is admitted only through its independently measured native
default contract, with all pre-existing content still compared. A newly allocated
embedded World tree cannot be replaced with the original absence while preserving
identity. If a later operation fails, that retained graph is reported even when
the scalar settings can be restored. Disabling nodes does not prove the new tree
or its effects disappeared.

## Failure and recovery evidence

Failures retain the primary structured error and report `execution_started`,
`possible_mutation`, `rollback_verified`, `verification_required` and affected
Objects where applicable. Restoration is attempted only with fresh authority and
the exact known state. A failed setter may leave only its measured original or
exact predicted output eligible for restoration. Unknown partial vectors, newer
manual edits or changed protected content refuse further compensation.

Typed recovery evidence uses `kind="scene_mutation"`, `owned_write_attempts`,
`restoration_verified` and bounded `retained_effects`. Attempts include direct
field writes and native allocation/publication/removal calls; they are not a count
of successful edits. Retained effects distinguish collection/World allocation
attempts, known allocations, collection removal attempts and embedded World graph
allocation. A native allocation can remain possible even when no field setter ran.

History retains only the reviewed flat evidence fields, with truncation and
incomplete flags. Unknown nested data and native identities are not silently
promoted to history proof. A successful response that reports
`restoration_verified=false` does not assert failure: no restoration was performed.
Likewise, `rollback_verified=false` before any owned write does not prove a
mutation. Interpret those fields with execution and retained-effect evidence.

RNA comparison records, retained buffers and native undo history are not durable
backups. A logical checkpoint may expire or include interleaved manual work.
Broader recovery, memory pressure, mixed manual/bridge editing and durable project
acceptance remain required.

## Evidence and remaining work

The isolated native runner must retain source-matched success, denied permission,
invalid context, protected-state preservation, injected failure and measured
recovery on both target Blender versions. Focused Python tests and development
native probes are separate evidence; neither certifies later edited source or
installed packages. See [native testing](native-testing.md) and
[release evidence](release-evidence.md).

Windows 11 is unqualified and no test machine is currently available. No rendered
visual acceptance or full installed scenario acceptance is claimed. Wider
collection deletion, Light conversion, animated/dependent camera and lighting
workflows, broader World graphs and physics-aware Scene changes remain mandatory
1.0 work. The [release gates](release-1.0-readiness.md),
[requirement ledger](release-1.0-ledger.json) and [execution plan](plan-1.0.md)
remain authoritative; this bounded increment does not waive their full target.
