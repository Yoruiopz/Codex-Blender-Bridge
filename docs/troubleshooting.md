# Troubleshooting

Start with the shortest end-to-end check:

1. Blender is open with the correct `.blend`.
2. The add-on is enabled and its panel says the bridge is listening on `127.0.0.1` at the expected port.
3. Codex is launching the MCP server from the intended virtual environment and repository directory.
4. `codex mcp list` or `/mcp` shows `blender_codex_bridge`.
5. A read-only `bridge.status` call succeeds.

Do not enable write permissions to diagnose a connection problem.

## The add-on ZIP does not install

Build the supported archive from the repository root:

```powershell
python .\scripts\build_addon.py
```

Install `dist/blender_codex_bridge-0.2.0.zip`. Inspecting the ZIP should show:

```text
blender_codex_bridge/__init__.py
```

If it instead starts with `addon/` or a repository directory, Blender cannot discover the add-on correctly. Do not zip the entire repository.

If Blender reports a Python exception, open **Window > Toggle System Console** on Windows or launch Blender from a terminal on macOS/Linux and capture the first traceback. Confirm Blender is 4.2 or newer. Disable/remove an older copy before reinstalling if Blender is loading duplicate modules.

## The Codex Bridge tab is missing

- Make sure the add-on is enabled in **Edit > Preferences > Add-ons**.
- Open a **3D Viewport**, press `N`, and look for **Codex Bridge**. The panel is not expected in every Blender editor.
- Check Blender's system console for registration errors.
- Disable and re-enable once after updating development files. Repeated registration errors usually indicate stale/duplicate installed copies; restart Blender and remove the duplicate.

## Start Bridge fails

The host must remain `127.0.0.1`. If the port is already in use:

```powershell
Get-NetTCPConnection -LocalPort 9876 -ErrorAction SilentlyContinue
```

Choose another unprivileged local port in the add-on and configure the MCP server to use the same value. Do not solve a bind failure by changing the host to `0.0.0.0`.

Security software can block local listeners. Permit Blender for loopback/local communication only; do not create an inbound LAN firewall rule.

## Codex does not show the MCP server

Confirm the standalone package starts from the exact environment:

```powershell
.\.venv\Scripts\blender-codex-mcp.exe
```

This command waits for MCP stdio input, so silence can be normal; terminate the manual probe afterward. A traceback indicates an install/import/configuration problem.

The equivalent module probe is `.\.venv\Scripts\python.exe -m mcp_server`. Connection defaults are `127.0.0.1:9876`, a 30-second request timeout, a 5-second connect timeout, and a 4 MiB frame limit. Override them with `--blender-host`, `--blender-port`, `--timeout`, `--connect-timeout`, and `--max-message-bytes`, or the corresponding `BLENDER_CODEX_BRIDGE_*` environment variables.

Check the registered entry:

```powershell
codex mcp list
```

For config-file setup, use an absolute executable path and `cwd`:

```toml
[mcp_servers.blender_codex_bridge]
command = "E:\\absolute\\path\\.venv\\Scripts\\blender-codex-mcp.exe"
cwd = "E:\\absolute\\path\\Codex-Blender-Bridge"
enabled = true
```

Restart the Codex client after editing `~/.codex/config.toml` or a trusted project's `.codex/config.toml`. See the official [Codex MCP documentation](https://developers.openai.com/codex/mcp/).

If you are using the repository plugin at `plugins/blender-codex-bridge`, remember that it does not embed Python or this package. Install the repository first so the environment that launches Codex can resolve the console script:

```powershell
Get-Command blender-codex-mcp
blender-codex-mcp --help
```

Then install/enable the local plugin. You can run its read-only `scripts/doctor.py` with the same Python environment to check the command and loopback listener.

## MCP starts but Blender is disconnected

- Start the bridge in Blender before the first tool call.
- Confirm host and port match exactly on both sides.
- Make sure another Blender instance is not listening on that port.
- `127.0.0.1` refers to the current machine/environment. A server running inside WSL, a container, VM, or remote Codex environment does not automatically share the Windows Blender loopback interface. V1 supports same-host local execution only.
- Stop/start the add-on listener, then restart the MCP server/Codex client.

Do not expose the port over LAN or a tunnel as a workaround.

## A tool is missing

Run `toolsets.list`. The running registry is authoritative.

