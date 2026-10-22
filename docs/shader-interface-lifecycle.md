# Shader interface lifecycle and native evidence

**Save availability:** `project.save` currently refuses Save and Save As before
native/path access; see [the safety change](project-save-safety.md). Fresh-process
results below establish feature serialization through owned fixture setup, not a
safe bridge project-save capability. Earlier typed-save reports are historical.

Unreleased development now includes two typed tools, following the native research
below. `shader_group.interface_add` remains the existing structured append operation.
Removal, conversion, panels, animated interface maintenance and broader shader
lifecycle remain required work in the [1.0 plan](plan-1.0.md). No 1.0 acceptance or
published-package support is implied by these development results.

## Typed preview and edit

Both tools belong to `nodes`. Inspect the current scene, mode and exact group first.

| Tool | Contract | Blender permissions |
| --- | --- | --- |
| `shader_group.interface_preview(group_name, socket_identifier, operation, new_name?, to_index?, value?)` | Read-only exact bounded scope and planned change; returns a SHA-256 fingerprint binding the full live scope and exact operation | `INSPECT_SCENE` |
| `shader_group.interface_edit(..., expected_fingerprint, allow_shared=false)` | Recheck the same scope/operation, apply one owned change, independently verify the predicted complete result and attempt guarded compensation on failure | `INSPECT_SCENE`, `EDIT_MATERIALS` |

The operations are `RENAME` with `new_name`, `MOVE` with a zero-based final
same-direction `to_index`, and `SET_DEFAULT` with `value`. Unrelated optional fields
are rejected. Names are exact non-control UTF-8, at most 63 bytes. Sockets are
identified by their native stable identifier, never by an assumed list position.
Both input and output sockets support rename/reorder; Float, Int, Bool, Vector and
Color definition defaults use strict values and native range checks. Floats and
vector/color components are bounded to magnitude one million and normalized to
native float32. Integer defaults are signed 32-bit; Shader sockets have no scalar
default. Existing instance values and Group Input/Output socket defaults remain
protected. Input definition defaults initialize newly created consumer inputs;
changing a definition default does not rewrite existing consumer inputs.

Preview and edit require Object Mode, local editable non-override affected owners
and no animation data on affected definitions/root owners or their binding owners.
Even an empty animation container is rejected. Incoming nested users are resolved
through actual native ownership and counted group-node references. The scope
includes every reached Material, World and Light root, all reached nested trees,
links, socket/default/primitive settings, image bindings and material-slot ownership.
Unreviewed native references, recursive graphs, unsupported node families, panels
and unsupported socket types fail closed. Shared root ownership requires explicit
`allow_shared=true` covering the complete reported owner list.

The proof is bounded to 32 trees, 100 direct users per definition, 100 root owners,
100 affected objects/scenes, 4,096 project and context objects, 256 nodes/1,024 links/
128 flat interface items per tree, 128 sockets per node direction, 100,000 values
and one MiB of serialized preservation state. Images must already be loaded simple
FILE/GENERATED images; only identity/binding metadata is read. No pixel access,
source decoding/reload, file grant, image packing or texture backup is implied.
This is shader-state preservation, not a comparison of geometry, evaluated shading,
image pixels or all scene dependencies.

The fingerprint also binds current scene/layer identity, file, frame, mode,
selection and active object. It does not grant permission. Live permission-provider
callbacks run before cancellation/lifetime/stop and final `nodes` membership checks,
then callback-free identity/context/
scope comparisons precede native writes and compensation. Preview remains available
while paused or emergency-stopped; modifying calls fail closed. MOVE preserves
active interface selection by stable identifier, including native independent
selection flags, rather than accidentally selecting a different socket.

Edits create normal logical/native history boundaries and cannot be nested in
`batch.execute`. Compensation runs only while permissions, stop state, context and
owner identities remain valid, and only when the complete current scope equals
the original state or exact owned predicted output. An unknown protected late edit,
acquired consumer, replaced ID or lost consent prevents further writes. Failures
report `execution_started`, `rollback_verified`, `possible_mutation` and required
reinspection. A canceled/expired queued request, disconnected owner, failed handoff
or disabled toolset prevents new writes, including compensation. A completed first
assignment may therefore remain and is reported as possible mutation requiring
explicit fresh-authority recovery. An ordinary native verification failure can
restore the exact owned output only while all authority remains valid.
Recovery history is finite and is not
a durable backup. These tools do not save; safe project saving remains separately blocked.

