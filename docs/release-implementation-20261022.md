# Release implementation checkpoint — 2026-10-22

Status: **development checkpoint; full 1.0 is NOT_READY**. No version bump, tag,
publication, workflow dispatch or repository visibility change was performed.

## Source identity

- Implementation: `844d771c53b988a76b673ac41a6654617dc47b72`.
- Final tested code, including the native artist fixture correction:
  `90997f5b88586d61fdb0773c8c5d647bf3936cb4`.
- Clean-checkout Python inventory: **175 files**, SHA-256
  `f166f896bfaa3f4712e60629870d8ec1c4624823f3349d159b2ff86f12622f97`.
- Subsequent documentation-only updates do not change that Python inventory.

Existing user edits to AGENTS.md, README's Blender-selection guidance and the
Blender Studio skill were preserved unstaged. The handoff's missing Windows
increment was reimplemented; its historical test results were not reused as
verification of this source.

## Completed development verification

| Check | Observed result |
| --- | --- |
| Full non-Blender suite, MCP SDK 2.0.0 | 2,056 passed; three Windows-only skips |
| Full non-Blender suite, MCP SDK 2.2.0 | 2,056 passed; three Windows-only skips |
| Ruff, mypy, compilation, generated inventory, dependency/diff checks | Passed; 40 standalone files typed; 198 registered MCP tools |
| Clean-checkout Linux Blender 4.3.2 native selection | **21/21 passed**; 21 of 41 registered cases, not the full matrix |
| Fresh writer/reader processes | Texture reopen, packed pixels, task plans and asset delivery passed |
| Texture save/reopen | Eight small format/role variants plus complete 4K raw DATA digest; 67,108,864 large-image channels |
| Matched camera comparison | Eight complete 32px RGBA8 pairs; zero changed pixels; not artistic acceptance |
| Independent host file checks | Nine exported textures and the saved project matched their complete hashes |
| Development packages | Add-on ZIP, MCP wheel and plugin ZIP built from the clean tested commit; checksums and packaged source bytes matched |
| Installed wheel outside checkout | CLI help and real stdio discovery passed; 198 tools; core-only default enablement |

Evidence lives under `build/release-implementation-20261022/`:

- `native-final/report.json` and its per-case/per-phase logs and owned bundles.
- `distribution-manifest.json`, complete source map and development asset hashes.
- `validation-summary.json`, `installed-wheel-evidence.json`, Python JUnit reports.
- `packages-final/`, development-only 0.3.0 artifacts; **never replace the published
  0.3.0 release with these files**.

The earlier `native/report.json` is **20/21 failed-matrix evidence**, not a pass.
Its artist fixture assumed layered Action slots and an available Cycles denoiser.
The corrected fixture retains motion, preservation and red compositor assertions,
and the entire selected-case matrix was rerun at the final tested code commit.
Do not add historical counts to the final run or treat source smokes as installed
add-on/plugin acceptance.

## Remaining release work

All fourteen acceptance entries in [the release ledger](release-1.0-ledger.json)
remain open. This checkpoint adds stored-source resolution, ownership guards,
broader structural evidence, bounded packed pixel recovery, Action/curve authoring,
nested GN inputs, advisory artist plans and scoped material-free GLB/FBX delivery.
It does not complete the full artist-workflow requirements.

Mandatory work still includes broader modeling/retopology, sculpt/surface/vertex/
weight painting, rig/driver/NLA workflows, simulation/cache/bake jobs, production
materials and import/export, complete artist interaction, constrained-memory and
mixed-editor recovery, and exact packaged installation/upgrade/rollback acceptance.
The new APIs' bounds and unsupported cases are part of their documentation.

The user confirmed no Windows 11 test machine is available. Qualification on
Blender 4.5 LTS and stable 5.x, UI/private-desktop checks and installed scenarios
A–F cannot be inferred from Linux source verification. Run and retain those
checks before freezing 1.0 support claims. The qualification checker currently
fails closed; the manual publication workflow was not dispatched.
