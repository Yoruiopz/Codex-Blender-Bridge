# Blender Codex Bridge plugin

This plugin packages the bridge's MCP server with a verification-first Blender workflow skill for Codex.

## Prerequisites

1. Install the repository's Python package so `blender-codex-mcp` is on `PATH`:

   ```powershell
   py -m pip install -e .
   ```

2. Install the matching Blender add-on ZIP and enable it. Published 0.2.0 packages are on [Releases](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.2.0); this source plugin is for unreleased 0.3.0 development and must be paired with that source build.
3. Open **3D Viewport → Sidebar → Codex Bridge**, choose the permissions you want, and start the local bridge.
4. Install or enable this plugin in Codex. Its bundled MCP server connects only to `127.0.0.1:9876`.

Run `scripts/doctor.py` with Python for a read-only check of the command installation and Blender listener.

Python execution is disabled by default and remains a last-resort, explicitly acknowledged super-permission. Every call requires `EXECUTE_PYTHON`, `DELETE_OBJECTS`, `ACCESS_EXTERNAL_FILES`, and `SAVE_PROJECT` together. Once armed, raw `bpy` bypasses narrower structured edit gates; its guardrails reduce accidents but are not a security sandbox. A started script that fails is tracked as a possible mutation with verification evidence and a finalized undo step.

Python stdout is capped at 64 KiB. Result conversion separately allows 4,000 global items, depth 8, 4,000 integer digits, no cyclic/shared container expansion, and 256 KiB serialized; violating a graph/scalar/byte budget or hitting a conversion failure replaces the value with explicit `__truncated__` metadata marked by `result_truncated` and `result_limit_bytes`, preserving audit/recovery output.
