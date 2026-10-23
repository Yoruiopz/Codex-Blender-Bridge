# Native checkpoint completion

The executor retains a local completion consumer for each guarded invocation.
Creating it requires that invocation's unused registry continuation and exact
admission binding. Checkpoint calls bind the consumer to their manager and guard
before providers run. Neither the context's diagnostic binding nor a copied
consumer authorizes a new delivery.

After the retained native `undo_push` returns `FINISHED`, the manager records the
completed snapshot and consumes a distinct event before invoking the cached
domain hook and its read-only proof. The event binds the manager call, guard,
registry entry, admission, parameters and callback identities. A cancelled or
raised native call, zero undo steps, and marker-only editor work issue no event.
Legacy zero-argument observers still run after successful pushes; they cannot
advance the guarded Scene/render role plans.

Scene/render admission hooks and their exact declared role-plan delegates each
claim the authenticated delivery once. Direct calls, copied events, unrelated
pushes and replay cannot advance those expectations. Hook failure keeps the
original denial and measured marker/native-snapshot counts, consumes the event,
and prevents that consumer from resuming. Guarded batches retain a separate
canonical continuation for each child and use the latest modifying child's
consumer for finalization, including after read-only children.

These checks protect retained structured-call ownership. They do not sandbox
arbitrary Python or native code, prove complete runtime preservation, or turn
undo history into a durable backup. Native support remains limited to the
separately qualified domain profiles and exact Blender builds.
