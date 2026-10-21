# Numeric rig controls and non-scripted bone drivers

Unreleased development tools; absent from published 0.3.0. They extend the existing
object-transform driver foundation with exact pose-bone targets and numeric object/pose-bone
properties. They do not expose raw RNA paths, driver expressions, arbitrary Python, files
or automatic saving.

## Workflow and public tools

1. Inspect the named rig/bones and protected objects; create a checkpoint before meaningful
   changes. `rig.property_inspect(object_name, property_name, bone_name?)` reads one exact
   stored numeric control without evaluating its dependencies.
2. Use `rig.property_set(object_name, property_name, value, bone_name?, create=false)`.
   Missing controls require explicit `create=true`. Omitting `bone_name` addresses an
   object property; naming it addresses that exact object's pose bone, not its shared
   armature rest data.
3. Add `rig.driver_add(object_name, bone_name, channel, variables, index=0,
   driver_type="AVERAGE")`. Targets are only `location`, `rotation_euler` or `scale`,
   component 0–2. New Euler targets require an Euler bone rotation mode. Types are the
   native non-scripted `AVERAGE`, `SUM`, `MIN` and `MAX` operations.
4. Inspect with `rig.driver_inspect` using the same exact target choices. Reinspect
   evaluated pose and skinned geometry independently; a created driver definition does
   not prove the desired deformation. Compare protected poses/meshes and capture a
   matched view when appearance matters.
5. Remove one exact reviewed target with `rig.driver_remove`; other channels are retained.
   Native checkpoint recovery remains explicit and finite.

Each variable declares `kind` and `object_name`, with optional `bone_name`:

| Kind | Additional choices | Native source |
| --- | --- | --- |
| `PROPERTY` | Exact `property_name`, already stored and numeric | `SINGLE_PROP` with a constructed, escaped object/pose-bone property path |
| `TRANSFORM` | `transform_type`: `LOC_X/Y/Z`, `ROT_X/Y/Z` or `SCALE_X/Y/Z`; optional `transform_space` (`TRANSFORM_SPACE` by default, or `LOCAL_SPACE`/`WORLD_SPACE`) | `TRANSFORMS` with an exact object/bone target |

Source paths are constructed from resolved names using quoted string literals. Existing
property paths are decoded as bounded JSON string choices and compared with the exact
constructed form; they are never evaluated or passed through reflective path resolution.
Quoted bone/property names are supported. Underscore-prefixed control names are reserved.
Numeric controls accept finite integers/floats, exclude booleans and have magnitude at
most 1,000,000. New control allocation is limited to owners below 128 custom properties.

## Ownership, dependencies and consent

Inspection requires `INSPECT_SCENE`. Mutations require live `EDIT_ANIMATION`, Object or
Pose Mode, local editable non-override object ownership and local armature data for bone
controls. The curves/properties belong to the object/pose; no shared rest-bone data is
edited implicitly. Direct consumers are inspected up to 100 datablocks; linked/read-only
consumers cause refusal. Responses list known direct affected object consumers and state
that transitive consumer preservation is unverified.

Dependency validation follows at most 32 objects, 256 pose bones and 128 drivers, with
one to eight variables per driver. It includes object/bone hierarchy and transform-source
edges. Static numeric properties are separate leaves, so a control property may drive
its own bone's transform without inventing a transform self-cycle. Transform self,
descendant and indirect cycles are refused before allocating a driver.

The current contract deliberately refuses active actions/NLA/tweak mode, object/pose
constraints, bone/vertex object parenting and existing scripted, custom-path,
self-dependent, keyframed/sampled or modifier-bearing drivers in the reviewed dependency
scope. Property sources must be stored numeric controls, not another driven custom path.
These restrictions are visible unsupported workflows; they do not establish complete
driver/IK/control-rig acceptance. Driver target state outside the reviewed scope and
whole-scene deformation still require further evidence.

## Failure and recovery

Permission, pause/stop and cancellation are checked before and after mutation. A numeric
property failure attempts to restore its prior value/absence. Driver creation owns only
its new curve and attempts scoped cleanup; it never overwrites an existing driver.
After the final control callback, a bounded callback-free preflight rechecks exact
object/data/pose identities, source identities, dependencies, consumer editability and
channel/property state immediately before allocation. Stale named replacements are refused.
Readback verifies driver type, variable kind/count/name, source identity, source path or
bone/transform settings. Default modifiers/variables on the newly allocated curve are
removed so the requested non-scripted operation has no implicit mapping layer.

Blender 4.5.14 creates a fresh SCRIPTED `0.0` driver with no variables/keys/samples and a
Generator modifier. Blender 5.2.2 instead supplies two BEZIER keys `(0,0)` and `(1,1)`,
AUTO_CLAMPED diagonal handles, LINEAR extrapolation and no modifiers. Before configuring
the explicitly requested non-scripted driver, the tool removes this reviewed diagonal
identity mapping **only from its new curve**. Recognition requires exactly those keys,
BEZIER/AUTO_CLAMPED settings, finite diagonal handles within +/-2 and LINEAR extrapolation.
Unexpected mappings or samples are retained with explicit failure evidence. Existing keyed
drivers, including an identical native identity mapping, remain unsupported and unchanged.
This does not add general F-curve mapping support or execute a supplied expression.

If permission is revoked after allocation, cleanup also respects that revocation. The
error reports `possible_mutation`, `rollback_verified` and any retained driver path/index.
Compensation also rechecks the exact owned write/configuration: a property changed by an
interleaved callback is retained, and a replaced or edited curve is never deleted as cleanup.
`cleanup_skipped=true` identifies a changed driver ownership/configuration requiring inspection.
Reinspect before retrying or explicitly removing the retained driver. A removal failure
does not claim that the previous driver was reconstructed; use measured inspection and
confirmed checkpoint recovery. No undo-capacity or durable-backup guarantee is implied.

## Development evidence

`tests/test_rig_drivers.py` covers typed metadata/wrappers, quoted names, bounded numeric
controls, dependency denial/cycles, local ownership, post-allocation cleanup/retention,
permission/pause/stop and exact channel removal.

The isolated `rig_drivers` fixture uses typed runtime calls to drive a pose bone from a
numeric control and an independent object transform. It independently verifies a two-unit
pose translation and complete displacement of three skinned vertices, then restores the
control and original geometry. A shared-armature-data object's pose remains unchanged.
It also checks quoted paths, descendant-cycle rejection and permission revocation with a
retained driver followed by explicit typed cleanup. It records the fresh native defaults,
verifies that normalization leaves no keys/samples/modifiers, and separately verifies
that a pre-existing keyed driver is rejected without changing its mapping or control.

Run through `scripts/run_blender_checks.py --case rig_drivers` with an explicit Blender
executable and unused evidence directory. Linux Blender 4.5.14 LTS and 5.2.2 development
evidence is at `build/rig-driver-normalization-20261022-2/report.json`; earlier 4.3.2 evidence
is at `build/rig-drivers-native-20261022-d/report.json`. Reports retain
`release_readiness=NOT_ASSESSED`. Windows 4.5/5.x, actual native undo,
action/constraint interleaving, production control rigs,
visual/deformation quality review and full character acceptance remain open.
