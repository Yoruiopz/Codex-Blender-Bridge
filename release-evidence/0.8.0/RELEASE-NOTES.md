# 0.8.0 alpha — locally authorized native project saving

Two new structured tools, `project.native_save_preview` and
`project.native_save_start`, support Copy New, Save Current and Save As on
standard Blender. Matching add-on, MCP wheel and plugin versions are 0.8.0,
with 270 public MCP tools. This is a prerelease toward the full artist workflow.

Native Save Effects is a separate, expiring local Blender grant, off by default.
The agent cannot arm it. Inspect Scene, Save Project, Access External Files and
an approved project folder are also required. Preview retains exact intent;
start accepts a bounded job. Keep the owning connection open and inspect the
terminal job and external effects. Native saving cannot be preempted, and a
failed or canceled job can retain files or other native effects. It does not
promise rollback. Copy New publishes without replacing an existing destination;
Save Current/As require explicit acceptance of the disclosed destination race.

The first save profile is finite: one local Scene, at most 32 Objects,
32,768 mesh vertices/131,072 corners, supported local rig/action/material forms,
and four already-loaded clean packed FILE images sharing a 1M-pixel/20 MiB
packed-data budget. Files are capped at 256 MiB. Dirty/generated/4K images,
protected plans and unsupported dependencies refuse. Factory palettes, line
styles and other unsupported project data can also prevent admission. The
owned test fixtures do not qualify arbitrary startup projects; users should not
delete artist data to force admission. Read the complete source contract in
`docs/native-project-saving.md`.

Accepted product source: `adfd0468946c7a4147b662715fb520be0afa7ae6`, tree
`9c24b416ede7b80268496fcd47cfd33ab562c72e`.

- All seven CI jobs passed on that commit. Each Python 3.10–3.12 × MCP SDK
  2.0.0/2.2.0 cell passed 9,687 tests, with three expected Windows skips.
- All 28 selected source-native cases passed on official Linux Blender
  4.5.14 (`62c1db4208e8`) and 5.2.2 (`d13f752e3b9c`).
- Six fresh installed phases passed using the exact accepted ZIP: genuine
  queued native saves, bounded direct weights and raw curve points. Actual
  Blender permissions, executor and job timers were used, without checkout
  product imports or service substitution.
- Sixteen installed observations passed across clean-directory 0.3/0.7
  upgrade/rollback routes on both builds, including 32 bridge connections and
  reconnects and twelve geometry previews. These probes use direct dispatch,
  manual executor/job turns and same-process reloads. They do not prove
  persisted installation or preferences across an OS Blender process restart.
- A fresh MCP wheel install, dependency check and stdio session passed with
  270 tools and 307 retained SDK responses. All 277 malformed inputs were
  rejected, including 67 native-save cases, with zero forwarded connections.
  Wheel/Git bytes, installed RECORD and preserved historical inputs matched.

Reports retain actual source/package hashes, full receipts, failures and reviewed
synthetic images. Reader receipts measure their own RSS and open/projection
intervals. Parent native blocking, parent peak memory and OS launch memory are
explicitly unmeasured. Separate wheel and Blender TCP checks do not establish
a combined MCP-to-Blender workflow.

The legacy `project.save`, protected `viewport.capture`, shader REMOVE/conversion,
held Timeline/provider reproduction and exact-build import restrictions remain
held. Arbitrary Python stays disabled by default. **Windows compatibility and
testing are deferred and unverified. All 29 implementation items and fourteen
stable gates remain open.** This does not establish stable 1.0 or complete
portable `.blend`, GLB or FBX delivery.

The concrete next steps are recorded in
`docs/releases/0.8.0-blocker-plan.md`: finish original current-pixel packing with
durable same-ID recovery, material/consumer recovery, broader ordinary save and
verification profiles, remaining artist domains and installed scenarios A–F.
Current material native failures and unqualified recovery work are excluded
from this release. Main and draft PR #8 remain unmerged; earlier releases remain
available and repository visibility is unchanged.
