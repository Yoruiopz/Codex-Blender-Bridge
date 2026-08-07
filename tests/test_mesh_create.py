from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.catalog import MESH_TOOL_NAMES, load_mesh_definitions
from mcp_server.tools.mesh import MeshTools


def _valid_params() -> dict[str, Any]:
    return {
        "object_name": "Structured Tetrahedron",
        "mesh_name": "Structured Tetrahedron Mesh",
        "vertices": [
            [0.0, 0.0, 1.0],
            [-1.0, -1.0, 0.0],
            [1.0, -1.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        "edges": [[0, 1], [1, 2]],
        "faces": [[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]],
        "collection_name": "Geometry",
        "location": [1.0, 2.0, 3.0],
        "rotation": [0.1, 0.2, 0.3],
        "scale": [2.0, 2.0, 2.0],
        "rotation_mode": "ZYX",
    }


def test_mesh_create_prevalidates_and_copies_complete_request(addon_package: str) -> None:
    mesh = importlib.import_module(f"{addon_package}.tools.mesh")
    prepared = mesh._prepare_mesh_create(_valid_params())

    assert prepared.object_name == "Structured Tetrahedron"
    assert prepared.mesh_name == "Structured Tetrahedron Mesh"
    assert prepared.collection_name == "Geometry"
    assert prepared.vertices[0] == (0.0, 0.0, 1.0)
    assert prepared.faces[-1] == (1, 3, 2)
    assert prepared.location == (1.0, 2.0, 3.0)
    assert prepared.rotation_mode == "ZYX"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"vertices": [[0.0, 0.0, float("inf")]]}, "finite"),
        ({"edges": [[0, 0]]}, "itself"),
        ({"edges": [[0, 1], [1, 0]]}, "duplicate"),
        ({"faces": [[0, 1, 99]]}, "out-of-range"),
        ({"faces": [[0, 1, 1]]}, "repeat"),
        ({"faces": [[0, 1]]}, "at least three"),
        ({"object_name": "x" * 64}, "63"),
        ({"rotation_mode": "QUATERNION"}, "Euler"),
    ],
)
def test_invalid_mesh_request_never_reaches_blender(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
    message: str,
) -> None:
    mesh = importlib.import_module(f"{addon_package}.tools.mesh")
    params = _valid_params()
    params.update(change)
    reached_blender = False

    def fail_if_called() -> Any:
        nonlocal reached_blender
        reached_blender = True
        raise AssertionError("invalid input reached Blender")

    monkeypatch.setattr(mesh, "require_blender", fail_if_called)
    with pytest.raises(Exception, match=message) as caught:
        mesh.create_mesh(object(), params)

    assert caught.value.code == "INVALID_ARGUMENT"
    assert reached_blender is False


def test_mesh_create_rolls_back_object_and_mesh_when_linking_fails(
    addon_package: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    mesh_module = importlib.import_module(f"{addon_package}.tools.mesh")

    class FakeMesh:
        def __init__(self, name: str) -> None:
            self.name = name
            self.users = 0

        def from_pydata(self, vertices: Any, edges: Any, faces: Any) -> None:
            self.input = (vertices, edges, faces)

        def validate(self, **_: Any) -> bool:
            return False

        def update(self, **_: Any) -> None:
            return None

    class Meshes:
        def __init__(self) -> None:
            self.created: FakeMesh | None = None
            self.removed = False

        def get(self, _: str) -> None:
            return None

        def new(self, name: str) -> FakeMesh:
            self.created = FakeMesh(name)
            return self.created

        def remove(self, _: FakeMesh) -> None:
            self.removed = True

    class Objects:
        def __init__(self) -> None:
            self.created: Any = None
            self.removed = False

        def get(self, _: str) -> None:
            return None

        def new(self, name: str, data: FakeMesh) -> Any:
            data.users += 1
            self.created = SimpleNamespace(name=name, data=data)
            return self.created

        def remove(self, obj: Any, *, do_unlink: bool) -> None:
            assert do_unlink is True
            obj.data.users -= 1
            self.removed = True

    meshes = Meshes()
    objects = Objects()
    bpy = SimpleNamespace(data=SimpleNamespace(meshes=meshes, objects=objects))
    collection = SimpleNamespace(
        objects=SimpleNamespace(link=lambda _: (_ for _ in ()).throw(RuntimeError("link failed")))
    )
    params = _valid_params()
    params["collection_name"] = None
    monkeypatch.setattr(mesh_module, "require_blender", lambda: bpy)
    monkeypatch.setattr(mesh_module, "get_collection", lambda _: collection)

    with pytest.raises(Exception) as caught:
        mesh_module.create_mesh(object(), params)

    assert caught.value.code == "OPERATION_FAILED"
    assert objects.removed is True
    assert meshes.removed is True


def test_mesh_create_registry_metadata_requires_both_permissions(addon_package: str) -> None:
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    mesh = importlib.import_module(f"{addon_package}.tools.mesh")
    registry = registry_module.ToolRegistry()
    mesh.register_tools(registry)

    spec = registry.get("mesh.create")
    assert spec.modifies is True
    assert spec.automatic_checkpoint is True
    assert spec.toolset == "mesh"
    assert spec.permissions == frozenset(
        {permissions.Permission.EDIT_MESH, permissions.Permission.TRANSFORM_OBJECTS}
    )


def test_mesh_create_mcp_definition_and_wrapper_forward_all_fields() -> None:
    definition = next(item for item in load_mesh_definitions() if item.name == "mesh.create")
    assert "mesh.create" in MESH_TOOL_NAMES
    assert definition.modifying is True
    assert definition.required_permissions == ("EDIT_MESH", "TRANSFORM_OBJECTS")

    class Registry:
        def __init__(self) -> None:
            self.call_args: tuple[str, dict[str, Any]] | None = None

        async def call(self, name: str, params: dict[str, Any]) -> dict[str, bool]:
            self.call_args = (name, params)
            return {"created": True}

    registry = Registry()
    tools = MeshTools(registry)  # type: ignore[arg-type]
    result = asyncio.run(
        tools.mesh_create(
            "Triangle",
            "Triangle Mesh",
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            faces=[[0, 1, 2]],
            collection_name="Geometry",
            location=[1.0, 2.0, 3.0],
        )
    )

    assert result == {"created": True}
    assert registry.call_args is not None
    assert registry.call_args[0] == "mesh.create"
    assert registry.call_args[1]["object_name"] == "Triangle"
    assert registry.call_args[1]["mesh_name"] == "Triangle Mesh"
    assert registry.call_args[1]["faces"] == [[0, 1, 2]]
    assert registry.call_args[1]["collection_name"] == "Geometry"
