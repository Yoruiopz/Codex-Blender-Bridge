# Blender Codex Bridge

Let Codex inspect and edit your Blender scene through local, permission-controlled tools.
Model objects, edit materials and shader nodes, unwrap UVs, work with rigs and animation,
configure lights and cameras, and render—with status and controls inside Blender.

**[Download 0.2.0](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.2.0)** ·
[Upgrade instructions](#upgrading) · [Troubleshooting](docs/troubleshooting.md)

This is **alpha software**. Start with a copy of an unimportant scene.
The repository is private; downloads require a GitHub account with access.
The published download is 0.2.0. The main branch also contains **unreleased 0.3.0 development**;
see [what is changing](docs/agent-workflows.md). Release downloads do not include unreleased tools.

## Install — no source build needed

You need Blender **4.2+**, standalone **Python 3.10+**, and a local Codex client with MCP support.
Blender's bundled Python is not the Python used for the MCP server.
Recent integration checks use Blender 4.5.1 and 5.1.2; other versions are not exhaustively tested.

### 1. Download the packages

Open the [0.2.0 release](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.2.0)
and expand **Assets**:

| Download | Purpose |
| --- | --- |
| `blender_codex_bridge-0.2.0.zip` | Required Blender add-on; do not extract it |
| `blender_codex_bridge-0.2.0-py3-none-any.whl` | Required MCP server; install with pip below |
| `blender-codex-bridge-plugin-0.2.0.zip` | Optional Codex plugin and Blender Studio guidance |
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
& "$bridgeHome\.venv\Scripts\python.exe" -m pip install "$env:USERPROFILE\Downloads\blender_codex_bridge-0.2.0-py3-none-any.whl"
codex mcp add blender_codex_bridge -- "$bridgeHome\.venv\Scripts\blender-codex-mcp.exe"
codex mcp list
```

Adjust the wheel path if necessary. Pip installs dependencies, so this step needs internet.
The absolute executable path avoids PATH and virtual-environment activation issues.

On **macOS/Linux**:

```bash
python3 -m venv "$HOME/.local/share/blender-codex-bridge/.venv"
"$HOME/.local/share/blender-codex-bridge/.venv/bin/python" -m pip install "$HOME/Downloads/blender_codex_bridge-0.2.0-py3-none-any.whl"
codex mcp add blender_codex_bridge -- "$HOME/.local/share/blender-codex-bridge/.venv/bin/blender-codex-mcp"
```

If the CLI is unavailable, use your client's MCP settings: select **STDIO** and enter the
same absolute executable path as the command, with no arguments.
See [OpenAI's MCP setup documentation](https://developers.openai.com/codex/mcp/).
Restart the client if needed and **start a new Codex task** to discover the tools.

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

0.2.0 provides **88 MCP tools** across modeling, materials/shader nodes, UVs, modifiers,
constraints, animation, rigging, scene settings, rendering, and inspection. It does not cover
every Blender editor or operator. Python is a dangerous last resort, disabled by default,
requiring Python, deletion, external-file, and save permissions together. It is **not a sandbox**.

The Blender connection stays on your machine, but scene summaries/images returned to Codex
are provided to the AI client. Local transport does not mean local-only model processing.

## Upgrading

Upgrade the **Blender add-on and MCP server together**, from the same release.
For 0.1.0 → 0.2.0, or later published updates:

1. Save and back up your scene. Stop the bridge and finish active tool calls.
2. Download the new ZIP and matching wheel from [Releases](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases).
3. Disable/remove the old add-on, install the new ZIP, and restart Blender to unload old modules.
4. Upgrade the **same virtual environment** registered with Codex:

   ```powershell
   & "$env:LOCALAPPDATA\BlenderCodexBridge\.venv\Scripts\python.exe" -m pip install --upgrade "$env:USERPROFILE\Downloads\blender_codex_bridge-0.2.0-py3-none-any.whl"
   ```

   Change the filename for future releases. If using an editable source install, update that
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
- **Download 404:** sign in to GitHub with an account that has access to this private repository.

More: [troubleshooting](docs/troubleshooting.md), [security](docs/security.md),
[tool contracts](docs/tool-design.md), [release notes](docs/releases/0.2.0.md).

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
Run isolated `scripts/blender_*_smoke.py` checks with Blender's
`--background --factory-startup --python-exit-code 1 --python` flags.

Licensed under [GPL-3.0-or-later](LICENSE).
