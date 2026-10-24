# Reviewed 0.4.0 alpha publisher

Prepared only; the owner has not run the workflow or any API request. Root owns review, support-branch creation/push, execution and publication.

`publish-reviewed-alpha.yml` is bound to `Yoruiopz/Codex-Blender-Bridge`, push branch `codex/publish-reviewed-0.4.0`, attempt 1, accepted source `4470d88bb4d8fb1ed75e86090dd6886fb55eb589` / tree `0353d119fd44ac918dc66d871ef2279576f9312d`, CI run `40058140088`, artifact `12546620664`, draft release `422510687` and tag `v0.4.0`.

The root-created support branch must contain exactly these three regular files in `release-evidence/0.4.0/`:

- `RELEASE-NOTES.md` (3,580 bytes; SHA256 `575411e1002676966a760c21660850527769ac31180736da767d9d0f54f5a7cb`).
- `blender-codex-bridge-0.4.0-development-evidence.tar.gz` (22,157,039 bytes; SHA256 `f6bc5dce6ecb2d495e7390be4cfcf81127c9d8a597eb63f578d010f8e594fc1a`).
- `EVIDENCE-SHA256SUMS.txt` (121 bytes; SHA256 `c5dbdaa22890f6ce0a94a1a8a8964e466fdc183bae53cfb20ca1bd0f0754cecd`).

Place the reviewed YAML at `.github/workflows/publish-reviewed-alpha.yml` on that branch. Checkout disables persisted credentials and selects the triggering support-branch commit. Download-artifact v4 retrieves only the fixed accepted artifact. Its four extracted package files and the two evidence assets have exact embedded sizes and SHA256 values; both checksum manifests also have exact expected contents. No source build, candidate import, candidate execution, archive execution, evidence extraction or merge is performed.

Before writing, the inline standard-library script checks the accepted run and all seven successful jobs, artifact identity/digest, accepted Git tree, exact draft body, target and prerelease status. It allows the tag to be absent or already resolve to the accepted source. It snapshots older releases, their tag objects and asset metadata, plus the latest stable release ID. Download redirects are HTTPS and host constrained; authorization headers are stripped before leaving the API host. Mutating redirects are refused.

Existing expected assets must already match their pinned metadata and independently downloaded bytes. Only missing assets are uploaded; there is no overwrite, deletion or automatic mutation retry. All six remote assets are downloaded and hashed before the final draft/CI/older-release rechecks. Publication changes only `draft=false`, `prerelease=true`, `make_latest=false`; subsequent checks require the tag to resolve to the accepted source and reverify all remote bytes, older release/tag metadata and latest stable ID.

An unexpected asset, body/state mismatch, changed older release, unknown upload outcome or missing digest stops execution. A later reviewed support-branch push may resume missing-only uploads while the release remains a matching draft. A release already public is deliberately refused at entry; root should inspect its state. A failure after publication is reported without automatic deletion or rollback. GitHub metadata pagination is deliberately bounded to fewer than 100 releases/assets and exactly seven CI jobs. Concurrent external edits cause refusal when measured; the workflow's concurrency group serializes only this publisher.

Static checks parsed the embedded Python AST and rehashed all six actual local assets plus the notes. PyYAML was unavailable in the existing interpreter, so the small fixed YAML structure was read manually. No workflow, native test, build, installation, candidate code or network request was executed during preparation. Independent source review is tracked in the accompanying receipt.

This only publishes the accepted 0.4.0 alpha. Windows remains deferred and unverified, all 14 stable readiness gates remain open, and separate 0.5 development is absent from these accepted artifacts.
