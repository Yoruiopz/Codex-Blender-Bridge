# Native project saving with explicit session permission

**0.9.0 alpha candidate — exact-build qualification pending.** The two typed tools use canonical queued admission,
retained source/path intent, a distinct local effects grant and bounded shared jobs.
The source inventory has 270 tools and matching 0.9.0 metadata. Each accepted build
must qualify this real installed path and retain exact source/package identities,
measured native outcomes and limitations. New 0.9.0 bytes still need exact-commit
full/static checks, all seven CI jobs, package integrity, installed core/image and
native-save/4K qualification. See the [candidate scope and gates](releases/0.9.0.md).
A source version or donor result does not establish acceptance or publication.
Published [0.8.0 evidence](https://github.com/Yoruiopz/Codex-Blender-Bridge/releases/tag/v0.8.0)
and the earlier 268-tool 0.7 release remain separate historical records.

Legacy `project.save` retains its [quarantined refusal](project-save-safety.md).
The native-save alternative does not provide an arbitrary-Python fallback or
complete 1.0 production delivery. Normal native effects require separate local
consent rather than a claim of exact-path confinement or hidden-Main equality.

The separate donor at `80ec3cb7dd2f64b5baa4fd8193fa9780fd3d93bf` passed nine
registered save/interruption scenarios on official Linux 4.5.14/5.2.2. Its
`418d79fda46bae16c59025657d844a452682b061` follow-up also passed native-save and
inherited geometry/Scene/image job replays after renaming the save-specific
helper. These are historical donor-source results. The 0.8 integration must
retain the 0.7 weight/raw-curve bounds and canonical-provider/job dependencies,
and qualify its genuine initial parameter hook through the actual installed TCP
queue. Direct ToolContext calls or a substituted classifier are not that proof.
No old source/package identity is reused as final 0.9 qualification.

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
sequencer container before any save. Subsequent diagnostics distinguished the
pointers and observed an empty editor with 129 channels in an ordinary Scene.
The source profile now admits an existing empty `SequenceEditor` through the
finite projection described below. Qualification must retain that editor and
its channels; clearing the editor or requiring factory names would bypass this
production requirement. Source commit
`6112fdf54e6464bf15ef9473ed9a57eef4650e69` subsequently passed the genuine queued
single-clean-4K fixture with that editor retained on both reviewed Linux builds.
All ten scenario assertions passed on each build; the source/helper snapshots
remained unchanged. This is prerequisite source evidence, not acceptance of the
new 0.9.0 metadata or packages. Earlier refusals and fixture cleanup remain
historical evidence, and ordinary artist-project admission remains open.

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
four, with each dimension at most 4,096. The finite source profile permits
16,777,216 pixels and 80 MiB packed bytes in aggregate. The prerequisite source's
single-clean-4K native result does not qualify new candidate packages or broader
4K delivery. Projects above the legacy 1,048,576-pixel budget require fresh
8 GiB available-memory and 2 GiB free-disk observations before large allocations,
reader launch and fresh-process open/decode/capture. Unknown or insufficient
resources refuse. These observations are admission checks, not reservations or
hard memory limits. Every raw
Float32 pixel digest, packed original-byte digest, size, color/alpha role and
binding is compared. No source packing, generated/dirty image conversion, reload
or equivalent current-edited-pixel backup is inferred. Saved files are capped
at 256 MiB for hashing/reopen; exceeding a cap after native saving reports its
retained effects.

A null `Scene.sequence_editor` retains the exact prior projection bytes. An
existing native `SequenceEditor` is admitted only after its declared, non-runtime
field metadata qualifies. Before any editor or channel instance getter, a finite
class-origin guard uses raw built-in type/module descriptors and the already-loaded
`bpy.types` module's bound native C resolver to establish canonical class identity
and native getter/constructor origins. It imports no `bpy`, does not trust a class
name or mutable registry alias alone, and retains the legacy refusal for an opaque
foreign editor. Synthetic metadata tests explicitly model this origin boundary;
the official native class shapes were exercised by the prerequisite source run,
while new package identities still require qualification. This is a stock native
registry assumption, not a hostile-Python or C-extension security boundary.
A bounded one-sentinel check proves the direct
top-level `strips` collection empty before reading `strips_all`, whose native
getter allocates a temporary recursive vector. The recursive collection,
`meta_stack` and any 4.5 `sequences`/`sequences_all` aliases must also be empty,
and `active_strip` must be null. Unknown editor collections, channel schemas,
nonempty data or more than 129 channels refuse. Rigid-body worlds still refuse.

The comparison includes every ordered `SequenceTimelineChannel` row, including
channel zero: arbitrary UTF-8 names, lock and mute flags, and the public read-only
`number` on 5.2. All channel metadata qualifies before any channel values are
read. On 4.5 the public number and underlying stored index are explicitly
`UNOBSERVED`; no hidden-index equality is claimed. Names, flags and ordering are
preserved without default-name checks, normalization or renaming. Inspection
never calls editor creation/ensure, prefetch or cache getters, reads C property
defaults/ranges, or clears strips, channels or editor panels. This finite
projection does not cover other editor settings or cache storage.

Getter provenance is pinned to official Blender source at
[`62c1db4208e862312bc36db5bc15d4a6dbcfa3e3`](https://github.com/blender/blender/tree/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3)
and [`d13f752e3b9c4f8c261cda552b1021f8bcc0382c`](https://github.com/blender/blender/tree/d13f752e3b9c4f8c261cda552b1021f8bcc0382c).
`rna_scene.cc` binds `sequence_editor` directly to `Scene.ed`;
`seq::editing_get` reads that pointer while `editing_ensure` creates it.
`rna_sequencer.cc` binds top-level strips and channel names/flags to native SDNA;
its 5.2 channel-number getter reads the stored index. These source bindings
support the bounded inspection design; exact-source native save/reopen and
installed-reader runs remain required to establish preservation in practice.

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
certify appearance, current edited-pixel packing, general 4K workflows, broader assets/dependencies,
Windows, full portable production delivery or 1.0. Those requirements remain
mandatory in the [readiness ledger](release-1.0-readiness.md).


## Single clean packed 4K source evidence and candidate gates

The explicit `native_project_saving_large` isolated-runner case exercises one
4096 × 4096 RGBA8, sRGB/STRAIGHT clean FILE image. Its original level-zero PNG
exceeds the old packed-byte cap and includes transparent, partial and opaque
alpha. The fixture packs and loads it, removes access to its external source
folder before creating save intents, and uses a socket worker connected to
`127.0.0.1` through the actual Runtime queue, response delivery and main-thread
timers. The legacy small fixture retains its separate direct-dispatch scope.

The prerequisite source passed COPY_NEW, Save As, current-file save and explicit
replacement, with a distinct fixed standalone Blender reader for every success.
Each reader compares the complete declared projection, original packed bytes and
all 67,108,864 Float32 components, including alpha, image roles and bindings.
Parent identity and declared authored state must also remain unchanged. Ordinary
Scene/SYSTEM data is retained; unprojected native storage remains outside the
comparison and is not claimed equal. Retained pixel buffers are not backups.

The same source run passed actual queued denial, cancellation, local grant revocation,
owner disconnect, stale intent after an owned manual edit and an injected reader
input failure. It retains source/program/binary identities, full reader receipts,
resource samples, source/reader peak memory, blocking intervals and bounded
phase/deadline facts. Native writes remain non-preemptible; interruption must
report effects already incurred and prevent subsequent unauthorized writes.
Read-only inspection/history replay must not enter another save.

Constrained-memory native qualification is **false on both builds**. The source
run allocated zero pressure bytes and reported
`SAFE_OWNED_PRESSURE_CAP_OR_HEADROOM`; ordinary resource samples and portable
denial models do not count as pressure acceptance. A bounded pressure
exercise may run only when it can retain at least 6 GiB available memory with
at most 2 GiB of disposable pressure buffers. If that cannot be demonstrated,
the report marks native low-resource qualification false; portable denial models
and ordinary resource samples do not count as that scenario. The runner retains
the unchanged 300-second process/phase bound.

The source result belongs to commit `6112fdf54e6464bf15ef9473ed9a57eef4650e69`,
not to the new 0.9.0 metadata. The two source runs passed in about 226.24 seconds
combined on official Linux 4.5.14 (`62c1db4208e8`) and 5.2.2 (`d13f752e3b9c`).
The runner report retains `release_readiness: NOT_ASSESSED`; exact candidate
native replays, reviewed retained evidence and installed-package qualification
remain required. Dirty or
generated images, identity-preserving current-pixel backup, broader artist
projects, Windows and full H01/1.0 acceptance remain open. Users should not
downsize artwork to bypass a refusal.

This candidate retains the 256 MiB file ceiling. A separate original/snapshot
raw-EXR pair can exceed the 16,777,216-pixel and 80 MiB packed limits. Work on
33,554,432-pixel/640 MiB packed/1 GiB saved-file sizing and source recovery is
in progress and excluded from 0.9.0. No current-pixel lifecycle, dirty/generated
conversion or durable backup qualification follows from the clean PNG result.
