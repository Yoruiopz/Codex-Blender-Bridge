# Artist task plans, references and protected transforms

**Save availability:** `project.save` currently refuses Save and Save As before
native/path access; see [the safety change](project-save-safety.md). Fresh-process
results below establish feature serialization through owned fixture setup, not a
safe bridge project-save capability. Earlier typed-save reports are historical.

This unreleased increment adds one bounded plan for the active Blender runtime. It
survives MCP client disconnection/reconnection. Runtime reset and project replacement
clear it. Plan text is task data, never executable instructions or permission.

`task.plan.set` accepts a goal of at most 2,000 characters, 1–32 steps and up to 32
unique exact protected object names in the current scene. Each step has an ASCII
`id` (1–64 letters/digits/underscores/hyphens), `description` (1–500 characters),
`status` (`pending`, `in_progress`, `completed`, `blocked`; default `pending`) and
optional `note` (up to 500 characters). Names are at most 63 UTF-8 bytes. The whole
saved representation is limited to 64 KiB UTF-8. The goal updates the task display.

`task.plan.inspect` returns the plan and revision. Replacement, step update, load
over an active plan, persistence and clear require `expected_revision`. Replacement
invalidates its baseline; step status/note updates preserve it. Marking a step
completed records a claim and does not certify its Blender result.

## Step execution and protected observations

`task.plan.preview_transform(..., step_id="revise")` optionally binds the preview
to that exact current step and its runtime plan generation before application.
The association cannot be supplied or retargeted at apply time. Status/note
corrections preserve it; replacement, explicit load, clear, reset and native
undo/redo invalidate old previews, even when plan/step IDs are reused.

