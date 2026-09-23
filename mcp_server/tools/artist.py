"""Typed MCP entry points for new structured artist domains."""

from __future__ import annotations

from typing import Any, Literal

from ..errors import BridgeError
from ..tool_registry import ToolDefinition, ToolRegistry, remote_tool
from ._common import MCPToolBinding, params

TOOL_DATA = (
    (
        "nla.edit_track",
        "animation_layers",
        True,
        ("EDIT_ANIMATION",),
        "Rename, mute or lock an exact NLA track, or remove an unlocked empty track without deleting actions.",
    ),
    (
        "weights.smooth",
        "weights",
        True,
        ("EDIT_MESH",),
        "Smooth one unlocked group across mesh edges on explicit vertices; fixed outside boundary and no implicit normalization.",
    ),
    (
        "weights.transfer",
        "weights",
        True,
        ("EDIT_MESH",),
        "Copy one group through explicit source/target vertex pairs, snapshotting before writes; no geometric correspondence guesses.",
    ),
    (
        "weights.inspect",
        "weights",
        False,
        ("INSPECT_SCENE",),
        "Inspect paginated vertex weights and locked groups in Object Mode.",
    ),
    (
        "weights.group_create",
        "weights",
        True,
        ("EDIT_MESH",),
        "Create an explicitly named vertex group on a local single-user mesh.",
    ),
    (
        "weights.assign",
        "weights",
        True,
        ("EDIT_MESH",),
        "Assign a weight or remove memberships on up to 1000 explicit vertices; rollback on failure.",
    ),
    (
        "weights.normalize",
        "weights",
        True,
        ("EDIT_MESH",),
        "Normalize named unlocked groups while preserving all unmentioned weights.",
    ),
    (
        "compositor.inspect",
        "compositor",
        False,
        ("INSPECT_SCENE",),
        "Inspect bounded scene compositor nodes, sockets and links.",
    ),
    (
        "compositor.create",
        "compositor",
        True,
        ("EDIT_RENDER",),
        "Initialize a missing compositor graph without replacing existing work.",
    ),
    (
        "compositor.edit",
        "compositor",
        True,
        ("EDIT_RENDER",),
        "Add/remove/configure reviewed compositor nodes and edit exact socket defaults/links.",
    ),
    (
        "animation_layers.inspect",
        "animation_layers",
        False,
        ("INSPECT_SCENE",),
        "Inspect bounded object drivers, NLA tracks and strips.",
    ),
    (
        "drivers.add",
        "animation_layers",
        True,
        ("EDIT_ANIMATION",),
        "Create a non-scripted transform driver from explicit independent source objects.",
    ),
    (
        "drivers.remove",
        "animation_layers",
        True,
        ("EDIT_ANIMATION",),
        "Remove one exact object transform driver.",
    ),
    (
        "nla.add_strip",
        "animation_layers",
        True,
        ("EDIT_ANIMATION",),
        "Add an existing action as an explicit NLA strip on a new named track, with slot selection.",
    ),
    (
        "nla.edit_strip",
        "animation_layers",
        True,
        ("EDIT_ANIMATION",),
        "Configure a named single-track CLIP strip or explicitly remove it.",
    ),
    (
        "simulation.inspect",
        "simulation",
        False,
        ("INSPECT_SCENE",),
        "Inspect one cloth modifier and its point-cache state.",
    ),
    (
        "simulation.cloth_add",
        "simulation",
        True,
        ("EDIT_MESH", "EDIT_SCENE"),
        "Add cloth to a local single-user mesh with a bounded empty modifier stack.",
    ),
    (
        "simulation.configure",
        "simulation",
        True,
        ("EDIT_MESH", "EDIT_SCENE"),
        "Configure reviewed cloth and pin-group settings before baking.",
    ),
    (
        "simulation.cache",
        "simulation",
        True,
        ("EDIT_MESH", "EDIT_SCENE", "EDIT_ANIMATION"),
        "Bake/free one in-memory cloth cache, at most 32 frames and 2000 vertices; excluded from batches.",
    ),
)


def load_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        remote_tool(
            name,
            toolset=group,
            modifying=modifies,
            required_permissions=permissions,
            description=description,
        )
        for name, group, modifies, permissions, description in TOOL_DATA
    )


