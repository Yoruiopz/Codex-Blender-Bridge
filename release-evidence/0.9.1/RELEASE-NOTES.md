# Blender Codex Bridge 0.9.1 — alpha

A reliability patch for the existing 270-tool bridge. This prerelease strengthens cancellation and permission revocation around lifecycle changes, canonical executor/job-context checks, and compatibility with optional request context. Five unqualified GLB staging tools remain excluded from public discovery and dispatch.

Source: `4c1c66ad4d134ed042a3da55deca931def3c898a`.
CI: https://github.com/Yoruiopz/Codex-Blender-Bridge/actions/runs/41223967621

## Verified scope

- All seven exact-commit CI jobs passed. Each Python 3.10–3.12 × MCP SDK 2.0.0/2.2.0 cell passed 15,026 tests with three Windows-only skips; Ruff, mypy, inventory and package checks passed.
- Official Linux Blender 4.5.14 (`62c1db4208e8`) and 5.2.2 (`d13f752e3b9c`): selected source regressions and four exact-package installed static flows passed. Installed MCP used Python 3.12.14 with both SDK versions on both Blender builds.
- Both Blender builds passed fresh installation, clean-directory replacement of 0.9.0, upgrade/rollback, paths with spaces and listener restart/reconnect component checks. These are same-process component checks; preference migration and a persisted-process upgrade are unqualified.
- Complete package members match Git; wheel RECORD, versions and checksums passed. The source bundle restores all 807 files. Four original synthetic PNGs were reviewed and retained.

The installed success scenario uses one owned, untextured Cube: create → transform → inspect → isolated geometry PNG → locally authorized Native Save Copy New → product fresh-process reader verifies the same geometry and transform. Blender-side consent is required; the external AI client cannot grant it.

Download the matching add-on ZIP, MCP wheel and optional Codex plugin ZIP below. Check SHA256SUMS.txt before installation. The evidence archive records source/package identities, test summaries, twelve qualification-only harness sources, four reviewed synthetic geometry PNGs and the public candidate source bundle. It contains no user projects, preferences, recovery backups or raw environment dumps.

## Limits and next work

This is an alpha, not stable 1.0. Windows compatibility/testing is deferred and unverified. Native qualification covers the declared Linux cases on official Blender 4.5.14 and 5.2.2 only; the entire native fixture inventory and complete artist workflows are not qualified.

Geometry previews show neutral shape, not original materials, lighting or protected viewport appearance. The installed scenario is a success flow in a disposable clean project; it does not certify ordinary production-project admission or end-to-end failure recovery. Component permission, interruption and preservation evidence is reported separately.

Existing finite native-save limits remain. Edited/generated/4K texture saving, durable paired recovery, protected capture, broader animation/simulation and complete GLB/FBX delivery still need implementation and qualification. Do not clear projects or downsize artwork to force admission. The original full artist-workflow target, all 29 implementation items and all 14 stable release gates remain open. Prior releases remain available.
