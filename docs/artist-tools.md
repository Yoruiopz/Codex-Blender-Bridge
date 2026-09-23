# Structured artist tools (unreleased)

These 21 tools are development work on `main`, not part of the published 0.3.0 assets.
They implement reviewed subsets of the requested 1.0 artist workflows. They do not yet
provide every compositor node, simulation solver, painting brush, driver or NLA operation.
Install matching development add-on and MCP sources to exercise them; do not mix an old
release add-on with this server. No release assets have been replaced.

## Enablement and permissions

Enable each toolset with `toolsets.enable`; Blender-side permissions remain authoritative.
All new toolsets start disabled. No raw Python permission is needed.

| Toolset | Read permission | Write permissions |
| --- | --- | --- |
| `weights` | `INSPECT_SCENE` | `EDIT_MESH` |
| `compositor` | `INSPECT_SCENE` | `EDIT_RENDER` |
| `animation_layers` | `INSPECT_SCENE` | `EDIT_ANIMATION` |
| `simulation` | `INSPECT_SCENE` | `EDIT_MESH`, `EDIT_SCENE`; cache operations also `EDIT_ANIMATION` |
| `geometry_nodes` zones | `INSPECT_SCENE` | `EDIT_MESH`; attaching still also requires `TRANSFORM_OBJECTS` |

Mutations use the existing main-thread dispatch, pause/stop gates, logical checkpoints and
history. Checkpoints are not durable backups or transactions. Inspect before/after, verify
evaluated results, and save only by agreement. These tools do not automatically save files.

## Vertex weights

`weights.inspect(object_name, offset=0, max_vertices=50)` returns group locks and paginated
memberships (up to 128 vertices per page). Follow `next_offset`; do not treat truncated
results as complete. Object Mode is required; budgets are 200,000 vertices and 128 groups.
Mutations require local, non-override, single-user mesh data.

- `weights.group_create(object_name, group_name)` creates an unused named group.
- `weights.assign(object_name, group_name, vertex_indices, weight)` assigns a finite 0–1
  weight to 1–1,000 unique explicit vertices. An explicit `null` removes membership.
- `weights.normalize(object_name, group_names, vertex_indices)` rescales 1–32 named unlocked
  groups to fill the weight remaining after all unnamed groups. Unnamed weights are preserved.
  Zero target totals and untouched totals exceeding one are rejected before mutation.

- `weights.smooth(object_name, group_name, vertex_indices, iterations=1, factor=0.5)` performs
  simultaneous one-ring edge averaging on one group. Only named vertices change; neighboring
  vertices outside the target set are fixed boundary values. Missing weights count as zero.
  Isolated vertices stay unchanged. Limits: 1–20 iterations, factor 0–1, 400,000 mesh edges and
  20,000 selected adjacency entries. This changes weights, never geometry or selection.
- `weights.transfer(source_object, source_group, object_name, group_name, source_indices,
  vertex_indices)` copies weights through explicit positional pairs. Both lists must contain
  1–1,000 unique indices and have equal length. Snapshotting makes overlapping same-object
  mappings safe. Missing source membership removes the target membership. Target groups must
  already exist; source groups may be locked. No nearest-surface or symmetry guess is made.

Smoothing and transfer preserve unrelated groups and do **not** normalize implicitly. Run
explicit normalization afterward when required; inspect totals before assuming skinning is valid.
Geometric mirroring, surface-interpolated transfer and brush strokes remain unimplemented.

Locked target groups cannot be edited. Weight application snapshots memberships and attempts rollback
on failure; inspect `rollback_performed` and reinspect before retrying. This is numeric skin-weight
authoring, **not** brush strokes or deform-quality validation.

## Compositor

`compositor.create(scene_name)` initializes a missing graph without replacing existing work.
It handles Blender 4.5 scene node trees and 5.1 scene compositor groups.
`compositor.inspect` returns bounded nodes/sockets/links and reviewed type names.
`compositor.edit(scene_name, operation, arguments)` accepts:

| Operation | Arguments |
| --- | --- |
| `ADD` | `node_type`, `node_name`, optional `settings` |
| `REMOVE` | `node_name` |
| `SET` | `node_name`, `settings` (reviewed direct RNA properties) |
| `INPUT` | `node_name`, `socket_name`, `value`, optional `socket_index`; input must be unlinked |
| `OUTPUT` | Same socket fields, but only RGB/Value constant outputs |
| `LINK` | `from_node`, `from_socket`, `to_node`, `to_socket`; optional `from_socket_index`, `to_socket_index`, `replace_existing` |
| `UNLINK` | Same endpoints/indices as LINK |

