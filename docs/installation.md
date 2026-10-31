# Installation and upgrades

These instructions target **0.9.1 alpha**. Install it only after the published
[0.9.1 release acceptance record](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.9.1)
identifies the accepted commit, package hashes and retained evidence. Until that
record is published, 0.9.1 remains a candidate. The previous
[0.9.0 release](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.9.0)
remains available with its own separate evidence. Use a disposable scene or project
copy for initial checks.

The manifest declares Blender **4.2+**; use the exact builds identified in the
chosen release's acceptance record. You also need standalone **Python 3.10+** and
a local Codex client with MCP support.
Blender's bundled Python is not the Python used for the MCP server.
Historical 0.3.0 release checks used Blender 4.5.1 and 5.1.2; this is not current-source or
1.0 qualification. Other versions and platforms are not exhaustively tested.

## 1. Download the packages

After its acceptance record is published, open the
[0.9.1 release](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.9.1)
and expand **Assets**:

| Download | Purpose |
| --- | --- |
| `blender_codex_bridge-0.9.1.zip` | Required Blender add-on; do not extract it |
| `blender_codex_bridge-0.9.1-py3-none-any.whl` | Required MCP server; install with pip below |
| `blender-codex-bridge-plugin-0.9.1.zip` | Optional Codex plugin and Blender Studio guidance |
| `SHA256SUMS.txt` | Checksums for verifying downloads |

GitHub's automatic **Source code** archives are for development, not Blender installation.
Verify all three installers against `SHA256SUMS.txt` before installing them. The
separate development-evidence archive uses `EVIDENCE-SHA256SUMS.txt`.

## 2. Install in Blender

1. Open **Edit → Preferences → Add-ons → Install from Disk…** (in the top-right menu).
2. Select the add-on ZIP, then enable **Blender Codex Bridge**.
3. In a **3D Viewport**, press **N** and open **Codex Bridge**.
4. Review permissions and click **Start Bridge**. Keep `127.0.0.1:9876`.

Leave Blender open. Never expose or tunnel this port to another computer.

### Historical 0.6.0 installation evidence

