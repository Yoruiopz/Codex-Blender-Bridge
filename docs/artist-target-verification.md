# Explicit target-channel verification for artist plans

`task.plan.verify_transform(step_id, receipt_id, expected_revision)` compares a
step-linked transform preview's intended authored core channels with its exact
target after application. The expected values are retained before the edit;
verification does not adopt the handler's output as its expected result.

This is a separate observation from `task.plan.compare`, which compares protected
objects. A matching target observation neither completes a step nor verifies an
artistic goal. It always reports `user_goal_verified=false`.

## Ordered use

1. Create a plan step and resolve the intended object through the existing
   reference workflow.
2. Call `task.plan.preview_transform` with that `step_id` and inspect the preview.
3. Apply that exact preview using `task.plan.apply_preview`. Retain the returned
   `step_receipt_id`; it identifies the finalized outer operation, not a client
   request ID or an undo token.
4. Inspect the current plan revision, then explicitly call
   `task.plan.verify_transform` with the step, receipt and revision.
5. Inspect protected data separately and obtain structural/visual evidence for
   any goal beyond the compared core channels. Refine through a new preview when
   the observed result does not meet the brief.

The three required arguments are bounded: `step_id` is 1–64 ASCII letters,
digits, underscores or hyphens; `receipt_id` is `step_receipt_` followed by 32
lowercase hexadecimal digits; `expected_revision` is an integer from 1 to
1,000,000,000. Booleans, numeric strings and floating-point revisions are rejected.

## Compared channels and expectation profile

The first profile compares these six fields, including untouched inactive
rotation representations:

| Field | Compared value |
| --- | --- |
| `location` | Three authored Float32 components |
| `rotation_mode` | Exact mode identifier |
| `rotation_euler` | Three authored Float32 components |
| `rotation_quaternion` | Four authored Float32 components |
| `rotation_axis_angle` | Four authored Float32 components |
| `scale` | Three authored Float32 components |

Requested assignments are predicted independently using IEEE Float32 storage;
comparison preserves signed zero and includes explicit bit encodings. Unassigned
channels retain their pre-edit expectation. No tolerance permits a different
stored channel value to be accepted as an exact match.

A step-linked preview exposes this retained profile as `target_expectation`;
unassociated previews retain their existing behavior and return no step
expectation. Receipt inspection exposes the same independently retained intent,
including an explicit reason when its verification profile is unavailable.

The qualified expectation profile requires an unchanged rotation mode and finite
component magnitudes at most 1,000,000. Every nonzero original/requested
Float32-effective component must have magnitude at least `2^-126`; exact positive
and negative zero remain supported. Requested values and their independently
rounded values must fit the native descriptor's hard range without clamping.
Location and scale edits can be observed in any existing mode; Euler assignments
require that the target already uses that same Euler mode. Rotation-mode
conversion and unqualified numeric/clamping cases retain an unavailable
expectation reason. Verification then returns `NOT_IMPLEMENTED` before reading
target channels. For existing location, Euler, scale and mode inputs, an
unavailable verification profile does not narrow their preview/apply contract.

### Quaternion assignment expectations

`transform.set` and `task.plan.preview_transform` accept an optional
`rotation_quaternion=[W, X, Y, Z]` for a target already in `QUATERNION` mode. Omit
Euler `rotation`, the setter's legacy `rotation_euler` alias and `rotation_mode`
when supplying it. No normalization, mode conversion or sign
canonicalization occurs. The independently predicted Float32 components remain
the expected authored result; equivalent quaternion signs are not treated as
identical stored channels.

