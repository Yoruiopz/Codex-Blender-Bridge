# Object RNA mutation boundaries

The compatible `transform.*`, `modifier.*` and object `constraint.*` tools now
recheck Blender authority at each direct field write, allocation, removal,
verification and attempted compensation. Their declared permission remains
`TRANSFORM_OBJECTS`. A stopped request does not finish configuring a partially
created component or automatically remove it. A separate authorized request may
inspect, repair or remove that retained component.

These tools require a live tool context and Object Mode in one current scene and
view layer. Exact object/component identities, current project, frame, active
object and selection are compared after permission providers run. Local Object
consumers are followed up to 32 objects and returned in `affected_objects`.
Unexplained non-Object consumers, linked/override owners, shared scene ownership
and shared collection ancestry fail closed. Ordinary camera bindings and the
measured particle-edit context reference are accounted for locally; the shared
object-deletion policy is unchanged. Shared or linked Mesh data still permits an
object-owned transform or modifier/constraint setting change.

Direct writes compare protected writable RNA fields, other transform channels,
component order/identities, custom-property values, Action/driver/NLA content,
pose/rest-bone state, vertex-group metadata, material bindings, and bounded base
Mesh/attribute/shape-key content. Pointer settings also freeze local source
objects and their outside consumers. Self references and incoming dependency
cycles are refused. Limits include 100 components, 128 custom properties, 256
pose/rest bones, 131,072 Mesh structural elements and 262,144 attribute/shape-key
values. Larger scopes require a separately bounded workflow.

A setter may change only its predicted field delta. Demonstrated native aliases
are modeled explicitly: constraint `mute`/`enabled`, Bevel `width`/`width_pct`,
component activation on allocation, and automatic Mesh texture-space bounds.
Unexpected setter coupling is retained for inspection rather than adopted as
owned output. Ordinary failures can restore prevalidated field values only while
fresh authority and the exact expected state still hold. `rollback_verified`
requires the complete measured baseline to match. Pause, emergency stop,
permission loss and request expiry latch the operation against later automatic
writes. RNA comparison snapshots and checkpoint history are not durable backups.

Native modifier/transform application uses `temp_override` without changing
persistent selection, active object or mode. It currently qualifies the bounded,
local, single-user Mesh path without shape keys; transform application additionally
refuses animated owners. Non-Mesh application, bone/vertex-parented world deltas,
non-default delta channels and unrepresentable matrix shear report explicit
unsupported contexts. Transform component locks are respected. Native calls can
block; they cannot be interrupted inside Blender's operator. Failure, cancellation
or a changed protected state after application reports possible retained mutation
and checkpoint recovery, never successful Mesh rollback. Mesh ID/ownership,
metadata, bindings, group metadata and other objects remain compared separately
from the allowed topology result.

`verified` refers to these structural comparisons. It does not establish visual
acceptance, arbitrary nested RNA/profile/NodeTree/material dependency preservation,
all modifier-specific conversion semantics, durable topology recovery, large-scene
latency, Windows behavior or full release acceptance. Those broader gates remain
open. In particular, Mesh material bindings are frozen; complete shader graph and
texture content are not proven by this helper. A dependency closure identifies
consumers; it does not by itself qualify every affected workflow.

Validation is retained by the official `object_rna_mutations` background fixture
on Blender 4.5 LTS and 5.2, with Python adversarial tests in
`tests/test_object_rna_mutation.py`. The fixture checks successful transforms and
component lifecycle, live stops between fields, measured ordinary-failure
compensation, native application, protected objects and context. Linux evidence
does not qualify Windows or the release acceptance scenarios.
