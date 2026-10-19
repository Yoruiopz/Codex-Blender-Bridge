# Texture images and material binding

Unreleased on `main`; not in the published 0.3.0 packages. These structured tools add image
assets and shader binding, not painting, baking, packing or unrestricted file access.

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
| `image.load(filepath, new_name, colorspace="sRGB")` | New image from an approved file; unique explicit name, no implicit reuse/reload | `EDIT_MATERIALS`, `ACCESS_EXTERNAL_FILES` |
| `nodes.set_image(material_name, node_name, image_name, interpolation?, projection?, extension?, allow_shared=false, group_path?)` | Bind a loaded image, or **explicit null** to clear; exact `ShaderNodeTexImage` at the material root or explicit nested path, at most 256 nodes / 1,024 links | `EDIT_MATERIALS`; FILE images additionally require `ACCESS_EXTERNAL_FILES` and approved-source preflight |
| `image.remove(image_name, confirm_unused=false)` | Confirmed zero-user local datablock only; fake users block removal; never forced unlink or source-file deletion | `EDIT_MATERIALS`, `DELETE_OBJECTS` |

Names must be non-control UTF-8, at most 63 bytes. Color spaces and sampler enums are validated
against the running Blender/OCIO configuration. `sRGB` is the default color role; explicitly use
an available `Non-Color` space for data maps. Loading one file under different new names gives
independent datablocks/color roles without changing an existing image.

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

The initial subset is PNG and **8-bit baseline/progressive JPEG**, limited to **32 MiB** per
file, **8,192 pixels** per dimension and **16,777,216 pixels** total. Header/chunk scanning is
bounded; PNG checksums, image-data and final-chunk checks precede decoding. Animated PNG and
`iCCP`, `zTXt` or **any `iTXt`** chunks (even uncompressed text) are not supported. HDR/EXR,
UDIMs, sequences, movies, multiview and unreviewed JPEG frame encodings remain unsupported.

Unsupported formats/contexts return `NOT_IMPLEMENTED`; malformed/over-budget inputs return
`INVALID_ARGUMENT`; denied permissions/folder scope return `PERMISSION_DENIED`. Header checks
are not full pixel/entropy validation. Blender's native decoder is **not interruptible** or a
security sandbox. These bounds reduce accidental workloads; responsive jobs remain a 1.0 gap.

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
only the newly created zero-user image. Unexpected users block cleanup; the error reports
`rollback_verified` / `possible_mutation`. Binding faults attempt to restore the previous reference
and changed sampler properties, verifying readback and unchanged link identities. Reinspect after
any failed mutation; recovery remains tracked if restoration cannot be verified.

Inspection reports dimensions only for already-loaded simple images; it does not read pixels or
probe/reload unloaded files. A source hash at binding describes the current file, **not proof that
an existing buffer is current with that file**. Structural success is not artistic approval.

## Evidence and remaining work

`blender_image_assets_smoke.py` uses disposable factory scenes and isolated profiles on Windows
Blender 4.5.1/5.1.2. It checks real preferences/live permissions, pause/stop, PNG/JPEG, independent
color roles, unused removal, isolated material binding on shared mesh data, orange/blue revisions
with separate roughness, protected pixels/source files, structural comparisons and repeated native
recovery. Matched captures require visual review. No user project or preferences are saved.

Reload/relocation, packing/unpacking/saving, painting/baking, broader formats, nested shader and
compositor image workflows, production-material reuse and responsive decoding remain open. This
advances LOOK-01, not complete [repair-and-texture or 1.0 acceptance](plan-1.0.md).
