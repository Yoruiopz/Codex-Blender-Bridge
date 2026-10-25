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

## Edit existing raw point fields

`animation.curve_edit(object_name, data_path, index=0, keyframes?, extrapolation?,
slot_identifier?, affected_objects?)` retains its existing public parameters. The
first admitted writer profile is **`RAW_FREE_POINT_V1`**: raw `co`, `handle_left`
and `handle_right` Float2 assignments on existing keys. This is a bounded
implementation increment; full curve authoring remains required for 1.0.

Each of at most 256 `keyframes` entries names one distinct existing `frame` and may
supply `co=[frame, value]`, `handle_left=[x, y]` or `handle_right=[x, y]`. The optional
`co` field is additive. Its MCP schema requires an exact two-element array of
finite numbers within ±1,000,000, rejecting booleans, numeric strings and malformed
arrays. Blender independently checks every input and requires the Float32-rounded
`co.x` bits to equal the selected key's original frame bits, including signed zero.
This profile changes values, not key times. A raw `co` assignment leaves handles
unchanged unless their fields are explicitly requested. `co_ui` is a separately
compared native read alias of `co`; it is never used as a setter.

The existing `interpolation`, `easing`, `handle_left_type`, `handle_right_type` and
`extrapolation` parameters remain in the public schema for compatibility. Valid
requests for any of them return `NOT_IMPLEMENTED` before point operations,
including requests that match the source value. Malformed enum values retain
`INVALID_ARGUMENT`. Do not include `handle_left_type="FREE"` or
`handle_right_type="FREE"` to authorize coordinates: both handles must already be
FREE. No keys, channels, slots or Actions are inserted or recreated by this tool.

### Source and context admitted by the first profile

This profile admits only the source-reviewed official **Linux Blender 4.5.14 LTS**
(build `62c1db4208e8`) and **Linux Blender 5.2.2 LTS** (build `d13f752e3b9c`). An exact
build match is an admission condition, not native qualification of this writer.
Other builds and platforms return `NOT_IMPLEMENTED`; Windows qualification is
deferred.

The named owner must be a local editable nonoverride Empty with no data block,
parent, constraints, modifiers, instancing or custom properties, directly owned by
the sole Scene's master collection and visible in its sole ViewLayer. Its active
Action must be local, editable, unshared and nonoverride, with an ordinary REPLACE
binding at full influence and no NLA tracks, drivers or tweak mode. Layered Actions
require the assigned OBJECT slot; an explicit `slot_identifier` must match it.
The target curve and all channels in the assigned slot must address `location`,
`rotation_euler` or `scale`, index 0–2, with XYZ rotation mode. Pose-bone, custom
control and arbitrary RNA channels need separate authoring profiles.

The current scene time must already equal an existing key on every admitted active
slot curve, and each raw Object channel must match that key's Float32 value.
A `co` edit that revises the current key's value is refused. The first native case
can therefore revise a future key while retaining an unchanged current key and
pose. Current-frame value revision and broader dirty/evaluated contexts remain
unqualified; the writer never adopts a changed Object projection as a new baseline.

Object Mode and a **separate existing unanimated active Empty** are required for the
normal checkpoint. The named animated owner may be unselected. A previous weak
checkpoint owner must also meet the bounded static Empty witness. A genuine
checkpoint/setup before intent capture is allowed; automatic checkpoints remain
enabled. Context acquisition after intent capture must preserve the original
compared source. Only the canonical completed checkpoint push advances the
source-reviewed ParticleEdit weak role.

The ordinary profile also requires exactly one Scene, ViewLayer, WindowManager
and Window, bounded local nonoverride Main IDs, no linked-library or Text roots,
no unrelated or embedded animation, and no admitted frame/dependency callbacks.
Main is limited to 256 IDs, 128 Objects and 16 Actions. Each admitted Action has at
most 32 curves and 1,024 total keyframes; sampled points, modifiers, drivers,
asset-marked Actions and Action custom properties are refused. External affected
consumers are unsupported, so `affected_objects` must be empty. These restrictions
are local to this writer, not global permission or inspection changes.

Every point on the selected curve must already have two FREE handles, finite exact
Float32 coordinates within ±1,000,000, reviewed interpolation/easing values, and
strictly increasing times. Stored or requested subnormal coordinates require a
separate qualification. Adjacent key times must have a Float32-rounded subtraction
greater than the exact native `0.01f` threshold (little-endian bytes `0ad7233c`).
Equality can merge keys; a Python-double gap greater than `0.01` is insufficient.
Source and independently rounded requested handles must bracket their key:
`left.x <= key.x <= right.x`. Crossing or swapped handles are refused rather than
clamped or swapped. The writer issues **no `FCurve.update`, sort, extrapolation
setter or `co_ui` setter**. Full update and extrapolation can relocate point storage
on the reviewed official builds; they require a separate owned-transition and
recovery contract.

