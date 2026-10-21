# Paired zone conversion and nested interfaces

Unreleased structured tools in the `geometry_nodes` toolset. These extend the
[nested group workflow](geometry-node-groups.md) with bounded schema maintenance.
They do not provide Geometry Nodes baking, free/rebake tools or native bake jobs.

| Tool | Permission | Contract |
| --- | --- | --- |
| `geometry_nodes.zone_inspect` | `INSPECT_SCENE` | Exact group/output, one paired input, at most 32 items; returns current boundary socket identifiers and item types |
| `geometry_nodes.zone_item_convert` | `EDIT_MESH` | Convert one unlinked numeric/bool/vector/color item by identifier and explicitly set both paired input defaults |
| `geometry_nodes.interface_edit` | `EDIT_MESH` | `RENAME`, `MOVE` or `SET_DEFAULT` on an exact interface socket, including a nested group definition |

All mutations require Object Mode, reviewed local editable non-override groups and
consumers. Shared or nested definitions require `allow_shared=true`; inspect every
affected consumer first. The existing 32-tree/eight-level, 256-node/1,024-link,
128-interface/socket and 100-consumer bounds apply. All participating definitions
and modifier owners must be unanimated. Attached simulation/bake consumers are
refused because reviewed Blender 4.3 RNA cannot establish their current cache state.
An unattached simulation definition can be inspected and converted.

## Explicit paired defaults

First inspect the output boundary:

```text
geometry_nodes.zone_inspect(group_name="Procedural Child", output_name="Repeat Out")
geometry_nodes.zone_item_convert(
  group_name="Procedural Child", output_name="Repeat Out",
  socket_identifier="Item_1", socket_type="INT",
  input_value=3, output_value=5, allow_shared=true
)
```

These are tool-call examples, not Python for Blender's console. Use the returned
identifier, not an assumed `Item_1`. Exactly one paired input is required. All four
boundary sockets for the item must be unlinked and uniquely matched by identifier,
name and type. Geometry, pointer, string, matrix and rotation conversion is refused.

Supported target types are `FLOAT`, `INT`, `BOOLEAN`, `VECTOR` and `RGBA`. Values use
the existing finite GN constant policy: signed 32-bit integers, exact booleans,
finite floats/components with magnitude at most `1e20`, three vector components or
four color components. These are native numeric values; no color conversion occurs.

`input_value` is the default on the paired input node's input socket;
`output_value` is the default on the output boundary's input socket. Native type
conversion resets both defaults. The tool requires their replacement explicitly
and verifies both after conversion. The two outgoing socket defaults are recreated
by Blender. All four identifiers, item name/order, pairing, other items, links,
reviewed dependent definitions and existing modifier values are checked separately.
An item is never removed/recreated to simulate conversion.

## Nested interface maintenance

```text
geometry_nodes.interface_edit(
  group_name="Procedural Child", socket_identifier="Socket_2",
  operation="RENAME", new_name="Width", allow_shared=true
)
geometry_nodes.interface_edit(
  group_name="Procedural Child", socket_identifier="Socket_2",
  operation="MOVE", to_index=1, allow_shared=true
)
geometry_nodes.interface_edit(
  group_name="Procedural Child", socket_identifier="Socket_2",
  operation="SET_DEFAULT", value=4.0, allow_shared=true
)
```

`MOVE.to_index` is the **final zero-based index among sockets of the same direction**.
The implementation translates Blender's insertion-boundary convention, then checks
the final order. Moving currently requires a flat socket-only interface. UI panel
creation/reparenting remains unsupported. Rename rejects duplicate names within
the direction. `SET_DEFAULT` accepts reviewed INPUT constants only. Existing group
instance and modifier constants retain their own values; changing an interface
default is not an implicit broadcast to every instance. Identifiers and links stay
stable. Interface type conversion/removal requires a future explicit consumer-value
migration contract; native probes demonstrate that type changes reset instance values.

## Failure and recovery

Before the final write, live gates and a callback-free complete bounded signature
revalidate exact group identity, editability, consumer scope, definitions and modifier
properties. The declared delta is checked independently from the newly captured
post-state. An interleaved same-count item/default/consumer edit is still a change.

A failed owned mutation attempts compensation only while live cancellation, pause,
emergency and `EDIT_MESH` gates allow each new recovery write and the current identity,
ownership and complete published signature still match.
Interleaved manual edits, new consumers, read-only changes or denied permission cause
compensation to be skipped. Errors report `execution_started`, `possible_mutation`,
`rollback_verified` and `verification_required`; inspect before retrying. An unknown
partial native assignment without an owned fingerprint is retained for explicit
recovery. Native undo/checkpoint retention is separate and finite. Success verifies
the bounded schema/consumer contract, not evaluated artistic quality or saved durability.

## Native bake research and concrete blockers

The opt-in phased `geometry_zone_lifecycle_probe` fixture uses only disposable
runner-owned data. It exercises a three-frame synchronous packed simulation,
FREE/rebake, independently sampled geometry and a fresh-process `.blend` reopen.
Stored-path deletion is tested with explicitly owned `meta/` and `blobs/` sentinels.
Direct RNA/operator calls in this research fixture do not constitute a product API.

Blender 4.3's single-bake and free routines delete a previously resolved disk path
even if the effective bake target is `PACKED`. A future packed tool must reject all
stored disk paths or establish an independently verified safe transition. Disk caches
require explicit approved cache-directory ownership, deletion consent and external
effect history; texture/asset directory consent does not authorize cache directories.

The synchronous operator blocks until it returns. The asynchronous operator starts
a native WM job and locks the interface. Reviewed Blender 4.3 RNA exposes bake
settings/identity but no authoritative baked/packed/completed-frame status, and its
public `is_job_running` enum excludes Geometry Nodes bake jobs. Wrapping those calls
in the image-job scheduler cannot establish truthful native progress, completion or
owner-specific cancellation. No bake tool is exposed by this increment. These
capability/lifecycle blockers remain requirements, rather than deferred release scope.

## Development evidence

Run `scripts/run_blender_checks.py --case geometry_zone_lifecycle` for the typed
workflow and `--case geometry_zone_lifecycle_probe` for the opt-in two-process native
research, using a new output directory and explicit Blender executable. The latter
writer uses `session_uid`, the actual native single-bake object lookup argument;
names are not accepted by that Blender operator. The first stronger 4.3.2 probe
passes in `build/gn-zone-api-probe-20261022-c/report.json`, retaining source hashes,
all conversion/default/link snapshots, packed playback and owned-path deletion proof.

Linux development evidence, fixture markers and schema checks do not qualify Windows,
installed release packages, production memory behavior, visual quality or full 1.0.

The typed workflow, existing nested-GN workflow and phased research probe also pass
on Linux Blender **4.3.2, 4.5.14 LTS and 5.2.2 LTS** in
`build/gn-zone-final-<version>-20261022-b/report.json`. The probe retains exact native
arguments, API inventories and per-process artifact hashes. These runs confirm the
same identifier/default-reset and packed-path deletion behavior across those versions.

Blender 5.2 replaces modifier IDProperties with typed modifier input/output storage.
The structured tools feature-detect that native storage, bind only exact identifiers
from the reviewed interface and preserve both constants and attribute modes. They
do not treat an IDProperty `TypeError` as empty evidence. Unknown fields, modes and
panels fail closed. Geometry-only modifiers and all six reviewed constant types are
covered, together with explicit refusal to overwrite an attribute-driven input.
