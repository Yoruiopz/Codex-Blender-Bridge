# Possible context effects during structured entry

An artist admission read can have a native context side effect before a requested
handler starts. In the two exact reviewed Blender builds, synchronizing a ViewLayer
can clear a legal hidden-and-selected Base. A public request may therefore receive
`PERMISSION_DENIED` after selection normalized, while its requested transform,
protected geometry and checkpoint state remain unchanged.

The source-pinned getter probe at `c34abf0` and public-entry probe at `fce7640`
demonstrated that distinction on Linux Blender 4.5.14 and 5.2.2. All four public
cases denied permission with zero handlers/checkpoints/bridge native pushes;
selection changed before the first provider in guarded `transform.set` and
pending-hide preview application. The no-factory control and synchronized preview
control retained selection. Those frozen probes qualify the observation. The
additive diagnostic subsequently passed both Linux builds at `ff8b0f0`: host checks
verified exact four-boolean error/history evidence for the three guarded calls,
absence on the no-factory control, unchanged primary errors/legacy flag presence,
and zero handler/checkpoint/native-push counts. This is selected development
evidence, not prevention or release qualification; see the
[dated source/report fingerprints](artist-workflow-checkpoint-20261023.md).

## Optional error evidence

When a known context read is reached during a failed canonical entry, its error
can include the following plain four-boolean diagnostic:

```json
{
  "entry_effects": {
    "view_layer_sync_possible": true,
    "context_change_measured": false,
    "handler_entered": false,
    "reinspection_required": true
  },
  "verification_required": true
}
```

These fields are inside the existing error `context`. They identify a possible
native context effect, not a measured change or geometry edit. Even a synchronized
read that changes nothing receives the conservative flag. No scene names, IDs,
selection values, pointers, parameters, grant values or deferred private errors
are exposed. Absent metadata does not establish that every Blender getter was
passive; this increment instruments the reviewed artist readers only.

The primary error object/code/message, existing `execution_started`,
`requested_edit_started`, `possible_mutation` and recovery evidence keep their
existing meanings. The previously qualified permission denials omitted execution
and mutation fields; this diagnostic does not turn those omissions into false
claims or invent an authored edit. It sets `verification_required=true` because
context should be reinspected.

Generic failed-operation history and runtime artist step receipts retain the
same bounded `entry_effects` evidence before terminal recording. A preview receipt
can still say `outcome="rejected"` and `handler_entered=false` while context effects
are possible. That classification describes the requested handler. Unmarked
errors/history/receipts retain their existing field shapes. Saved plan schema,
protection baselines and successful tool results are unchanged.

## Retention and scope

A physical thread-local stack binds each audit to its retained interlock entry,
after the entry fence. It stores only monotonic context/handler bits and live
status. A copied Python Context cannot redirect a read away from a genuinely new
physical entry; a stale copied Context outside an entry cannot mark a future
request. Nested context effects fold into the retained physical parent on success
and failure, including swallowed child errors. A child's handler bit never becomes
the parent's handler bit. The handler flag is marked at the exact registered
handler invocation point. An already-retained continuation temporarily binds
its own audit even if another registry is currently executing; only its possible
context effect folds back to the physical caller. Existing continuation/grant
rules are unchanged. Rebound evidence is cumulative for that retained call, so
propagation remains conservative and establishes no exact change time. Context
slots and error fields grant no authority.

Markers precede the selected-Object reader in `artist_loop._context`, the earlier
selection-source reference reader, `Boundary._session`'s mode read, and the active
Object read in checkpoint-role `Plan._read`. Metadata is snapshotted before
executor history and step receipts; direct invoke/dispatch errors are annotated
before returning, with entry-exit annotation as a fallback. The reserved field is
recomputed for each entry, preventing a reused error from carrying an earlier
call's diagnostic. Optional annotation failures preserve the primary exception.
The reviewed artist admission and native-completion cleanup paths release only
Python bookkeeping after terminal recording and perform no marked native reads.

This increment changes no grants, permission ordering, native getters, checkpoints,
editor finalization, cancellation policy, compensation or protected capture
admission. Native selection may still normalize. It provides neither a complete
raw Base witness nor context-preservation prevention. Those require the separate
[supported native witness and admission design](protected-capture-design.md).
