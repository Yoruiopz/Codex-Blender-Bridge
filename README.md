# Blender Codex Bridge

Let Codex inspect and edit Blender through local, permission-controlled MCP tools.
Work with objects, meshes, materials, UVs, rigs, animation, lights and renders, with
status, permissions and recovery controls inside Blender.

**[Published 0.6.0 alpha](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.6.0)** ·
[0.7.0 alpha candidate](docs/releases/0.7.0.md) ·
[GitHub releases](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases) ·
[Release evidence](docs/releases/0.6.0.md#verified-evidence) ·
[Install](#install--no-source-build-needed) · [Troubleshooting](docs/troubleshooting.md) ·
[Contribute](CONTRIBUTING.md)

This is **alpha software**. Try it on a disposable scene or a copy of your project.
The published **0.6.0 alpha** dates to October 25, 2026 at **14:29:56 UTC**, from
`73cad805903fcd0be9175b49a5ecf78505ecd4a5`. It adds bounded isolated geometry previews
and history-failure containment, with [exact-source CI, selected Linux native and
installed-package evidence](docs/releases/0.6.0.md#verified-evidence). All six release
assets were verified through anonymous downloads. The current development checkout
can contain later increments; the published evidence applies to that exact release.
The [GitHub releases page](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases)
is the authority for accepted artifacts. Earlier releases, including the separate
[0.5.0 4K/UV evidence](docs/releases/0.5.0.md#verified-evidence), remain available.
Use matching add-on, MCP server and optional plugin artifacts from one accepted build.

This checkout prepares the **[0.7.0 alpha candidate](docs/releases/0.7.0.md)** with
retained direct-weight edits, the bounded `RAW_FREE_POINT_V1` curve writer and a
populated selected-field protection test for isolated geometry previews. Candidate
package, exact-commit CI and installed qualification remain pending; **0.6.0 remains
the recommended download**. The preview's selected-data checks do not qualify
appearance or complete protected objects. Reported image-review discrepancies are
retained in the candidate notes and require resolution before visual acceptance.

Development targets **official, unmodified Blender only**, without a fork or custom
distribution. The new [geometry preview](docs/geometry-preview.md) renders bounded
authored meshes in a separate official Blender process; original materials and current
viewport appearance are excluded. Ordinary viewport capture remains available when artist protection
is unarmed. Protected viewport capture still refuses until a stock-Blender redesign is
qualified; see [capture status and preservation requirements](docs/protected-capture-design.md).

**1.0 is not ready.** Follow the [development status](docs/development-status.md),
[roadmap](docs/roadmap.md) and [release plan](docs/plan-1.0.md).
All 29 implementation items and 14 stable-release gates remain open; the
[published blocker plan](https://github.com/Yoruiopz/Codex-Blender-Bridge/blob/codex/release-0.6-publication-evidence/docs/releases/0.6.0-blocker-plan.md)
records the remaining implementation and validation steps.
Windows compatibility work and Windows testing are **deferred**. Linux development evidence
does not qualify Windows 11, the Windows Blender 4.5 LTS/stable 5.x matrix, or the installed
end-to-end workflows required by the [release gates](docs/release-1.0-readiness.md).

## Install — no source build needed

The instructions below install the published **0.6.0 alpha**. Use its matching
artifacts and [release-specific qualification evidence](docs/releases/0.6.0.md).

You need Blender **4.2+**, standalone **Python 3.10+**, and a local Codex client with MCP
support. Blender's bundled Python does not run the MCP server. The declared minimum is not
a guarantee that every Blender version or platform is tested; see the
[accepted 0.6.0 release](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.6.0) for its evidence.

### 1. Download the packages

Get these assets from the [0.6.0 release](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.6.0):

| Asset | Purpose |
| --- | --- |
| `blender_codex_bridge-0.6.0.zip` | Required Blender add-on; keep it zipped |
| `blender_codex_bridge-0.6.0-py3-none-any.whl` | Required standalone MCP server |
| `blender-codex-bridge-plugin-0.6.0.zip` | Optional Codex plugin and workflow guidance |
| `SHA256SUMS.txt` | Download checksums |

Verify the three installers against `SHA256SUMS.txt`. Use the release assets
rather than GitHub's automatic source archives.

### 2. Install in Blender

In **Edit → Preferences → Add-ons → Install from Disk…**, select the add-on ZIP and enable
**Blender Codex Bridge**. Open a **3D Viewport**, press **N**, open **Codex Bridge**, review
permissions and click **Start Bridge**. Keep the listener at `127.0.0.1:9876`.

### 3. Connect Codex

Install the wheel in a standalone Python virtual environment, then register its absolute
`blender-codex-mcp` executable path with Codex. The [installation guide](docs/installation.md)
has copyable Windows and macOS/Linux commands, checksum checks and optional plugin setup.
Use manual MCP registration or plugin registration once. Start a new Codex task afterward.

### 4. Try it

Begin with a read-only request:

> Check Blender bridge status, summarize my scene, and inspect my selection. Do not change anything.

Then try a small edit on a disposable scene:

> Create a cube named BridgeTest. Inspect it afterward and show me a preview. Do not save the project.

Codex can enable a toolset. Only you can grant Blender permissions in the panel.

## How it works

**Codex → local MCP server → Blender add-on → Blender main thread.**

The add-on checks permissions and returns measured state for verification. Its sidebar shows
status, toolsets, permissions, history, **Pause**, **Emergency Stop** and recovery controls.
Inspect before editing, create a checkpoint, and verify the result structurally and visually.

### Scope and limitations

- Keep Blender and the MCP server on the same trusted workstation. Never expose or tunnel
  the loopback listener; it does not authenticate other local processes.
- Scene summaries and captures go to your AI client. Local transport does not mean local-only
  model processing. Share project data only when appropriate for that client.
- Tools support bounded, documented subsets of Blender. Mode, selection, ownership and
  dependency restrictions can refuse an edit. A successful response still needs verification.
- Checkpoints use Blender's finite global undo history. They can include interleaved manual
  work and do not replace backups. A failed batch can leave earlier edits applied.
- Stop/cancel controls act at safe boundaries. An active native Blender operation may finish
  first; inspect current state before retrying. Save only when intended.
- Arbitrary Python is disabled by default, needs four broad permissions together and is
  **not a security sandbox**. Use structured tools for normal work.

Read the [security model](docs/security.md) and [recovery limits](docs/native-recovery.md).

## Features

### Published 0.5.0 additions

Surface-paint jobs admit up to 4,096² source and stencil pixels, with explicit finite work
caps, 64×64 ownership tiles and complete input/output hashes. Synchronous surface painting
retains its smaller limit. Generated-image sculpt-mask sampling also admits 4,096² pixels,
with bounded channel copying and full input revalidation; this read remains synchronous.
These source profiles are documented in [surface painting](docs/image-surface-paint.md) and
[sculpt masks](docs/surface-brushes.md). The published source has bounded complete-pixel,
deadline, memory and interruption evidence on two Linux builds; visual and
constrained-memory acceptance remain open. Those 0.5.0 results stay specific to
that source; 0.6.0 has separate selected qualification evidence.

The integrated [direct UV guard](docs/uv-edit-safety.md) covers `uv.coordinates_set`,
`uv.transform` and `uv.pin` within a static, material-free, single-user Edit Mode profile.
It retains exact intent and attempted-field recovery; unsupported dependencies, unknown
outcomes and authority loss refuse further writes. Full UV workflows, native undo, durable
recovery remain open. See the [0.5.0 evidence and limits](docs/releases/0.5.0.md).

### Artist-workflow foundations carried from 0.4.0 alpha

The published 0.4.0 alpha provides artist plans, exact runtime references, reviewed transform
preview/apply and independent target-channel observations. Step marks and historical receipts
do not certify the user's goal. It also adds bounded mesh repair and UV authoring, explicit
sculpt/vertex-color brushes, weight brushes and geometric transfer, Action/F-curve inspection
and sampling, reviewed rig controls, nested node workflows and bounded jobs. Quaternion
assignment preserves raw WXYZ components within a strict existing-mode static-mesh profile.
See the [0.4.0 notes](docs/releases/0.4.0.md) and each linked domain contract for limits.

Safety changes narrow unsupported ownership, checkpoint, callback and recovery paths.
**`project.save` is unavailable**, protected viewport capture and shader-interface removal
remain unsupported, and the known Blender 5.2.2 import quarantine stays in place. The
current UV guard retains its separate restricted profile and qualification requirements.
Published bounded export/weight checks do not establish full production delivery or
character-workflow acceptance; the tool inventory cannot supply that evidence.

### Previously published 0.3.0 alpha

The **published 0.3.0 alpha** includes inspection and viewport evidence, object lifecycle and
transforms, selection-scoped mesh editing, materials and shader nodes, UV unwrap/packing,
reviewed modifiers and constraints, rigging/keyframes, scene/camera/light/world/render tools,
and explicit saving. Its 20 additions provide selection/mode control, filtered queries,
bulk origin-based layout, ordered batches and allowlisted Geometry Nodes editing.
See [release notes](docs/releases/0.3.0.md) and [workflow examples](docs/agent-workflows.md).

### Earlier 0.3.0 agent workflows

Use precise queries, compact inspection and small batches to reduce round trips. A batch plan
checks availability and permissions, not simulated scene results. Blender executes serially;
inspect partial failures before retrying. See [batch and Geometry Nodes limits](docs/agent-workflows.md).

<a id="unreleased-structured-uv-seams"></a>

Candidate mesh/UV, painting, shader, character, procedural, simulation and delivery contracts
are tracked in [development status](docs/development-status.md), including the
[structured UV-seam contract](docs/development-status.md#unreleased-structured-uv-seams).
They are absent from the 0.3.0 downloads. Historical UV planner/probe research is distinct
from the integrated three-tool guard and does not qualify its complete workflow.

Current development contracts include [packed recovery jobs](docs/image-recovery-jobs.md),
[shader interface plans](docs/shader-interface-lifecycle.md),
[guarded rig edits](docs/rig-edit-boundaries.md) and the
[two-bone animation benchmark](docs/character-nla.md).

Published 0.6.0 includes bounded isolated authored-geometry preview jobs.
They use a separate official Blender worker and a new opaque view. The worker
never opens the source project; original-material appearance and complete hidden-Main
preservation remain unqualified. Selected source and installed checks passed;
see [the release evidence](docs/releases/0.6.0.md#verified-evidence) and
[geometry-preview limits](docs/geometry-preview.md).

### Complete tool inventory — current source

This generated inventory describes the **current development source**, including bounded tools
whose acceptance remains subject to their documented limits. It is checked against the
registry in CI. It does not describe the 108-tool 0.3.0 download.
The local recovery UI also has an add-on-only action, not an extra MCP tool.

<!-- BEGIN GENERATED MCP TOOLS -->
Current registry: **268 MCP tools**.

<details>
<summary>core — 36 tools</summary>

| Tool | What it does |
| --- | --- |
| `bridge.status` | Report Blender bridge, project, mode, and permission status. |
| `bridge.task.clear` | Clear the current high-level task from Blender's UI. |
| `bridge.task.set` | Show the current high-level Codex task in Blender's UI. |
| `checkpoint.create` | Create a logical agent undo checkpoint. |
| `checkpoint.list` | List checkpoint labels, operation history and conservative recovery availability. |
| `checkpoint.undo_last` | Use Blender global undo only with explicit acknowledgement of user-interleaving risk. |
| `jobs.cancel` | Request safe-point cancellation of an exact job, not rollback; available while paused. |
| `jobs.inspect` | Inspect session-local image or bounded rigid-evaluation job progress, result/error and retained effects. |
| `jobs.list` | List bounded session-local image and rigid-evaluation jobs and retained Scene receipts; no durable queue. |
| `object.inspect` | Inspect one object without dumping raw vertex coordinates. |
| `preview.geometry_image` | Retrieve a successful fresh geometry-preview PNG from this session; stale/expired handles refuse. |
| `preview.geometry_start` | Start one bounded isolated authored-geometry preview job; no source Main or original material appearance is changed. |
| `project.info` | Inspect project metadata and render settings. |
| `project.save` | Project saving is unavailable until native save side effects can be bounded. |
| `scene.compare` | Compare current measured object fields with a session snapshot; report incomplete coverage. |
| `scene.inspect` | Return a compact authoritative structural scene representation. |
| `scene.snapshot` | Capture bounded structural evidence for explicitly named objects and fields. |
| `scene.summary` | Return an LLM-oriented structural and textual scene summary. |
| `selection.inspect` | Inspect active and selected objects or mesh elements. |
| `task.plan.apply_preview` | Apply an exact runtime transform preview once after renewed permission, identity, context and consumer checks. |
| `task.plan.capture` | Capture bounded structural evidence for exact protected scope without enabling enforcement. |
| `task.plan.clear` | Clear runtime plan only; scene-stored JSON remains until explicitly replaced. |
| `task.plan.compare` | Explicitly compare protected scope with its transient baseline; incomplete coverage is not preservation proof. |
| `task.plan.enforce` | Explicitly enable/disable runtime protected scope; unreviewed modifying tools fail closed while enabled. |
| `task.plan.inspect` | Inspect runtime plan steps, revision and current protected-scope policy. |
| `task.plan.load` | Explicitly validate/load saved scene JSON as plan data; never executes text or restores session baselines. |
| `task.plan.persist` | Explicitly store validated plan JSON in a scene property; never saves the project. |
| `task.plan.preview_transform` | Preview exact transform channels and reviewed affected consumers without editing or acquiring edit authority. |
| `task.plan.set` | Create/correct a bounded artist plan with advisory protected objects; replacement requires current revision. |
| `task.plan.update` | Correct an exact step's status/note at the expected plan revision. |
| `task.plan.verify_transform` | Compare a current step receipt's independently retained intended core transform channels with the exact target; never completes the step. |
| `task.reference.resolve` | Resolve exact object names/current selection to bounded runtime references without granting authority. |
| `toolsets.disable` | Disable a local MCP domain toolset. |
| `toolsets.enable` | Enable a lazy local MCP domain toolset. |
| `toolsets.list` | List local MCP toolsets and their enablement state. |
| `viewport.capture` | Capture a viewport image; temporary settings are restored but Render Result is replaced. |

</details>

<details>
<summary>animation — 14 tools</summary>

| Tool | What it does |
| --- | --- |
| `animation.action_bind` | Assign/clear an exact object Action/slot with expected old binding and explicit affected-object scope. |
| `animation.action_copy` | Copy and bind an explicit independent active Action; source remains in this session, unused source retention across saves is not guaranteed. |
| `animation.action_create` | Create an unbound OBJECT-slot Action with explicit fake-user retention; never saves. |
| `animation.action_inspect` | Inspect one exact Action's bounded content, slots, direct references and save retention. |
| `animation.action_remove` | Confirm removal of one unused unretained Action ID without unlinking or automatic recreation. |
| `animation.action_update` | Rename/set fake-user retention on one Action; clearing retention additionally needs DELETE_OBJECTS. |
| `animation.curve_edit` | Edit bounded raw co/value and FREE handle fields of existing ordinary Object keys; interpolation, handle-type, extrapolation and full-update profiles remain unsupported. |
| `animation.curve_inspect` | Inspect an exact active-Action curve's extrapolation and paged keyframes with full Bezier handles; never update or evaluate animation. |
| `animation.curve_sample` | Sample bounded direct values of one exact active-Action curve; no scene, NLA, driver, constraint or deformation evaluation. |
| `animation.inspect` | Inspect one object's bounded action, F-curves, keyframes, slots, and drivers. |
| `animation.keyframe_delete` | Delete a keyframe from an explicit object RNA data path. |
| `animation.keyframe_insert` | Insert a keyframe on an explicit object RNA data path. |
| `animation.set_frame` | Set the current scene frame and subframe explicitly. |
| `animation.set_range` | Set the scene playback and optional preview frame ranges. |

</details>

<details>
<summary>animation_layers — 12 tools</summary>

| Tool | What it does |
| --- | --- |
| `animation_layers.inspect` | Inspect bounded object drivers, NLA tracks and strips. |
| `drivers.add` | Create a non-scripted transform driver from explicit independent source objects. |
| `drivers.remove` | Remove one exact object transform driver. |
| `nla.add_strip` | Add an existing action as an explicit NLA strip on a new named track, with slot selection. |
| `nla.clip_add` | Add one explicit Action/slot clip into an existing unlocked track without overlap or channel mapping. |
| `nla.edit_strip` | Configure a named single-track CLIP strip or explicitly remove it. |
| `nla.edit_track` | Rename, mute or lock an exact NLA track, or remove an unlocked empty track without deleting actions. |
| `nla.push_down` | Push a standard active action into a new top NLA track, preserving its action/slot and frame range; rollback on failure. |
| `nla.solo_track` | Set an exact track's solo state; replacing another solo requires explicit acknowledgement and unlocked tracks. |
| `nla.track_reorder` | Reorder the complete explicit track permutation with native identities preserved; requires an existing NLA Editor. |
| `nla.transition_add` | Create one real native transition between explicitly named adjacent gapped clips; requires an existing NLA Editor. |
| `nla.transition_remove` | Confirm removal of exactly one native transition while preserving its neighboring clips and Action contents. |

</details>

<details>
<summary>asset_delivery — 4 tools</summary>

| Tool | What it does |
| --- | --- |
| `asset.export` | Export a current previewed asset to an approved unused GLB/FBX path. |
| `asset.export_preview` | Preview exact static/skinned asset scope and GLB/FBX format limits. |
| `asset.import` | Import a current preview over frozen private source bytes into a new owned collection. |
| `asset.import_preview` | Validate complete approved static GLB/FBX bytes and preview source/destination fingerprint. |

</details>

<details>
<summary>batch — 2 tools</summary>

| Tool | What it does |
| --- | --- |
| `batch.execute` | Run 1-32 structured steps serially; one logical undo marker, stop on error, no atomic rollback. |
| `batch.plan` | Preflight 1-32 structured steps for shape and static permissions, not scene state or handler arguments. |

</details>

<details>
<summary>compositor — 3 tools</summary>

| Tool | What it does |
| --- | --- |
| `compositor.create` | Initialize a missing compositor graph without replacing existing work. |
| `compositor.edit` | Add/remove/configure reviewed compositor nodes and edit exact socket defaults/links. |
| `compositor.inspect` | Inspect bounded scene compositor nodes, sockets and links. |

</details>

<details>
<summary>constraints — 4 tools</summary>

| Tool | What it does |
| --- | --- |
| `constraint.add` | Add an allowlisted object constraint with an explicit target where required. |
| `constraint.inspect` | Inspect bounded object constraints and allowlisted settings. |
| `constraint.remove` | Remove one explicitly named object constraint. |
| `constraint.set` | Set direct allowlisted RNA properties on one object constraint. |

</details>

<details>
<summary>geometry_nodes — 25 tools</summary>

| Tool | What it does |
| --- | --- |
| `geometry_nodes.attach` | Attach an explicit geometry node group to an exact named object modifier. |
| `geometry_nodes.create` | Create a geometry node group with geometry IO and optional passthrough. |
| `geometry_nodes.group_attach` | Attach a recursively reviewed nested GN graph to one mesh object. |
| `geometry_nodes.group_bind` | Bind a reviewed nested GN group through a uniquely named instance. |
| `geometry_nodes.group_copy_for_node` | Copy one nested GN instance root while retaining referenced descendants. |
| `geometry_nodes.group_link` | Link exact socket identifiers in a reviewed nested GN graph. |
| `geometry_nodes.group_remove` | Remove only an explicitly confirmed unused GN group. |
| `geometry_nodes.group_set_input` | Set an unlinked constant by exact socket identifier in a reviewed GN graph. |
| `geometry_nodes.inspect` | Inspect a bounded geometry graph, interface, and direct users. |
| `geometry_nodes.interface_add` | Add a typed interface socket to an explicit geometry node group. |
| `geometry_nodes.interface_edit` | Rename/reorder/set one nested interface socket default while preserving existing consumer values. |
| `geometry_nodes.link` | Link exact compatible geometry-node sockets without graph cycles. |
| `geometry_nodes.modifier_inspect` | Inspect stored GN modifier inputs by stable interface identifiers. |
| `geometry_nodes.modifier_set_input` | Set an object-owned GN modifier constant without changing the shared graph. |
| `geometry_nodes.node_add` | Add a compatible geometry node with validated settings. |
| `geometry_nodes.node_remove` | Remove an exact geometry node and its incident links. |
| `geometry_nodes.node_set_input` | Set an exact geometry node input's scalar or vector default. |
| `geometry_nodes.node_set_properties` | Configure allowlisted direct scalar/enum properties of a geometry node. |
| `geometry_nodes.unlink` | Remove links between exact geometry-node sockets. |
| `geometry_nodes.zone_create` | Create a paired repeat/simulation zone with bounded constant iterations. |
| `geometry_nodes.zone_inspect` | Inspect paired zone item identifiers/types within 32 items; no cache-state assertion. |
| `geometry_nodes.zone_item_add` | Add a reviewed state/repeat item to an exact zone output. |
| `geometry_nodes.zone_item_convert` | Convert one unlinked paired numeric zone item preserving identifiers with explicit replacement defaults. |
| `geometry_nodes.zone_item_edit` | Rename/reorder an exact zone item or remove an unlinked non-geometry item. |
| `geometry_nodes.zone_remove` | Remove both boundaries of an exact zone and incident links. |

</details>

<details>
<summary>interaction — 4 tools</summary>

| Tool | What it does |
| --- | --- |
| `context.set_mode` | Set a named object's mode; non-Object modes isolate selection and require EDIT_MESH or EDIT_ANIMATION. |
| `mesh.components_inspect` | Inspect paginated component indices and measured centers on the active single Edit Mode mesh. |
| `mesh.select_components` | Select bounded explicit indices on the active single Edit Mode mesh; return refreshed selection ID. |
| `selection.set` | Set exact Object Mode selection and active object; do not change visibility or mode. |

</details>

<details>
<summary>layout — 4 tools</summary>

| Tool | What it does |
| --- | --- |
| `object.align` | Align explicit independent objects by evaluated world origins along one axis. |
| `object.distribute` | Space explicit independent object origins evenly on one world axis while preserving endpoints. |
| `object.transform_batch` | Prevalidate and apply up to 128 explicit independent-object transforms in one logical operation. |
| `scene.query` | Query bounded current-view-layer objects by glob, type, collection, visibility, selection, and evaluated world origin. |

</details>

<details>
<summary>materials — 26 tools</summary>

| Tool | What it does |
| --- | --- |
| `image.create` | Create a new float linear-color/data canvas up to 4096/axis and 16,777,216 pixels; native transfer is not preemptible, no overwrite/file writes. |
| `image.export_job_start` | Accept a frozen-source PNG/EXR no-overwrite export and verified reimport job; poll terminal file/image effects, undo never removes files. |
| `image.inspect` | Inspect bounded image metadata/direct users without loading unloaded buffers. |
| `image.inspect_pixels` | Inspect complete RGBA digests/samples; default statistics <=1M pixels, explicit include_statistics=false for <=16M (no ranges/nonfinite scan); FILE reads need external-file consent. |
| `image.load` | Load a new bounded PNG/JPEG/plain FLOAT RGBA EXR from Blender's approved texture folder; no implicit reuse or file writes. |
| `image.pack_version` | Create a distinct packed FILE_BYTES version or exact raw CURRENT_PIXELS snapshot, <=1M pixels; no save/binding. |
| `image.paint_job_start` | Accept one source/mask-frozen tiled paint job up to 16,777,216 pixels; poll evidence, keep owner connected, native commit is not preemptible. |
| `image.paint_surface_job_start` | Accept one frozen-input surface paint job; private overlap/projection/visibility/painting yields after delivery, poll final pixel/recovery evidence. |
| `image.paint_surface_version` | Project bounded orthographic world strokes/raw stencils through explicit opaque geometry into a NEW UV image; preserve inputs and verify pixels/appearance. |
| `image.paint_version` | Paint bounded UV-image strokes with optional raw RGBA-channel mask/inversion/resampling into a new version; preserve both inputs, FILE reads need external-file consent. |
| `image.recovery_job_preview` | Preview exact 4K original-ID recovery fingerprint, loaded-vs-packed mode and consumer scope; private channel validation follows in the job. |
| `image.recovery_preview` | Preview exact unloaded FILE image identity, packed replacement and complete bounded consumers; <=1M pixels. |
| `image.remove` | Remove one explicitly confirmed unused image datablock, never its source file. |
| `image.restore_packed_snapshot` | Confirm current preview and reconstruct an unloaded original FILE Image ID by replacing packed bytes; <=1M pixels. |
| `image.restore_pixels` | Restore a retained raw snapshot to its exact loaded float/byte original image ID, preserving consumers; <=1M pixels. |
| `image.restore_snapshot_job_start` | Accept current-fingerprint cooperative 4K snapshot recovery; unloaded FILE reconstruction additionally confirms packed replacement. |
| `image.snapshot_job_start` | Accept an owner-bound cooperative CURRENT_PIXELS raw snapshot, up to 4096 x 4096; native capture/commit block, poll completion. |
| `material.assign` | Assign a material to an exact object slot or append it. |
| `material.copy_for_object` | Copy a material for one object slot without changing shared mesh data. |
| `material.create` | Create a named material with optional nodes and viewport color. |
| `material.delete` | Delete one exact material, refusing active users unless forced. |
| `material.inspect` | Inspect material users, important nodes, textures, and Principled values. |
| `material.set_principled` | Set validated common Principled BSDF inputs. |
| `material.slot_add` | Append a material slot to one exact object. |
| `material.slot_remove` | Remove one exact object material slot. |
| `material.unassign` | Clear one exact object material slot without deleting it. |

</details>

<details>
<summary>mesh — 31 tools</summary>

| Tool | What it does |
| --- | --- |
| `color_attribute.create` | Create a distinct FLOAT_COLOR POINT/CORNER attribute with verified full initialization. |
| `color_attribute.inspect` | Inspect paginated FLOAT_COLOR entries and a complete raw color digest. |
| `color_attribute.paint` | Paint linear RGBA MIX on explicit vertex-associated POINT/CORNER entries. |
| `color_attribute.remove` | Remove a color attribute only with data-loss and named-consumer acknowledgment plus deletion permission. |
| `color_attribute.rename` | Rename a color attribute with explicit named-consumer acknowledgment; consumers are not rewritten. |
| `mesh.analyze` | Inspect bounded base-mesh topology, adjacent winding and triangle crossing/contact candidates with explicit completeness. |
| `mesh.bevel_selected` | Bevel selected mesh elements with explicit width and segments. |
| `mesh.bridge_chains` | Bridge an exact equal open-chain preview with quads and no vertex merge, preserving original supported custom data. |
| `mesh.bridge_chains_preview` | Preview two equal open chains with explicit endpoint correspondence and a bounded preservation fingerprint. |
| `mesh.bridge_loops` | Bridge two referenced closed boundary/wire loops without vertex merging; unequal loops produce triangles. |
| `mesh.create` | Create a fully prevalidated arbitrary mesh object from bounded topology arrays. |
| `mesh.delete_selected` | Delete selected mesh elements. |
| `mesh.dissolve_selected` | Dissolve selected mesh elements. |
| `mesh.edge_ring_inspect` | Preview paginated measured edges and expected topology for a complete connected quad ring. |
| `mesh.edge_slide` | Apply fingerprinted selected-chain edge slides on explicit neighboring rails. |
| `mesh.extrude_selected` | Extrude the selected mesh region by an explicit offset. |
| `mesh.fill_holes` | Cap complete disjoint boundary loops with bounded n-gons; new face UVs start at zero. |
| `mesh.inset_selected` | Inset selected faces with explicit thickness and depth. |
| `mesh.inspect` | Inspect compact mesh and topology statistics. |
| `mesh.loop_cut` | Cut the entire connected quad ring with evenly spaced cuts, including unselected faces. |
| `mesh.mark_seams` | Mark or clear UV seams on selected edges of one local single-user Edit Mode mesh. |
| `mesh.merge_by_distance` | Weld only selected vertices within an explicit local-space distance. |
| `mesh.project_to_surface` | Apply an exact current bounded base-surface projection preview, preserving supported custom data. |
| `mesh.recalculate_normals` | Recalculate normals for the selected mesh region. |
| `mesh.sculpt_brush` | Apply explicit-mask base-mesh PUSH/SMOOTH strokes with protected topology/UV/material evidence. |
| `mesh.sculpt_mask_sample` | Sample a generated UV image into explicit sculpt-mask weights without changing mesh or image data. |
| `mesh.set_face_attributes` | Set smooth shading and/or an existing material-slot index on bounded referenced faces; material changes additionally require EDIT_MATERIALS. |
| `mesh.slide_preview` | Preview bounded selected vertex/edge slides along explicit topology rails. |
| `mesh.subdivide_selected` | Subdivide selected edges without smoothing under a conservative growth budget. |
| `mesh.surface_projection_preview` | Preview fresh selected vertices fitted to explicit base reference polygons with measured correspondence. |
| `mesh.vertex_slide` | Apply fingerprinted vertex slides on explicit neighboring rails, preserving topology and UVs. |

</details>

<details>
<summary>modifiers — 5 tools</summary>

| Tool | What it does |
| --- | --- |
| `modifier.add` | Add and configure an allowlisted object modifier. |
| `modifier.apply` | Apply one modifier in a validated Object Mode context. |
| `modifier.inspect` | Inspect bounded allowlisted modifier state for an explicit object. |
| `modifier.remove` | Remove one explicitly named modifier. |
| `modifier.set` | Set direct allowlisted RNA properties on one modifier. |

</details>

<details>
<summary>nodes — 20 tools</summary>

| Tool | What it does |
| --- | --- |
| `nodes.add` | Add a validated shader node to one material graph. |
| `nodes.inspect` | Inspect a complete bounded material shader graph. |
| `nodes.inspect_properties` | Inspect one shader node's reviewed settings, native enum choices and color ramp with bounded native samples. |
| `nodes.link` | Link exact material-node output and input sockets. |
| `nodes.refresh_image` | Refresh/relocate an image-node binding using a new approved FILE image version while retaining the old image/buffer. |
| `nodes.remove` | Remove one exact shader node and its incident links. |
| `nodes.rename` | Rename one exact shader node without collisions. |
| `nodes.set_color_ramp` | Replace a shader color ramp with 1-32 ordered scene-linear RGBA stops and reviewed interpolation settings. |
| `nodes.set_image` | Bind/clear a loaded image and validated sampling settings on an exact root material image node; FILE sources require external-file policy checks. |
| `nodes.set_input` | Set one exact material-node input default value. |
| `nodes.set_properties` | Set reviewed native shader-node scalar/enum properties, preserving links/socket defaults with measured failure recovery. |
| `nodes.unlink` | Remove links between exact material-node sockets. |
| `shader_group.bind` | Bind/clear an exact unlinked group instance after dependency and file-policy checks. |
| `shader_group.copy_for_node` | Copy one shader-group instance, preserving input defaults and links; nested data remains shared. |
| `shader_group.create` | Create a new empty local shader group with input/output nodes. |
| `shader_group.inspect` | Inspect a bounded shader-group graph, interface and transitive parent ownership evidence. |
| `shader_group.interface_add` | Add one typed interface socket to an explicitly scoped shader group. |
| `shader_group.interface_edit` | Apply one exact shader interface preview with complete bounded graph/owner CAS and guarded compensation. |
| `shader_group.interface_preview` | Preview one bounded shader interface rename/reorder/default plan with exact full-scope fingerprint. |
| `shader_group.remove` | Remove a confirmed unused shader-group datablock without forced unlink or deleting nested data. |

</details>

<details>
<summary>objects — 11 tools</summary>

| Tool | What it does |
| --- | --- |
| `object.create` | Create a structured Blender object primitive. |
| `object.delete` | Delete one object when destructive permission is granted. |
| `object.duplicate` | Duplicate an object, optionally with linked data. |
| `object.move_to_collection` | Move or additionally link an object to a collection. |
| `object.rename` | Rename an object deterministically. |
| `object.set_parent` | Set or clear an object's parent. |
| `transform.apply` | Apply selected transform components to object data. |
| `transform.rotate` | Apply a deterministic Euler rotation delta in radians. |
| `transform.scale` | Apply a deterministic multiplicative scale. |
| `transform.set` | Set absolute location, rotation, or scale values. |
| `transform.translate` | Apply a deterministic translation delta. |

</details>

<details>
<summary>python — 1 tools</summary>

| Tool | What it does |
| --- | --- |
| `python.execute` | Run acknowledged Blender Python as a super-permission last resort. |

</details>

<details>
<summary>render — 3 tools</summary>

| Tool | What it does |
| --- | --- |
| `render.configure` | Configure engine, resolution, samples, image settings, and approved output path. |
| `render.execute` | Render an explicit scene to a managed or approved local file and replace Render Result. |
| `render.inspect` | Inspect an explicit scene's bounded render configuration. |

</details>

<details>
<summary>rigging — 18 tools</summary>

| Tool | What it does |
| --- | --- |
| `rig.bind_mesh` | Bind a mesh using empty groups or contextual automatic weights; requires mesh-edit permission for weights/groups. |
| `rig.bone_add` | Add one explicit edit bone to a named armature. |
| `rig.bone_remove` | Remove one explicit bone with optional child reparenting. |
| `rig.bone_update` | Update explicit edit-bone geometry, hierarchy, name, or deform flags. |
| `rig.constraint_add` | Add a supported named pose-bone constraint. |
| `rig.constraint_remove` | Remove one named pose-bone constraint. |
| `rig.create` | Create an armature object with one explicit root bone. |
| `rig.deformation_inspect` | Measure current-frame evaluated pose/skin, deform weights, edge strain and stored IK limits; no quality verdict. |
| `rig.driver_add` | Add a non-scripted pose-bone driver from reviewed numeric controls or transforms. |
| `rig.driver_inspect` | Inspect a driver on an exact pose-bone transform component. |
| `rig.driver_remove` | Remove one exact reviewed pose-bone transform driver. |
| `rig.ik_configure` | Create/configure explicit two-bone IK with independent Empty controls and enumerated skin scope. |
| `rig.ik_inspect` | Inspect one exact stored pose-bone IK constraint; no evaluated-quality verdict. |
| `rig.ik_remove` | Confirm removal of one exact scoped IK constraint; native checkpoint recovery remains explicit. |
| `rig.inspect` | Inspect a bounded armature hierarchy, pose transforms, and constraints. |
| `rig.pose_transform` | Set finite pose-bone transform channels explicitly. |
| `rig.property_inspect` | Inspect one exact numeric object or pose-bone control property. |
| `rig.property_set` | Create or set an explicit bounded numeric rig control with dependency review. |

</details>

<details>
<summary>scene_edit — 11 tools</summary>

| Tool | What it does |
| --- | --- |
| `camera.configure` | Configure camera optics, clipping, depth of field, and active-scene assignment. |
| `collection.create` | Create and link a collection under an explicit scene or parent. |
| `collection.delete` | Remove an explicitly confirmed empty collection within the current Scene. |
| `collection.rename` | Rename an explicit collection without collisions. |
| `light.configure` | Configure a named Blender light's energy, color, and supported settings within its current subtype. |
| `scene.configure` | Configure an explicit scene's camera, units, and gravity. |
| `scene.variant.apply` | Apply an exact fresh preview with live consent, ownership and protected-state CAS checks. |
| `scene.variant.capture` | Store exact current camera/light controls and protected static scene proof as Scene JSON without saving. |
| `scene.variant.inspect` | Inspect bounded inert Scene cinematic records and exact library CAS. |
| `scene.variant.preview` | Render matched current/candidate images and restore owned settings; issue a fresh session-bound apply token. |
| `world.configure` | Create, assign, and configure a scene world and Background node. |

</details>

<details>
<summary>simulation — 9 tools</summary>

| Tool | What it does |
| --- | --- |
| `rigid_body.cache` | Execute an exact whole-world memory cache proposal; BAKE verifies every matrix/frame and all operations measure context recovery. |
| `rigid_body.cache_preview` | Preview a bounded memory-only world operation and session/context fingerprint; requires static reviewed Main dependencies including unused IDs. |
| `rigid_body.evaluate_job_start` | Accept an exact preview for cooperative whole-world evaluation; poll jobs.inspect for completion and retained partial effects. |
| `rigid_body.evaluate_preview` | Preview a bounded whole-world evaluation job, proposed range and exact session/context fingerprint; no bake claim. |
| `rigid_body.inspect` | Inspect the exact current Scene's bounded whole-world rigid bodies, constraints and cache ownership. |
| `simulation.cache` | Bake/free one in-memory cloth cache, at most 32 frames and 2000 vertices; excluded from batches. |
| `simulation.cloth_add` | Add cloth to a local single-user mesh with a bounded empty modifier stack. |
| `simulation.configure` | Configure reviewed cloth and pin-group settings before baking. |
| `simulation.inspect` | Inspect one cloth modifier and its point-cache state. |

</details>

<details>
<summary>uv — 16 tools</summary>

| Tool | What it does |
| --- | --- |
| `uv.align` | Align explicit UV corners to an exact U/V coordinate while preserving pins and face orientation. |
| `uv.analyze` | Measure bounded triangulated UV overlap/winding, pixel anisotropy and world-unit texel density, with explicit completeness. |
| `uv.capture_layout` | Capture a bounded UV-coordinate PNG without scene/UI/render changes; not a quality verdict. |
| `uv.coordinates_set` | Set explicit face-corner UVs within a validated face reference. Bounded standalone local Edit Mode admission and exact before/after checks; inspect reported partial state after failure. |
| `uv.inspect` | Inspect bounded UV layers, selection, bounds, and island connectivity. |
| `uv.layer_activate` | Activate an Object Mode UV layer and optionally make it the render/clone layer. |
| `uv.layer_create` | Create a zero UV layer or copy UVs/pins in Object Mode; copy per-layer selection where available, otherwise preserve mesh-global selection. |
| `uv.layer_remove` | Remove an Object Mode UV layer only with explicit data-loss confirmation. |
| `uv.layer_rename` | Rename an Object Mode UV layer; named consumers are not rewritten. |
| `uv.pack_islands` | Pack selected UV islands using bounded margin settings. |
| `uv.pin` | Pin or unpin scoped UV corners while preserving coordinates. Bounded standalone local Edit Mode admission and exact before/after checks; inspect reported partial state after failure. |
| `uv.relax` | Relax one complete explicit UV island with fixed boundaries/pins and bounded displacement. |
| `uv.smart_project` | Smart-project selected faces using bounded projection settings. |
| `uv.stitch` | Copy explicit same-vertex UV corner correspondences to fixed anchors without welding mesh topology. |
| `uv.transform` | Scale scoped UVs about a pivot, rotate, then offset; respect pins by default. Bounded standalone local Edit Mode admission and exact before/after checks; inspect partial failures. |
| `uv.unwrap` | Unwrap selected faces with explicit method and margin. |

</details>

<details>
<summary>weights — 9 tools</summary>

| Tool | What it does |
| --- | --- |
| `weights.assign` | Assign a weight or remove memberships on up to 1000 explicit vertices; rollback on failure. |
| `weights.brush_stroke` | Apply 1-32 explicit bounded spherical weight dabs to named vertices/group, preserving other memberships; no auto normalization. |
| `weights.group_create` | Create an explicitly named vertex group on a local single-user mesh. |
| `weights.inspect` | Inspect paginated vertex weights and locked groups in Object Mode. |
| `weights.mirror_geometric` | Reflect explicit source vertices across an explicit LOCAL/WORLD plane; require unique one-to-one bounded correspondence and exact group mapping. |
| `weights.normalize` | Normalize named unlocked groups while preserving all unmentioned weights. |
| `weights.smooth` | Smooth one unlocked group across mesh edges on explicit vertices; fixed outside boundary and no implicit normalization. |
| `weights.transfer` | Copy one group through explicit source/target vertex pairs, snapshotting before writes; no geometric correspondence guesses. |
| `weights.transfer_surface` | Transfer explicit mapped groups through closest base-mesh triangles and barycentric weights, rejecting distant/ambiguous correspondence. |

</details>

<!-- END GENERATED MCP TOOLS -->

## Upgrading

Replace the add-on and MCP server together from the same release, then restart Blender and
Codex. Check both versions and begin with inspection. See the
[upgrade and rollback guide](docs/installation.md#upgrading).
Downgrading packages does not undo scene edits.

## Common problems

For connection, missing tool and permission errors, start with
[troubleshooting](docs/troubleshooting.md). For a reproducible bug or feature request, see
[Support](SUPPORT.md). Report security issues through [SECURITY.md](SECURITY.md).

## Development

Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks and safe native fixtures.
[Architecture](docs/architecture.md), [tool design](docs/tool-design.md) and the
[protocol](docs/protocol.md) explain the implementation. Development packages are test builds;
passing CI or smoke tests alone does not accept a 1.0 release.

Licensed under [GPL-3.0-or-later](LICENSE).
