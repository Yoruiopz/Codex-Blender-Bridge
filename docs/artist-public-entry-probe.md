# Denied public artist entry research

`artist_public_entry_probe` is an opt-in interactive fixture for the actual
`BridgeRuntime.dispatch` → executor → registry path. It adds no production
permissions, admission exceptions or tools. Run only through
`scripts/run_blender_checks.py --case artist_public_entry_probe --blender PATH
--output NEW_DIRECTORY`, in a disposable desktop process. It saves neither
a project nor preferences and never starts a network listener.

The fixture supports only Release builds at the two exact reviewed sources:
4.5.14 `62c1db4208e862312bc36db5bc15d4a6dbcfa3e3` and 5.2.2
`d13f752e3b9c4f8c261cda552b1021f8bcc0382c`. The earlier isolated getter case
passed on both at bridge source `c34abf0`: three raw controls retained selection;
eleven individual getters/readers cleared a legal hidden-and-selected Base.
That result does not establish a public-entry outcome. The source review and
missing native witness are documented in [the capture design](protected-capture-design.md).

## Setup and measured calls

The actual artist tools create and arm a plan protecting factory Cube. A new
plain triangle Mesh is selected and active. Synchronized fixture setup uses
explicit `ViewLayer.update`; a valid reference and transform preview are created
through actual runtime dispatch. Raw Python permission-provider grants allow
this owned setup but keep execute-Python, project saving, deletion and external
files disabled.

Four calls are measured separately, in one main-thread timer turn without a yield:

| Case | Entry | State at dispatch |
| --- | --- | --- |
| No-admission denied control | `transform.apply` | Working Mesh hidden and raw-selected |
| Guarded transform denial | `transform.set` | Working Mesh hidden and raw-selected |
| Current-preview denied control | `task.plan.apply_preview` | Synchronized visible selected working Mesh |
| Preview after pending hide | `task.plan.apply_preview` | Previously current preview, then hidden and raw-selected Mesh |

For pending cases, `Object.hide_set(True)` is the last setup writer. Only the
source-reviewed raw `ViewLayer.objects.selected` research reader runs before
dispatch and immediately after denial. It has a Debug-build assertion and is
not a supported complete production Base-state witness. There are no private
offsets or `ctypes` accesses.

During each measured call the actual permission provider records raw selection
before returning a coherent grant set with `TRANSFORM_OBJECTS=False` and
`INSPECT_SCENE=True`. No permission-provider context getter, update or mutation
can cause the measured selection change. Selection outcomes and error classes
are recorded rather than prescribed. Every case must reach the denied provider;
the control must enter no admission factory and the three guarded cases must
enter their actual factory. A factory may reject a preview whose context becomes
stale; the receipt retains the terminal public error. The pending-preview case does not assert that its
context remains valid after synchronization.

## Evidence and limits

A Python profiler counts actual registered handler code objects, artist admission
factory/readers, `CheckpointManager.before_modification`, and `_snapshot`.
Registered ToolSpec identities, handlers, admission factories, checkpoint
callbacks, registry logic and permission checks are not replaced. The fixture
installs the recording permission provider described above. The ordered events
retain raw selection at factory and
provider entry. Each case also retains raw selection before dispatch/after denial,
the exact structured public error, outer history, literal transform channels,
protected Cube and working Mesh geometry/identities/material references,
checkpoint markers/bookkeeping, bridge pause/stop flags, window/Scene/ViewLayer
identity and frame settings. All requested transforms, protected geometry and
checkpoint bookkeeping must remain unchanged, and handlers/checkpoints must
remain unentered.

`_snapshot` contains the add-on's sole native `undo_push` callsite. Zero snapshot
entries and unchanged tracked native position establish zero bridge push attempts
and completions for these calls. This is not native global-history introspection
or a claim about arbitrary host code. Operator-wrapper profiling is intentionally
avoided: the two reviewed Blender versions use different Python/native wrappers.

Mode, active Object and per-Base hidden status have no complete supported raw
RNA snapshot. The fixture therefore records their synchronized setup values,
and performs a labeled explicit update/inspection only **after** retaining the
post-denial raw selection. That later inspection can itself clear selection in
the no-admission control; it is outside the measured interval. The fixture does
not claim complete raw Base/context preservation. A hashed JSON receipt retains
all four observations; per-case JSON is also flushed to the native log before
verification, preserving measured results if an assertion fails.

## Separate remediation design boundary

This probe qualifies an observation, not a fix. Production must not adopt its
raw Release collection reader, synchronize before capturing the baseline, or
move providers earlier and capture a fresh baseline afterward. Those approaches
would leave the original pre-provider state unproven. Armed capture remains
refused.

A production remedy first needs a source-qualified supported native read-only
witness exposing synchronization status and the relevant raw Base/active and
LayerCollection state without ensuring or evaluating. The narrow entry policy
could then refuse pending state before any syncing getter; after every provider
it must compare the same frozen witness and authored scope. Temporary capture
isolation additionally requires a complete raw per-field witness for restoration
compare-and-swap. An official status predicate alone cannot prove those writes.
No such supported RNA primitive was found on either exact build. Native witness
development and any changed admission contract require separate review and
fault/permission-loss tests; this patch changes neither.
