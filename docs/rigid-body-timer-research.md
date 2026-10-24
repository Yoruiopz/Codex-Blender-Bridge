# Timer-separated rigid-body memory-cache research

Status: **opt-in fixture research; the first native probe failed its negative
control, and this follow-up has not run natively**. This increment
adds no typed tool, production job driver or new supported solver scope. The
registered [rigid-body cache lifecycle](rigid-body-lifecycle.md) remains synchronous.
SIM-01, JOB-01 and the full 1.0 acceptance gates remain open.

The question is whether a small, completely admitted static rigid-body world can
populate its memory cache through separately scheduled integer-frame evaluations,
then use Blender's supported `ptcache.bake_from_cache` operator to retain that
already computed cache as a bake. Separating frames could provide cooperative
safe points without starting an unowned native background bake. Every individual
frame evaluation still contains nonpreemptible native calls.

## Exact native source

The retained source receipt is
`build/rigid-timer-source-20261023/receipt.json`; exact files are under its two
commit-named directories. The receipt records upstream paths, Git blob identities,
byte counts and SHA-256 hashes. This source review is independent of native test
results and does not establish supported behavior on other Blender builds.
The additional `rigidbody-receipt.json` in the same directory retains the exact
rigid-body evaluator and RNA setter source used to investigate that failure.

| Native commit | File | SHA-256 |
| --- | --- | --- |
| `62c1db4208e862312bc36db5bc15d4a6dbcfa3e3` (4.5.14 LTS) | `physics_pointcache.cc` | `a6e93f2cfc1d97bc32c8e61c10c75a86e8ce24b3d94a7aaaaa35c50842ee1836` |
| Same | `pointcache.cc` | `7b6e6b41ec839a9208a91ec6144aca5182e5589c2b72b981a9ab5e646086bf73` |
| `d13f752e3b9c4f8c261cda552b1021f8bcc0382c` (5.2.2 LTS) | `physics_pointcache.cc` | `3aa44eaa1facf19cb3cfcbbd14ed6992b3469dc001c554a9f8852e1204909753` |
| Same | `pointcache.cc` | `0c2badc9c5aa21d448ded4d99e294f6ada76a7987f77f726889603225c9a43ba` |
| `62c1db4208e862312bc36db5bc15d4a6dbcfa3e3` | `rigidbody.cc` | `cecfef906ee05302e62f393c50c7925394c18fff48434aba8f45f8154535fbbe` |
| Same | `rna_rigidbody.cc` | `ef115cdc17163906e33a446634bf36a9f63ba31033032392788afca12ccb2cbd` |
| `d13f752e3b9c4f8c261cda552b1021f8bcc0382c` | `rigidbody.cc` | `83493dfe758dba0dca943becdef8c1fc5eb7d50bb1c5eb82a693fe2d65a66234` |
| Same | `rna_rigidbody.cc` | `bc05c35d33e1180f1212a153ca18a25d058245e1497f6d7fa9c15d39710300a0` |

Both pinned editor implementations expose the same important distinction:

