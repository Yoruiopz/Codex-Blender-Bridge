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

### Frozen source and verification

This increment is commit `bf5c53ee7c027588762b4d5e6b59ac7c71526d16`: 212 Python source
files with inventory SHA-256
`62652ba7af435ff96cdddf20085cf1d99ccbf92bd25031e3066830f988a72453`.
The following commit `4c05657` changes only the oversized-socket regression test to
accept the platform's early closed-peer errors while still proving no request is submitted.
Both clean SDK suites passed **2,815 tests**, with three Windows-only skips each.
All six Python/SDK CI jobs and the package job passed in run `39690171441`.
[PR #2](https://github.com/Yoruiopz/Codex-Blender-Bridge/pull/2) merged as
`7bf15710fa90de293b040bfa55c46098ced7cfa5`.

All **53/53** registered native cases passed on Linux Blender **4.5.14 LTS** and
**5.2.2 LTS** at that identical clean source. The first invocation lost its runner
connection after all 4.5 cases and 34 of the 5.2 cases; its incomplete report remains
unchanged. A separate invocation completed the remaining 19 cases. This is complete
case coverage across two retained invocations, not an uninterrupted passing matrix.
The 4K delivery fixture passed on both versions, without claiming constrained-memory
or production-latency acceptance.

Evidence under `build/artist-next-20261022/` includes `native-clean/report.json`,
`native-clean-resume/report.json`, `native-selection-receipt.json`, both
`python-sdk*-clean-testfix.xml` files, seven CI logs and `package-verification/`.
Exact development add-on/wheel/plugin members, archive CRCs, wheel RECORD and checksums
passed; a fresh isolated installed wheel discovered 229 tools over actual stdio.
Installed Blender add-on/plugin workflows remain separate. The committed
[evidence index](development-evidence/bf5c53e.json) retains these fingerprints and limits;
it does not replace retention of the complete logs, artifacts and reviewed visuals.

## Installed-package discovery correction

Commit `395a3088695c70e551ac1734485aae6f80ac348b` fixes Blender's literal add-on discovery
metadata, validates discovery/runtime/manifest versions when packaging, and binds inventory
generation to its own checkout. Its 214-file Python inventory SHA-256 is
`53dbc3fc84028637cd4fabc28194f5fbd1aebd850c724fc083f72f0a240d2467`.
Both clean SDK suites passed **2,829 tests**, with three Windows-only skips each; all seven
CI jobs passed in run `39695106809`. [PR #3](https://github.com/Yoruiopz/Codex-Blender-Bridge/pull/3)
merged as `df531cd4c61c214a5c984bb1dc80a706c26af4bd`.

Exact-commit development packages passed archive/member/checksum/wheel RECORD checks.
The installed-ZIP probe passed on Linux Blender 4.5.14 and 5.2.2 with all imports resolving
to the isolated installed directory: fresh candidate and upgrade expose 229 documented
tools; historical baseline and rollback expose 108. Default dangerous permissions, loopback
reconnect and bounded creation/transforms were checked. Only this native case was selected;
this is not a complete native run or installed artist acceptance. Historical metadata needs
explicit known-name enablement, and clean-directory replacement does not prove preferences
migration or UI uninstall. Published downloads were not replaced.

The [committed evidence index](development-evidence/395a308.json) records package, report,
suite and CI fingerprints. Complete local artifacts are under
`build/public-install-fix-20261022/`; their permanent release retention remains a separate gate.

## Frozen 246-tool workflow increment

The development registry adds seventeen typed tools, reaching 246: [Action lifecycle](action-lifecycle.md),
[NLA clips/transitions/reordering](nla-lifecycle.md), [approved-source static imports](asset-import.md),
[static camera/light variants](cinematic-variants.md), and explicit
[unloaded FILE reconstruction](image-portability.md). Loaded byte-buffer restoration and
memory-only snapshots for missing backing files extend the existing image tools. A loaded
buffer restore preserves packed bytes; unloaded reconstruction explicitly confirms their
replacement. Both remain bounded to one million pixels and keep original native Image IDs.
Save consent is independent; retained buffers and undo history are not durable backups.

Animation/curve/driver and NLA changes add write-boundary scope, permission, context and
known-state comparisons, with measured partial recovery. Importers operate over frozen
validated bytes in a private scene and publish an owned closure; unsupported skin/animation
and general textured FBX are refused. Static variant previews retain matched current/candidate
renders and disclose Render Result replacement. None completes the full artist benchmark.

Separate native [shader interface research](shader-interface-lifecycle.md) demonstrates
socket-index animation aliasing on 4.5 and destructive default resets on type conversion.
It adds no public interface-editing API. A separate 4K image recovery probe preserves complete
raw pixels, identity and bindings after reopening, with roughly 2 GB peak RSS and a 17–18 s
cooperative encoding prototype. It does not yet implement public 4K recovery jobs, native
undo, constrained-memory or Windows acceptance. Source-matched whole-increment validation
must identify its own frozen commit and packages; prior increment counts do not certify it.

This increment is frozen at `cb7b536321e216bc4134403d466cf2a506751465`, with
246 Python files and source inventory SHA-256
`0826af25b27122c576e71f16ea93d13a0a25f73b8a306556efcc782ba290c2e4`.
Both SDK suites passed **3,401 tests**, with three Windows-only skips each. All seven
Python/SDK/package CI jobs passed in run `39697014490`. Exact add-on, wheel and plugin
members/checksums passed, and a fresh isolated installed wheel exposed 246 tools over
actual stdio with core-only defaults and disabled-domain errors.

The complete **68/68 native cases passed on each Linux Blender 4.5.14 LTS and
5.2.2 LTS** in one clean-source invocation: 136 passing cases across 162 isolated
processes, including interactive, fresh-process, installed-ZIP and 4K checks.
The frozen checkout remained clean and all source hashes matched after execution.
[PR #4](https://github.com/Yoruiopz/Codex-Blender-Bridge/pull/4) merged as
`c363f929cd1438add7729a0f5e3169c0b57feb5d`.

The [committed evidence index](development-evidence/cb7b536.json) binds these results
to their source, packages, CI logs and complete validation receipt. Full local evidence
is under `build/next-wave-freeze-20261022/`; native report SHA-256 is
`ef5aa8b1282c6289b46cd89cb02ea950193895f30ae88a96f34c7fa0db8276ab`.
File-cache advice targeted only completed task-owned artifacts; no contents were
changed or removed. These results do not establish constrained-memory, Windows,
production latency, full installed scenarios A–F or artistic acceptance.

## Subsequent guarded recovery increment

The next increment reaches **251 MCP tools**. It adds three
[cooperative packed-image recovery APIs](image-recovery-jobs.md) and two
[shader interface plan/edit APIs](shader-interface-lifecycle.md). Existing
[rig binding](rig-binding-safety.md), [rest/pose editing](rig-edit-boundaries.md),
[object property mutations](object-rna-safety.md), NLA and static cinematic variants
gain stricter ownership, exact-state recovery and late-authority checks. Binding now
requires `EDIT_MESH` because it changes vertex weights; this is an unreleased permission
correction with unchanged protocol envelopes.

Permission sets use one coherent live grant snapshot. Toolset state is checked after
providers, and image jobs check their owner/deadline/cancel flags without invoking another
permission callback before publication. Recovery evidence remains separate from file
effects; failed observations are marked unknown, detailed history is redacted when
inspection is denied, and terminal scheduler cleanup releases the owner even after
observation/history failures.

Initial frozen source `91cf62279afe2d3615cc2d9388ed0f034ca3a27d` passed both complete
SDK suites with **3,722 tests** and three Windows-only skips each. Ruff, mypy over
57 standalone files, compilation, inventory, exact packages and installed-wheel stdio
checks passed. All seven CI jobs passed in run `39701957370`.
Its 264-file Python inventory SHA-256 is
`bd334205139721e65ccd694113c98c1c7c7a62b6a04acfb6c1b5610dc71cab73`.
The complete clean **79-case** inventory finished on both Linux versions, with
**155/158 cases passing** across 196 isolated processes. The driver fixture failed
on both versions at newly guarded pose calls. Blender 5.2's scanner workflow also
exposed native Boolean material-binding changes. The [failed validation index](development-evidence/91cf622.json)
retains this result separately; passing focused reruns do not replace that matrix.

Follow-up changes keep generic self-driver pose editing explicitly unsupported,
verify typed pose restoration after driver removal, and bound Boolean application
to a demonstrated material-preserving contract. Native 5.2 can append a foreign or
null cutter material even in INDEX mode. The guarded subset requires exactly one
DATA-linked material on target and cutter, with the same native Material ID and
zero polygon material indices. The scanner performs geometry with those explicit
bindings before isolating its finish. Final pure authority checks after content
comparisons and operator polling also block late cancellation or deadline expiry.
Corrected combined-source suites, packages and complete native verification use
their own commit-bound receipts; the initial results do not certify later source.

The corrected increment is frozen at `1cd300014d337d13c272f75c957380ded20508b4`
and merged through [PR #5](https://github.com/Yoruiopz/Codex-Blender-Bridge/pull/5)
as `149ce6ed4f26f274d6637ea3ee172eddaae0881f`. Both complete SDK suites passed
**3,831 tests**, with three Windows-only skips each. All seven CI jobs passed in
run `39705859462`, covering Python 3.10–3.12 and SDK 2.0.0/2.2.0 plus packages.
Exact add-on, wheel and plugin bytes/checksums and installed-wheel stdio discovery
passed; only core was enabled by default.

One complete clean invocation passed **79/79 native fixtures on each Linux
Blender 4.5.14 LTS and 5.2.2 LTS**: 158 cases and 196 isolated processes,
including interactive, 4K, installed-ZIP and fresh-process checks. Source hashes,
script hashes, distinct process identities, integer-zero exit codes and the clean
checkout were verified after completion. Final scanner front/isometric captures
received technical visual review on both versions; this is not artist acceptance.

The [corrected evidence index](development-evidence/1cd3000.json) identifies the
264-file source fingerprint, exact packages, CI and complete validation receipt.
Local reports, logs and visuals remain under `build/next2-final-freeze-20261022/`,
with all 1,128 native evidence files hashed. External long-term retention remains
open. These Linux development results do not close any of the fourteen gates.

The [two-bone ribbon benchmark](character-nla.md) samples complete deformation,
rest/weights/material/UV data and protected motion after a fresh reopen. Its 24 matched
captures retain twelve byte-identical writer/reader pairs. This is a bounded skin/NLA
benchmark, not a production character or artist approval. The large image experiment
records exact signed HDR/negative-zero channels, roughly 93–98-second snapshots and
19–24-second restoration. A slower scheduling-budget run expired before publication;
the public deadline and memory preflight were preserved. Native publication can block
for several seconds. See the domain contract for measured limits and exact source drift.

## Protected transforms and checkpoint authority

The subsequent development source adds four typed interaction tools, reaching 255:
runtime protected-scope enforcement, exact references, transform previews and single-use
preview application. [The contract](task-plans.md) limits enforcement to reviewed static
Object transforms; wider authoring, visual references and protected saving remain open.
Undo and redo invalidate handles without dropping the active plan or protected policy.

New checkpoint work checks canonical caller lifetime, toolsets and pause/stop after
readers and before every marker write or native undo push. All modifying handler entries
share a final pure check. Batch budgets are checked again after preflight and before
child entry. Rejected handlers do not finalize unrelated deferred editor work; an entered
writer can still retain measured failure-recovery bookkeeping. These are cooperative
boundaries, not preemption of a running Blender call.

The isolated checkpoint increment `f544094238404926b244d072c03160891d3f479d`
passed 3,977 tests and three Windows-only skips on each SDK, plus the selected interactive
undo and artist-loop cases on both Linux Blender versions. Its 267-file source SHA-256 is
`c2b3c66f5c3503954f0d9addee8b68c36a5f34641ebfebbe777ca9ce2a00c9d1`;
the receipt remains in the isolated checkpoint worktree under
`build/checkpoint-authority-validation/source-receipt.json`. Combined-source packages,
complete native validation and installation require their own frozen receipts.

Applying modifiers and transforms now requires both `EDIT_MESH` and
`TRANSFORM_OBJECTS`. A post-poll authority/content check runs outside the temporary
selection override before the native call. The isolated permission correction retains
both-version denial, successful application and recovery evidence; it does not establish
that all modifying domains are safe. The wider audit still has open scene, render and
project-save findings.

## Checkpoint admission and serialization research

The next bounded development work retains a Scene/render authored plan before
permission callbacks and reuses it across checkpoint creation, handler writes and
finalization. Native undo's exact ParticleEdit weak-role transition is advanced
only after a completed push; Scene.original and other identities remain literal.
Marker compare-and-set preserves newer values, retained owner tokens prevent
finalizing another edit, and unreviewed guarded batch composition refuses entry.
Custom-property comparisons distinguish boolean, integer, float and signed zero.

The [Scene contract](scene-edit-safety.md) explicitly reports incomplete bundled
runtime preservation. The [render contract](render-boundaries.md) admits only a
bounded static EEVEE/PNG profile on the reviewed 4.5 build; it refuses the reviewed
5.2 build because hidden SYSTEM settings have no proven supported read-only reader.
An existence check followed by native property resolution can still repair storage,
so neither runtime getters nor pointer resolution supply that missing guarantee.

Private [rigid-body Mesh/UV and external native-role projections](rigid-create-new-research.md)
remain unwired to production admission. The [three-process asset experiment](portable-blend-worker-research.md)
compares one tiny static asset and packed 2×2 images, restoring original fake-user
flags. Blender 4.5 camera compatibility conversion is disclosed separately from raw
storage preservation. It does not enable project saving or prove process containment.

Per-increment frozen sources, logs and negative outcomes remain under
`build/scene-checkpoint-finish-v3-20261022/`,
`build/render-checkpoint-finish-v3-20261022/`,
`build/rigid-scope-profile-validation-20261022-6/` in its isolated worktree,
and `build/portable-blend-worker-validation-20261022/`. Their selected Linux
results remain separate from combined-source qualification and Windows acceptance.

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
