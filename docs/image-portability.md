# Packed image versions and raw pixel snapshots

**Save availability:** `project.save` currently refuses Save and Save As before
native/path access; see [the safety change](project-save-safety.md). Fresh-process
results below establish feature serialization through owned fixture setup, not a
safe bridge project-save capability. Earlier typed-save reports are historical.

Unreleased development tools, not included in 0.3.0. These bounded foundations
advance texture portability and durable edited-input recovery; they do not close
the full 1.0 delivery, recovery, compatibility or artistic acceptance gates.

The original packing/loaded restoration tools require Object Mode and **Edit Materials**. A FILE source/target also
requires live **Access External Files**. Packing modifies project datablocks in
memory; it does not grant save consent or write an external file. An explicit
`project.save` retains its **Save Project** and path grants, but its native backend is unavailable.

## Choose the content being preserved

`image.pack_version(image_name, new_name, mode)` creates a unique packed version
without changing the source's pixels, interpretation, material bindings or paths.
The version retains a persistent native ID reference to its exact original and a
fake user so Blender keeps the standalone datablock. The reference increases the
original's user count. Actual packed bytes preserve the image; a fake user alone
is not a pixel backup.

- **FILE_BYTES** embeds the complete original approved PNG/JPEG/reviewed EXR
  file bytes. A dirty source can have different current pixels: this mode does
  **not** claim to preserve those edits. Stored Blender-relative filepaths use the
  saved project's source-resolution policy, with live alias/root/project checks.
- **CURRENT_PIXELS** encodes every actual stored float32 RGBA channel into a
  separate uncompressed raw EXR snapshot. Hidden RGB, signed/HDR data and negative
  zero are retained without color conversion or alpha association. This snapshot
  uses `Non-Color` and `CHANNEL_PACKED` as recovery storage, with the original's
  role recorded separately. It is not an automatically equivalent shader binding.
  This mode reads only the complete already-loaded buffer and can preserve it
  after the backing file disappears. It performs no source-file read or implicit
  load, and returns `source_file_at_read=null`. FILE_BYTES keeps its independent
  approved-path/complete-file-proof requirements.

Names never overwrite/reuse an existing datablock. Source and complete pixels
are checked before and after publication. Failure cleanup can delete only the
new owned unused version with live **Delete Objects** permission; denied cleanup
returns `retained_image_name`, `possible_mutation` and recovery evidence.

Packed data becomes persistent only after a separately authorized `.blend` save.
FILE_BYTES must not be presented as proof of current-pixel recovery, and a packed
hash alone is not a native decoded-pixel or appearance certificate. The tools do
not automatically save, bind a material, reload an original or delete a file.

## Restore the original image identity

`image.restore_pixels(image_name, snapshot_name, allow_shared=false)` accepts only
a CURRENT_PIXELS snapshot referencing that exact original Image datablock. A new
same-name image cannot substitute for the original; the native ID relationship
survives an explicit save and fresh-process reopen.

The target must currently be local, editable, unanimated, already loaded and
float or byte, with the original dimensions, FILE/GENERATED source and color/alpha roles.
Unloaded/missing-target allocation and changed-role or
resized targets are explicitly unsupported. A saved packed FILE_BYTES original
can therefore reopen its old buffer and receive its separately saved raw edited
pixels, preserving the original image ID and existing material consumers.

Recovery validates the snapshot's bounded metadata, exact packed bytes, canonical
EXR layout and every raw channel in standard-library memory. It does not use a
native image getter that might fall back to an external filepath for a malformed
or unloaded snapshot. Its current packed version is the recovery source; editing
a displayed snapshot buffer does not silently replace that stored version.

Restoration affects every consumer of the original ID. More than one reference
beyond the known snapshot/fake-user references requires `allow_shared=true`.
Linked/override/read-only direct consumers block mutation. Evidence lists at most
100 direct consumers and does not claim a complete transitive scene graph.

The write preserves original identity, metadata, packed bytes and consumer scope,
and independently reads back the complete raw digest. It retains both original
and snapshot. A late permission/cancellation/native error can follow a pixel
write: `possible_mutation=true` is intentional, and `CANCELLED` does not mean
rollback. Inspect before retrying; an automatic compensating write could erase
interleaved manual work. Save explicitly if restored pixels must persist.

## Bounds and observed evidence

These synchronous tools support **1,048,576 pixels** and **20 MiB** of packed
bytes. Native transfers, encoding drains, packing and readback can block; no
cooperative 4K or production-latency claim is made. Existing larger painting and
export jobs keep their separate contracts.

The phased `image_portability_probe` fixture uses distinct writer/reader process
instances and profiles. It compares original-file and edited-buffer packing for
PNG8/PNG16/EXR32/raw EXR in COLOR/DATA roles, generated signed/HDR floats and
already-packed images. External source paths are unavailable in the reader.
It checks complete packed bytes/pixels and real material-node bindings, typed
snapshot creation/restoration, denied permissions, denied allocation cleanup and
post-write cancellation evidence.

