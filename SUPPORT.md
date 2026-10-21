# Support

Start with [installation and upgrades](docs/installation.md) and
[troubleshooting](docs/troubleshooting.md). Confirm that the add-on and MCP server come from
the same release or source checkout, the listener is started in Blender, and `bridge.status`
succeeds. Toolset enablement and Blender permission grants are separate controls.

The published 0.3.0 alpha has 108 tools. The development branch contains unreleased work
and still uses 0.3.0 version metadata; see [development status](docs/development-status.md).
A tool described on `main` may be absent from a released package.

## Ask for help or report a bug

Search [GitHub Issues](https://github.com/Yoruiopz/Codex-Blender-Bridge/issues) before opening
a new issue. Use the bug template for installation, connection or behavior problems, and
the feature template for an unsupported workflow. Describe what you were trying to do in
Blender and include:

- Release asset names or the full source commit and whether local changes are present;
  how the add-on, MCP server and optional plugin were installed.
- OS/version, Blender version/build, standalone Python version, MCP SDK version and Codex client.
- The exact tool, small redacted arguments, returned error code/context and request ID if available.
- Minimal reproduction steps using a disposable scene, expected result and observed result.
- Relevant bounded logs or captures, what changed, and whether the project was saved or recovery
  was attempted. If a call timed out, inspect the scene before retrying it.

Use `python -m pip show blender-codex-bridge mcp` in the environment registered with Codex
to identify server dependencies. Check the add-on with `bridge.status`; do not assume that
matching 0.3.0 labels prove a development build matches a published package.

Do not attach credentials, proprietary `.blend` files, full scene dumps or personal paths.
Prefer a small synthetic reproduction and review logs/screenshots before sharing.
For a possible vulnerability, follow [SECURITY.md](SECURITY.md) instead of posting details.

## Know the limits

This is alpha software. Unsupported domains, modes, shared/linked data and safety budgets
may return explicit refusals. Do not enable arbitrary Python or broaden permissions to work
around a structured permission denial. Keep the listener local, preserve project backups and
reinspect partial failures. [Release readiness](docs/release-1.0-readiness.md) tracks open
qualification and workflow gaps; 1.0 is not ready.
