# Native recovery availability

Unreleased on `main`; published 0.3.0 is unchanged. Checkpoints are session-local labels for
Blender's finite global undo history, **not saved backups or transactions**. A label alone
does not prove its native snapshot still exists.

## Check before recovery

1. Inspect the current scene, mode, active object and selection. Retain independent scoped
   evidence and record protected data before editing.
2. Use one logical operation or `batch.execute` for a coherent revision. Batches still apply
   every child's live permission/stop checks and are explicitly non-atomic.
3. Inspect `checkpoint.list(...).recovery`, or the compact
   `bridge.status.agent.recovery` summary. The Blender checkpoint panel shows the step limit,
   enabled state, a configured memory limit, expired-operation count and attempted-recovery
   controls. Disabled buttons do not silently select a different checkpoint.
4. Explicitly acknowledge global undo risk with
   `checkpoint.undo_last(confirm_global_undo=true, restore_snapshot=true)` in Object Mode.
   This navigates to the latest retained logical operation's before-marker. The local UI
   also permits named checkpoint restoration. Remote stop/pause checks remain authoritative;
   local recovery has its existing user-controlled recovery override.
5. Reinspect changed and protected data and compare relevant captures. Reaching a marker
   does not prove all constraints or the artistic result. Save only as separately agreed.

Omitting `restore_snapshot` keeps the compatibility contract: exactly one native global undo,
not a logical-operation restore. It clears tracking afterwards. Named labels returned in
`checkpoints` keep their existing shape; match their IDs to `recovery.checkpoints` for status.
`operation.undo_boundary_created` and `undo_boundary_finalized` describe snapshot events,
not a promise that those snapshots will remain retained.

## Availability states

| `availability` | Meaning | Snapshot navigation |
| --- | --- | --- |
| `unverified` | No observed bridge-only step-limit expiry; unobserved eviction is still possible | May be attempted if mode/settings and authorization allow |
| `guard_would_exceed_step_limit` | The next recovery guard would exceed the observed target's step budget under the current settings | Refused before stamping a guard or invoking undo |
| `expired` | Observed bridge pushes already exceeded that target's native step window | Refused; increasing preferences does not resurrect the snapshot |

`can_attempt_restore` checks only this window, Object Mode and undo settings. It is not an
authorization grant, pause override, native-context guarantee or guarantee of availability.
`snapshot_marker_verified` remains false in inspection. Only actual successful marker
navigation returns it true. `native_history_introspection=false` and
`availability_guaranteed=false` are intentional: the bridge does not enumerate Blender's
private undo stack or probe it by changing the scene.

The window counts successful bridge-owned Object Mode snapshot pushes, **not tool calls**.
It accounts for the extra guard push and resets the known branch position after measured
recovery, rather than aging older boundaries by already-undone future operations. It does
not assume Blender applies its tail step limit on the first push after undo/redo truncation.
Only live label/operation/pending-session references are retained in the bounded ledger.

Known-expired operation boundaries are pruned from the recovery queue. Named checkpoint
labels remain visible, marked expired; they do not become a fallback to unrelated work.
`expired_operations_pruned_since_clear` is bookkeeping since the last tracking reset, not
a lifetime metric. Old operation-history entries may outlive their recovery boundaries.
Native/manual undo or redo, file/session replacement, failed navigation, legacy one-step
undo and normal shutdown invalidate tracking through the existing lifecycle hooks.

## What remains unknown

Manual/operator snapshots are not counted. A configured memory limit can evict native history
earlier than the step limit, including during guard creation. Preference changes, other
editor stacks and Blender-internal grouping can also invalidate assumptions. Settings are
reported, never raised automatically. Global Undo disabled or zero undo steps cannot create
a claimed native recovery snapshot.

For unknown eviction, navigation retains the existing bounded guard/redo contract. A missing
target fails explicitly; the bridge attempts to return to captured unsnapshotted work and
reports `return_to_guard_verified`. A redo failure is an uncertain state requiring inspection,
not successful rollback. Without prior pending Edit Mode-group finalization, a
known-expiry/guard-budget refusal instead reports
`execution_started=false`, `scene_undo_performed=false` and zero completed undo steps; no
guard-return claim is made because navigation never began. If the call already finalized a
pending edit group, `execution_started=true` and that group's finalized-boundary evidence
remain explicit even though no scene undo occurred. Pre-cancellation does not create a guard
or finalize a group. No native C operation can be preempted midway.

Blender's [undo implementation](https://github.com/blender/blender/blob/v4.5.1/source/blender/editors/undo/ed_undo.cc)
and [stack limit implementation](https://github.com/blender/blender/blob/v4.5.1/source/blender/blenkernel/intern/undo_system.cc)
explain the step/memory limits and branching behavior. The ledger is conservative supporting
evidence, not a replacement for measured native recovery. Other versions and production-sized
mixed-editor/memory-pressure cases still need representative acceptance evidence.

## Native regression

Run `scripts/run_blender_checks.py` with explicit Blender paths, `--case undo_capacity` and
`--include-interactive`. It uses a disposable factory scene and isolated config/scripts/datafiles
and temporary directories. It never saves a user project or preferences.

The fixture uses actual add-on preferences and structured transform/inspection/recovery tools.
On installed Windows Blender 4.5.1 LTS and 5.1.2 it verifies:

- 17 separate edits at the factory 32-step limit: 16 retained operations recover numerically,
  the oldest is pruned, and another restore refuses without an undo. This does **not** claim
  all 17 edits were recoverable or that the initial state was restored in this case.
- In that process's isolated 128-step test setting, all 17 edits recover; the user's setting
  is never modified. New branches after repeated recovery retain correct older positions.
- Named checkpoint guard-budget refusal before navigation and irreversible expiry despite a
  later preference increase.
- Delayed Mesh Edit Mode-group finalization whose before-target expires: the refusal retains
  finalized-group/possible-mutation evidence and does not claim that scene undo occurred.
- Unobserved manual snapshot eviction remains unverified, fails explicitly and returns to
  the measured guard, including an unsnapshotted manual transform.
- Live permission denial and remote pause/emergency gates do not consume a recovery boundary.
- Independent scoped comparisons preserve the protected duplicate, geometry/material bindings,
  selection, active object and Object Mode; matched before/after solid captures check appearance.

This is a recovery-mechanics fixture, not production-art approval, durable recovery or full
REC-01/1.0 acceptance. See [the full release gates](release-1.0-readiness.md).
