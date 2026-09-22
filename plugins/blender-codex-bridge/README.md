# Blender Codex Bridge plugin

This optional plugin packages MCP launch configuration and a verification-first Blender
workflow skill for Codex. Install the standalone MCP server separately.

## Prerequisites

1. Download the matching MCP wheel from [0.3.0 Releases](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.3.0).
   Install it in an environment whose `blender-codex-mcp` executable is on the PATH visible to Codex:

   ```powershell
   python -m pip install ./blender_codex_bridge-0.3.0-py3-none-any.whl
   ```

2. Install the matching `blender_codex_bridge-0.3.0.zip` in Blender and enable it. Use the add-on, MCP server and plugin from the same release.
3. Open **3D Viewport → Sidebar → Codex Bridge**, choose the permissions you want, and start the local bridge.
4. Install or enable this plugin in Codex. Its MCP launch configuration connects only to `127.0.0.1:9876`.

Restart Codex/start a new task after upgrading. Use plugin registration **or** manual MCP
registration, not both. For an isolated virtual environment without changing PATH, use
the [manual installation guide](https://github.com/Yoruiopz/Codex-Blender-Bridge/blob/v0.3.0/README.md#install--no-source-build-needed)
instead. The repository is currently private, so downloads require repository access.

Run `scripts/doctor.py` with Python for a read-only check of the command installation and Blender listener.

Python execution is disabled by default and remains a last-resort, explicitly acknowledged super-permission. Every call requires `EXECUTE_PYTHON`, `DELETE_OBJECTS`, `ACCESS_EXTERNAL_FILES`, and `SAVE_PROJECT` together. Once armed, raw `bpy` bypasses narrower structured edit gates; its guardrails reduce accidents but are not a security sandbox. A started script that fails is tracked as a possible mutation with verification evidence and a finalized undo step.

Python stdout is capped at 64 KiB. Result conversion separately allows 4,000 global items, depth 8, 4,000 integer digits, no cyclic/shared container expansion, and 256 KiB serialized; violating a graph/scalar/byte budget or hitting a conversion failure replaces the value with explicit `__truncated__` metadata marked by `result_truncated` and `result_limit_bytes`, preserving audit/recovery output.
