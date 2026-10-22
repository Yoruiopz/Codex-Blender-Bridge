# Artist task plans, references and protected transforms

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
