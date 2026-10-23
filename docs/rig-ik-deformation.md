# Two-bone IK and current-frame deformation evidence

These unreleased structured tools connect an explicit limb IK revision to measured pose
and skin motion. They are a bounded character foundation. Robust production control rigs,
combined Action/NLA revisions, visual character benchmarks, native undo acceptance and the
full CHARACTER requirement remain open. They do not imply 1.0 readiness.

## Workflow

1. Inspect the scene, named armature, bones, target controls and skin. Resolve any selection
   references before editing. Create an explicit logical checkpoint for the limb revision.
2. Use existing `object.create` with `object_type="EMPTY"` for separately named target and
   pole controls if needed. Their transforms must be independent: no parenting, object
   constraints, actions, drivers or NLA. Creating these controls is a separate explicit edit.
3. Call `rig.deformation_inspect` for the current frame, explicit bones and sampled vertices.
   Retain the endpoint distance, vertex positions, weight observations and protected scope.
4. Call `rig.ik_configure` with exact root/tip/control/constraint names and **every** mesh
   consuming the armature. Missing constraints require `create=true`; updates require
   `create=false`. The target and pole are existing objects and are never allocated implicitly.
5. Inspect the stored constraint, then repeat the deformation measurement. Compare actual
   endpoint and skin changes, and recheck protected limbs/data. Use a matched viewport or
   render to judge elbow direction, silhouette and deformation quality.
6. Move an explicit control through existing structured transforms when requested, then
   remeasure the rig and skin. The control transform needs its own transform permission.
   Save only when requested and authorized. None of these new tools saves a project.

For a limb named `Upper.L` → `Lower.L`:

```json
{
  "object_name": "CharacterRig",
  "root_bone_name": "Upper.L",
  "tip_bone_name": "Lower.L",
  "target_object": "HandTarget.L",
  "pole_object": "ElbowPole.L",
  "affected_meshes": ["CharacterSkin"],
  "constraint_name": "Arm IK.L",
  "create": true,
  "pole_angle": 0.0,
  "influence": 1.0,
  "iterations": 128,
  "use_stretch": false
}
```

Angles are radians. Native IK is iterative; a configured constraint is not proof that the
endpoint reaches a target or that the result meets the brief.

## Tools and consent

| Tool | Required permission | Contract |
| --- | --- | --- |
| `rig.ik_inspect` | `INSPECT_SCENE` | Read one exact tip-bone IK constraint's stored settings. |
| `rig.ik_configure` | `EDIT_ANIMATION` | Create or update one connected two-bone branch, using explicit independent Empty target/pole controls and skin scope. |
| `rig.ik_remove` | `EDIT_ANIMATION`, `DELETE_OBJECTS` | Remove one exact scoped IK constraint after `confirm=true`; never delete its controls, bones or skins. |
| `rig.deformation_inspect` | `INSPECT_SCENE` | Read current-frame evaluated pose/skin and bounded numeric diagnostics, without changing frame, weights, modifiers or pose. |

The `rigging` toolset must be enabled independently of Blender permissions. Configure and
remove use normal operation history/checkpoints. Every forward and compensating write
rechecks cancellation, toolset availability, pause/emergency state, live consent, session
identity, explicit scene/container scope, current direct users and the frozen constraint.

## IK subset and ownership

The armature has at most 256 pose bones and uses Blender's legacy IK solver in Pose Position.
The root has exactly the connected tip child, and the tip has no children. Both rest lengths
exceed `0.000001`; Bendy Bone segments and other pose constraints are outside this contract.
The solver chain is fixed at two bones, targeting the tip tail. Location solving is enabled,
rotation targeting disabled, and the constraint unmuted. Settings are bounded to influence
`0..1`, pole angle `-pi..pi`, and `1..512` iterations; stretch is an explicit boolean.
Existing IK uses COPY_POSE, these controls or unbound target slots, no bone subtargets and
no custom owner/target space. Retargeting a different bound control is rejected.

Mutation requires Object Mode without changing mode or selection. The rig, controls and
listed skins are local, editable, non-override objects in the current view layer and one
scene, without shared/instanced collection ancestry, object parents/constraints, actions,
drivers or NLA. Up to eight distinct explicit skins are accepted. Each skin has one plain
vertex-group armature modifier targeting this rig: no envelopes, preserve-volume mode,
modifier masks or multi-modifier blending. Unexpected incoming references fail before
writing. Scene lookup is bounded to 65,536 objects and direct users to 256 per object.

Pose constraints belong to the armature **object**. Sharing its local rest Armature data
does not itself prohibit this tool: no rest data is written, and another object's pose
remains independent. The guards freeze native object/data/bone identities, rest basis and
reviewed inheritance settings, raw pose/IK channels, control matrices and skin bindings.
They do not claim a complete transitive dependency graph or whole-scene preservation.
Use explicit structural comparisons for broader protected geometry, weights and materials.

