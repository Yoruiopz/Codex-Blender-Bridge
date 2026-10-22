# Portable asset .blend helper research

This is an opt-in native experiment, not a public delivery tool or a safe project
saver. `project.save` remains unavailable under the [save safety contract](project-save-safety.md).
There is no worker backend in the add-on or MCP server. Full production `.blend`
delivery and authorized current-file saving remain required for 1.0.

## Three fresh processes

The isolated native runner has three explicitly selected research cases, in this
order: `portable_blend_writer_probe`, `portable_blend_worker_probe`, and
`portable_blend_reader_probe`. They share one task-owned bundle within each
runtime's new evidence directory. Existing two-phase cases are unchanged.

| Process | Measured operation |
| --- | --- |
| Interactive writer | Build a tiny static fixture, record its exact asset projection and original per-ID fake-user flags, then call `libraries.write(fake_user=True)` with an explicit asset closure. Verify that live source identities, content, filepath, dirty state and context are unchanged. Make original external PNG paths unavailable. |
| Background helper | Open only that library payload, prove its predicted contents and complete packed image bytes, load the verified packed pixels, restore the retained per-ID flags, then save a new file within the task-owned bundle. |
| Interactive reader | Open the helper's output in a third process and compare the complete retained fixture projection, original flags, full 2×2 packed RGBA pixels, color/alpha roles, bindings, geometry, UVs, units, camera values, intended orphan and inert metadata. |

The handoff binds exact native build, fixture source hash, input file hash,
preceding JSON hash, process token and PID. Wrong ordering, reused output paths,
unknown IDs or a projection mismatch stop the experiment. Fake-user restoration
uses the vector captured before serialization; output values never become the
expected flag vector. The original editing process receives no flag edits.

The fixture uses at most 32 asset IDs, 64 total IDs including native UI, two 2×2
packed images and one triangle. It excludes linked data, overrides, animation,
drivers, modifiers, constraints, custom normals, asset metadata, scripts and
external payload dependencies. UI IDs are excluded from the library closure.
This is an asset-only file, not preservation of an editor layout or an entire
arbitrary project.

## Native camera compatibility data

Strict raw equality on Blender 4.5.14 first refused the opened library: its
Camera acquired a `cycles` custom-property group containing twelve panorama
values. That failed result remains separate from the later contrast experiment.

Exact native `camera.cc` explains the addition. For non-undo serialization,
`camera_blend_write` makes a temporary copy of ID properties, writes compatibility
properties from native Camera fields, serializes the copy, then restores the
source properties. This is a write-time compatibility representation; the
experiment does not attribute it to a Python Cycles load handler.

The contrast computes those twelve expected values from the source Camera RNA
and native enum integer **before** `libraries.write`. It accepts only that exact
predicted addition on the pinned 4.5 build. The original raw snapshot remains
unchanged. The output reports `raw_custom_storage_preserved=false` and retains
the declared compatibility conversion. No compatibility property is deleted,
and there is no general normalization or output-readback adoption. The tested
5.2 output retains the original empty Camera custom storage; the experiment does
not establish a general reason for that difference.

Exact upstream source identities:

- Blender 4.5.14: commit `62c1db4208e862312bc36db5bc15d4a6dbcfa3e3`,
  `camera.cc` Git blob `712873f0c5380d6ce03fab756f4ed8b945fd3a6a`,
  SHA256 `f54d88a810e5cafb79228a3189adbf9071d457737c4d5499758f942c5eae2515`.
- Blender 5.2.2: commit `d13f752e3b9c4f8c261cda552b1021f8bcc0382c`,
  `camera.cc` Git blob `98cae6915f6d5da4531edd1abdfec450e2934222`,
  SHA256 `31f0843ec2e683f60525394df3589fc8d62bcbcc0f6642e19096dcc7fe536ae6`.

## Operational isolation and its limits

Each process uses `--factory-startup --disable-autoexec`, a new owned 0700
HOME/config/cache/data/runtime/temp/cwd profile and a small environment allowlist.
It records factory preferences, bundled add-ons and callback descriptors before
opening the payload. No user credentials or arbitrary Python/Blender path
variables are inherited. The helper's disposable save preferences explicitly use
thumbnail `NONE` and backup count zero; this changes no artist preferences.

The interactive phases require the [isolated native runner](native-testing.md)
and an authenticated, task-owned display. Linux `strace` file/network observations
and a task-owned sentinel record observed effects. These are not an OS filesystem
or network sandbox, a complete absence-of-side-effects proof, or Windows
qualification. Hidden native catalog callbacks remain outside a public RNA
enumeration. No existing output is overwritten or published to an approved artist
destination by this experiment, and no source or evidence files are deleted.

Native serialization is synchronous and non-preemptible. This experiment has no
production job ownership, cancellation, reconnect, staging-publication, overwrite,
crash-durability or recovery contract. It provides no 4K, constrained-memory,
installed-package, visual artist or scenarios A–F acceptance. The complete artist
workflow, Windows qualification and all release gates remain open.

Source-matched manifests, earlier failed runs, trace files, process records and
test reports remain under the research worktree's
`build/portable-blend-worker-*` directories. Local retention is not permanent
external release-evidence retention. A passing research case does not enable a
delivery capability or authorize publishing a release.
