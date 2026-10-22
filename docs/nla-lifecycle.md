# Bounded NLA lifecycle

The development registry adds four typed tools in the `animation_layers` toolset.
They require live `EDIT_ANIMATION` consent inside Blender and participate in automatic
logical checkpoints and operation history. They never save a project or edit Action
channels. Raw Python remains disabled by default.

| Tool | Explicit operation |
| --- | --- |
| `nla.clip_add` | Add one named existing Action/slot as a new clip in an existing unlocked track, at an integral start frame. Reject overlap, implicit trimming and channel mapping. |
| `nla.transition_add` | Create one real native `TRANSITION` over the positive gap between the named adjacent left/right clips. |
| `nla.transition_remove` | With `confirm=true`, remove exactly the named transition between those neighbors. Preserve the neighboring clip identities and Action content. |
| `nla.track_reorder` | Apply the complete, unique, bottom-to-top track-name permutation while preserving the native track and strip identities. |

Every call requires `object_name` and an explicit `affected_objects` list containing the
complete reviewed object dependency closure, excluding the target itself. An empty list
means that no other object consumes the target beyond ordinary scene/collection ownership.
The target must be a local editable object in one current scene/view layer, in Object Mode,
with NLA enabled and no tweak mode or drivers. Linked/override targets and dependencies
outside the declared closure fail before writes. Shared Actions are read and their complete
bounded content and reference counts are preserved; a clip binding validates its own-object
transform or exact numeric-control channels and suitable explicit OBJECT slot.

Transitions and track ordering require an **existing NLA Editor in the current window**.
The tools select their exact owner/tracks/strips only temporarily, restrict the editor to
selected objects, and restore the previous selection, active object/track, strip flags and
editor filter after successful execution. They never change an editor's type. Background
mode or a missing editor returns `NOT_IMPLEMENTED` without creating a transition or moving
tracks. Clip insertion and exact transition removal use the native data API.

The reviewed scope is at most 16 tracks, 64 total strips, 16 scoped Actions, 32 initially
selected objects, 256 current-scene/view-layer objects and 31 declared dependent objects.
Clip lookup scans at most 1,024 available Actions. Only CLIP/TRANSITION strips are supported;
META/SOUND strips, nested strips and strip modifiers require a broader contract. Strip
controls preserve the complete content and identities of unique `influence`/`strip_time`
F-Curves, with at most 256 keys per curve, bounded modifiers and no drivers or sampled points.
Action bounds are enforced by the shared animation content reader. New clips require a
positive integral source range of at most 100,000 frames, within +/-100,000, and one suitable
explicit OBJECT slot for layered Actions.

## Legacy structured NLA endpoints

`nla.add_strip`, `nla.edit_strip`, `nla.edit_track`, `nla.solo_track` and `nla.push_down` retain
their existing request fields. Their Blender handlers now require a live ToolContext and
recheck consent, cancellation/disconnect, pause/stop, session/ID identity, object consumers,
Action/slot/content/user counts, timing, selection and exact known partial state before
**each** write and compensating write. All five accept the optional `affected_objects`
list with the same complete reviewed object dependency closure as the four lifecycle
tools. Omission preserves the previous single-target scope: an undeclared skin, child or
other object consumer is refused. A complete explicit skin closure permits the first
character track through `nla.push_down` or `nla.add_strip`; both create a nonempty track
and its first clip in one logical operation. No empty-track endpoint is required.

`nla.push_down` also accepts optional `expected_action_name`. When supplied, the exact
current active Action must match before allocation. Omission preserves the existing
request behavior. Both additive fields are forwarded by the typed MCP wrappers, and
successful edits enumerate the target and its declared affected objects.

The reviewed isolated strip setters preserve native float storage and timing aliases,
source range, scale/repeat, blend durations and control curves. They preflight every requested
intermediate stage before the first write. Automatic blending is modeled across the bounded
owner's tracks, including native transition validation; a request that would rewrite another
strip's blends or repair/remove a transition returns `NOT_IMPLEMENTED` before the setter.
For example, enabling `use_auto_blend` on one clip cannot silently overwrite a manually tweaked
blend on its adjacent track. Ordinary automatic blending confined to the requested strip is
supported. Source ranges and resulting extents must remain ordered, at least one frame long
and within +/-100,000; implicit native clamping is rejected.

`settings={"use_animated_influence": true}` remains supported after demonstrating its native
behavior on both development runtimes. A new control is exactly one private `influence`
F-Curve with one key at the strip's start/current influence, using the existing interpolation,
handle and smoothing preferences. The complete fresh constructor is verified before adopting
it into the known state. Disabling the flag **retains the curve**; enabling it again reuses
that same curve and content. It does not edit those control keyframes. An incomplete animated-
time control scope, unknown constructor shape or missing native preference evidence fails
closed. These are explicit unsupported contexts, not completed general NLA control authoring.

New clip/track constructors are validated against reviewed native defaults. An allocation
that acquires foreign settings or consumers is retained and reported instead of deleted.
On a failed first allocation, an empty newly created AnimData may also remain; its presence
is reported and does not count as verified full rollback. Push-down retains the identity
proof for a fully verified private strip constructor before returning that strip to its
caller. A failure immediately after that boundary can therefore remove the exact owned
track/strip and measure complete restoration. Unverified or foreign allocations remain
available for reinspection instead of being deleted by assumption.

## Recovery and development evidence

Compensation occurs only while live consent and the exact known partial scope still match.
A changed consumer, manual edit, replaced ID, cancellation, permission denial or stop state
prevents further compensating writes. Error evidence identifies retained strip/track/control
state where it can be measured, sets `possible_mutation`, and claims `rollback_verified` only
when the original complete scoped state is measured again. Retaining a newly allocated
control curve while restoring its flag is not complete rollback. Removing a transition uses
its finalized native checkpoint for recovery; the tool does not recreate a new strip and
claim its original identity survived. Native undo is session recovery, not a durable backup.

The isolated UI fixture `nla_lifecycle` exercises all four new APIs and all five legacy NLA
endpoints. Paired Linux Blender 4.5.14 LTS and 5.2.2 LTS runs demonstrate real transition motion
at x=0/5/10, complete track permutation, shared Action preservation, protection of another
initially selected animated owner, exact timing/blending, custom-preference influence controls,
late permission revocation without unauthorized cleanup, an injected native move failure with
measured compensation, refusal of a last-provider native Object-to-Pose mode switch before
clip allocation, and native checkpoint recovery after transition removal. The separate
`nla_lifecycle_probe` records raw native APIs and constructor facts.

Run both only through the [isolated native runner](native-testing.md). Development reports
and failed iterations are retained under `build/next-wave-nla-*`; the combined focused report
is `build/next-wave-nla-final-20261022-6/report.json`. These disposable Linux scenes do not prove
Windows isolation, an installed package, an artist-reviewed character/deformation benchmark,
or complete release acceptance. The [character NLA fixture](character-nla.md) separately
demonstrates bounded fresh-process character/NLA persistence. Remaining requirements stay
in the [1.0 readiness ledger](release-1.0-readiness.md).
