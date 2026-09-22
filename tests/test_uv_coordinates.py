from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from mcp_server.tools.uv import UVTools


@pytest.fixture
def uv_page(addon_package):
    module = importlib.import_module(f"{addon_package}.tools.uv")
    layer = SimpleNamespace(name="UVMap", data=[
        SimpleNamespace(uv=(i / 10, i / 20), pin_uv=i == 4) for i in range(6)
    ])
    obj = SimpleNamespace(mode="OBJECT", data=SimpleNamespace(
        uv_layers=SimpleNamespace(active=layer, get=lambda name: layer if name == "UVMap" else None),
        polygons=[SimpleNamespace(index=i, loop_start=i * 3, loop_total=3, select=i == 1) for i in range(2)],
        loops=[SimpleNamespace(vertex_index=i % 4) for i in range(6)],
    ))
    return module, obj


def page(module, obj, offset=0, maximum=2, selected_only=False):
    return module._coordinate_page(obj, layer_name=None, selection_id=None,
                                   selected_only=selected_only, offset=offset, maximum=maximum)


def test_coordinate_pages_cross_face_boundaries_without_duplicates(uv_page):
    module, obj = uv_page
    items = []
    offset = 0
    while True:
        result = page(module, obj, offset)
        items.extend(result["items"])
        if result["next_offset"] is None:
            break
        offset = result["next_offset"]
    assert [(item["face_index"], item["corner_index"]) for item in items] == [
        (0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2),
    ]
    assert items[4]["uv"] == [0.4, 0.2] and items[4]["pinned"]
    assert items[0]["selected"] is None
    assert result["scoped_loop_count"] == 6 and not result["truncated"]
    assert page(module, obj, 99)["items"] == []


def test_coordinate_selection_scope_and_limits(uv_page, monkeypatch):
    module, obj = uv_page
    result = page(module, obj, selected_only=True)
    assert result["scoped_loop_count"] == 3
    assert all(item["face_index"] == 1 for item in result["items"])
    monkeypatch.setattr(module, "_MAX_LOOPS", 2)
    assert page(module, obj)["analysis_truncated"]
    assert page(module, obj)["items"] == []


@pytest.mark.parametrize("key,value", [
    ("include_coordinates", 1), ("coordinate_offset", -1),
    ("coordinate_offset", True), ("max_coordinates", 257), ("max_coordinates", 0),
])
def test_coordinate_arguments_are_bounded_and_typed(uv_page, monkeypatch, key, value):
    module, obj = uv_page
    monkeypatch.setattr(module, "_mesh_object", lambda params: obj)
    with pytest.raises(Exception) as caught:
        module.inspect_uv(None, {key: value})
    assert caught.value.code == "INVALID_ARGUMENT"


def test_coordinate_wrapper_passes_pagination():
    calls = []

    class Registry:
        async def call(self, method, params):
            calls.append((method, params))

    asyncio.run(UVTools(Registry()).uv_inspect("Cube", include_coordinates=True,
                                           coordinate_offset=12, max_coordinates=4))
    method, params = calls[0]
    assert method == "uv.inspect"
    assert params["include_coordinates"] and params["coordinate_offset"] == 12
    assert params["max_coordinates"] == 4
