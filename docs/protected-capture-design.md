# Protected capture: source findings and required witness

## Current stock-Blender direction

Development targets **official, unmodified Blender only**. No fork, custom build
or custom Blender distribution is a product requirement. Ordinary
`viewport.capture` remains available when artist protection is unarmed; the
framing fixture records bounded ordinary capture geometry and restoration.
Protected capture remains refused until a new stock profile is qualified. Its
existing `modifies=True`, `automatic_checkpoint=False` and `CAPTURE_VIEWPORT`
authorization are unchanged.

The missing native API blocks the earlier strict same-Main guarantee of observing
raw pending Base flags without ensuring synchronization. It does not block all
ordinary screenshots or useful visual verification. The source findings below
remain valid for that older guarantee; custom-API work is stopped outside the
candidate and retained as historical analysis.

The authorized redesign may use an explicit synchronization stage with clearly
declared effects, or a separate Scene/process snapshot preview. `GPUOffScreen`
still reaches dependency-graph evaluation, and context getters can ensure
synchronization. An explicit `ViewLayer.update` is an authorized mutation, not a
passive read. A separate Scene/process route also needs measured parent isolation;
its name alone is not preservation evidence.

Every proposed profile must qualify matched parent authored-data and context
preservation. It may not clear or rebase an armed protection scope, adopt changed
state after synchronization as the protected baseline, or restore over intervening
manual edits. Authority, lifetime, ownership and expected-state checks remain
required. No redesigned protected profile or restoration guarantee is implemented
or qualified by this document. Safe-save asset-catalog effects are a separate,
unchanged requirement. All 29 implementation items and 14 open gates remain.

The following sections retain the earlier same-Main source investigation and
its stricter raw-state witness requirements. They are not a requirement to ship a
custom Blender API before ordinary capture or a separately qualified stock
redesign can be useful.

## Getter counterexample to qualify

`readonly_context_probe` is an opt-in interactive research case. Run it only with
`scripts/run_blender_checks.py --case readonly_context_probe --blender PATH
--output NEW_DIRECTORY`. It creates an owned Scene, measures all cases in one
main-thread timer turn without yielding, restores the original window Scene and
ViewLayer, and saves neither a project nor preferences. Its hashed JSON receipt
retains each API call sequence and raw before/after selection.

The legal setup explicitly synchronizes a visible selected active Mesh, then
calls `Object.hide_set(True)`. Native `hide_set` ensures synchronization before
setting `BASE_HIDDEN`, then tags the ViewLayer for synchronization. It does not
clear `BASE_SELECTED` after setting the hidden flag. A following getter that
ensures synchronization can clear selection through `BKE_base_eval_flags`.
The probe observes the raw `ViewLayer.objects.selected` collection before and
after each reader. That raw collection has a debug-only precondition assertion;
the probe refuses every build except the two exact source-pinned Release builds.
It must not become a production read-only witness.

Controls use raw object iteration, raw selected iteration and
`artist_loop._objects`, each expected to preserve the pending raw selection.
Individual probes use `context.selected_objects`, `context.active_object`,
`context.mode`, `ViewLayer.objects.active`, `Object.select_get`, `hide_get`,
`visible_get`, and actual `LayerCollection.children` traversal. They require an
ordinary current window Scene/ViewLayer and no Python context override. Context
providers may otherwise replace the screen callbacks. No redraw or depsgraph
update is permitted between the pending setter and the final raw observation.

The existing artist readers with source paths to these getters are:

| Reader at bridge source `2043c9d` | Potential synchronizing read |
| --- | --- |
| `tools/artist_loop.py:_context` | selected Objects, mode, active Object |
| `tools/_object_rna_mutation.py:Boundary._session` | mode, selected Objects, active Object |
| `tools/_scene_checkpoint_roles.py:Plan._read` | active Object, including construction and later checks |

The fixture calls these three reader methods independently; the latter two use
reader-only shells to avoid entering write-boundary constructors. The role shell
uses a no-op active validator, explicitly limiting the claim to `_read` itself.
It does not dispatch a public tool, run a permission-provider race, or establish
an existing admission bug. Native results are required before attributing one.
`artist_loop._objects` uses raw collection resolution and is not classified as
a synchronizing getter.

The source review pins both full upstream commits:

* Blender 4.5.14: `62c1db4208e862312bc36db5bc15d4a6dbcfa3e3`.
* Blender 5.2.2: `d13f752e3b9c4f8c261cda552b1021f8bcc0382c`.

For each commit the retained source receipt covers
`makesdna/DNA_layer_types.h`, `makesrna/intern/rna_layer.cc`, `rna_scene.cc`,
`rna_object_api.cc`, `blenkernel/intern/layer.cc`, `layer_utils.cc`, `context.cc`,
and `editors/screen/screen_context.cc`, under `source/blender/`. The exact raw
URLs are `https://raw.githubusercontent.com/blender/blender/FULL_COMMIT/PATH`;
the receipt records SHA-256, Git blob identity and relevant line anchors.

The source chains are `rna_Object_hide_set` to `BKE_view_layer_need_resync_tag`,
then getter to `BKE_view_layer_synced_ensure`, layer sync, and
`BKE_base_eval_flags`. Raw collection iteration does not call the ensure. Source
references for the two versions respectively include `rna_object_api.cc:134`
and `:150`, `layer.cc:999` and `:1032`, and `BKE_base_eval_flags` at
`layer.cc:2345` and `:2434`; receipts retain the complete functions.

## No supported no-sync status predicate

