# Artist workflow development checkpoint — 2026-10-22

**Development evidence; full artist-workflow 1.0 remains NOT_READY.** The
fourteen release requirements remain open. Published 0.3.0 remains alpha, with
108 tools; these results concern newer development source and packages.

## Frozen first increment

Commit `4f8e3c1d27fe54d1029c9bc622aaa0ccc108b394` adds bounded mesh slides and
UV refinement, explicit-mask sculpt and vertex-color brushes, weight brushes,
geometric mirroring and surface transfer, numeric rig controls and bone drivers,
and stronger object/layout ownership and measured recovery. Its registry contains
218 MCP tools. The complete 191-file Python source inventory has SHA-256
`1b7af7921a37a06d9a4dedd9fb90d16282a2c76416212f72d33bd2419142fbd4`.

Both complete Python 3.12 suites passed **2,366 tests**, with three Windows-only
skips each, on MCP SDK 2.0.0 and 2.2.0. Ruff, mypy, compilation, generated inventory,
dependency and whitespace checks passed. All **45/45** registered native fixtures
passed from a clean checkout on Linux Blender **4.3.2**, including UI cases and
fresh-process workflows. The complete Linux **4.5.14 LTS** selection also passed
45/45 at that source. Neither establishes Windows or installed artist acceptance.

Retained evidence is under `build/artist-continuation-20261022/`:

- `native-final/report.json`: complete 4.3.2 run and per-case logs/bundles.
- `native-lts-stable/report.json`: separate 4.5.14/5.2.2 results; inspect individual
  outcomes rather than assuming the whole report passes. The 5.2.2 selection
  completed 42/45: Geometry Nodes modifier storage and fresh driver defaults
  exposed compatibility defects; 4K delivery refused its memory preflight.
  Fixes and reruns belong to a subsequent source increment.
- `python-sdk20-final.xml` and `python-sdk22-final.xml`: complete suite results.
- `package-verification/distribution-manifest.json`: exact package and source hashes.
- `package-verification/installed-wheel-evidence.json`: actual isolated stdio discovery
  outside the checkout, exactly 218 tools, core-only defaults and disabled-domain errors.
- `development-visual-review.json`: hashed reviewed development captures; no artistic
  acceptance claim.

The add-on ZIP, wheel and plugin match the same committed source. Archive CRCs,
checksums and all packaged add-on/MCP/plugin source members were verified. These
development artifacts retain 0.3.0 metadata and **must never replace the published
0.3.0 assets**. Native source fixtures are distinct from installed add-on/plugin tests.

The earlier `native-baseline-all/report.json` failed one 4K delivery fixture and
remains separate evidence. The fixture's Linux memory probe and CPU denoiser setup
were corrected before the complete final 4.3.2 run. No old pass count was combined
with a focused rerun to fabricate a complete passing matrix.

## Public repository preparation

Commit `cd11e98a72c71a7006bec7a8a4cc0aa7d0fc2ec6` adds the concise README,
installation/development guides, contribution/support/security guidance, issue forms
and PR template. It changes no Python source from the frozen increment. All six
Python 3.10–3.12 × MCP SDK 2.0.0/2.2.0 CI jobs and the package job passed in
Actions run `39685379435`. [PR #1](https://github.com/Yoruiopz/Codex-Blender-Bridge/pull/1)
merged as `e2037426cb13202728d37ab4a4cd5abc298a8838`.

The user changed repository visibility to Public. Anonymous requests verified the
repository and merged README/contribution/security documents. Anonymous downloads
of all six 0.2.0/0.3.0 packages matched their published checksums and ZIP CRCs.
Existing releases were retained without replacement. These checks verify public
distribution access, not fresh installation or workflow correctness.

Evidence under `build/public-facing-20261022/` includes all seven downloaded CI
job logs, `ci/jobs.json`, `anonymous-access.json` and
`anonymous-release-downloads/verification.json`. The prepublication bounded pattern
scan inspected 891 reachable blobs and found no matching credential patterns or
suspicious tracked credential/private-key paths; it is not a security certification.
Existing user guidance edits remain preserved separately from committed changes.

## Subsequent bounded increment

The next development increment adds eleven typed tools: base-reference projection
preview/apply, orthographic surface painting and its cooperative job, IK inspection/
configuration/removal, current-frame deformation inspection, and Geometry Nodes
zone inspection/conversion/interface editing. Their complete bounds are documented in
[surface projection](mesh-surface-projection.md), [surface painting](image-surface-paint.md),
[IK/deformation](rig-ik-deformation.md) and [zone lifecycle](geometry-zone-lifecycle.md).
The combined registry contains 229 MCP tools.

Native 5.2 compatibility work uses its actual typed Geometry Nodes modifier inputs,
normalizes only reviewed identity keys on freshly allocated driver curves, and preserves
actual mesh-global UV face/corner/sync selection. A separate native pack test proves the
UV operator consumes the scoped flags while unselected islands remain unchanged.
New-image publication refuses metadata/pixel writes after another consumer acquires
the output. Existing cloth caches gain live scope/permission gates and measured recovery;
the rigid-body timing defect was not reproduced in cloth and no cloth time normalization
was added.

The [cache research](simulation-cache-research.md) records rigid-body stale/fractional-time
behavior, native disk-setup crashes, fluid deletion scope and version-dependent FREE
completion. It adds no public rigid-body/fluid bake tool. Focused native results are
development evidence; complete clean-source matrix and package results must identify
their own commit and hashes. They cannot be combined with the first increment's matrix.

Development CI now retains packages and per-matrix JUnit artifacts for 90 days. Accepted
release evidence still needs the separately retained and hashed immutable evidence bundle.

## Remaining gates

Use the [execution plan](plan-1.0.md), [readiness gates](release-1.0-readiness.md)
and [requirement ledger](release-1.0-ledger.json). These foundations do not complete
the broader modeling, UV/material, surface/sculpt/paint, character/NLA, procedural/
simulation, cinematic, artist-interaction or production-delivery requirements.

Windows 11 hardware is unavailable. Exact Windows Blender 4.5 LTS/stable 5.x
matrices, installed scenarios A–F, upgrade/rollback, constrained-memory/mixed-editor
recovery and reviewed appearance acceptance remain mandatory. No component version,
1.0 tag or 1.0 release has been created. Linux checks do not change the qualified
platform target or silently waive any requirement.