- `ptcache.bake("EXEC_DEFAULT", bake=True)` directly calls
  `BKE_ptcache_bake` before returning FINISHED: [4.5 lines 201–209](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/editors/physics/physics_pointcache.cc#L201-L209)
  and [5.2 lines 203–211](https://github.com/blender/blender/blob/d13f752e3b9c4f8c261cda552b1021f8bcc0382c/source/blender/editors/physics/physics_pointcache.cc#L203-L211).
  The implementation evaluates a frame-range loop within that one call:
  [4.5 lines 3297–3337](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/blenkernel/intern/pointcache.cc#L3297-L3337)
  and [5.2 lines 3225–3265](https://github.com/blender/blender/blob/d13f752e3b9c4f8c261cda552b1021f8bcc0382c/source/blender/blenkernel/intern/pointcache.cc#L3225-L3265).
  `bake=False` still uses this implementation; it is not a one-frame step API.
- INVOKE creates a native POINTCACHE WM job and locks the interface:
  [4.5 lines 212–244](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/editors/physics/physics_pointcache.cc#L212-L244)
  and [5.2 lines 214–246](https://github.com/blender/blender/blob/d13f752e3b9c4f8c261cda552b1021f8bcc0382c/source/blender/editors/physics/physics_pointcache.cc#L214-L246).
  This experiment does not adopt that job or use global break/cancel operators.
- `ptcache.bake_from_cache` only sets `PTCACHE_BAKED`, sends a notifier and
  returns FINISHED: [4.5 lines 335–345](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/editors/physics/physics_pointcache.cc#L335-L345)
  and [5.2 lines 337–347](https://github.com/blender/blender/blob/d13f752e3b9c4f8c261cda552b1021f8bcc0382c/source/blender/editors/physics/physics_pointcache.cc#L337-L347).
  Its shared poll checks cache/owner availability and editability; it does not
  establish frame coverage or freshness. No simulation or missing-frame repair
  occurs in this conversion operator. A baked flag remains insufficient evidence.
- FREE clears the baked bit in the tested memory-only path:
  [4.5 lines 162–174](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/editors/physics/physics_pointcache.cc#L162-L174)
  and [5.2 lines 164–176](https://github.com/blender/blender/blob/d13f752e3b9c4f8c261cda552b1021f8bcc0382c/source/blender/editors/physics/physics_pointcache.cc#L164-L176).
  It does not prove memory deletion or recomputation of changed inputs.

The native bake loop changes integer `cfra` and temporarily sets `framelen=1`;
it does not normalize `subframe` in that loop. The earlier retained
[simulation-cache research](simulation-cache-research.md) separately measured
fractional-time false success and stale FREE/rebake behavior. This experiment
therefore uses explicit subframe zero for population and verifies restored caller
time independently, while retaining the proven same-value world reset strategy.

The extra source review qualifies what that reset means. The `time_scale`
setter's reset callback marks `PTCACHE_OUTDATED`; it does not immediately erase
memory frames: [4.5 RNA callback](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/makesrna/intern/rna_rigidbody.cc#L143-L148)
and [rigid-body reset](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/blenkernel/intern/rigidbody.cc#L2155-L2160).
The evaluator handles the outdated reset when advancing from the start frame to
start frame + 1: [4.5](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/blenkernel/intern/rigidbody.cc#L2196-L2203),
[5.2](https://github.com/blender/blender/blob/d13f752e3b9c4f8c261cda552b1021f8bcc0382c/source/blender/blenkernel/intern/rigidbody.cc#L2205-L2212).
Visiting only frame 1 before setting BAKED can therefore retain old frames.
Moreover, missing baked frames can still enter the one-frame-forward simulation
fallback, so evaluation after conversion is not necessarily pure cache playback:
[4.5](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/blenkernel/intern/rigidbody.cc#L2235-L2258),
[5.2](https://github.com/blender/blender/blob/d13f752e3b9c4f8c261cda552b1021f8bcc0382c/source/blender/blenkernel/intern/rigidbody.cc#L2244-L2267).
A fresh world's first cached frame is written while advancing to frame 2;
visiting frame 1 is not proof of a stored frame.

## Retained first-run failure

The exact `d9681a9` fixture failed on both reviewed Linux builds at its incomplete
conversion control. Both runs reached the complete comparison and caller-time
restoration stage before the negative comparison returned zero difference.
The runner report and failure artifacts remain at
`/workspace/Codex-Blender-Bridge/build/rigid-timer-native-20261023/native`.
No stopped-owner cases ran, and neither run passed the research fixture.

That first control reused the previously populated world after FREE and a
same-value reset, then visited only frame 1 before conversion. The source shows
why this is not a valid proof of incomplete cache contents. The first fixture
also omitted a nonzero-motion assertion and discarded completed matrices on
later failure; its retained evidence cannot distinguish residual frames from a
static reference. The follow-up preserves that failure and replaces the control
with a separate newly allocated native world and cache.

## Intended bounded experiment

The fixture uses two separately allocated worlds, each within the existing
reviewed whole-world memory-only profile, and executes only the actual current
window's world at a time. Bodies, geometry, settings, context, dependencies and
exact cache identity remain bounded by that profile. No constraints, animation,
disk cache flags, external cache paths or new dependency exceptions are introduced.

The planned positive sequence is a fresh sequential reference, a separate reset
and candidate population across timer callbacks, exact-cache conversion, then
complete last-frame-first playback. Every full 4×4 body matrix at every requested
frame must match the independent fresh reference and the existing typed BAKE
control within the declared tolerance. FINISHED, motion at one frame and cache
information strings are not substitutes for those comparisons.
This known falling benchmark additionally requires each ACTIVE body's frame-3 Z
translation to decrease from frame 1 by more than the comparison tolerance.
This condition belongs to this fixture; the existing typed cache tool permits
valid static and zero-gravity worlds.

Each native frame-set, view-layer update and dependency-graph sampling stage
occupies a separate timer turn. The existing exact-state comparison runs before
the next stage; publication accepts only its declared frame delta and volatile
cache status. Those status fingerprints do not serialize or compare the hidden
memory-cache contents. The complete playback and incomplete-cache control are
the bounded behavioral evidence for cache population.

The fixture also requires negative and recovery controls:

- Allocate a separate native world/cache without copying, reference passes or
  bake operations on that world. Evaluate only frame 1, compare its baseline to
  the role-remapped moving reference, then convert and sample frame 3 first.
  Record flags, cache information and matrices before interpreting the required
  playback mismatch. This characterizes why conversion success alone cannot
  authorize a completed-bake claim. No stored-frame coverage is inferred from
  simply visiting frame 1.
- Introduce an authored external edit during a timer gap. The next exact-state
  comparison must refuse further owned mutation and preserve that edit.
- Cancel or revoke a required grant between callbacks. No later frame,
  conversion, context restoration, reset or cleanup write may start under the
  stopped authority. Retained partial frame/cache effects must be explicit.
- Restore authority for a new, separately authorized typed FREE and BAKE control;
  do not treat eventual cleanup as part of the canceled operation.

Timer callback counts, phase-local progress, complete matrix evidence and timings
belong in the owned detailed evidence file. The success marker must remain
bounded and reference that file by hash. No result is claimed until the isolated
runner exits successfully with source-matched evidence.
The follow-up retains live phase evidence in STATE, writes an atomic owned JSON
checkpoint after each driver turn and before motion/comparison assertions, and
includes that evidence in failure output. A later negative failure therefore
retains completed matrices, measured errors and cache-status fingerprints.
Both timer callbacks contain Python failures, retain the original traceback in
the owned evidence directory and request process exit without cache cleanup or
context restoration on that failure path. No success marker is emitted.

## Running and interpretation

Select the interactive `rigid_timer_probe` case through
`scripts/run_blender_checks.py --case rigid_timer_probe` with explicit Blender
paths and a new evidence directory. Its fixture is
`scripts/blender_rigid_timer_probe_smoke.py`; the exact marker is
`BLENDER_RIGID_TIMER_PROBE_OK `. Ordinary runner defaults do not select it.
Follow [native test isolation](native-testing.md), including private non-input
desktop enforcement on Windows. Do not launch the UI fixture directly or use a
user project. The fixture does not save a project or preferences; native process
exit recovery remains inside the runner's disposable profile.

A passing research run would establish only the measured tiny-world timer/cache
behavior and boundary controls on its exact source/build. It would not register
a cooperative bake tool, prove transport handoff or disconnect ownership, provide
an undo/durable backup, impose a hard native latency or memory ceiling, qualify
general constraints/collisions/animated inputs, or close installed/Windows/full
artist acceptance. Production integration still needs an owned job contract,
mutator interlock, terminal/history evidence and authoritative safe points.


## Source-matched development result

Commit `a40f916fc7922a0cc09128e6d0c0e31cd049db58` passes the isolated interactive
probe on Linux Blender 4.5.14 and 5.2.2. Each result retains 79 yielded phase rows
and 79 read-only status polls; completion performs a separately verified final
caller-time restore. These counts are not a count of every timer callback.
Both ACTIVE bodies fall by `0.028728008270263672` across the three-frame reference.
Every sampled 4×4 matrix matches the fresh reference, separate population and
existing typed BAKE control exactly. The distinct fresh-world incomplete cache
starts at the same matrices but remains static, giving a last-frame-first error
of `0.028728008270263672`; its baked flag does not satisfy the motion contract.

External edit, cancellation and permission loss each stop before additional native
work. The external X edit remains `0.125`; no automatic frame restoration or cache
cleanup is attempted on stopped authority. New explicitly authorized FREE/BAKE
requests succeed afterward. The final caller context matches independently.
This covers the measured tiny world and matrix samples, not hidden cache contents,
velocity/state completeness, transport handoff/disconnect ownership, a pending
checkpoint across job turns, general solver inputs, deadlines or memory caps.

The report SHA-256 is
`758d33a0cdcdcd9073c7d9eec8586226b5e546d611a345ea65afc7fa361e3b99`;
its 309-file source fingerprint is
`7d4be21b8bb9470bb9b5f0dddd21727a44fec3f142684654ad3e2d001da7274e`.
The byte-verified local source, C-source receipts, reports, logs, full matrix JSON
and earlier negative evidence archive is `build/rigid-timer-evidence-20261023.tar.gz`
(SHA-256 `56b8be29fb74332b1016bc3b15fdc46dc9c6086316fad48de08abe58a852f65f`).
The external owned display helper was reviewed and its current bytes retained;
the original runner report did not freeze its prelaunch hash. This remains focused
development evidence, with no Windows or installed/release acceptance.

A production job still requires an exact owned checkpoint, a reservation spanning
yields, control over evaluation-producing inspection, request lifecycle ownership
and a recovery ledger independent of bounded display history. The synchronous
native-call lease cannot simply be held across timer turns. SIM-01 and JOB-01
remain open; this research does not add a public simulation job tool.