The new field has a narrower [mutation profile](object-rna-safety.md#quaternion-assignments).
Both requested and independently rounded quaternions must have a Euclidean norm
within `1e-6` of one. Components must be finite and within `[-1, 1]`; raw and
rounded nonzero magnitudes must be at least `2^-126`, while either signed zero is
supported. Existing location, Euler, scale and mode inputs retain their previous
contracts. Verification still compares all six core fields, including inactive
Euler/axis-angle channels; it does not certify evaluated orientation,
deformation, appearance, the artistic goal or durable recovery.

The new quaternion field additionally requires a complete qualified immutable
intent for all six core channels before writing. Captured original/requested
numeric components must meet the normal Float32/signed-zero profile, magnitude
limit of 1,000,000 and native hard-range checks above. An unavailable intent
returns `NOT_IMPLEMENTED` before assignment; the new field cannot proceed by
leaving target verification unavailable.

The expectation's numeric limits qualify the captured original/requested values. Later
manual drift to a finite native Float32 value outside that expectation range can
still be reported as `channels_differ` when the static reader remains supported.
The observer does not silently adopt that drift as the expected result.

These are authored **core-channel** observations. Delta transforms, parenting,
parent-inverse matrices, evaluated/world transforms, dependencies, geometry,
materials, composition and appearance require separate evidence. Resolving the
frozen name through Blender's Object datablocks does not establish membership in
the current scene or view layer.

## Provenance and result states

Only the named step's latest retained successful, completed outer receipt in the
current runtime generation is eligible. Failed/rejected, evicted, historical or
superseded receipts refuse. A later bridge writer, native undo/redo generation,
plan replacement/load/reset, changed step description or changed intent also
prevents attachment. Status/note corrections before the call remain compatible
when the step's provenance survives; the caller must provide the current plan
revision.

The executor freezes verification provenance before entry permission providers.
After live permission/cancellation checks, and again after native reads, it
requires the same runtime store, epoch, generation, plan revision, step, receipt,
operation, immutable intent and completed mutation revision. Verification refuses
an executing mutator, an applying preview or an active background job.

The reader validates the retained native Object identity and fixed native RNA
descriptors before reading fields. It uses no context/selection getter, view-layer
update, dependency-graph evaluation or `matrix_world` read. Missing or replaced
targets are reported before their channel values could become a new baseline.

The response contains the step, receipt and outer operation IDs plus a bounded
`target_observation` with scope `authored_core_transform_channels`:

| Status | Meaning |
| --- | --- |
| `channels_match` | Every compared stored value matches the retained expectation |
| `channels_differ` | The same native target has explicit compared differences |
| `target_missing` | The frozen exact Object name no longer resolves |
| `target_replaced` | That name resolves to a different native Object identity |

The runtime journal exposes the retained intent and target observation separately
from `protected_observation`. Its legacy `step_evidence.scope` remains
`protected_objects_only` for compatibility with protected-comparison consumers;
`target_observation_scope=authored_core_transform_channels` describes the separate
target record, which also carries its own explicit scope. Inspection labels evidence
as recorded or stale and always reports `current_scene_verified=false`. A recorded
observation is a historical fact, not a fresh native read. Manual edits require
another explicit verification. Saved schema-v1 plan text includes none of this
runtime evidence or authority.

## Sidebar evidence

For each displayed step with an execution receipt, the artist sidebar formats the
latest receipt's existing public target evidence under a **Target core channels:**
heading, with the status on the next line. The protected-object comparison and
claimed step mark remain separate. The four recorded target statuses describe a
historical match, difference, missing target or replaced target at explicit
verification; none certifies the current scene, completes a step or accepts an
artistic goal.

The fixed reminders also use two lines each: `Step marks are claims;` followed by
`receipts do not verify the goal`, and `Target records are historical;` followed by
`verify after manual edits`. These line breaks change presentation only.

The labels describe the retained receipt:

| Receipt evidence | Target core channels label |
| --- | --- |
| Recorded `channels_match` | Matched at verification |
| Recorded `channels_differ` | Differences at verification |
| Recorded `target_missing` | Target missing at verification |
| Recorded `target_replaced` | Target replaced at verification |
| Stale observation or explicitly historical receipt | Stale; verify again |
| No observation, available expectation | Not verified |
| No observation, unavailable expectation | Expectation unavailable |
| No observation and no retained expectation, including older receipts | No retained expectation |
| Unknown validity, wrong scope or unsupported/malformed record contents | Observation unavailable |

Stale evidence takes priority over a previous recorded result. A recorded outcome
requires the `authored_core_transform_channels` scope. The display does not
refresh `current_scene_verified=false`; manual changes require another explicit
verification.

This display formats the public receipt already available to the sidebar.
Drawing it does not request another plan inspection, read native target channels
or context, invoke verification, capture an image or save the project. Portable
formatter and sidebar-wiring checks establish presentation behavior; they do not
establish native, visual or installed workflow acceptance.

## Permissions and acceptance boundary

The method is a read-only `core` tool requiring live `INSPECT_SCENE` permission.
It remains available under pause/emergency stop, subject to permission and caller
lifetime checks. It is not batchable and creates no native writes, checkpoints,
automatic repair, save or step completion. Successful verification adds no
operation-history entry. Failed or rejected calls handled by the executor retain
its existing failure audit; native effect evidence remains separate. Terminal
receipt bookkeeping reads no Blender state and runs no providers.

The opt-in `artist_target_verification` fixture must run through the
[isolated native runner](native-testing.md). Its completion contract includes
Float32-inexact decimals, Euler fractions, negative/nonuniform scale, signed zero,
position-only quaternion/axis-angle edits with preserved inactive channels,
manual drift, missing/replaced targets, unsupported mode conversion and complete
declared protected/context preservation. Source-matched native reports are
required; this document does not infer a pass from portable tests or runner wiring.
No new render is required for this read-only core-channel claim.

The development registry contains **266 MCP tools**, with components **0.3.0
alpha**. Full artist-loop, protected visual capture, native undo, durable recovery,
production acceptance and installed scenarios A–F remain open. Windows testing
remains paused, and all fourteen [release requirements](release-1.0-readiness.md)
remain OPEN. Safe native project saving remains
[unavailable](project-save-safety.md).
