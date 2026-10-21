# Security reporting

Blender Codex Bridge controls a powerful local application and can expose scene content or
modify project data within granted permissions. Read the [security model](docs/security.md)
for deployment, data handling, arbitrary Python and recovery limits.

## Report a vulnerability privately

Use **Security → Report a vulnerability** on
[this repository](https://github.com/Yoruiopz/Codex-Blender-Bridge/security) if private
vulnerability reporting is available. If it is unavailable, open a minimal
[issue](https://github.com/Yoruiopz/Codex-Blender-Bridge/issues) asking for a private contact.
Do not include exploitation steps, sensitive `.blend` files, tokens or private paths in
that public request.

In a private report, provide the affected release or exact source commit, Blender/OS/Python
versions, required permissions and setup, impact, and a small synthetic reproduction.
Distinguish the published alpha from development builds that still report 0.3.0 metadata.
Do not test against someone else's session or data.

The project has no declared long-term support or backport policy. Include reports concerning
the latest published alpha or current development source; older-version reports should state
whether the behavior also occurs there. Ordinary bugs and usage questions belong in
[Support](SUPPORT.md).
