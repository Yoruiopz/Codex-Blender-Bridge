# Native project saving with explicit session permission

Unreleased source integration. Qualification of this combined source,
fresh-installed packages and end-to-end workflows is pending. The older `project.save` tool retains its
[quarantined refusal](project-save-safety.md). These are distinct typed tools,
not an arbitrary-Python fallback or completed 1.0 delivery.

The separate native-save source at `80ec3cb7dd2f64b5baa4fd8193fa9780fd3d93bf`
passed all nine registered save/interruption scenarios on official Linux Blender
4.5.14 and 5.2.2. Its follow-up `418d79fda46bae16c59025657d844a452682b061`
also passed native-save and inherited geometry, Scene and image job replays after
renaming the save-specific authority helper. Those results qualify that donor
source's bounded profile; they do not qualify this integration with public 0.7.
This checkout retains the 0.7 weight and raw-curve recovery bounds and adds exact
canonical-provider dependency checks for the native-save permission wrapper and
jobs class. Focused models, full checks, genuine native entry and fresh installed
replays must all pass on the final combined commit before its support is claimed.
The published 0.7 packages remain a separate 268-tool release; this unreleased
source registry has 270 tools and does not change the component version.

The first registered native runs stopped before any save at unsupported factory
palette data. The isolated qualification fixture now inventories all native data
families and explicitly cleans known factory data before creating its owned test
asset. It retains structured failure details and records the declared Scene/UI
binding changes from that setup. Passing this cleaned fixture will establish only
the narrow declared profile. Ordinary startup palettes, line styles and transient
Viewer/runtime images still need a separately reviewed, measured extension;
standard startup project support remains an open production usability requirement.
The following native attempt also exposed a misspelled Scene property before any
save: the exact Blender RNA identifier is `rigidbody_world`. The fixture now
retains a batch census of declared class/field/type/array/function metadata before
value validation. It reads no property defaults, dynamic enum catalogs, pointee
types or project values. Missing or mismatched declarations fail together; these
metadata checks do not replace the nine actual save/reopen/interruption cases.
Both builds passed that metadata census, then refused a non-absent Scene cache or
sequencer container before any save. The initial report did not distinguish the
two pointers. Fixture diagnostics now record them independently and report the
remaining declared value predicates together. Only an attested fresh fixture's
verified empty sequencer container may be cleared during owned setup; production
guards continue to refuse it, and nonempty, unknown or rigid-body data is retained.
The next run identified the retained state: zero strips/meta stack and no active
strip, with 129 factory channels. Exact source for both builds initializes those
channels in order as `Channel 0` through `Channel 128`, unlocked and unmuted.
The fixture may recognize only that complete public-field state before its owned
clear. Blender 5.2 also exposes each channel's read-only number; Blender 4.5 does
not expose the stored index, so no hidden-index equality is claimed. Nondefault
names, flags, ordering, layouts or incomplete observations refuse; localized names
are never normalized or renamed. This
setup exception does not change the production sequencer guard or qualify saves.

Ordinary Save/Save As on official, unmodified Blender can synchronize/flush
project state and run callbacks, catalog writes and history/thumbnail effects
outside the selected project folder. Native overwrite is not an atomic
compare-and-swap operation. These effects require explicit Blender-side authority
rather than silently broadening existing save/path grants.

## Authorize a bounded session

In Blender's Codex Bridge panel, choose an existing **Approved Project Folder**
and enable **Inspect Scene**, **Save Project** and **Access External Files**.
Use **Arm Native Save Effects for this Session** to review and allow the normal
native effects for this Bridge session and its connected clients. The duration
defaults to 900 seconds and is bounded to 1–1800. Duration/folder settings alone
do not arm consent; there is no stored `allow_native_save_effects` preference.

The grant starts off, expires without renewal and can be revoked locally while
a job is active. Register/unregister, Bridge start/reset/stop, emergency stop,
project replacement and native undo/redo revoke it. Renewal during an active save
is refused. Once armed, each save does not require another local popup. MCP cannot
arm/renew it or change the local folder. Trusted Python inside Blender is not an
adversarial security boundary.

Both tools require `INSPECT_SCENE`, `SAVE_PROJECT`, `ACCESS_EXTERNAL_FILES` and
`NATIVE_SAVE_EFFECTS`. Both are modifying operations: preview retains intent and
can perform declared native inspection. Enforced protected scope refuses through
the registry's pure initial classification before admission, permission providers,
Blender reads or file access. Protection/baselines are never cleared or rebased.

## Preview, accept, inspect

`project.native_save_preview(mode, filepath, overwrite_policy)` requires an exact
absolute `.blend` filepath, even when saving the current file. It must be within
the approved ordinary local folder. Missing parents, aliases/symlinks/reparse
points, implicit directories, automatic rename and changed paths refuse. Paths
containing spaces are valid.

| Mode | Overwrite policy | Meaning |
| --- | --- | --- |
| `COPY_NEW` | `NO_CLOBBER` | Save a copy to owned staging, verify in a fresh worker, then atomically create the unused final path. Original project filepath/file bytes stay separate. |
| `SAVE_CURRENT` | `NATIVE_REPLACE_EXPECTED` | Save the exact current file with explicit previewed identity/hash and normal native backups. |
| `SAVE_AS` | `NATIVE_NEW_EXPECTED` or `NATIVE_REPLACE_EXPECTED` | Save the exact new/replacement path and intentionally change Blender's active filepath. |

