# Guarded timeline and keyframe editing

The existing four mutators keep their names, `EDIT_ANIMATION` permission,
defaults and result fields. This unreleased increment adds live gates, exact
ownership/context comparisons and independent post-state evidence. It does not
complete character or mixed-editor recovery acceptance.

## Timeline

`animation.set_frame(frame)` supports fractional frames within ±1,000,000. It
intentionally evaluates the whole scene, including native handlers, and reports
actual frame/subframe and measured native blocking time. The native call is
synchronous. A postwrite cancellation, revocation, pause, handler failure or
changed session reports both the observed and actual previous timeline. It never
replays a stale frame automatically or claims arbitrary handler effects were
undone. Reinspect before a new authorized request. This tool still creates no
automatic undo checkpoint.

`animation.set_range(start, end, use_preview=false, preview_start?, preview_end?)`
accepts playback bounds **0–1,000,000**, with end at least start, and preview bounds
inside that range. Earlier code accepted negative playback bounds that Blender
silently clamped; these now fail before mutation. Current frames may be negative.

Official Blender RNA and paired native probes prove that disabled preview setters
reset the opposite bound to the main range, while enabling an unset `(0, 0)`
preview initializes both bounds. The bridge predicts these exact effects, enables
preview before configuring bounds, and skips redundant setters. Deliberately
enabled `(0, 0)` previews remain intact. Arbitrary changes to another bound are
never adopted as an expected native effect.

Before every write and compensation, permission, toolset, cancellation, pause/
emergency stop, exact Scene/session/view layer/mode and every timeline field are
checked. Known local range failures can restore exact prior values while the
boundary remains valid. Manual edits or lost authority prevent stale compensation
and leave explicit possible-mutation evidence.

## Keyframe scope and evidence

`animation.keyframe_insert` and `animation.keyframe_delete` add optional
`affected_objects`. Omitted means an independent owner with no unaccounted
consumers. For a rig, enumerate its complete reviewed dependent-object closure,
such as skinned meshes, up to 32 objects including the target. Shared mesh data is
allowed for object transforms because the tools edit the object's Action. The
Action needs one real consumer; an additional fake user is allowed. Shared,
linked, overridden or read-only Actions and unsupported graphs fail closed.

Reviewed paths are own transforms, exact pose-bone transforms and existing finite
numeric custom controls. Bone names use canonical escaped paths and rotations
must match the current mode. Arbitrary shared-data RNA, sampled/asset-marked/
custom-property Actions and unclassified empty native Actions require broader
contracts. Bounds match [Action lifecycle](action-lifecycle.md). Insertion with
NLA tracks or active influence/blend conversion is refused pending independent
conversion evidence. Tweak mode and owner drivers are refused. Cycle-aware keys
with cyclic modifiers require an explicit mapped-frame contract before mutation.

The bridge checks exact object/data/Action identities, slots, source values,
consumers, protected channels/groups (including nested custom colors), NLA context
and timeline. A new native Action must have one OBJECT slot/layer/keyframe strip/
channelbag, only requested channels/frames, accounted users and no fake retention.
Changes made during the completion authority callbacks invalidate its observed
content/binding and prevent further writes.

Successful nonvisual insertion independently verifies eligible frame/components
and numeric values. Deletion verifies their absence. `requested_keyframes` is
complete for at most four components and independent of the older truncated
general curve preview. Conditional `AVAILABLE`, `REPLACE` and `NEEDED` options can
omit components; the result reports `requested_keyframes_complete=false` and
explicit `conditional_component_omissions`. Refine when the brief requires all
components. `INSERTKEY_VISUAL` verifies key presence but truthfully reports
`requested_key_values_verified=false`; its evaluated conversion still needs
independent workflow verification.

Native errors and postwrite cancellation retain observed data and the logical
checkpoint. No blind key/Action recreation or compensation is attempted. Inspect
the reported Action before a new typed correction or confirmed checkpoint recovery.
Retained Actions and undo are not durable backups; these calls never save a file.

## Development verification

`build/next-wave-animation-guard-native-20261022-final-2/report.json` runs `rig`,
`animation_curves`, phased `action_lifecycle` and `animation_mutations` on Linux
Blender **4.5.14 LTS** and **5.2.2 LTS**. Coverage includes native preview/zero-range
behavior, four live stops, measured range compensation, requested keys/values,
protected channels/groups/colors, conditional omissions, and explicit later typed
correction after cancellation. Rig scope preserves the exact current-Scene
particle-edit context reference while rejecting an extra sculpt gravity reference.

`build/next-wave-animation-preview-rna-20261022.json` retains official source
references. These development reports identify dirty source; the eventual clean
wave must retain its own commit, hashes and complete matrix. Windows, interactive
native undo/manual interleaving, constrained memory, broader rigging-handler
safety and full character/visual acceptance remain open. Use only the isolated
native runner.
