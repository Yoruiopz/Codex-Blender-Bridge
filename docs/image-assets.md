# Texture images and material binding

Unreleased on `main`; not in the published 0.3.0 packages. These structured tools add image
assets and shader binding. Separate [pixel/brush tools](texture-painting.md) create generated
textures and paint independent versions. Baking, packing and unrestricted file access remain unsupported.

## Set up in Blender

1. In the bridge add-on preferences or sidebar **Permissions**, choose an **Approved Texture
   Folder**: an existing absolute local subdirectory containing the textures you intend to use.
   An empty setting blocks loading. The agent cannot change this setting through MCP.
2. Enable **Edit Materials** and, only for the intended reads, **Access External Files**.
   Enable the `materials` toolset, and `nodes` for binding. Toolsets do not grant permissions.
   Python, deletion and project saving are not required for loading or binding.
3. Inspect material users. Use `material.copy_for_object` before changing only one object that
   shares its material; referenced images and groups are not deep-copied.

Mutations require Object Mode and run on Blender's main thread. They do not change selection,
active object or viewport. Linked/override/read-only data is not silently made local.

## Tool contracts

| Tool | Scope | Blender permissions |
| --- | --- | --- |
| `image.inspect(image_name?, offset=0, max_images=32)` | Existing metadata/direct users; at most 64 images, 100 users per image and 256 users total, with pagination/truncation | `INSPECT_SCENE` |
| `image.load(filepath, new_name, colorspace="sRGB", alpha_mode?)` | New image from an approved file; unique explicit name, no implicit reuse/reload | `EDIT_MATERIALS`, `ACCESS_EXTERNAL_FILES` |
| `nodes.refresh_image(material_name, node_name, new_image_name, filepath?, group_path?, allow_shared=false)` | [Versioned refresh/relocation](image-revisions.md): load a new FILE version and rebind one exact image node, retaining the old image/buffer | `EDIT_MATERIALS`, `ACCESS_EXTERNAL_FILES` |
| `nodes.set_image(material_name, node_name, image_name, interpolation?, projection?, extension?, allow_shared=false, group_path?)` | Bind a loaded image, or **explicit null** to clear; exact `ShaderNodeTexImage` at the material root or explicit nested path, at most 256 nodes / 1,024 links | `EDIT_MATERIALS`; FILE images additionally require `ACCESS_EXTERNAL_FILES` and approved-source preflight |
| `image.remove(image_name, confirm_unused=false)` | Confirmed zero-user local datablock only; fake users block removal; never forced unlink or source-file deletion | `EDIT_MATERIALS`, `DELETE_OBJECTS` |

Names must be non-control UTF-8, at most 63 bytes. Color spaces and sampler enums are validated
against the running Blender/OCIO configuration. `sRGB` is the default color role; explicitly use
an available `Non-Color` space for data maps. Loading one file under different new names gives
independent datablocks/color roles without changing an existing image.
Optional `alpha_mode` selects STRAIGHT, PREMUL, CHANNEL_PACKED or NONE before the new buffer is
verified; omission preserves the native default. Inspection also reports alpha mode, dirty
and floating-point status for loaded buffers (otherwise null), without loading an unloaded buffer.
EXR is the explicit exception to omission/defaults: choose `Linear Rec.709` with `PREMUL` for
ordinary associated color, `Linear Rec.709` with `CHANNEL_PACKED` for independently stored raw
color channels, or `Non-Color` with `CHANNEL_PACKED` for data. EXR file hints never select the
role for you. Missing/unsupported interpretation is rejected before native image allocation.

Binding admits local, loaded, single-view FILE/GENERATED images only and checks material users.
Nested paths also check [transitive group ownership](shader-groups.md); explicitly isolate shared
parents/children before changing only one material user.
Shared materials require explicit `allow_shared=true`. Binding never edits image pixels/color
space, loads an unloaded buffer, changes graph links or silently reloads an image. Packed FILE
images still require a permitted supported source path for this workflow.

### Approved sources and limits

Files must resolve canonically inside the Blender-controlled folder. Network/UNC, mapped network
drives, Blender `//` paths, traversal, alternate streams and resolved symlink escapes are rejected.
Environment variables and `~` are not expanded. The folder cannot be a volume root. This scope
is specific to these tools, not a sandbox for other file-capable tools or armed raw Python.

Every format is limited to **8,192/axis** and **16,777,216 pixels**. File limits include a bounded
header/encoding allowance, not permission to decode extra pixels:

| Format | File budget | Reviewed subset |
| --- | --- | --- |
| PNG | 129 MiB | Standard grayscale/palette/RGB/alpha depths and Adam7; CRC and complete bounded zlib/scanline/filter framing |
| JPEG | 32 MiB | 8-bit baseline/progressive frame headers; full file hash, not independent entropy validation |
| EXR | 257 MiB | Version 2, single-part uncompressed increasing/contiguous scanlines, exactly alphabetic A/B/G/R FLOAT32 unit-sampled channels, equal zero-origin data/display windows |

