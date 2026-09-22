from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.layout import LAYOUT_TOOL_DATA, LayoutTools


class FakeObject:
    def __init__(self, name: str, location: tuple[float, float, float]) -> None:
        self.name = name
        self._location = location
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.rotation_mode = "XYZ"
        self.scale = (1.0, 1.0, 1.0)
        self.dimensions = (2.0, 2.0, 2.0)
        self.delta_location = self.delta_rotation_euler = (0.0, 0.0, 0.0)
        self.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        self.delta_scale = (1.0, 1.0, 1.0)
        self.lock_location = self.lock_rotation = self.lock_scale = (False, False, False)
        self.is_editable = True
        self.library = self.override_library = self.parent = self.animation_data = self.rigid_body = None
        self.children: list[Any] = []
        self.constraints: list[Any] = []
        self.selected = True
        self.visible = True
        self.type = "MESH"
        self.reject_location = False
        self.origin_offset = 0.0

    @property
    def location(self) -> tuple[float, float, float]:
        return self._location

    @location.setter
    def location(self, value: tuple[float, float, float]) -> None:
        if self.reject_location and value[0] == 999.0:
            raise RuntimeError("injected setter failure")
        self._location = value

    def evaluated_get(self, _depsgraph: Any) -> Any:
        return SimpleNamespace(matrix_world=SimpleNamespace(translation=(self.location[0] + self.origin_offset, *self.location[1:])))

    def select_get(self, *, view_layer: Any) -> bool:
        return self.selected

    def visible_get(self, *, view_layer: Any) -> bool:
        return self.visible


class FakeObjects(dict[str, FakeObject]):
    def __iter__(self) -> Any:
        return iter(self.values())


