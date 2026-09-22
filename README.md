# Blender Codex Bridge

Let Codex inspect and edit your Blender scene through local, permission-controlled tools.
Model objects, edit materials and shader nodes, unwrap UVs, work with rigs and animation,
configure lights and cameras, and render—with status and controls inside Blender.

**[Download 0.3.0](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.3.0)** ·
[Upgrade instructions](#upgrading) · [Troubleshooting](docs/troubleshooting.md)

This is **alpha software**. Start with a copy of an unimportant scene.
The repository is currently private; downloads require a GitHub account with repository access.
**0.3.0** adds faster structured scene workflows and Geometry Nodes editing.
See [release notes](docs/releases/0.3.0.md) and [workflow examples](docs/agent-workflows.md).

## Install — no source build needed

You need Blender **4.2+**, standalone **Python 3.10+**, and a local Codex client with MCP support.
Blender's bundled Python is not the Python used for the MCP server.
Recent integration checks use Blender 4.5.1 and 5.1.2; other versions are not exhaustively tested.

### 1. Download the packages

Open the [0.3.0 release](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.3.0)
and expand **Assets**:

| Download | Purpose |
| --- | --- |
| `blender_codex_bridge-0.3.0.zip` | Required Blender add-on; do not extract it |
| `blender_codex_bridge-0.3.0-py3-none-any.whl` | Required MCP server; install with pip below |
| `blender-codex-bridge-plugin-0.3.0.zip` | Optional Codex plugin and Blender Studio guidance |
| `SHA256SUMS.txt` | Checksums for verifying downloads |

GitHub's automatic **Source code** archives are for development, not Blender installation.

### 2. Install in Blender

1. Open **Edit → Preferences → Add-ons → Install from Disk…** (in the top-right menu).
2. Select the add-on ZIP, then enable **Blender Codex Bridge**.
3. In a **3D Viewport**, press **N** and open **Codex Bridge**.
4. Review permissions and click **Start Bridge**. Keep `127.0.0.1:9876`.

Leave Blender open. Never expose or tunnel this port to another computer.

### 3. Connect Codex

On **Windows**, with the wheel in Downloads, run PowerShell:

```powershell
$bridgeHome = Join-Path $env:LOCALAPPDATA 'BlenderCodexBridge'
py -3 -m venv "$bridgeHome\.venv"
& "$bridgeHome\.venv\Scripts\python.exe" -m pip install "$env:USERPROFILE\Downloads\blender_codex_bridge-0.3.0-py3-none-any.whl"
codex mcp add blender_codex_bridge -- "$bridgeHome\.venv\Scripts\blender-codex-mcp.exe"
codex mcp list
```

Adjust the wheel path if necessary. Pip installs dependencies, so this step needs internet.
The absolute executable path avoids PATH and virtual-environment activation issues.

On **macOS/Linux**:

```bash
python3 -m venv "$HOME/.local/share/blender-codex-bridge/.venv"
"$HOME/.local/share/blender-codex-bridge/.venv/bin/python" -m pip install "$HOME/Downloads/blender_codex_bridge-0.3.0-py3-none-any.whl"
codex mcp add blender_codex_bridge -- "$HOME/.local/share/blender-codex-bridge/.venv/bin/blender-codex-mcp"
```

If the CLI is unavailable, use your client's MCP settings: select **STDIO** and enter the
same absolute executable path as the command, with no arguments.
See [OpenAI's MCP setup documentation](https://developers.openai.com/codex/mcp/).
Restart the client if needed and **start a new Codex task** to discover the tools.

**Compatibility:** 0.3.0 is tested with MCP SDK 2.0.0 and 2.2.0; the old SDK pin is no
longer needed. If deliberately installing historical 0.2.0, follow its
[release-specific instructions](docs/releases/0.2.0.md), including `mcp==2.0.0`.

The optional plugin is an alternative, not a requirement: extract its ZIP and install
the contained plugin directory using your client's local-plugin workflow. It needs
`blender-codex-mcp` on the PATH visible to Codex. **Use plugin registration or manual
MCP registration, not both.** Manual registration above works with an isolated virtual environment.

### 4. Try it

Start with:

> Check Blender bridge status, summarize my scene, and inspect my selection. Do not change anything.

Then try:

> Create a cube named BridgeTest. Inspect it afterward and show me a preview. Do not save the project.

Codex can enable a needed toolset. Only **you** can grant a disabled Blender permission
in the panel; the MCP server cannot grant itself permission.

## How it works

**Codex → MCP server → local Blender add-on → Blender main thread.**

The add-on validates requests, checks permissions, and executes registered operations.
It returns measured scene state so Codex can inspect the result instead of assuming success.

The sidebar includes connection status, current task, toolsets, permissions, history,
**Pause**, **Emergency Stop**, and recovery controls. Stop controls prevent new edits;
an already-running Blender operation may need to finish. Inspect before retrying.

The workflow is **inspect → checkpoint → edit → inspect again → preview when useful**.
Checkpoints use Blender's global undo stack: they are not saved backups and can include
interleaved manual work. Keep normal backups and save only when intended.

0.3.0 provides **108 MCP tools** across modeling, materials/shader nodes, UVs, modifiers,
constraints, animation, rigging, scene settings, rendering, and inspection. It does not cover
every Blender editor or operator. Python is a dangerous last resort, disabled by default,
requiring Python, deletion, external-file, and save permissions together. It is **not a sandbox**.

The Blender connection stays on your machine, but scene summaries/images returned to Codex
are provided to the AI client. Local transport does not mean local-only model processing.

## Features

**0.3.0** contains all 88 tools from 0.2.0 plus 20 new tools (108 total).
Rows marked **New in 0.3.0** are not available in older downloads.
Optional domain toolsets start disabled;
enabling a toolset does not grant Blender permissions.

| Area | Supported workflows | Availability |
| --- | --- | --- |
| Inspection and evidence | Project and scene summaries, object state, active object/selection, mesh statistics, viewport previews | 0.2.0+ |
| Objects and transforms | Create primitives, duplicate, rename, delete, parent, organize in collections; set/apply transforms | 0.2.0+ |
| Mesh modeling | Create arbitrary meshes from bounded topology arrays; inspect, extrude, inset, bevel, dissolve, delete selected components, recalculate normals | 0.2.0+ |
| Materials | Create/inspect/delete materials, manage slots and assignments, configure Principled shader inputs | 0.2.0+ |
| Shader nodes | Inspect material node trees; add/remove/rename nodes, set inputs, connect/disconnect sockets | 0.2.0+ |
| UVs | Inspect UVs, unwrap, smart-project, pack islands | 0.2.0+ |
| Modifiers and constraints | Inspect, add, configure and remove supported types; apply modifiers | 0.2.0+ |
| Rigging | Create armatures, add/update/remove bones, pose transforms, bone constraints, mesh binding | 0.2.0+ |
| Animation | Inspect animation, set frame/range, insert/delete keyframes | 0.2.0+ |
| Scene and look development | Scene settings, collections, cameras, lights and world configuration | 0.2.0+ |
| Rendering | Inspect/configure settings, execute renders; permission-controlled external output | 0.2.0+ |
| Recovery and controls | Task/status display, permissions, toolset controls, history, logical undo checkpoints, pause/emergency stop, explicit project save | 0.2.0+ |
| Python execution | Explicitly armed, broad `bpy` access for unsupported workflows; bounded returned evidence and diagnostic output | 0.2.0+; disabled by default |
| Context and selection | Set object selection and active object; enter supported object/mesh/armature modes; inspect/select vertex, edge or face indices with fresh selection evidence | **New in 0.3.0** |
| Search and bulk layout | Filter scene objects; transform up to 128 objects; align/distribute independent objects along measured world-space origins | **New in 0.3.0** |
| Geometry Nodes | Create/inspect graphs, add interface sockets and reviewed node types, configure properties/inputs, link/unlink/remove nodes, attach as modifiers | **New in 0.3.0** |
| Efficient batches | Plan and execute 1–32 ordered structured steps with permission checks, bounded results, per-step history and partial-failure evidence | **New in 0.3.0** |

### Faster agent workflows in 0.3.0

Use filtered scene queries and compact component inspection to find precise targets, then
bulk tools or short batches to reduce MCP round trips. Blender execution stays serial on
the main thread. A batch plan checks method availability and permissions; it is **not** a
simulation or full argument validation. Batches stop at the first failure and do **not**
automatically roll back completed edits. Cancellation is checked between steps, not inside
an active Blender operation. Reinspect before retrying a partial or timed-out operation.

Geometry Nodes uses a reviewed node allowlist and explicit acknowledgement for shared
graphs. Bulk alignment/distribution uses object origins, not surface spacing, and rejects
dependent objects it cannot safely handle. See [workflow limits and examples](docs/agent-workflows.md).

Try this with matching 0.3.0 packages:

> Find the independent objects named Prop_*. Inspect them, plan an even distribution along
> X, preserve their materials and off-axis positions, then verify the result. Do not save.

### Scope and limitations

This is broad Blender access, **not a claim that every Blender action has a structured tool**.
Tools support their declared schemas and reviewed types, not every property in Blender.
Mode switching does not implement sculpt or paint strokes. Dedicated compositor editing,
simulation/baking workflows, advanced weight painting, drivers/NLA editing, and Geometry
Nodes simulation/repeat zones are not currently covered by structured tools. Context-sensitive
operations can require a particular mode and selection. Unsupported requests must fail
explicitly rather than pretend to succeed.

Python can reach beyond structured tools only when all four permissions are enabled:
`EXECUTE_PYTHON`, `DELETE_OBJECTS`, `ACCESS_EXTERNAL_FILES`, and `SAVE_PROJECT`.
Once armed, raw `bpy` can bypass narrower editing gates; its import policy is an accident
guard, **not a security sandbox**. Keep it disabled for normal workflows.

### Complete tool inventory — 0.3.0

Expand a domain for every registered MCP tool. This inventory is generated from the code
and checked in CI; the feature table above identifies which domains are new.
Blender's local recovery UI also has an add-on-only restore action, not an extra MCP tool.

<!-- BEGIN GENERATED MCP TOOLS -->
Current registry: **108 MCP tools**.

<details>
<summary>core — 16 tools</summary>

| Tool | What it does |
| --- | --- |
| `bridge.status` | Report Blender bridge, project, mode, and permission status. |
| `bridge.task.clear` | Clear the current high-level task from Blender's UI. |
| `bridge.task.set` | Show the current high-level Codex task in Blender's UI. |
| `checkpoint.create` | Create a logical agent undo checkpoint. |
| `checkpoint.list` | List recent agent checkpoints and operation history. |
| `checkpoint.undo_last` | Use Blender global undo only with explicit acknowledgement of user-interleaving risk. |
| `object.inspect` | Inspect one object without dumping raw vertex coordinates. |
| `project.info` | Inspect project metadata and render settings. |
| `project.save` | Save the current project when Blender-side permission allows it. |
| `scene.inspect` | Return a compact authoritative structural scene representation. |
| `scene.summary` | Return an LLM-oriented structural and textual scene summary. |
| `selection.inspect` | Inspect active and selected objects or mesh elements. |
| `toolsets.disable` | Disable a local MCP domain toolset. |
| `toolsets.enable` | Enable a lazy local MCP domain toolset. |
| `toolsets.list` | List local MCP toolsets and their enablement state. |
| `viewport.capture` | Capture a viewport image; temporary settings are restored but Render Result is replaced. |

</details>

<details>
<summary>animation — 5 tools</summary>

| Tool | What it does |
| --- | --- |
| `animation.inspect` | Inspect one object's bounded action, F-curves, keyframes, slots, and drivers. |
| `animation.keyframe_delete` | Delete a keyframe from an explicit object RNA data path. |
| `animation.keyframe_insert` | Insert a keyframe on an explicit object RNA data path. |
| `animation.set_frame` | Set the current scene frame and subframe explicitly. |
| `animation.set_range` | Set the scene playback and optional preview frame ranges. |

</details>

<details>
<summary>batch — 2 tools</summary>

| Tool | What it does |
| --- | --- |
| `batch.execute` | Run 1-32 structured steps serially; one logical undo marker, stop on error, no atomic rollback. |
| `batch.plan` | Preflight 1-32 structured steps for shape and static permissions, not scene state or handler arguments. |

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
<summary>geometry_nodes — 10 tools</summary>

| Tool | What it does |
| --- | --- |
| `geometry_nodes.attach` | Attach an explicit geometry node group to an exact named object modifier. |
| `geometry_nodes.create` | Create a geometry node group with geometry IO and optional passthrough. |
| `geometry_nodes.inspect` | Inspect a bounded geometry graph, interface, and direct users. |
| `geometry_nodes.interface_add` | Add a typed interface socket to an explicit geometry node group. |
| `geometry_nodes.link` | Link exact compatible geometry-node sockets without graph cycles. |
| `geometry_nodes.node_add` | Add a compatible geometry node with validated settings. |
| `geometry_nodes.node_remove` | Remove an exact geometry node and its incident links. |
| `geometry_nodes.node_set_input` | Set an exact geometry node input's scalar or vector default. |
| `geometry_nodes.node_set_properties` | Configure allowlisted direct scalar/enum properties of a geometry node. |
| `geometry_nodes.unlink` | Remove links between exact geometry-node sockets. |

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
<summary>materials — 8 tools</summary>

| Tool | What it does |
| --- | --- |
| `material.assign` | Assign a material to an exact object slot or append it. |
| `material.create` | Create a named material with optional nodes and viewport color. |
| `material.delete` | Delete one exact material, refusing active users unless forced. |
| `material.inspect` | Inspect material users, important nodes, textures, and Principled values. |
| `material.set_principled` | Set validated common Principled BSDF inputs. |
| `material.slot_add` | Append a material slot to one exact object. |
| `material.slot_remove` | Remove one exact object material slot. |
| `material.unassign` | Clear one exact object material slot without deleting it. |

</details>

<details>
<summary>mesh — 8 tools</summary>

| Tool | What it does |
| --- | --- |
| `mesh.bevel_selected` | Bevel selected mesh elements with explicit width and segments. |
| `mesh.create` | Create a fully prevalidated arbitrary mesh object from bounded topology arrays. |
| `mesh.delete_selected` | Delete selected mesh elements. |
| `mesh.dissolve_selected` | Dissolve selected mesh elements. |
| `mesh.extrude_selected` | Extrude the selected mesh region by an explicit offset. |
| `mesh.inset_selected` | Inset selected faces with explicit thickness and depth. |
| `mesh.inspect` | Inspect compact mesh and topology statistics. |
| `mesh.recalculate_normals` | Recalculate normals for the selected mesh region. |

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
<summary>nodes — 7 tools</summary>

| Tool | What it does |
| --- | --- |
| `nodes.add` | Add a validated shader node to one material graph. |
| `nodes.inspect` | Inspect a complete bounded material shader graph. |
| `nodes.link` | Link exact material-node output and input sockets. |
| `nodes.remove` | Remove one exact shader node and its incident links. |
| `nodes.rename` | Rename one exact shader node without collisions. |
| `nodes.set_input` | Set one exact material-node input default value. |
| `nodes.unlink` | Remove links between exact material-node sockets. |

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
<summary>rigging — 9 tools</summary>

| Tool | What it does |
| --- | --- |
| `rig.bind_mesh` | Bind a mesh using empty groups or contextual automatic weights. |
| `rig.bone_add` | Add one explicit edit bone to a named armature. |
| `rig.bone_remove` | Remove one explicit bone with optional child reparenting. |
| `rig.bone_update` | Update explicit edit-bone geometry, hierarchy, name, or deform flags. |
| `rig.constraint_add` | Add a supported named pose-bone constraint. |
| `rig.constraint_remove` | Remove one named pose-bone constraint. |
| `rig.create` | Create an armature object with one explicit root bone. |
| `rig.inspect` | Inspect a bounded armature hierarchy, pose transforms, and constraints. |
| `rig.pose_transform` | Set finite pose-bone transform channels explicitly. |

</details>

<details>
<summary>scene_edit — 7 tools</summary>

| Tool | What it does |
| --- | --- |
| `camera.configure` | Configure camera optics, clipping, depth of field, and active-scene assignment. |
| `collection.create` | Create and link a collection under an explicit scene or parent. |
| `collection.delete` | Remove an explicitly confirmed collection and report unlinked contents. |
| `collection.rename` | Rename an explicit collection without collisions. |
| `light.configure` | Configure a named Blender light's type, energy, color, and shape settings. |
| `scene.configure` | Configure an explicit scene's camera, units, and gravity. |
| `world.configure` | Create, assign, and configure a scene world and Background node. |

</details>

<details>
<summary>uv — 4 tools</summary>

| Tool | What it does |
| --- | --- |
| `uv.inspect` | Inspect bounded UV layers, selection, bounds, and island connectivity. |
| `uv.pack_islands` | Pack selected UV islands using bounded margin settings. |
| `uv.smart_project` | Smart-project selected faces using bounded projection settings. |
| `uv.unwrap` | Unwrap selected faces with explicit method and margin. |

</details>

<!-- END GENERATED MCP TOOLS -->

## Upgrading

Upgrade the **Blender add-on and MCP server together**, from the same release.
For 0.1.0 or 0.2.0 → 0.3.0:

1. Save and back up your scene. Stop the bridge and finish active tool calls.
2. Download the new ZIP and matching wheel from [Releases](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases).
3. Disable/remove the old add-on, install the new ZIP, and restart Blender to unload old modules.
4. Upgrade the **same virtual environment** registered with Codex:

   ```powershell
   & "$env:LOCALAPPDATA\BlenderCodexBridge\.venv\Scripts\python.exe" -m pip install --upgrade "$env:USERPROFILE\Downloads\blender_codex_bridge-0.3.0-py3-none-any.whl"
   ```

   Remove any old `mcp==2.0.0` constraint from your install command or requirements file;
   keeping SDK 2.0.0 installed also works. Do not mix a 0.3.0 server with
   the 0.2.0 add-on. If using an editable source install, update that
   environment or re-register the new executable path; do not accidentally update another Python.

5. Update the optional plugin if you use it. Restart Codex/start a new task.
6. Start the bridge, review permissions, and ask for `bridge.status` to check the add-on version.
   Run `python -m pip show blender-codex-bridge` in the registered environment to check the MCP version.
7. Begin with inspection. Old selection IDs and undo checkpoints do not carry across sessions.

No bridge scene-file migration is required. Updating does not intentionally rewrite your
`.blend`. To roll back, reinstall **both** older packages and restart both sides; restore a
project backup if needed. Downgrading software does not undo scene edits.

## Common problems

- **Connection refused:** open Blender, enable the add-on, and press **Start Bridge**.
- **Toolset disabled:** enable the domain needed; toolsets and permissions are separate.
- **Permission denied:** review the named Blender switch. Do not enable Python to bypass it.
- **Executable not found:** register an absolute path from the environment containing the wheel.
- **Old/duplicate tools:** remove duplicate registration and start a new task after upgrading.
- **Download 404:** sign in with repository access while the repository is private; also check that the requested release has actually been published.

More: [troubleshooting](docs/troubleshooting.md), [security](docs/security.md),
[tool contracts](docs/tool-design.md), [release notes](docs/releases/0.3.0.md).

## Development

Source builds are for contributors and unreleased features—not required for installation:

```powershell
git clone https://github.com/Yoruiopz/Codex-Blender-Bridge.git
cd Codex-Blender-Bridge
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check addon mcp_server scripts tests
.\.venv\Scripts\python.exe -m mypy mcp_server
.\.venv\Scripts\python.exe scripts/build_release.py
```

The release builder produces the add-on ZIP, MCP wheel, plugin ZIP, and checksums in
`dist/release`. Read [AGENTS.md](AGENTS.md) and [protocol](docs/protocol.md) before changes.
After changing registered tools, run `python scripts/readme_tools.py` to refresh the inventory.
CI checks inventory consistency and builds downloadable development packages; these artifacts
are test builds, not published releases. Tagged release assets remain the recommended install.
Run isolated `scripts/blender_*_smoke.py` checks with Blender's
`--background --factory-startup --python-exit-code 1 --python` flags.

Licensed under [GPL-3.0-or-later](LICENSE).