class ArtistTools:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def weights_smooth(
        self,
        object_name: str,
        group_name: str,
        vertex_indices: list[int],
        iterations: int = 1,
        factor: float = 0.5,
    ) -> Any:
        return await self.registry.call(
            "weights.smooth",
            params(
                object_name=object_name,
                group_name=group_name,
                vertex_indices=vertex_indices,
                iterations=iterations,
                factor=factor,
            ),
        )

    async def weights_transfer(
        self,
        source_object: str,
        source_group: str,
        object_name: str,
        group_name: str,
        source_indices: list[int],
        vertex_indices: list[int],
    ) -> Any:
        return await self.registry.call(
            "weights.transfer",
            params(
                source_object=source_object,
                source_group=source_group,
                object_name=object_name,
                group_name=group_name,
                source_indices=source_indices,
                vertex_indices=vertex_indices,
            ),
        )

    async def weights_inspect(
        self, object_name: str, offset: int = 0, max_vertices: int = 50
    ) -> Any:
        return await self.registry.call(
            "weights.inspect",
            params(object_name=object_name, offset=offset, max_vertices=max_vertices),
        )

    async def weights_group_create(self, object_name: str, group_name: str) -> Any:
        return await self.registry.call(
            "weights.group_create", params(object_name=object_name, group_name=group_name)
        )

    async def weights_assign(
        self, object_name: str, group_name: str, vertex_indices: list[int], weight: float | None
    ) -> Any:
        return await self.registry.call(
            "weights.assign",
            {
                "object_name": object_name,
                "group_name": group_name,
                "vertex_indices": vertex_indices,
                "weight": weight,
            },
        )

    async def weights_normalize(
        self, object_name: str, group_names: list[str], vertex_indices: list[int]
    ) -> Any:
        return await self.registry.call(
            "weights.normalize",
            params(object_name=object_name, group_names=group_names, vertex_indices=vertex_indices),
        )

    async def compositor_inspect(
        self, scene_name: str, max_nodes: int = 100, max_links: int = 200
    ) -> Any:
        return await self.registry.call(
            "compositor.inspect",
            params(scene_name=scene_name, max_nodes=max_nodes, max_links=max_links),
        )

    async def compositor_create(self, scene_name: str) -> Any:
        return await self.registry.call("compositor.create", {"scene_name": scene_name})

    async def compositor_edit(
        self,
        scene_name: str,
        operation: Literal["ADD", "REMOVE", "SET", "INPUT", "OUTPUT", "LINK", "UNLINK"],
        arguments: dict[str, Any],
    ) -> Any:
        """ADD: node_type/node_name/settings; SET: node_name/settings; INPUT: node_name/socket_name/value/socket_index?; REMOVE: node_name; LINK/UNLINK: from_node/from_socket/to_node/to_socket and optional socket indices; LINK also accepts replace_existing."""
        if "scene_name" in arguments or "operation" in arguments:
            raise BridgeError(
                "INVALID_ARGUMENT", "arguments cannot override scene_name or operation"
            )
        return await self.registry.call(
            "compositor.edit", {"scene_name": scene_name, "operation": operation, **arguments}
        )

    async def animation_layers_inspect(self, object_name: str) -> Any:
        return await self.registry.call("animation_layers.inspect", {"object_name": object_name})

    async def drivers_add(
        self,
        object_name: str,
        data_path: Literal["location", "rotation_euler", "scale"],
        variables: list[dict[str, str]],
        index: int = 0,
        driver_type: Literal["AVERAGE", "SUM", "MIN", "MAX"] = "AVERAGE",
    ) -> Any:
        """Each variable has object_name, transform_type (LOC_X/ROT_X/SCALE_X, etc.), transform_space. No expressions or arbitrary RNA paths."""
        return await self.registry.call(
            "drivers.add",
            params(
                object_name=object_name,
                data_path=data_path,
                variables=variables,
                index=index,
                driver_type=driver_type,
            ),
        )

    async def drivers_remove(
        self,
        object_name: str,
        data_path: Literal["location", "rotation_euler", "scale"],
        index: int = 0,
    ) -> Any:
        return await self.registry.call(
            "drivers.remove", params(object_name=object_name, data_path=data_path, index=index)
        )

    async def nla_add_strip(
        self,
        object_name: str,
        track_name: str,
        strip_name: str,
        action_name: str,
        frame_start: int = 1,
        slot_identifier: str | None = None,
    ) -> Any:
        return await self.registry.call(
            "nla.add_strip",
            params(
                object_name=object_name,
                track_name=track_name,
                strip_name=strip_name,
                action_name=action_name,
                frame_start=frame_start,
                slot_identifier=slot_identifier,
            ),
        )

    async def nla_edit_track(
        self,
        object_name: str,
        track_name: str,
        settings: dict[str, Any] | None = None,
        remove: bool = False,
    ) -> Any:
        return await self.registry.call(
            "nla.edit_track",
            params(
                object_name=object_name, track_name=track_name, settings=settings, remove=remove
            ),
        )

    async def nla_edit_strip(
        self,
        object_name: str,
        track_name: str,
        strip_name: str,
        settings: dict[str, Any] | None = None,
        remove: bool = False,
    ) -> Any:
        return await self.registry.call(
            "nla.edit_strip",
            params(
                object_name=object_name,
                track_name=track_name,
                strip_name=strip_name,
                settings=settings,
                remove=remove,
            ),
        )

    async def simulation_inspect(self, object_name: str, modifier_name: str) -> Any:
        return await self.registry.call(
            "simulation.inspect", params(object_name=object_name, modifier_name=modifier_name)
        )

    async def simulation_cloth_add(self, object_name: str, modifier_name: str) -> Any:
        return await self.registry.call(
            "simulation.cloth_add", params(object_name=object_name, modifier_name=modifier_name)
        )

    async def simulation_configure(
        self, object_name: str, modifier_name: str, settings: dict[str, Any]
    ) -> Any:
        return await self.registry.call(
            "simulation.configure",
            params(object_name=object_name, modifier_name=modifier_name, settings=settings),
        )

    async def simulation_cache(
        self,
        object_name: str,
        modifier_name: str,
        operation: Literal["BAKE", "FREE"],
        frame_start: int = 1,
        frame_end: int = 10,
    ) -> Any:
        return await self.registry.call(
            "simulation.cache",
            params(
                object_name=object_name,
                modifier_name=modifier_name,
                operation=operation,
                frame_start=frame_start,
                frame_end=frame_end,
            ),
        )

    async def geometry_nodes_zone_create(
        self,
        group_name: str,
        zone_type: Literal["REPEAT", "SIMULATION"],
        input_name: str,
        output_name: str,
        iterations: int = 1,
        allow_shared: bool = False,
    ) -> Any:
        return await self.registry.call(
            "geometry_nodes.zone_create",
            params(
                group_name=group_name,
                zone_type=zone_type,
                input_name=input_name,
                output_name=output_name,
                iterations=iterations,
                allow_shared=allow_shared,
            ),
        )

    async def geometry_nodes_zone_item_add(
        self,
        group_name: str,
        output_name: str,
        socket_type: Literal["GEOMETRY", "FLOAT", "INT", "BOOLEAN", "VECTOR", "RGBA"],
        name: str,
        allow_shared: bool = False,
    ) -> Any:
        return await self.registry.call(
            "geometry_nodes.zone_item_add",
            params(
                group_name=group_name,
                output_name=output_name,
                socket_type=socket_type,
                name=name,
                allow_shared=allow_shared,
            ),
        )

    async def geometry_nodes_zone_remove(
        self, group_name: str, output_name: str, allow_shared: bool = False
    ) -> Any:
        return await self.registry.call(
            "geometry_nodes.zone_remove",
            params(group_name=group_name, output_name=output_name, allow_shared=allow_shared),
        )

    async def geometry_nodes_zone_item_edit(
        self,
        group_name: str,
        output_name: str,
        name: str,
        operation: Literal["RENAME", "MOVE", "REMOVE"],
        new_name: str | None = None,
        to_index: int | None = None,
        allow_shared: bool = False,
    ) -> Any:
        return await self.registry.call(
            "geometry_nodes.zone_item_edit",
            params(
                group_name=group_name,
                output_name=output_name,
                name=name,
                operation=operation,
                new_name=new_name,
                to_index=to_index,
                allow_shared=allow_shared,
            ),
        )

    def bindings(self) -> tuple[MCPToolBinding, ...]:
        methods = {name: getattr(self, name.replace(".", "_")) for name, *_ in TOOL_DATA}
        descriptions = {name: description for name, _, _, _, description in TOOL_DATA}
        for suffix in ("zone_create", "zone_item_add", "zone_item_edit", "zone_remove"):
            name = f"geometry_nodes.{suffix}"
            methods[name] = getattr(self, f"geometry_nodes_{suffix}")
            descriptions[name] = f"Structured paired Geometry Nodes {suffix}."
        return tuple(
            MCPToolBinding(name, handler, (handler.__doc__ or descriptions[name]))
            for name, handler in methods.items()
        )