Native writable IK properties are inventoried for compare-before-write/recovery, including
properties beyond the exposed authoring fields. Unknown property kinds, excessive inventory
or custom-property-bearing constraints fail closed. The native target/control names are
returned; requested names must fit Blender's 63-byte UTF-8 limit.

## Failure and recovery

Existing-constraint updates restore attempted settings only while the exact constraint and
its complete expected writable configuration still match the operation's output. A new or
externally edited constraint is retained, with recovery evidence. A created constraint can
be removed during compensation only with current animation **and deletion** consent; cancel,
pause, emergency stop, changed references or revoked consent can require explicit recovery.

A native allocation that raises before returning a handle may have retained an unknown
constraint. Such failures report possible mutation and bounded observed tip-constraint names;
they do not guess ownership or silently delete an allocation. Inspect before retrying.
`rollback_verified=false` and `cleanup_skipped=true` mean automatic recovery was not proven.

Confirmed removal is not automatically reversed by rebuilding a similar constraint: that
would change its identity and could overwrite newer work. Failed removal reports the known
return/presence evidence. Native checkpoint recovery remains a separate explicit action,
with the global-undo/interleaving limitations in [native recovery](native-recovery.md).

## Deformation measurements

`rig.deformation_inspect` takes one armature, one skin, 1–32 exact bone names, 1–256 distinct
vertex indices and explicit `coordinate_space="LOCAL"` or `"WORLD"`. Optional
`target_object` and `tip_bone_name` are supplied together. The endpoint-to-target metric always
uses world space. LOCAL geometry is **mesh-local**, while LOCAL bone positions are
**armature-local**; the response names both coordinate frames.

The inspector supports Object/Pose Mode with the skin in Object Mode, one enabled plain
armature modifier and no shape keys or additional modifiers. Pose-constraint snapshots
currently support IK only, up to 128 constraints. Mesh limits are 4,096 vertices, 8,192 edges,
4,096 faces, 16,384 loops/base triangles, 128 vertex groups and 65,536 memberships.
Evaluated vertex count, indexed edges and polygon correspondence must match the base mesh
before any vertex mapping is reported. Every temporary evaluated mesh is released on success
or failure. Source identity, frame, base geometry/weights, raw pose and reviewed IK metadata
are rechecked around evaluation; this is not a full animated dependency certificate.

The response includes:

- Actual evaluated heads/tails, lengths, unsigned parent-axis bend angles, degenerate bone
  observations and stored native IK lock/limit ranges. Limit satisfaction is **not assessed**;
  an unsigned bend angle is not a local Euler joint-limit comparison.
- Base/evaluated vertex positions and displacement in the declared space; endpoint distance
  uses the **evaluated** rig and target, rather than raw pose channels.
- Sampled memberships, locked flags, unmatched/non-deforming groups, deform-only weight sums,
  unweighted vertices and a declared influence-count threshold. `max_influences` is `1..16`
  (default 4), and `weight_tolerance` is `0..0.1` (default `0.0001`). Extra detail groups do not
  count toward deform normalization. A sum differing from one is an observation, not proof
  of poor Blender deformation.
- Whole bounded-mesh edge-length ratios and degenerate edge counts, plus area/degeneracy of
  the **base triangulation** measured in both states. These are not self-intersection,
  collision, flipped-face or artistic-quality certificates.

`quality_verdict` remains `NOT_ASSESSED`. Inspect matched visual evidence and the brief
before accepting a character revision. The tools do not sample a timeline, construct a
complete control rig, repair joint limits, normalize weights or manage Action/NLA lifecycle.

## Native evidence

The disposable `rig_ik` case runs through `scripts/run_blender_checks.py`. A native behavior
probe preceded the mutation contract. The typed fixture then repairs a one-bone chain,
checks endpoint distance and pole-plane reversal, reads actual skin displacement and
deform-only weights, preserves a separate limb and a shared-rest-data rig alias, verifies
permission denial and owned failure compensation, and exercises explicit create/update/remove.

Current development evidence passes on Linux Blender 4.3.2, 4.5.14 LTS and 5.2.2. This is
factory-startup evidence for this subset. Windows 11, installed-package scenarios, native
undo, production character/visual acceptance and the complete CHARACTER gate remain open;
see the [full release gates](release-1.0-readiness.md).

The separate [character revision benchmark](character-revision.md) defines an
ordered static-IK → weight-repair → target-Action path with protected sampled
deformation and matched visual evidence. Its source-matched native proof remains
a separate requirement; it does not relax this tool's static mutation scope or
establish general animated-control IK revision.
