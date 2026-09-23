from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools import constraints as mcp_constraints
from mcp_server.tools import modifiers as mcp_modifiers
from mcp_server.tools import uv as mcp_uv


class _RNAProperty:
    def __init__(
        self,
        kind: str,
        *,
        array_length: int = 0,
        minimum: float = -1_000_000,
        maximum: float = 1_000_000,
        enum: tuple[str, ...] = (),
        readonly: bool = False,
    ) -> None:
        self.type = kind
        self.array_length = array_length
        self.hard_min = minimum
        self.hard_max = maximum
        self.enum_items = [SimpleNamespace(identifier=item) for item in enum]
        self.is_enum_flag = False
        self.is_readonly = readonly


class _Owner:
    def __init__(self) -> None:
        self.bl_rna = SimpleNamespace(
            properties={
                "width": _RNAProperty("FLOAT", minimum=0.0, maximum=10.0),
                "segments": _RNAProperty("INT", minimum=1, maximum=16),
                "enabled": _RNAProperty("BOOLEAN"),
                "mode": _RNAProperty("ENUM", enum=("ONE", "TWO")),
                "target": _RNAProperty("POINTER"),
                "offset": _RNAProperty("FLOAT", array_length=3),
            }
        )
        self.width = 1.0
        self.segments = 2
        self.enabled = True
        self.mode = "ONE"
        self.target = None
        self.offset = (0.0, 0.0, 0.0)


class _FailingOwner(_Owner):
    def __init__(self) -> None:
        self._segments = 2
        self.fail_segments = False
        super().__init__()
        self.fail_segments = True

    @property
    def segments(self) -> int:
        return self._segments

    @segments.setter
    def segments(self, value: int) -> None:
        if getattr(self, "fail_segments", False) and value != 2:
            raise ValueError("synthetic Blender setter failure")
        self._segments = value


