# Shader interface removal research probe

Status: the fresh-created probe reached removal and AFTER on Linux 4.5.14 and
5.2.2, then failed its full-state native-undo comparison. The distinct
persistent-loaded-fixture variant passed twelve removal/undo/redo cases and a
fresh-process reader on each Linux build at source `31eb64d`. This adds no public
removal or conversion tool and closes no LOOK-01, recovery, platform or 1.0 gate.

The current tools support interface rename, flat reorder and definition-default
edits. Existing paired Linux evidence demonstrates that an unlinked Float to
Vector conversion retains its identifier but loses definition and instance
defaults. Reverting its type does not recover those values. The loaded-fixture result below demonstrates bounded unused socket removal;
fresh-created recovery and public removal remain open. See
[the existing lifecycle evidence](shader-interface-lifecycle.md).

Source-reviewed native behavior is pinned to Blender 4.5.14 commit
`62c1db4208e862312bc36db5bc15d4a6dbcfa3e3` and 5.2.2 commit
`d13f752e3b9c4f8c261cda552b1021f8bcc0382c`. Their
[4.5 RNA removal](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/makesrna/intern/rna_node_tree_interface.cc#L735)
and [5.2 RNA removal](https://github.com/blender/blender/blob/d13f752e3b9c4f8c261cda552b1021f8bcc0382c/source/blender/makesrna/intern/rna_node_tree_interface.cc#L867)
call native item deletion and invariant updates. Native identifier RNA is
read-only; both new-socket and exposed item-copy paths allocate a fresh UID.
Deleting and recreating/copying a same-named socket has no supported RNA inverse
that restores its old identifier. These source observations motivate the probe;
they are not native execution evidence.

Run this opt-in interactive, writer/reader case only through the isolated native
runner, with explicit Blender executables and a new output directory:

```bash
python scripts/run_blender_checks.py --blender /absolute/path/to/blender --case shader_remove_probe --output /new/owned/output
```

The new source-backed loaded-asset diagnostic uses a separate selector:

```bash
python scripts/run_blender_checks.py --blender /absolute/path/to/blender --case shader_remove_loaded_probe --output /new/owned/loaded-output
```

Follow [native test isolation](native-testing.md). Windows must obtain a private,
non-input desktop or fail closed. The runner starts distinct factory processes
for the writer and reader and verifies their process identities and success
markers. A partial journal or a normal process exit without the required marker
does not establish success.

The writer reuses the existing bounded shared shader fixture: two material roots,
a parent with two leaf instances, a World and Light, and an unrelated protected
material/group. It adds direct leaf instances in both materials and the World,
plus a second Group Input and Group Output. Twelve cases remove one unused
Float, Int, Bool, Vector, Color or Shader socket in each direction. Every target
is placed before surviving peers to exercise native index shifts. Input instance
defaults differ from definition defaults and between consumers.

"Unused" requires no link at any matching socket: interface INPUT maps to Group
Input outputs and every instance input; interface OUTPUT maps to Group Output
inputs and every instance output. The projection is scoped to the exact leaf and
its actual instances. An unrelated group with the same socket identifier remains
protected. Removed RNA wrappers are never read afterward.

For every removal, the probe requires exact surviving interface order, identifiers,
types, primitive socket/interface/node configuration, defaults, link endpoints and
validity/mute state, graph ownership, material-slot bindings and caller context.
Tree, node and root-owner native pointers must remain identical across that
single removal. Unexposed native ID tags are outside the proof; the exposed
`is_runtime_data` property remains measured. Image pixels, shader evaluation,
all scene properties and arbitrary node/dependency families are outside this
fixture. The proof is bounded to 16 trees, 64 nodes/128 links/64 interface items
per tree and one MiB of serialized shader preservation state.

Native interface active index/identifier and independent selection flags are
recorded separately, with both removed-active and surviving-active cases.
Virtual Group Input/Output socket records are also protected. This probe observes
native interface UI changes; it does not
silently restore them or claim they are preserved. An eventual public removal
contract must explicitly define and qualify its UI-selection policy.

Each case creates actual native BEFORE and AFTER snapshots, performs native undo,
reacquires every Blender wrapper, and requires the original identifier and complete
original shader state. Native redo must restore the exact removed shader state.
UI restoration is measured separately. Re-adding a same-named socket is never
used or described as identity-preserving recovery. A failed native undo or state
comparison fails the writer and retains its last measured journal stage. This
does not establish general recovery under interleaved manual work or memory pressure.

## Measured fresh-created limitation and loaded-fixture origin

The frozen fresh-created source `ade6eb4a95a8e72cf6fca27596b408305abd8678`
passed the first unlinked Float input removal and its AFTER snapshot on both
Linux versions, without a crash. Native undo then changed embedded
`World::Probe World.is_runtime_data` from true to false; 4.5 also changed the
embedded Light tree. All compared shader fields beyond those status booleans
matched. The writer failed and no reader started. This remains a recovery
limitation, not a successful removal/undo or serialization result. Its report is
retained at `build/shader-remove-native-20261023/native/report.json` in the
original workspace (SHA-256
`acb606f073c655d3add29c2e8218ec165fd47343d4966ef246f2bfde064daa7d`).

The pinned source explains why the status matters. The ID RNA getter returns
true for `ID_TAG_NO_MAIN` and other non-Main/evaluated states independently of
the explicit `ID_TAG_RUNTIME` bit. Its dynamic editability callback rejects
setting that status on such IDs. Embedded creation requests
`LIB_ID_CREATE_NO_MAIN`; World and Light writers explicitly write their embedded
trees. Undo serialization retains `ID_TAG_RUNTIME` but omits `ID_TAG_NO_MAIN`,
and the embedded reader reconstructs tags with `id_tag=0`. Ordinary setup-file
serialization/read also reconstructs these IDs without the original NO_MAIN
tag. This is a source-backed lifecycle transition, not a harmless-field exclusion.
The [4.5 getter/editability](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/makesrna/intern/rna_ID.cc#L593),
[4.5 undo tag policy](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/makesdna/DNA_ID.h#L947)
and [4.5 embedded read](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/blenloader/intern/readfile.cc#L2127)
have corresponding code in the pinned 5.2 source. The exact source excerpts,
blob identities and causal trace are retained at
`build/shader-remove-runtime-source-20261023/runtime-transition-trace.json`.

`shader_remove_loaded_probe` explicitly serializes its owned factory seed,
reloads it, and verifies that **only the source-predicted runtime-status
booleans** changed in the complete shader core. This setup occurs before any
measured removal baseline or BEFORE checkpoint. Every participating shader,
root-owner, material-binding and context ID must then report literal
`is_runtime_data=False`. The property remains in every removal, undo, redo and
reader comparison. The status is never assigned on Blender data; only the
expected primitive comparison record predicts the documented read transition.
No user data is normalized. Writer and reader success markers name the loaded
variant and both retain explicit `PERSISTENT_LOADED_OWNED_FIXTURE` provenance.

The first loaded attempt, source `ba7c7db02d93c41c01ca0ad9a03154c486f3bd30`,
stopped before removal on both versions: the immediate post-load snapshot had no
`context.selected_objects`. Its failed report remains separate at
`build/shader-remove-loaded-native-20261023/native/report.json` (SHA-256
`67eb933c9fda300f0154f1d50caea856b1230e55970f5a76f3be3ef90fa2f031`).
Blender explicitly [clears the interactive window context after file loading](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/windowmanager/intern/wm_files.cc#L866),
and [native undo requires an active screen](https://github.com/blender/blender/blob/62c1db4208e862312bc36db5bc15d4a6dbcfa3e3/source/blender/editors/undo/ed_undo.cc#L533).
The correction returns to the actual timer event loop exactly once after each
owned load, then reacquires all RNA objects and compares the same complete core
and visible-selection context. It requires a window and screen on that next
callback and checks native operator polls before invocation. There is no context
retry, alternate selection definition, empty fallback or comparison exclusion.
Only primitive records, paths and the bridge service cross the load handoff.
The corrected source is pending native execution; portable event-order tests are
separate from native evidence. Both exact-version source anchors are retained at
`build/shader-remove-postload-context-source-20261023/source-anchors.json`.

A positive loaded-fixture result would apply only to that origin. A future
public preflight could conservatively require literal false for all participating
IDs and refuse other states before checkpoint/mutation. It must not silently
alter flags, condition a user's project through saving/undo, or exclude the
property from preservation evidence. Fresh-created shader recovery remains
mandatory open work for full LOOK-01.

The final removed state is serialized only through labeled, runner-owned fixture
setup. The helper also proves public `project.save` refuses before native/path
access. A separate reader opens that disposable project and verifies all removed
identifiers remain absent and every surviving shader record/binding matches.
This is serialization evidence, not safe project saving, production delivery or
a durable backup. No rendered appearance claim or visual review is made.

After positive source-matched native results, a possible next bounded contract is
fingerprinted, explicitly shared-consented removal of an unlinked interface
socket under the existing local, flat, unanimated shader scope. Its deletion
result must describe only surviving identifiers as preserved. Automatic socket
recreation cannot reuse the old native identifier and must not be presented as
rollback. Linked removal, animated paths, panels and conversion remain mandatory
separate work; this probe does not defer them from the full 1.0 target.