`VIEW_LAYER_OUT_OF_SYNC` is an internal DNA bit, `(1 << 3)`, at
`DNA_layer_types.h:279` in 4.5 and `:169` in 5.2. The 5.2 native function
`BKE_view_layer_is_synced` (`layer.cc:1015`) reads it without synchronizing.
Neither version exposes this bit or predicate through the registered ViewLayer
RNA properties/functions, including `rna_def_view_layer_common` in
`rna_scene.cc`. LayerCollection visibility predicates describe derived
visibility, not synchronization status. Depsgraph identity or updated flags
cannot replace the missing predicate.

Accordingly, a Python preflight cannot currently prove that calling these
getters will preserve the frozen pre-provider Base state. Inspecting selection
only after synchronization would adopt a changed baseline. Reading AUTO Mesh
texture-space vectors has a separate ensure/writeback hazard and is also
excluded from purportedly passive preflight.

## Candidate primitive and evaluation closure

`GPUOffScreen.draw_view3d` accepts explicit view and projection matrices. On both
exact refs its `gpu_py_offscreen.cc` path calls `BKE_scene_ensure_depsgraph` and
`ED_view3d_draw_offscreen` with a null context. It avoids the old
`render.opengl` path's WindowManager job cancellation, Render Result replacement,
Scene render settings and modal custom-data-mask writes. Matrices can avoid
temporary viewport location/rotation/lens assignments. Null draw context skips
the Python PRE/POST_VIEW callback path. This does not prove evaluation is passive
or eliminate Base isolation/shading state requirements.

The guarded candidate must perform an explicit, authorized update after freezing
the whole admitted Main. Borrowing a previously evaluated graph is insufficient.
`ViewLayer.update` reaches `BKE_scene_graph_update_tagged` with
`SYNC_WRITEBACK_YES`; 5.2 also synchronizes all Main Scene ViewLayers. Both versions
copy evaluated object transforms/Base flags/runtime bounds back to originals.
AUTO Mesh texture space also writes original Mesh flags/location/size. The only
source caller of queued `sync_writeback::add` in each complete source tree is
Geometry Nodes' baking remap in `MOD_nodes.cc`; refusing modifiers removes that
queue caller, not the other original-ID writes. Simple node-tree update can
normalize socket availability and active outputs. Each allowed native outcome
must therefore be predicted from the frozen authored input, before providers,
or the input refused before any update. No cache backup/restoration is claimed.

The smallest candidate supports only the exact two Linux builds, one Scene and
ViewLayer in Main, at most 32 Objects, 128 IDs, 32,768 geometry elements and a
2 MiB frozen authored representation, Object mode, exact named Mesh framing,
solid flat Object colors, disabled overlays, and images at most 1,024 pixels
on each axis. Every allowed ID type and reference must have its own literal
snapshot contract; these limits do not by themselves admit an ID type.
It refuses animation, handlers, drivers, procedural dependencies, modifiers,
constraints, parenting, instances, shape keys, physics, compositor, linked or
override data, media/Render Result consumers, unsupported ID references and
invalid bounds before any native update. Unsupported data anywhere in Main is
refused, including unrelated Scenes on 5.2. Materials and World would need exact
reviewed factory-shaped node graphs and canonical update flags. Solid evidence
cannot qualify material or rendered appearance.

## Concrete native-read-only witness requirement

The missing primitive is a supported source-qualified native read that reports
the ViewLayer sync bit, raw Base membership/order, active Base, all relevant
Base visibility/selection/collection flags, and raw LayerCollection identity,
parentage, flags and Collection references **without ensuring synchronization,
evaluating, invoking Python getters, allocating authored IDs or emitting native
notifiers**. It must preserve a legal pending hidden-and-selected Base state.
An official RNA predicate alone could support refusing all pending state, but
cannot supply the raw per-Base compare-and-swap proof needed during temporary
isolation and restoration. Python raw collection controls in this probe do not
provide that complete witness. Private memory offsets and `ctypes` are excluded.

Before the earlier strict same-Main candidate could be implemented, a native test
would need to establish that witness on both exact builds and compare before/after
raw data during accepted, refused and injected-failure calls. It must include a
provider that dirties the layer and changes selection/visibility, literal authored
all-Main snapshots,
explicit evaluation/writeback candidates, and the actual armed transform loop.
No synchronization or newly observed native result may become the baseline.

The eventual boundary also requires an actual main-thread assertion and an
exclusive bridge mutation lease before factory/provider entry. The integrated
[Scene reservation](scene-job-kernel.md) already denies capture while a job owns
the evaluation context; its selected native evidence is recorded in the
[2026-10-23 checkpoint](artist-workflow-checkpoint-20261023.md). It grants no armed
artist-capture admission and supplies no missing raw Base witness. Freeze exact
parameters, current plan/revision/generation and complete authored scope before
the first provider. Revalidate CAPTURE permission, cancellation, pause/stop,
policy and full expected state after callbacks and immediately before each
owned write or native update. Temporary UI writes require per-field expected
state and compare-and-swap restoration, preserving foreign manual edits. When
permission/caller/stop authority is lost, follow the existing boundary policy:
stop authored writes, report retained temporary fields and restoration failure,
and require reinspection; do not silently compensate after revocation. Private
GPU resource release remains necessary, with no late image publication.

The guarded operation must own finalization so the generic modifying-tool path
does not finalize an unrelated editor checkpoint. It must never update the
artist plan baseline or label a stale baseline verified. The ordinary capture
path remains available, and the current armed refusal stays until a new stock
profile is qualified against its explicit preservation contract.
