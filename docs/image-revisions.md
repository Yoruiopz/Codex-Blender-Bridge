# Versioned texture refresh and relocation

Unreleased on `main`; not part of the published 0.3.0 packages. `nodes.refresh_image` refreshes
an Image Texture node from disk, or repairs its source path, by loading a **new image version**
and rebinding that node in one logical operation. It does not reload or modify the old image.

## Why versioned refresh is explicit

Native probes on Blender 4.5.1 and 5.1.2 changed a file from red to blue, called
`Image.reload()`, pushed an after-point and undid it. The buffer remained blue: global undo
did not restore the previous pixels. A separate new image/binding version retained the red
buffer and restored the original binding/pixels in the same probe. Blender also documents
that image datablock copies do not duplicate modified pixel buffers.

This is a reason to use versioned revisions, **not** to claim in-place reload is solved or to
drop it from the full 1.0 target. Durable pixel snapshots, image-identity-preserving edits,
paint-stack/memory-pressure recovery and responsive decoding remain open requirements.
Retained image caches and native undo history are not durable backups. Buffer freeing, file
reload, saving/reopening and history eviction can change what remains recoverable.

## Contract

`nodes.refresh_image(material_name, node_name, new_image_name, filepath?, group_path?,
allow_shared=false)` belongs to `nodes`, and requires **both `EDIT_MATERIALS` and
`ACCESS_EXTERNAL_FILES`** in Blender. Enable the toolset and choose an Approved Texture Folder
as described in [image assets](image-assets.md). MCP cannot grant permissions or choose the folder.

- `new_image_name` must be unique, explicit, non-control UTF-8 text of at most 63 bytes.
  Nothing is overwritten, implicitly reused or renamed to make room.
- The exact target must be an already-bound Image Texture node at the material root or an
  explicit [group-instance path](shader-groups.md), at most eight levels. An empty binding
  requires the normal load/bind workflow instead.
- Omit `filepath` to reread the bound FILE image's source. Supply an approved absolute path
  to relocate it, including when the previous source is missing/unloaded. A GENERATED source
  requires an explicit filepath; the new version is FILE, not generated or packed.
- The old image must be local/editable/non-override, single-view FILE or GENERATED. Its
  loaded/unloaded state, dirty pixels and packed contents are not changed. Linked, movie,
  sequence, tiled/UDIM or multiview sources are unsupported, not silently converted.
- Object Mode and complete material/group ownership are required. Shared material or parent
  group use needs explicit `allow_shared=true`; this acknowledges every reported user of
  the changed node. A shared old image alone needs no shared-image mutation consent, because
  the old image and its other bindings are not edited. Isolate material/group instances first
  when the request is to affect just one object.
- Direct action/driver/NLA animation on the material, chosen tree or image is unsupported.
  This is not a complete transitive/evaluated animation analysis.

Normal graph bounds apply: 256 nodes, 1,024 links and 128 interface items. Source reads reuse
the shared [approved PNG/JPEG/reviewed EXR preflight](image-assets.md), format/dimension/pixel limits, live authorization and
before/after source checks. A changed file between decoding and binding rejects the revision.
An explicit relocation reads **only the new source**, not a missing or disallowed old path.
Decoding is native and not interruptible; no responsive-job guarantee is implied.

The new version inherits the original's color space and alpha interpretation. Node interpolation,
projection and extension, all target socket identifiers/types/defaults, and semantic graph links
are compared before/after. Changes with incompatible native side effects fail with measured
restoration evidence. This does not certify arbitrary node/image-user settings, evaluated
dependencies, source/file currency after the call, pixel equivalence or material appearance.

`image.load` also accepts optional `alpha_mode`: `STRAIGHT`, `PREMUL`, `CHANNEL_PACKED` or `NONE`.
Omission preserves the native default. Color/alpha roles are applied before authorized buffer
verification, since changing alpha interpretation can invalidate the cache. `image.inspect`
reports alpha mode and already-loaded buffer flags without loading an unloaded image.
Dirty/float flags are null when their buffer evidence is unavailable; floating-point reads
are limited to already-loaded simple images because that native getter can itself acquire a buffer.

## Evidence and failure behavior

A successful response explicitly says `revision_mode="new_image_for_node"`,
`image_identity_preserved=false`, `previous_buffer_reloaded=false` and `file_written=false`.
It includes both image summaries, source evidence, retained sampler settings and material/group
scope. This is a new datablock, not a rename or in-place pixel mutation. The normal main-thread
dispatcher provides one history/checkpoint boundary for the coherent load-and-bind operation.

On a decode failure, the existing loader owns scoped cleanup of its new image. After decoding,
binding or post-verification failures attempt to restore the old binding/samplers and remove
only the newly created zero-user, non-fake-user image with live `DELETE_OBJECTS` consent.
Normal successful refresh still needs no deletion grant. Denied cleanup keeps the new image,
reports `cleanup_permission_denied=true` and cannot claim complete rollback even if the old
binding is restored. Inspect and use confirmed recovery or separately authorized unused removal.
Unexpected users are never forcibly unlinked, even when deletion is permitted.
`rollback_verified`, `possible_mutation`, `execution_started` and `verification_required`
report the measured outcome. An unresolved partial revision requires reinspection and confirmed
snapshot recovery where available; no blanket transaction/rollback guarantee is made.

## Artist workflow

1. Inspect scene/mode/selection and the exact image node, source metadata and shared users.
   Record protected objects/group contents and matched material views. Create a checkpoint;
   isolate the target material/group if needed.
2. Refresh under a new version name, or provide the new approved filepath for relocation.
   The bridge reads source files; it does not write, delete, pack or unpack them.
3. Reinspect the new/retained images and changed node. Compare protected group content and
   relevant structural snapshots, then capture a matched material/rendered view and refine.
   Root `shader_inputs` covers binding metadata, not nested contents or pixels; compare those
   separately. A source hash is not an artistic or full pixel-content certificate.
4. For a failed/unwanted revision, inspect its effects, confirm logical native recovery and
   verify the restored binding/pixels/appearance. Do not assume a label guarantees retention.
5. Save only in the agreed workflow with `SAVE_PROJECT`. Unused old versions are not given
   fake users or durable backups; explicitly decide dependency/retention policy before delivery.

## Native coverage and remaining work

`blender_image_revisions_smoke.py` exercises a nested orange/blue/green texture workflow,
same-file refresh after an external fixture change, relocation, missing/unloaded-source repair,
dirty generated and packed FILE originals, alpha/sampler preservation and staged native undo.
It independently hashes complete small fixture pixel buffers/packed bytes, compares protected
group state and retains matched before/revised/recovered/protected views. Scope/permission/
pause/stop/unsupported-mode/animation rejections and deliberately incomplete cleanup are tested.
No user project/preferences are saved. Run through the [non-visible test runner](native-testing.md).

This is not a representative production prop or full LOOK-01 acceptance. In-place image editing,
durable pixel recovery, packing/unpacking/saving, full painting/baking, compositor images, broader
formats and jobs remain mandatory in the [full 1.0 plan](plan-1.0.md).
Separate [bounded UV-image brushes](texture-painting.md) now create generated paint versions;
they do not solve these identity-preserving or durable image lifecycle requirements.

Native data semantics: [Blender Image API](https://docs.blender.org/api/4.5/bpy.types.Image.html).
