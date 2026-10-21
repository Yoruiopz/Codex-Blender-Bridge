# Packed image versions and raw pixel snapshots

Unreleased development tools, not included in 0.3.0. These bounded foundations
advance texture portability and durable edited-input recovery; they do not close
the full 1.0 delivery, recovery, compatibility or artistic acceptance gates.

Both tools require Object Mode and **Edit Materials**. A FILE source/target also
requires live **Access External Files**. Packing modifies project datablocks in
memory; it does not grant save consent or write an external file. An explicit
`project.save` still independently requires **Save Project** and its path policy.

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
float, with the original dimensions, FILE/GENERATED source and color/alpha roles.
Unloaded/missing-target allocation, byte-buffer restoration and changed-role or
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
memory-pressure, 4K, unloaded/byte/identity-wide recovery and full artist acceptance
remain open. This fixture is development evidence, always `NOT_ASSESSED` for
release readiness.
