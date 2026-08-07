from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.animation import (
    ANIMATION_TOOL_NAMES,
    AnimationTools,
    load_animation_definitions,
)


class RecordingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, values))
        return {"method": name, "params": values}


def test_animation_addon_registry_metadata(addon_package: str) -> None:
    animation = importlib.import_module(f"{addon_package}.tools.animation")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry()

    animation.register_tools(registry)

    assert registry.list_tools() == tuple(sorted(ANIMATION_TOOL_NAMES))
    inspect_spec = registry.get("animation.inspect")
    assert inspect_spec.toolset == "animation"
    assert inspect_spec.modifies is False
    assert inspect_spec.permissions == frozenset({permissions.Permission.INSPECT_SCENE})
    for name in ANIMATION_TOOL_NAMES[1:]:
        spec = registry.get(name)
        assert spec.toolset == "animation"
        assert spec.modifies is True
        assert spec.permissions == frozenset({permissions.Permission.EDIT_ANIMATION})
    assert registry.get("animation.set_frame").automatic_checkpoint is False


def test_animation_mcp_definitions_are_loader_ready() -> None:
    definitions = load_animation_definitions()

    assert tuple(item.name for item in definitions) == ANIMATION_TOOL_NAMES
    assert all(item.toolset == "animation" for item in definitions)
    assert definitions[0].modifying is False
    assert definitions[0].required_permissions == ("INSPECT_SCENE",)
    assert all(item.modifying for item in definitions[1:])


def test_animation_wrapper_forwards_explicit_keyframe_scope() -> None:
    registry = RecordingRegistry()
    tools = AnimationTools(registry)  # type: ignore[arg-type]

    result = asyncio.run(
        tools.animation_keyframe_insert(
            "Character",
            'pose.bones["Hand.L"].rotation_euler',
            frame=12.5,
            index=2,
            group="Hand",
            options=["INSERTKEY_NEEDED"],
        )
    )

    assert result["method"] == "animation.keyframe_insert"
    assert registry.calls == [
        (
            "animation.keyframe_insert",
            {
                "object_name": "Character",
                "data_path": 'pose.bones["Hand.L"].rotation_euler',
                "frame": 12.5,
                "index": 2,
                "group": "Hand",
                "options": ["INSERTKEY_NEEDED"],
            },
        )
    ]


def test_set_range_validates_before_mutating_scene(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    animation = importlib.import_module(f"{addon_package}.tools.animation")
    errors = importlib.import_module(f"{addon_package}.errors")
    scene = SimpleNamespace(
        name="Scene",
        frame_start=1,
        frame_end=250,
        use_preview_range=False,
        frame_preview_start=1,
        frame_preview_end=250,
    )
    monkeypatch.setattr(
        animation,
        "require_blender",
        lambda: SimpleNamespace(context=SimpleNamespace(scene=scene)),
    )

    with pytest.raises(errors.BridgeError) as caught:
        animation.set_range(object(), {"start": 20, "end": 10})

    assert caught.value.code == errors.ErrorCode.INVALID_ARGUMENT.value
    assert (scene.frame_start, scene.frame_end) == (1, 250)
    result = animation.set_range(
        object(),
        {
            "start": -10,
            "end": 40,
            "use_preview": True,
            "preview_start": 0,
            "preview_end": 30,
        },
    )
    assert result["frame_start"] == -10
    assert result["frame_end"] == 40
    assert result["preview_start"] == 0
    assert result["preview_end"] == 30


def test_action_inspection_bounds_curves_and_keyframes(addon_package: str) -> None:
    animation = importlib.import_module(f"{addon_package}.tools.animation")

    def point(frame: float) -> Any:
        return SimpleNamespace(co=(frame, frame * 2), interpolation="BEZIER", easing="AUTO")

    curves = [
        SimpleNamespace(
            data_path="location",
            array_index=index,
            group=None,
            mute=False,
            keyframe_points=[point(1), point(2), point(3)],
        )
        for index in range(3)
    ]
    action = SimpleNamespace(
        name="Action",
        frame_range=(1.0, 3.0),
        is_action_layered=False,
        slots=[],
        fcurves=curves,
        layers=[],
    )

    result = animation._inspect_action(action, max_curves=2, max_keyframes=4)

    assert result["fcurve_count"] == 3
    assert len(result["fcurves"]) == 2
    assert [len(item["keyframes"]) for item in result["fcurves"]] == [3, 1]
    assert result["truncated"] == {
        "fcurves": True,
        "keyframes": True,
        "slots": False,
    }


def test_animation_rejects_non_finite_or_oversized_inputs(addon_package: str) -> None:
    animation = importlib.import_module(f"{addon_package}.tools.animation")
    errors = importlib.import_module(f"{addon_package}.errors")

    with pytest.raises(errors.BridgeError):
        animation._frame_param({"frame": float("nan")}, "frame", 1.0)
    with pytest.raises(errors.BridgeError):
        animation._data_path({"data_path": "x" * 513})
