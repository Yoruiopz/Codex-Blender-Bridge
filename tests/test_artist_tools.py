from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from mcp_server.errors import BridgeError
from mcp_server.tool_registry import create_default_registry
from mcp_server.tools.artist import TOOL_DATA, ArtistTools

MODULES = ("weights", "compositor", "animation_layers", "simulation")


def test_artist_metadata_and_permissions(addon_package):
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    registry = registry_module.ToolRegistry(enabled_toolsets=MODULES)
    for module in MODULES:
        importlib.import_module(f"{addon_package}.tools.{module}").register_tools(registry)
    context = SimpleNamespace(permissions=permissions.PermissionManager(lambda: {}))
    for name, group, modifies, required, _ in TOOL_DATA:
        spec = registry.get(name)
        assert spec.toolset == group and spec.modifies == modifies
        assert {p.value for p in spec.permissions} == set(required)
        assert spec.automatic_checkpoint
        with pytest.raises(Exception) as caught:
            registry.dispatch(name, {}, context)
        assert caught.value.code == "PERMISSION_DENIED"
    mcp = create_default_registry(None)
    assert mcp.enabled_toolsets == ("core",)
    for group in MODULES:
        mcp.enable(group)
    assert {name for name, *_ in TOOL_DATA} <= set(mcp.tool_names())
    assert len(ArtistTools(mcp).bindings()) == len(TOOL_DATA) + 3


@pytest.mark.parametrize(
    "module,handler",
    [
        ("weights", "inspect"),
        ("weights", "group_create"),
        ("weights", "assign"),
        ("weights", "normalize"),
        ("weights", "smooth"),
        ("weights", "transfer"),
        ("compositor", "inspect"),
        ("compositor", "create"),
        ("animation_layers", "inspect"),
        ("animation_layers", "driver_add"),
        ("animation_layers", "driver_remove"),
        ("animation_layers", "nla_add"),
        ("animation_layers", "nla_edit"),
        ("simulation", "inspect"),
        ("simulation", "cloth_add"),
        ("simulation", "configure"),
        ("simulation", "cache"),
        ("geometry_nodes", "zone_create"),
        ("geometry_nodes", "zone_item_add"),
        ("geometry_nodes", "zone_remove"),
    ],
)
def test_artist_rejects_unknown_params(addon_package, module, handler):
    mod = importlib.import_module(f"{addon_package}.tools.{module}")
    with pytest.raises(Exception) as caught:
        getattr(mod, handler)(None, {"unexpected": True})
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("value", [None, [], [True], [0, 0], [-1], [4], [[0]], list(range(1001))])
def test_weight_indices_are_bounded(addon_package, value):
    mod = importlib.import_module(f"{addon_package}.tools.weights")
    with pytest.raises(Exception) as caught:
        mod._indices(SimpleNamespace(data=SimpleNamespace(vertices=[None] * 4)), value)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_weight_rollback_restores_membership(addon_package):
    mod = importlib.import_module(f"{addon_package}.tools.weights")
    values = [0.2, 0.3]

    class Group:
        index = 0
        calls = 0

        def add(self, indices, value, mode):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("injected failure")
            values[indices[0]] = value

    obj = SimpleNamespace(
        name="Mesh",
        data=SimpleNamespace(
            vertices=[
                SimpleNamespace(groups=[SimpleNamespace(group=0, weight=value)]) for value in values
            ]
        ),
    )
    group = Group()
    with pytest.raises(Exception) as caught:
        mod._apply(obj, [(group, 0, 0.7), (group, 1, 0.8)])
    assert caught.value.code == "OPERATION_FAILED"
    assert caught.value.context["rollback_performed"]
    assert values == [0.2, 0.3]


@pytest.mark.parametrize("operation", [None, [], {}, "SCRIPT"])
def test_compositor_invalid_operation(addon_package, operation):
    mod = importlib.import_module(f"{addon_package}.tools.compositor")
    with pytest.raises(Exception) as caught:
        mod.edit(None, {"operation": operation})
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("field", ["use_disk_cache", "use_external"])
def test_simulation_rejects_file_caches(addon_package, monkeypatch, field):
    mod = importlib.import_module(f"{addon_package}.tools.simulation")
    cache = SimpleNamespace(use_disk_cache=False, use_external=False, is_baked=False)
    setattr(cache, field, True)
    modifier = SimpleNamespace(point_cache=cache, settings=SimpleNamespace(quality=2))
    obj = SimpleNamespace(data=SimpleNamespace(vertices=[None] * 4), modifiers=[modifier])
    monkeypatch.setattr(mod, "_object", lambda *args: obj)
    monkeypatch.setattr(mod, "_modifier", lambda *args: modifier)
    for handler, params in (
        (mod.cache, {"operation": "BAKE"}),
        (mod.configure, {"settings": {"mass": 0.5}}),
    ):
        with pytest.raises(Exception) as caught:
            handler(None, params)
        assert caught.value.code == "INVALID_ARGUMENT"
        assert "memory" in caught.value.message


def test_wrappers_preserve_null_and_reject_reserved_fields():
    class Recording:
        async def call(self, name, params):
            return name, params

    wrapper = ArtistTools(Recording())
    name, params = asyncio.run(wrapper.weights_assign("Mesh", "Group", [0], None))
    assert name == "weights.assign" and "weight" in params and params["weight"] is None
    with pytest.raises(BridgeError) as caught:
        asyncio.run(wrapper.compositor_edit("Scene", "ADD", {"scene_name": "Other"}))
    assert caught.value.code == "INVALID_ARGUMENT"
