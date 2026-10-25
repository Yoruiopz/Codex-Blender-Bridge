0.5.0 alpha adds bounded 4K painting and guarded direct UV edits. The full artist-workflow 1.0 target remains unfinished; all fourteen stable release gates remain open.

Changes:

- Surface-paint jobs accept source/stencil inputs up to 4096 × 4096, use bounded ownership tiles and finite work counters, and preserve complete input/output hash checks. Synchronous surface painting keeps its separate one-million-pixel profile.
- Generated-image sculpt-mask reads support the bounded 4096-square profile. Sampling remains synchronous; progress/cancellation through a job ID is unavailable for this read.
- `uv.coordinates_set`, `uv.transform` and `uv.pin` retain independent intent before providers, verify exact Float32 values and owned write prefixes, and permit measured compensation only while authority and expected state still match. Unknown outcomes retain partial state for inspection. The initial profile is static, material-free, single-user Edit Mode, with supplied physical buffers, UV sync disabled, at most 512 corners/eight maps. Batch composition and artist-protected-plan operation are unsupported.

Verified source: `4a45b99927082e1448a963140d4895c4ae82a4c7`, tree `c7daaead4cb9332b81768535248e1c7e67037d7c`.

- [Exact-commit CI](https://github.com/Yoruiopz/Codex-Blender-Bridge/actions/runs/40172422470): seven successful jobs; each Python 3.10–3.12 × MCP SDK 2.0.0/2.2.0 cell passed 7,939 tests with the same three Windows-only skips.
- All four accepted package/checksum files passed API digest, archive safety, immutable Git payload and wheel RECORD comparisons. The release uses these exact CI-built bytes.
- Fourteen selected native process results passed on Linux Blender 4.5.14 (`62c1db4208e8`) and 5.2.2 (`d13f752e3b9c`): direct UV cases, actual 4K surface/stencil/sculpt-mask cases, checkpoint-sensitive weight/asset regressions, and two installed add-on upgrade/rollback routes.
- Normal 4K jobs took 240.466 / 224.349 seconds; peak whole-process RSS was 2,801,774,592 / 2,663,469,056 bytes. These are measurements of the retained generated DATA, raw stencil and orthographic fixture. They do not promise universal completion, realtime performance, constrained-memory operation or native-call preemption. Queue/start cancellation, disconnect and deadline endpoints are recorded separately.
- A fresh installed wheel passed an actual MCP SDK 2.2.0 session with 266 tools, 25 disabled domains and 195 malformed standard-JSON cases. Installed module/RECORD bytes matched the wheel and Git. Third-party dependencies were reused through explicit read-only links; the bridge wheel and session were new.
- Add-on fresh install, previous-version replacement, upgrade and rollback passed separately with published 0.3.0 and 0.4.0 packages on both builds, including default denial, installed origins and reconnect checks. Four rows execute in one fresh Blender process per build/route; this does not establish Blender process restart, preference migration or complete installed artist scenarios.

Limits:

Windows compatibility/testing remains **deferred and unverified**. Reviewed visuals, constrained-memory runs, native global undo, durable recovery, complete A–F artist workflows and complete native inventory acceptance remain open. UV checks use local main-thread registered-tool dispatch; 4K fixture transport and installed discovery checks do not constitute installed artist-workflow acceptance. Automatic texture-space cache/hidden state, internal BMesh allocation purity and persistent UV-layer identity remain unverified.

`project.save` remains unavailable for Save and Save As. Protected viewport capture, shader-interface REMOVE/conversion and the exact Blender 5.2.2 typed-import quarantine retain their restrictions. Disposable asset readers use explicitly labeled fixture serialization/import; they do not qualify those blocked production capabilities. Curve, cloth-job and material-recovery work in separate development lanes is excluded.

Install matching add-on ZIP, MCP wheel and optional plugin together; verify `SHA256SUMS.txt`, restart both sides and begin with a disposable project and inspection. GitHub source archives are not the add-on installer. The evidence archive includes original CI ZIPs/logs, native reports, installed-session receipts, member hashes and a standalone source Git bundle verified by restoration and `git fsck --strict`. Verify it with `EVIDENCE-SHA256SUMS.txt`.

Previous releases remain available unchanged. Main and draft PR #8 remain unmerged; repository visibility is unchanged. This is a prerelease, not stable 1.0 or cross-platform qualification.
