# Nested Geometry Nodes and modifier constants

Unreleased development tools; absent from published 0.3.0. They use Blender's data API
on the main thread, authoritative permissions and normal history/checkpoint handling.
They do not run arbitrary Python, open files, apply modifiers or save projects.

## Typed workflow

1. Create root/leaf graphs with `geometry_nodes.create`, add reviewed interfaces/nodes,
   and configure leaf graphs with the existing structured tools.
2. Use `geometry_nodes.group_bind(parent_group_name, child_group_name, node_name)` to
   create a uniquely named `GeometryNodeGroup` instance. Every reachable graph is reviewed
   before introducing an evaluation dependency. File/import/script nodes remain excluded.
3. Inspect current node sockets with `geometry_nodes.inspect`. Use exact socket
   **identifiers**, not UI labels or indices, with `geometry_nodes.group_link` and
   `geometry_nodes.group_set_input`. Occupied link targets require `replace_existing=true`.
4. Attach the reviewed nested root to an exact mesh object with
   `geometry_nodes.group_attach`. An existing different group needs explicit
   `replace_existing_group=true`; existing modifier properties are bounded and retained
   for measured failure recovery.
5. Call `geometry_nodes.modifier_inspect(object_name, modifier_name)` to obtain current
   interface identifiers, stored values, attribute-use flags and labels. Call
   `geometry_nodes.modifier_set_input` to set an explicit constant on that object's
   modifier. This leaves the graph definition and other objects' modifier values unchanged,
   including when the mesh or node group is shared.
6. Use `geometry_nodes.group_copy_for_node` to isolate one child-root tree before editing
   its definition. Input identifiers/defaults and parent graph links are checked after
   rebinding. Referenced descendants remain shared: this is explicitly **not a deep copy**.
7. Remove an unused version with `geometry_nodes.group_remove(confirm_unused=true)`.
   Actual datablock deletion requires `DELETE_OBJECTS` plus `EDIT_MESH`; any real or fake
   user prevents removal. No consumers are forcibly unlinked.

The original `geometry_nodes.*` graph mutators retain their existing shallow reviewed
contract; they do not start accepting arbitrary nested graphs implicitly. The new
identifier-based link/default methods work on recursively reviewed graphs. Broader
interface/instance removal and nested node-property editing remain open workflows.

## Scope and permissions

Graph mutations require `EDIT_MESH`; attachment and modifier-constant edits also require
`TRANSFORM_OBJECTS`. Inspection requires `INSPECT_SCENE`. Mutations require Object Mode,
local editable non-override group dependencies and editable parent consumers.

The parent ownership review follows GN groups to direct object consumers, reports affected
objects and refuses scopes beyond its budget. Shared or nested definitions require
`allow_shared=true` on each graph edit. This acknowledges the reported consumer scope;
it does not isolate the edited tree. Collection/geometry instances and evaluated transitive
effects still require separate inspection. Object-owned modifier constants do not require
shared-graph acknowledgement because they do not change the definition.

Reachable graphs are limited to 32 distinct trees, depth eight, 256 nodes/1,024 links and
128 interface items per tree, with 128 sockets per node direction. Parent review supports
32 groups and 100 consumers. Recursive/unbound groups, ambiguous names and exhausted scope
fail before normal mutation. A final review catches dependencies that grow during binding;
failed allocations then return measured recovery evidence.

Supported modifier constants are float, signed 32-bit integer, boolean, three-component
vector, four-component color and bounded string. Numeric values must be finite; float/vector
magnitudes are limited to 1e20 and strings to 1,024 printable characters. Native readback
uses explicit small float tolerances and refuses an unexpected clamp/change. Input identity
uses `interface.identifier`; the interface collection's name lookup is not treated as an
identifier lookup. Label changes therefore do not silently retarget a stored modifier value.

Attribute-driven modifier inputs and animated objects are refused for constant editing.
Group defaults must be enabled and unlinked. Multi-input links are refused until native
ordering/recovery has a reviewed contract. Simulation/repeat zone lifecycle, zone-item type
conversion, disk baking, general bake jobs and production scene-size acceptance are not
completed by this increment.

## Failure and verification

Handlers recheck permission, pause/stop and cancellation before and after mutation. They
return structural state and `verification_required=true`, never an evaluated-geometry
certificate. Independently inspect evaluated output and protected objects, then capture
appropriate appearance evidence when the task needs it.

Recovery attempts require live permissions. A failed instance copy can restore its binding
while retaining an unused new tree when deletion consent is absent. Such failures report
`binding_restored`, `cleanup_denied`, `retained_group`, `possible_mutation` and the measured
`rollback_verified` result. Restoring a binding alone is not reported as full rollback.
Reinspect before continuing; native undo remains finite and needs separate UI acceptance.

## Development evidence

`scripts/blender_geometry_node_groups_smoke.py` uses typed runtime dispatch and independently
measures evaluated grid topology/bounds. It verifies all exposed modifier constant types,
stable identifiers after an explicit fixture label change, one-instance copy isolation,
protected geometry, recursive rejection, permission denial and a post-allocation fault with
denied cleanup. Shared source meshes and selection/mode remain unchanged.

Run through the isolated runner:

```text
python scripts/run_blender_checks.py --blender <absolute executable> --case geometry_node_groups --output <unused evidence directory>
```

The focused Linux Blender 4.3.2 run passed at
`build/geometry-node-groups-native-20261022-b/report.json`. This is dirty-source development
evidence with `release_readiness=NOT_ASSESSED`. Windows 4.5/5.x, actual native undo/recovery,
packaged installation, visual quality and complete procedural/simulation acceptance remain open.