The shared reader hashes complete files with at most **64 KiB per read**. PNG inflation is also
output-capped to 64 KiB blocks and its exact declared scanline budget, including empty Adam7
passes; a small compressed file cannot silently expand beyond that budget. Metadata is limited
to 64 KiB/chunk and 256 KiB cumulatively, with 16,384 total PNG chunks (enough for row-streamed
4K output). Animated PNG and `iCCP`, `zTXt`, **any `iTXt`**, and `eXIf` remain unreviewed.
JPEG keeps a 4,096-header-marker budget and bounded marker padding; its entropy/pixels are
still checked by the native decoder, not certified by the header reader.

EXR metadata uses short ASCII names, at most 64 KiB of header, 64 attributes and 4 KiB/attribute.
Only required fields, bridge role/alpha hints, Rec.709 chromaticities and bounded
`comments`/`owner`/`capDate` strings are reviewed. Offsets, row coordinates/counts and exact
file length must agree before native decoding. Half/compressed/tiled/deep/multipart/layered,
cropped/overscan, long-name and non-Rec.709 EXR are not silently interpreted. No pixel arrays
or file-sized byte copies are constructed by preflight. Format details follow the
[PNG specification](https://www.w3.org/TR/png-3/) and
[OpenEXR layout](https://openexr.com/en/latest/OpenEXRFileLayout.html); this is intentionally
a reviewed subset, not a general decoder or security sandbox.

The image loader, binding, revision, painting and pixel-inspection paths all use this reader.
Live external-file permission and the approved-folder setting are rechecked before reads;
file identity/hash is checked across preflight and before/after native loading. Pause/stop and
edit permission are rechecked before further native mutation, including immediately after
allocation. Cleanup requires live deletion permission and exact owned zero-user/no-fake-user
data; a denied cleanup reports its last observed name and possible-mutation evidence.
UDIMs, sequences, movies, multiview and unreviewed encodings remain unsupported, not fabricated.

Unsupported formats/contexts return `NOT_IMPLEMENTED`; malformed/over-budget inputs return
`INVALID_ARGUMENT`; denied permissions/folder scope return `PERMISSION_DENIED`. Header checks
are not full pixel/entropy validation. Blender's native decoder is **not interruptible** or a
security sandbox. `preflight_steps` yields internal IO/CPU safe points for future jobs; current
`image.load` still drains it synchronously and is not a responsive import/export job. These
bounds reduce accidental workloads; responsive delivery jobs remain a 1.0 gap.

## Inspect, edit, verify and recover

Inspect the scene, mode, selection and material ownership; create a logical checkpoint first.

1. Load an approved color map under a new name and explicit color space. Load data maps separately
   as Non-Color; do not change a shared color image's role.
2. Isolate the intended object's material if needed. Add an Image Texture node with `nodes.add`,
   bind using `nodes.set_image` and connect exact inspected sockets with `nodes.link`. Binding
   alone does not create connections or choose UV coordinates.
3. Reinspect the image/shader, compare protected `scene.snapshot` baselines and capture a matched
   material/rendered view. `shader_inputs` includes root Image Texture binding, sampler and listed
   source metadata, not image pixels or file contents.
4. Revise by loading/binding another image, then compare. These operations use normal history and
   automatic checkpoints. Confirmed `checkpoint.undo_last` snapshot recovery is tested for binding,
   load and unused removal; it remains global Blender undo, not a durable backup.
5. Save only when agreed and permitted. These tools never write images, pack dependencies, delete
   source files or save a `.blend` automatically.

Loading hashes/checks the file before and after native decoding and independently verifies loaded
dimensions, color space and source identity. A decode-time fault/cancellation attempts to remove
only the newly created zero-user, non-fake-user image **with live `DELETE_OBJECTS` consent**.
Normal successful loading still needs no deletion grant. Denied cleanup retains the image,
reports `cleanup_permission_denied=true` and requires inspection/confirmed recovery or separately
authorized unused removal. Unexpected users block cleanup even when deletion is permitted; the error reports
`rollback_verified` / `possible_mutation`. Binding faults attempt to restore the previous reference
and changed sampler properties, verifying readback and unchanged link identities. Reinspect after
any failed mutation; recovery remains tracked if restoration cannot be verified.

`image.inspect` reports dimensions only for already-loaded simple images; it does not read pixels or
probe/reload unloaded files. A source hash at binding describes the current file, **not proof that
an existing buffer is current with that file**. Structural success is not artistic approval.
Use `image.inspect_pixels` for explicitly authorized, bounded loaded-buffer evidence; it does
not replace metadata inspection, file-currency checks or visual review.

## Evidence and remaining work

`blender_image_assets_smoke.py` uses disposable factory scenes and isolated profiles on Windows
Blender 4.5.1/5.1.2. It checks real preferences/live permissions, pause/stop, PNG/JPEG, independent
color roles, unused removal, isolated material binding on shared mesh data, orange/blue revisions
with separate roughness, protected pixels/source files, structural comparisons and repeated native
recovery. Matched captures require visual review. No user project or preferences are saved.

[Versioned node refresh/relocation](image-revisions.md) now works at root/nested paths without
reloading the original buffer. In-place reload/pixel editing and durable pixel recovery,
packing/unpacking/saving, painting/baking, broader formats, compositor image workflows,
production-material reuse and responsive decoding remain open. This
advances LOOK-01, not complete [repair-and-texture or 1.0 acceptance](plan-1.0.md).
