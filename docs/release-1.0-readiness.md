# Working toward 1.0.0

Status: **not release-ready**. This is an acceptance plan, not a feature announcement
or a promise of a release date. Published 0.3.0 remains alpha; `main` contains unreleased work.
No version bump or publication happens merely because the tool count increases.

## Proposed 1.0 promise

A dependable, consent-first local bridge for the documented structured Blender workflows:
inspect, resolve targets, checkpoint, edit, structurally verify, visually verify where relevant,
and save only with permission. Arbitrary Python stays a disabled-by-default super-permission,
not evidence that every Blender feature has a dependable structured implementation.

The exact supported Blender versions and operating systems must be decided from release
evidence. The present declared minimum (4.2) is broader than the locally exercised matrix
(4.5.1 LTS and 5.1.2 on Windows). Do not call all platforms/versions verified by inference.

## Release gates

| Gate | Required acceptance evidence | Current gap / next work |
| --- | --- | --- |
| Target and data ownership | Every modifying domain documents shared data, linked libraries, overrides, active/multi-object modes and hidden scope; rejects unsupported cases before mutation | Mesh/UV ownership guard added on main; audit materials, modifiers, rigs, nodes, transforms and all remaining mutators |
| Recoverable edits | Deliberate mid-operation faults, canceled callers, operator failures and manual undo interleaving leave truthful history and verifiable recovery state | Existing checkpoints and batch evidence are not transactions; expand injected-failure and real undo tests |
| Preserved context | Each representative workflow proves unchanged mode, selection, active object, visibility, UV layer and unrelated data where promised | Selection preservation has coverage; UV layer activation and operator context need broader audit |
| Bounded evidence | Explicit truncation, stable pagination rules, large-scene fixtures and measured time/memory reports | Hard limits exist; add performance baselines and inspect partial-result handling across domains |
| End-to-end workflows | Modeling, materials/nodes, UVs, rigging, animation, scene layout and rendering each have an install-to-result scenario with pre/post evidence | Current factory-startup smokes cover portions, not complete production acceptance |
| Visual verification | Retained, matched viewport/render evidence for appearance-sensitive acceptance scenarios | Isolated preview exists; add repeatable comparisons and interactive viewport coverage |
| Protocol and authorization | Versioned compatibility, reconnect, malformed/oversized frames, duplicate IDs, timeout/cancel, pause/stop and Python gates pass adversarial tests | Core tests exist; expand live disconnect and recovery scenarios; no LAN listener |
| Installation and upgrade | Fresh ZIP/wheel/plugin installation, previous-release upgrade, rollback, paths with spaces and disconnected/restarted Blender tested on claimed platforms | Package/metadata/checksum/clean-wheel CI exists; interactive install and platform matrix remain open |
| Public contracts | Registry, schemas, README, permission matrix, error codes, limitations and migration notes agree for the release commit | Generated inventory is checked; audit full parameter/error contracts and freeze supported surface before RC |
| Release provenance | Packages built from one tested commit; all checks green; checksums verified; downloadable assets and reproducible test report retained | Packaging gates exist; combine Blender acceptance evidence with CI for each release candidate |

No row is complete merely because its happy path passes. Permission denial, unsupported
context, preservation constraints and recovery are part of the acceptance criteria.

## Delivery sequence

1. **Safety baseline:** close ownership/context gaps, add regression fixtures, strengthen failure evidence.
2. **Daily workflows:** finish targeted structured editing gaps and add whole-task acceptance scenarios.
3. **Compatibility and usability:** exercise installation/upgrades and Blender/platform matrix; align UI and docs.
4. **Release candidate:** freeze supported contracts, run the complete matrix from a clean checkout,
   review remaining known issues, and package a candidate. Fix release blockers before 1.0 publication.

Large planned capabilities such as compositor graphs, advanced weights/NLA/drivers, simulations,
durable variants and semantic references need explicit scope decisions. They must be either
implemented and verified or clearly excluded from the 1.0 promise—not silently claimed through Python.

## Current increment: shared mesh ownership

Selection-scoped mesh edits (normals, delete, dissolve, extrude, inset, bevel, seam marking)
and UV unwrap/Smart Project/packing now require local, non-override, single-user mesh data.
Unsupported ownership returns `NOT_IMPLEMENTED` before editing or creating a UV layer.
Inspection remains available for shared meshes. This does not silently copy data or make
linked assets local; those are separate user decisions. Other editing domains are not
covered by this guard and still require the audit above.

## Known acceptance-test gap found during this audit

`blender_uv_modifier_constraint_smoke.py` currently passes even when Blender prints
`Unwrap failed to solve 1 of 1 island(s)`. Its later Smart Project checks do not prove
that the earlier unwrap produced the intended result. Keep this script as a domain
dispatch smoke test, not proof of a successful unwrap workflow. Before 1.0, add a
well-seamed fixture with explicit non-degenerate UV postconditions and a failure fixture
that distinguishes an operator's `FINISHED` response from the user's goal being achieved.