On the measured Linux Blender 4.3.2 probe, ordinary dirty PNG16 COLOR `pack()` did
not reproduce the edited raw digest. Explicit raw CURRENT_PIXELS snapshots did.
That observation is a reason to retain the two content contracts, not a universal
claim about native Blender packing. Windows 4.5/5.x, actual UI undo/redo,
memory-pressure, 4K, unloaded/identity-wide recovery and full artist acceptance
remain open. This fixture is development evidence, always `NOT_ASSESSED` for
release readiness.

## Byte-buffer recovery and native allocation research

Loaded byte targets now use the same explicit raw snapshot and identity-preserving
write contract. Every snapshot channel must be one of the exact float32 values
returned by Blender's byte getter. A mathematically similar value, hidden clipping
or negative-zero conversion is refused before writing. A final full target digest
after permission/cancellation callbacks preserves newer interleaved manual pixels.

The `image_recovery_probe` fixture demonstrates every byte value across FILE and
GENERATED targets, sRGB/Linear Rec.709/Non-Color, and STRAIGHT/CHANNEL_PACKED roles
on Linux Blender 4.5.14 and 5.2.2. This is distinct from persistence: native
`pack(data=...)` on a GENERATED image retained the current buffer but fresh reopen
recreated generated pixels instead. A separately packed raw snapshot still retains
the edited channels; native generated packing is not an equivalent backup.

Native injection of new packed PNG bytes recovered missing-path, unloaded FILE
byte images while retaining their IDs, metadata and bindings through fresh reopen.
That changes packed bytes, so it does **not** extend `image.restore_pixels`, which
preserves an existing packed payload. Likewise, reloading raw float EXR bytes with
Linear Rec.709/STRAIGHT interpretation changed association and failed exact pixel
recovery. An unloaded-target lifecycle therefore uses the separately explicit contract below.
The probe retains these negative observations and establishes no 4K, native-undo,
Windows, memory-pressure or complete artist-workflow acceptance.

## Reconstruct an unloaded original FILE image

`image.recovery_preview(image_name, snapshot_name, allow_shared=false)` validates
the retained raw snapshot and an unloaded local original FILE image without
loading its missing buffer or reading any external path. It requires **Inspect
Scene**, plus live **Access External Files** for the FILE target; edit permission
is not needed for the read-only preview. Its fingerprint includes process/session
identity, native image identities, snapshot owner/metadata/hash, target roles and
loaded state, old packed bytes, and every bounded direct consumer's identity and
reference count. A fresh preview is required after any measured change or restart.

`image.restore_packed_snapshot(..., expected_target_fingerprint,
confirm_replace_packed_bytes=true, allow_shared=false)` additionally requires
**Edit Materials** and unpaused, non-stopped state. It reconstructs the existing
Image ID from its exact referenced snapshot and **replaces the packed payload**.
The original name/path/color/alpha roles and consumer bindings remain unchanged.
The previous loaded buffer/storage cannot be observed when it is missing; the
explicit preview reports reconstruction dimensions/storage from snapshot metadata.
No external reload, new Image ID, external file write or automatic save occurs.
The retained snapshot remains available. Save explicitly to persist replacement.

The demonstrated unloaded contract supports byte sRGB/Linear Rec.709/Non-Color
with STRAIGHT/CHANNEL_PACKED alpha, and float Non-Color or linear CHANNEL_PACKED.
Associated linear float color is rejected before mutation. Byte channels must
exactly match the native byte getter's representable values; no clipping or
approximation is used. Both this preview and reconstruction retain the synchronous
1M-pixel/20MiB bounds. Native pack/decode/readback are non-preemptible; these tools
do not promise responsive 4K operations.

An input or permission change before publication leaves the target unmodified.
A late cancellation, permission revocation or native failure can follow actual
packed-byte replacement. Errors retain the original and snapshot, report
`possible_mutation`, and do not automatically replay old bytes through revoked
consent. Inspect and confirm recovery explicitly. The phased `image_recovery`
fixture verifies nine role/storage combinations, complete raw channels, vanished
backing files, native ID references, material bindings, permission denial, stale
manual-metadata protection, post-native revocation and separately saved fresh
reopen on Linux Blender 4.5.14/5.2.2. It also proves a new snapshot acquired by an
incoming consumer receives no subsequent metadata/payload/owner writes.
Native UI undo, Windows, 4K, constrained-memory and complete artist acceptance
remain open requirements.

Recovery gates place their final live permission providers before callback-free
lifetime, pause/emergency, mode and identity/consumer checks. A provider that
returns a grant while pausing, stopping or switching to Edit Mode cannot permit
the next pixel, packed-byte or snapshot-metadata write. Owned allocation cleanup
also rechecks Delete Objects after its cancellation callback. Native fixtures
exercise all three state changes at all three publication boundaries.
