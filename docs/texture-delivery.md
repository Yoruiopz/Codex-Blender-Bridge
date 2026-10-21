# Cooperative texture export and verified reimport

Unreleased on `main`, **not in the published 0.3.0 packages**. `image.export_job_start`
connects the reviewed codecs, no-clobber staging, shared file reader and native image loader
through the same scheduler as painting. This advances DELIVER-01 / LOOK-01 / REC-01; it does
not complete durable pixel recovery, all delivery requirements or release acceptance.

## Use the structured job

Choose an Approved Texture Folder in Blender, enable `materials` in Blender/MCP, and grant
**Edit Materials**, **Access External Files** and **Save Project**. That last grant authorizes
the requested external output; this tool never saves the `.blend`. MCP cannot grant consent.
Keep the owning connection open, use Object Mode, and choose an exact unused file path and
unused image name. Formats are `PNG8`, `PNG16`, `EXR32`, `EXR32_RAW`; extensions must match.

```text
image.export_job_start(
  image_name="Painted Canvas", new_name="Reimported Canvas",
  filepath="C:/approved-textures/canvas.exr", format="EXR32_RAW",
  time_limit_seconds=300
)
jobs.inspect(job_id="<exact returned job_id>")
jobs.cancel(job_id="<exact returned job_id>")
```

This is tool-call notation, not a Python fallback. Acceptance is **not completion**. Poll
until terminal; independently inspect the reimport, explicitly bind it, compare an appropriate
material/render capture, and verify native recovery. There is one active paint/delivery job
globally, at most 32 terminal summaries, and no batch nesting or durable/general bake queue.

Inputs are loaded local unanimated RGBA, at most 4,096/axis and 16,777,216 pixels, with reviewed
byte-sRGB, Linear Rec.709 or Non-Color interpretation. Source identity, metadata, complete raw
digest and permitted FILE proof are frozen at acceptance and revalidated before publication,
after checkpoint setup and before success. Sources are never rewritten or rebound. Associated
linear COLOR normalizes only the private copy; undefined additive zero-alpha RGB is refused.
`source_pixels_sha256_float32_le` is the original raw buffer;
`encoded_source_pixels_sha256_float32_le` identifies the possibly normalized encoder input.
`exact_raw_float32_bits_verified` refers to that encoder input, **not** automatic identity
recovery of an associated/sRGB source; `raw_input_float32_recovery_verified` distinguishes them.

The job yields during normalization, encoding, file hash/layout checks and complete decoded
channel comparison. Header/hash checks repeat after native decoding. Reimport uses one
main-thread native checkpoint/finalization, not a boundary held open across timer yields.
Independent pixel references account for PNG quantization, native PNG16 COLOR association,
conventional associated EXR and exact raw FLOAT bits including negative zero. Normalized
PNG channels have a predeclared `2^-23` absolute allowance; PNG16 COLOR uses `2/65535` for
native OCIO variation. Non-raw EXR uses `2^-23 * max(1,abs(reference))`; raw float paths demand
bit equality. All channels are compared; no sample-only or artistic certificate is implied.

### Cancellation, files and native recovery

Before publication, cancel/disconnect/deadline/emergency stops work at a safe point and removes
only unchanged owned staging when live grants still allow it. Revoked consent retains its
exact path. After publication, failures and native undo **never delete the final file**.
Inspect `external_effects`: publication attempted/confirmed/unknown, path/bytes/hash, staging
cleanup/retention, native decode and pixel proof. These effects also survive in terminal
operation history via `job_evidence`; start history explicitly says delivery is not completed.
`checkpoint.list` keeps recovery controls available without scene inspection but redacts
detailed job evidence when `INSPECT_SCENE` is disabled. The local audit is retained unchanged;
`jobs.inspect/list` still require inspection permission. Verification flags record checks
already observed, not a permanent live-state certificate; terminal status and reinspection matter.
The sidebar warns about published files/retained staging, with progress and the shared
**Image Job CPU Budget (ms)** preference (1–8 ms, default 4); polling includes elapsed duration.

Cancellation during native allocation is observed only afterward; failed loader cleanup needs
live `DELETE_OBJECTS`, zero users and no fake user. Denial reports its last observed retained
name. Once the native checkpoint is finalized, subsequent verification yields to other work:
a late failure retains the image for explicitly confirmed snapshot recovery or separately
consented removal, never silently deleting a potentially interleaved user edit. `CANCELLED`
does not mean rollback. A source becoming stale after publication leaves truthful file effects.

The finite 1–300 second deadline does not preempt native copies/decode, complete source
revalidation, synchronous reimport preflight, fsync or undo. These tails are outside the CPU-slice target and can delay polling
and cancellation. A 4K job may need an explicit 300-second deadline; neither slice settings nor
pixel-buffer estimates are real-time, process-memory or production-throughput guarantees.
Full source/native arrays remain; 4K RGBA float arrays alone are 256 MiB each, excluding
Blender/GPU/undo memory. Fresh-process reopening, crash durability, packing/save/reopen,
memory-pressure/8K/UDIM, broader OCIO/format and production artist acceptance remain open.