The historical published 0.6.0 alpha was released on 2026-10-25 at 14:29:56 UTC
from `73cad805903fcd0be9175b49a5ecf78505ecd4a5`. Its exact ZIP passed fresh candidate installation,
previous-package replacement, upgrade and rollback separately with published
0.3.0 and 0.5.0 on Linux Blender 4.5.14 and 5.2.2. Four fresh background processes
each ran four phases, for sixteen installed observations. Eight candidate previews
executed installed start/inspect/image methods with default external-file denial
followed by explicit local consent, verified package bytes and worker paths with
spaces. Workers were reaped. Each route remained in one fresh process; process
restart and preference migration are not established. Its matching wheel passed a
fresh MCP SDK 2.2.0 stdio session with 268 tools, 240 SDK receipts and 210 malformed
standard-JSON cases. Third-party dependencies were reused through explicit
read-only links; the bridge installation and session were new. Exact-commit CI
covered Python 3.10–3.12 and SDK 2.0.0/2.2.0. All six release assets were downloaded
and hashed anonymously; see [the release evidence](releases/0.6.0.md#verified-evidence).
Historical [0.5.0 evidence](releases/0.5.0.md#verified-evidence) remains specific
to that source. These historical results do not qualify 0.9.1. They are bounded alpha checks,
not complete artist-workflow or stable 1.0 acceptance. Windows compatibility and
testing remain deferred and unverified; the commands below are setup guidance.
macOS is also unqualified.

The older published 0.3.0 ZIP has a discovery metadata issue on these two Linux
builds. Reinstalling that same ZIP does not fix its missing literal version.
The matching 0.4.0, 0.5.0 and 0.6.0 packages contain the correction. Earlier releases remain
available for deliberate rollback.

## 3. Connect Codex

On **Windows**, with the wheel in Downloads, run PowerShell:

```powershell
$bridgeHome = Join-Path $env:LOCALAPPDATA 'BlenderCodexBridge'
py -3 -m venv "$bridgeHome\.venv"
& "$bridgeHome\.venv\Scripts\python.exe" -m pip install "$env:USERPROFILE\Downloads\blender_codex_bridge-0.9.1-py3-none-any.whl"
codex mcp add blender_codex_bridge -- "$bridgeHome\.venv\Scripts\blender-codex-mcp.exe"
codex mcp list
```

Adjust the wheel path if necessary. Pip installs dependencies, so this step needs internet.
The absolute executable path avoids PATH and virtual-environment activation issues.

On **macOS/Linux**:

```bash
python3 -m venv "$HOME/.local/share/blender-codex-bridge/.venv"
"$HOME/.local/share/blender-codex-bridge/.venv/bin/python" -m pip install "$HOME/Downloads/blender_codex_bridge-0.9.1-py3-none-any.whl"
codex mcp add blender_codex_bridge -- "$HOME/.local/share/blender-codex-bridge/.venv/bin/blender-codex-mcp"
```

If the CLI is unavailable, use your client's MCP settings: select **STDIO** and enter the
same absolute executable path as the command, with no arguments.
See [OpenAI's MCP setup documentation](https://developers.openai.com/codex/mcp/).
Restart the client if needed and **start a new Codex task** to discover the tools.

**Compatibility gate:** before 0.9.1 acceptance, its exact release commit must pass
the Python 3.10–3.12 and MCP SDK 2.0.0/2.2.0 CI matrix. Consult the published
acceptance record for the results; these instructions do not establish that gate.
The historical 0.6.0 SDK checks above remain separate. If deliberately installing
historical 0.2.0, follow its
[release-specific instructions](releases/0.2.0.md), including `mcp==2.0.0`.

The optional plugin is an alternative, not a requirement: extract its ZIP and install
the contained plugin directory using your client's local-plugin workflow. It needs
`blender-codex-mcp` on the PATH visible to Codex. **Use plugin registration or manual
MCP registration, not both.** Manual registration above works with an isolated virtual environment.

## 4. Try it

Start with:

> Check Blender bridge status, summarize my scene, and inspect my selection. Do not change anything.

Then try:

> Create a cube named BridgeTest. Inspect it afterward and show me a preview. Do not save the project.

Codex can enable a needed toolset. Only **you** can grant a disabled Blender permission
in the panel; the MCP server cannot grant itself permission.

## Verify downloads

Compare the downloaded files with the release's `SHA256SUMS.txt` before installing.
On Windows, run `Get-FileHash -Algorithm SHA256 <downloaded-file>` in PowerShell and compare
the displayed digest with the matching filename. On Linux use
`sha256sum --check SHA256SUMS.txt` from the directory containing all three assets;
on macOS use `shasum -a 256 -c SHA256SUMS.txt`.
Checksums detect mismatched/corrupt files; they do not independently authenticate a release.

## Upgrading

Upgrade the **Blender add-on and MCP server together**, from the same release.
For 0.9.0 or earlier → matching 0.9.1 packages, after 0.9.1 acceptance is published:

1. Save and back up your scene using Blender’s own UI. Legacy `project.save` remains
   quarantined. The typed native-save workflow has bounded project scope and requires
   explicit local consent; its presence does not establish release acceptance or
   replace your backup. Stop the bridge and finish active tool calls.
2. Download the accepted ZIP and matching wheel from the
   [0.9.1 release](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.9.1)
   and verify their hashes against its acceptance record.
3. Disable/remove the old add-on, install the new ZIP, and restart Blender to unload old modules.
4. Upgrade the **same virtual environment** registered with Codex:

   ```powershell
   & "$env:LOCALAPPDATA\BlenderCodexBridge\.venv\Scripts\python.exe" -m pip install --upgrade "$env:USERPROFILE\Downloads\blender_codex_bridge-0.9.1-py3-none-any.whl"
   ```

   Remove any old `mcp==2.0.0` constraint from your install command or requirements file;
   use the SDK versions identified in the chosen release's evidence. Do not mix a 0.9.1 server with
   an older add-on. If using an editable source install, update that
   environment or re-register the new executable path; do not accidentally update another Python.

5. Update the optional plugin if you use it. Restart Codex/start a new task.
6. Start the bridge, review permissions, and ask for `bridge.status` to check the add-on version.
   Run `python -m pip show blender-codex-bridge` in the registered environment to check the MCP version.
7. Begin with inspection. Old selection IDs and undo checkpoints do not carry across sessions.

No bridge scene-file migration is required. Updating does not intentionally rewrite your
`.blend`. To roll back, reinstall **both** older packages and restart both sides; restore a
project backup if needed. Downgrading software does not undo scene edits.

Use a clean add-on directory for replacement: Blender's overwrite installer can retain obsolete
files. The historical 0.6.0 installed probe covered its own bounded replacement,
enablement, preview and upgrade/rollback routes. It does not qualify 0.9.1 installation,
restart, preference migration or reconnect. Check the 0.9.1 acceptance record for
which routes were verified against its exact package hashes. Windows compatibility
and testing remain deferred and unverified; macOS remains unqualified.


[Back to README](../README.md) · [Troubleshooting](troubleshooting.md)
