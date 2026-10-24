# Bounded render mutation and publication contract

This development increment tightens `render.configure` and `render.execute` while
keeping their typed arguments and protocol envelopes. It does not qualify 1.0 or
close the broader cinematic, delivery, ownership or Windows acceptance gates.
The components remain 0.3.0 alpha.

## Admitted dependency scope

The initial native profile covers a single actual current Scene, window and view
layer in Object Mode with a non-null frozen active Object, local editable static meshes, cameras, lights, plain
empties and a reviewed set of procedural shader nodes. It freezes all admitted
Main IDs and embedded shader graphs, mesh topology/attributes, material bindings,
collection membership, per-object material slots, UV active/render selectors,
light-linking collections and per-member INCLUDE/EXCLUDE flags (including the
Scene master collection), authored transforms, units, camera settings, world/light settings,
EEVEE settings, view-layer settings and current selection/context. Inactive factory
Palette, LineStyle and viewer-image records receive explicit bounded readers.
`Render Result` is a disclosed native output buffer, not a recoverable checkpoint.

Animation and drivers, linked/override data, shared Scene consumers, object
parenting/constraints/modifiers/instances, custom split normals, media/image inputs, node groups,
compositor graphs (including File Output), sequencer media, motion blur, Freestyle,
multiview, custom AOV/light groups, custom engines, render/composite/frame/dependency
handlers and unreviewed runtime RNA are refused before tool-owned render writes.
Known bundled runtime properties are identified by their descriptors and never
read; their ordinary raw ID-property storage remains protected on the exact
reviewed 4.5 build. The exact 5.2 build moves bundled settings to SYSTEM storage,
which the current raw reader cannot cover. Both render mutations therefore
return `NOT_IMPLEMENTED` on that build before owned writes. This is an explicit data
profile, not a sandbox for other code in the Blender process.
That refusal also applies when bundled runtime declarations have been removed:
descriptor absence does not prove that authored SYSTEM storage was removed.
Protected raw custom-property scalars carry explicit type tags; finite floats
use their hexadecimal representation, preserving signed zero. Containers retain
their exact native ID-property group/array kind and mandatory raw native array
storage typecode (`f`, `d`, `i` or `b`). Supported Python container forms have
separate tags; unreviewed representations refuse before iteration. This applies
recursively to Scene, material and raw UI/WindowManager properties. Fixed native
RNA fields retain their existing typed representation.

Evidence is bounded to 256 Main IDs, 64 objects, 32,768 aggregate mesh/attribute
elements, 512 shader nodes, 2,048 shader links, eight view layers, collection depth
eight and 2 MiB of serialized preservation evidence. Exceeding a bound refuses the
operation. The first proven execution path is native EEVEE and PNG with at most
1,048,576 output pixels. Additional formats, Cycles, images, nested procedural
workflows and general production scenes remain mandatory 1.0 work.

## Live writes and measured recovery

The tool freezes its original dependencies and literal owned fields before calling
permission providers. Every owned setter repeats live authorization, request and
toolset checks, complete protected/owned-field comparisons, then a pure terminal
request/state guard. External output also requires `ACCESS_EXTERNAL_FILES` and an
Approved Asset Folder. `render.execute` always requires `CAPTURE_VIEWPORT` as well
as `EDIT_RENDER`.

Failed setters retain their primary error. Compensation writes only independently
predicted values that still belong to the same admitted context and request. It
stops after lost authorization, request cancellation/deadline, pause/stop, disabled
toolsets, changed consumers or newer manual settings. Failure responses disclose
retained render settings, blocked recovery, possible Render Result replacement,
and known or uncertain file effects. Retained buffers and Blender undo do not
provide a durable render-output backup.

Blender's native render call blocks and cannot be preempted by this bridge. The
result reports its measured blocking interval and checks cancellation at subsequent
boundaries. This increment makes no universal real-time guarantee.

The private checkpoint adapter freezes typed preparation and the full authored
ledger before entry permission providers. The handler must reuse that exact
ledger, with independently predicted owned setter transitions, through the final
checkpoint. Its separate static projection checks descriptors, bindings, topology
and admission predicates; static equality alone does not establish preservation
of authored settings. The readonly post-marker guard never calls providers.
Both render mutations register the optional admission factory. The registry
captures before entry providers and reuses that ledger through the handler and
finalization. Guarded batch composition remains unavailable pending a separate
transition proof. Deferred editor finalization and complete native executor
acceptance remain independent verification requirements.

## Private output and explicit overwrite tightening

Blender writes only to a precreated file in an owned private staging directory.
The bridge verifies its identity, complete SHA-256/byte count, PNG chunk checksums,
encoding/dimensions and complete bounded deflate scanlines before publication.
Native EXIF/ICC/text metadata is retained as bounded opaque bytes, never decoded;
this does not relax the separate image-source admission policy. PNG structural
checks do not establish artistic appearance, linear HDR pixel accuracy or visual
acceptance.

Publication creates a hard link atomically without replacing an existing target.
A file created after preflight is preserved. An existing target with
`overwrite=True` returns `NOT_IMPLEMENTED` before private resources or settings
change: fingerprint-bound replacement needs separate proof. This is an intentional
security tightening of the existing argument, not a waiver of the 1.0 overwrite
requirement. If the filesystem reports an ambiguous link failure, the response
reports unknown publication instead of asserting that no file exists.