## Required end-to-end outcome

An agent must explicitly choose an image version, format, exact approved output path and
reimport name; write without unexpected overwrite; reopen the published file; verify all
pixels/declared quantization, metadata, source preservation and appearance; and report what
exists on disk separately from native undo or `.blend` save state. Saving a project alone or
writing an encoder stream is not that outcome. Durable input-pixel recovery remains open.

The full-size path must support existing 4K canvases, cooperative CPU work and bounded staging
buffers without reducing the requirement to a small synchronous export. Cancellation before
publication must not leave a final file; cancellation/failure after publication must retain
truthful path/hash/image/history evidence, not pretend a native undo deleted an external file.
Native decode/transfers remain non-preemptible and must be bounded and permission-gated.

## Internal codec foundation

`pixel_codecs.py` is a standard-library, read-only borrowed-buffer encoder, not a filesystem or
MCP API. It yields immutable bounded byte blocks and empty CPU safe points every 256 pixels,
including highly compressible rows. Input is complete bottom-left float32 RGBA, at most
4,096/axis and 16,777,216 pixels. It never changes the source, opens a path, publishes a file,
loads an image, grants permission, or certifies a delivery. The caller must keep its buffer
frozen and own consent, staging, size/hash checks and publication. Invalid pixels or cancellation
can occur after some bytes have been emitted: those bytes must stay in private owned staging.

| Encoding | Stored file interpretation | Important limit |
| --- | --- | --- |
| `PNG8` | Unassociated RGBA8; COLOR encoded sRGB, DATA raw normalized channels | Quantized, not lossless float recovery |
| `PNG16` | Unassociated big-endian RGBA16; same COLOR/DATA distinction | Native color decoder returns linear associated floats, not the encoded samples |
| `EXR32` | Single-part uncompressed RGBA float scanlines; COLOR conventionally premultiplied, DATA independent | COLOR premultiplication loses hidden zero-alpha RGB; not exact raw-channel recovery |
| `EXR32_RAW` | Unmodified float32 linear/raw channels, including hidden zero-alpha RGB | Color/raw reopen must explicitly use CHANNEL_PACKED; ordinary straight/premultiplied decode is not raw recovery |