@pytest.fixture
def layout_env(addon_package: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    module = importlib.import_module(f"{addon_package}.tools.layout")
    errors = importlib.import_module(f"{addon_package}.errors")
    objects = FakeObjects({name: FakeObject(name, location) for name, location in (
        ("A", (0.0, 1.0, 2.0)), ("B", (2.0, 3.0, 4.0)), ("C", (10.0, 5.0, 6.0)),
    )})
    view_layer = SimpleNamespace(name="ViewLayer", objects=objects, update=lambda: None)
    scene = SimpleNamespace(name="Scene", collection=SimpleNamespace(name="Scene Collection", all_objects=objects))
    bpy = SimpleNamespace(context=SimpleNamespace(view_layer=view_layer, scene=scene, mode="OBJECT", evaluated_depsgraph_get=lambda: object()), data=SimpleNamespace(collections={}))
    monkeypatch.setattr(module, "require_blender", lambda: bpy)

    def get_object(name: str, *, allow_active: bool) -> FakeObject:
        assert allow_active is False
        if name not in objects:
            raise errors.BridgeError(errors.ErrorCode.OBJECT_NOT_FOUND, "Missing object.")
        return objects[name]

    monkeypatch.setattr(module, "get_object", get_object)
    return SimpleNamespace(module=module, errors=errors, objects=objects, bpy=bpy)


def test_layout_metadata_matches_mcp_and_is_permission_gated(addon_package: str) -> None:
    module = importlib.import_module(f"{addon_package}.tools.layout")
    registry = importlib.import_module(f"{addon_package}.tool_registry").ToolRegistry()
    module.register_tools(registry)
    for name, description, modifying, permissions in LAYOUT_TOOL_DATA:
        spec = registry.get(name)
        assert spec.toolset == "layout"
        assert spec.description == description
        assert spec.modifies is modifying
        assert {permission.value for permission in spec.permissions} == set(permissions)
        assert spec.automatic_checkpoint


def test_query_filters_measured_origins_and_paginates(layout_env: Any) -> None:
    module = layout_env.module
    first = module.query_scene(object(), {"origin_min": [0, 0, 0], "origin_max": [10, 10, 10], "limit": 2})
    assert [obj["object"] for obj in first["objects"]] == ["A", "B"]
    assert first["matched_count"] == 3
    assert first["next_offset"] == 2
    assert first["result_truncated"] is True
    assert first["matches_complete"] is True
    second = module.query_scene(object(), {"offset": 2, "limit": 2})
    assert second["objects"][0]["world_origin"] == [10.0, 5.0, 6.0]
    assert second["next_offset"] is None


def test_query_filters_selection_visibility_type_collection_and_glob(layout_env: Any) -> None:
    env = layout_env
    env.objects["B"].visible = False
    env.objects["C"].selected = False
    env.bpy.data.collections["Subset"] = SimpleNamespace(all_objects={"A", "B"})
    result = env.module.query_scene(object(), {"name_pattern": "[AB]", "object_types": ["mesh"], "collection_name": "Subset", "selected": True, "visible": True})
    assert [item["object"] for item in result["objects"]] == ["A"]
    assert env.module.query_scene(object(), {"name_pattern": "a"})["matched_count"] == 0


def test_query_reports_bounded_scan(layout_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(layout_env.module, "MAX_QUERY_SCAN", 2)
    result = layout_env.module.query_scene(object(), {})
    assert result["scanned_count"] == result["matched_count"] == 2
    assert result["scan_truncated"] and result["result_truncated"]
    assert result["matches_complete"] is False


@pytest.mark.parametrize("params", [{"visible": 1}, {"limit": True}, {"offset": -1}, {"limit": 201}, {"origin_min": [10, 0, 0], "origin_max": [0, 0, 0]}, {"origin_min": [float("inf"), 0, 0]}, {"object_types": "MESH"}, {"typo": "*"}])
def test_query_rejects_malformed_input(layout_env: Any, params: dict[str, Any]) -> None:
    with pytest.raises(layout_env.errors.BridgeError):
        layout_env.module.query_scene(object(), params)


def test_batch_prevalidates_every_record_before_mutation(layout_env: Any) -> None:
    env = layout_env
    before = env.objects["A"].location
    with pytest.raises(env.errors.BridgeError):
        env.module.transform_batch(object(), {"edits": [{"object_name": "A", "location": [5, 5, 5]}, {"object_name": "B", "scale": [1, float("nan"), 1]}]})
    assert env.objects["A"].location == before
    with pytest.raises(env.errors.BridgeError):
        env.module.transform_batch(object(), {"edits": [{"object_name": "A", "location": [5, 5, 5]}, {"object_name": "Missing", "scale": [1, 1, 1]}]})
    assert env.objects["A"].location == before


def test_batch_applies_components_and_preserves_selection(layout_env: Any) -> None:
    env = layout_env
    result = env.module.transform_batch(object(), {"edits": [{"object_name": "A", "location": [5, 5, 5], "rotation": [0.1, 0.2, 0.3]}, {"object_name": "B", "scale": [2, 3, 4]}]})
    assert result["verified"] and result["changed"]
    assert result["affected_objects"] == ["A", "B"]
    assert env.objects["A"].location == (5, 5, 5)
    assert env.objects["A"].rotation_euler == (0.1, 0.2, 0.3)
    assert env.objects["B"].scale == (2, 3, 4)
    assert all(obj.selected for obj in env.objects)


def test_batch_restores_all_objects_after_late_assignment_failure(layout_env: Any) -> None:
    env = layout_env
    before = {obj.name: obj.location for obj in env.objects}
    env.objects["B"].reject_location = True
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.transform_batch(object(), {"edits": [{"object_name": "A", "location": [5, 5, 5]}, {"object_name": "B", "location": [999, 5, 5]}]})
    assert caught.value.context["rollback_complete"] is True
    assert caught.value.context["execution_started"] is True
    assert {obj.name: obj.location for obj in env.objects} == before


def test_batch_rejects_evaluated_mismatch_and_restores_channels(layout_env: Any) -> None:
    env = layout_env
    env.objects["A"].origin_offset = 1
    before = env.objects["A"].location
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.transform_batch(object(), {"edits": [{"object_name": "A", "location": [5, 5, 5]}]})
    assert caught.value.context["rollback_complete"] is True
    assert env.objects["A"].location == before


@pytest.mark.parametrize(("attribute", "value"), [("parent", object()), ("children", [object()]), ("constraints", [object()]), ("rigid_body", object()), ("delta_location", (1, 0, 0)), ("animation_data", SimpleNamespace(action=object(), drivers=[], nla_tracks=[]))])
def test_batch_rejects_transform_dependencies_before_mutation(layout_env: Any, attribute: str, value: Any) -> None:
    env = layout_env
    setattr(env.objects["B"], attribute, value)
    before = env.objects["A"].location
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.transform_batch(object(), {"edits": [{"object_name": "A", "location": [5, 5, 5]}, {"object_name": "B", "location": [6, 5, 5]}]})
    assert caught.value.code == "NOT_IMPLEMENTED"
    assert env.objects["A"].location == before


def test_batch_honors_mode_and_component_locks(layout_env: Any) -> None:
    env = layout_env
    env.objects["B"].lock_location = (True, False, False)
    before = env.objects["A"].location
    with pytest.raises(env.errors.BridgeError):
        env.module.align_objects(object(), {"object_names": ["A", "B"], "axis": "X"})
    assert env.objects["A"].location == before
    env.bpy.context.mode = "EDIT_MESH"
    with pytest.raises(env.errors.BridgeError) as caught:
        env.module.transform_batch(object(), {"edits": [{"object_name": "A", "location": [1, 1, 1]}]})
    assert caught.value.code == "INVALID_MODE"


def test_align_uses_world_origin_extrema_midpoint_and_explicit_reference(layout_env: Any) -> None:
    env = layout_env
    result = env.module.align_objects(object(), {"object_names": ["A", "B", "C"], "axis": "X", "target": "CENTER"})
    assert result["coordinate"] == 5.0
    assert [obj.location for obj in env.objects] == [(5, 1, 2), (5, 3, 4), (5, 5, 6)]
    env.module.align_objects(object(), {"object_names": ["A", "B", "C"], "axis": "Y", "target": "REFERENCE", "reference_object": "C"})
    assert [obj.location[1] for obj in env.objects] == [5, 5, 5]


def test_distribute_sorts_and_preserves_endpoints_and_other_axes(layout_env: Any) -> None:
    env = layout_env
    result = env.module.distribute_objects(object(), {"object_names": ["C", "A", "B"], "axis": "X"})
    assert result["order"] == ["A", "B", "C"]
    assert result["spacing"] == 5
    assert env.objects["A"].location == (0, 1, 2)
    assert env.objects["B"].location == (5, 3, 4)
    assert env.objects["C"].location == (10, 5, 6)


@pytest.mark.parametrize("params", [{"object_names": ["A", "A"]}, {"object_names": ["A", "B"], "target": "ACTIVE"}, {"object_names": ["A", "B"], "target": "REFERENCE", "reference_object": "C"}, {"object_names": ["A", "B"], "axis": "XY"}])
def test_align_rejects_ambiguous_or_duplicate_targets(layout_env: Any, params: dict[str, Any]) -> None:
    with pytest.raises(layout_env.errors.BridgeError):
        layout_env.module.align_objects(object(), params)


def test_layout_wrappers_forward_only_json_fields() -> None:
    class RecordingRegistry:
        async def call(self, name: str, values: dict[str, Any]) -> Any:
            return {"name": name, "params": values}

    tools = LayoutTools(RecordingRegistry())  # type: ignore[arg-type]
    result = asyncio.run(tools.scene_query(selected=False, origin_min=[0, 0, 0]))
    assert result == {"name": "scene.query", "params": {"name_pattern": "*", "selected": False, "origin_min": [0, 0, 0], "offset": 0, "limit": 50}}
    result = asyncio.run(tools.object_transform_batch([{"object_name": "Cube", "location": [1, 2, 3]}]))
    assert result["params"]["edits"][0] == {"object_name": "Cube", "location": [1, 2, 3]}


def test_layout_mcp_schema_has_typed_transform_records() -> None:
    from mcp import Client
    from mcp.server import MCPServer

    async def scenario() -> None:
        server = MCPServer("Layout schema test")
        tools = LayoutTools(object())  # type: ignore[arg-type]
        server.tool(name="object.transform_batch")(tools.object_transform_batch)
        async with Client(server) as client:
            response = await client.list_tools()
            schema = response.tools[0].input_schema
            definitions = schema["$defs"]
            assert definitions["TransformEdit"]["required"] == ["object_name"]
            assert definitions["TransformEdit"]["properties"]["location"]["items"]["type"] == "number"

    asyncio.run(scenario())