Approved Asset Folder comparisons read the canonical bridge preference's native
raw storage and descriptor, without calling its runtime string getter. In the
reviewed 5.2 build, AddonPreferences stores these values in distinct system
properties with no reviewed supported raw reader. Explicit external render paths
therefore return `NOT_IMPLEMENTED`. Managed temporary output avoids this
preference read, but remains blocked by the separate 5.2 render-input SYSTEM
storage refusal below.
The raw-reader failure never means an empty default and never triggers a runtime
getter fallback. Supporting approved external output on that version remains
mandatory release work.

Bundled Cycles SYSTEM settings on 5.2 also have no admitted raw reader. Native
`is_property_set(..., ghost=False)` reports storage existence without proving
its type. Resolving a malformed runtime pointer can delete and recreate its
storage, even when the existence check returned true. Resolving a valid pointer
can construct its mutable Python PropertyGroup class. Owned temporary-schema
diagnostics reproduce the repair on both builds; they do not authorize a
runtime getter or constructor fallback. Restoring complete 5.2 render admission
requires a separately proven nonmutating raw reader.

Cleanup removes only the authorized unchanged private resource. Changed/unknown
bytes, sidecars, lost authorization or identity/context drift retain staging for
inspection. Published files survive cleanup and Blender undo. The tool does not
claim filesystem crash durability, a host/filesystem sandbox, Windows acceptance,
or automatic removal of published render files. Managed outputs remain in their
per-request temporary directory until ordinary host temporary-file cleanup.

## Exact native source and acceptance evidence

Development evidence uses official Linux builds 4.5.14 LTS (`62c1db4208e8`) and
5.2.2 LTS (`d13f752e3b9c`). Exact upstream Git blobs bind reviewed native behaviors:

- The WindowManager ID visitor traverses both `win.scene` (`USER_ONE`) and
  `win.unpinned_scene` (`NOP`). The profile accepts the measured second reference
  only for these builds with one Main Scene/window, an unpinned workspace and no
  raw custom ID aliases. Native checkpoint polling writes the weak
  ToolSettings.particle_edit Scene/Object pair. Before providers, the adapter
  freezes the exact initial pair and the source-derived pair `(Scene, active
  Object)`. Only the manager's successful-push notification advances that
  expectation, followed immediately by readonly comparison. Scene.original and
  WindowManager consumer counts remain literal protected values. Arbitrary
  consumers and unnotified transitions are refused.
- Native EEVEE is `BLENDER_EEVEE_NEXT` only in the reviewed 4.5 build and
  `BLENDER_EEVEE` only in the reviewed 5.2 build. Native engine registration
  protects the existing built-in identifier, while the other spelling is
  available to Python engines. Unknown builds and the other version's spelling
  are refused, including a planned engine change before any checkpoint write.
- Principled subsurface socket availability is derived from `custom2` and
  `SOCK_UNAVAIL`. The 4.5 update touches Subsurface IOR and Anisotropy; the 5.2
  update touches IOR only. Defaults, links, methods, identities and unrelated raw
  socket flags remain protected. Native failure never authorizes a transition.
- Native mesh/attribute collection iteration exposes mutable array buffers.
  Native undo snapshots can make the next RNA iteration detach shared storage.
  In the checkpoint projection only, the nine measured MeshVertex/Edge/Loop/Polygon
  and Bool/Float2/FloatVector/Int2/Int attribute-value roles use their parent Mesh
  ID, exact RNA class, bounded order/index and attribute identity as their
  structural identity. Every authored value remains in the full ledger. Main
  IDs, shader graphs, nodes, sockets, unmeasured subdata and descriptors retain
  their exact identities; moving any of those is refused.

Immediately after `FINISHED`, before callback-backed providers, the bridge seals
only one of two complete candidates computed before providers: the original raw
closure or the exact source-derived closure. Native evaluation can retain the raw
availability or update it. Later checks require that same sealed candidate; even a
provider changing the derived flag is refused. Arbitrary per-field mixtures and
unrelated changes are refused. These are native derived availability flags, not
adopted authored socket values.

Exact-byte receipts under the retained implementation evidence bind `wm.cc`,
`wm_files.cc`, `node_shader_bsdf_principled.cc`, `rna_node_socket.cc`,
`rna_nodetree.cc` and `node.cc` to full upstream commits and blob identities.
Research observations and failed fixture runs remain separate from passing
acceptance. The final implementation receipt records source and report hashes.

The opt-in isolated native cases are `render_scope_probe` (research inventory),
`render_boundaries` (registered tiny native success),
`render_boundaries_interactive` (owned interactive display) and
`render_adversarial` (actual RNA with controlled interruption/interference and
native output effects). Unsupported native runtime-property registration is
reported explicitly, rather than counted as getter-denial proof.
On 5.2 these cases verify explicit SYSTEM-storage refusal, permission precedence
and zero native checkpoint/render writes; they do not claim successful rendering.

The full Windows 11 / Blender 4.5 LTS and stable 5.x installed-package matrix,
constrained-memory/4K runs, reviewed cinematic visuals, mixed manual editing,
production delivery and scenarios A–F remain open. Linux evidence is development
evidence and does not establish the release's Windows qualification.
