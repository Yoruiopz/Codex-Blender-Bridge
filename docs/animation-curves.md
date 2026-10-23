# Bounded Action versions, F-curve inspection, sampling and authoring

These unreleased structured tools extend the existing animation tools. They do not
complete character, animation or NLA acceptance for 1.0. Explicit assignment and
retention are covered separately by the bounded [Action lifecycle](action-lifecycle.md).
The existing frame/range/key tools have [guarded mutation contracts](animation-mutations.md).
The two authoring tools require Blender-side `EDIT_ANIMATION`, the `animation` toolset and an explicitly
named local editable non-override object with an active Action. NLA tweak mode is
rejected. They participate in the normal checkpoint/history workflow and never save.

## Inspect one exact curve before editing

`animation.curve_inspect(object_name, data_path, index=0, slot_identifier?, point_offset=0, point_limit=64)`
requires only Blender-side `INSPECT_SCENE` and the `animation` toolset. It reads the
explicit object's active Action without changing context, evaluating the curve,
updating handles or creating a checkpoint. Shared, linked and noneditable Objects
and Actions remain readable. This tool does not inherit the authoring ownership or
NLA tweak-mode restrictions.

The selector must match exactly one existing curve by `data_path` and `index`
(0–16,384). A layered Action requires the object's assigned active slot; an optional
`slot_identifier` must match it. Other slots are excluded. Legacy Actions reject a
slot identifier. The shared bounded Action inventory supports at most 1,024 curves,
64 slots, 16 layers, 32 strips per layer and 64 channelbags per strip. Unknown
layered APIs fail explicitly.

The result identifies `object`, `action`, `slot_identifier`, `data_path`, `index`,
`group`, `mute`, `lock` and `extrapolation`. Each `keyframes` record contains `frame`,
`value`, `interpolation`, `easing`, both handle types and both two-dimensional handle
coordinates. Coordinates are finite JSON numbers; unsupported nonfinite native
data returns `NOT_IMPLEMENTED`. These are stored authored values, not sampled
motion or proof of deformation quality.

Pagination reports `point_count`, `point_offset`, `point_limit`, `returned_points`,
`truncated` and `next_offset`. Follow `next_offset` while `truncated` is true.
Offsets are strict integers from 0 to 1,000,000 and limits are strict integers from
1 to 256. Curves exceeding 1,000,000 total points return `NOT_IMPLEMENTED` before
point reads, so every supported page and terminal offset is reachable. Each page
uses only the requested native indices, including when earlier pages are skipped.
An offset equal to the count returns an empty complete page; an offset beyond it
is invalid. Sampled curves return `NOT_IMPLEMENTED` even when their keyframe
collection is empty, rather than suggesting their animation was fully inspected.

## Measure values between stored keys

`animation.curve_sample(object_name, data_path, frames, index=0, slot_identifier?)`
requires Blender-side `INSPECT_SCENE` and the `animation` toolset. It uses the same
exact active-Action/assigned-slot selector as `curve_inspect`; shared, linked and
noneditable data remains readable. Supply 1 to 128 explicit finite numbers within
plus or minus 1,000,000. Booleans and numeric strings are invalid. Request order and
duplicate frames are retained.

Each `samples` entry reports `requested_frame`, the Float32 `evaluated_frame`
actually passed to Blender, and the finite `value` returned by native
`FCurve.evaluate`. Results identify the object, Action, slot, curve, group,
extrapolation, mute/lock state, `point_count` and `sample_count`. Muted and locked
curves may be read: these values describe the stored curve independently of
whether playback uses it. `evaluation_scope=ACTIVE_ACTION_FCURVE`,
`scene_evaluated=false` and the four `includes_*` flags explicitly exclude NLA
blending, drivers, constraints and deformation. Frames use Action coordinates;
there is no scene-time or NLA remapping.

Sampling supports 1 to 1,024 keyframes with finite coordinates and handles,
strictly increasing stored key times, `CONSTANT`/`LINEAR`/`BEZIER` interpolation,
and `CONSTANT`/`LINEAR` extrapolation. Empty or sampled curves, modifiers, drivers,
unsupported interpolation/extrapolation and an unavailable native evaluation API
return `NOT_IMPLEMENTED` before evaluation. Invalid native output or an evaluation
failure is an explicit error; a partial sample list is never returned as success.
No property path is resolved or evaluated as Python.

The tool never advances scene time, evaluates the dependency graph, updates
handles, writes properties, creates checkpoints or saves. Cancellation/deadline
checks bound work between native calls; an individual native evaluation remains
non-preemptible. Use `curve_inspect` to compare stored authoring, then
`curve_sample` to compare numeric easing or overshoot at chosen frames. Full
character motion and visual deformation require separate evidence.

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

Both authoring tools now recheck live cancellation, pause/emergency stop, permission and
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

Portable read-only fixtures cover full handle metadata, shared/linked reads,
exact layered slots, strict pagination and indexed reads at the million-point
budget, finite output, and matching official MCP schemas/forwarding. The native
fixture also includes read-only pages before and after the existing authoring
checks; results must be retained for the exact source being qualified.

Unit fixtures cover invalid input, shared/linked ownership, active layered-slot
selection, failure restoration and RNA-wrapper replacement. The disposable native
`animation_curves` runner case verifies independent Action binding, protected source
and unrelated channel preservation, linear/constant motion samples, explicit FREE
handles, context preservation and playback using an existing typed NLA strip.

The earlier authoring fixture passed on **Linux Blender 4.5.14 LTS and 5.2.2 LTS** in
`build/next-wave-animation-guard-native-20261022-final-2/report.json`. It includes measured
native compensation and late pause/permission/manual-key refusal; that historical
run predates `animation.curve_inspect`. Unit fixtures also
prove live stop/cancel/permission/toolset refusal, postwrite manual-key/consumer
interleaving, protected-channel preservation after native failure, and retained
allocations after authority or ownership changes. The earlier 4.3.2 evidence is
historical source evidence. Windows, production-scale/mixed-editor undo, curve
insertion/deletion and full character acceptance remain open. Run native fixtures
only through `scripts/run_blender_checks.py`.
