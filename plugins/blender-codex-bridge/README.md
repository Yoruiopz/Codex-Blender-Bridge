# Blender Codex Bridge plugin

This optional plugin packages MCP launch configuration and a verification-first Blender
workflow skill for Codex. Install the standalone MCP server separately.

These instructions target matching **0.9.1 alpha** add-on, MCP server and plugin
artifacts. Install them only after the
[0.9.1 release page](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.9.1)
publishes the accepted commit, package checksums and qualification evidence.
Before that record exists, 0.9.1 remains a candidate. Matching source versions or
a candidate ZIP alone do not establish acceptance. Previous
[0.9.0 artifacts and evidence](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.9.0)
remain available separately; use all components from the same release.
Windows compatibility and testing remain deferred and unverified. The Windows
command below is setup guidance, not Windows qualification. The full artist
workflow and stable 1.0 requirements remain unfinished.

## Prerequisites

1. Once accepted and published, download the matching MCP wheel from
   [0.9.1 Releases](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.9.1)
   and verify it against that release's `SHA256SUMS.txt`.
   Install it in an environment whose `blender-codex-mcp` executable is on the PATH visible to Codex:

   ```powershell
   python -m pip install ./blender_codex_bridge-0.9.1-py3-none-any.whl
   ```

2. Install the matching `blender_codex_bridge-0.9.1.zip` in Blender and enable it.
   Verify its checksum and use the add-on, MCP server and plugin from the same release.
3. Open **3D Viewport → Sidebar → Codex Bridge**, choose the permissions you want, and start the local bridge.
4. Verify and extract `blender-codex-bridge-plugin-0.9.1.zip`, then install or enable
   its plugin directory in Codex. Its MCP launch configuration connects only to `127.0.0.1:9876`.

Restart Codex/start a new task after upgrading. Use plugin registration **or** manual MCP
registration, not both. For an isolated virtual environment without changing PATH, use
the [manual installation guide](https://github.com/Yoruiopz/Codex-Blender-Bridge/blob/v0.9.1/docs/installation.md)
instead.

Run `scripts/doctor.py` with Python for a read-only check of the command installation and Blender listener.

Python execution is disabled by default and remains a last-resort, explicitly acknowledged super-permission. Every call requires `EXECUTE_PYTHON`, `DELETE_OBJECTS`, `ACCESS_EXTERNAL_FILES`, and `SAVE_PROJECT` together. Once armed, raw `bpy` bypasses narrower structured edit gates; its guardrails reduce accidents but are not a security sandbox. A started script that fails is tracked as a possible mutation with verification evidence and a finalized undo step.

Python stdout is capped at 64 KiB. Result conversion separately allows 4,000 global items, depth 8, 4,000 integer digits, no cyclic/shared container expansion, and 256 KiB serialized; violating a graph/scalar/byte budget or hitting a conversion failure replaces the value with explicit `__truncated__` metadata marked by `result_truncated` and `result_limit_bytes`, preserving audit/recovery output.