def _fake_bpy(objects: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(data=SimpleNamespace(objects=objects or {}))


def test_rna_prevalidates_batch_and_rejects_nonfinite_values(addon_package: str) -> None:
    rna = importlib.import_module(f"{addon_package}.tools._rna")
    owner = _Owner()

    with pytest.raises(Exception) as caught:
        rna.prepare_assignments(
            owner,
            {"width": 3.0, "segments": 99},
            allowed=frozenset({"width", "segments"}),
            object_pointers=frozenset(),
            bpy=_fake_bpy(),
        )
    assert caught.value.code == "INVALID_ARGUMENT"
    assert owner.width == 1.0

    with pytest.raises(Exception) as caught:
        rna.prepare_assignments(
            owner,
            {"width": float("inf")},
            allowed=frozenset({"width"}),
            object_pointers=frozenset(),
            bpy=_fake_bpy(),
        )
    assert caught.value.code == "INVALID_ARGUMENT"


def test_rna_rejects_traversal_and_resolves_explicit_object_pointer(
    addon_package: str,
) -> None:
    rna = importlib.import_module(f"{addon_package}.tools._rna")
    owner = _Owner()
    target = SimpleNamespace(name="Rig")

    with pytest.raises(Exception) as caught:
        rna.prepare_assignments(
            owner,
            {"target.name": "Rig"},
            allowed=frozenset({"target"}),
            object_pointers=frozenset({"target"}),
            bpy=_fake_bpy({"Rig": target}),
        )
    assert caught.value.code == "INVALID_ARGUMENT"

    assignments = rna.prepare_assignments(
        owner,
        {"target": "Rig"},
        allowed=frozenset({"target"}),
        object_pointers=frozenset({"target"}),
        bpy=_fake_bpy({"Rig": target}),
    )
    rna.apply_assignments(owner, assignments)
    assert owner.target is target


def test_rna_assignment_rolls_back_earlier_properties(addon_package: str) -> None:
    rna = importlib.import_module(f"{addon_package}.tools._rna")
    owner = _FailingOwner()
    assignments = rna.prepare_assignments(
        owner,
        {"width": 4.0, "segments": 4},
        allowed=frozenset({"width", "segments"}),
        object_pointers=frozenset(),
        bpy=_fake_bpy(),
    )

    with pytest.raises(Exception) as caught:
        rna.apply_assignments(owner, assignments)

    assert caught.value.code == "OPERATION_FAILED"
    assert owner.width == 1.0
    assert owner.segments == 2


def test_addon_domain_metadata_is_permissioned_and_checkpointed(
    addon_package: str,
) -> None:
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    permission_module = importlib.import_module(f"{addon_package}.permissions")
    uv = importlib.import_module(f"{addon_package}.tools.uv")
    modifiers = importlib.import_module(f"{addon_package}.tools.modifiers")
    constraints = importlib.import_module(f"{addon_package}.tools.constraints")
    registry = registry_module.ToolRegistry()

    uv.register_tools(registry)
    modifiers.register_tools(registry)
    constraints.register_tools(registry)

    assert set(registry.list_tools()) == {
        "constraint.add",
        "constraint.inspect",
        "constraint.remove",
        "constraint.set",
        "modifier.add",
        "modifier.apply",
        "modifier.inspect",
        "modifier.remove",
        "modifier.set",
        "uv.inspect",
        "uv.pack_islands",
        "uv.smart_project",
        "uv.unwrap",
    }
    for name in registry.list_tools():
        spec = registry.get(name)
        if name.endswith(".inspect"):
            assert spec.permissions == frozenset(
                {permission_module.Permission.INSPECT_SCENE}
            )
        elif name.startswith("uv."):
            assert spec.permissions == frozenset({permission_module.Permission.EDIT_MESH})
        else:
            assert spec.permissions == frozenset(
                {permission_module.Permission.TRANSFORM_OBJECTS}
            )
        assert spec.modifies is (not name.endswith(".inspect"))
        if spec.modifies:
            assert spec.automatic_checkpoint is True


def test_loader_friendly_mcp_definitions_match_declared_names() -> None:
    for module, toolset, permission in (
        (mcp_uv, "uv", "EDIT_MESH"),
        (mcp_modifiers, "modifiers", "TRANSFORM_OBJECTS"),
        (mcp_constraints, "constraints", "TRANSFORM_OBJECTS"),
    ):
        definitions = module.load_definitions()
        assert tuple(item.name for item in definitions) == module.TOOL_NAMES
        assert all(item.toolset == toolset for item in definitions)
        for item in definitions:
            expected = (permission,) if item.modifying else ("INSPECT_SCENE",)
            assert item.required_permissions == expected
    assert {
        "uv.pack_islands",
        "uv.smart_project",
        "uv.unwrap",
    } == mcp_uv.DESTRUCTIVE_TOOL_NAMES
    assert {
        "modifier.apply",
        "modifier.remove",
    } == mcp_modifiers.DESTRUCTIVE_TOOL_NAMES
    assert {"constraint.remove"} == mcp_constraints.DESTRUCTIVE_TOOL_NAMES


def test_mcp_wrappers_forward_explicit_names_and_settings() -> None:
    class Registry:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def call(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
            self.calls.append((name, values))
            return {"ok": True}

    registry = Registry()
    modifier_tools = mcp_modifiers.ModifierTools(registry)  # type: ignore[arg-type]
    constraint_tools = mcp_constraints.ConstraintTools(registry)  # type: ignore[arg-type]
    uv_tools = mcp_uv.UVTools(registry)  # type: ignore[arg-type]

    asyncio.run(
        modifier_tools.modifier_set("Cube", "Bevel", {"width": 0.1, "segments": 3})
    )
    asyncio.run(
        constraint_tools.constraint_add(
            "Camera", "TRACK_TO", settings={"target": "Focus", "track_axis": "TRACK_NEGATIVE_Z"}
        )
    )
    asyncio.run(uv_tools.uv_pack_islands("Cube", selection_id="sel_123"))

    assert registry.calls[0] == (
        "modifier.set",
        {
            "object_name": "Cube",
            "modifier_name": "Bevel",
            "settings": {"width": 0.1, "segments": 3},
        },
    )
    assert registry.calls[1][0] == "constraint.add"
    assert registry.calls[1][1]["settings"]["target"] == "Focus"
    assert registry.calls[2][0] == "uv.pack_islands"
    assert registry.calls[2][1]["object_name"] == "Cube"
    assert registry.calls[2][1]["selection_id"] == "sel_123"


def test_uv_island_connectivity_does_not_treat_seams_as_uv_edits(addon_package: str) -> None:
    uv = importlib.import_module(f"{addon_package}.tools.uv")
    shared_first = {0: (0.0, 0.0), 1: (1.0, 0.0)}
    shared_second = {0: (0.0, 0.0), 1: (1.0, 0.0)}
    connected = {
        0: [(4, False, shared_first)],
        1: [(4, False, shared_second)],
    }
    seam_marked = {
        0: [(4, True, shared_first)],
        1: [(4, False, shared_second)],
    }

    assert uv._islands(connected) == [[0, 1]]
    assert uv._islands(seam_marked) == [[0, 1]]