- Core tools should be visible without a domain toolset.
- Every optional domain starts disabled. Current toolsets are `objects`, `mesh`, `materials`, `nodes`, `uv`, `modifiers`, `constraints`, `animation`, `rigging`, `scene_edit`, `render`, and `python`.
- A roadmap entry does not mean the tool is implemented.
- Restart Codex after upgrading the MCP package so it refreshes tool definitions.

If MCP exposes a tool that Blender returns `METHOD_NOT_FOUND` for, the add-on and server versions are mismatched. Install both from the same release/checkout.

## `PERMISSION_DENIED`

This means the Blender trust boundary is working. Read `error.context.missing_permissions`, review the request in the Blender panel, and enable only the narrow permission you intend to grant.

Enabling a toolset is not the same as granting permission. `EDIT_SCENE` and `EDIT_RENDER` are distinct from object/material/animation edits; deletion, arbitrary Python, external files, and saving are separate capabilities. Do not turn on all permissions to avoid a targeted denial.

## `python.execute` is missing or denied

Python is intentionally disabled by its toolset and a four-permission super-permission gate. Confirm the `python` toolset is enabled and all four Blender toggles are on: **Execute Blender Python (Dangerous)**, **Delete Objects**, **Access External Files**, and **Save Project**. Then include a non-empty `expected_effect` and `confirm_dangerous=true` in the call. `PERMISSION_DENIED` lists whichever of `EXECUTE_PYTHON`, `DELETE_OBJECTS`, `ACCESS_EXTERNAL_FILES`, and `SAVE_PROJECT` are still missing.

The requirement is intentionally broader than the stated script effect. Once armed, raw `bpy` bypasses normal structured `EDIT_MESH`, `EDIT_MATERIALS`, `EDIT_ANIMATION`, `EDIT_SCENE`, and `EDIT_RENDER` checks; it can also delete, use Blender file APIs, and save. Turning a narrower domain permission off does not sandbox Python.

Policy failures list the denied name/import or a safe limit. Imports are limited to `bpy`, `bmesh`, `mathutils`, and `math`; shell, process, network, filesystem, dynamic-code, and double-underscore introspection paths are rejected. The policy is an accident guard, not a hard security sandbox.

If a successful response has `result_truncated: true`, the script ran but its result exceeded at least one conversion budget—4,000 total items, depth 8, 4,000 integer digits, no cyclic/shared container references, or 256 KiB serialized—or conversion/size checking itself failed. The bridge stops bounded conversion, replaces the value with explicit `__truncated__` metadata (including a reason and maximums), reports `result_limit_bytes: 262144` and `result_bytes: null`, and still returns separate audit/recovery fields. Huge integers are rejected before expensive decimal stringification. Do not treat the placeholder as the requested result or rerun the same large/recursive graph automatically. Return a compact acyclic summary/page from the script or inspect affected Blender data with structured tools. Captured stdout has its own 64 KiB limit and uses `stdout_truncated` independently.

A `TIMEOUT` from this tool uses a cooperative Python trace deadline. Long Blender C operations cannot always be preempted. If execution started, runtime failure and timeout errors include the digest, expected effect, bounded stdout, coarse before/after counts and object deltas, `mutation_outcome_unknown: true`, and `verification_required: true`. The failed call is tracked as a possible mutation with a finalized Blender undo step. Inspect history and all potentially affected data before retrying or deciding whether to use confirmed global undo.

A successful call also returns `verification_required: true`. Run the relevant domain inspectors and visual checks, then disable the Python toolset and restore all four high-risk permissions to least privilege.

Do not weaken the policy or add shell/network tooling to work around a missing structured operation. Add a typed handler when the workflow is common.

## `AGENT_PAUSED` or `EMERGENCY_STOPPED`

Resume from the Blender panel after reviewing pending/current activity. Emergency stop may require an explicit reset and restart depending on add-on state. Reinspect bridge status and selection after recovery; do not blindly replay mutations that may have completed before the stop.

## `INVALID_MODE` or `INVALID_SELECTION`

Inspect current mode and selection. Mesh component tools commonly require:

- an active mesh object;
- Edit Mode where documented;
- the expected vertex/edge/face selection type;
- a non-empty, current selection or valid session selection ID.

Mode changes, topology edits, undo, file reload, scene switching, and reconnect can invalidate a selection handle. Reselect and call `selection.inspect` rather than reusing a stale ID.

## `OBJECT_NOT_FOUND`

Object names are case-sensitive and can change after duplication/rename. Run `scene.summary` or a filtered `scene.inspect`, then use an exact returned name/ID. Do not use fuzzy matches for mutation when several candidates exist.

## Viewport capture fails

Viewport capture requires a supported Blender UI context.