An optional `rotation_quaternion=[W, X, Y, Z]` previews authored quaternion
components when the target already uses `QUATERNION` mode. Omit Euler `rotation`
and every `rotation_mode` argument for this request; `transform.set` also refuses
its legacy `rotation_euler` alias alongside the new field. The bounded
[quaternion mutation profile](object-rna-safety.md#quaternion-assignments) applies
to both direct assignment and preview/application. The request is not normalized
or converted and requires complete qualified independent intent for all six
core channels before a write. A step-linked preview retains those Float32 expectations for
explicit [target-channel verification](artist-target-verification.md#quaternion-assignment-expectations);
raw authored-channel agreement remains separate from evaluated or artistic
acceptance. Existing transform inputs retain their previous contracts.

Quaternion assignments require a standalone registered `transform.set` call or
the explicit `task.plan.preview_transform` / `task.plan.apply_preview` sequence.
`batch.plan` and `batch.execute` refuse `transform.set` entries containing
`rotation_quaternion` with `NOT_IMPLEMENTED` before preparing the child. Existing
Euler, location and scale batches retain their previous contracts.

After the outer executor finishes its checkpoint handling and records the actual
operation, `task.plan.inspect` exposes a runtime `step_evidence` journal. It retains
at most 32 receipts FIFO, reports truncation and unexpected recording failure,
and survives MCP reconnect. Receipts include the real outer `operation_id`,
preview/revision provenance, completed/failed/rejected outcome, error code and
measured checkpoint/recovery facts. A failed receipt can describe retained partial
work; it is not rollback proof. Direct registry calls have no outer operation
receipt. Existing unassociated previews remain valid and create no step receipt.

`task.plan.compare(step_id="revise", expected_revision=...)` explicitly attaches
the resulting observation to that step's latest retained receipt. A plain compare
continues to return evidence without attaching it. An intervening bridge writer,
plan/generation change, newer receipt or replaced baseline prevents attachment.
These protected-comparison observations are labeled `protected_objects_only` and
`user_goal_verified=false`: they say nothing about the edited target, appearance,
artistic quality or step completion.

An observation's `validity` is `recorded` while its runtime generation, bridge
mutation revision and retained baseline still match, `stale` after invalidation,
or `unknown` when its snapshot is no longer retained or availability is unknown.
`recorded` describes retained evidence, not a fresh scene inspection; every
observation reports `current_scene_verified=false`. Manual edits and unrelated
native activity require another explicit comparison. Native undo/redo keeps
operation receipts as historical facts and marks their observations stale;
an explicit protected comparison can add a new observation without making that old operation
current. Replacing/loading/clearing/resetting a plan discards the journal entirely.
Saved schema-v1 stays passive and never includes receipts or observation IDs.

The sidebar separates claimed step marks, execution outcomes, protected-only
observation validity and historical target core-channel results. No operation or
comparison implicitly completes a step.
Portable tests cover the receipt and invalidation boundaries. The extended native
`artist_loop` fixture passed on Linux Blender 4.5.14 and 5.2.2 at frozen source
`cdbc1c5`; real manual undo/redo and known recovery are exercised separately by
the interactive `undo_lifecycle` fixture on both builds. These results verify
execution evidence and preservation within the reviewed profile, not artistic intent.

### Explicit target-channel observations

`task.plan.verify_transform(step_id, receipt_id, expected_revision)` separately
compares a current step's latest successful completed preview receipt with its
exact target's authored core transform channels. Its independent Float32
expectation is retained before application, including untouched inactive rotation
channels and signed zero, and exposed as `target_expectation`. Results distinguish
matching/differing channels and a missing/replaced target; changed provenance,
later writers and historical or unavailable expectation profiles refuse before
channel reads.

This read-only `INSPECT_SCENE` method adds a runtime `target_observation`, with
scope `authored_core_transform_channels` and `user_goal_verified=false`. It creates
no checkpoint and never completes a step. Successful calls add no
operation-history entry; failed or rejected calls handled by the executor retain
its existing failure audit. The existing journal's top-level
`scope=protected_objects_only` remains a compatibility label for protected
observations; `target_observation_scope=authored_core_transform_channels`
labels the separate target evidence, and the target record has its own scope.
Both kinds of observation remain historical and report
`current_scene_verified=false` during inspection. The sidebar puts the **Target
core channels:** heading and its status on separate lines, formatting the latest
public receipt: a recorded match, difference, missing target or replacement
remains historical. Stale evidence
takes priority; unavailable expectations, not-yet-verified targets and absent
legacy expectations receive distinct labels, while malformed or unknown records
show unavailable evidence. This presentation adds no plan inspection,
native/context read, verification, capture or save, and does not change protected
observations or claimed completion. See the
[sidebar evidence boundary](artist-target-verification.md#sidebar-evidence).

The first target profile requires an unchanged rotation mode and compares only
location, rotation mode, Euler/quaternion/axis-angle channels and scale. Unsupported
mode conversion leaves existing preview/application behavior intact. Parent,
delta, evaluated/world and visual outcomes require separate evidence. See the
[target-verification contract](artist-target-verification.md) for exact bounds,
receipt lifetime and native acceptance requirements. Its new source-matched native
proof is separate from the earlier artist-loop results above.

Protected scope is **advisory by default**. `task.plan.capture` explicitly snapshots
exact protected objects; `task.plan.compare` reports changed, unchanged-within-scope
or unknown evidence, including missing/replaced objects. Fields, budgets, eight-snapshot
eviction and unmeasured data follow [scene evidence](scene-evidence.md). Image pixels,
artistic quality and full transitive dependencies are not certified. Responses report
whether runtime protection is enabled; comparison never enables it.

## Explicit runtime enforcement

`task.plan.enforce(enabled=true, expected_revision=...)` opts into a bounded static-prop
profile with at least one exact protected object. It resolves current protected identities,
requires inspection consent, and refuses an active background job or nested enablement
inside another executing request. It grants no permissions. The plan cannot be replaced,
loaded over or cleared while enforcement is enabled. Status/note corrections remain possible
without changing the protection generation. Explicit disable uses `enabled=false` and the
current revision, remains possible under pause/emergency stop, and records an operation-history
audit. Cancellation/inspection denial still prevents the control change. Reconnect preserves
runtime protection; reset/project replacement clears it.

An in-flight mutator is also counted by the surviving Blender tool registry. Replacing or
clearing runtime plan/project state and resetting enabled toolsets cannot hide that writer
and enable a new protected plan before its handler finishes. Both counters unwind on failure;
they are runtime bookkeeping and are never restored from saved JSON.

Every native undo and redo, including a known bridge recovery, invalidates all runtime
references/previews and advances the protection generation even if Blender restores identical
object identities, context and authored values. Reinspect and create new handles afterward.
The plan, active protection, baseline and in-flight mutator counter remain intact. An already
active preview or write boundary keeps its prior generation and cannot continue or compensate
across that history change. This invalidation does not grant whole-scene undo while armed.

Only `transform.set`, `transform.translate`, `transform.rotate`, `transform.scale` and
`task.plan.apply_preview` currently have reviewed modifying scope. Other modifying tools,
including context selection/mode, mesh/material/rig edits, batch execution, viewport/render
capture, persistence, project saving and whole-scene undo, fail before their handler or
automatic checkpoint while protection is enabled. Native checkpointing for accepted
transforms remains available. No cleanup/recovery tool implicitly disables the policy.

Scope follows incoming native Object ID consumers, up to 32 Objects and 100 direct users per
Object. Direct/transitive protected consumers reject the edit. An outbound read-only reference
and a sibling sharing Mesh data are not transform targets. Ordinary Scene/Collection membership
does not add every scene object; unknown references, linked/shared/instanced ownership and
excluded consumers fail closed. Policy generation, protected identities, context, authored
state and consumer closure are checked after live callbacks before owned fields and compensation.
A late stop, disconnect, policy change or manual edit can retain measured partial work; it
does not authorize a later field or unsafe rollback.

The profile caps the project at 256 Objects, 256 collections, 16 scenes, 1,024 native IDs and
512 collection child links, with 32 owning collections per Object and 32,768 affected geometry/
attribute records. It rejects all drivers, dependency/frame handlers, affected animation/rigs/
shape keys, instances, implicit physics, Geometry Nodes roles, and writable runtime RNA
descriptors that would be read. Blender's bundled `Object.active_selection_set` UI index is
excluded from artist snapshot readers; its content is unmeasured. Unread readonly collection/UI
descriptors and unrelated workspace fields are not evaluated. Other domains/larger scenes
need further reviewed profiles. Native `user_map` remains a blocking scan; these budgets do
not establish interruptibility, a universal deadline or a native memory cap.

This enforces bridge-owned authored writes in the supported profile. It is not a sandbox
for arbitrary installed Python, message-bus callbacks, timers, monkeypatches or other processes,
nor proof that composition, evaluated simulation, appearance or the user's goal is unchanged.

## Exact references and matched previews

`task.reference.resolve(source="selection")` records current selection, or
`source="objects", object_names=[...]` resolves 1–32 exact current scene/view-layer names.
It never infers pronouns, screenshot meaning or similarity. Scene, layer, selection, active
object, mode, frame, filepath, identities and protection generation must still match when used.
At most 16 runtime references are retained FIFO.

`task.plan.preview_transform(reference_id=..., expected_revision=..., location=...,
rotation=..., scale=..., rotation_mode=...)` previews one referenced object's typed
`transform.set` change. Multi-object references also need `object_name` from that reference.
The result reports current/requested authored channel differences and reviewed consumers.
It edits no scene data, requires inspection only, and grants no edit authority. It does not
predict evaluated geometry, a final image or artistic quality.

`task.plan.apply_preview(preview_id=..., expected_revision=...)` requires live inspection
and transform consent and consumes the preview once. An 8 MiB bounded authored/context/
consumer fingerprint must match at preflight and the new write boundary after nested-dispatch
callbacks. At most eight previews are retained FIFO; their references may expire sooner.
Stale/evicted/consumed previews require a fresh preview. Step corrections can advance the plan
revision without changing protection; apply still requires the current revision.

The bounded loop is inspect → plan/capture protected evidence → enable → resolve reference →
preview → checkpoint/apply → compare → record correction → preview/apply again. Visual review,
wider coverage and an authorized save while protection remains enabled are open UX-01
requirements. Do not disable a user's negative constraints to bypass unsupported tools.

## Native checkpoint admission for the artist profile

Interactive native undo pushes poll particle editing even in Object Mode. On the
reviewed Blender builds that poll can bind the Scene's weak particle Scene/Object
roles to the frozen active Object. The original raw consumer fingerprint therefore
refused a real first preview apply when Scene references changed from membership
count 2 to membership plus this weak role, count 3. The refusal is retained as
negative evidence; a passing background fixture did not exercise this boundary.

Artist preview/protected-transform admission now retains one authored write Boundary
before permission providers. The exact same Boundary follows native checkpoints,
the exact nested preview transform, verified channel assignments, compensation and
finalization. A frozen preview role-origin cannot be advanced or replaced; a
separate call-owned role plan advances only during authenticated successful native
push delivery and then must pass readonly comparison. An untrusted notification,
failed/zero push, owner loss, newer authored value or changed preview cannot adopt
a replacement baseline.

The consumer projection removes only that separately proved weak particle Object
reference. Camera use, ordinary membership counts and all other consumers remain
literal. Writable ParticleEdit and ParticleBrush fields and brush identity are
fingerprinted before and after binding. Both exact reviewed runtimes expose a null
ParticleBrush curve getter; a non-null curve is refused rather than omitted. Runtime
getters and changed native descriptors remain refused before those values are read.
The particle adapter uses the existing artist profile for active-Object validation;
particles and soft-body cache sources remain unsupported.

Artist admission also accepts `(1, previous Object A)` before transforming active
Object B when it can freeze a separate readonly witness for A. The immutable
preview origin retains that exact witness through call-owned forks. Only an
authenticated completed push predicts the weak reference's removal from A and
addition to B; both Objects' Scene consumers are projected using that exact phase.
The previous Object is not added to B's write-affected closure. A protected previous
Object remains readonly, while a protected Object actually affected by B remains
refused. Camera references, membership and all other consumers remain literal.
Scene/render checkpoint admission retains its original strict initial-pair policy.

The previous-owner witness currently accepts local static Empty/Mesh Objects under
the existing artist profile. It measures the Object's authored channels, geometry,
attributes, UV/color/group roles, native settings children and incoming Object
consumer closure. It also measures exact Mesh/Material/node-tree direct consumers
and up to sixteen Materials with at most eight native Principled/output nodes each,
including socket defaults, links, interface state and typed custom values. Material
evidence is limited to one MiB each and the entire witness to eight MiB. An incoming
consumer may be B: its reference topology is frozen without freezing B's requested
transform values. The existing 32-Object closure limits apply separately to B's
write-affected closure and A's readonly consumer closure.

The Mesh's clone/stencil UV selectors are admitted only as exact aliases into its
own bounded UV-layer inventory. Their native pointer descriptors and fixed layer
type are validated before reading them; the witness retains the selected layer's
index, identity and name alongside its authored data and roles. A null selector is
retained literally. Blender 4.5's native getters select existing CustomData layers,
whereas the reviewed 5.2 getters can return null for unset UV-name selectors. A
foreign, missing, renamed, replaced or reordered layer fails the retained proof;
other non-null Mesh dependency pointers remain unsupported. The original 4.5 first-preview refusal at `40ad506` remains retained negative
evidence. After the exact same-Mesh alias fix, `artist_multitarget` and
`undo_lifecycle` passed on both Linux builds at `cdbc1c5`; the earlier 5.2 result
is historical evidence for its own source.

Unmeasured outbound sources are refused: custom ID references, non-null component
source pointers, asset metadata, skin layers, material animation, image/group/object
shader dependencies and nonempty material interfaces. The inherited literal artist
profile does not certify unread bundled runtime settings or derived caches. Broader
previous-owner types and dependency profiles remain mandatory full UX-01 work;
these refusals do not remove them from the target. A→B→A, protected material drift,
wrong-owner callbacks, stale origins and denied/failed pushes are covered by
portable tests and focused native cases. At `cdbc1c5`, both Linux builds passed
actual A→B→A edits with a protected previous owner and material-drift denial before
checkpoint/write. Interactive undo retained operation provenance while invalidating
reference and observation currency. At `bf3696f`, the separate Scene checkpoint
fixture passed authenticated completion and native-push fault controls on both builds.
Unarmed ordinary transforms keep their existing broad behavior; their
entry-policy guard does not claim authored checkpoint admission. These are
source-specific development results; full UX-01 and release gates remain open.

## Saved plan data

`task.plan.persist(confirm=true, expected_revision=...)` requires live `INSPECT_SCENE`
and `EDIT_SCENE`, an editable local scene and current exact protected scope. It stores
validated schema-v1 JSON in `_blender_codex_bridge_task_plan_v1` and participates in native
checkpoint/history. It does not save the project or write external files. An independently
authorized save with `SAVE_PROJECT` remains required for disk persistence. Persistence
and saving are unreviewed under active protection and are refused.

Persistence checks live permission, cancellation, pause/stop, context, plan revision, protected
identities and the exact previous property after callbacks. Recovery requires the same live
gates and an owned value; newer manual text or unknown partial assignments are retained with
explicit recovery evidence. Non-text/oversized storage is refused.

`task.plan.load` explicitly validates that bounded JSON, rejecting duplicate/unknown/invalid
fields and unresolved protected names before replacement. No text is evaluated and no snapshot
ID, protection generation, reference/preview or live identity is accepted. Names resolve afresh.
Loading begins advisory; capture a new baseline and explicitly enable protection afterward.

`task.plan.clear` clears runtime data/task display only after explicit disablement. Stored JSON
remains until explicitly replaced. Full visual reference understanding, wider protected authoring,
protected save and complete artist acceptance remain open.
