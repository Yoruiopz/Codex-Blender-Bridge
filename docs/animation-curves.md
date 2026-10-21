# Bounded Action versions and F-curve authoring

These unreleased structured tools extend the existing animation tools. They do not
complete character, animation or NLA acceptance for 1.0. Explicit assignment and
retention are covered separately by the bounded [Action lifecycle](action-lifecycle.md).
The existing frame/range/key tools have [guarded mutation contracts](animation-mutations.md).
Both require Blender-side `EDIT_ANIMATION`, the `animation` toolset and an explicitly
named local editable non-override object with an active Action. NLA tweak mode is
rejected. They participate in the normal checkpoint/history workflow and never save.

## Create an independent Action

`animation.action_copy(object_name, new_name, affected_objects?)` copies the complete active Action and
binds only the named object to that new version. The name must be unused and fit 63
UTF-8 bytes. Shared source Actions may be copied without changing their channels;
curve authoring then edits the independent version. A layered Action must have an
assigned active slot, whose identifier is preserved in the copy.

Before allocation, the complete Action is bounded to 1,024 curves and 16,384 total
keyframes, with at most 1,024 unsampled keyframes and 32 modifiers per curve. Layered
inventory is bounded to 64 slots, 16 layers, 32 strips per layer and 64 channelbags
per strip. Unsupported native layered APIs fail explicitly.

The source is retained in the current session. **An unused source Action is not
pinned with a fake user and may be omitted by a later save.** The result reports its
remaining users, fake-user state and session-only versus referenced retention.
This is neither durable version storage nor an automatic backup. Allocation or
binding failure reports the retained new Action name and measured binding recovery;
it does not silently delete the retained Action.

## Edit one existing curve

`animation.curve_edit(object_name, data_path, index=0, keyframes?, extrapolation?,
slot_identifier?, affected_objects?)` selects exactly one existing F-curve on the active Action. Shared,
linked, overridden or read-only Actions are rejected. Layered Actions use only the
object's assigned active slot; an explicit slot identifier must match it.

Each of at most 256 `keyframes` entries names one distinct existing `frame` and may
set `interpolation` (`CONSTANT`, `LINEAR`, `BEZIER`), `easing`, handle types, and
`handle_left`/`handle_right` coordinates. Explicit handle coordinates require the
corresponding `FREE` type. Numeric input is finite and bounded to ±1,000,000. No keys,
channels or slots are inserted or guessed. Curves are limited to 1,024 existing
unsampled points. Extrapolation is `CONSTANT` or `LINEAR`.

All input is validated before edits. Post-state contains every bounded curve point,
including handles affected by native recalculation. Native keyframe wrappers are
reacquired after extrapolation/update because Blender may invalidate earlier RNA
wrappers. Failure attempts measured local restoration and reports whether mutation
may remain; reinspection is required. Other Action channels and source versions
are not replaced. Automatic handle recalculation can affect neighboring handles on
the edited curve. Other Action metadata, layers, groups, slots and channels are
compared around each write. Point wrappers are reacquired at every write boundary.

Both tools now recheck live cancellation, pause/emergency stop, permission and
toolset, exact object/Action identity, Action content/reference ownership, current
session and NLA/binding context before every write and compensation. Changed
consumers, manual keys or a newer binding prevent stale compensation. A failed
copy retains its allocation and delegates binding recovery to the same guarded
Action lifecycle contract; it never blindly rebinds a protected source or deletes
the retained copy. The optional `affected_objects` defaults to an empty list for
independent objects. Dependent consumers must be enumerated exactly within the
32-object closure; unsupported graphs fail closed. These tools require no active
owner drivers or tweak mode, local editable Actions, and bounded lifecycle content;
asset-marked/custom-property Actions and sampled curves need broader contracts.

## Verification and remaining limits

Unit fixtures cover invalid input, shared/linked ownership, active layered-slot
selection, failure restoration and RNA-wrapper replacement. The disposable native
`animation_curves` runner case verifies independent Action binding, protected source
and unrelated channel preservation, linear/constant motion samples, explicit FREE
handles, context preservation and playback using an existing typed NLA strip.

The strengthened fixture passes on **Linux Blender 4.5.14 LTS and 5.2.2 LTS** in
`build/next-wave-animation-guard-native-20261022-final-2/report.json`. It includes measured
native compensation and late pause/permission/manual-key refusal. Unit fixtures also
prove live stop/cancel/permission/toolset refusal, postwrite manual-key/consumer
interleaving, protected-channel preservation after native failure, and retained
allocations after authority or ownership changes. The earlier 4.3.2 evidence is
historical source evidence. Windows, production-scale/mixed-editor undo, curve
insertion/deletion and full character acceptance remain open. Run native fixtures
only through `scripts/run_blender_checks.py`.
