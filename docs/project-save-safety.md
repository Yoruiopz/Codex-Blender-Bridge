# Project saving is blocked pending native side-effect control

Published 0.4.0/0.5.0 alphas and current development source: **`project.save` returns
`NOT_IMPLEMENTED` for both
current-file Save and Save As.** The prior alpha's native save capability is
unavailable in these versions. The tool name, optional `filepath`,
permission metadata and V1 envelopes remain compatible; successful saving is
not supported. Earlier published artifacts remain available unchanged.

`SAVE_PROJECT` remains required. Supplying `filepath` also requires
`ACCESS_EXTERNAL_FILES`; the handler checks both grants together in its final
permission snapshot. Permission denial and canonical cancellation, expiry,
disconnect, pause or emergency stop retain their existing error codes. With
valid authority, the handler refuses before accessing Blender, resolving or
probing a destination, creating staging files or invoking a native save.
Expected errors report `execution_started=false`, `native_save_invoked=false`,
`project_saved=false` and `bridge_file_writes=false`. These facts describe the
bridge handler, not arbitrary code in Blender or a permission provider.

A known no-write save refusal does not finalize an older deferred editor-session
snapshot. Other tools cannot opt out of failure finalization by supplying similar
error details. Unexpected provider failures remain conservative and require
inspection. No native callback is removed, preference changed or hidden internal
memory patched to make saving appear safe.

## Why a last permission check is insufficient

Both `wm.save_mainfile` and `wm.save_as_mainfile` reach
`wm_save_as_mainfile_exec` and `wm_file_write`. Native asset libraries register
C-level `SAVE_POST` callbacks independently of `bpy.app.handlers.save_post`.
Their global catalog-save flag defaults to true. Loaded catalog services can
read or rewrite files outside the requested project destination, including a
catalog definition file with deletions but no dirty flag. An empty Python
handler list, an asset-free Main or `asset.catalogs_save.poll() == false` does
not prove those native services absent. No reviewed public RNA API enumerates
or disables the relevant state.

Exact native source review covers Blender **4.5.14 LTS**, commit
`62c1db4208e862312bc36db5bc15d4a6dbcfa3e3`, and **5.2.2 LTS**, commit
`d13f752e3b9c4f8c261cda552b1021f8bcc0382c`. The retained evidence includes:

- `source/blender/windowmanager/intern/wm_files.cc` and `wm.cc`; exact-byte
  receipt SHA-256 `7bd654cff7f1ff7eafda0096b6701eba0d2fa9de2f514a64f48c8d606093dcfe`.
- `source/blender/asset_system/intern/asset_library.cc` (`on_blend_save` and
  callback registration) and `asset_catalog.cc` (`write_to_disk_ex`); retained
  Git-blob-verified exact copies for both native commits.

Native saving can also flush edit/sculpt buffers, pack data, update interactive
recent-file and OS-document history, refresh bookmarks in 5.2, and clear hidden
recovered/undo-flush bookkeeping. A destination existence check, canonical
cancellation guard, clean authored-state comparison or `copy=True` cannot bound
all of these effects. The removed legacy backend also lacked atomic destination
publication and a final lifetime check after its additional permission provider.

`libraries.write` is not an approved whole-project replacement. Full Main/UI
serialization has native failure evidence; asset-only serialization omits state
or changes fake-user semantics. There is no supported substitute save backend.
Arbitrary Python remains disabled by default and does not satisfy this missing
structured workflow.

## What fresh-process fixtures establish

Selected isolated native writer fixtures first prove the public typed refusal,
then deliberately serialize their own disposable input through a **fixture-only
native Save As**. The reader can still test texture pixels, bindings, rigs,
actions, variants or other serialized feature state. This setup is not a public
bridge tool, safe filesystem boundary or production-delivery result. Writer
evidence states `fixture_native_save=true` and
`bridge_safe_project_save_verified=false`; it also checks that current-file and
same-path public saves refuse without rewriting the fixture file. Recovery-job
fixture serialization runs on its owned Blender main thread.

Earlier successful typed-save reports are historical evidence for their old
source fingerprints. They do not qualify this source or establish controlled
native save effects. The new small denial fixture checks permissions, late
caller/stop changes and zero bridge save/Blender-reader entry. Selected Linux
fixtures do not qualify Windows or installed packages.

Safe authorized project saving, complete portable `.blend` delivery and fresh
production-project reopen remain **mandatory open 1.0 requirements** in the
[execution plan](plan-1.0.md) and [readiness gates](release-1.0-readiness.md).
This mitigation blocks unsafe work; it does not complete those capabilities or
replace their acceptance evidence.
