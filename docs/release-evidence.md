# Release evidence qualification

`scripts/qualify_release.py` is a fail-closed gate for the full 1.0 target.
It exits zero only when every required evidence contract passes. Native runner reports
retain `release_readiness: NOT_ASSESSED`; a passing smoke report alone cannot qualify a release.
The committed [ledger](release-1.0-ledger.json) deliberately records every requirement as open.
Its version selections are test targets, not claims of passing acceptance.

Copy the ledger into a retained evidence bundle outside the checkout. Populate it with
actual results after completing the requirements in the [execution plan](plan-1.0.md)
and [readiness gates](release-1.0-readiness.md). Run from a clean release checkout:

```text
python scripts/qualify_release.py --ledger /absolute/path/to/evidence/ledger.json
```

The output is JSON containing `READY` or `NOT_READY` and explicit blockers. Publication
automation must require exit code zero for the same ledger, commit and package bytes it
will publish; this CLI itself neither publishes nor grants publishing permission. Without
`--stage`, qualification is read-only. `--stage /new/output/directory` copies qualified
packages plus a hash-checked evidence ZIP and qualification receipt only after every gate
passes. Staging rejects changed package/evidence bytes and must be outside both checkout
and evidence bundle.

## Ledger and artifact identity

Use schema version `1` and target version `1.0.0`. `commit` is the full Git SHA.
`source_files` maps every Python file under `addon/`, `mcp_server/`, and `scripts/` to its
SHA-256. `source_sha256` is SHA-256 of UTF-8 `json.dumps(source_files, sort_keys=True)`,
matching the native runner. Missing files, changed files, extra source files and dirty
or untracked checkout state block qualification. Source paths and bytes are also compared
directly with committed Git blobs, so ignored additions and assume-unchanged files cannot
masquerade as tested commit contents. Use a fresh qualification checkout without line-ending
conversion (`git -c core.autocrlf=false clone ...` on Windows); acceptance packages and
native fingerprints must use those exact source bytes. All component versions must match 1.0.0.

`support` selects exact `blender_lts` (4.5.x) and `blender_stable` (stable 5.x) patch versions
on `Windows 11`. Re-select the current supported stable patch before RC and rerun acceptance;
the initial values are the existing exercised development versions. Other OSes and 4.2 are
outside this qualification target and must not be described as release-verified.

Every artifact reference is `{"path": "relative/or/absolute/path", "sha256": "64 lowercase hex digits"}`.
Paths are relative to the containing ledger or receipt, respectively. All resolved files
must be inside the ledger's retained bundle, available and hash-matched. Use relative
references for a portable uploaded bundle. `packages` has exactly `addon`, `mcp`, `plugin`, and
`checksums`, referencing the matching 1.0.0 filenames produced by the release builder.
Qualification checks package identity, source contents, ZIP integrity and exact checksum lines.

Every receipt contains `schema_version: 1`, `commit`, `source_sha256`, `package_sha256`
(all four package keys and hashes), and a nonempty `artifacts` array of retained references.
Receipts themselves are referenced and hashed by the ledger. Historical evidence from
another commit, dirty worktree, source digest or package set does not qualify.

## Required receipt kinds

- **Requirement acceptance:** each of the fourteen fixed requirement IDs needs
  `status: "accepted"` and a nonempty `evidence` list in the ledger. Each receipt has
  `kind: "requirement_acceptance"`, matching `requirement_id`, `status: "accepted"`,
  `structured_tools: true`, a named `reviewed_by`, and nonempty `visual_evidence` references.
  `checks` must mark each of `success`, `permission_denial`, `invalid_context`, `preservation`,
  `recovery`, `structural`, and `visual` as `"passed"`. Review must cover the complete
  requirement, including specialist capability gaps; one tool's happy path cannot stand
  in for the whole requirement. Test-fixture setup Python is permissible; product workflow
  acceptance must use structured tools.
- **Quality matrix:** `quality_matrix` references a `kind: "quality_matrix"` receipt with
  every supported Python 3.10/3.11/3.12 × MCP 2.0.0/2.2.0 combination passing, plus passing
  lint, typing, add-on compilation, inventory, diff, package and checksum checks. Retain
  command logs and exact-commit CI artifacts rather than copying another commit's status.
- **Native matrix:** `native_matrices` references `kind: "native_matrix"` receipts with
  `platform: {"system": "Windows", "release": "11"}` and a hashed `report` reference.
  The report must match source/commit, be clean, pass every current runner case exactly
  once per executable, and use private Windows desktops for UI cases. Together the receipts
  must cover both selected versions. Each receipt's `logs` list contains `case`,
  `blender_executable`, and an `artifact` reference for every result. Phased cases add
  `phase: "writer"` or `"reader"` and retain both logs. Distinct process-instance tokens,
  correlated phase markers, positive process IDs, both successful exits, and consistent
  versions are required; a parent's success flag cannot replace these process proofs.
  Logs must match the runner success marker and reported evidence.
- **Installed scenarios:** `installed_scenarios` references twelve `kind: "installed_scenario"`
  receipts: A–F on each selected Blender version. Include `scenario`, `blender_version`,
  the Windows 11 `platform`, `installed_packages: true`, `source_checkout_imports: false`,
  and all acceptance/reviewer/check/visual fields above. Scenario F also requires
  `upgrade_from: "0.3.0"` and `rollback_verified: true`. These are actual install-to-result
  exercises, not direct dispatch from the source tree.

The validator proves consistency and completeness of retained records. It cannot establish
the authenticity of a host assertion or replace human artistic review. Reviewers must retain
the actual native/CI logs, package-install provenance and images, and inspect their meaning.
No successful receipt is generated automatically by this infrastructure.

Development CI retains its package artifacts and per-matrix JUnit reports for 90
days. This extends the previous 14-day package window, but is not permanent release
evidence. Before those artifacts expire, retain the complete accepted bundle and
hashed receipts outside expiring CI storage. The qualified publication workflow
uploads the hash-checked evidence ZIP alongside the immutable release packages.

## Manual release workflow

The `Qualify and publish 1.0` workflow is explicitly dispatched; pushes and pull requests
continue using normal development CI. It requires the full release commit and a successful
Actions run at that same commit retaining a reviewed `release-candidate-evidence` artifact.
That artifact has `ledger.json` at its root and all referenced files beneath it. The workflow
checks the producer commit, downloads the bundle outside the checkout, qualifies and stages
the exact package bytes, and requires `docs/releases/1.0.0.md` from the accepted commit.

It requires an existing v1.0.0 tag at the accepted commit and does not create or replace
tags. It uploads a draft release, downloads
and hashes all uploaded assets, then publishes as the final step. It does not change
repository visibility or replace earlier release assets. A failed upload/verification can
leave an unpublished draft; review and remove that incomplete draft before retrying.
The current 0.3.0 source and open ledger cannot pass this workflow.
