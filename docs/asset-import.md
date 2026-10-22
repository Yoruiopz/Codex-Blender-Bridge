# Approved-source static asset import

`asset.import_preview` and `asset.import` are development tools in `asset_delivery`.
Choose **Approved Asset Source Folder** in Blender before reading input. This READ folder
is separate from the existing approved asset output folder. Empty defaults grant no path
access, and MCP cannot change either approval setting.

| Tool | Result | Required Blender permissions |
| --- | --- | --- |
| `asset.import_preview` | Complete bounded source admission, dependency/loss summary and a fingerprint covering source bytes, identity and measured destination state | `INSPECT_SCENE`, `ACCESS_EXTERNAL_FILES` |
| `asset.import` | One new exactly named collection with an owned static import; no project save | Preview permissions plus `EDIT_SCENE`, `TRANSFORM_OBJECTS`, `EDIT_MESH`, `EDIT_MATERIALS`, `EDIT_ANIMATION`, `DELETE_OBJECTS` |

Inspect the preview, repeat its current `fingerprint` as `expected_fingerprint`, and repeat
`required_accepted_losses` exactly as `accepted_losses`. `collection_name` must be unused.
Changed source identity, bytes, destination state or collection availability requires a new
preview. An import never overwrites existing collections or writes the approved source file.
`SAVE_PROJECT` is separately required for an explicit later `project.save`.
Preview fingerprints are bound to a per-process nonce and native ID `session_uid` values.
They cannot authorize a restarted process or a same-name ID replacement, including memory
address reuse. Internal owned-ID inventories also use native UIDs so compensation never
adopts a replacement merely because its pointer matches. Non-ID override/context RNA wrappers
retain their separate pointer evidence.

## Current admission contract

Input must be one ordinary existing local `.glb` or `.fbx`, inside the approved source folder,
with no symbolic links or reparse points in its ancestry. Volume roots, devices and network
paths are excluded. The complete file is limited to 64 MiB. Import requires Object Mode,
a local editable destination and one-metre units.

GLB admission covers one self-contained core glTF 2.0 scene with mesh/empty objects, triangle
primitives, reviewed float/unsigned accessors, the first UV map, core PBR constants and embedded
base-color PNG/JPEG images. Every JSON field is checked against the admitted subset. External
and data URIs, extensions/extras, skins, animation, cameras, unreviewed texture channels,
projective/sheared node matrices and excessive accumulated transforms are rejected. Limits
include 64 objects, 100,000 aggregate instance vertices/triangles, 16 materials and an
aggregate 4096² embedded-image pixel budget. Texture bytes pass bounded stream validation
before Blender can decode them. Loss acknowledgements are `VERTEX_SPLITS`,
`AXIS_UNIT_CONVERSION` and `PBR_MATERIAL_RECONSTRUCTION`.

FBX admission covers material-free static mesh/empty binary FBX 7400/7500. The standard-library
parser bounds nesting, properties, decompression and geometry before the native importer runs.
Media, materials, animation, rigs and constraints are rejected, including embedded media:
Blender's FBX importer can read an external image filename before using embedded content.
Loss acknowledgements are `AXIS_UNIT_CONVERSION` and `FBX_MESH_RECONSTRUCTION`.

`include_animation=true` returns `NOT_IMPLEMENTED`. General textured FBX, source skinning,
animation, broader material roles and their conversion/delivery evidence remain mandatory
unfinished 1.0 work. These tools do not silently discard those capabilities.

## Ownership, execution and recovery

The native importer reopens a private complete input copy, created in a task-owned temporary
directory outside the approved READ folder. On POSIX its directory/file modes are 0700/0600.
Identity and full-byte checks protect that input across callbacks. Original approved source
bytes are rechecked, and the source folder receives no output writes. This is race detection
and resource ownership; it is not an OS sandbox against the same user, installed native code
or arbitrary Blender handlers.

Blender imports synchronously into a private Scene. Only new local mesh/empty/material/packed
image IDs and their reviewed ownership closure can be published. Packed image bytes must match
preflighted embedded bytes; complete loaded float pixels and metadata are measured after native
decode. Old geometry/UV/weights/rig/animation/shader definitions, loaded pixels/packed bytes,
ID ownership, scene timing/units and current context are compared before and after import.
Coverage is enumerated and bounded: it does not measure arbitrary custom data, modifiers,
constraints, world/render definitions, simulation caches, every linked dependency or visual
appearance. Destination limits include 4096 IDs, 128 objects, 64 materials/actions and 32 images,
with an aggregate 4096² loaded protected-image pixel budget. Unsupported complete evidence
fails before mutation. Empty startup Viewer/Render Result IDs are admitted; loaded viewer
buffers are outside this contract.

Collection publication updates native view-layer membership before restoring selection.
Permission-provider callbacks finish before the terminal cancellation and pause/stop check.
Rehoming and post-update selection restoration repeat protected context, native identity and
consumer checks after callbacks; only the expected temporary selection difference may be restored.
The empty private Scene has an internal extra user on the reviewed native versions, so its
removal checks exact identity, no contents, no mapped consumers, no context/window owner and
only that sole internal user. User counts are never cleared. Other owned IDs use explicit
unlinking within their closure and removal without implicit consumer unlinking.

An injected failure can remove an unchanged, unpublished owned closure while all required
permissions remain live. Publication, a newer edit, a new consumer, paused/stopped execution
or revoked permission prevents blind compensation and reports retained IDs and temporary
resources. Incomplete allocation inventory is explicit. A published partial result remains
inspectable and requires explicit recovery. Native undo does not remove filesystem staging;
retained buffers, operation history and an unsaved checkpoint are not durable backups.

Native import, packed-image decode, view-layer update and FBX cycle release report measured
blocking intervals. They have no hard cancellation guarantee. Live gates are repeated before
subsequent writes. Blender 5.2 native FBX failure → owned-ID removal → reimport reproduced a
shutdown crash in Python cyclic collection, even after bridge failure references were cleared.
Before FBX compensation deletion the bridge releases unreachable native helper cycles while
IDs still exist, then repeats live permissions, stop/context, exact ownership/consumer and
protected-state checks. A finalizer's newer edit or acquired consumer blocks all cleanup writes.
GLB compensation does not run this global collection. This remains a synchronous cleanup tail,
not a real-time guarantee or a universal upstream crash fix.

## Development evidence and limits

The phased `asset_import` fixture creates owned GLB/FBX sources, tests denial, invalid context,
stale fingerprints, loss acknowledgement, injected native failure and measured exact-closure
recovery. It then imports successfully, explicitly saves an owned `.blend`, relocates its
source files and opens that project in a fresh process. Complete imported pixels, packed bytes,
image bindings, geometry, transforms, units and timing must match. Dirty protected pixels are
checked within the writer; their independent durable recovery is not certified by this fixture.
No operator success is described as visual or artist acceptance.

Both Linux Blender 4.5.14 and 5.2.2 passed this bounded paired fixture. Reports and retained
negative GC-isolation runs are under `build/next-wave-import-*` in the task workspace. Frozen
source/package qualification must be recorded separately. Windows installation/native checks,
4K/constrained-memory import, human visual review, mixed manual editing, cancellation/disconnect
and history-eviction recovery remain open; this foundation does not close the production
1.0 delivery gate.