### Preservation, lifecycle and recovery

The registered admission factory retains the original bounded request, canonical
ordinary Runtime/Executor/provider services, permissions, cancellation hooks,
Object/Action session identities, assigned slot, curve/point identities and the
complete declared Action and preservation scope before providers or checkpoint
writes. This profile is standalone: `batch.plan`/`batch.execute` refuse this
nonbatchable writer. Protected task-scope enforcement needs separate qualification;
this first profile requires advisory task scope. The existing structured-mutation
lease remains held through entry, editing, recovery and checkpoint finalization.

A pure kernel independently predicts the complete Action prefix for every Float32
field assignment, including the `co_ui` read alias. Untouched values, scalar types,
signed zeros, metadata, other channels and descendant identities remain compared.
Fresh owner membership and point facts are checked before canonical native calls;
point/vector wrappers and the callable's native owner are released before the next
provider boundary. Neither native output nor a post-checkpoint observation becomes
a new expected baseline.

Cancellation, disconnect, deadline, permission/toolset changes, pause/stop, changed
bindings/consumers/context or replaced services stop later writes. The first refusal
remains sticky. A setter is recorded as attempted before entry. A native exception
can have effects: recovery may reverse only an independently verified attempted
prefix under current authority, through the same raw field path. Unknown state,
manual interleaving or lost authority retains effects and reports refusal instead
of overwriting newer work. No recovery recreates keys, channels or Actions.

Success and failure carry flat typed `recovery_evidence` with
`kind=curve_mutation`: original IDs, selector, stage, attempted/verified field and
update counts, original/requested/observed digests, known/partial-state flags and
restoration refusal. Native update counts remain zero in this profile. These
observations grant no restore authority and retain no native handles, buffers or
intent prefixes in history. Inspection denial redacts the recovery payload under
the existing policy. A compared rollback is not native undo availability or a
durable backup. The writer never saves.

Results identify `authored_profile=RAW_FREE_POINT_V1` and disclose
`context_sync_possible=true`, `current_pose_revision_qualified=false`,
`persistent_non_ID_identity_qualified=false` and
`complete_hidden_state_qualified=false`. The ordinary trusted synchronous leaf is
not an arbitrary in-process Python sandbox, a persistent non-ID/ABA identity
guarantee or proof that every native hidden/runtime field is unchanged.

The pure snapshot retains its existing 65,536-item, depth-32, 4,096-byte-string and
1,537-step budgets. Items multiplied by field steps must not exceed 2,097,152;
existing request budgets also apply. Work can be refused below the point limits.
Native allocation, reads, ownership scans, checkpoints and individual setters can
block until return. This synchronous increment adds no job, hard memory cap or
latency guarantee.

`action_copy` retains its separate allocation/binding contract: a failed copy
retains its allocation and delegates measured binding recovery to Action lifecycle;
it does not blindly rebind a protected source or delete a retained copy. Its
`affected_objects` scope retains the separate bounded consumer-closure rules.

## Verification and remaining limits

Portable inspection/sampling fixtures cover read-only selectors, pagination,
metadata and bounded numeric evaluation. The new point-intent models cover strict
source/request admission, independent complete Float32 prefixes, signed zero,
`co`/`co_ui` alias preservation, no-op classification and inverse-prefix direction.
MCP schema fixtures exercise optional Float2 validation and preserve the existing
forwarding envelope, including retained unsupported enum parameters. These checks
do not prove a native registered write or checkpoint recovery.

The earlier authoring fixture passed on **Linux Blender 4.5.14 LTS and 5.2.2 LTS** in
`build/next-wave-animation-guard-native-20261022-final-2/report.json`. That historical
run predates the retained-intent writer. A separate native RNA probe observed raw
`co`/left/right calls preserve measured point addresses and extrapolation/full
update relocate them on both exact builds. Neither result qualifies this new
registered writer, its lifecycle or its recovery. Exact-source native evidence must
be retained for the point-only profile before release acceptance, including sampled
values, full authored/preservation comparisons, genuine checkpoints, denial,
invalid context, injected failures, manual interleaving and measured recovery.
Run native fixtures only through `scripts/run_blender_checks.py`.

Current-frame curves, interpolation/easing, all handle modes/conversion,
extrapolation/full-update ownership, broader rigs/controls, curve insertion/deletion,
Action/NLA workflows, mixed manual/bridge undo, production memory/latency and full
character acceptance remain mandatory work. Windows compatibility/testing remains
deferred. This increment does not complete H05/C03 or qualify 1.0.
