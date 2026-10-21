# Cinematic variants

The development `scene_edit` toolset contains a bounded camera and lighting iteration
workflow. It is a partial implementation of UX-01 and cinematic scenario E, not
acceptance of the full artist workflow or Windows release qualification.

Inspect with `scene.variant.inspect`, capture the actual current state with
`scene.variant.capture`, review matched images from `scene.variant.preview`, then
apply that exact preview with `scene.variant.apply`. Every write uses Blender's live
permissions. Capturing Scene metadata requires `INSPECT_SCENE` and `EDIT_SCENE`;
preview adds `TRANSFORM_OBJECTS` and `CAPTURE_VIEWPORT`, and applying requires
`INSPECT_SCENE`, `EDIT_SCENE` and `TRANSFORM_OBJECTS`. All three changing operations
participate in normal logical history; preview is modifying even when it restores
numeric controls successfully. Read-only inspection remains available while paused
or emergency-stopped. Changing operations resolve permission-provider callbacks
before final cancellation/stop-state checks, then compare the complete current
scope before each native write and compensation write.

## Explicit scope and preservation

Capture names one independent camera, one to eight independent lights, and every
scene mesh as a protected object (one to 32, including hidden objects and shared
mesh consumers). References must resolve exactly to local editable objects and
single-user camera/light data in the current scene. Controls cannot have parents,
children, constraints, modifiers, animation, locked transforms, nonidentity delta
transforms, focus-object dependencies or unreviewed incoming consumers. Camera
marker and external focus references are rejected.

The first contract accepts static Object Mode EEVEE scenes with at most 64 objects,
128 collections and eight view layers. Supported scene objects are unparented base
meshes, cameras, lights and plain non-instanced empties. Protected mesh geometry,
UVs, attributes, material bindings, collection membership, visibility and shared
consumers are compared. Mesh custom normals, shape keys, modifiers, animation,
constraints and external image dependencies are rejected. Mesh proofs use the
bounded base-mesh capture (20,000 combined vertices/edges/faces and bounded custom
data); the complete protected profile must fit 512 KiB.

Reviewed shader nodes are Principled BSDF, material/world/light outputs, Background,
Emission, Checker Texture, UV Map, Texture Coordinate, RGB and Value. Each graph is
limited to 64 nodes and 256 links. Groups, image textures, object dependencies and
other node types are rejected. Blender 5.2's default Emission → Light Output graph
is retained and checked. The implementation checks actual compositor graph and
sequencer contents: a deprecated `use_nodes` value or an empty SequenceEditor alone
does not imply a dependency. Actual compositor graphs, sequencer strips, timeline
markers, multiview rendering and view curves are outside this contract. Background
scenes, rigid-body worlds/objects/constraints, force fields, camera background-image
collections, custom AOVs/light groups and Freestyle are also rejected before writes.

The guard also compares world and render/color settings, frame/subframe, view
layers, exact runtime IDs, selection, active object, active camera and the stored
library. Camera angle aliases are derived from the captured lens/sensor settings;
they are excluded from the protected profile alongside those controlled settings.
Blender 4.5 adds a legacy camera `cycles` compatibility dictionary on save. Only
its exact reviewed key set with native-equal values and scalar types is canonicalized;
those settings already have native RNA proof. Other `cycles` custom properties
remain protected, and native ID references in any protected custom property are
rejected rather than reduced to their own custom-property contents.
Camera lens/clipping/DOF, transforms and reviewed light shape/energy/color settings
are captured as exact native values, not inferred from images.

## Persistence and stale references

The Scene custom property `_blender_codex_bridge_cinematic_variants_v1` stores strict
schema-v1 JSON: at most eight variants and 256 KiB. Records contain exact names,
reviewed numeric controls and a protected-profile digest. Unknown fields, duplicate
JSON keys, nonfinite numbers, duplicate references, paths and authority fields are
rejected. This is inert project metadata, not executable data or saved permission.

Every changing operation requires the current inspected library revision and the
fingerprint of its exact JSON text. Replacing an existing variant additionally
requires its current ID. A fresh preview returns a session token tied to current
runtime identities, controls, JSON and protected state; apply consumes it once,
including an attempted apply that subsequently fails. At most eight preview tokens
are retained. Reopening or changing context requires a newly authorized toolset,
exact reference rebind and a new preview. Changed protected assets or render/world/
time settings require capturing a newly reviewed variant.

Capture, preview and apply never save a project. Persisting the library to disk is
an independent `project.save` operation with `SAVE_PROJECT`, `ACCESS_EXTERNAL_FILES`
and an explicit approved destination. A logical checkpoint is not a disk backup.

## Matched previews and recovery

Preview pins the named camera and captures current/candidate PNG images at 384 ×
256 pixels, 100% resolution, 16 EEVEE samples, RGBA8, no render border and ray tracing
disabled. It checks the complete PNG dimensions and retains path, byte count and
SHA-256 for both files. It restores owned camera/light controls, active camera and
changed capture settings, and verifies the protected profile and current context.
The two images still need visual review for composition, lighting and appearance.

Native refresh/render calls execute synchronously on Blender's main thread and
cannot be interrupted before they return. Guards run around writes and native
calls. This API does not promise a hard frame-time deadline or isolate arbitrary
user handlers. Detected permission/context/protected-data changes stop subsequent
writes. Compensation requires current consent and exact ownership of the attempted
outputs; pause, emergency stop, replaced values or protected-state changes can
refuse it. Failures report possible mutation and measured rollback status for
reinspection and explicit recovery.

Preview replaces Blender's Render Result and retains two managed temporary PNGs.
Those effects remain in bounded operation history even when numeric scene state is
restored. Native undo does not delete the PNGs or restore the previous Render
Result. No automatic project save, arbitrary output path or overwrite is involved.

## Development verification

The isolated `cinematic_variants` fixture uses separate writer and reader processes.
It compares complete matched RGBA8 images, injects a failure after an actual control
write, verifies guarded compensation and native undo, saves through the separately
authorized project API, then reopens the project and rebinds references. It checks
that a saved preview token cannot authorize apply, compares the reopened current
render with the writer's render and exercises A → B → A controls. Per-process logs,
capture hashes and source fingerprints are retained by the native runner.

Broader camera rigs, animated/procedural assets, texture-rich/nested materials,
compositor/pass authoring, reference interpretation, interactive progress and the
full cinematic acceptance scenario remain open release requirements.

The final bounded development run passed on Linux Blender **4.5.14 LTS** and
**5.2.2 LTS**, including separate writer/readers, camera-background/AOV/custom-ID
rejection, permission denial, invalid mode, protected attribute and raw-JSON changes,
post-write failure compensation and actual native undo. Six additional native
fault cases per version make an otherwise granting permission provider pause,
emergency-stop or switch mode immediately before control writes or compensation;
no unpermitted control writes occur. Read-only inspection remains available under
the pause/stop flags. Pure regressions reproduce four late writes with the former
gate ordering and verify zero writes after the correction. Both fresh readers compared
98,304 RGBA8 pixels with **zero changed pixels** against the writer's current image.
The evidence is retained at
`build/next-wave-variants-provider-gates-20261022-final2/report.json` in the original development
workspace, with a source/visual receipt beside it. The four matched writer captures
were reviewed technically for the intended warm wide → cool close-up change; this
is not human artistic acceptance. Sixty-four domain tests plus related history/parity
coverage (100 tests total) passed with MCP SDK 2.0.0 and 2.2.0. These are dirty-worktree
development results; the clean source/package matrix and Windows acceptance remain
separate requirements.
