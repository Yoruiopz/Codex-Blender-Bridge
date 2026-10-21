# Artist task plans and advisory protected scope

This unreleased increment adds one bounded plan for the active Blender runtime. It
survives MCP client disconnection/reconnection. Runtime reset and project replacement
clear the plan; a different scene or replaced protected-object identity requires
explicit correction before creating a new baseline. Plan text is task data, never
executable instructions or permission to change Blender.

`task.plan.set` accepts a goal of at most 2,000 characters, 1–32 steps and up to 32
unique exact protected object names in the current scene. Each step has an ASCII
`id` (1–64 letters/digits/underscores/hyphens), `description` (1–500 characters),
`status` (`pending`, `in_progress`, `completed`, `blocked`; default `pending`) and
optional `note` (up to 500 characters). Object names are at most 63 UTF-8 bytes.
The whole saved representation is limited to 64 KiB UTF-8. The plan goal also
updates the existing concise Blender task display.

`task.plan.inspect` returns the current plan and revision. Replacing an active plan,
updating a step through `task.plan.update`, loading over an active plan, persisting
or clearing requires its `expected_revision`. Replacement invalidates its previous
protected baseline; step status/note updates preserve that baseline. Marking a step
completed records a claim and does not certify its Blender result.

Protected scope is **advisory**. These tools do not enforce preservation across other
mutators. `task.plan.capture` explicitly snapshots the exact protected objects through
the existing bounded structural evidence store. `task.plan.compare` reports changed,
unchanged-within-scope or unknown evidence, including missing/replaced objects.
Fields, budgets, truncation, eight-snapshot eviction and unmeasured data follow
[scene evidence](scene-evidence.md). Image pixels, artistic quality and full
transitive dependencies are not certified by this comparison. Capture an appropriate
viewport/render separately when appearance matters. Every response explicitly reports
`protected_scope_enforced: false`.

`task.plan.persist(confirm=true, expected_revision=...)` requires live `INSPECT_SCENE`
and `EDIT_SCENE`, an editable local scene and a current exact protected scope. It
stores validated schema-v1 JSON in the active scene custom property
`_blender_codex_bridge_task_plan_v1` and participates in native checkpoint/history.
It **does not save the project** or write external files. An independently authorized
project save with `SAVE_PROJECT` is still required for disk persistence.

`task.plan.load` explicitly reads that property. It rejects oversized, malformed,
duplicate-key, unknown-version and invalid-schema JSON and unresolved protected names
before replacing the runtime plan. No saved text is evaluated, no permission is granted,
and no saved snapshot ID or live object identity is accepted. Protected names are
resolved again against the current scene; capture a new baseline after loading.

`task.plan.clear` clears the runtime plan and concise task display. It leaves stored
scene JSON unchanged. Persist an explicitly corrected plan to replace stored content.
This increment supplies plan tracking and explicit evidence; variants, reference
understanding, automatic previews, universal protected-scope enforcement and complete
artist acceptance remain open.