For example, preview a copy:

```json
{"mode":"COPY_NEW","filepath":"/approved/Character delivery.blend","overwrite_policy":"NO_CLOBBER"}
```

Call `project.native_save_start` with the returned `preview_id`, fingerprint,
identical mode/path/overwrite policy and the complete `required_accepted_losses`
verbatim as `accepted_losses`. That array is required, including an empty array
when appropriate. SAVE_CURRENT/SAVE_AS require
`NATIVE_DESTINATION_RACE_NOT_EXCLUDED`: path/hash checks cannot eliminate their
native write race. Exact zero-user orphan losses are separately listed rather
than changing fake-user flags or silently dropping missing output state.

The deadline is a strict integer 1–300 seconds, default 120. Acceptance creates a
job; poll `jobs.inspect`/`jobs.list` and keep its owner connection open. Use
`jobs.cancel` when needed. Consumed/expired previews, source or fact changes,
permission loss and changed plan/service/grant identity refuse rather than
adopting a new baseline. One active job is shared with image, geometry and Scene
work. The start response is not completed-save evidence.

## Initial declared-data profile

The bounded `stock_native_project_v1` profile uses arbitrary asset names and
explicit relationships: one local Scene, up to 128 non-UI IDs, 32 Objects and 16
Collections. Reviewed local Mesh/Empty/Armature/Camera/Light Objects,
Scene/Collection relationships, armature binding and layered Actions are admitted.
The comparison includes represented static transforms, topology/UV/weights/
material bindings, rig rest hierarchy, Action slots/curves/keys/handles, units/
range, camera/light fields and reviewed shader inputs/links/sampling.

Limits include 32,768 Mesh vertices/131,072 corners, 64 Bones, 64 FCurves/2,048
keys, eight Materials and 64 shader nodes/128 links. First shader forms are
Material Output, Principled, Image Texture, World Output and Background. Nested
or unsupported nodes, other modifiers/constraints/drivers/NLA/shape keys,
linked/override data, external libraries/caches/movies/scripts/IES and unknown
families/schemas refuse for this profile.

Images must already be loaded, unanimated, packed, clean FILE images: at most
four, with 1,048,576 pixels and 20 MiB packed bytes in aggregate. Every raw
Float32 pixel digest, packed original-byte digest, size, color/alpha role and
binding is compared. No source packing, generated/dirty image conversion, reload
or equivalent current-edited-pixel backup is inferred. Saved files are capped
at 256 MiB for hashing/reopen; exceeding a cap after native saving reports its
retained effects.

Reviewed animation-driven raw channels are explicit comparison exclusions while
their authoritative Action data remains included. Native synchronization there
is allowed. Hidden UI/Base/SYSTEM storage, runtime caches, undeclared custom
properties and appearance are outside the projection. UI is saved by the normal
native writer, never through full Main/UI library export. This is not an
exhaustive raw-Main snapshot or complete production dependency coverage.

Known-family IDs with zero users and no fake user are omitted from the saved
projection and named in the preview's required accepted losses. Their source CAS
tracks identity, rather than all omitted authored content. The global unsupported
family check runs earlier and also rejects zero-user unsupported IDs. Runtime or
Viewer data must not be treated as an ordinary unused authored image without a
separately measured classification of native omission and fresh-open behavior.

## Files, failures and fresh reopen

Native save and some transfers/checks are synchronous and cannot be preempted.
Cancellation, expiry, disconnect, pause or revoked permission stops later actions
at their next gate. A native call may already have written project, backup,
staging or callback files and changed the active filepath. No automatic undo,
reload or source restoration overwrites later manual work.

COPY_NEW verifies owned hashed staging before no-clobber publication.
SAVE_CURRENT/SAVE_AS have native file effects before fresh verification. A fixed
bundled reader runs in a fresh official Blender process with factory startup and
autoexec disabled, reopens only owned hashed output and compares the frozen
projection, including complete packed bytes/pixels. It never writes into the
artist's active project. Installed reader execution is a separate acceptance gate.

Inspect `external_effects` on every terminal outcome. Its typed `native_save`
envelope records entry/completion, possible authorized effects, actual filepath
before/after and declared/fresh-process verification. The native external-effect
inventory remains explicitly incomplete. At most four known final/staging/backup
artifacts enter bounded history; truncation/missing evidence is independent of
unknown catalog/callback paths. No unknown path/hash is invented. Files survive
undo, cancellation and late history errors.

Failed native-save artifacts and their receipts remain inspectable separately
from the display history. Later accepted requests may retry reaping their exact
owned reader process, including after an Approved Project Folder change; they
never delete retained project/backup bytes or publish a failed copy. Four retained
failed saves block further starts. Explicit recovery-artifact lifecycle beyond
that conservative limit is not yet implemented.

Folder/private environment/hash checks detect bounded races; they are not a
host filesystem/network sandbox or crash/power-loss proof. No universal blocking
time or process-memory cap is promised. Fresh reopen of this profile does not
certify appearance, current edited-pixel packing, 4K, broader assets/dependencies,
Windows, full portable production delivery or 1.0. Those requirements remain
mandatory in the [readiness ledger](release-1.0-readiness.md).
