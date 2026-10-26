# Installed native-save qualification

This is an opt-in development fixture, not an installed acceptance result. It
requires root execution through `scripts/run_blender_checks.py`, the reviewed
private display, and a verified package-probe configuration. Windows testing is
deferred. No source checkout is installed or added to Blender's product import
path.

The new `installed_native_save` case has three fresh interactive Blender phases:
`native_save`, `weights`, and `curve`. Each installs the candidate ZIP into an
owned scripts folder containing spaces. Original installed Runtime,
PermissionManager, executor, queue, checkpoints, registry and job service
identities remain fixed. Package members and all loaded product module origins
are rechecked during the workflow. Fixture setup/data oracles are loaded before
checkout paths are removed; their source hashes are retained, and their `main`
functions are never invoked.

This supporting harness targets the exact reviewed 0.8 candidate below. These
pins identify a package to test; they are not a native acceptance result:

| Evidence | Exact pin |
| --- | --- |
| Candidate source | `adfd0468946c7a4147b662715fb520be0afa7ae6` |
| Candidate tree | `9c24b416ede7b80268496fcd47cfd33ab562c72e` |
| Candidate add-on ZIP SHA256 | `2de08ba5033f3f7ae773f1e63449e2d8c31ac1300341526c027446ad5a9b900e` |
| Candidate add-on ZIP bytes | 872657 |
| Exact candidate CI run | 40310834054; all seven jobs passed |
| Candidate public tools | 270 |
| Component version | 0.8.0 candidate; installed native qualification pending |

Changing a candidate requires new reviewed pins and exact package/source
qualification. The supporting fixture commit is recorded separately. Historical
0.7 qualification at source `8d07ad898ba92c5e94db57b1562fefef9c8e0e1c` and ZIP
`0afc38c1315fedc952c3c657c82f510c720ce79a669df319f8278c959f67eaf4`
is preserved unchanged.

The original supporting harness commit
`513f7a102ab20ecb042ae16b9bf45d714de398e8` remains unchanged. It tested the
fa81 development package, source `fa81dc35c859c22ebd742dc4034c0a787d2ee49d`,
tree `99d6bc2e30bb536eb52ed6923d547b373d9a30a6`, ZIP SHA256
`3e645b6ff1f2a0ca6125b95b86822802f5d7dc7991b33770ff0ed037e250e054`,
version 0.7.0 development with 270 tools. Both first installed native-save phases
failed with `CALLER_HOOK_UNSUPPORTED` before the positive save cases. Their full
receipts and supporting source freezes remain separate historical failure
evidence. The corrected package above has new bytes and source identity; this
retarget does not relabel those failures or prove the corrected installed run.
The current supporting harness commit is recorded separately at execution time.

## Real queued execution

The fixture's persistent TCP worker handles only bounded JSON/socket/queue work
on literal `127.0.0.1`. It has no Blender, Runtime or scheduler reference. It keeps
one owner connection across accepted jobs and status calls. The main fixture
timer submits one request, returns to Blender, and polls on later timer turns.
Blender's genuine executor and job timers perform every product operation. The
fixture never calls `Runtime.dispatch`, `_drain_timer`, a job tick, or a replaced
permission provider. Request failures are terminal and are not retried.

The phase deadline is 300 seconds. Individual queued requests use a 30-second
budget; native-save jobs retain their 120-second requested deadline. Native calls
remain noninterruptible. A failed deadline or resource check is a failed result,
not permission to raise a bound or adopt new expected state.

## Declared coverage

The native-save phase starts disarmed, verifies actual denial and the legacy
`project.save` quarantine, then invokes the real local UI grant operator. Real
local preferences select the owned approved folder; no remote method grants
native-save authority. Owned factory cleanup and asset setup occur before
immutable save intents, with the existing finite metadata/value preflight and
129-default-channel checks. These setup effects do not qualify arbitrary artist
projects or restoration of hidden UI/cache state.

The five positive cases are initial Save As, Copy New, Save Current, new Save As
and replacement Save As. The four adverse cases cancel a running fresh reader,
revoke its authority, revoke from an owned save-post callback, and preserve a
manual geometry edit during fresh-reader work. The fixture verifies terminal
job/history facts and retained file bytes independently. Pause, emergency-stop,
invalid Edit Mode and enforced-protected-scope refusals are also included.
Fixture-owned byte reads after revocation are test oracles; they are not product
filesystem actions or a replacement permission source. The owned Python callback
is not a complete native C handler inventory.

Save-post revocation occurs before the product may hash the saved file. Its
empty artifact list and incomplete evidence remain explicit; any later
fixture-owned byte observations are recorded separately and grant no product
restore authority. Reader cancellation/revocation and manual-change cases must
verify the artifact descriptors already measured by the product.

The weights phase verifies assign/normalize, denial, locked-group scope and
invalid input against complete independent Float32 membership predictions. The
curve phase verifies the existing `RAW_FREE_POINT_V1` future-key raw coordinates
and FREE handles, exact no-op, denial and unsupported/invalid requests. Both use
an explicit genuine queued setup checkpoint before frozen requests. They verify
declared authored/protected/context state and preservation of earlier history.
Neither qualifies cold-context synchronization, full character animation,
native undo or durable weight/curve recovery.

## Evidence and remaining gates

Each fresh process writes a bounded complete JSON receipt (maximum 4 MiB),
independently reopens it, then emits a compact hash/size-bound success marker
(maximum 32 KiB). The runner's existing 64 KiB log-tail cap is unchanged. Each
marker is bound to the process instance, candidate source/tree/ZIP and phase;
all three fresh phases must pass on one build before the case passes. Root must
inspect the full receipts, native blocking/retained effects and source/package
hashes before accepting a result.

The runner exposes the canonical phase order to the stable evidence qualifier;
reports cannot supply a different order or claim a reader phase for this case.
The stable qualifier also binds every installed-phase candidate commit, Git tree
and add-on ZIP hash to its qualified source/package ledger. This intentionally
prevents a separate supporting fixture from serving as final 1.0 evidence by
relabelling its candidate.
A reviewed final-candidate/support-harness contract remains required; a fixture
must never try to pin its own containing commit as a self-reference.

Fresh installation here does not establish upgrade from 0.3.0 or 0.7.0, rollback,
restart/reconnect, wheel-to-Blender end-to-end operation, the complete native
inventory, Windows compatibility, production 4K saving or stable 1.0. Those
remain separate required gates. The full artist-workflow goal and all unmet
release requirements remain open.
