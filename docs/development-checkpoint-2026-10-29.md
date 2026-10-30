# Development checkpoint: 2026-10-29

This checkpoint records private development evidence through **2026-10-30 00:06 UTC**.
It does not qualify a new release. Published [0.9.0 alpha](releases/0.9.0.md)
remains the accepted packaged baseline; source-only increments below have no
matching installed-package acceptance. All 29
[implementation items](implementation-completion.md) and all fourteen
[stable release requirements](release-1.0-ledger.json) remain **OPEN**.

## Verified private prerequisites

| Source | Completed verification | Scope and remaining limit |
| --- | --- | --- |
| Owned snapshot cleanup, `d540175ac6cfacf72c0abde93210328760472ace` | 11,253 non-Blender tests passed, three Windows-only skips, all static checks passed. Linux Blender 4.5.14 and 5.2.2 passed 26 fresh native phases, covering 68 cases and 72 independently rehashed and parsed evidence copies. Source and isolation helper stayed unchanged. | Original-owner cleanup, preservation, stop/retry, retirement and bounded repeated captures. Request binding uses a source-qualified closure replica; actual executor dispatch and transport are unqualified. Evidence copies are test artifacts, not durable recovery backups. |
| Mesh-storage role, identity and native-key guards, `250067f283532d5d0a5a87675ae96c09f2f6cb48` | 12,739 non-Blender tests passed, three Windows-only skips, all static checks passed; all 774 source files stayed unchanged. | Source-model prerequisite only. The untraced native preview exceeded its 60-second deadline before job start. Native preparation and recovery are unqualified. |
| Runtime-first descriptor audit, `13adb61077c9634bb9188d0d95415b2dd1c3f134` | 12,764 non-Blender tests passed, three Windows-only skips, all static checks passed; all 774 source files stayed unchanged. Earlier focused validation passed 435 tests, and independent review passed nine additional adversarial models and 47 selected cases. | Removes unused static metadata reads while retaining shadow/origin screening and the controls around each remaining native read. The exact-source full suite passed. Native deadline compliance is **not** established. |

The cleanup phases cover the existing stored-snapshot gateway and cleanup
success, permission denial, ownership tampering, stop/retry, partial failure and
sixteen repeated captures on each build. The independent audit verified fresh
process identities, retained foreign files, removed owned files and resource
floors. This does not establish history retention, restart recovery, current
edited pixels, paired 4K storage or complete artist-project recovery.

The runtime-first change's actual **untraced** Blender 5.2.2 preview still
returned `TIMEOUT` after approximately 60 seconds. No job start or preparation
ran. The fixture settled with no active job, executor frame or executing mutator;
sampled identities and protected values matched. These samples do not establish
complete preservation or the required five-phase job lifecycle. The source and
private display helper remained unchanged. The test deadline and safety checks
were not relaxed, and no precise CPU attribution has been established.

Local retained evidence is indexed by
`milestone-owned-cleanup-qualified-20261029.json`,
`milestone-b2-role-source-qualified-20261029.json` and
`b2-runtime-first-native05-cold-diagnosis.json`. These private manifests and
their logs are separate from published release assets.

## Next critical path

1. Prove the bounded native bulk runtime-flag API before considering product
   adoption: original collection/getter provenance, membership and ordering,
   exact result shape, before/after control checks, injected failures and measured
   blocking intervals on both stock Blender builds. No generic metadata cache,
   skipped ownership comparisons or deadline extension is justified by the
   present timeout. Re-run the real preview and complete job lifecycle after a
   reviewed implementation, then qualify the exact source with the full suite.
2. Add a fixture through actual queued executor dispatch for owned snapshot
   cleanup. Verify original request/lifetime binding, interruption, denial and
   failure/retry through the real executor and loopback server in a fresh test
   registry. Shipping simulation/cache caller integration remains a separate
   required step. The passing closure replica is a prerequisite for this test,
   not its substitute.
3. Integrate qualified prerequisites into native Mesh-storage, GLB, texture and
   save workflows. Prove original file-byte packing separately from current
   edited-pixel packing, identity-preserving durable restoration and fresh-process
   reopen at original 4K resolution. Then run the required structured artist
   scenarios and matching installed-package checks, including portable `.blend`,
   textured/skinned/animated GLB and FBX delivery.

These steps support the existing requirement ledger. Modeling/retopology,
protected editing, UV and look development, character animation, procedural and
cinematic work, interaction and production delivery retain their full completion
criteria. Temporary bounded profiles and refusals do not close those items.
The published save limits remain **16,777,216 aggregate pixels, 80 MiB packed
bytes and 256 MiB saved files**; private larger-budget work is unqualified.

Implementation continues on official, unmodified Linux Blender **4.5.14** and
**5.2.2** through the [isolated native runner](native-testing.md).
**Windows-specific compatibility and testing remain deferred until implementation
is complete and remain unverified.** They do not block this implementation pass;
complete Windows and installed-candidate acceptance remain mandatory before
stable 1.0. See the [execution plan](plan-1.0.md) and
[readiness gates](release-1.0-readiness.md) for the unchanged release criteria.