Use preview → review every affected owner → explicit shared consent → edit →
reinspect/compare. These operations preserve existing rendered inputs rather than
claiming an appearance change. Appearance-changing follow-up work still requires
matched visual review under the normal artist work loop.

The isolated phased `shader_interface_probe` fixture passed on Linux Blender
**4.5.14 LTS** and **5.2.2 LTS**. It creates a shared leaf shader, a nested parent,
two material roots, a World root and a Light root, plus an unrelated protected
material/group. It compares complete bounded interface/socket/default/link records,
including all those consumers, then saves and checks the same graphs and animation
in a separate reader process. Embedded node trees are identified by owner kind and
name; their default names are not assumed globally unique.

## Demonstrated unanimated behavior

- Renaming one exact interface identifier propagates its displayed name while
  retaining all original interface identifiers, instance values and graph links.
- Moving a flat interface socket preserves identifiers, links and defaults across
  nested consumers. Native `interface.move` uses insertion positions: moving down
  requires accounting for removal of the old position. The fixture checks the
  entire resulting peer permutation, not merely the requested item's position.
- Setting the interface default preserves existing instance defaults. A new group
  instance inherits the new interface default. The interface default and current
  instance values are separate state.
- Native `interface.move` keeps the numeric active index and can select another
  socket on both versions. The typed edit preserves the prior active identifier.
  On 5.2 assigning `active_index` also selects the socket; the typed edit preserves
  the independent selection flags too. Full-state checks retain these properties.
- The same identifier set, nested/root links, defaults, owner references and stored
  animation survive an actual fresh-process reopen of the saved project.

These results do not establish safety for animated interfaces, panels, arbitrary
shader nodes, linked/override owners, every consumer family or production scale.
They do not constitute Windows or installed-package acceptance.

## Measured conversion loss

For an **unlinked Float input**, changing `socket_type` to `NodeSocketVector`
retains the interface identifier but resets the interface default and every
existing instance's default to zero vectors on both versions. Changing the type
back to Float leaves zero defaults; it does not recover the former Float values.
The fixture restores the exact original interface and all instance defaults
explicitly and independently verifies the whole pre-conversion graph afterward.
This is measured fixture recovery, not a released conversion or general recovery
contract. Linked conversions and broader type/animation preservation remain open.

## Measured animation difference

The fixture keyframes one material group instance's Float input at frames 1 and 2,
then swaps its order with a second input. It retains actual FCurve paths and samples
the values by stable socket identifier:

| Native version | FCurve after reorder | Sampled result |
| --- | --- | --- |
| 4.5.14 LTS | Path remains `nodes["Surface"].inputs[0].default_value` | Animation targets the wrong peer socket; the original input retains a stale value |
| 5.2.2 LTS | Native code rewrites the path to `inputs[1].default_value` | Both sampled input values remain correct |

Restoring only the original order on 4.5 does not restore the wrong peer's old
default. The fixture explicitly restores that value and verifies both original
samples. Future typed edits must reject unsupported animation or demonstrate
complete action/driver/path preservation and measured recovery for the affected
versions and consumers. Native behavior on 5.2 cannot be assumed on 4.5.

## Retained development evidence

`build/next-wave-shader-interface-probe-20261022-final/report.json` in the original
workspace retains the paired native logs, source fingerprints, full result data
and separate-process identity. Earlier failed probe reports remain separate.
`docs/shader-groups.md` describes currently registered public tools; this document
records the new native behavior and the requirements it leaves open. The current
results come from a dirty development worktree, not a frozen release candidate.

The later `shader_interface` phased interactive fixture exercises the actual typed
tools, the two materials/World/Light nested scope, all ten supported default
family/direction combinations, output rename/reorder and native UI selection,
permission/mode/stale-preview/animation denials, native undo and fixture-only
serialization plus fresh-process reopen. Fault cases retain real granting-provider
pause/stop/mode/toolset changes before initial writes and compensation, canonical
queued cancellation/deadline expiry, RequestLifetime disconnect/rejected handoff, consumer acquisition,
same-name ID replacement, protected late edits, injected verification failure and
caller cancellation without any subsequent recovery write. Provider faults use
actual prepared/written boundary predicates, independent of permission-source call
counts. Exact retained final report/source hashes are recorded in its
development receipt at
`build/next2-shader-interface-authority-20261022-final/development-receipt.json`; the paired
`report.json`, writer/reader logs and saved disposable projects remain beside it.
Earlier failed and intermediate reports remain separate. These technical comparisons do not establish Windows,
installed-package, artist visual or full-workflow acceptance.
