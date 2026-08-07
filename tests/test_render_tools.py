from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.tools.render import RenderTools


class RecordingRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, values: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, values))
        return values


def test_render_registration_permissions(addon_package: str) -> None:
    module = importlib.import_module(f"{addon_package}.tools.render")
    permissions = importlib.import_module(f"{addon_package}.permissions")
    registry_module = importlib.import_module(f"{addon_package}.tool_registry")
    registry = registry_module.ToolRegistry()

    module.register_tools(registry)

    assert registry.get("render.inspect").modifies is False
    assert registry.get("render.configure").permissions == {
        permissions.Permission.EDIT_RENDER
    }
    assert registry.get("render.execute").permissions == {
        permissions.Permission.EDIT_RENDER,
        permissions.Permission.CAPTURE_VIEWPORT,
    }
    assert registry.get("render.execute").automatic_checkpoint is False


def test_render_external_path_is_local_absolute_and_format_matched(
    addon_package: str,
    tmp_path: Path,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.render")
    errors = importlib.import_module(f"{addon_package}.errors")

    assert module._validate_external_path(str(tmp_path / "frame.png"), "PNG").is_absolute()
    with pytest.raises(errors.BridgeError):
        module._validate_external_path(str(tmp_path / "frame.jpg"), "PNG")
    with pytest.raises(errors.BridgeError):
        module._validate_external_path("relative.png", "PNG")


def test_render_wrapper_omits_unset_values() -> None:
    registry = RecordingRegistry()
    tools = RenderTools(registry)  # type: ignore[arg-type]

    result = asyncio.run(tools.render_configure("Scene", engine="CYCLES", samples=64))

    assert result == {"scene_name": "Scene", "engine": "CYCLES", "samples": 64}
    assert registry.calls == [("render.configure", result)]


def _fake_render_scene() -> Any:
    image = SimpleNamespace(file_format="PNG", color_mode="RGB")
    render = SimpleNamespace(
        engine="BLENDER_EEVEE_NEXT",
        resolution_x=1920,
        resolution_y=1080,
        resolution_percentage=100,
        fps=24,
        fps_base=1.0,
        film_transparent=False,
        use_file_extension=True,
        filepath="//original.png",
        image_settings=image,
    )
    return SimpleNamespace(
        name="Scene",
        render=render,
        cycles=SimpleNamespace(samples=128),
        eevee=SimpleNamespace(taa_render_samples=64),
    )


def _render_snapshot(scene: Any) -> tuple[Any, ...]:
    render = scene.render
    return (
        render.engine,
        render.resolution_x,
        render.resolution_y,
        render.resolution_percentage,
        render.fps,
        render.fps_base,
        render.film_transparent,
        render.use_file_extension,
        render.filepath,
        render.image_settings.file_format,
        render.image_settings.color_mode,
        scene.cycles.samples,
        scene.eevee.taa_render_samples,
    )


def _enum_values(_owner: Any, property_name: str) -> set[str]:
    return {
        "engine": {"BLENDER_EEVEE_NEXT", "CYCLES"},
        "file_format": {"PNG", "JPEG"},
        "color_mode": {"BW", "RGB", "RGBA"},
    }[property_name]


def test_render_configure_rejects_late_path_without_partial_mutation(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.render")
    scene = _fake_render_scene()
    before = _render_snapshot(scene)
    required: list[Any] = []
    context = SimpleNamespace(require=lambda permission: required.append(permission))
    monkeypatch.setattr(module, "_scene", lambda _: scene)
    monkeypatch.setattr(module, "_enum_values", _enum_values)

    with pytest.raises(Exception) as caught:
        module.configure_render(
            context,
            {
                "scene_name": "Scene",
                "engine": "CYCLES",
                "width": 800,
                "height": 600,
                "resolution_percentage": 50,
                "fps": 29.97,
                "film_transparent": True,
                "use_file_extension": False,
                "file_format": "PNG",
                "color_mode": "RGBA",
                "samples": 512,
                "output_filepath": str(tmp_path / "late-invalid.jpg"),
            },
        )

    assert caught.value.code == "INVALID_ARGUMENT"
    assert len(required) == 1
    assert _render_snapshot(scene) == before


def test_render_configure_checks_external_permission_before_any_mutation(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.render")
    errors = importlib.import_module(f"{addon_package}.errors")
    scene = _fake_render_scene()
    before = _render_snapshot(scene)

    class DenyingContext:
        @staticmethod
        def require(_permission: Any) -> None:
            raise errors.BridgeError(errors.ErrorCode.PERMISSION_DENIED, "denied")

    monkeypatch.setattr(module, "_scene", lambda _: scene)
    monkeypatch.setattr(module, "_enum_values", _enum_values)

    with pytest.raises(Exception) as caught:
        module.configure_render(
            DenyingContext(),
            {
                "scene_name": "Scene",
                "engine": "CYCLES",
                "width": 1280,
                "height": 720,
                "resolution_percentage": 75,
                "fps": 60.0,
                "film_transparent": True,
                "use_file_extension": False,
                "file_format": "PNG",
                "color_mode": "RGBA",
                "samples": 1024,
                "output_filepath": str(tmp_path / "denied.png"),
            },
        )

    assert caught.value.code == "PERMISSION_DENIED"
    assert _render_snapshot(scene) == before


def test_render_configure_prevalidates_format_color_compatibility(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.render")
    scene = _fake_render_scene()
    before = _render_snapshot(scene)
    monkeypatch.setattr(module, "_scene", lambda _: scene)
    monkeypatch.setattr(module, "_enum_values", _enum_values)

    with pytest.raises(Exception) as caught:
        module.configure_render(
            SimpleNamespace(require=lambda _permission: None),
            {
                "scene_name": "Scene",
                "engine": "CYCLES",
                "width": 640,
                "height": 480,
                "file_format": "JPEG",
                "color_mode": "RGBA",
                "samples": 8,
            },
        )

    assert caught.value.code == "INVALID_ARGUMENT"
    assert _render_snapshot(scene) == before


def test_render_configure_rolls_back_if_dynamic_rna_rejects_prepared_enum(
    addon_package: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(f"{addon_package}.tools.render")
    scene = _fake_render_scene()

    class DynamicImageSettings:
        def __init__(self) -> None:
            self._file_format = "PNG"
            self.color_mode = "RGB"

        @property
        def file_format(self) -> str:
            return self._file_format

        @file_format.setter
        def file_format(self, value: str) -> None:
            if value == "CONTEXT_UNAVAILABLE":
                raise TypeError("context-sensitive enum rejected")
            self._file_format = value

    scene.render.image_settings = DynamicImageSettings()
    before = _render_snapshot(scene)

    def enum_values(_owner: Any, property_name: str) -> set[str]:
        if property_name == "file_format":
            return {"PNG", "CONTEXT_UNAVAILABLE"}
        return _enum_values(_owner, property_name)

    monkeypatch.setattr(module, "_scene", lambda _: scene)
    monkeypatch.setattr(module, "_enum_values", enum_values)

    with pytest.raises(TypeError, match="context-sensitive enum rejected"):
        module.configure_render(
            SimpleNamespace(require=lambda _permission: None),
            {
                "scene_name": "Scene",
                "engine": "CYCLES",
                "width": 320,
                "height": 240,
                "resolution_percentage": 25,
                "fps": 48.0,
                "film_transparent": True,
                "use_file_extension": False,
                "file_format": "CONTEXT_UNAVAILABLE",
                "samples": 16,
            },
        )

    assert _render_snapshot(scene) == before