Inspect socket names rather than guessing them across Blender versions. Reviewed nodes include
render layers, RGB/value, mix, blur, brightness/contrast, gamma, hue/saturation, invert, math,
alpha-over, glare, outputs/viewer and layout nodes. Availability still depends on Blender version.
File/image/script/nested groups are not admitted. Existing graphs containing unreviewed nodes
cannot be modified by these tools. Shared 5.x compositor groups are rejected. Graph editing
limits are 512 nodes and 2,048 links. Inspection reports truncation.

## Drivers and NLA

`animation_layers.inspect(object_name)` reports object drivers and NLA tracks/strips.
It does not return driver expressions. Editing is limited to local editable objects,
outside NLA tweak mode; budgets are 128 drivers, 64 tracks and 256 strips.

`drivers.add(object_name, data_path, variables, index=0, driver_type="AVERAGE")` supports
`location`, `rotation_euler`, `scale` and index 0–2. Types are AVERAGE/SUM/MIN/MAX, never SCRIPTED.
Each of 1–8 variables specifies `object_name`, `transform_type` (LOC/ROT/SCALE + _X/_Y/_Z),
and `transform_space` (WORLD_SPACE/LOCAL_SPACE/TRANSFORM_SPACE). Sources must be independent:
no parent, constraints or animation data, and not the target. Targets cannot have an active
action/NLA or an existing driver on that channel. `drivers.remove` removes one exact channel.
Arbitrary RNA paths, expressions, bone targets and complex dependency networks are not implemented.

`nla.add_strip(object_name, track_name, strip_name, action_name, frame_start=1, slot_identifier=null)`
uses an existing action on a new named track. It selects the sole compatible OBJECT action slot
or requires an explicit slot identifier. It does **not** push down or clear an active action;
an active action can mask NLA playback. Targets with drivers are rejected.
`nla.edit_strip(object_name, track_name, strip_name, settings, remove=false)` edits a named CLIP
strip on a single-strip track, or explicitly removes the strip. Timing, repeat, scale, influence,
blend/extrapolation and mute settings are reviewed; scale/repeat are limited to 0.01–100.
Transitions, meta strips, track lifecycle/reordering, action creation and full curve editing remain gaps.

## Geometry Nodes zones

- `geometry_nodes.zone_create(group_name, zone_type, input_name, output_name, iterations=1,
  allow_shared=false)` creates paired REPEAT or SIMULATION boundaries and a geometry passthrough.
- `geometry_nodes.zone_item_add(group_name, output_name, socket_type, name, allow_shared=false)`
  adds GEOMETRY/FLOAT/INT/BOOLEAN/VECTOR/RGBA state, at most 32 items.
- `geometry_nodes.zone_remove(group_name, output_name, allow_shared=false)` removes the output,
  paired inputs and their incident links. Interior nodes are retained.

Use existing node/link/input tools to build the zone body. Boundary nodes must be created/removed
through paired APIs. Repeat iterations must be constant integers 0–64; linked iteration counts
are rejected. This bounds the count, **not** total geometry complexity or evaluation time.
Shared graph edits still require acknowledgement. Simulation-zone disk baking, item removal/
reordering, nested node groups and arbitrary node types are not implemented.

## Cloth and baking

`simulation.cloth_add(object_name, modifier_name)` requires Object Mode, a local single-user
mesh with at most 2,000 vertices and an empty modifier stack. `simulation.configure` edits
reviewed stiffness/damping, mass, air damping, time scale, pin group/stiffness and quality (1–5).
Free a baked cache before configuration. `simulation.inspect` reports settings and cache flags.

`simulation.cache(object_name, modifier_name, operation="BAKE"|"FREE", frame_start=1, frame_end=10)`
targets exactly one visible cloth modifier in the current view layer. BAKE supports at most
32 frames, quality at most 5, and **in-memory caches only**. Disk/external caches are rejected.
It restores the current frame/subframe and verifies the baked flag after the operator returns.
Evaluated deformation must still be checked independently. Frame evaluation can update other
animated/simulated scene dependencies; this is not a scene-isolation sandbox.

The native bake call is synchronous and cannot be interrupted mid-call. Limits are workload
guards, not a hard wall-clock guarantee. These tools are excluded from `batch.execute`.
On failure, inspect cache state before retrying; explicit FREE is the cache recovery operation.
Global undo is not guaranteed to recover a baked cache. No fluid, rigid-body, particle, texture,
Geometry Nodes disk or external-file baking workflow is claimed.

## Verification

`scripts/blender_artist_smoke.py` runs in an isolated factory-startup process. Tested on Windows
with Blender 4.5.1 LTS and 5.1.2: weight normalization/lock rejection, evaluated driver output,
NLA playback/timing/removal, paired repeat/simulation zones, evaluated repeated geometry,
cloth deformation/bake/free, compositor editing and a measured red render. No user scene is touched.
Non-Blender tests cover registry/permission parity, typed forwarding, input bounds, weight failure
rollback and rejection of file caches. These are regression foundations, not complete 1.0 acceptance.