COLOR accepts reviewed straight linear input, or explicitly declared byte-sRGB input converted
to linear for EXR. DATA has no color transform; EXR permits signed/HDR finite data in all four
channels. COLOR alpha stays `[0,1]`. PNG refuses signed/HDR channels rather than clipping them.
No view transform, exposure, grading or implicit interpretation of arbitrary OCIO roles occurs.
Rows are flipped explicitly into file order; EXR channels are alphabetic A/B/G/R, float32 little
endian. Storage follows the [PNG specification](https://www.w3.org/TR/png-3/) and
[OpenEXR layout](https://openexr.com/en/latest/OpenEXRFileLayout.html); conventional EXR color
association follows the [OpenEXR technical introduction](https://openexr.com/en/latest/TechnicalIntroduction.html).

## File pixels are not necessarily Blender buffer pixels

Native probes on Windows Blender 4.5.1/5.1.2 distinguish:

- PNG8 COLOR: `Image.pixels` exposes encoded unassociated values.
- PNG16 COLOR with normal straight-alpha loading: float ImBuf is linear and associated.
  RGB hidden by zero alpha is lost in that normal decoded buffer, although it exists in the file.
- Conventional EXR32 COLOR with PREMUL: the float buffer is associated.
- Raw EXR with explicit CHANNEL_PACKED, and DATA PNG16/EXR: independent raw channels survive.

The independent byte parsers verify file encoding exactly. Native PNG16 color conversion is
compared separately to a standard-sRGB double reference with an explicit `2/65535` absolute
allowance for the native OCIO float path; that is not a universal OCIO precision guarantee.
`alpha_mode` alone describes file loading/saving representation, not proof of buffer association.
Blender's [pixel RNA implementation](https://github.com/blender/blender/blob/v4.5.1/source/blender/makesrna/intern/rna_image.cc)
exposes the underlying float buffer directly. Inspection reports raw values, not a guessed
unassociated color or display transformation.

The render probe also found a generated-float transparency difference between 4.5 and 5.1:
4.5 rendered an API-written straight float canvas too bright through a transparent material.
New bridge-generated canvases/paint versions now keep independent requested straight RGBA
under native CHANNEL_PACKED, avoiding implicit coupling and preserving hidden RGB. A real
transparent/emission Cycles CPU camera comparison against PNG8/PNG16/conventional EXR references validates
the intended color/opacity, not only readback. Existing image datablocks are never relabeled.
This comparison explicitly connects Alpha to opacity. CHANNEL_PACKED leaves Color-only RGB
independent; it does not silently darken it by unused alpha or create transparent shader links.
Rebinding into a different alpha-unused graph still needs inspection and appearance review.
Reviewed associated linear COLOR FILE sources normalize before brush math; inspector and mask
reads remain raw. Additive zero-alpha associated RGB is not guessed as straight color.

## Internal approved-file staging

`texture_staging.TextureStaging` is an internal resource for the existing codec, not a
registered tool, arbitrary-file writer or image loader. Construction does not probe paths.
Every subsequent IO step requires live `EDIT_MATERIALS`, `ACCESS_EXTERNAL_FILES` and
`SAVE_PROJECT` before touching external paths. The typed job supplies Blender's live
approved-folder preference, cancellation, main-thread dispatch, audit/history and checkpoint
boundaries; this class cannot supply those by itself.

- Require the user's exact PNG/EXR output path under an existing approved subdirectory.
  Reject traversal, UNC/network/mapped drives, alternate streams, reserved names, trailing
  dots/spaces, volume roots, missing parents and symlink/reparse-point directory ancestry.
  Never make directories, rename to avoid a collision or overwrite an existing target,
  including a directory or dangling link.
- Write only codec-emitted bounded blocks to a uniquely created owned staging file in that
  parent. A full 4K float payload is not copied into a file-sized `bytes` object. Flush/fsync
the file and verify its entire SHA-256, size and identity in 64 KiB read steps before sealing.
  Invalid pixels, IO failure, pause/stop or cancellation can leave private partial bytes,
  never an automatically published final output.
- Explicit publication uses a same-filesystem hard link: atomic create-if-absent, with no
  replace, rename or copy fallback. An unsupported filesystem fails closed. A competing
  actor creating the target wins without having its bytes overwritten. Revalidate live
  permissions/location/owned identity and retain `file_published` immediately after linking,
  before any late check that could fail. A separate streaming proof checks published bytes.
  `publication_attempted` is recorded before the system call. If the call raises after a
  possible filesystem effect, `publication_outcome_unknown=true` requires reinspection of
  the exact target: `file_published=false` means unconfirmed, not proof that no file exists.
- Cleanup only unlinks the exact unchanged owned staging entry. It does not delete images
  or require a scene `DELETE_OBJECTS` grant, and never removes the published path. Revoked
  edit/external/save consent, changed identity/location or IO failure retain staging and its
  explicit path/status for recovery. Cleanup closes handles even on denial. The caller must
  retain this evidence on every terminal path, including generator close/disconnect.
  Streaming read proofs recheck the approved folder before every 64 KiB read, not only at
  the beginning/end; changing that approval stops the next chunk.

On Windows, ordinary-directory handles pin the entire output ancestry without delete sharing
until cleanup, preventing tested rename redirection. Attribute-only handles were experimentally
insufficient; native tests now verify exclusion and release with real directory read handles.
This uses [CreateFile sharing contracts](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
not window APIs or system-wide settings. Other platforms currently use resolution/identity
checks; namespace-race exclusion against a hostile local process is **not** claimed. These
are consent/accident guards, not a filesystem security sandbox or cross-platform RC acceptance.

The hash proof certifies bytes emitted by this resource's reviewed bounded codec, not arbitrary
PNG/EXR inputs. `native_decode_verified`, `pixel_roundtrip_verified` and
`crash_durability_verified` remain false in resource evidence. The job promotes decode/pixel
flags only after its separate native readback/comparison stages; these are observed checks,
not an everlasting live-state certificate. Hard-link creation
does not prove crash/power-loss durability, `.blend` packing, native undo of external files,
fresh-process reopening or recoverability of an existing pixel buffer. Fixture output files
are explicitly disposable and removed by the fixture's temporary-directory owner afterward.

## Remaining delivery and release acceptance

1. Finish platform/race acceptance of the integrated approved output/staging policy,
   rather than treating Windows path tests as all-OS proof.
2. Extend terminal-history/error/cleanup evidence through broader mixed-editor and recovery
   interleaving. The typed job now retains known published/uncertain/temporary file effects.
3. Shared streaming preflight and reviewed public EXR/large-PNG import are implemented.
   Delivery jobs integrate their IO/CPU safe points; broader-format, race, synchronous reimport
   tails and memory-pressure acceptance remain, not a claim of general decoder safety.
4. Extend the implemented typed export/reimport workflow's compatibility/ownership acceptance;
   preserve Blender-authoritative edit/file/save grants and independently consented deletion.
5. Extend the implemented 4K cooperative lifecycle under memory pressure and broader workloads;
   preserve the guarded image publication and truthful external-file/native-undo distinction.
6. Fresh-process/reopen, complete numeric verification and matched material/render evidence,
   including raw recovery, quantization, alpha-zero, HDR/data, cancellation, path races,
   preservation, invalid context and deletion-denied failures.
7. Explicit packing/approved `.blend` save/reopen and production delivery/upgrade acceptance.

The codec and native fixtures are development evidence only. They do not close DELIVER-01,
REC-01, JOB-01, PAINT-01 or any full-artist/release gate. Native tests use the
[non-interrupting runner](native-testing.md), never a user's project or visible fallback.
