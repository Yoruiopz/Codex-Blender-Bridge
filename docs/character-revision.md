# Character weight repair and IK reach revision

The opt-in `character_revision` fixture joins the existing weight, IK, Action and
deformation tools into one bounded character task. Its brief is to repair a poor
elbow-weight patch, revise a two-bone reach and animate the independent target
while preserving a second character. This is a development benchmark contract;
source-matched native reports and reviewed captures are required before claiming
that a particular source passes it.

## Ordered authoring

The fixture starts with a named two-bone limb, one unconstrained protected limb,
a small plain skinned mesh, explicit UVs/materials and a locked detail group.
Independent Empty objects serve as the target and pole. A separately animated
rig and skin share the local rest Armature data and form the protected scope.
Raw construction, independent observations and fixture-only camera rendering are
labeled separately from artist edits through the registered tools.

The sequence uses these existing interfaces:

1. `rig.deformation_inspect` records the poor weight patch and current-frame
   geometry, weights, joints and target distance.
2. `rig.ik_configure` configures the active two-bone limb while the rig, target,
   pole and skin remain static. Its exact skin scope is supplied explicitly.
3. `weights.brush_stroke` repairs explicit memberships in the elbow patch. Both
   deform groups have known expected values; the locked detail group, other
   vertices and protected objects remain outside the edit.
4. `transform.set` moves the target through reachable poses. Repeated deformation
   inspections and matched renders compare the broken and corrected elbow.
5. `animation.action_create`, `animation.action_bind`,
   `animation.keyframe_insert` and `animation.curve_edit` author the independent
   target's motion, with the constrained rig and its skin explicitly declared as
   affected objects. `animation.curve_inspect` and `animation.curve_sample` inspect
   stored interpolation while that Action is active.
6. Current-frame deformation inspection checks ordinary timeline samples. The
   protected animated alias is compared with its own baseline at each matching
   frame; preservation does not mean freezing its evaluated pose across time.

This order respects the existing IK contract. Configuring or removing IK after
its target has an Action, driver or NLA remains unsupported. Only one exact IK
constraint per rig is accepted. This benchmark neither relaxes those guards nor
establishes bilateral or general production control-rig authoring.

## Evidence and refusals

The completion gate requires every bounded skin vertex to match an independent
linear-blend-skinning oracle using rest geometry, memberships and bone transforms.
Endpoint distance, rest lengths and elbow-plane direction are checked separately
so matching the skinning formula does not by itself certify the IK solution.
Complete protected rest bones, geometry, weights/group locks, UVs, materials,
bindings, Actions and NLA state are compared with their declared baselines.

Permission and locked-group refusals must preserve measured data. An admitted IK
post-write failure is exercised while its scope is still static: known writable
configuration and native constraint identity are measured after compensation.
That bounded local restoration is separate from native global undo, manual undo
interleaving or a durable backup.

The fixture retains matched 512 by 512 camera images of relevant repair and reach
poses. Raw pixels, source identity, evidence hashes and independent numerical
measurements must be retained. Captures require review; their existence alone
does not accept silhouette, elbow quality or production artistic intent.
Owned raw setup is settled before measurement, and stored selection flags are
observed without relying on a selected-object getter as a preservation shortcut.

Run only through the [isolated native runner](native-testing.md), selecting
`--case character_revision`, explicit Blender executables and a new output
directory. The case uses a disposable background process and fixture-only camera
renders. It does not enter the artist's Blender session, serialize a project,
invoke public `project.save` or establish fresh-process persistence. Safe native
project saving remains [unavailable](project-save-safety.md).

## Qualification boundary

The existing [character NLA fixture](character-nla.md) separately covers its
admitted pose-Action/NLA, transition, track-ordering and fixture-persistence path.
The new revision benchmark adds a weight-repair and animated-target combination;
it does not replace that evidence or expand a narrower tool contract implicitly.

The registry remains **265 MCP tools**, with components **0.3.0 alpha**. This
increment adds no API or protocol version. Full CHAR-01, complete ownership and
recovery audits, larger production characters, constrained-memory/manual-editor
work, installed scenarios A–F, native undo, durable recovery and artistic
acceptance remain open. Windows testing remains paused. All fourteen release
requirements remain OPEN in the [readiness ledger](release-1.0-readiness.md).