- Use an interactive Blender session for viewport views/shading. In `--background`, only `view="camera"` with `shading="rendered"` is supported, using the active scene camera.
- Keep at least one 3D Viewport available.
- Try `view="current"`, `shading="solid"`, overlays off, and a modest resolution first.
- Confirm `CAPTURE_VIEWPORT` is enabled.
- Camera view requires an active valid camera.
- Material/rendered view may need shader compilation and can exceed a short timeout.
- An isolated object name must resolve and be visible in the active view layer.

After a failure, verify the user's view, shading, overlays, selection, and visibility were restored. If not, report the exact failure and restore them manually; do not continue modifying the scene.

Every supported capture replaces Blender's session-level Render Result buffer. This is an explicit `CAPTURE_VIEWPORT` side effect; save a needed render before requesting a bridge capture.

## Render configuration or execution fails

- `render.inspect` requires `INSPECT_SCENE`.
- `render.configure` requires `EDIT_RENDER`.
- `render.execute` requires `EDIT_RENDER` and `CAPTURE_VIEWPORT` because it replaces Render Result.
- A user-provided output path additionally requires `ACCESS_EXTERNAL_FILES`; omit `filepath` to use a managed temporary output.
- Existing explicit files are not overwritten unless `overwrite=true`.
- Validate the scene has a usable camera and that the selected engine exists in the running Blender version.

After a timeout or failure, call `render.inspect` and verify Render Result/output state before repeating the render.

## Requests time out

A timeout includes queue wait and Blender execution. Common causes:

- Blender is busy, rendering, compiling shaders, or showing a modal dialog.
- A prior main-thread command is still running; execution is serial.
- Inspection/capture bounds are too large.
- The configured Codex `tool_timeout_sec` is too short for the supported operation.
- The MCP/add-on connection dropped.

First inspect Blender and local logs. Narrow the request or reduce capture resolution. Increase `tool_timeout_sec` only for an operation expected to be safe and finite.

A timeout does not prove an active mutation was rolled back. Check operation history and reinspect the current `.blend` before retrying.

Post-send timeout/disconnect failures are marked non-retryable with `outcome_unknown:true`; do not automatically repeat them. Only an explicit pre-send failure with `executed:false` is safe for an unchanged retry. Cancelling an MCP call closes that bridge connection so Blender can reject still-pending work; reconnect and reinspect before continuing.

## Undo did not produce the expected state

Bridge checkpoints rely on Blender's session undo behavior and logical operation history. They are not saved project snapshots.

- List checkpoints/history and confirm the latest agent operation.
- User edits and some Blender operations can change the undo stack.
- `checkpoint.undo_last` refuses calls unless `confirm_global_undo=true`; the Blender panel asks for confirmation. Confirmation acknowledges risk—it cannot prove that the top undo entry belongs only to the agent.
- File reload/restart loses session-only recovery state.
- A failed or timed-out mutation may require structural inspection before deciding whether undo applies.

Use normal versioned backups for important work. Test destructive operations on a copy.

## Project save is denied or unsafe

Saving requires `SAVE_PROJECT`. Saving to a new/external path may also require `ACCESS_EXTERNAL_FILES` and an explicit approved path. The bridge should not invent a destination or overwrite unexpectedly.

If the current file is unsaved, ask the user for a destination rather than guessing. Confirm the returned filepath and dirty state after saving.

## MCP protocol errors or garbled output

An MCP stdio server must reserve stdout for MCP protocol messages. Debug `print()` calls on stdout can corrupt the session. Send logs to stderr or the configured logger.

For Blender transport errors, each wire message is one UTF-8 JSON object followed by a newline and is limited to 4 MiB. Add-on and MCP-server versions must agree on the `1.0` envelope. See [`protocol.md`](protocol.md).

## Where to look for diagnostics

- Blender panel: connection/task/current tool/queue state, toolsets, permissions, bounded history, last error, checkpoint controls, and **Copy Diagnostics**.
- Blender system console or launch terminal: detailed add-on logs and tracebacks.
- Codex/MCP stderr: standalone server connection and protocol diagnostics.
- Automated tests: `python -m pytest` from the repository root.

Use request/operation IDs to correlate layers. `bridge.task.set` can show the high-level operation to the Blender user and `bridge.task.clear` should remove it after completion/abandonment. When reporting a bug, include OS, Blender version, Python version for the MCP environment, package/add-on/plugin version, exact tool and bounded arguments, public error code/context, and relevant log excerpt. Remove private project paths and scene content.
